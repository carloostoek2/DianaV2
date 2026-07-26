"""Unit tests for pure RepetitionGuard (H4 — no I/O)."""

from __future__ import annotations

from diana.cognitive.repetition_guard import RepetitionGuard


def test_streak_of_two_prior_same_is_repeated_at_threshold_3() -> None:
    guard = RepetitionGuard(threshold=3)
    assert guard.is_repeated("precio", ["precio", "precio"]) is True


def test_one_prior_same_is_not_repeated_at_threshold_3() -> None:
    guard = RepetitionGuard(threshold=3)
    assert guard.is_repeated("precio", ["precio"]) is False


def test_interrupted_streak_newest_different_is_false() -> None:
    guard = RepetitionGuard(threshold=3)
    # recent is DESC (newest first): newest is "otro" → streak breaks
    assert guard.is_repeated("precio", ["otro", "precio", "precio"]) is False


def test_empty_recent_default_threshold_is_false() -> None:
    guard = RepetitionGuard(threshold=3)
    assert guard.is_repeated("precio", []) is False


def test_empty_recent_threshold_1_is_true() -> None:
    """Current alone counts as streak 1; threshold 1 → True."""
    guard = RepetitionGuard(threshold=1)
    assert guard.is_repeated("precio", []) is True


def test_blank_current_intent_always_false() -> None:
    guard = RepetitionGuard(threshold=3)
    assert guard.is_repeated("", ["", ""]) is False
    assert guard.is_repeated("   ", ["precio", "precio"]) is False


def test_non_consecutive_older_matches_do_not_count() -> None:
    guard = RepetitionGuard(threshold=3)
    # newest matches, then different, then same again — streak stops at 2
    assert guard.is_repeated("precio", ["precio", "chat", "precio"]) is False
