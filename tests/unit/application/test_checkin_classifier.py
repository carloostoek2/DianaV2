
"""Check-in phatic cut helpers on TurnClassifier."""

from __future__ import annotations

import pytest

from diana.application.turn_classifier import (
    TurnClassifier,
    is_checkin_phatic,
    is_pure_greeting,
)
from diana.cognitive.models import Comprehension


def _comp(**overrides) -> Comprehension:
    data = {
        "intent": "saludar",
        "topics": ["apertura"],
        "emotion": "neutral",
        "urgency": "baja",
        "risk": "bajo",
        "needs_history": False,
        "needs_context": False,
        "needs_memory": False,
        "needs_policy": False,
        "needs_examples": False,
        "needs_schedule": False,
    }
    data.update(overrides)
    return Comprehension(**data)


@pytest.fixture
def clf() -> TurnClassifier:
    return TurnClassifier()


def test_is_checkin_phatic_bienestar(clf: TurnClassifier) -> None:
    assert is_checkin_phatic("cómo estás", _comp(), classifier=clf) is True
    assert is_pure_greeting("cómo estás", _comp(), classifier=clf) is False


def test_is_checkin_phatic_dia(clf: TurnClassifier) -> None:
    assert is_checkin_phatic("qué tal tu día", _comp(), classifier=clf) is True


def test_is_checkin_rejects_pure_hola(clf: TurnClassifier) -> None:
    assert is_checkin_phatic("Hola", _comp(), classifier=clf) is False


def test_is_checkin_rejects_sales(clf: TurnClassifier) -> None:
    assert (
        is_checkin_phatic(
            "cómo estás, quiero comprar el pack",
            _comp(),
            classifier=clf,
        )
        is False
    )
