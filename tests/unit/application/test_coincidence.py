"""Unit tests for the pure coincidence engine (C1, SPEC-AUTONOMIA-CALIBRACION §5)."""

from __future__ import annotations

import pytest

from diana.application.coincidence import label, match_rate


class TestLabel:
    def test_send_approved_as_is_is_acierto(self) -> None:
        assert label("send", "approved_as_is") == "acierto"

    def test_send_corrected_is_desacuerdo(self) -> None:
        assert label("send", "corrected") == "desacuerdo"

    def test_send_escalated_is_desacuerdo(self) -> None:
        assert label("send", "escalated") == "desacuerdo"

    def test_blocked_approved_is_conservadora(self) -> None:
        assert label("blocked", "approved_as_is") == "conservadora"

    def test_escalate_approved_is_conservadora(self) -> None:
        assert label("escalate", "approved_as_is") == "conservadora"

    def test_doctrine_approved_is_conservadora(self) -> None:
        assert label("doctrine", "approved_as_is") == "conservadora"

    def test_non_send_with_correction_is_none(self) -> None:
        # Both sides agreed NOT to send — not a match-rate event.
        assert label("blocked", "corrected") is None
        assert label("escalate", "escalated") is None
        assert label("doctrine", "corrected") is None

    def test_send_without_owner_outcome_is_none(self) -> None:
        assert label("send", None) is None

    def test_unknown_tokens_are_none(self) -> None:
        assert label("send", "whatever") is None
        assert label("nope", "approved_as_is") is None
        assert label(None, None) is None

    def test_case_and_whitespace_insensitive(self) -> None:
        assert label("  SEND ", " Approved_As_Is ") == "acierto"


class TestMatchRate:
    def test_exact_spec_formula(self) -> None:
        # 3 aciertos, 1 desacuerdo → 3/4
        labels = ["acierto", "acierto", "acierto", "desacuerdo"]
        assert match_rate(labels) == pytest.approx(0.75)

    def test_ignores_conservadora_and_none(self) -> None:
        labels = ["acierto", "conservadora", None, "desacuerdo", "conservadora"]
        assert match_rate(labels) == pytest.approx(0.5)

    def test_all_aciertos_is_one(self) -> None:
        assert match_rate(["acierto", "acierto"]) == pytest.approx(1.0)

    def test_empty_denominator_is_none(self) -> None:
        assert match_rate([]) is None
        assert match_rate(["conservadora", None, "conservadora"]) is None

    def test_only_desacuerdos_is_zero(self) -> None:
        assert match_rate(["desacuerdo", "desacuerdo"]) == pytest.approx(0.0)
