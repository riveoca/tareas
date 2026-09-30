"""CLI:  python -m tareas_app [serve|check]"""
import argparse
import threading
import webbrowser

from .config import settings


def cmd_serve(args) -> None:
    import uvicorn

    url = f"http://{args.host}:{args.port}"
    print(f"Tareas IA → Jira en {url}  (Ctrl+C para salir)")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("tareas_app.server:app", host=args.host, port=args.port, log_level="warning")


def cmd_check(_args) -> None:
    import httpx

    from .jira import JiraClient, JiraError

    print("== Jira ==")
    try:
        jc = JiraClient()
        me = jc.myself()
        print(f"  Conectado como: {me.get('displayName')} ({me.get('emailAddress', '')})")
        meta = jc.metadata()
        print(f"  Proyecto: {meta['project']} - {meta['project_name']}")
        print("  Tipos:", ", ".join(f"{t['name']}({t['level']})" for t in meta["issue_types"]))
        print("  Equipo:", ", ".join(u["displayName"] for u in meta["users"]) or "(nadie asignable)")
        print("  Campo story points:", meta["story_points_field"] or "NO ENCONTRADO (define JIRA_STORY_POINTS_FIELD)")
        print("  Campo fecha de inicio:", meta["start_date_field"] or "NO ENCONTRADO (define JIRA_START_DATE_FIELD)")
        print(f"  Épicas abiertas: {len(meta['epics'])}")
        print("  Sprints:", ", ".join(f"{s['name']} ({s['state']})" for s in meta["sprints"]) or "(ninguno / tablero kanban)")
    except (JiraError, httpx.HTTPError) as e:
        print("  ERROR:", e)

    print("== Claude ==")
    import os
    print("  Modelo:", settings.claude_model, "| API key:", "sí" if os.getenv("ANTHROPIC_API_KEY") else "NO")

    print("== Ollama ==")
    try:
        tags = httpx.get(f"{settings.ollama_url}/api/tags", timeout=3).json()
        names = [m["name"] for m in tags.get("models", [])]
        ok = settings.ollama_model in names
        print(f"  {settings.ollama_url} OK. Modelo '{settings.ollama_model}':", "disponible" if ok else
              f"NO instalado (ollama pull {settings.ollama_model}). Disponibles: {', '.join(names)}")
    except httpx.HTTPError as e:
        print("  No disponible:", e)


def main() -> None:
    p = argparse.ArgumentParser(prog="tareas", description="Desglose de tareas con IA y subida a Jira")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="Arranca la app web (por defecto)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    sub.add_parser("check", help="Comprueba la conexión con Jira, Claude y Ollama")
    args = p.parse_args()
    if args.cmd == "check":
        cmd_check(args)
    else:
        if args.cmd is None:
            args = s.parse_args([])
        cmd_serve(args)


if __name__ == "__main__":
    main()
