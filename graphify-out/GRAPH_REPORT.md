# Graph Report - tareas  (2026-09-29)

## Corpus Check
- Corpus is ~9,888 words - fits in a single context window. You may not need a graph.

## Summary
- 206 nodes · 511 edges · 11 communities (10 shown, 1 thin omitted)
- Extraction: 90% EXTRACTED · 9% INFERRED · 1% AMBIGUOUS · INFERRED: 48 edges (avg confidence: 0.89)
- Token cost: 43,419 input · 0 output

## Community Hubs (Navigation)
- Configuración y servidor
- Desglose con IA (llm.py)
- Cliente Jira (JiraClient)
- Guía y reglas de negocio
- UI: épicas y creación de tareas
- UI: tabla, filtros y totales
- UI: arranque y llamadas a la API
- UI: edición de tareas
- UI: fechas y configuración
- Subida a Jira: campos y reglas
- Lanzador tareas

## God Nodes (most connected - your core abstractions)
1. `index.html (script)` - 71 edges
2. `JiraClient` - 26 edges
3. `renderTasks()` - 19 edges
4. `Plan` - 15 edges
5. `renderAll()` - 15 edges
6. `esc()` - 13 edges
7. `queueSave()` - 12 edges
8. `_add_to_plan()` - 11 edges
9. `_get()` - 11 edges
10. `bulkCreate()` - 11 edges

## Surprising Connections (you probably didn't know these)
- `Chat-based plan edits` --references--> `index.html (script)`  [AMBIGUOUS]
  README.md → tareas_app/static/index.html
- `Rule: dates only from Configuration (default today .. end of month)` --rationale_for--> `effDefaults()`  [INFERRED]
  .claude/CLAUDE.md → tareas_app/static/index.html
- `formatTitle()` --semantically_similar_to--> `_add_to_plan (epics, titles, assignee, dates, dedup)`  [INFERRED] [semantically similar]
  tareas_app/static/index.html → .claude/CLAUDE.md
- `python-multipart>=0.0.9` --conceptually_related_to--> `breakdownFiles()`  [INFERRED]
  requirements.txt → tareas_app/static/index.html
- `Push updates existing issues with jira_key instead of duplicating` --rationale_for--> `pushToJira()`  [INFERRED]
  README.md → tareas_app/static/index.html

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **User-decided business rules for task breakdown** — _claude_claude_no_labels_rule, _claude_claude_story_point_granularity, _claude_claude_date_rule, _claude_claude_title_format_rule [EXTRACTED 1.00]
- **Three LLM provider options sharing one prompt** — readme_claude_code_provider, readme_anthropic_api, readme_ollama_local_ai, _claude_claude_system_prompt [INFERRED 0.85]
- **Frontend calls to FastAPI backend via api()** — tareas_app_static_index_breakdowntext, tareas_app_static_index_breakdownfiles, tareas_app_static_index_saveconfig, tareas_app_static_index_flushsave, tareas_app_static_index_pushtojira, tareas_app_static_index_init [EXTRACTED 1.00]

## Communities (11 total, 1 thin omitted)

### Community 0 - "Configuración y servidor"
Cohesion: 0.10
Nodes (31): Connection, post, put, Settings, Desglose automático de tareas con IA (Claude u Ollama) y subida a Jira Cloud., JiraError, Exception, Cliente mínimo de las APIs REST v3 y Agile de Jira Cloud. (+23 more)

### Community 1 - "Desglose con IA (llm.py)"
Cohesion: 0.15
Nodes (29): _add_to_plan(), breakdown(), _call_claude(), _call_claude_code(), _call_ollama(), claude_code_available(), _context_text(), format_title() (+21 more)

