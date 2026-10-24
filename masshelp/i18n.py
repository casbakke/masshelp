"""Fixed member-facing strings in English and Spanish.

Rules for these strings: .kiro/steering/plain-language.md. Other languages fall back
to English here; the LLM handles them in conversation (G5, best effort).
"""

from __future__ import annotations

from masshelp.util.lang import base_language

TEMPLATES: dict[str, dict[str, str]] = {
    # R32: first message of every SMS conversation.
    "disclosure_sms": {
        "en": "MassHelp here. I'm a free automated assistant, not MassHealth.",
        "es": "Le habla MassHelp. Soy un asistente automático gratuito, no MassHealth.",
    },
    # Prefix on texts sent by tools (document requests, confirmations).
    "sms_prefix": {
        "en": "MassHelp (automated assistant, not MassHealth): ",
        "es": "MassHelp (asistente automático, no MassHealth): ",
    },
    # R36
    "fallback": {
        "en": "Sorry, I had trouble with that. Can you say it another way?",
        "es": "Perdón, tuve un problema con eso. ¿Me lo puede decir de otra forma?",
    },
    "too_many_steps": {
        "en": "Sorry, that took me too long. Can you tell me again what you need?",
        "es": "Perdón, me tardé demasiado. ¿Me puede decir otra vez qué necesita?",
    },
    # R8
    "identity_locked": {
        "en": (
            "I'm sorry, I couldn't confirm who you are. For your safety I have to stop here. "
            "Please call MassHealth at {phone}. Goodbye from MassHelp."
        ),
        "es": (
            "Lo siento, no pude confirmar su identidad. Por su seguridad, tengo que parar aquí. "
            "Por favor llame a MassHealth al {phone}. Adiós de parte de MassHelp."
        ),
    },
    # R24
    "document_request": {
        "en": "{instructions} Reply here with the photo. Text STOP to stop messages.",
        "es": "{instructions} Responda aquí con la foto. Envíe STOP para dejar de recibir mensajes.",
    },
    # R29
    "confirmation": {
        "en": (
            "Your work rule form was sent to MassHealth (sample demo). Receipt number: {receipt}. "
            "Your form: {link} . The link works for 7 days. MassHealth makes the final decision. "
            "Questions? Call MassHealth at {phone}."
        ),
        "es": (
            "Su formulario de la regla de trabajo fue enviado a MassHealth (demo de muestra). "
            "Número de recibo: {receipt}. Su formulario: {link} . El enlace funciona por 7 días. "
            "MassHealth toma la decisión final. ¿Preguntas? Llame a MassHealth al {phone}."
        ),
    },
}


def t(key: str, lang: str | None, **kwargs: object) -> str:
    variants = TEMPLATES[key]
    text = variants.get(base_language(lang)) or variants["en"]
    return text.format(**kwargs) if kwargs else text


def has_translation(key: str, lang: str | None) -> bool:
    return base_language(lang) in TEMPLATES[key]
