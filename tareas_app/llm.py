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

from . import dedup
from .config import settings
from .models import AIResult, Defaults, Epic, Plan, Task, default_due_date, default_start_date

SYSTEM_PROMPT = """Eres un asistente de gestión de proyectos ágil (Scrum en Jira). Recibes lo que alguien hizo \
o tiene que hacer (un texto escrito a mano o un archivo de memoria / registro de cambios) y lo registras en Jira.

Metodología del equipo: el jefe de proyecto planifica cada proyecto en Microsoft Planner; cada tarea del Planner tiene \
en Jira una HISTORIA espejo (dentro de la épica del proyecto, con los story points). El trabajo concreto de cada \
persona se registra como SUBTAREAS (1 punto cada una) de esas Historias. Tu trabajo es repartir lo que dice el texto entre \
las Historias que le correspondan: crear las subtareas nuevas en la Historia más acorde y marcar como hechas las \
subtareas planificadas que el texto da por terminadas.

Cómo hacerlo, en este orden:
1. Separa el texto en trabajos (entregables) y decide para cada uno si ya se HIZO o está POR HACER.
2. HISTORIA: para cada trabajo elige en <historias_existentes> la Historia más acorde y pon su clave en "historia".
  · Compara el QUÉ (funcionalidad, flujo, pantalla, servicio, entregable) con el título y la "descripcion" de cada \
Historia, aunque estén redactados distinto; primero filtra por proyecto ("epica") y luego elige la más específica \
(p.ej. un ajuste del despliegue del asistente va en la Historia de despliegue de la épica del asistente, no en la de \
otro proyecto ni en una genérica de "ajustes").
  · Si hay empate, prefiere la Historia cuyo "responsable" es la persona que hizo el trabajo (\
<persona_que_registra> o la que nombre el texto), luego la que esté "En curso", y luego la que ya tenga subtareas \
parecidas.
  · Un trabajo que toca dos Historias se parte en una subtarea por Historia (cada parte en la suya); nunca una \
subtarea que mezcle dos Historias.
  · Si un trabajo no encaja de verdad en ninguna Historia, deja "historia" en null (se subirá como tarea suelta de \
la épica) y en "reply" nómbralo y sugiere la Historia que habría que crear en el Planner. No fuerces una Historia que \
no corresponde solo por estar en el mismo proyecto.
3. YA PLANIFICADO: mira las "subtareas" de esa Historia. Si el trabajo HECHO equivale a una subtarea abierta \
("hecha": false), aunque esté redactada distinto, no la crees: pon su clave en "cerrar". Si equivale a una que ya \
está hecha, o a una "en la lista, sin subir", omítelo. Solo claves que aparezcan en <historias_existentes>.
4. Lo que quede son subtareas NUEVAS: crea cada una con las reglas de abajo.

Reglas:
- done: true si el texto dice que el trabajo ya se hizo (pasado: "hice", "corregí", "quedó listo", un registro de
  cambios); false si es algo por hacer o planificado.
- Las épicas son los PROYECTOS. Agrupa las tareas en "epics" por proyecto. Si la tarea tiene Historia, su épica es la \
de la Historia: usa su "id_epica" y el nombre exacto de su "epica". Sin Historia: si el proyecto coincide con una \
épica existente (aunque se escriba distinto), usa el id y el nombre EXACTO de esa épica; si no existe, crea una épica \
nueva (id null) cuyo nombre sea el nombre del proyecto en MAYÚSCULAS.
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
- TAMAÑO DE TAREA (lo más importante): cada subtarea es un ENTREGABLE con sentido propio, \
de unas pocas horas hasta un día de trabajo (vale 1 punto; lo pone la app). Piensa "¿esto lo pondría un jefe de proyecto como una línea en su \
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
- story_points: null siempre (la app pone 1 punto a cada subtarea).
- description: el detalle de lo hecho o por hacer (usa "- " para viñetas); aquí van los pasos concretos.
- SIN REPETICIONES: antes de responder, revisa tu lista. Si dos tareas describen el mismo trabajo con otras \
palabras, se solapan, o una es parte de otra, fusiónalas en una. Tampoco repitas tareas que ya existen en \
<epicas_existentes>, aunque estén redactadas distinto. EXCEPCIÓN: si el texto da varios números de servicio, \
ticket u orden (p.ej. "servicios 40286 y 40285"), cada número es una tarea distinta: no las fusiones y pon el número \
en el título.
- issue_type: solo uno de los tipos estándar disponibles (normalmente el equivalente a "Tarea"); si va en una Historia
  da igual cuál (se sube como subtarea).
- assignee: nombre exacto de un miembro del equipo SOLO si el texto nombra a esa persona (p.ej. "Ana hizo…"); \
si está en primera persona o no se indica, null.
- start_date / due_date: siempre null (las fechas se asignan desde la configuración de la app).
- En "reply" resume en 1-2 frases lo desglosado y cualquier duda (p.ej. si no quedó claro el proyecto).
Responde en español."""


