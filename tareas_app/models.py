"""Modelos de datos: lo que devuelve la IA y lo que se guarda/edita en la app."""
from __future__ import annotations

import calendar
import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


# ---------- Salida estructurada de la IA ----------

class AITask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(description="Título corto y accionable de la tarea")
    description: str = Field(description="Detalle de lo realizado / criterios de aceptación")
    issue_type: str = Field(description="Uno de los tipos de incidencia disponibles en el proyecto")
    story_points: float | None = Field(description="Estimación en story points (1,2,3,5,8,13) o null")
    assignee: str | None = Field(description="Nombre exacto de un miembro del equipo si el texto lo indica, o null")
    start_date: str | None = Field(description="Fecha de inicio YYYY-MM-DD si el texto la indica, o null")
    due_date: str | None = Field(description="Fecha de fin YYYY-MM-DD si el texto la indica, o null")
    labels: list[str] = Field(description="Etiquetas sin espacios")


class AIEpic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(description="id de una épica existente si las tareas pertenecen a ella; null si es nueva")
    summary: str
    description: str
    tasks: list[AITask]


class AIResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: str = Field(description="Resumen breve (1-2 frases) de lo desglosado")
    epics: list[AIEpic] = Field(description="Solo las tareas NUEVAS, agrupadas por épica")


# ---------- Datos de la app ----------

def _new_id() -> str:
    return uuid.uuid4().hex[:10]


class Task(BaseModel):
    id: str = Field(default_factory=_new_id)
    summary: str = ""
    description: str = ""
    issue_type: str = ""
    story_points: float | None = None
    assignee_id: str | None = None      # accountId de Jira
    assignee_name: str | None = None
    sprint_id: int | None = None
    sprint_name: str | None = None
    start_date: str | None = None       # YYYY-MM-DD
    due_date: str | None = None         # YYYY-MM-DD
    priority: str | None = None
    labels: list[str] = []
    jira_key: str | None = None


class Epic(BaseModel):
    id: str = Field(default_factory=_new_id)
    summary: str = ""
    description: str = ""
    labels: list[str] = []
    tasks: list[Task] = []
    jira_key: str | None = None
    linked: bool = False  # épica que ya existía en Jira: se usa su clave pero la app no la modifica


class Plan(BaseModel):
    epics: list[Epic] = []


def default_start_date() -> str:
    """Inicio por defecto: hoy."""
    return date.today().isoformat()


def default_due_date() -> str:
    """Fin por defecto: último día del mes actual."""
    t = date.today()
    return t.replace(day=calendar.monthrange(t.year, t.month)[1]).isoformat()


class Defaults(BaseModel):
    """Configuración aplicada a las tareas nuevas. Fechas vacías = automáticas (hoy / fin de mes)."""
    assignee_id: str | None = None
    assignee_name: str | None = None
    sprint_id: int | None = None
    sprint_name: str | None = None
    start_date: str | None = None
    due_date: str | None = None


class Workspace(BaseModel):
    id: str = "main"
    title: str = "Tareas"
    created_at: str = ""
    plan: Plan = Plan()
    defaults: Defaults = Defaults()
