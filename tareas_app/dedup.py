"""Detección de subtareas repetidas: compara títulos por parecido, no solo por igualdad exacta."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Palabras que no distinguen una tarea de otra
_STOP = set("""a al con de del el en la las lo los para por que se su sus un una uno y o e u
como desde entre hacia hasta sin sobre tras ya mas ademas""".split())


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"[\W_]+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


def core(title: str, epic: str | None = None) -> str:
    """Parte que describe el trabajo: sin el prefijo del proyecto ("PROYECTO - …")."""
    parts = [p for p in re.split(r"\s+-\s+", title.strip()) if p]
    if epic:
        target = _plain(epic)
        for k in range(1, len(parts)):
            if _plain(" - ".join(parts[:k])) == target:
                parts = parts[k:]
                break
    elif len(parts) > 1 and not re.search(r"[a-záéíóúñ]", parts[0]):  # prefijo en mayúsculas
        parts = parts[1:]
    return _plain(" - ".join(parts))


def _tokens(text: str) -> set[str]:
    return {w[:6] for w in text.split() if w not in _STOP and len(w) > 1}  # raíz corta: "configurar" ≈ "configuración"


def similarity(a: str, b: str) -> tuple[float, float]:
    """(solapamiento de palabras significativas, parecido letra a letra), ambos 0..1. El primero distingue tareas
    con la misma plantilla ("menú de consola - opciones de logs" ≠ "… de estado"); el segundo detecta erratas."""
    if not a or not b:
        return 0.0, 0.0
    ta, tb = _tokens(a), _tokens(b)
    jac = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    return jac, SequenceMatcher(None, a, b).ratio()


def _numbers(text: str) -> set[str]:
    """Números de 3+ cifras del título (nº de servicio, ticket, OT…): si difieren, no es la misma tarea."""
    return set(re.findall(r"\d{3,}", text))


# Umbrales (palabras, letras): en la misma Historia basta con que se parezcan; en otra tienen que ser casi iguales
SAME_STORY = (0.7, 0.92)
OTHER_STORY = (0.8, 0.96)


def find_duplicate(title: str, parent: str | None, pool: list[dict], epic: str | None = None) -> dict | None:
    """Busca en `pool` (dicts con key, summary, parent) una incidencia que sea el mismo trabajo que `title`.
    Devuelve la más parecida que supere el umbral, o None."""
    c = core(title, epic)
    nums = _numbers(c)
    best, best_s = None, 0.0
    for it in pool:
        other = core(it["summary"], epic)
        if nums != _numbers(other):  # distinto nº de servicio/ticket/OT → trabajo distinto aunque el resto coincida
            continue
        jac, ratio = similarity(c, other)
        lim_j, lim_r = SAME_STORY if parent and it.get("parent") == parent else OTHER_STORY
        if (jac >= lim_j or ratio >= lim_r) and max(jac, ratio) > best_s:
            best, best_s = it, max(jac, ratio)
    return best