class LLMError(Exception):
    pass


def _context_text(plan: Plan, meta: dict | None, content: str | None, defaults: Defaults | None = None) -> str:
    meta = meta or {}
    person = (defaults.assignee_name if defaults else None) or meta.get("me") or "(desconocida)"
    team = [u["displayName"] for u in meta.get("users", [])]
    types = [t["name"] for t in meta.get("issue_types", []) if t.get("level") == 0] or ["Task", "Story", "Bug"]
    existing = [
        {"id": e.id, "epica_proyecto": e.summary, "tareas": [t.summary for t in e.tasks][-30:]}
        for e in plan.epics
    ]
    in_plan = {e.jira_key for e in plan.epics if e.jira_key}
    existing += [{"id": f"jira:{je['key']}", "epica_proyecto": je["summary"], "tareas": []}
                 for je in meta.get("epics", []) if je["key"] not in in_plan]
    # Historias abiertas (espejo del Planner) con sus subtareas y las que ya están en el plan sin subir
    pending = {}
    for e in plan.epics:
        for t in e.tasks:
            if t.parent_key and not t.jira_key:
                pending.setdefault(t.parent_key, []).append({"clave": None, "titulo": t.summary, "hecha": t.done,
                                                             "nota": "en la lista, sin subir"})
    stories = [{"clave": h["key"], "historia": h["summary"], "descripcion": h.get("description") or None,
                "epica": h["epic"], "id_epica": f"jira:{h['epic_key']}", "estado": h.get("status"),
                "responsable": h["assignee"],
                "subtareas": [{"clave": st["key"], "titulo": st["summary"], "hecha": st["done"]} for st in h["subtasks"]]
                + pending.get(h["key"], [])}
               for h in meta.get("stories", []) if h.get("epic_key")]
    body = f"""Fecha de hoy: {date.today().isoformat()}

<proyecto_jira>
Tipos de incidencia estándar disponibles: {', '.join(types)}
Miembros del equipo: {', '.join(team) or '(desconocidos: usa null)'}
</proyecto_jira>

<persona_que_registra>{person}</persona_que_registra>

<epicas_existentes (proyectos)>
{json.dumps(existing, ensure_ascii=False, indent=1) if existing else '(ninguna)'}
</epicas_existentes (proyectos)>

<historias_existentes>
{chr(10).join(json.dumps(h, ensure_ascii=False) for h in stories) if stories else '(ninguna: todas las tareas van con historia null)'}
</historias_existentes>
"""
    if content is not None:
        body += f"\n<trabajo_a_desglosar>\n{content}\n</trabajo_a_desglosar>\n"
    else:
        body += "\nDesglosa el trabajo del documento adjunto.\n"
    return body


# ---------------- Claude ----------------

def _call_claude(plan: Plan, meta: dict | None, content: str, filename: str | None, defaults: Defaults) -> AIResult:
    client = anthropic.Anthropic()
    if filename:
        blocks: list[dict] = [
            {"type": "document", "title": filename,
             "source": {"type": "text", "media_type": "text/plain", "data": content}},
            {"type": "text", "text": _context_text(plan, meta, None, defaults)},
        ]
    else:
        blocks = [{"type": "text", "text": _context_text(plan, meta, content, defaults)}]

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


def _call_claude_code(plan: Plan, meta: dict | None, content: str, filename: str | None, defaults: Defaults) -> AIResult:
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
        proc = subprocess.run(cmd, input=_context_text(plan, meta, text, defaults), capture_output=True, text=True,
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

def _call_ollama(plan: Plan, meta: dict | None, content: str, filename: str | None, defaults: Defaults) -> AIResult:
    text = f'Archivo "{filename}":\n{content}' if filename else content
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "format": AIResult.model_json_schema(),
        "options": {"temperature": 0.2, "num_ctx": 16384},
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": _context_text(plan, meta, text, defaults)}],
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
              provider: str, filename: str | None = None) -> tuple[str, Plan, int, list[dict], list[dict]]:
    """Desglosa `content` y añade las tareas nuevas al plan.
    Devuelve (resumen, plan, nº tareas nuevas, repetidas omitidas, subtareas existentes que ya se hicieron)."""
    call = {"claude_code": _call_claude_code, "claude": _call_claude}.get(provider, _call_ollama)
    result = call(plan, meta, content, filename, defaults)
    added, dupes = _add_to_plan(result, plan, defaults, meta)
    return result.reply, plan, added, dupes, _to_close(result, meta)


