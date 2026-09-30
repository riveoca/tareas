"""Persistencia simple en SQLite: el espacio de trabajo se guarda como JSON."""
import sqlite3
from datetime import datetime

from .config import settings
from .models import Workspace


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sessions ("
        " id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT, data TEXT)"
    )
    return conn


def get_session(session_id: str) -> Workspace | None:
    with _conn() as conn:
        row = conn.execute("SELECT data FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return Workspace.model_validate_json(row[0]) if row else None


def save_session(session: Workspace) -> Workspace:
    now = datetime.now().isoformat(timespec="seconds")
    if not session.created_at:
        session.created_at = now
    with _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, data) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET title=excluded.title, updated_at=excluded.updated_at,"
            " data=excluded.data",
            (session.id, session.title, session.created_at, now, session.model_dump_json()),
        )
    return session

