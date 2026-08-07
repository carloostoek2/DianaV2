"""Strong-signal heuristic for profile resynthesis (SPEC-EVOLUCION-AGENTE 1.1, cond c).

Pure module: no I/O, no LLM, no aiogram (import-purity preserved). It matches
introspección / confianza / proyecto-de-vida language in a VIP message to
decide whether the Fase 1 profile should be resynthesized NOW (outside the
volume window).

The FORM follows ``j4_triggers.match_keywords`` (word-boundary regex for single
words, substring for phrases); the CONTENT is deliberately DISJOINT from
``PAGO_KEYWORDS`` / ``COMPROMISO_KEYWORDS`` — payment/commitment never triggers
a resynthesis. This is the synthesized LLM profile (Fase 1), DISTINTO de
``profiles`` (tabla vector, ``repositories/memories.py``) y de ``/vip_profile``
(comando legacy admin). A strong signal is unrelated to escalation.
"""

from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger("diana.application")


def _fold(text: str) -> str:
    """Lowercase + strip diacritics (NFKD) for accent-insensitive matching.

    Mexican VIP chat routinely drops accents ("no se que hacer"); folding both
    the term and the message to a canonical de-accented form makes the accented
    term ("no sé qué hacer") match the accent-less text (fix round S4).
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))

# Own strong-signal vocabulary — introspection / trust / life plan. NEVER
# payment/commitment keywords (those live in j4_triggers.py, out of scope).
_STRONG_SIGNAL_TERMS: tuple[str, ...] = (
    # Introspección / apertura personal.
    "me siento",
    "siento que",
    "me pasa que",
    "no sé qué hacer",
    "me cuesta",
    "me da miedo",
    "tengo miedo",
    "me preocupa",
    "me preocupan",
    "necesito hablar",
    "quiero contarte",
    "a veces siento",
    "estoy pensando",
    "he estado pensando",
    "me estoy dando cuenta",
    "no me siento bien",
    "me siento solo",
    "me siento sola",
    # Confianza / vínculo.
    "confiar",
    "confianza",
    "confío",
    "te tengo confianza",
    # Proyecto de vida / identidad.
    "mi futuro",
    "plan de vida",
    "proyecto de vida",
    "quién soy",
    "cambiar de vida",
    "mi familia",
    "mi mamá",
    "mi papá",
    "mi relación",
    "lo que más quiero",
    "mi sueño",
    "mis metas",
)


def match(text: str | None) -> bool:
    """True if ``text`` carries a strong profile-synthesis signal.

    Empty/None text never matches. Case- and accent-insensitive (S4): a
    single-word term is matched at word boundaries, a phrase by substring — the
    same semantics as ``j4_triggers.match_keywords``, with both sides folded to
    a de-accented form. Returns True when ANY term matches.
    """
    if not text:
        return False
    folded = _fold(text)
    for term in _STRONG_SIGNAL_TERMS:
        k = _fold(term.strip())
        if not k:
            continue
        if " " in k:
            if k in folded:
                return True
        else:
            if re.search(rf"\b{re.escape(k)}\b", folded, flags=re.IGNORECASE):
                return True
    return False


__all__ = ["_STRONG_SIGNAL_TERMS", "match"]
