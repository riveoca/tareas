"""Desglose de tareas con Claude o con una IA local (Ollama)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from datetime import date

import anthropic
import httpx
from pydantic import ValidationError

from .config import settings
from .models import AIResult, Defaults, Epic, Plan, Task, default_due_date, default_start_date

SYSTEM_PROMPT = """Eres un asistente de gestión de proyectos ágil (Scrum en Jira). Recibes lo que alguien hizo \
o tiene que hacer (un texto escrito a mano o un archivo de memoria / registro de cambios) y lo desglosas en tareas \
listas para Jira.

Reglas:
- Las épicas son los PROYECTOS. Identifica a qué proyecto pertenece cada trabajo y agrupa las tareas en la épica \
de ese proyecto. Si el proyecto coincide con una épica existente (aunque se escriba distinto), usa el id y el nombre \
EXACTO de esa épica. Si no existe, crea una épica nueva (id null) cuyo nombre sea el nombre del proyecto en MAYÚSCULAS.
- Título de cada tarea con este formato exacto:
  NOMBRE DEL PROYECTO - descripción breve de la tarea - info adicional si es necesaria
  · NOMBRE DEL PROYECTO = el nombre exacto de su épica.
  · descripción breve = un título DICIENTE: que cualquier persona del equipo (también alguien no técnico, como \
un jefe de proyecto) entienda qué se hizo y para qué, sin abrir la tarea. Estructura: verbo en infinitivo + qué \
cosa + para qué o con qué resultado. Entre 6 y 14 palabras. Evita que el título sea solo un nombre de archivo, \
función o comando; nombra la funcionalidad o el problema que resuelve.
  · info adicional = solo si aporta (componente, archivo, cliente, ticket, entorno…); si no, omite ese tramo y su guion.
  Ejemplos buenos:
    "META - WHATSAPP - Configurar webhook para recibir mensajes entrantes de clientes"
    "ASISTENTE_IA - Corregir respuesta vacía del chat cuando falla la consulta al modelo - producción"
    "Flujos QA - SIGE - Hacer que el runner detecte todos los tests agregando __init__.py - paquetes de tests"
  Ejemplos malos (poco dicientes): "Agregar __init__.py", "Fix webhook", "Ajustes varios", "Actualizar archivo".
- TAMAÑO DE TAREA (lo más importante): cada tarea equivale a 1 story point = un ENTREGABLE con sentido propio, \
de unas pocas horas hasta un día de trabajo. Piensa "¿esto lo pondría un jefe de proyecto como una línea en su \
planificación?". Si no, es demasiado pequeño y va dentro de otra tarea.
  · Una tarea = un resultado que se puede revisar (una funcionalidad, una corrección, una integración, un informe, \
una configuración completa…), NO cada paso o acción suelta para conseguirlo.
  · Los pasos intermedios de un mismo resultado (analizar, crear el archivo, codificar, probar, ajustar, subir) van \
JUNTOS en una sola tarea y se detallan como viñetas en su "description". Solo sepáralos si cada uno es un trabajo \
considerable por sí mismo (p.ej. una batería de pruebas grande, un despliegue complejo).
  · Cambios pequeños relacionados (renombrar, mover archivos, ajustes de formato, pequeños fixes sobre lo mismo, \
actualizar dependencias, comentarios) se AGRUPAN en una única tarea; nunca una tarea por cada uno.
  · Divide solo cuando un trabajo es claramente de varios días; entonces pártelo por partes funcionales \
(p.ej. "backend del login", "pantalla del login"), no por pasos mecánicos.
  · No inventes trabajo que el texto no menciona ni implica: nada de tareas genéricas de "documentar", "probar" o \
"desplegar" si el texto no las nombra.
  · Mejor pocas tareas con sentido que muchas triviales. Como referencia, un día de trabajo descrito en un registro \
suele dar 1-4 tareas, no 10.
- story_points: null (el equipo los estima en Jira).
- description: el detalle de lo hecho o por hacer (usa "- " para viñetas); aquí van los pasos concretos.
- SIN REPETICIONES: antes de responder, revisa tu lista. Si dos tareas describen el mismo trabajo con otras \
palabras, se solapan, o una es parte de otra, fusiónalas en una. Tampoco repitas tareas que ya existen en \
<epicas_existentes>, aunque estén redactadas distinto.
- issue_type: solo uno de los tipos estándar disponibles (normalmente el equivalente a "Tarea").
- assignee: nombre exacto de un miembro del equipo SOLO si el texto nombra a esa persona (p.ej. "Ana hizo…"); \
si está en primera persona o no se indica, null.
- start_date / due_date: siempre null (las fechas se asignan desde la configuración de la app).
- En "reply" resume en 1-2 frases lo desglosado y cualquier duda (p.ej. si no quedó claro el proyecto).
Responde en español."""


class LLMError(Exception):
    pass


def _context_text(plan: Plan, meta: dict | None, content: str | None) -> str:
    meta = meta or {}
    team = [u["displayName"] for u in meta.get("users", [])]
    types = [t["name"] for t in meta.get("issue_types", []) if t.get("level") == 0] or ["Task", "Story", "Bug"]
    existing = [
        {"id": e.id, "epica_proyecto": e.summary, "tareas": [t.summary for t in e.tasks][-30:]}
        for e in plan.epics
    ]
    in_plan = {e.jira_key for e in plan.epics if e.jira_key}
    existing += [{"id": f"jira:{je['key']}", "epica_proyecto": je["summary"], "tareas": []}
                 for je in meta.get("epics", []) if je["key"] not in in_plan]
    body = f"""Fecha de hoy: {date.today().isoformat()}

