
"""Pure deterministic template matcher for short VIP replies (H6).

No I/O, no LLM. Cognitive Core only — does not import application/telegram/behavior.

Local ``_kw_hit`` is inspired by ``application.j4_triggers.match_keywords`` but is
stricter: multi-word phrases use non-word lookarounds on both sides (not bare
substring), so ``eres real`` does not match ``eres realmente`` / ``realista``.
"""


from __future__ import annotations

import random
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TemplateRule:
    """One fixed-template reply rule evaluated in list order."""

    id: str
    trigger_patterns: list[str]
    max_words: int | None
    response_pool: list[str]
    reason: str


# Historical saludo_constante shape (H6). Production no longer wires that
# TemplateRule pre-pipeline; the post-Analyst cut reuses the same lock so a
# mislabeled intent=saludar cannot canned-reply to real requests.
PURE_GREETING_MAX_WORDS = 4
PURE_GREETING_PATTERNS = (
    "hola",
    "holaa",
    "holis",
    "buenas",
    "buenos días",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "hey",
    "qué tal",
    "que tal",
)

# Allowed leftover tokens after stripping the greeting keyword (affection /
# vocatives only). Anything else ("como", "estas", "tu", "día", fillers)
# means the turn is a check-in or mixed content — fail open to full pipeline.
_PURE_GREETING_EXTRA_TOKENS = frozenset(
    {
        "amor",
        "cielo",
        "bebe",
        "bebé",
        "corazon",
        "corazón",
        "hermosa",
        "hermoso",
        "linda",
        "lindo",
        "bonita",
        "bonito",
        "guapa",
        "guapo",
        "reina",
        "rey",
        "vida",
        "mi",
    }
)


def _kw_hit(kw: str, lower_text: str) -> bool:
    """Match keyword as a whole-token sequence on lowercased text.

    Single tokens and multi-word phrases both require non-word boundaries on
    both sides so ``eres real`` does not hit ``eres realmente`` / ``realista``.
    """
    k = (kw or "").strip().lower()
    if not k:
        return False
    return re.search(rf"(?<!\w){re.escape(k)}(?!\w)", lower_text) is not None


def _longest_greeting_keyword(lower_text: str) -> str | None:
    """Return the longest PURE_GREETING_PATTERNS hit, or None."""
    hits = [kw for kw in PURE_GREETING_PATTERNS if _kw_hit(kw, lower_text)]
    if not hits:
        return None
    return max(hits, key=len)


def looks_like_pure_greeting_text(text: str) -> bool:
    """True when inbound text is a pure short greeting.

    Contract: known greeting keyword, ≤4 words, and after removing that
    keyword the only leftover tokens are optional vocatives (amor/cielo/…).
    Check-ins like ``Que tal como estas?`` / ``Que tal tu día`` keep the
    keyword + word-count shape but must NOT take the canned saludo pool.
    """
    if not text or not str(text).strip():
        return False
    words = str(text).strip().split()
    if len(words) > PURE_GREETING_MAX_WORDS:
        return False
    lower = str(text).lower()
    matched = _longest_greeting_keyword(lower)
    if matched is None:
        return False
    residual = re.sub(
        rf"(?<!\w){re.escape(matched)}(?!\w)",
        " ",
        lower,
        count=1,
    )
    # Drop punctuation / emoji; keep letters (incl. Spanish accents).
    residual = re.sub(r"[^\w\sáéíóúüñ]", " ", residual, flags=re.UNICODE)
    residual_words = [w for w in residual.split() if w]
    return all(w in _PURE_GREETING_EXTRA_TOKENS for w in residual_words)


# --- Phatic check-in fast lane (post-Analyst; pools + light context) ---------
# Subtypes share the saludo trust doors but NEVER the Holis pool.
CHECKIN_MAX_WORDS = 8

CHECKIN_BIENESTAR_PATTERNS = (
    "cómo estás",
    "como estas",
    "cómo estas",
    "como estás",
    "cómo te va",
    "como te va",
    "cómo andas",
    "como andas",
    "qué tal estás",
    "que tal estas",
    "qué tal estas",
    "que tal estás",
    "cómo te sientes",
    "como te sientes",
)

CHECKIN_DIA_PATTERNS = (
    "qué tal tu día",
    "que tal tu dia",
    "qué tal tu dia",
    "que tal tu día",
    "cómo te fue el día",
    "como te fue el dia",
    "cómo te fue el dia",
    "como te fue el día",
    "cómo estuvo tu día",
    "como estuvo tu dia",
    "qué tal el día",
    "que tal el dia",
    "qué tal el dia",
    "que tal el día",
    "cómo va tu día",
    "como va tu dia",
    "cómo te fue hoy",
    "como te fue hoy",
)

