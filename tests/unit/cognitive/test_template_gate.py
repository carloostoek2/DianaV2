"""Unit tests for pure TemplateGate (H6 — no I/O, no LLM)."""

from __future__ import annotations

import random

from diana.cognitive.template_gate import TemplateGate, TemplateRule

IA_TEMPLATE = "jsjsj si y sólo vivo en tu mente 😏"

SALUDO_POOL = ["Holis 😁", "Holaa, qué tal?", "Hola amor, cómo vas?"]

DETECCION_IA = TemplateRule(
    id="deteccion_ia",
    trigger_patterns=[
        "eres una ia",
        "eres un bot",
        "eres ia",
        "hablo con una ia",
        "hablo con un bot",
        "eres real",
    ],
    max_words=None,
    response_pool=[IA_TEMPLATE],
    reason="plantilla_deteccion_ia",
)

SALUDO = TemplateRule(
    id="saludo_constante",
    trigger_patterns=[
        "hola",
        "holaa",
        "holis",
        "buenas",
        "buenos días",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "hey",
        "qué tal",
        "que tal",
    ],
    max_words=4,
    response_pool=list(SALUDO_POOL),
    reason="plantilla_saludo",
)



def _saludo_gate() -> TemplateGate:
    return TemplateGate(rules=[SALUDO], rng=random.Random(0))


def _ia_gate() -> TemplateGate:
    return TemplateGate(rules=[DETECCION_IA], rng=random.Random(0))


def _full_gate() -> TemplateGate:
    return TemplateGate(rules=[DETECCION_IA, SALUDO], rng=random.Random(0))


def test_empty_and_blank_text_return_none() -> None:
    gate = _full_gate()
    assert gate.match("") is None
    assert gate.match("   ") is None


def test_saludo_matches_short_hola_and_holis() -> None:
    gate = _saludo_gate()
    for text in ("Hola", "holis", "HOLA"):
        rule = gate.match(text)
        assert rule is not None
        assert rule.id == "saludo_constante"
        assert rule.reason == "plantilla_saludo"


def test_saludo_rejects_long_hola_message() -> None:
    gate = _saludo_gate()
    long_msg = "Hola, tengo una pregunta sobre el contenido"
    assert len(long_msg.strip().split()) > 4
    assert gate.match(long_msg) is None


def test_deteccion_ia_matches_probe_and_renders_exact() -> None:
    gate = _ia_gate()
    rule = gate.match("eres una ia?")
    assert rule is not None
    assert rule.id == "deteccion_ia"
    assert gate.render(rule) == IA_TEMPLATE


def test_rule_order_deteccion_ia_beats_saludo_on_mixed_short() -> None:
    gate = _full_gate()
    rule = gate.match("hola eres una ia")
    assert rule is not None
    assert rule.id == "deteccion_ia"
    assert rule.reason == "plantilla_deteccion_ia"


def test_phrase_trigger_matches_with_punctuation() -> None:
    gate = _ia_gate()
    rule = gate.match("??? eres un bot ???")
    assert rule is not None
    assert rule.id == "deteccion_ia"


def test_phrase_eres_real_does_not_match_realmente_or_realista() -> None:
    """Multi-word phrase requires trailing word boundary (not bare substring)."""
    gate = _ia_gate()
    assert gate.match("eres realmente inteligente?") is None
    assert gate.match("eres realista con los plazos") is None
    assert gate.match("eres real?") is not None
    assert gate.match("eres real").id == "deteccion_ia"  # type: ignore[union-attr]


def test_single_token_uses_word_boundary() -> None:
    """'hola' as token matches; must not fire inside an unrelated glued token."""
    gate = _saludo_gate()
    assert gate.match("hola") is not None
    # Single-token boundary: 'holaxyz' should not match trigger 'hola'
    assert gate.match("holaxyz") is None


def test_saludo_max_words_boundary_exactly_four_matches_five_does_not() -> None:
    gate = _saludo_gate()
    four = "hola a b c"
    five = "hola a b c d"
    assert len(four.split()) == 4
    assert len(five.split()) == 5
    rule = gate.match(four)
    assert rule is not None
    assert rule.id == "saludo_constante"
    assert gate.match(five) is None


def test_saludo_unaccented_aliases_match() -> None:
    gate = _saludo_gate()
    for text in ("buenos dias", "que tal"):
        rule = gate.match(text)
        assert rule is not None, text
        assert rule.id == "saludo_constante"


def test_render_with_fixed_rng_is_stable_and_in_pool() -> None:
    gate = TemplateGate(rules=[SALUDO], rng=random.Random(0))
    rule = gate.match("hey")
    assert rule is not None
    a = gate.render(rule)
    b = gate.render(rule)
    assert a in SALUDO_POOL
    # With fixed Random(0) after two draws we still stay in pool; first is stable if we re-seed
    gate2 = TemplateGate(rules=[SALUDO], rng=random.Random(0))
    rule2 = gate2.match("hey")
    assert rule2 is not None
    assert gate2.render(rule2) == a
    assert b in SALUDO_POOL

