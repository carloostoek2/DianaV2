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
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
_MIN_NATURAL_SPLIT_LEN = 20
_MIN_TYPO_WORD_LEN = 4


def pick_quirk(
    rng: Random,
    probability: float,
    *,
    force: str | None = None,
) -> QuirkKind | None:
    """Return a quirk kind, or None when the probability gate does not fire.

    ``force`` (tests) bypasses probability and returns the kind directly.
    """
    if force is not None:
        if force not in _QUIRK_KINDS:
            raise ValueError(f"invalid quirk_force: {force!r}")
        return force  # type: ignore[return-value]

    p = max(0.0, min(1.0, float(probability)))
    if p <= 0.0:
        return None
    if rng.random() >= p:
        return None
    return rng.choice(list(_QUIRK_KINDS))


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


def apply_typo(text: str, rng: Random) -> tuple[str, str] | None:
    """Mild typo on first alphabetic word len≥4; correction bubble ``*{word}``.

    Swap characters at indices 1 and 2 of the chosen word (interior swap).
    Returns ``None`` when no candidate word exists.
    ``rng`` reserved for future multi-candidate selection; currently unused
    beyond API stability (first candidate wins).
    """
    del rng  # first-candidate policy; kept for injectable determinism contract
    stripped = text.strip()
    if not stripped:
        return None

    match = None
    for m in _WORD_RE.finditer(stripped):
        if len(m.group(0)) >= _MIN_TYPO_WORD_LEN:
            match = m
            break
    if match is None:
        return None

    word = match.group(0)
    # Interior swap of positions 1 and 2 (0-indexed).
    chars = list(word)
    chars[1], chars[2] = chars[2], chars[1]
    typoed_word = "".join(chars)
    typoed = stripped[: match.start()] + typoed_word + stripped[match.end() :]
    correction = f"*{word}"
    return typoed, correction
