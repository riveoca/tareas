# Memoria del proyecto «Tareas IA → Jira»

Documento de traspaso: explica qué es el proyecto, cómo está montado, dónde está cada cosa, qué reglas
sigue y qué hay que saber para mantenerlo. Para el uso básico ver también `README.md`.

---

## 1. Qué es y para qué sirve

Aplicación web **local** (corre en el propio PC, en `http://127.0.0.1:8765`) que usa el equipo de Servitel para:

1. **Registrar en Jira Cloud el trabajo hecho.** Se describe con palabras lo que se hizo (o se suben archivos
   `.txt` de registro / memoria de cambios) y una IA lo desglosa en **épicas** (= proyectos) y **tareas** listas
   para Jira. Se revisan y editan en una tabla y se suben con un botón.
2. **Seguir el avance del sprint.** Vista «📈 Avance del sprint» que reproduce el *Informe de trabajo
   completado* de Jira (del equipo y personal) y una gráfica de tareas creadas por día, **sin fines de semana**.

Además, en `planner/` hay una **herramienta aparte** (script de línea de comandos) que carga tareas en
**Microsoft Planner** manejando la web con Playwright (ver sección 9).

Tecnología: Python 3.11+, FastAPI + Uvicorn, SQLite, Pydantic, httpx, SDK `anthropic`. El front es **un único
`index.html`** con JS y CSS inline, sin frameworks ni build; las gráficas se dibujan en SVG a mano.

---

## 2. Puesta en marcha (desde cero)

```bash
cd tareas
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # rellenar (ver sección 3)
./tareas check              # comprueba Jira, Claude y Ollama
./tareas                    # arranca la app y abre el navegador
```

- `./tareas` es un script bash que hace `cd` a la carpeta y ejecuta `.venv/bin/python -m tareas_app "$@"`.
- Subcomandos (`tareas_app/__main__.py`):
  - `serve` (por defecto): opciones `--host` (127.0.0.1), `--port` (8765), `--no-browser`.
  - `check`: imprime usuario de Jira, proyecto, tipos de incidencia, equipo asignable, campos de story points
    y fecha de inicio detectados, nº de épicas abiertas, sprints; estado de la API key de Claude y de Ollama.
- **No hay recarga automática**: tras tocar código Python hay que parar (Ctrl+C) y volver a lanzar.
  Los cambios en `index.html` solo requieren recargar el navegador.

---

## 3. Configuración (`.env`)

Plantilla comentada en `.env.example`. `config.py` lo carga con `python-dotenv` en un `Settings` inmutable
(se lee una vez al arrancar: cambiar `.env` exige reiniciar).

| Variable | Uso |
|---|---|
| `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY` | Conexión a Jira Cloud (auth básica email + token). Sin las 4, la app funciona pero no puede subir ni ver sprints. |
| `JIRA_STORY_POINTS_FIELD`, `JIRA_START_DATE_FIELD` | Id del campo personalizado (p. ej. `customfield_10016`). Vacío = se busca por nombre («Story Points», «Fecha de inicio»…). |
| `TASK_STORY_POINTS` | Puntos que se ponen a cada tarea generada por IA. Vacío = ninguno. |
| `LLM_PROVIDER` | IA por defecto: `claude_code`, `claude` u `ollama` (se puede cambiar en la app). |
| `CLAUDE_CODE_BIN`, `CLAUDE_CODE_MODEL` | Para `claude_code`: comando del CLI y modelo opcional. |
| `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `CLAUDE_EFFORT`, `CLAUDE_FALLBACKS` | Para `claude` (API de Anthropic). |
| `OLLAMA_URL`, `OLLAMA_MODEL` | Para `ollama` (IA local). Con modelos pequeños (3B) el desglose es pobre; mejor ≥7B. |
| `TAREAS_DB` | Ruta del SQLite (por defecto `tareas.db`). |

⚠️ `.env` contiene el token personal de Jira: **no se sube a git ni se comparte**. Cada persona que tome el
proyecto debe crear su propio token en https://id.atlassian.com/manage-profile/security/api-tokens.
Las tareas se crean en Jira **en nombre del dueño del token**.

---

## 4. Estructura de archivos

```
tareas/
├── tareas                    # lanzador bash
├── requirements.txt
├── .env / .env.example       # configuración (el .env no se versiona)
├── tareas.db                 # SQLite con el plan y la configuración del usuario (no se versiona)
├── README.md                 # documentación de uso
├── MEMORIA_PROYECTO.md       # este documento
├── .claude/                  # instrucciones y permisos para Claude Code (ver sección 10)
├── graphify-out/             # grafo de conocimiento del código (opcional, ver sección 10)
├── planner/                  # herramienta aparte para Microsoft Planner (sección 9)
└── tareas_app/
    ├── __main__.py           # CLI: serve / check
    ├── config.py             # lectura de .env → settings
    ├── models.py             # modelos Pydantic
    ├── store.py              # persistencia SQLite
    ├── llm.py                # prompt + llamadas a las 3 IAs + incorporación al plan
    ├── jira.py               # cliente REST de Jira (lectura, escritura, datos de gráficas)
    ├── server.py             # API FastAPI
    └── static/index.html     # toda la interfaz
