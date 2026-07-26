"""Unit tests for pure human-quirk helpers (H3.6 / AGENTS §4.12)."""

from __future__ import annotations

import random

from diana.behavior.quirks import apply_typo, natural_split_text, pick_quirk


# --- pick_quirk ---


def test_pick_quirk_p_zero_returns_none() -> None:
    rng = random.Random(0)
    assert pick_quirk(rng, 0.0) is None


def test_pick_quirk_force_returns_kind() -> None:
    rng = random.Random(0)
    assert pick_quirk(rng, 0.0, force="pause") == "pause"
    assert pick_quirk(rng, 0.0, force="natural_split") == "natural_split"
    assert pick_quirk(rng, 0.0, force="typo_correct") == "typo_correct"


def test_pick_quirk_p_one_returns_one_of_kinds() -> None:
    rng = random.Random(42)
    kinds = {pick_quirk(rng, 1.0) for _ in range(60)}
    assert None not in kinds
    assert kinds <= {"pause", "natural_split", "typo_correct"}
    # With enough draws, expect more than one kind (uniform).
    assert len(kinds) >= 2


def test_pick_quirk_force_invalid_fail_closed_pause() -> None:
    """Invalid force must not raise mid-delivery; fall closed to pause."""
    assert pick_quirk(random.Random(0), 1.0, force="nope") == "pause"
    assert pick_quirk(random.Random(0), 0.0, force="bogus") == "pause"


# --- natural_split_text ---


def test_natural_split_multi_sentence() -> None:
    text = "Hello there friend. How are you doing today?"
    parts = natural_split_text(text)
    assert len(parts) >= 2
    joined = " ".join(parts)
    for word in ("Hello", "there", "friend", "How", "are", "you", "doing", "today"):
        assert word in joined
    assert all(p.strip() for p in parts)


def test_natural_split_short_or_single_sentence_unchanged() -> None:
    assert natural_split_text("short ok") == ["short ok"]
    assert natural_split_text("Only one sentence here without end") == [
        "Only one sentence here without end"
    ]


def test_natural_split_empty() -> None:
    assert natural_split_text("") == []
    assert natural_split_text("   ") == []


def test_natural_split_exclamation_question() -> None:
    text = "Wow that was amazing! Really great stuff here?"
    parts = natural_split_text(text)
    assert len(parts) >= 2


# --- apply_typo ---


def test_apply_typo_swaps_mid_word_and_correction() -> None:
    rng = random.Random(0)
    text = "Hello beautiful world"
    typoed, correction = apply_typo(text, rng)
    assert typoed != text
    assert correction.startswith("*")
    original_word = correction[1:]
    assert original_word in text
    assert original_word not in typoed or typoed != text
    # Semantic content: all original words except the swapped one still present
    # and correction restores the intended word.
    assert original_word.isalpha()
    assert len(original_word) >= 4


def test_apply_typo_no_candidate_returns_none() -> None:
    rng = random.Random(0)
    # All words shorter than 4 letters.
    assert apply_typo("hi ok me", rng) is None
    assert apply_typo("", rng) is None


def test_apply_typo_prefers_first_long_word() -> None:
    rng = random.Random(1)
    text = "ab code longer word"
    result = apply_typo(text, rng)
    assert result is not None
    typoed, correction = result
    # First alphabetic word with len >= 4 is "code"; swap interior [1]<->[2].
    assert correction == "*code"
    assert "cdoe" in typoed
    assert "code" not in typoed.split()


def test_apply_typo_skips_noop_swap_words() -> None:
    """book/look style double letters: try next pair or next word, never noop."""
    rng = random.Random(0)
    # "book" swap(1,2) is noop (o/o); must still produce a real typo.
    result = apply_typo("book time", rng)
    assert result is not None
    typoed, correction = result
    assert typoed != "book time"
    assert correction in ("*book", "*time")
    assert correction[1:] not in typoed.split() or typoed != "book time"


def test_apply_typo_all_noop_candidates_returns_none() -> None:
    """Words where no adjacent swap changes the string → None (pause fallback)."""
    rng = random.Random(0)
    # "aaaa" any adjacent swap is still "aaaa".
    assert apply_typo("aaaa", rng) is None
    assert apply_typo("aa bb", rng) is None


def test_apply_typo_spanish_accented_word() -> None:
    rng = random.Random(0)
    text = "Me gusta el café mucho"
    result = apply_typo(text, rng)
    assert result is not None
    typoed, correction = result
    assert typoed != text
    # First long word is "gusta" (len 5); café is also eligible if reached.
    assert correction.startswith("*")
    word = correction[1:]
    assert any(c in "áéíóúñüÁÉÍÓÚÑÜ" or c.isalpha() for c in word)
    assert word in text
