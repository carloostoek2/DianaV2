"""Unit tests for pure J.4 keyword classification."""

from __future__ import annotations

from diana.application.j4_triggers import (
    IA_TEMPLATE,
    classify_j4_text,
    match_keywords,
)


def test_pago_hit() -> None:
    hit = classify_j4_text("Hola, cuál es el precio de la suscripción?")
    assert hit is not None
    assert hit.category == "pago_precio"
    assert hit.tipo == "pago_precio"
    assert hit.template is None
    assert any(k in hit.keywords_hit for k in ("precio", "suscripción", "suscripcion"))


def test_ia_hit_sets_exact_template() -> None:
    hit = classify_j4_text("sos un bot o qué?")
    assert hit is not None
    assert hit.category == "identidad_ia"
    assert hit.tipo == "identidad_ia"
    assert hit.template == IA_TEMPLATE
    assert hit.template == "jsjsj si y sólo vivo en tu mente 😏"


def test_compromiso_hit() -> None:
    hit = classify_j4_text("podemos coordinar una cita?")
    assert hit is not None
    assert hit.category == "compromiso_real"
    assert hit.tipo == "compromiso_real"


def test_ia_priority_over_pago() -> None:
    hit = classify_j4_text("eres un bot y cuánto cuesta?")
    assert hit is not None
    assert hit.category == "identidad_ia"


def test_botella_not_identidad_ia() -> None:
    hit = classify_j4_text("me regalas una botella?")
    assert hit is None or hit.category != "identidad_ia"
    assert match_keywords("me regalas una botella?", ["bot"]) == []


def test_empty_text_none() -> None:
    assert classify_j4_text("") is None
    assert classify_j4_text("   ") is None


def test_pago_expanded_phrases() -> None:
    for text in (
        "cuánto vale el pack?",
        "cuanto vale?",
        "ya pagué con paypal",
        "cuál es el costo?",
        "está pagado?",
    ):
        hit = classify_j4_text(text)
        assert hit is not None, text
        assert hit.category == "pago_precio", text


def test_ia_chatgpt_and_eres_real() -> None:
    for text in ("eres real?", "sos real", "usás chatgpt?", "eres un chatbot"):
        hit = classify_j4_text(text)
        assert hit is not None, text
        assert hit.category == "identidad_ia", text
        assert hit.template == IA_TEMPLATE


def test_bare_chatbot_alone_not_ia() -> None:
    """Bare chatbot/IA terms without second person should not FP identity."""
    hit = classify_j4_text("el chatbot del banco falló")
    assert hit is None or hit.category != "identidad_ia"


def test_compromiso_quedemos_not_bare_quedar() -> None:
    assert classify_j4_text("quedemos mañana") is not None
    assert classify_j4_text("quedemos mañana").category == "compromiso_real"  # type: ignore[union-attr]
    # bare "quedar" alone is no longer a trigger (FP tighten)
    hit = classify_j4_text("no quiero quedar mal")
    assert hit is None or hit.category != "compromiso_real"
