"""API web + interfaz (FastAPI)."""
from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import llm, store
from .config import settings
from .jira import JiraClient, JiraError
from .models import Defaults, Plan, Workspace

app = FastAPI(title="Tareas IA → Jira")
STATIC = Path(__file__).parent / "static"
ALLOWED_EXT = {".txt", ".md", ".log", ".csv", ".json"}
WORKSPACE_ID = "main"  # un único espacio de trabajo

_meta_cache: dict = {"at": 0.0, "data": None, "error": None}


def jira_meta(refresh: bool = False) -> dict | None:
    """Metadatos del proyecto Jira (equipo, tipos, sprints…), cacheados 10 min."""
    if refresh or time.time() - _meta_cache["at"] > 600:
        try:
            _meta_cache.update(data=JiraClient().metadata(), error=None)
        except Exception as e:  # la app funciona sin Jira; solo no podrá subir
            _meta_cache.update(data=None, error=str(e))
        _meta_cache["at"] = time.time()
    return _meta_cache["data"]


def _get() -> Workspace:
    return store.get_session(WORKSPACE_ID) or store.save_session(Workspace(id=WORKSPACE_ID))


@app.get("/")
def index():
    # Sin caché: tras actualizar la app el navegador debe cargar la interfaz nueva, no una copia guardada
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/config")
def config(refresh: bool = False):
    meta = jira_meta(refresh)
    return {
        "jira": meta,
        "jira_error": _meta_cache["error"],
        "default_provider": settings.llm_provider,
        "providers": {
            "claude_code": llm.claude_code_available(),
            "claude": bool(os.getenv("ANTHROPIC_API_KEY")),
            "ollama": True,
        },
        "claude_model": settings.claude_model,
        "ollama_model": settings.ollama_model,
    }


@app.get("/api/state")
def state():
    return _get()


def _run_breakdown(content: str, provider: str, filename: str | None) -> dict:
    ws = _get()
    if not content.strip():
        raise HTTPException(400, "No hay contenido que desglosar")
    try:
        note, ws.plan, added, dupes, to_close = llm.breakdown(ws.plan, ws.defaults, _fresh_meta(), content, provider, filename)
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    store.save_session(ws)
    return {"workspace": ws, "note": note, "added": added, "skipped": len(dupes), "duplicates": dupes, "to_close": to_close}


def _fresh_meta() -> dict | None:
    """Metadatos con las Historias y subtareas leídas de Jira en este momento (la caché puede tener 10 min):
    así la IA y la deduplicación ven también lo que se creó hace un rato."""
    meta = jira_meta()
    if not meta:
        return meta
    try:
        j = JiraClient()
        return {**meta, "stories": j.stories(), "recent_subtasks": j.recent_subtasks()}
    except Exception:  # sin conexión momentánea: se usa la caché
        return meta


class TextIn(BaseModel):
    text: str
    provider: str = "claude"


@app.post("/api/breakdown/text")
def breakdown_text(body: TextIn):
    return _run_breakdown(body.text, body.provider, None)


@app.post("/api/breakdown/file")
async def breakdown_file(file: UploadFile, provider: str = Form("claude")):
    if Path(file.filename or "").suffix.lower() not in ALLOWED_EXT:
        raise HTTPException(400, f"{file.filename}: solo se aceptan {', '.join(sorted(ALLOWED_EXT))}")
    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(400, f"{file.filename}: máximo 2 MB")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return _run_breakdown(text, provider, file.filename)


@app.put("/api/plan")
def save_plan(plan: Plan):
    ws = _get()
    ws.plan = plan
    return store.save_session(ws)


@app.put("/api/defaults")
def save_defaults(defaults: Defaults):
    ws = _get()
    ws.defaults = defaults
    return store.save_session(ws)


@app.get("/api/sprint/{sprint_id}/issues")
def sprint_issues(sprint_id: int):
    """Incidencias de un sprint con su fecha de creación (para la gráfica de avance)."""
    try:
        return JiraClient().sprint_issues(sprint_id)
    except (JiraError, httpx.HTTPError) as e:
        raise HTTPException(502, str(e))


