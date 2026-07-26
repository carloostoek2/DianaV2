"""J.4 deterministic text triggers (pre-Director) — pure match, no LLM.

Identifiers in English; match strings and IA template are Spanish product content
(Anexo J.4). Classification priority: identidad_ia → pago_precio → compromiso_real.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

J4Category = Literal["identidad_ia", "pago_precio", "compromiso_real"]

IA_TEMPLATE = "jsjsj si y sólo vivo en tu mente 😏"

# Prefer second-person / question-like forms for identity probes.
# Bare "chatbot" / "inteligencia artificial" alone omitted (high FP).
IDENTIDAD_IA_KEYWORDS = [
    "eres ia",
    "eres una ia",
    "sos ia",
    "sos una ia",
    "eres un bot",
    "sos un bot",
    "eres bot",
    "sos bot",
    "eres una inteligencia artificial",
    "sos una inteligencia artificial",
    "eres un robot",
    "sos un robot",
    "sos real o",
    "eres real o",
    "eres real",
    "sos real",
    "eres real?",
    "sos real?",
    "chatgpt",
    "eres chatgpt",
    "sos chatgpt",
    "eres un chatbot",
    "sos un chatbot",
    "eres chatbot",
    "sos chatbot",
]

PAGO_KEYWORDS = [
    "precio",
    "precios",
    "pago",
    "pagos",
    "pagar",
    "pagado",
    "pagada",
    "suscripción",
    "suscripcion",
    "abono",
    "reembolso",
    "reembolsos",
    "tarifa",
    "tarifas",
    "cuesta",
    "costo",
    "costos",
    "cuánto sale",
    "cuanto sale",
    "cuánto cuesta",
    "cuanto cuesta",
    "cuánto vale",
    "cuanto vale",
    "cuánto es",
    "cuanto es",
    "transferencia",
    "mercadopago",
    "mercado pago",
    "paypal",
    "reclamo",
    "reclamar",
    "cobrar",
    "cobro",
]

# Commitment / real-world meet — tighten broad tokens (no bare "quedar").
# Residual FP risk remains on short "cita"/"encuentro" (Anexo product terms).
COMPROMISO_KEYWORDS = [
    "cita",
    "citas",
    "una cita",
    "hacer una cita",
    "agendar cita",
    "encuentro",
    "encuentros",
    "vernos",
    "nos vemos",
    "quedemos",
    "acuerdo",
    "acuerdos",
    "acuerdo de",
    "contenido personalizado",
    "pack personalizado",
    "videollamada",
    "video llamada",
]


@dataclass(frozen=True)
class J4Hit:
    """Result of classify_j4_text."""

    category: J4Category
    tipo: str
    keywords_hit: list[str]
    template: str | None = None


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    """Case-insensitive word-boundary (token) or substring (phrase) match."""
    if not text or not keywords:
        return []
    lower = text.lower()
    hits: list[str] = []
    for kw in keywords:
        k = (kw or "").strip().lower()
        if not k:
            continue
        if " " in k:
            if k in lower:
                hits.append(kw.strip())
        else:
            if re.search(rf"\b{re.escape(k)}\b", lower, flags=re.IGNORECASE):
                hits.append(kw.strip())
    return hits


def classify_j4_text(text: str) -> J4Hit | None:
    """Classify VIP text into a J.4 category; first non-empty category wins."""
    if not text or not str(text).strip():
        return None

    ia_hits = match_keywords(text, IDENTIDAD_IA_KEYWORDS)
    if ia_hits:
        return J4Hit(
            category="identidad_ia",
            tipo="identidad_ia",
            keywords_hit=ia_hits,
            template=IA_TEMPLATE,
        )

    pago_hits = match_keywords(text, PAGO_KEYWORDS)
    if pago_hits:
        return J4Hit(
            category="pago_precio",
            tipo="pago_precio",
            keywords_hit=pago_hits,
            template=None,
        )

    compromiso_hits = match_keywords(text, COMPROMISO_KEYWORDS)
    if compromiso_hits:
        return J4Hit(
            category="compromiso_real",
            tipo="compromiso_real",
            keywords_hit=compromiso_hits,
            template=None,
        )

    return None


__all__ = [
    "COMPROMISO_KEYWORDS",
    "IA_TEMPLATE",
    "IDENTIDAD_IA_KEYWORDS",
    "J4Category",
    "J4Hit",
    "PAGO_KEYWORDS",
    "classify_j4_text",
    "match_keywords",
]
