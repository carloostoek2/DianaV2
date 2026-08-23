"""Text quality heuristic H1 (C2) — deterministic draft/sent text scoring, no LLM.

SPEC-AUTONOMIA-CALIBRACION.md §6: score ANY text 0–1 with the same fixed
rules, so the owner correction's contribution is measurable:

    quality_delta = score(sent) − score(shadow draft)

Rules (fixed weights; constants with manual ``system_config`` override via
``apply_overrides`` — NEVER auto-calibrated):

- SEGURIDAD (hard gate): a forbidden keyword or PII (email/phone/card/handle/
  URL, via ``llm.pii_masker``) makes the score 0.0 outright.
- longitud adecuada  · pregunta o apertura de cierre · uso del nombre del VIP
  · léxico cálido/positivo · naturalidad coloquial.

Pure module: stdlib + ``llm.pii_masker`` only (no aiogram, no persistence).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from diana.llm.pii_masker import mask_pii

logger = logging.getLogger("diana.application")

__all__ = [
    "DEFAULT_WEIGHTS",
    "DEFAULT_WARM_LEXICON",
    "DEFAULT_COLLOQUIAL_LEXICON",
    "DEFAULT_FORMAL_LEXICON",
    "TextQualityScorer",
    "score",
]

DEFAULT_WEIGHTS: dict[str, float] = {
    "longitud": 0.25,
    "cierre": 0.20,
    "nombre": 0.20,
    "calidez": 0.20,
    "naturalidad": 0.15,
}

DEFAULT_WARM_LEXICON: tuple[str, ...] = (
    "😊",
    "😁",
    "👍",
    "claro que sí",
    "con gusto",
    "encantada",
    "me alegro",
    "perfecto",
    "genial",
    "excelente",
    "buen día",
    "cariño",
    "un abrazo",
    "abrazos",
    "te quiero",
    "feliz",
    "gracias",
)

DEFAULT_COLLOQUIAL_LEXICON: tuple[str, ...] = (
    "qué tal",
    "oye",
    "va",
    "dale",
    "súper",
    "un poquito",
    "claro",
    "mira",
    "bueno",
    "pues",
    "ya verás",
    "tranquila",
    "sin problema",
    "!",
)

DEFAULT_FORMAL_LEXICON: tuple[str, ...] = (
    "usted",
    "estimado",
    "le informo",
    "atentamente",
    "sírvase",
    "hago de su conocimiento",
    "a la brevedad",
)

# Length band considered "adecuada".
_MIN_CHARS = 8
_MAX_CHARS = 600

# Closing-openers: a question or a soft closing keeps the door open.
_CLOSING_OPENERS: tuple[str, ...] = (
    "?",
    "¿",
    "un abrazo",
    "saludos",
    "quedo atenta",
    "quedo atento",
    "cualquier cosa avísame",
    "cualquier cosa me dices",
    "aquí estoy",
    "cuídate",
    "que tengas buen día",
    "buen día",
)


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _has_any(text_lower: str, tokens: Iterable[str]) -> bool:
    return any(token in text_lower for token in tokens if token)


def _has_pii(text: str) -> bool:
    """True when the text carries PII (email/phone/card/handle/URL)."""
    try:
        return bool(mask_pii(text).stats)
    except Exception:
        return False


def score(
    text: str | None,
    *,
    vip_name: str | None = None,
    forbidden_keywords: Iterable[str] | None = None,
    warm_lexicon: Iterable[str] = DEFAULT_WARM_LEXICON,
    colloquial_lexicon: Iterable[str] = DEFAULT_COLLOQUIAL_LEXICON,
    formal_lexicon: Iterable[str] = DEFAULT_FORMAL_LEXICON,
    weights: Mapping[str, float] | None = None,
) -> float:
    """Deterministic 0–1 text-quality score (H1, C2).

    SEGURIDAD is a hard gate: forbidden keyword or PII → 0.0. Then the five
    weighted rules. ``vip_name`` None → the name rule scores neutral 0.5
    (neither helps nor hurts — the scorer cannot know the VIP's name).
    """
    if not text or not str(text).strip():
        return 0.0
    text = str(text).strip()
    text_lower = text.lower()

    # Hard gate — nothing else matters.
    if forbidden_keywords:
        for keyword in forbidden_keywords:
            kw = str(keyword or "").strip().lower()
            if kw and kw in text_lower:
                return 0.0
    if _has_pii(text):
        return 0.0

    effective = dict(DEFAULT_WEIGHTS)
    if weights:
        for key, value in weights.items():
            try:
                effective[key] = _clamp01(float(value))
            except (TypeError, ValueError):
                continue

    # longitud adecuada
    length = len(text)
    if length < _MIN_CHARS:
        longitud = length / _MIN_CHARS
    elif length <= _MAX_CHARS:
        longitud = 1.0
    else:
        over = length - _MAX_CHARS
        longitud = max(0.5, 1.0 - over / (_MAX_CHARS * 2))

    # pregunta o apertura de cierre
    cierre = 1.0 if _has_any(text_lower, _CLOSING_OPENERS) else 0.0

    # uso del nombre del VIP (neutral 0.5 when the name is unknown)
    if vip_name:
        nombre = 1.0 if str(vip_name).strip().lower() in text_lower else 0.0
    else:
        nombre = 0.5

    # léxico cálido/positivo
    calidez = 1.0 if _has_any(text_lower, warm_lexicon) else 0.0

    # naturalidad coloquial (colloquial wins over formal)
    if _has_any(text_lower, colloquial_lexicon):
        naturalidad = 1.0
    elif _has_any(text_lower, formal_lexicon):
        naturalidad = 0.0
    else:
        naturalidad = 0.5

    total_weight = sum(effective.values())
    if total_weight <= 0.0:
        return 0.0
    weighted = (
        effective.get("longitud", 0.0) * longitud
        + effective.get("cierre", 0.0) * cierre
        + effective.get("nombre", 0.0) * nombre
        + effective.get("calidez", 0.0) * calidez
        + effective.get("naturalidad", 0.0) * naturalidad
    )
    return _clamp01(weighted / total_weight)


class TextQualityScorer:
    """Callable H1 scorer with a mutable forbidden-keyword source.

    ``forbidden_keywords`` may be a static iterable OR a zero-arg callable
    returning the current list (the boot-loaded ``app.forbidden_keywords`` is a
    mutable list reference — the scorer sees live updates without rebuilding).
    Manual overrides via ``apply_overrides`` (``system_config`` key
    ``text_quality``) — never auto-calibrated.
    """

    def __init__(
        self,
        *,
        forbidden_keywords: (
            Callable[[], Iterable[str]] | Iterable[str] | None
        ) = None,
        warm_lexicon: Iterable[str] = DEFAULT_WARM_LEXICON,
        colloquial_lexicon: Iterable[str] = DEFAULT_COLLOQUIAL_LEXICON,
        formal_lexicon: Iterable[str] = DEFAULT_FORMAL_LEXICON,
        weights: Mapping[str, float] | None = None,
    ) -> None:
        self._forbidden: Callable[[], Iterable[str]] | Iterable[str] | None = (
            forbidden_keywords
        )
        self._warm = list(warm_lexicon)
        self._colloquial = list(colloquial_lexicon)
        self._formal = list(formal_lexicon)
        self._weights = dict(weights or {})

    def _keywords(self) -> list[str]:
        if self._forbidden is None:
            return []
        if callable(self._forbidden):
            return [str(k) for k in self._forbidden()]
        return [str(k) for k in self._forbidden]

    def __call__(self, text: str, *, vip_name: str | None = None) -> float:
        return score(
            text,
            vip_name=vip_name,
            forbidden_keywords=self._keywords(),
            warm_lexicon=self._warm,
            colloquial_lexicon=self._colloquial,
            formal_lexicon=self._formal,
            weights=self._weights,
        )

    def apply_overrides(self, config: dict[str, Any]) -> None:
        """Manual override from ``system_config`` (key ``text_quality``).

        Missing keys are ignored; invalid values are rejected without crashing.
        """
        if not isinstance(config, dict):
            return
        weights = config.get("weights")
        if isinstance(weights, dict):
            for key, raw in weights.items():
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                if 0.0 <= value <= 1.0:
                    self._weights[str(key)] = value
        for attr, key in (
            ("_warm", "warm_lexicon"),
            ("_colloquial", "colloquial_lexicon"),
            ("_formal", "formal_lexicon"),
        ):
            raw = config.get(key)
            if isinstance(raw, list):
                setattr(self, attr, [str(t) for t in raw if str(t).strip()])
