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
- `static/index.html` — toda la interfaz (JS inline). Dos vistas: Tareas y "Avance del sprint" (`#sprint`), en SVG y sin
  fines de semana: "Informe de trabajo completado" del equipo como Jira: alcance (rojo), cerrados (verde),
  directriz de 0 al alcance actual (`GET /api/sprint/{id}/burnup` → `JiraClient.sprint_burnup`, que reproduce la API
  interna `greenhopper/.../scopechangeburndownchart.json`; sus horas vienen en hora local como si fueran UTC).
  Debajo, el mismo informe personal (`?assignee=<nombre>`, por defecto el usuario de Jira) solo con sus tareas asignadas hoy.
  El eje va del inicio al fin previsto; si el sprint sigue abierto después (o se cerró tarde), se alarga hasta hoy / el cierre y tareas creadas por día hábil
  (`GET /api/sprint/{id}/issues` → `JiraClient.sprint_issues`).
  Al final, apartado plegado "Desempeño histórico individual" que solo carga al abrirlo (`GET /api/performance` →
  `JiraClient.performance`, consultas en paralelo por tramos de fecha, caché 10 min en `server.py`): todos se comparan
  por media por sprint y solo en los sprints cerrados de la persona elegida (decisión del usuario: llevar más sprints no da ventaja). Incluye tendencia
  (últimos 3 vs 3 anteriores) y reparto por épica (`by_sprint[id].epics`).

## Reglas de negocio (decididas por el usuario)
- En Jira cada tarea lleva solo su épica como padre; **no se envían etiquetas**.
- Desglose: 1 story point = un entregable con sentido propio (horas–1 día), no cada paso; nada de tareas
  repetidas o triviales. Los pasos van en la descripción.
- Fechas: solo de Configuración; vacías = inicio hoy, fin último día del mes actual. Las fechas del texto se ignoran.
- Títulos: `PROYECTO - descripción diciente - info adicional` (el proyecto es el nombre exacto de la épica).

## Cuidado
- `.env` contiene el token de Jira: no mostrarlo ni copiarlo.
- `tareas.db` tiene el plan real del usuario: no borrarlo.
