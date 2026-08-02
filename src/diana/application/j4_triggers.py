"""J.4 deterministic text triggers (pre-Director) — pure match, no LLM.

Identifiers in English; match strings and IA template are Spanish product content
(Anexo J.4). Classification priority: pago_precio → compromiso_real.

H6: ``identidad_ia`` is no longer returned by ``classify_j4_text``. Pure IA probes
fall through to CognitiveDirector TemplateGate (supervised approve). Hybrid text
with payment/commitment keywords escalates as pago/compromiso only.

``IA_TEMPLATE`` / ``IDENTIDAD_IA_KEYWORDS`` / category literal value remain for
historical labels and dead-path helper unit tests; the classifier never emits
``identidad_ia``.
"""


from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

J4Category = Literal["pago_precio", "compromiso_real"]

IA_TEMPLATE = "jsjsj si y sólo vivo en tu mente 😏"

# Prefer second-person / question-like forms for identity probes.
# Bare "chatbot" / "inteligencia artificial" alone omitted (high FP).
IDENTIDAD_IA_KEYWORDS = [
    "eres ia",
    "eres una ia",
    "eres una ai",
    "eres ai",
    "sos ia",
    "sos una ia",
    "sos una ai",
    "sos ai",
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
    "sos humano",
    "eres humano",
    "sos humano?",
    "eres humano?",
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
    "pagué",
    "pague",
    "pagó",
    "pago",
    "pagado",
    "pagada",
    "factura",
    "facturas",
    "descuento",
    "descuentos",
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
    "cuánto te sale",
    "cuanto te sale",
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
    "usd",
    "mxn",
    "ars",
    "reclamo",
    "reclamar",
    "cobrar",
    "cobro",
]

# Commitment / real-world meet — tighten broad tokens (no bare "quedar").
# Residual FP risk remains on short "cita"/"encuentro"/"nos vemos" (Anexo terms).
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
    """Result of classify_j4_text (pago_precio or compromiso_real only).

    H6: ``identidad_ia`` is never emitted; pure IA probes go to TemplateGate.
    ``also_matched`` remains for historical/helper callers but classifiers no
    longer populate hybrid co-hits.
    """

    category: J4Category
    tipo: str
    keywords_hit: list[str]
    template: str | None = None
    also_matched: tuple[str, ...] = ()



def match_keywords(text: str, keywords: list[str]) -> list[str]:
    """Case-insensitive word-boundary (token) or substring (phrase) match."""
    if not text or not keywords:
        return []
    lower = text.lower()
    hits: list[str] = []
    seen: set[str] = set()
    for kw in keywords:
        k = (kw or "").strip().lower()
        if not k or k in seen:
            continue
        if " " in k:
            if k in lower:
                hits.append(kw.strip())
                seen.add(k)
        else:
            if re.search(rf"\b{re.escape(k)}\b", lower, flags=re.IGNORECASE):
                hits.append(kw.strip())
                seen.add(k)
    return hits


def classify_j4_text(text: str) -> J4Hit | None:
    """Classify VIP text into a residual J.4 category; first non-empty wins.

    Priority: pago_precio → compromiso_real. Never returns ``identidad_ia``
    (H6 TemplateGate owns pure IA probes in Cognitive Core).
    """
    if not text or not str(text).strip():
        return None

    pago_hits = match_keywords(text, PAGO_KEYWORDS)
    compromiso_hits = match_keywords(text, COMPROMISO_KEYWORDS)

    if pago_hits:
        return J4Hit(
            category="pago_precio",
            tipo="pago_precio",
            keywords_hit=pago_hits,
            template=None,
        )

    if compromiso_hits:
        return J4Hit(
            category="compromiso_real",
            tipo="compromiso_real",
            keywords_hit=compromiso_hits,
            template=None,
        )

    return None



def format_j4_motivo(hit: J4Hit) -> str:
    """Build owner-facing motivo including co-matched categories when present."""
    base = ",".join(hit.keywords_hit) if hit.keywords_hit else hit.tipo
    if hit.also_matched:
        return f"{base} [also: {','.join(hit.also_matched)}]"
    return base


__all__ = [
    "COMPROMISO_KEYWORDS",
    "IA_TEMPLATE",
    "IDENTIDAD_IA_KEYWORDS",
    "J4Category",
    "J4Hit",
    "PAGO_KEYWORDS",
    "classify_j4_text",
    "format_j4_motivo",
    "match_keywords",
]