```

---

## 5. Cómo funciona por dentro

### 5.1 Modelo de datos (`models.py`)

Dos grupos de modelos:

- **Salida de la IA** (`AIResult` → `AIEpic` → `AITask`), con `extra="forbid"` porque se usan como *JSON Schema*
  de salida estructurada para las tres IAs. `AIEpic.id` es el id de una épica existente (del plan, o
  `jira:CLAVE` si es de Jira) o `null` si es nueva.
- **Datos de la app**:
  - `Task`: título, descripción, tipo, puntos, responsable (`assignee_id` = accountId de Jira + nombre),
    sprint (id + nombre), fechas `YYYY-MM-DD`, prioridad, `jira_key` (vacío hasta que se sube).
  - `Epic`: título, descripción, tareas, `jira_key`, y `linked=True` si es una épica que **ya existía en Jira**
    (la app solo usa su clave como padre, nunca la modifica).
  - `Plan` (lista de épicas), `Defaults` (responsable, sprint y fechas que reciben las tareas nuevas) y
    `Workspace` (plan + defaults).
  - `default_start_date()` = hoy; `default_due_date()` = último día del mes actual.

### 5.2 Persistencia (`store.py`)

Una tabla `sessions(id, title, created_at, updated_at, data)` donde `data` es el `Workspace` entero en JSON.
Solo se usa una fila, `id = "main"` (un único espacio de trabajo). No hay migraciones: si se añaden campos
a los modelos, poner valores por defecto para que los JSON antiguos sigan validando.

⚠️ `tareas.db` contiene el plan real de trabajo: no borrarlo. Para empezar limpio en otro equipo basta con no
copiarlo (se crea solo).

### 5.3 API (`server.py`)

| Endpoint | Qué hace |
|---|---|
| `GET /` | Sirve `static/index.html`. |
| `GET /api/config[?refresh=true]` | Metadatos de Jira (equipo, tipos, sprints, épicas abiertas, usuario conectado, campos detectados) **cacheados 10 min** + qué IAs están disponibles. Si Jira falla devuelve `jira: null` y `jira_error`. |
| `GET /api/state` | El `Workspace` guardado. |
| `PUT /api/plan` · `PUT /api/defaults` | Guardan plan / configuración (el front autoguarda con 500 ms de espera). |
| `POST /api/breakdown/text` | `{text, provider}` → desglose con IA, lo añade al plan y devuelve `{workspace, note, added, skipped}`. |
| `POST /api/breakdown/file` | Multipart (`file`, `provider`). Solo `.txt .md .log .csv .json`, máx. 2 MB; decodifica UTF-8 o latin-1. |
| `POST /api/push` | `{plan, only_ids?}` → guarda el plan tal como está en pantalla y lo sube a Jira; devuelve resultados por elemento. |
| `GET /api/sprint/{id}/issues` | Datos del sprint e incidencias (sin épicas) con fecha de creación, responsable y estado. |
| `GET /api/sprint/{id}/burnup[?assignee=]` | Datos del informe de trabajo completado (equipo, o una persona; `__none` = sin responsable). |

Errores de IA o de Jira se devuelven como HTTP 502 con el mensaje en español, que el front muestra tal cual.

### 5.4 Desglose con IA (`llm.py`)

1. `breakdown()` elige la función según el proveedor:
   - `claude_code` → `_call_claude_code`: ejecuta el CLI `claude -p` con `--json-schema` (esquema de `AIResult`),
     `--system-prompt`, sin herramientas, sin guardar sesión y **con cwd en el directorio temporal** para que no
     cargue ningún `CLAUDE.md`. Usa la cuenta de Claude de quien tenga sesión iniciada (no necesita API key).
     Timeout 10 min.
   - `claude` → `_call_claude`: SDK `anthropic` (beta messages, streaming, `thinking` adaptativo, `effort`,
     `output_format=AIResult`, y *fallbacks* de servidor si `CLAUDE_FALLBACKS` no está vacío). Si es un archivo,
     se manda como bloque `document`.
   - cualquier otro → `_call_ollama`: `POST /api/chat` con `format` = JSON Schema, temperatura 0.2, contexto 16k.
2. Las tres usan el **mismo `SYSTEM_PROMPT`** (único sitio donde están las reglas de desglose) y el mismo
   contexto (`_context_text`): fecha de hoy, tipos de incidencia, miembros del equipo, épicas existentes del
   plan (con sus últimos 30 títulos, para no repetir) y épicas abiertas de Jira.
3. `_add_to_plan()` incorpora el resultado:
   - Busca la épica por id, por nombre normalizado en el plan, o entre las épicas de Jira (en ese caso crea en
     el plan una épica `linked`). Si no existe, crea una nueva.
   - `format_title()` fuerza el formato `ÉPICA - descripción - info` (quita el prefijo si la IA ya lo puso,
     aunque la épica contenga « - »).
   - **Deduplicación**: descarta tareas cuyo título normalizado ya exista en el plan (cuenta como `skipped`).
   - Responsable: el miembro del equipo que nombre el texto; si no, el de Configuración.
   - Sprint y fechas: siempre los de Configuración; fechas vacías → hoy / fin de mes. **Las fechas que
     devuelva la IA se ignoran.**

### 5.5 Subida a Jira (`jira.py`)

`JiraClient` usa `httpx` con auth básica contra `/rest/api/3`, `/rest/agile/1.0` y (para el informe)
`/rest/greenhopper/1.0`.

- **Lectura de metadatos** (`metadata()`): tipos de incidencia (nivel 1 = épica, 0 = estándar), usuarios
  asignables, prioridades, sprints **activos y futuros** de todos los tableros no-kanban del proyecto, épicas no
  terminadas (JQL paginado con `nextPageToken`, máx. 500) y detección de campos por nombre.
- **`push_plan(plan, only_ids)`**:
  1. Por cada épica: si es `linked` usa su clave; si no, la crea (o la actualiza si ya tiene clave y se sube
     todo). Si la épica falla, sus tareas no se suben.
  2. Por cada tarea: crea o actualiza (si ya tiene `jira_key` → `PUT`, nunca se duplica) con
     `parent = clave de la épica`. Si el tipo no es estándar, usa el primer tipo estándar.
  3. Campos enviados (`_fields_for`): título (máx. 250), descripción convertida a ADF (`to_adf`, soporta viñetas
     `- `), responsable (o `null` para desasignar), prioridad, story points, `duedate`, fecha de inicio.
     **No se envían etiquetas.**
  4. `_save_issue`: si Jira rechaza un campo opcional (prioridad, fecha fin, puntos, fecha inicio) porque no está
     en la pantalla del proyecto, reintenta sin él y lo avisa en el resultado.
  5. Al final mueve las tareas a su sprint en bloques de 50 (`POST /sprint/{id}/issue`).
  6. Pausa de 0,1 s entre tareas por el rate limit. Las claves obtenidas se guardan en el plan.
- Eliminar una tarea en la app **no** la borra en Jira.

### 5.6 Avance del sprint

- **Tareas subidas** (`sprint_issues`): JQL `sprint = N` sin épicas, ordenado por creación; el front cuenta
  tareas creadas por **día hábil** (lo de sábado/domingo se suma al lunes), acumulado y por día.
- **Informe de trabajo completado** (`sprint_burnup`): lee la API **interna** con la que Jira dibuja su propio
  informe, `greenhopper/1.0/rapid/charts/scopechangeburndownchart.json` (necesita `originBoardId` del sprint).
  Recorre los eventos (`added`, `statC` = puntos, `column.notDone`) y calcula en cada instante el **alcance**
  (puntos de tareas dentro del sprint) y los **cerrados** (relativos al inicio, para que empiecen en 0). Genera
  la tabla de actividad (tarea añadida / quitada / cerrada / reabierta / cambio de puntos).
  - Peculiaridad: esa API devuelve horas **locales del tablero escritas como si fueran UTC**; se corrigen con la
    zona horaria que trae `workRateData.timezone`.
  - Eje: del inicio al fin previsto; si el sprint sigue abierto después (o se cerró tarde), llega hasta hoy / el
    cierre y se marca el fin previsto.
  - Personal (`?assignee=`): mismo cálculo filtrando las tareas **asignadas hoy** a esa persona (no refleja
    reasignaciones durante el sprint). Por defecto se muestra el usuario dueño del token.
- Front: colores como Jira (alcance rojo, completado verde, directriz gris de 0 al alcance actual), líneas en
  escalón, «Hoy» y alcance proyectado punteado. Datos se recargan al abrir la vista, cambiar de sprint o pulsar ↻.

### 5.7 Interfaz (`static/index.html`)

Un solo archivo (~1000 líneas). Partes principales del JS:

- Arranque: `init()` → `/api/config` y `/api/state`; el proveedor de IA elegido y la vista se recuerdan en
  `localStorage`. `#sprint` en la URL abre directamente la vista del sprint.
