"""Cliente mínimo de las APIs REST v3 y Agile de Jira Cloud."""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from .config import settings
from .models import Epic, Plan, Task

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
        return self._request("GET", "/myself")

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
            "me": self.myself().get("displayName"),
            "epics": self.epics(),
            "story_points_field": self.story_points_field(),
            "start_date_field": self.start_date_field(),
        }

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
        if not epic_type or not std_types:
            raise JiraError("El proyecto no tiene tipo Épica o tipos estándar disponibles")
        sp_field, start_field = self.story_points_field(), self.start_date_field()
        results: list[dict] = []
        by_sprint: dict[int, list[Task]] = defaultdict(list)

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
                t_type = by_name.get((task.issue_type or "").lower())
                if not t_type or t_type["level"] != 0:
                    t_type = std_types[0]
                try:
                    fields, opt = self._fields_for(task, t_type["id"], sp_field, start_field)
                    fields["parent"] = {"key": epic.jira_key}
                    created = task.jira_key is None
                    task.jira_key, warns = self._save_issue(task.jira_key, fields, opt)
                    record(task, "task", True, warns, created=created)
                    if task.sprint_id:
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