### Community 2 - "Cliente Jira (JiraClient)"
Cohesion: 0.14
Nodes (13): JiraClient, Épicas no terminadas del proyecto., Todo lo que la app y la IA necesitan saber del proyecto., Crea (key=None) o actualiza una incidencia. Si Jira rechaza un campo opcional…, Sube el plan a Jira: crea lo nuevo y actualiza lo que ya tiene clave. Con…, Texto plano -> Atlassian Document Format (párrafos y viñetas simples)., Tipos del proyecto con su nivel: 1 = épica, 0 = estándar, -1 = subtarea., Sprints activos y futuros de los tableros del proyecto (vacío si ningún tablero… (+5 more)

### Community 3 - "Guía y reglas de negocio"
Cohesion: 0.10
Nodes (26): _add_to_plan (epics, titles, assignee, dates, dedup), Rule: dates only from Configuration (default today .. end of month), '.env' with Jira token (do not expose), LLM providers: claude_code, claude, ollama, No tests; validate with short .venv scripts, Rule: 1 story point = one meaningful deliverable, SYSTEM_PROMPT (shared by 3 providers), tareas.db (user's real plan, JSON persistence) (+18 more)

### Community 4 - "UI: épicas y creación de tareas"
Cohesion: 0.21
Nodes (20): Chat-based plan edits, Por persona tab (assignments and points per person), index.html (script), addTask(), browse(), bulkCreate(), createEpic(), createEpicFromDlg() (+12 more)

### Community 5 - "UI: tabla, filtros y totales"
Cohesion: 0.22
Nodes (14): allTasks(), openConfig(), priorities(), renderBulk(), renderFilters(), renderResults(), renderTasks(), renderTotals() (+6 more)

### Community 6 - "UI: arranque y llamadas a la API"
Cohesion: 0.33
Nodes (14): api(), breakdownFiles(), breakdownText(), esc(), flushSave(), init(), pickFiles(), pushToJira() (+6 more)

### Community 7 - "UI: edición de tareas"
Cohesion: 0.28
Nodes (13): applyBulk(), changeEpic(), deleteTasks(), findTask(), moveTask(), queueSave(), readConfig(), setAssignee() (+5 more)

### Community 8 - "UI: fechas y configuración"
Cohesion: 0.36
Nodes (9): autoDue(), autoStart(), dateHints(), effDefaults(), fmtDate(), iso(), renderDefaults(), saveConfig() (+1 more)

### Community 9 - "Subida a Jira: campos y reglas"
Cohesion: 0.29
Nodes (7): _fields_for (Jira fields sent), Rule: task has only its epic as parent, no labels sent, push_plan (Jira create/update), Push updates existing issues with jira_key instead of duplicating, Breakdown includes labels (etiquetas), Optional field fallback when Jira rejects a field, Story points field auto-detection / JIRA_STORY_POINTS_FIELD

## Ambiguous Edges - Review These
- `index.html (script)` → `Chat-based plan edits`  [AMBIGUOUS]
  README.md · relation: references
- `Rule: task has only its epic as parent, no labels sent` → `Breakdown includes labels (etiquetas)`  [AMBIGUOUS]
  README.md · relation: conceptually_related_to
- `tareas.db (user's real plan, JSON persistence)` → `Tareas IA -> Jira (README)`  [AMBIGUOUS]
  README.md · relation: references

## Knowledge Gaps
- **12 isolated node(s):** `pickedFiles`, `selected`, `expanded`, `drop`, `./tareas check (Jira/Claude/Ollama connectivity)` (+7 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `index.html (script)` and `Chat-based plan edits`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **What is the exact relationship between `Rule: task has only its epic as parent, no labels sent` and `Breakdown includes labels (etiquetas)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `tareas.db (user's real plan, JSON persistence)` and `Tareas IA -> Jira (README)`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **Why does `index.html (script)` connect `UI: épicas y creación de tareas` to `Guía y reglas de negocio`, `UI: tabla, filtros y totales`, `UI: arranque y llamadas a la API`, `UI: edición de tareas`, `UI: fechas y configuración`?**
  _High betweenness centrality (0.184) - this node is a cross-community bridge._
- **Why does `JiraClient` connect `Cliente Jira (JiraClient)` to `Configuración y servidor`, `Desglose con IA (llm.py)`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Why does `Tareas IA -> Jira (project guide)` connect `Guía y reglas de negocio` to `Subida a Jira: campos y reglas`, `UI: épicas y creación de tareas`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `JiraClient` (e.g. with `Epic` and `Plan`) actually correct?**
  _`JiraClient` has 4 INFERRED edges - model-reasoned connections that need verification._