- **⚙️ Configuración** (`openConfig`, `saveConfig`): responsable, sprint y fechas por defecto; opción de
  aplicarlos a todas las tareas pendientes de subir.
- **Nuevo desglose** (`setMode`): ✍️ Escribir (`breakdownText`), 📄 Subir archivos (`breakdownFiles`, uno por
  petición) y 📋 Lista rápida (`bulkCreate`, sin IA: una tarea por línea, `# PROYECTO` cambia de épica,
  `título | puntos` opcional).
- **Tabla** (`renderTasks`, `renderFilters`, `renderTotals`): edición en línea de todos los campos, filtros
  por épica / persona / estado, selección múltiple (`applyBulk`, borrar, subir seleccionadas), detalle
  desplegable con la descripción, gestor de épicas (`openEpics`). `formatTitle` (versión JS) re-titula al
  cambiar de épica.
- Autoguardado: `queueSave()` → `flushSave()` (`PUT /api/plan`).
- **Subir a Jira** (`pushToJira`): confirma nuevas / actualizadas / sin responsable y muestra resultados con
  enlaces (`renderResults`).
- **Sprint**: `setView`, `loadSprintChart`, `renderSprintChart`, `sprintDays`, `drawSprintChart`,
  `drawBurnup`, `drawMine`, `chartFrame`, `chartHover`.