# Short substance cues → fail open to full pipeline (sales / request / drama).
_CHECKIN_SUBSTANCE_CUES = (
    "precio",
    "comprar",
    "pago",
    "pagar",
    "contenido",
    "suscri",
    "pack",
    "onlyfans",
    "promo",
    "descuento",
    "quiero que",
    "necesito",
    "problema",
    "ayuda con",
    "pregunta sobre",
    "explicame",
    "explícame",
    "cuéntame de",
    "cuentame de",
    "por qué no",
    "porque no",
)

# Default pools (español neutro, 1 sentence max). Soft pools when mood_low.
CHECKIN_BIENESTAR_POOL = (
    "Bien, aquí ando 😊",
    "Todo bien, ¿y tú?",
    "Aquí andamos, ¿tú qué tal?",
)
CHECKIN_BIENESTAR_SOFT_POOL = (
    "Aquí ando, tranqui 💙 ¿tú cómo estás?",
    "Todo bien por aquí, ¿y tú?",
    "Aquí andamos, cuéntame cómo te sientes",
)
CHECKIN_DIA_POOL = (
    "Bien, tranqui por aquí",
    "Todo bien por acá, ¿y el tuyo?",
    "Aquí andamos, ¿tú qué tal tu día?",
)
CHECKIN_DIA_SOFT_POOL = (
    "Tranqui por aquí 💙 ¿tú cómo vas?",
    "Todo bien por acá, ¿cómo te fue el tuyo?",
    "Aquí andamos suave, ¿qué tal tu día?",
)
# Warmer picks when a safe fact exists (presence only — no fact interpolation).
CHECKIN_WARM_NOD_POOL = (
    "Bien por aquí 🙂 ¿y tú?",
    "Todo bien, me alegra saber de ti",
    "Aquí andamos, cuéntame",
)


def _has_substance_beyond_checkin(lower_text: str) -> bool:
    """True when the turn looks like sales / drama / request / long ask."""
    for cue in _CHECKIN_SUBSTANCE_CUES:
        if cue in lower_text:
            return True
    return False


def _longest_pattern_hit(lower_text: str, patterns: tuple[str, ...]) -> str | None:
    hits = [kw for kw in patterns if _kw_hit(kw, lower_text)]
    if not hits:
        return None
    return max(hits, key=len)


def detect_phatic_subtype(text: str) -> str | None:
    """Classify short phatic text into saludo_puro / check-in subtypes.

    Returns None when the turn should take the full supervised pipeline
    (substance, length, or unrecognized shape). Pure greetings win over
    check-in so ``Hola`` / ``qué tal`` keep the Holis pool.
    """
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    words = raw.split()
    if looks_like_pure_greeting_text(raw):
        return "saludo_puro"
    if len(words) > CHECKIN_MAX_WORDS:
        return None
    lower = raw.lower()
    if _has_substance_beyond_checkin(lower):
        return None
    if _longest_pattern_hit(lower, CHECKIN_DIA_PATTERNS) is not None:
        return "checkin_dia"
    if _longest_pattern_hit(lower, CHECKIN_BIENESTAR_PATTERNS) is not None:
        return "checkin_bienestar"
    # Greeting + check-in residual (pure-greeting already rejected).
    matched = _longest_greeting_keyword(lower)
    if matched is not None:
        residual = re.sub(
            rf"(?<!\w){re.escape(matched)}(?!\w)",
            " ",
            lower,
            count=1,
        )
        residual = re.sub(r"[^\w\sáéíóúüñ]", " ", residual, flags=re.UNICODE)
        residual_l = " ".join(residual.split())
        if residual_l and _longest_pattern_hit(residual_l, CHECKIN_DIA_PATTERNS):
            return "checkin_dia"
        if residual_l and _longest_pattern_hit(
            residual_l, CHECKIN_BIENESTAR_PATTERNS
        ):
            return "checkin_bienestar"
        if residual_l in {"como estas", "cómo estás", "como estás", "cómo estas"}:
            return "checkin_bienestar"
        if residual_l in {"tu dia", "tu día", "el dia", "el día"}:
            return "checkin_dia"
    return None


def looks_like_checkin_text(text: str) -> bool:
    """True when text is a short bienestar/día check-in (not pure saludo)."""
    subtype = detect_phatic_subtype(text)
    return subtype in {"checkin_bienestar", "checkin_dia"}