def _to_close(result: AIResult, meta: dict | None) -> list[dict]:
    """Subtareas abiertas que el texto da por hechas, solo si existen de verdad (la IA no puede inventar claves)."""
    subs = {st["key"]: (h, st) for h in (meta or {}).get("stories", []) for st in h["subtasks"] if not st["done"]}
    out, seen = [], set()
    for key in result.cerrar:
        key = key.strip().upper()
        if key in subs and key not in seen:
            seen.add(key)
            h, st = subs[key]
            out.append({"key": key, "summary": st["summary"], "story_key": h["key"], "story": h["summary"]})
    return out


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


def _add_to_plan(result: AIResult, plan: Plan, defaults: Defaults, meta: dict | None) -> tuple[int, list[dict]]:
    """Añade al plan las tareas de la IA. Devuelve (nº añadidas, repetidas omitidas con la incidencia que ya existe)."""
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

    stories = {h["key"]: h for h in (meta or {}).get("stories", [])}
    sub_type = next((t["name"] for t in (meta or {}).get("issue_types", []) if t.get("level") == -1), "Subtarea")
    existing = {_norm(t.summary) for e in plan.epics for t in e.tasks}
    # Contra qué se comparan las subtareas nuevas: las de Jira (Historias abiertas y las recientes de cualquier
    # Historia, también cerradas) y las de la lista que aún no se subieron
    pool = {st["key"]: {"key": st["key"], "summary": st["summary"], "parent": h["key"]}
            for h in stories.values() for st in h["subtasks"]}
    pool |= {st["key"]: st for st in (meta or {}).get("recent_subtasks", [])}
    pool = list(pool.values()) + [{"key": None, "summary": t.summary, "parent": t.parent_key}
                                  for e in plan.epics for t in e.tasks if not t.jira_key]
    added, dupes = 0, []
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
        for at in ae.tasks:
            story = stories.get((at.historia or "").strip().upper())
            if epic is None and not (story and story.get("epic_key")):
                # Épica nueva: solo se crea si alguna tarea suelta la necesita (las de Historia van a la de su Historia)
                epic = Epic(summary=ae.summary.strip(), description=ae.description)
                plan.epics.append(epic)
                epics_by_id[epic.id] = epic
                epics_by_name[name] = epic
            t_epic = epic
            if story and story.get("epic_key") and (epic is None or story["epic_key"] != epic.jira_key):
                # La Historia manda: la subtarea va en la épica de su Historia
                t_epic = linked_epic(jira_epics.get(story["epic_key"])
                                     or {"key": story["epic_key"], "summary": story["epic"] or story["epic_key"]})
            title = format_title(t_epic.summary, at.summary)
            key = _norm(title)
            if key == _norm(t_epic.summary):  # vacía
                continue
            same = dedup.find_duplicate(title, story["key"] if story else None, pool, t_epic.summary)
            if key in existing or same:
                dupes.append({"summary": title, "key": (same or {}).get("key"), "existing": (same or {}).get("summary", title),
                              "parent": (same or {}).get("parent")})
                continue
            existing.add(key)
            pool.append({"key": None, "summary": title, "parent": story["key"] if story else None})
            # Responsable: la persona del equipo que nombre el texto; si no nombra a nadie, la de Configuración.
            # Sprint y fechas: los de Configuración; fechas vacías = hoy / último día del mes.
            user = users.get((at.assignee or "").strip().lower())
            if user:
                assignee_id, assignee_name = user["accountId"], user["displayName"]
            else:
                assignee_id, assignee_name = defaults.assignee_id, defaults.assignee_name
            # Con Historia: subtarea de 1 punto y sin sprint (hereda el de la Historia). Sin Historia: tarea suelta como antes.
            t_epic.tasks.append(Task(
                summary=title, description=at.description, issue_type=sub_type if story else at.issue_type,
                story_points=1 if story else settings.task_story_points, labels=at.labels,
                assignee_id=assignee_id, assignee_name=assignee_name,
                sprint_id=None if story else defaults.sprint_id, sprint_name=None if story else defaults.sprint_name,
                start_date=defaults.start_date or default_start_date(),
                due_date=defaults.due_date or default_due_date(),
                parent_key=story["key"] if story else None, parent_summary=story["summary"] if story else None,
                done=at.done,
            ))
            added += 1
    return added, dupes