---

## 6. Reglas de negocio (decididas por el responsable del proyecto)

Estas reglas no son técnicas: son decisiones del equipo. No cambiarlas sin consultarlo.

- **Épica = proyecto.** Si el proyecto ya existe como épica en Jira, se reutiliza; las nuevas van en MAYÚSCULAS.
- **Títulos**: `PROYECTO - descripción diciente - info adicional`. El proyecto es el nombre exacto de la épica;
  la descripción la debe entender alguien no técnico (jefe de proyecto): verbo en infinitivo + qué + para qué.
- **Tamaño de tarea**: 1 story point = un entregable con sentido propio (de unas horas a un día). Los pasos
  (analizar, codificar, probar…) van como viñetas en la descripción, no como tareas. Nada de tareas triviales,
  repetidas ni inventadas. Referencia: un día de registro suele dar 1–4 tareas.
- **En Jira** cada tarea lleva solo su épica como padre. **No se envían etiquetas** (las tareas antiguas que ya
  tenían etiquetas en Jira las conservan).
- **Fechas**: solo las de Configuración; vacías = inicio hoy, fin último día del mes actual. Las fechas del texto
  se ignoran.
- **Gráficas del sprint**: deben verse y comportarse **igual que el informe de Jira**, con la única diferencia de
  quitar los fines de semana. No añadir métricas ni estilos propios.

Para ajustar el comportamiento del desglose, el único sitio es `SYSTEM_PROMPT` en `tareas_app/llm.py`
(lo comparten las tres IAs).

---

## 7. Historial de cambios relevante

| Fecha | Cambio |
|---|---|
| 2026-09-28 | Primera versión: desglose con IA (Claude Code / API de Claude / Ollama), tabla editable y subida a Jira. |
| 2026-09-29 | Se dejan de enviar etiquetas a Jira. Se reescribe el prompt para evitar sobre-división y repeticiones. Fechas solo desde Configuración. Se añaden `.claude/` y el grafo `graphify-out/`. |
| 2026-09-30 | Vista «📈 Avance del sprint» (informe de trabajo completado del equipo y personal, tareas por día, sin fines de semana). README reescrito como documentación neutra. |
| 2026-10-05/06 | Herramienta `planner/` para Microsoft Planner (aún sin commit). |