@app.get("/api/sprint/{sprint_id}/burnup")
def sprint_burnup(sprint_id: int, assignee: str | None = None):
    """Informe de trabajo completado (puntos creados vs. cerrados) con los datos de Jira; con assignee, el personal."""
    try:
        return JiraClient().sprint_burnup(sprint_id, assignee or None)
    except (JiraError, httpx.HTTPError) as e:
        raise HTTPException(502, str(e))


_perf_cache: dict = {"at": 0.0, "data": None}


@app.get("/api/performance")
def performance(refresh: bool = False):
    """Desempeño histórico por persona y sprint (pesado: recorre todo el proyecto; se guarda 10 minutos)."""
    if refresh or not _perf_cache["data"] or time.time() - _perf_cache["at"] > 600:
        try:
            _perf_cache["data"] = JiraClient().performance()
        except (JiraError, httpx.HTTPError) as e:
            raise HTTPException(502, str(e))
        _perf_cache["at"] = time.time()
    return _perf_cache["data"]


# ---------- Mis tareas: Historias y subtareas en Jira (lectura y edición directa) ----------

def _jira_call(fn, *args):
    try:
        return fn(*args)
    except (JiraError, httpx.HTTPError) as e:
        raise HTTPException(502, str(e))


@app.get("/api/mywork")
def my_work(account_id: str, done: bool = False):
    """Historias y subtareas asignadas a una persona, con sus Historias y épicas y el avance de cada Historia."""
    return _jira_call(JiraClient().my_work, account_id, done)


def _editable(j: JiraClient, key: str, updated: str | None, force: bool) -> dict:
    """Comprueba que la incidencia se puede tocar: las subtareas solo si las creó el usuario; las Historias sí
    (la interfaz avisa antes). Si alguien la cambió en Jira desde que se cargó, 409 con el valor actual."""
    item = _jira_call(j.get_item, key)
    if item["subtask"] and not item["mine"]:
        raise HTTPException(403, f"{key} la creó {item['creator'] or 'otra persona'}: solo puedes editar las subtareas que creaste")
    if updated and item["updated"] != updated and not force:
        raise HTTPException(409, {"message": f"{key} cambió en Jira desde que la cargaste", "current": item})
    return item


class EditIn(BaseModel):
    changes: dict
    updated: str | None = None
    force: bool = False


@app.patch("/api/issues/{key}")
def edit_issue(key: str, body: EditIn):
    j = JiraClient()
    _editable(j, key, body.updated, body.force)
    return _jira_call(j.edit_item, key, body.changes)


class StatusIn(BaseModel):
    category: str  # new | indeterminate | done
    updated: str | None = None
    force: bool = False


@app.post("/api/issues/{key}/status")
def issue_status(key: str, body: StatusIn):
    if body.category not in ("new", "indeterminate", "done"):
        raise HTTPException(400, "Estado no válido")
    j = JiraClient()
    _editable(j, key, body.updated, body.force)
    return _jira_call(j.set_status, key, body.category)


class SubtaskIn(BaseModel):
    summary: str
    assignee_id: str | None = None
    start_date: str | None = None
    due_date: str | None = None
    description: str = ""


@app.post("/api/issues/{key}/subtasks")
def add_subtask(key: str, body: SubtaskIn):
    if not body.summary.strip():
        raise HTTPException(400, "La subtarea necesita un título")
    j = JiraClient()
    return _jira_call(j.create_subtask, key, body.summary.strip(), body.assignee_id, body.start_date,
                      body.due_date, body.description)


class PushIn(BaseModel):
    plan: Plan
    only_ids: list[str] | None = None


@app.post("/api/push")
def push(body: PushIn):
    """Guarda el plan recibido (tal como está en pantalla) y lo sube a Jira."""
    ws = _get()
    ws.plan = body.plan
    try:
        results = JiraClient().push_plan(ws.plan, set(body.only_ids) if body.only_ids else None)
    except JiraError as e:
        store.save_session(ws)
        raise HTTPException(502, str(e))
    store.save_session(ws)
    return {"workspace": ws, "results": results}
