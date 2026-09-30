# Tareas IA → Jira

App web local (FastAPI + SQLite + una sola página HTML) que desglosa con IA el trabajo realizado en
épicas y tareas y las sube a Jira Cloud. El usuario y la interfaz están en español: responde y escribe
textos de la app en español.

## Ejecutar
- `./tareas` → app en http://127.0.0.1:8765 (usa `.venv/bin/python -m tareas_app`)
- `./tareas check` → comprueba Jira, Claude y Ollama
- Tras cambiar código Python hay que reiniciar el servidor (no hay recarga automática).
- No hay tests; para validar lógica usa scripts cortos con `.venv/bin/python` (p.ej. `_add_to_plan`).

## Estructura (`tareas_app/`)
- `llm.py` — `SYSTEM_PROMPT` (único, compartido por los 3 proveedores: `claude_code`, `claude`, `ollama`),
  llamadas a cada IA y `_add_to_plan` (épicas, títulos, responsable, fechas, deduplicación).
- `jira.py` — cliente Jira: metadatos, `_fields_for` (campos enviados) y `push_plan` (crea/actualiza).
- `models.py` — salida estructurada de la IA (`AIResult`) y datos de la app (`Plan`, `Epic`, `Task`, `Defaults`).
- `server.py` — API FastAPI; `store.py` — persistencia JSON en `tareas.db`; `config.py` — lee `.env`.
- `static/index.html` — toda la interfaz (JS inline).

## Reglas de negocio (decididas por el usuario)
- En Jira cada tarea lleva solo su épica como padre; **no se envían etiquetas**.
- Desglose: 1 story point = un entregable con sentido propio (horas–1 día), no cada paso; nada de tareas
  repetidas o triviales. Los pasos van en la descripción.
- Fechas: solo de Configuración; vacías = inicio hoy, fin último día del mes actual. Las fechas del texto se ignoran.
- Títulos: `PROYECTO - descripción diciente - info adicional` (el proyecto es el nombre exacto de la épica).

## Cuidado
- `.env` contiene el token de Jira: no mostrarlo ni copiarlo.
- `tareas.db` tiene el plan real del usuario: no borrarlo.
