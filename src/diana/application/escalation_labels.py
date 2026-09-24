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

# Owner-facing message per false-positive resume key (AGENTS §4.21). One source
# for both entry points (the escalation DM button and the /fp command), so the
# same fact is never written twice with different wording. Keys are the
# ``FpResumeKey`` vocabulary; ``marked`` is the neutral fallback.
FP_RESUME_MESSAGES_ES: dict[str, str] = {
    "draft_sent": (
        "Falso positivo marcado ✅\nTe envié el borrador para aprobar."
    ),
    "blocked_safety": (
        "Falso positivo marcado ✅\nNo generé borrador: ese turno se frenó por "
        "seguridad. Puedes responder manualmente al suscriptor."
    ),
    "skipped_new_turn": (
        "Falso positivo marcado ✅\nEl suscriptor ya escribió algo nuevo: ese "
        "mensaje quedó reemplazado. Atiende el turno nuevo."
    ),
    "skipped_owner_wrote": (
        "Falso positivo marcado ✅\nYa escribiste tú en ese chat después de la "
        "escalación, así que no generé borrador para no duplicar tu respuesta."
    ),
    "skipped_no_vip_text": (
        "Falso positivo marcado ✅\nNo pude recuperar el mensaje original para "
        "generar el borrador. Puedes responderle a mano."
    ),
    "skipped_no_draft_generated": (
        "Falso positivo marcado ✅\nNo pude preparar un borrador usable para "
        "ese turno. Puedes responderle a mano."
    ),
    "skipped_no_connection": (
        "Falso positivo marcado ✅\nNo pude preparar el borrador: falta la "
        "conexión de negocio de ese chat. Puedes responderle a mano."
    ),
    "skipped_unavailable": (
        "Falso positivo marcado ✅\nNo pude preparar el borrador porque el "
        "generador no está disponible en este momento. Puedes responderle a mano."
    ),
    "skipped_in_progress": (
        "Falso positivo marcado ✅\nYa estaba preparando el borrador de ese "
        "turno; te llega en un momento."
    ),
    "skipped_error": (
        "Falso positivo marcado ✅\nNo pude preparar el borrador. Puedes "
        "responderle a mano."
    ),
    "stale": (
        "Falso positivo marcado ✅\nEse turno ya no aplica: se resolvió, lo "
        "reemplazó otro más reciente o el suscriptor ya recibió respuesta."
    ),
    "marked": "Falso positivo marcado ✅",
    "failed": "No se pudo marcar",
}


def tipo_from_reason(reason: str) -> str:
    """Map decision.reason to escalation tipo; default semantica."""
    if reason in SYSTEM_ESCALATION_TIPOS:
        return reason
    return "semantica"


def label_es_for_tipo(tipo: str) -> str:
    """Human Spanish label for owner DM; falls back to raw tipo."""
    return _LABELS_ES.get(tipo, tipo)


def fp_resume_message(key: str) -> str:
    """Owner-facing message for a resume key; neutral fallback when unknown."""
    return FP_RESUME_MESSAGES_ES.get(key) or FP_RESUME_MESSAGES_ES["marked"]


__all__ = [
    "FP_RESUME_MESSAGES_ES",
    "SYSTEM_ESCALATION_TIPOS",
    "fp_resume_message",
    "label_es_for_tipo",
    "tipo_from_reason",
]
