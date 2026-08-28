"""Unit tests for the H1 text-quality heuristic (C2, no LLM)."""

from __future__ import annotations


from diana.application.text_quality_heuristics import (
    TextQualityScorer,
    hard_gate_hit,
    score,
)


class TestScore:
    def test_empty_is_zero(self) -> None:
        assert score("") == 0.0
        assert score(None) == 0.0
        assert score("   ") == 0.0


class TestHardGateHit:
    def test_keyword_is_true(self) -> None:
        assert hard_gate_hit(
            "Te mando tu contraseña", forbidden_keywords=["contraseña"]
        ) is True

    def test_pii_is_true(self) -> None:
        assert hard_gate_hit("Escríbeme a ana@correo.com") is True

    def test_clean_text_is_false(self) -> None:
        assert hard_gate_hit("¡Claro que sí, María!") is False

    def test_empty_is_false(self) -> None:
        assert hard_gate_hit("") is False
        assert hard_gate_hit(None) is False
        assert hard_gate_hit("   ") is False

    def test_forbidden_keyword_is_hard_zero(self) -> None:
        assert score("Te mando tu contraseña", forbidden_keywords=["contraseña"]) == 0.0

    def test_pii_is_hard_zero(self) -> None:
        # Email + card-shaped numbers are PII → gate fires.
        assert score("Escríbeme a ana@correo.com") == 0.0
        assert score("Tu tarjeta 4111 1111 1111 1111 vence pronto") == 0.0

    def test_good_text_scores_high(self) -> None:
        text = "¡Claro que sí, María! ¿Quieres que te lo aparte? 😊"
        result = score(text, vip_name="María")
        assert 0.0 < result <= 1.0
        assert result > 0.7

    def test_name_usage_counts(self) -> None:
        with_name = score("Hola María, con gusto te ayudo", vip_name="María")
        without_name = score("Hola, con gusto te ayudo", vip_name="María")
        assert with_name > without_name

    def test_unknown_name_is_neutral(self) -> None:
        with_name = score("Hola María, con gusto", vip_name="María")
        no_name_known = score("Hola María, con gusto", vip_name=None)
        assert no_name_known < with_name

    def test_very_short_text_scores_low(self) -> None:
        assert score("ok") < score("Claro que sí, ¿te lo aparto? 😊")

    def test_formal_text_loses_naturalness(self) -> None:
        formal = score("Estimado cliente, le informo que su pedido saldrá a la brevedad")
        casual = score("¡Claro que sí! Te lo aparto sin problema 😊")
        assert casual > formal

    def test_closing_opener_helps(self) -> None:
        open_question = score("¿Quieres que te lo aparte?")
        flat = score("Ya quedó listo")
        assert open_question > flat

    def test_delta_positive_when_correction_improves(self) -> None:
        draft = "ok"
        corrected = "¡Claro que sí, María! ¿Te lo aparto? 😊"
        delta = score(corrected, vip_name="María") - score(draft, vip_name="María")
        assert delta > 0.2


class TestTextQualityScorer:
    def test_callable_signature(self) -> None:
        scorer = TextQualityScorer(forbidden_keywords=["secreto"])
        assert scorer("claro que sí 😊") > scorer("te paso el secreto")

    def test_live_keyword_source(self) -> None:
        keywords: list[str] = []
        scorer = TextQualityScorer(forbidden_keywords=lambda: keywords)
        before = scorer("Mira el link de tu envío")
        keywords.append("link")
        after = scorer("Mira el link de tu envío")
        assert before > 0.0
        assert after == 0.0

    def test_apply_overrides_replaces_lexicons(self) -> None:
        scorer = TextQualityScorer()
        scorer.apply_overrides({"warm_lexicon": ["palabra cálida única"]})
        assert scorer("palabra cálida única") > scorer("texto frío sin marcadores")
