# Tareas IA → Jira

Le cuentas a una IA (Claude o una IA local con Ollama) el trabajo realizado, o le pasas archivos
`.txt` de memoria/registro de cambios, y te genera un desglose en **épicas y tareas** con
**responsable, story points, tipo, prioridad y etiquetas**. Lo revisas y corriges en la app
(a mano o pidiéndoselo por chat) y lo subes a **Jira Cloud** con un botón.

## Instalación

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # y rellénalo
```

En `.env`:
- `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` ([crear token](https://id.atlassian.com/manage-profile/security/api-tokens)), `JIRA_PROJECT_KEY`.
- **Claude con tu cuenta (Pro/Team/Enterprise), sin API key:** basta con tener [Claude Code](https://claude.com/claude-code)
  instalado y con sesión iniciada (`claude` → `/login`). La app lo usa en modo no interactivo (`LLM_PROVIDER=claude_code`).
- Opcional: `ANTHROPIC_API_KEY` para usar la API de Anthropic directamente (`CLAUDE_MODEL`, por defecto `claude-opus-5-5`).
- `OLLAMA_URL` / `OLLAMA_MODEL` para la IA local. Recomendado un modelo de 7B+ (p.ej. `ollama pull qwen2.5:7b`);
  los de 3B funcionan pero desglosan peor.

## Uso

```bash
./tareas check    # comprueba conexión con Jira, Claude y Ollama
./tareas          # abre la app en http://127.0.0.1:8765
```

1. Escribe lo que hiciste ("Ana terminó el login con Google, Luis arregló el carrito…")
   y/o adjunta tus `.txt` de memoria (📎). Pulsa *Generar desglose* (Ctrl+Enter).
2. Revisa el plan a la derecha: edita títulos, descripciones, tipo, puntos, responsable, prioridad;
   mueve tareas entre épicas, añade o elimina. Se guarda solo.
3. Pestaña **Por persona**: qué tiene asignado cada uno y cuántos puntos suma.
4. También puedes pedir cambios por chat: "pon todo lo de pagos a Luis", "divide la épica de login en dos".
5. **Subir a Jira**: crea las épicas y sus tareas hijas. Lo que ya se subió (tiene clave `PRJ-123`)
   se **actualiza** en lugar de duplicarse. Quitar algo del plan no lo borra en Jira.

## Notas

- El equipo, tipos de incidencia y prioridades se leen del proyecto de Jira; la IA solo asigna a personas
  que existen allí (las que no, salen marcadas con ⚠).
- Story points: se detecta el campo automáticamente ("Story point estimate"/"Story Points"); si no,
  define `JIRA_STORY_POINTS_FIELD` (lo muestra `./tareas check`).
- Si Jira rechaza un campo opcional (prioridad, story points, etiquetas no están en la pantalla del
  proyecto), la incidencia se crea sin él y se avisa en el resultado.
- El plan y el chat se guardan en `tareas.db` (SQLite). "🧹 Limpiar" vacía el chat y los adjuntos sin tocar el plan.
