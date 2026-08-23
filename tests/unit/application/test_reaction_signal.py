"""Unit tests for the H2 reaction-signal classifier (C3, no LLM)."""

from __future__ import annotations


from diana.application.reaction_signal import (
    ReactionSignalClassifier,
    classify,
)


class TestClassify:
    def test_negative_emotion_wins(self) -> None:
        # Emotion overrides even positive surface tokens.
        comp = {"emotion": "molesta", "intent": "quejarse"}
        assert classify("gracias perfecto", comp) == "negative"

    def test_positive_emotion_wins(self) -> None:
        comp = {"emotion": "cariñosa", "intent": "agradecer"}
        assert classify("", comp) == "positive"

    def test_positive_lexicon(self) -> None:
        assert classify("¡Genial, gracias!", None) == "positive"

    def test_negative_lexicon(self) -> None:
        assert classify("Esto está mal, no me gusta", None) == "negative"

    def test_negative_outweighs_positive(self) -> None:
        assert classify("gracias pero está horrible, no me gusta", None) == "negative"

    def test_tie_is_neutral(self) -> None:
        # "gracias" (1) vs "mal" (1) → tie → neutral (deterministic).
        assert classify("gracias pero está mal", None) == "neutral"

    def test_neutral_default(self) -> None:
        assert classify("", None) == "neutral"
        assert classify("el paquete llegó", None) == "neutral"

    def test_case_insensitive(self) -> None:
        assert classify("GRACIAS POR TODO", None) == "positive"

    def test_empty_comprehension_dict(self) -> None:
        assert classify("genial", {}) == "positive"


class TestReactionSignalClassifier:
    def test_callable(self) -> None:
        classifier = ReactionSignalClassifier()
        assert classifier("¡Perfecto, gracias!", None) == "positive"
        assert classifier("mal servicio", None) == "negative"

    def test_apply_overrides(self) -> None:
        classifier = ReactionSignalClassifier()
        classifier.apply_overrides({"positive_lexicon": ["último token"]})
        assert classifier("último token", None) == "positive"
        assert classifier("gracias", None) == "neutral"
