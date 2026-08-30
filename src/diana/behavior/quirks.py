"""Pure human-quirk helpers for advanced delivery (H3.6 / AGENTS §4.12).

Mechanical only: pause selection, sentence natural-split, mild typo+correction.
No I/O, no LLM, no cognitive imports. Deterministic with injected RNG.
"""

from __future__ import annotations

import re
from random import Random
from typing import Literal

QuirkKind = Literal["pause", "natural_split", "typo_correct"]

_QUIRK_KINDS: tuple[QuirkKind, ...] = ("pause", "natural_split", "typo_correct")
# Typo+correction is the only quirk the VIP actually sees. Pause is nearly
# invisible; natural_split is a rare extra after paragraph delivery split.
_QUIRK_WEIGHTS: dict[QuirkKind, float] = {
    "typo_correct": 0.60,
    "pause": 0.25,
    "natural_split": 0.15,
}
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
# Latin letters + Spanish accented (áéíóúñü and uppercase).
_WORD_RE = re.compile(
    r"[A-Za-zÀ-ÖØ-öø-ÿÁÉÍÓÚÜÑáéíóúüñ]+",
    re.UNICODE,
)
_MIN_NATURAL_SPLIT_LEN = 20
_MIN_TYPO_WORD_LEN = 4
# Onomatopeya de risa. Decisión de la dueña (ajuste quirúrgico de quirks):
# la risa SÍ puede salir desordenada ("se puede desordenar como sea", es
# natural), pero NUNCA se corrige: nadie corrige su propia risa. Cubre el
# formato real de Diana (letras j/s/h: jsjsjh, jshshs, jsjsjs), además de:
#   · sílabas j+vocal repetidas: jaja, jeje, jiji, jojo, ajaja, jajaja
#   · mezclas j/s/h con doble letra: jsjs, jsjjs, jshshs, jsjsjh
#   · risas meme: ksksks, xdxdxd
_LAUGH_RE = re.compile(
    r"^(?:"
    r"(?:[aeiou]?j[aeiou]?){2,}"   # jaja / jeje / jiji / jojo / ajaja
    r"|j[jsh]{2,}"                 # jsjs / jsjjs / jshshs / jsjsjh / jsjsjs
    r"|(?:ks|sk|xd|dx){2,}"        # ksks / xdxd
    r")$",
    re.IGNORECASE,
)


def pick_quirk(
    rng: Random,
    probability: float,
    *,
    force: str | None = None,
) -> QuirkKind | None:
    """Return a quirk kind, or None when the probability gate does not fire.

    ``force`` (tests) bypasses probability and returns the kind directly.
    Invalid force fail-closes to ``pause`` (never raises mid-delivery).
    """
    if force is not None:
        if force not in _QUIRK_KINDS:
            return "pause"
        return force  # type: ignore[return-value]

    p = max(0.0, min(1.0, float(probability)))
    if p <= 0.0:
        return None
    if rng.random() >= p:
        return None
    kinds = list(_QUIRK_WEIGHTS)
    weights = [_QUIRK_WEIGHTS[k] for k in kinds]
    return rng.choices(kinds, weights=weights, k=1)[0]


def natural_split_text(text: str) -> list[str]:
    """Split on sentence boundaries when text is long enough and has ≥2 parts.

    Boundaries: ``. `` / ``! `` / ``? `` (whitespace after terminal punct).
    Returns a single-element list when split is not applicable.
    """
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped) < _MIN_NATURAL_SPLIT_LEN:
        return [stripped]

    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(stripped) if p.strip()]
    if len(parts) < 2:
        return [stripped]
    return parts


def apply_typo(text: str, rng: Random) -> tuple[str, str | None] | None:
    """Mild typo on first viable alphabetic word len≥4; correction ``*{word}``.

    Laugh onomatopoeia (jsjs/jshshs/…) may be scrambled freely — any letter
    order is natural — but never gets a correction bubble: nobody corrects
    their own laugh (decision of the product owner). A non-laugh word returns
    ``(*{word})``; a laugh word returns ``(typoed, None)``.
    Prefer first viable word; try adjacent interior swaps starting at (1,2),
    then (2,3), … If a swap is a no-op (e.g. ``book`` double letter), try the
    next pair, then the next word. Returns ``None`` when no real typo is
    possible. ``rng`` reserved for injectable determinism contract (first
    viable wins).
    """
    del rng  # first-viable policy; kept for injectable determinism contract
    stripped = text.strip()
    if not stripped:
        return None

    for match in _WORD_RE.finditer(stripped):
        word = match.group(0)
        if len(word) < _MIN_TYPO_WORD_LEN:
            continue
        typoed_word = _first_real_swap(word)
        if typoed_word is None:
            continue
        typoed = stripped[: match.start()] + typoed_word + stripped[match.end() :]
        correction = None if _LAUGH_RE.match(word) else f"*{word}"
        return typoed, correction
    return None


def _first_real_swap(word: str) -> str | None:
    """Return word with first adjacent swap that actually changes it, else None."""
    chars = list(word)
    # Adjacent pairs from index 1..len-2 (prefer interior; keep trying).
    for i in range(1, len(chars) - 1):
        if chars[i] == chars[i + 1]:
            continue
        swapped = chars.copy()
        swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        candidate = "".join(swapped)
        if candidate != word:
            return candidate
    # Also try swap at (0,1) if interior pairs all failed/noop (len>=4).
    if chars[0] != chars[1]:
        swapped = chars.copy()
        swapped[0], swapped[1] = swapped[1], swapped[0]
        candidate = "".join(swapped)
        if candidate != word:
            return candidate
    return None
