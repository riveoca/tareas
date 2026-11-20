"""Cliente mínimo de las APIs REST v3 y Agile de Jira Cloud."""
from __future__ import annotations

import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from .config import settings
from .dedup import find_duplicate
from .models import Epic, Plan, Task

SUBTASK_STORY_POINTS = 1  # cada subtarea vale 1 punto (decisión del usuario)
STORY_POINT_FIELD_NAMES = ("story point estimate", "story points", "puntos de historia",
                           "estimación de puntos de historia")
START_DATE_FIELD_NAMES = ("start date", "fecha de inicio", "fecha inicio")


class JiraError(Exception):
    field_errors: dict = {}


class JiraClient:
    def __init__(self) -> None:
        if not settings.jira_configured:
            raise JiraError("Faltan JIRA_URL / JIRA_EMAIL / JIRA_API_TOKEN / JIRA_PROJECT_KEY en .env")
        self.project = settings.jira_project_key
        self.http = httpx.Client(
            base_url=f"{settings.jira_url}/rest/api/3",
            auth=(settings.jira_email, settings.jira_api_token),
            headers={"Accept": "application/json"},
            timeout=30,
        )
        self._fields: list[dict] | None = None
        self._me: dict | None = None

    def _request(self, method: str, path: str, **kw) -> dict | list | None:
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = None
            field_errors = body.get("errors", {}) if isinstance(body, dict) else {}
            msgs = (body.get("errorMessages", []) if isinstance(body, dict) else []) + [
                f"{k}: {v}" for k, v in field_errors.items()]
            err = JiraError(f"Jira {r.status_code} en {method} {path}: {'; '.join(msgs) or r.text[:500]}")
            err.field_errors = field_errors
            raise err
        return r.json() if r.content else None

    def _agile(self, method: str, path: str, **kw):
        return self._request(method, f"{settings.jira_url}/rest/agile/1.0{path}", **kw)

    # ---------- Lectura ----------

    def myself(self) -> dict:
        if self._me is None:
            self._me = self._request("GET", "/myself")
        return self._me

    def project_info(self) -> dict:
        return self._request("GET", f"/project/{self.project}")

    def issue_types(self) -> list[dict]:
        """Tipos del proyecto con su nivel: 1 = épica, 0 = estándar, -1 = subtarea."""
        types = self.project_info().get("issueTypes", [])
        return [
            {"id": t["id"], "name": t["name"], "level": t.get("hierarchyLevel", -1 if t.get("subtask") else 0)}
            for t in types
        ]

    def assignable_users(self) -> list[dict]:
        users = self._request("GET", "/user/assignable/search", params={"project": self.project, "maxResults": 200})
        return sorted(
            ({"accountId": u["accountId"], "displayName": u.get("displayName", ""), "email": u.get("emailAddress", "")}
             for u in users if u.get("accountType") == "atlassian" and u.get("active", True)),
            key=lambda u: u["displayName"].lower(),
        )

    def priorities(self) -> list[str]:
        try:
            return [p["name"] for p in self._request("GET", "/priority")]
        except JiraError:
            return []

    def sprints(self) -> list[dict]:
        """Sprints activos y futuros de los tableros del proyecto (vacío si ningún tablero usa sprints).
        Los tableros de proyectos gestionados por el equipo son tipo "simple" y también pueden tener sprints."""
        out: dict[int, dict] = {}
        try:
            boards = self._agile("GET", "/board", params={"projectKeyOrId": self.project}).get("values", [])
        except JiraError:
            return []
        for b in boards:
            if b.get("type") == "kanban":
                continue
            start = 0
            try:
                while True:
                    page = self._agile("GET", f"/board/{b['id']}/sprint",
                                       params={"state": "active,future", "startAt": start, "maxResults": 50})
                    for s in page.get("values", []):
                        out[s["id"]] = {"id": s["id"], "name": s["name"], "state": s.get("state"),
                                        "startDate": (s.get("startDate") or "")[:10],
                                        "endDate": (s.get("endDate") or "")[:10]}
                    if page.get("isLast", True):
                        break
                    start += 50
            except JiraError:
                continue  # tablero sin sprints habilitados
        return sorted(out.values(), key=lambda s: (s["state"] != "active", s["startDate"] or "9", s["name"]))

    def epics(self) -> list[dict]:
        """Épicas no terminadas del proyecto."""
        epic_types = [t["id"] for t in self.issue_types() if t["level"] == 1]
        if not epic_types:
            return []
        jql = (f'project = "{self.project}" AND issuetype in ({", ".join(epic_types)}) '
               f'AND statusCategory != Done ORDER BY created DESC')
        out: list[dict] = []
        token = None
        while len(out) < 500:
            body = {"jql": jql, "fields": ["summary", "status"], "maxResults": 100}
            if token:
                body["nextPageToken"] = token
            page = self._request("POST", "/search/jql", json=body)
            out += [{"key": i["key"], "summary": i["fields"].get("summary", ""),
                     "status": (i["fields"].get("status") or {}).get("name", "")} for i in page.get("issues", [])]
            token = page.get("nextPageToken")
            if not token or page.get("isLast", True):
                break
        return out

    def sprint_issues(self, sprint_id: int) -> dict:
        """Datos de un sprint y sus incidencias (sin épicas) con su fecha de creación, para la gráfica de tareas."""
        s = self._agile("GET", f"/sprint/{sprint_id}")
        local = lambda v: _dt(v).date().isoformat() if v else ""
        sprint = {"id": s["id"], "name": s["name"], "state": s.get("state"),
                  "startDate": local(s.get("startDate")), "endDate": local(s.get("endDate")),
                  "completeDate": local(s.get("completeDate"))}
        epic_types = [t["id"] for t in self.issue_types() if t["level"] == 1]
        jql = f"sprint = {int(sprint_id)}"
        if epic_types:
            jql += f" AND issuetype not in ({', '.join(epic_types)})"
        issues: list[dict] = []
        token = None
        while len(issues) < 5000:
            body = {"jql": jql + " ORDER BY created ASC", "maxResults": 100,
                    "fields": ["summary", "created", "assignee", "status"]}
            if token:
                body["nextPageToken"] = token
            page = self._request("POST", "/search/jql", json=body)
            for i in page.get("issues", []):
                f = i["fields"]
                issues.append({"key": i["key"], "summary": f.get("summary", ""),
                               "created": (f.get("created") or "")[:10],
                               "assignee": (f.get("assignee") or {}).get("displayName"),
                               "status": (f.get("status") or {}).get("name", "")})
            token = page.get("nextPageToken")
            if not token or page.get("isLast", True):
                break
        return {"sprint": sprint, "issues": issues}

    def sprint_burnup(self, sprint_id: int, assignee: str | None = None) -> dict:
        """Informe de trabajo completado (burnup) con los datos del burndown de Jira (API interna greenhopper).
        Por cada evento tras el inicio: totales de puntos creados (alcance = tareas en el sprint) y cerrados
        (en el sprint y hechas; relativo al inicio, así empieza en 0). Tiempos en ms epoch.
        Con assignee (nombre visible, o "__none") solo cuentan las tareas del sprint asignadas hoy a esa persona."""
        keys = None
        if assignee:
            keys = {i["key"] for i in self.sprint_issues(sprint_id)["issues"]
                    if (i["assignee"] or "__none") == assignee}
        s = self._agile("GET", f"/sprint/{sprint_id}")
        d = self._request("GET", f"{settings.jira_url}/rest/greenhopper/1.0/rapid/charts/scopechangeburndownchart.json",
                          params={"rapidViewId": s["originBoardId"], "sprintId": sprint_id})
        # Esta API da las horas locales del tablero escritas como si fueran UTC: se pasan a epoch real
        tz = ZoneInfo((d.get("workRateData") or {}).get("timezone") or "UTC")
        real = lambda ms: int(datetime.fromtimestamp(ms / 1000, timezone.utc).replace(tzinfo=tz).timestamp() * 1000)
        start, end = d["startTime"], d["endTime"]
        now = d.get("completeTime") or d["now"]
        summaries = d.get("issueToSummary", {})
        state: dict[str, dict] = defaultdict(lambda: {"in": False, "pts": None, "done": False})
        scope = lambda st: (st["pts"] or 0) if st["in"] else 0
        closed = lambda st: (st["pts"] or 0) if st["in"] and st["done"] else 0
        tot = {"scope": 0.0, "closed": 0.0}
        base, events = None, []
        for t in sorted(d.get("changes", {}), key=int):
            ts = int(t)
            if ts > now:
                break
            if ts > start and base is None:
                base = dict(tot)
            for e in d["changes"][t]:
                if keys is not None and e["key"] not in keys:
                    continue
                st = state[e["key"]]
                was, s0, c0 = dict(st), scope(st), closed(st)
                if "added" in e:
                    st["in"] = bool(e["added"])
                if "statC" in e:
                    st["pts"] = e["statC"].get("newValue")
                if "column" in e:
                    st["done"] = not e["column"].get("notDone", True)
                tot["scope"] += scope(st) - s0
                tot["closed"] += closed(st) - c0
                if ts <= start:
                    continue
                if st["in"] != was["in"]:
                    kind = "Tarea añadida" if st["in"] else "Tarea quitada"
                elif st["done"] != was["done"] and st["in"]:
                    kind = "Tarea cerrada" if st["done"] else "Tarea reabierta"
                elif st["pts"] != was["pts"] and st["in"]:
                    kind = f"Cambio de puntos {_num(was['pts'])} → {_num(st['pts'])}"
                else:
                    continue
                events.append({"t": real(ts), "key": e["key"], "summary": summaries.get(e["key"], ""), "event": kind,
                               "scope": tot["scope"], "closed": tot["closed"]})
        if base is None:
            base = dict(tot)
        for ev in events:  # cerrados relativos al inicio del sprint
            ev["closed"] -= base["closed"]
        # Si el sprint sigue abierto pasada su fecha de fin (o se cerró tarde), el eje llega hasta hoy / el cierre
        return {"name": s["name"], "state": s.get("state"), "start": real(start), "end": real(max(end, now)),
                "planned_end": real(end), "now": real(now), "finished": bool(d.get("completeTime")),
                "field": (d.get("statisticField") or {}).get("name", "Puntos de historia"),
                "assignee": assignee, "start_scope": base["scope"], "closed_before": base["closed"], "events": events}

    def performance(self) -> dict:
        """Histórico de todos los sprints (cerrados y activo) para el desempeño individual comparado.
        Cada incidencia hecha (sin épicas) cuenta en el último sprint en que estuvo; si nunca tuvo sprint, en el
        sprint cuyo periodo contiene su fecha de resolución. Devuelve por persona y sprint puntos y tareas cerradas."""
        boards = [b for b in self._agile("GET", "/board", params={"projectKeyOrId": self.project}).get("values", [])
                  if b.get("type") != "kanban"]
        sprints: dict[int, dict] = {}
        for b in boards:
            start = 0
            try:
                while True:
                    page = self._agile("GET", f"/board/{b['id']}/sprint", params={"startAt": start, "maxResults": 50})
                    for s in page.get("values", []):
                        if s.get("state") == "future" or not s.get("startDate"):
                            continue
                        sprints[s["id"]] = {"id": s["id"], "name": s["name"], "state": s.get("state"),
                                            "start": _dt(s["startDate"]).date().isoformat(),
                                            "end": _dt(s.get("completeDate") or s["endDate"]).date().isoformat()}
                    if page.get("isLast", True):
                        break
                    start += 50
            except JiraError:
                continue
        order = sorted(sprints.values(), key=lambda s: (s["start"], s["id"]))
        pos = {s["id"]: n for n, s in enumerate(order)}

        sp = self.story_points_field()
        sprint_field = self.sprint_field()
        epic_types = [t["id"] for t in self.issue_types() if t["level"] == 1]
        jql = f'project = "{self.project}"'
        if epic_types:
            jql += f" AND issuetype not in ({', '.join(epic_types)})"
        fields = ["assignee", "status", "resolutiondate", "parent"] + [f for f in (sp, sprint_field) if f]
        rows: dict[tuple, dict] = defaultdict(lambda: {"points": 0.0, "tasks": 0, "epics": {}})
        open_: dict[str, dict] = defaultdict(lambda: {"points": 0.0, "tasks": 0})
        outside: dict[str, dict] = defaultdict(lambda: {"points": 0.0, "tasks": 0})
        # Tramos por fecha de creación (cada 3 sprints) leídos en paralelo: recorrer todo el proyecto es lento
        cuts = [s["start"] for s in order[::3]][1:]
        ranges = [(a, b) for a, b in zip([None] + cuts, cuts + [None])]

        def fetch(rng):
            a, b = rng
            q = jql + (f' AND created >= "{a}"' if a else "") + (f' AND created < "{b}"' if b else "")
            out, token = [], None
            while len(out) < 20000:
                body = {"jql": q + " ORDER BY created ASC", "maxResults": 100, "fields": fields}
                if token:
                    body["nextPageToken"] = token
                page = self._request("POST", "/search/jql", json=body)
                out += page.get("issues", [])
                token = page.get("nextPageToken")
                if not token or page.get("isLast", True):
                    return out
            return out

        with ThreadPoolExecutor(max_workers=8) as pool:
            issues = [i for chunk in pool.map(fetch, ranges) for i in chunk]
        for i in issues:
            f = i["fields"]
            who = (f.get("assignee") or {}).get("displayName") or "Sin responsable"
            pts = float(f.get(sp) or 0) if sp else 0.0
            if ((f.get("status") or {}).get("statusCategory") or {}).get("key") != "done":
                open_[who]["points"] += pts
                open_[who]["tasks"] += 1
                continue
            ids = [s["id"] for s in (f.get(sprint_field) or []) if s.get("id") in pos] if sprint_field else []
            sid = max(ids, key=pos.get) if ids else None
            if sid is None and f.get("resolutiondate"):
                day = _dt(f["resolutiondate"]).date().isoformat()
                sid = next((s["id"] for s in order if s["start"] <= day <= s["end"]), None)
            if sid is None:
                outside[who]["points"] += pts
                outside[who]["tasks"] += 1
                continue
            # Proyecto = épica padre (las subtareas cuelgan de una tarea, no de la épica)
            par = f.get("parent") or {}
            level = (((par.get("fields") or {}).get("issuetype") or {}).get("hierarchyLevel"))
            epic = (par.get("fields") or {}).get("summary") if level == 1 else None
            r = rows[(who, sid)]
            r["points"] += pts
            r["tasks"] += 1
            e = r["epics"].setdefault(epic or "Sin épica", {"points": 0.0, "tasks": 0})
            e["points"] += pts
            e["tasks"] += 1
        people = sorted({w for w, _ in rows} | set(outside) | set(open_))
        return {
            "sprints": order,
            "field": next((f.get("name") for f in self._fields if f["id"] == sp), "Puntos de historia"),
            "people": [{"name": w,
                        "by_sprint": {str(s): rows[(w, s)] for (ww, s) in list(rows) if ww == w},
                        "outside": outside.get(w, {"points": 0.0, "tasks": 0}),
                        "open": open_.get(w, {"points": 0.0, "tasks": 0})} for w in people],
            "issues": len(issues),
            "generated": datetime.now(timezone.utc).isoformat(),
        }

    def _field_by_name(self, configured: str, names: tuple[str, ...]) -> str | None:
        if configured:
            return configured
        if self._fields is None:
            self._fields = self._request("GET", "/field")
        for f in self._fields:
            if f.get("name", "").strip().lower() in names:
                return f["id"]
        return None

    def story_points_field(self) -> str | None:
        return self._field_by_name(settings.jira_story_points_field, STORY_POINT_FIELD_NAMES)

    def start_date_field(self) -> str | None:
        return self._field_by_name(settings.jira_start_date_field, START_DATE_FIELD_NAMES)

    def metadata(self) -> dict:
        """Todo lo que la app y la IA necesitan saber del proyecto."""
        return {
            "project": self.project,
            "project_name": self.project_info().get("name", self.project),
            "base_url": settings.jira_url,
            "issue_types": self.issue_types(),
            "users": self.assignable_users(),
            "priorities": self.priorities(),
            "sprints": self.sprints(),
            "me": (me := self.myself()).get("displayName"),
            "me_id": me.get("accountId"),
            "epics": self.epics(),
            "stories": self.stories(),
            "story_points_field": self.story_points_field(),
            "start_date_field": self.start_date_field(),
        }

    def stories(self) -> list[dict]:
        """Historias abiertas del proyecto (espejo de las tareas del Planner) con su épica y los títulos de sus
        subtareas: la IA cuelga de ellas el trabajo como subtareas."""
        types = [t["id"] for t in self.issue_types() if t["level"] == 0 and re.match(r"(?i)histor|story", t["name"])]
        if not types:
            return []
        jql = (f'project = "{self.project}" AND issuetype in ({", ".join(types)}) AND statusCategory != Done '
               f'ORDER BY created ASC')
        out = []
        for i in self._search(jql, ["summary", "description", "parent", "assignee", "subtasks", "status"], 1000):
            f, par = i["fields"], i["fields"].get("parent") or {}
            out.append({"key": i["key"], "summary": f.get("summary", ""), "epic_key": par.get("key"),
                        "description": adf_to_text(f.get("description"))[:200],
                        "epic": (par.get("fields") or {}).get("summary"), "status": (f.get("status") or {}).get("name"),
                        "assignee": (f.get("assignee") or {}).get("displayName"),
                        "subtasks": [{"key": s["key"], "summary": s["fields"]["summary"],
                                      "done": ((s["fields"].get("status") or {}).get("statusCategory") or {}).get("key") == "done"}
                                     for s in f.get("subtasks") or []]})
        return out

    def recent_subtasks(self, days: int = 180) -> list[dict]:
        """Subtareas creadas en los últimos `days` días, de cualquier Historia (también cerradas): para no repetirlas."""
        jql = f'project = "{self.project}" AND issuetype in subTaskIssueTypes() AND created >= -{days}d'
        return [{"key": i["key"], "summary": i["fields"].get("summary", ""),
                 "parent": (i["fields"].get("parent") or {}).get("key")}
                for i in self._search(jql, ["summary", "parent"], 3000)]

    def subtasks_of(self, key: str) -> list[dict]:
        raw = self._request("GET", f"/issue/{key}", params={"fields": "subtasks"})
        return [{"key": s["key"], "summary": s["fields"]["summary"], "parent": key}
                for s in raw["fields"].get("subtasks") or []]

    # ---------- Mis tareas (Historias y subtareas de una persona) ----------

    def _search(self, jql: str, fields: list[str], limit: int = 2000) -> list[dict]:
        out, token = [], None
        while len(out) < limit:
            body = {"jql": jql, "maxResults": 100, "fields": fields}
            if token:
                body["nextPageToken"] = token
            page = self._request("POST", "/search/jql", json=body)
            out += page.get("issues", [])
            token = page.get("nextPageToken")
            if not token or page.get("isLast", True):
                break
        return out

    def sprint_field(self) -> str | None:
        if self._fields is None:
            self._fields = self._request("GET", "/field")
        return next((f["id"] for f in self._fields
                     if (f.get("schema") or {}).get("custom") == "com.pyxis.greenhopper.jira:gh-sprint"), None)

    def _item_fields(self) -> list[str]:
        return ["summary", "status", "issuetype", "assignee", "creator", "duedate", "description", "parent",
                "updated"] + [f for f in (self.start_date_field(), self.sprint_field()) if f]

    def _item(self, i: dict, start_field: str | None, me_id: str) -> dict:
        f = i["fields"]
        # Sprint de la incidencia: el activo, si no el próximo; si solo estuvo en sprints cerrados, es backlog
        spr = [s for s in (f.get(self.sprint_field()) or []) if s.get("state") in ("active", "future")]
        spr.sort(key=lambda s: (s["state"] != "active", s.get("startDate") or "9"))
        sprint = {"id": spr[0]["id"], "name": spr[0]["name"], "state": spr[0]["state"],
                  "start": (spr[0].get("startDate") or "")[:10], "end": (spr[0].get("endDate") or "")[:10]} if spr else None
        t = f.get("issuetype") or {}
        st = f.get("status") or {}
        who = lambda u: (u or {}).get("accountId")
        return {
            "key": i["key"], "type": t.get("name", ""), "subtask": bool(t.get("subtask")),
            "summary": f.get("summary", ""), "status": st.get("name", ""),
            "category": (st.get("statusCategory") or {}).get("key", "new"),
            "assignee_id": who(f.get("assignee")), "assignee": (f.get("assignee") or {}).get("displayName"),
            "creator_id": who(f.get("creator")), "creator": (f.get("creator") or {}).get("displayName"),
            "start_date": f.get(start_field) if start_field else None, "due_date": f.get("duedate"),
            "description": adf_to_text(f.get("description")), "parent": (f.get("parent") or {}).get("key"),
            "updated": f.get("updated"), "mine": who(f.get("creator")) == me_id, "sprint": sprint,
        }

    def my_work(self, account_id: str, include_done: bool = False) -> dict:
        """Historias (tipos estándar) y subtareas asignadas a una persona, con las Historias y épicas que las
        contienen (aunque no sean suyas) y el avance de cada Historia contando todas sus subtareas."""
        me_id = self.myself()["accountId"]
        start_field = self.start_date_field()
        epic_types = [t["id"] for t in self.issue_types() if t["level"] == 1]
        fields = self._item_fields()
        jql = f'project = "{self.project}" AND assignee = "{account_id}"'
        if epic_types:
            jql += f" AND issuetype not in ({', '.join(epic_types)})"
        jql += " AND (statusCategory != Done OR resolved >= -14d)" if include_done else " AND statusCategory != Done"
        items = {i["key"]: self._item(i, start_field, me_id) for i in self._search(jql + " ORDER BY duedate ASC", fields)}
        for it in items.values():
            it["assigned"] = True
        # Historias que contienen subtareas de la persona pero están asignadas a otra
        missing = sorted({it["parent"] for it in items.values() if it["subtask"] and it["parent"] not in items})
        for i in range(0, len(missing), 100):
            for raw in self._search(f"key in ({','.join(missing[i:i + 100])})", fields):
                items[raw["key"]] = {**self._item(raw, start_field, me_id), "assigned": False}
        parents = [k for k, it in items.items() if not it["subtask"]]
        progress = {k: {"done": 0, "total": 0} for k in parents}
        for i in range(0, len(parents), 100):
            for raw in self._search(f"parent in ({','.join(parents[i:i + 100])})", fields):
                p = progress[raw["fields"]["parent"]["key"]]
                p["total"] += 1
                p["done"] += ((raw["fields"].get("status") or {}).get("statusCategory") or {}).get("key") == "done"
                # Las subtareas ya cerradas de la persona también se devuelven, para verlas (y reabrirlas) en su Historia
                if raw["key"] not in items and (raw["fields"].get("assignee") or {}).get("accountId") == account_id:
                    items[raw["key"]] = {**self._item(raw, start_field, me_id), "assigned": True}
        for k in parents:
            items[k]["progress"] = progress[k]
        epic_keys = sorted({items[k]["parent"] for k in parents if items[k]["parent"]})
        epics = {raw["key"]: raw["fields"]["summary"]
                 for i in range(0, len(epic_keys), 100)
                 for raw in self._search(f"key in ({','.join(epic_keys[i:i + 100])})", ["summary"])}
        return {"items": list(items.values()), "epics": epics, "me_id": me_id}

    def get_item(self, key: str) -> dict:
        start_field = self.start_date_field()
        fields = self._item_fields()
        raw = self._request("GET", f"/issue/{key}", params={"fields": ",".join(fields)})
        return self._item(raw, start_field, self.myself()["accountId"])

    def edit_item(self, key: str, changes: dict) -> dict:
        """Cambia campos básicos (summary, description, start_date, due_date, assignee_id, parent) y el sprint
        (`sprint`: id de un sprint activo/futuro, o null para devolverla al backlog; sus subtareas la siguen)."""
        changes = dict(changes)
        if "sprint" in changes:
            sprint = changes.pop("sprint")
            if sprint:
                self._agile("POST", f"/sprint/{int(sprint)}/issue", json={"issues": [key]})
            else:
                self._agile("POST", "/backlog/issue", json={"issues": [key]})
            if not changes:
                return self.get_item(key)
        start_field = self.start_date_field()
        names = {"summary": "summary", "due_date": "duedate", "start_date": start_field, "parent": "parent",
                 "assignee_id": "assignee", "description": "description"}
        fields = {}
        for k, v in changes.items():
            if k not in names or not names[k]:
                raise JiraError(f"Campo no editable: {k}")
            if k == "description":
                v = to_adf(v or "")
            elif k == "assignee_id":
                v = {"accountId": v} if v else None
            elif k == "parent":
                v = {"key": v} if v else None
            elif k in ("start_date", "due_date"):
                v = v or None
            fields[names[k]] = v
        try:
            self._request("PUT", f"/issue/{key}", json={"fields": fields})
        except JiraError as e:
            if "Request blocked" in str(e) and "description" in fields:
                # El WAF de Jira rechaza textos como sleep(1) o alert(): se reescriben sin paréntesis
                text = re.sub(r"\b(sleep|alert|eval|exec|benchmark|select|union|script)\s*\(([^)]*)\)", r"\1 \2",
                              changes["description"], flags=re.I)
                fields["description"] = to_adf(text)
                self._request("PUT", f"/issue/{key}", json={"fields": fields})
            else:
                raise
        return self.get_item(key)

    def set_status(self, key: str, category: str) -> dict:
        """Lleva la incidencia a un estado de la categoría pedida (new, indeterminate o done) con sus
        transiciones; si no hay una directa, pasa antes por "en curso"."""
        for _ in range(3):
            if self.get_item(key)["category"] == category:
                return self.get_item(key)
            trs = self._request("GET", f"/issue/{key}/transitions")["transitions"]
            cat = lambda t: ((t.get("to") or {}).get("statusCategory") or {}).get("key")
            t = next((t for t in trs if cat(t) == category), None) or next(
                (t for t in trs if cat(t) == "indeterminate"), None)
            if not t:
                break
            self._request("POST", f"/issue/{key}/transitions", json={"transition": {"id": t["id"]}})
        item = self.get_item(key)
        if item["category"] != category:
            raise JiraError(f"{key}: el flujo de Jira no permite llegar a ese estado desde «{item['status']}»")
        return item

    def create_subtask(self, parent: str, summary: str, assignee_id: str | None, start_date: str | None,
                       due_date: str | None, description: str = "") -> dict:
        sub_type = next((t for t in self.issue_types() if t["level"] == -1), None)
        if not sub_type:
            raise JiraError("El proyecto no tiene tipo Subtarea")
        start_field = self.start_date_field()
        fields = {"project": {"key": self.project}, "issuetype": {"id": sub_type["id"]}, "parent": {"key": parent},
                  "summary": summary[:250], "description": to_adf(description), "duedate": due_date or None}
        if assignee_id:
            fields["assignee"] = {"accountId": assignee_id}
        if start_field and start_date:
            fields[start_field] = start_date
        sp_field = self.story_points_field()
        if sp_field:
            fields[sp_field] = SUBTASK_STORY_POINTS
        key, _ = self._save_issue(None, fields, tuple(f for f in ("duedate", start_field, sp_field) if f))
        return self.get_item(key)

    # ---------- Escritura ----------

    def _save_issue(self, key: str | None, fields: dict, optional: tuple[str, ...]) -> tuple[str, list[str]]:
        """Crea (key=None) o actualiza una incidencia. Si Jira rechaza un campo opcional
        (no está en la pantalla del proyecto, p.ej. prioridad o fecha de inicio), se reintenta sin él."""
        warnings: list[str] = []
        for _ in range(len(optional) + 1):
            try:
                if key:
                    self._request("PUT", f"/issue/{key}", json={"fields": fields})
                    return key, warnings
                return self._request("POST", "/issue", json={"fields": fields})["key"], warnings
            except JiraError as e:
                bad = [f for f in e.field_errors if f in optional and f in fields]
                if not bad:
                    raise
                for f in bad:
                    fields.pop(f)
                    warnings.append(f"campo '{f}' omitido: {e.field_errors[f]}")
        raise JiraError("No se pudo guardar la incidencia")

    def _fields_for(self, item: Epic | Task, issue_type_id: str, sp_field: str | None,
                    start_field: str | None) -> tuple[dict, tuple[str, ...]]:
        fields: dict = {"summary": item.summary[:250], "description": to_adf(item.description)}
        if not item.jira_key:
            fields |= {"project": {"key": self.project}, "issuetype": {"id": issue_type_id}}
        if isinstance(item, Task):
            if item.assignee_id:
                fields["assignee"] = {"accountId": item.assignee_id}
            elif item.jira_key:
                fields["assignee"] = None  # desasignar si se quitó en la app
            if item.priority:
                fields["priority"] = {"name": item.priority}
            if item.story_points is not None and sp_field:
                fields[sp_field] = item.story_points
            if item.due_date or item.jira_key:
                fields["duedate"] = item.due_date or None
            if start_field and (item.start_date or item.jira_key):
                fields[start_field] = item.start_date or None
        optional = tuple(f for f in ("priority", "duedate", sp_field, start_field) if f)
        return fields, optional

    def push_plan(self, plan: Plan, only_ids: set[str] | None = None) -> list[dict]:
        """Sube el plan a Jira: crea lo nuevo y actualiza lo que ya tiene clave.
        Con only_ids solo se suben esas tareas (y sus épicas). Guarda las claves en el plan."""
        types = self.issue_types()
        by_name = {t["name"].lower(): t for t in types}
        epic_type = next((t for t in types if t["level"] == 1), None)
        std_types = [t for t in types if t["level"] == 0]
        sub_type = next((t for t in types if t["level"] == -1), None)
        if not epic_type or not std_types:
            raise JiraError("El proyecto no tiene tipo Épica o tipos estándar disponibles")
        sp_field, start_field = self.story_points_field(), self.start_date_field()
        results: list[dict] = []
        by_sprint: dict[int, list[Task]] = defaultdict(list)
        live_subs: dict[str, list[dict]] = {}  # subtareas actuales de cada Historia, leídas al subir

        def record(item, kind, ok, warnings=None, error=None, created=False):
            results.append({
                "id": item.id, "kind": kind, "summary": item.summary, "key": item.jira_key,
                "url": f"{settings.jira_url}/browse/{item.jira_key}" if item.jira_key else None,
                "ok": ok, "created": created, "warnings": warnings or [], "error": error,
            })

        for epic in plan.epics:
            tasks = [t for t in epic.tasks if only_ids is None or t.id in only_ids]
            if only_ids is not None and not tasks:
                continue
            if epic.linked and not epic.jira_key:
                record(epic, "epic", False, error="Épica de Jira sin clave")
                continue
            if not epic.linked and (only_ids is None or not epic.jira_key):
                try:
                    fields, opt = self._fields_for(epic, epic_type["id"], sp_field, start_field)
                    created = epic.jira_key is None
                    epic.jira_key, warns = self._save_issue(epic.jira_key, fields, opt)
                    record(epic, "epic", True, warns, created=created)
                except (JiraError, httpx.HTTPError) as e:
                    record(epic, "epic", False, error=str(e))
                    continue  # sin épica no se crean sus hijas

            for task in tasks:
                as_sub = bool(task.parent_key and sub_type)
                t_type = sub_type if as_sub else by_name.get((task.issue_type or "").lower())
                if not t_type or (not as_sub and t_type["level"] != 0):
                    t_type = std_types[0]
                try:
                    if as_sub and task.jira_key is None:
                        # Última comprobación en Jira: alguien pudo crearla desde que se desglosó
                        if task.parent_key not in live_subs:
                            live_subs[task.parent_key] = self.subtasks_of(task.parent_key)
                        same = find_duplicate(task.summary, task.parent_key, live_subs[task.parent_key], epic.summary)
                        if same:
                            record(task, "task", False, error=f"Ya existe en {task.parent_key} como {same['key']} "
                                                              f"«{same['summary']}»: no se creó. Bórrala de la lista.")
                            continue
                    if as_sub:  # la subtarea hereda el sprint de su Historia y vale 1 punto
                        task.sprint_id = task.sprint_name = None
                        task.story_points = SUBTASK_STORY_POINTS
                    fields, opt = self._fields_for(task, t_type["id"], sp_field, start_field)
                    fields["parent"] = {"key": task.parent_key if as_sub else epic.jira_key}
                    created = task.jira_key is None
                    task.jira_key, warns = self._save_issue(task.jira_key, fields, opt)
                    if as_sub and created:
                        live_subs[task.parent_key].append({"key": task.jira_key, "summary": task.summary,
                                                           "parent": task.parent_key})
                    if task.done:
                        try:
                            self.set_status(task.jira_key, "done")
                        except JiraError as e:
                            warns.append(f"no se pudo pasar a Finalizada: {e}")
                    record(task, "task", True, warns, created=created)
                    if task.sprint_id and not as_sub:
                        by_sprint[task.sprint_id].append(task)
                except (JiraError, httpx.HTTPError) as e:
                    record(task, "task", False, error=str(e))
                time.sleep(0.1)  # amable con el rate limit

        # Mover al sprint (la API agile admite hasta 50 incidencias por llamada)
        for sprint_id, tasks in by_sprint.items():
            for i in range(0, len(tasks), 50):
                chunk = tasks[i:i + 50]
                try:
                    self._agile("POST", f"/sprint/{sprint_id}/issue", json={"issues": [t.jira_key for t in chunk]})
                except (JiraError, httpx.HTTPError) as e:
                    for r in results:
                        if r["id"] in {t.id for t in chunk}:
                            r["warnings"].append(f"no se pudo mover al sprint: {e}")
        return results