@dataclass(frozen=True, slots=True)
class PhaticLightContext:
    """Optional light context for check-in pool pick (fail-soft fields).

    All fields optional. Missing / unknown → plain pool RNG (like Holis).
    ``safe_memory_fact`` is a presence signal only (no free-form interpolation).
    """

    mood_low: bool | None = None
    recent_trend: str | None = None
    safe_memory_fact: str | None = None


def pick_checkin_reply(
    subtype: str,
    *,
    context: PhaticLightContext | None = None,
    rng: Any = random,
    bienestar_pool: Sequence[str] | None = None,
    bienestar_soft_pool: Sequence[str] | None = None,
    dia_pool: Sequence[str] | None = None,
    dia_soft_pool: Sequence[str] | None = None,
    warm_nod_pool: Sequence[str] | None = None,
) -> str:
    """Pick a short check-in line from pools + light context. Fail-soft.

    No LLM. If mood/memory missing or pools empty on a branch → fall back.
    """
    ctx = context or PhaticLightContext()
    mood_low = bool(ctx.mood_low) if ctx.mood_low is not None else False
    has_safe_fact = bool(ctx.safe_memory_fact and str(ctx.safe_memory_fact).strip())
    trend = (ctx.recent_trend or "").strip().lower()
    if trend and any(
        t in trend for t in ("baj", "cansad", "triste", "distan", "apag")
    ):
        mood_low = True

    if subtype == "checkin_dia":
        soft = list(dia_soft_pool or CHECKIN_DIA_SOFT_POOL)
        default = list(dia_pool or CHECKIN_DIA_POOL)
    else:
        soft = list(bienestar_soft_pool or CHECKIN_BIENESTAR_SOFT_POOL)
        default = list(bienestar_pool or CHECKIN_BIENESTAR_POOL)

    warm = list(warm_nod_pool or CHECKIN_WARM_NOD_POOL)

    if mood_low and soft:
        pool = [t for t in soft if t and str(t).strip()]
    elif has_safe_fact and warm:
        pool = [t for t in warm if t and str(t).strip()]
    else:
        pool = [t for t in default if t and str(t).strip()]

    if not pool:
        pool = [t for t in default if t and str(t).strip()] or [
            "Todo bien, ¿y tú?",
        ]
    if len(pool) == 1:
        return pool[0]
    return rng.choice(pool)


def checkin_reason_for(subtype: str) -> str:
    """Decision.reason for check-in fast lane (orchestrator phatic deliver)."""
    if subtype == "checkin_dia":
        return "plantilla_checkin_dia"
    return "plantilla_checkin_bienestar"


def is_phatic_template_reason(reason: str | None) -> bool:
    """True for saludo / check-in plantilla reasons (shared deliver path)."""
    if not reason:
        return False
    return reason == "plantilla_saludo" or str(reason).startswith("plantilla_checkin")


class TemplateGate:
    """Match inbound VIP text to the first applicable rule; render a pool response."""

    def __init__(self, rules: list[TemplateRule], *, rng: Any = random) -> None:
        self._rules = list(rules)
        self._rng = rng

    def match(self, text: str) -> TemplateRule | None:
        if not text or not str(text).strip():
            return None
        lower = text.lower()
        words = text.strip().split()
        for rule in self._rules:
            if rule.max_words is not None and len(words) > rule.max_words:
                continue
            if any(_kw_hit(kw, lower) for kw in rule.trigger_patterns):
                return rule
        return None

    def render(self, rule: TemplateRule) -> str:
        if not rule.response_pool:
            raise ValueError(f"TemplateRule {rule.id!r} has empty response_pool")
        if len(rule.response_pool) == 1:
            return rule.response_pool[0]
        return self._rng.choice(rule.response_pool)


__all__ = [
    "PURE_GREETING_MAX_WORDS",
    "PURE_GREETING_PATTERNS",
    "CHECKIN_MAX_WORDS",
    "CHECKIN_BIENESTAR_PATTERNS",
    "CHECKIN_DIA_PATTERNS",
    "CHECKIN_BIENESTAR_POOL",
    "CHECKIN_BIENESTAR_SOFT_POOL",
    "CHECKIN_DIA_POOL",
    "CHECKIN_DIA_SOFT_POOL",
    "CHECKIN_WARM_NOD_POOL",
    "PhaticLightContext",
    "TemplateRule",
    "TemplateGate",
    "looks_like_pure_greeting_text",
    "looks_like_checkin_text",
    "detect_phatic_subtype",
    "pick_checkin_reply",
    "checkin_reason_for",
    "is_phatic_template_reason",
]
