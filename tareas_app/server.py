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
    return FileResponse(STATIC / "index.html")


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
        note, ws.plan, added, skipped = llm.breakdown(ws.plan, ws.defaults, jira_meta(), content, provider, filename)
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    store.save_session(ws)
    return {"workspace": ws, "note": note, "added": added, "skipped": skipped}


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
