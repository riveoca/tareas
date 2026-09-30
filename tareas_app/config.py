import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    jira_url: str = _env("JIRA_URL").rstrip("/")
    jira_email: str = _env("JIRA_EMAIL")
    jira_api_token: str = _env("JIRA_API_TOKEN")
    jira_project_key: str = _env("JIRA_PROJECT_KEY")
    jira_story_points_field: str = _env("JIRA_STORY_POINTS_FIELD")
    jira_start_date_field: str = _env("JIRA_START_DATE_FIELD")
    # Story points que se ponen a cada tarea generada; vacío = no se ponen (se estiman en Jira)
    task_story_points: float | None = float(_env("TASK_STORY_POINTS")) if _env("TASK_STORY_POINTS") else None

    llm_provider: str = _env("LLM_PROVIDER", "claude_code")
    claude_code_bin: str = _env("CLAUDE_CODE_BIN", "claude")
    claude_code_model: str = _env("CLAUDE_CODE_MODEL")
    claude_model: str = _env("CLAUDE_MODEL", "claude-opus-5-5")
    claude_effort: str = _env("CLAUDE_EFFORT", "medium")
    claude_fallbacks: str = _env("CLAUDE_FALLBACKS", "default")
    ollama_url: str = _env("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    ollama_model: str = _env("OLLAMA_MODEL", "qwen2.5-coder:3b")

    db_path: Path = ROOT / _env("TAREAS_DB", "tareas.db")

    @property
    def jira_configured(self) -> bool:
        return all([self.jira_url, self.jira_email, self.jira_api_token, self.jira_project_key])


settings = Settings()
