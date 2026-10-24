"""Light language guess, used only to pick the disclosure language for unknown numbers.

The LLM handles real language switching through the set_language tool (R11).
"""

from __future__ import annotations

import re

_SPANISH_WORDS = {
    "hola", "buenos", "buenas", "gracias", "carta", "recibí", "recibi", "ayuda",
    "necesito", "quiero", "español", "espanol", "trabajo", "sí", "por", "favor",
    "tengo", "qué", "que", "cómo", "como", "usted", "seguro", "salud",
}


def guess_language(text: str | None) -> str | None:
    """Return "es" if the text looks Spanish, else None (unknown)."""
    if not text:
        return None
    lowered = text.lower()
    if re.search(r"[ñ¿¡]", lowered):
        return "es"
    words = set(re.findall(r"[a-záéíóúü]+", lowered))
    hits = len(words & _SPANISH_WORDS)
    if hits >= 2 or (hits == 1 and len(words) <= 3):
        return "es"
    return None


LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "pt": "Portuguese",
    "ht": "Haitian Creole",
    "zh": "Chinese",
    "vi": "Vietnamese",
    "ru": "Russian",
    "ar": "Arabic",
}


def language_name(code: str | None) -> str:
    if not code:
        return "English"
    base = code.split("-")[0].lower()
    return LANGUAGE_NAMES.get(base, code)


def base_language(code: str | None) -> str:
    return (code or "en").split("-")[0].lower()
