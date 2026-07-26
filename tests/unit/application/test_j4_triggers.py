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