def _num(v) -> str:
    return "—" if v is None else f"{v:g}"


def _dt(value: str) -> datetime:
    """Fecha ISO de Jira (con Z o -0500) a hora local."""
    return datetime.fromisoformat(value).astimezone()


def adf_to_text(doc: dict | None) -> str:
    """Atlassian Document Format -> texto plano (párrafos, viñetas "- " y saltos); inverso aproximado de to_adf."""
    if not doc:
        return ""

    def inline(n: dict) -> str:
        if n.get("type") == "text":
            return n.get("text", "")
        if n.get("type") == "hardBreak":
            return "\n"
        if n.get("type") in ("mention", "emoji", "status", "date"):
            return (n.get("attrs") or {}).get("text", "")
        if n.get("type") == "inlineCard":
            return (n.get("attrs") or {}).get("url", "")
        return "".join(inline(c) for c in n.get("content", []))

    def block(n: dict, prefix: str = "") -> list[str]:
        t = n.get("type")
        if t in ("bulletList", "orderedList"):
            return [line for item in n.get("content", []) for line in block(item, "- ")]
        if t == "listItem":
            lines = [line for c in n.get("content", []) for line in block(c)]
            return [prefix + lines[0]] + ["  " + x for x in lines[1:]] if lines else []
        if t in ("paragraph", "heading", "codeBlock", "blockquote", "panel") or "content" not in n:
            text = inline(n) if t != "blockquote" and t != "panel" else "\n".join(
                line for c in n.get("content", []) for line in block(c))
            return [prefix + text] if text else []
        return [line for c in n.get("content", []) for line in block(c)]

    out: list[str] = []
    for n in doc.get("content", []):
        lines = block(n)
        if out and lines and n.get("type") not in ("bulletList", "orderedList"):
            out.append("")
        out += lines
    return "\n".join(out).strip()


def to_adf(text: str) -> dict:
    """Texto plano -> Atlassian Document Format (párrafos y viñetas simples)."""
    content: list[dict] = []
    bullets: list[dict] = []

    def flush_bullets():
        if bullets:
            content.append({"type": "bulletList", "content": list(bullets)})
            bullets.clear()

    for block in (text or "").split("\n"):
        line = block.rstrip()
        if not line.strip():
            flush_bullets()
            continue
        stripped = line.lstrip()
        if stripped[:2] in ("- ", "* ", "• "):
            bullets.append({"type": "listItem", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": stripped[2:]}]}]})
        else:
            flush_bullets()
            content.append({"type": "paragraph", "content": [{"type": "text", "text": line}]})
    flush_bullets()
    return {"type": "doc", "version": 1, "content": content}
