"""Owner-facing Spanish labels and tipo mapping for escalation reasons.

Machine `tipo` / `reason` stay stable English/snake_case for stores and parsers.
Spanish strings are display-only (owner DM).
"""

from __future__ import annotations

# Deterministic / Decider / J.4 reasons that are themselves a tipo.
SYSTEM_ESCALATION_TIPOS = frozenset(
    {
        "frustracion_directa",
        "pregunta_repetida",
        "pago_precio",
        "compromiso_real",
        "identidad_ia",
        "palabra_prohibida",
    }
)

_LABELS_ES: dict[str, str] = {
    "frustracion_directa": "Frustración directa (VIP molesta)",
    "pregunta_repetida": "Pregunta repetida",
    "pago_precio": "Pago / precio",
    "compromiso_real": "Compromiso real",
    "identidad_ia": "Identidad IA",
    "palabra_prohibida": "Palabra prohibida",
    "semantica": "Semántica",
}


def tipo_from_reason(reason: str) -> str:
    """Map decision.reason to escalation tipo; default semantica."""
    if reason in SYSTEM_ESCALATION_TIPOS:
        return reason
    return "semantica"


def label_es_for_tipo(tipo: str) -> str:
    """Human Spanish label for owner DM; falls back to raw tipo."""
    return _LABELS_ES.get(tipo, tipo)


__all__ = [
    "SYSTEM_ESCALATION_TIPOS",
    "tipo_from_reason",
    "label_es_for_tipo",
]