<proyecto_jira>
Tipos de incidencia estándar disponibles: {', '.join(types)}
Miembros del equipo: {', '.join(team) or '(desconocidos: usa null)'}
</proyecto_jira>

<epicas_existentes (proyectos)>
{json.dumps(existing, ensure_ascii=False, indent=1) if existing else '(ninguna)'}
</epicas_existentes (proyectos)>
"""
    if content is not None:
        body += f"\n<trabajo_a_desglosar>\n{content}\n</trabajo_a_desglosar>\n"
    else:
        body += "\nDesglosa el trabajo del documento adjunto.\n"
    return body


# ---------------- Claude ----------------

def _call_claude(plan: Plan, meta: dict | None, content: str, filename: str | None) -> AIResult:
    client = anthropic.Anthropic()
    if filename:
        blocks: list[dict] = [
            {"type": "document", "title": filename,
             "source": {"type": "text", "media_type": "text/plain", "data": content}},
            {"type": "text", "text": _context_text(plan, meta, None)},
        ]
    else:
        blocks = [{"type": "text", "text": _context_text(plan, meta, content)}]

    kwargs: dict = {}
    if settings.claude_fallbacks:
        kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": settings.claude_fallbacks}

    try:
        with client.beta.messages.stream(
            model=settings.claude_model,
            max_tokens=64000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": blocks}],
            thinking={"type": "adaptive"},
            output_config={"effort": settings.claude_effort},
            output_format=AIResult,
            **kwargs,
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise LLMError("API key de Anthropic inválida o ausente (ANTHROPIC_API_KEY en .env)")
    except anthropic.RateLimitError:
        raise LLMError("Límite de uso de la API de Claude alcanzado; reintenta en un momento")
    except anthropic.BadRequestError as e:
        raise LLMError(f"Petición rechazada por la API de Claude: {e.message}")
    except anthropic.APIStatusError as e:
        raise LLMError(f"Error de la API de Claude ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise LLMError("No se pudo conectar con la API de Claude")

    if message.stop_reason == "refusal":
        raise LLMError("Claude rechazó la petición")
    if message.stop_reason == "max_tokens":
        raise LLMError("La respuesta de Claude se cortó por longitud; divide el texto")
    if message.parsed_output is None:
        raise LLMError("Claude no devolvió un desglose válido")
    return message.parsed_output


# ---------------- Claude Code (cuenta de Claude, sin API key) ----------------

def claude_code_available() -> bool:
    return shutil.which(settings.claude_code_bin) is not None


def _call_claude_code(plan: Plan, meta: dict | None, content: str, filename: str | None) -> AIResult:
    """Usa el CLI `claude` en modo no interactivo con la sesión de tu cuenta (Pro/Team/Enterprise)."""
    if not claude_code_available():
        raise LLMError("No se encontró Claude Code (comando 'claude'). Instálalo e inicia sesión con tu cuenta.")
    text = f'Archivo "{filename}":\n{content}' if filename else content
    cmd = [
        settings.claude_code_bin, "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(AIResult.model_json_schema()),
        "--system-prompt", SYSTEM_PROMPT,
        "--tools", "",
        "--no-session-persistence",
    ]
    if settings.claude_code_model:
        cmd += ["--model", settings.claude_code_model]
    try:
        # cwd temporal: que no cargue CLAUDE.md ni configuración de ningún proyecto
        proc = subprocess.run(cmd, input=_context_text(plan, meta, text), capture_output=True, text=True,
                              timeout=600, cwd=tempfile.gettempdir())
    except subprocess.TimeoutExpired:
        raise LLMError("Claude Code tardó demasiado (más de 10 min)")
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        err = (proc.stderr or proc.stdout).strip()[:400]
        if "login" in err.lower() or "auth" in err.lower():
            raise LLMError("Claude Code no tiene sesión iniciada: ejecuta 'claude' en una terminal y haz /login")
        raise LLMError(f"Claude Code falló: {err or 'sin salida'}")
    if out.get("is_error"):
        raise LLMError(f"Claude Code devolvió un error: {str(out.get('result'))[:400]}")
    data = out.get("structured_output")
    try:
        return AIResult.model_validate(data) if data is not None else AIResult.model_validate_json(out.get("result", ""))
    except ValidationError as e:
        raise LLMError(f"Claude Code no devolvió un desglose válido: {e.errors()[:3]}")


# ---------------- Ollama (IA local) ----------------

def _call_ollama(plan: Plan, meta: dict | None, content: str, filename: str | None) -> AIResult:
    text = f'Archivo "{filename}":\n{content}' if filename else content
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "format": AIResult.model_json_schema(),
        "options": {"temperature": 0.2, "num_ctx": 16384},
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": _context_text(plan, meta, text)}],
    }
    try:
        r = httpx.post(f"{settings.ollama_url}/api/chat", json=payload, timeout=600)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise LLMError(f"No se pudo usar Ollama en {settings.ollama_url}: {e}")
    raw = r.json().get("message", {}).get("content", "")
    try:
        return AIResult.model_validate_json(raw)
    except ValidationError as e:
        raise LLMError(f"La IA local devolvió un JSON no válido: {e.errors()[:3]}")


# ---------------- Entrada común ----------------

def breakdown(plan: Plan, defaults: Defaults, meta: dict | None, content: str,
              provider: str, filename: str | None = None) -> tuple[str, Plan, int, int]:
    """Desglosa `content` y añade las tareas nuevas al plan.
    Devuelve (resumen, plan, nº tareas nuevas, nº duplicadas omitidas)."""
    call = {"claude_code": _call_claude_code, "claude": _call_claude}.get(provider, _call_ollama)
    result = call(plan, meta, content, filename)
    added, skipped = _add_to_plan(result, plan, defaults, meta)
    return result.reply, plan, added, skipped


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.lower()).strip()


def format_title(epic_name: str, summary: str) -> str:
    """Garantiza el formato "PROYECTO - descripción - info": el primer tramo es el nombre exacto de la épica."""
    parts = [p.strip() for p in re.split(r"\s+-\s+", summary.strip()) if p.strip()]
    target = _norm(epic_name)
    for k in range(1, len(parts) + 1):  # el nombre de la épica puede contener " - " (p.ej. "META - WHATSAPP")
        if _norm(" - ".join(parts[:k])) == target:
            parts = parts[k:]
            break
    return " - ".join([epic_name.strip(), *parts]) if parts else epic_name.strip()


def _add_to_plan(result: AIResult, plan: Plan, defaults: Defaults, meta: dict | None) -> tuple[int, int]:
    users = {u["displayName"].strip().lower(): u for u in (meta or {}).get("users", [])}
    epics_by_id = {e.id: e for e in plan.epics}
    epics_by_name = {_norm(e.summary): e for e in plan.epics}
    jira_epics = {je["key"]: je for je in (meta or {}).get("epics", [])}
    jira_by_name = {_norm(je["summary"]): je for je in jira_epics.values()}
    by_key = {e.jira_key: e for e in plan.epics if e.jira_key}

    def linked_epic(je: dict) -> Epic:
        """Épica del plan que representa una épica existente de Jira (se crea si hace falta)."""
        if je["key"] not in by_key:
            e = Epic(summary=je["summary"], jira_key=je["key"], linked=True)
            plan.epics.append(e)
            by_key[e.jira_key] = epics_by_id[e.id] = epics_by_name[_norm(e.summary)] = e
        return by_key[je["key"]]

    existing = {_norm(t.summary) for e in plan.epics for t in e.tasks}
    added = skipped = 0
    for ae in result.epics:
        if not ae.tasks:
            continue
        # Épica = proyecto: por id, por nombre en la lista, o por nombre/clave entre las épicas de Jira
        name = _norm(ae.summary)
        epic = epics_by_id.get(ae.id or "") or epics_by_name.get(name)
        if epic is None:
            je = jira_epics.get((ae.id or "").removeprefix("jira:")) or jira_by_name.get(name)
            if je:
                epic = linked_epic(je)
        if epic is None:
            epic = Epic(summary=ae.summary.strip(), description=ae.description)
            plan.epics.append(epic)
            epics_by_id[epic.id] = epic
            epics_by_name[name] = epic

        for at in ae.tasks:
            title = format_title(epic.summary, at.summary)
            key = _norm(title)
            if key == _norm(epic.summary) or key in existing:  # vacía o repetida
                skipped += 1
                continue
            existing.add(key)
            # Responsable: la persona del equipo que nombre el texto; si no nombra a nadie, la de Configuración.
            # Sprint y fechas: los de Configuración; fechas vacías = hoy / último día del mes.
            user = users.get((at.assignee or "").strip().lower())
            if user:
                assignee_id, assignee_name = user["accountId"], user["displayName"]
            else:
                assignee_id, assignee_name = defaults.assignee_id, defaults.assignee_name
            epic.tasks.append(Task(
                summary=title, description=at.description, issue_type=at.issue_type,
                story_points=settings.task_story_points, labels=at.labels,  # None = sin puntos
                assignee_id=assignee_id, assignee_name=assignee_name,
                sprint_id=defaults.sprint_id, sprint_name=defaults.sprint_name,
                start_date=defaults.start_date or default_start_date(),
                due_date=defaults.due_date or default_due_date(),
            ))
            added += 1
    return added, skipped