## 8. Pendientes y puntos débiles conocidos

- El prompt nuevo de desglose no se ha validado a fondo con desgloses reales; revisar la calidad cuando se use.
- Nadie ha comparado punto a punto el informe de trabajo completado de la app con el de Jira.
- La API `greenhopper` **no es pública**: Atlassian puede cambiarla sin aviso y romper el informe.
- El selector de sprint solo muestra sprints **activos y futuros** (no cerrados).
- La caché de metadatos de Jira dura 10 min: si se crean épicas o sprints nuevos en Jira, pulsar ↻.
- No hay tests automatizados. Para validar lógica se usan scripts cortos, p. ej.:
  ```bash
  .venv/bin/python -c "from tareas_app.llm import format_title; print(format_title('META - WHATSAPP', 'META - WHATSAPP - Configurar webhook'))"
  ```
- Un único espacio de trabajo y sin usuarios: es una app personal/local, no está pensada para exponerse en red
  (no tiene autenticación; no cambiar `--host` a `0.0.0.0`).

---

## 9. Herramienta `planner/` (Microsoft Planner)

Independiente de la app (su propio `.venv` y `requirements.txt` con Playwright). Sirve para volcar tareas en un
plan de Planner (p. ej. el plan «Trazabilidad») **sin API de Microsoft Graph**, controlando la web.

- `instalar.sh`: crea `planner/.venv` (usa el Chrome del sistema, no descarga navegadores).
- `abrir_chrome.sh`: abre un Chrome aparte con perfil propio (`planner/chrome-perfil/`, en `.gitignore`) y puerto
  de depuración **9333**. Hay que iniciar sesión en Planner en esa ventana y dejarla abierta.
- `planner.py` (se conecta por CDP a ese Chrome):
  - `ver --plan X`: lista depósitos y tareas (solo lectura).
  - `aplicar --plan X tareas.json [--simular]`: crea las que no existen (clave = título exacto) y completa
    campos. Fechas y descripción solo se escriben si están vacías; depósito y estado siempre se fuerzan.
  - `borrar --plan X "Título"` y `asignar --plan X "Nombre" [--simular]`.
- Formato del JSON y detalles en `planner/README.md`; ejemplos en `ejemplo_tareas.json`,
  `validacion_tareas.json` y `recolecciones_tareas.json`.
- Frágil por diseño: depende de los textos de la interfaz de Planner en español y de posiciones de pantalla
  (viewport 1600×1000). Si Microsoft cambia la interfaz, hay que ajustar `planner.py`.

---

## 10. Trabajar con Claude Code en este repo

- `.claude/CLAUDE.md`: resumen del proyecto y reglas para el asistente (responder en español, no mostrar `.env`,
  no borrar `tareas.db`, reglas de negocio).
- `.claude/settings.json`: permite `./tareas check` y scripts `.venv/bin/python -c`; **deniega leer `.env`**.
- `graphify-out/`: grafo de conocimiento del código (opcional, se consulta con la skill `/graphify`).
  Ojo: graphify no analiza el JS dentro de `.html`; para incluir las funciones de la interfaz hubo que extraer
  el `<script>` a un `.js` temporal y reasignarlo a `index.html`. Un `graphify --update` normal las pierde.

## 11. Otros archivos en la carpeta

- `Tareas de trazabilidad Servientrega en Jira.docx`: documento de trabajo del proyecto Trazabilidad
  (Servientrega); no lo usa el código.

## 12. Checklist para quien recoge el proyecto

1. Clonar, crear `.venv` e instalar dependencias.
2. Crear su propio `.env` con **su** token de Jira y el proyecto correcto.
3. Elegir IA: lo más simple es tener Claude Code instalado con sesión iniciada (`LLM_PROVIDER=claude_code`).
4. `./tareas check` y verificar que detecta campos de story points y fecha de inicio (si no, fijarlos en `.env`).
5. `./tareas`, revisar ⚙️ Configuración (responsable, sprint) y hacer un desglose de prueba **sin subirlo**.
6. Antes de cambiar reglas de desglose, títulos, fechas o gráficas, leer la sección 6.
