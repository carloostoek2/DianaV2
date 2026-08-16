"""TurnClassifier pure-unit tests: 4 categories, "no estoy seguro", EA-03.

No DB, no LLM, no aiogram — pure heuristic over a ``Comprehension`` + text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from diana.cognitive.models import Comprehension
from diana.application.turn_classifier import (
    CLASSIFIER_CONFIDENCE_MIN,
    TurnClassification,
    TurnClassifier,
    is_pure_greeting,
    make_pure_greeting_cut,
)


def _comp(**kw) -> Comprehension:
    data = dict(
        intent="otro",
        topics=[],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=False,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
    )
    data.update(kw)
    return Comprehension(**data)


@pytest.fixture
def clf() -> TurnClassifier:
    return TurnClassifier()


def test_default_confidence_min(clf: TurnClassifier) -> None:
    assert clf.confidence_min == CLASSIFIER_CONFIDENCE_MIN == 0.7


def test_phatic_saludo(clf: TurnClassifier) -> None:
    c = clf.classify("hola diana", _comp(intent="saludar"))
    assert c.category == "fatico"
    assert c.confidence == 1.0
    assert clf.is_confident(c)


def test_phatic_despedida(clf: TurnClassifier) -> None:
    c = clf.classify("nos vemos", _comp(intent="despedirse"))
    assert c.category == "fatico"
    assert c.confidence == 1.0
    assert clf.is_confident(c)


def test_phatic_agradecer(clf: TurnClassifier) -> None:
    c = clf.classify("gracias", _comp(intent="agradecer"))
    assert c.category == "fatico"
    assert c.confidence == 1.0
    assert clf.is_confident(c)


def test_phatic_agradecer_carinosa_low_conf(clf: TurnClassifier) -> None:
    """Afecto leve = conservador: 0.7 sigue >= min → fast-lane ok."""
    c = clf.classify("gracias hermosa", _comp(intent="agradecer", emotion="cariñosa"))
    assert c.category == "fatico"
    assert c.confidence == 0.7
    assert clf.is_confident(c)


def test_informativo(clf: TurnClassifier) -> None:
    c = clf.classify(
        "me puedes mandar el contenido", _comp(intent="solicitar_contenido")
    )
    assert c.category == "informativo"
    assert c.confidence == 0.9


def test_emocional_emotion_negativa(clf: TurnClassifier) -> None:
    c = clf.classify("me siento mal", _comp(intent="otro", emotion="triste"))
    assert c.category == "emocional"


def test_emocional_queja(clf: TurnClassifier) -> None:
    c = clf.classify("esto no me gusto", _comp(intent="queja"))
    assert c.category == "emocional"


def test_emocional_flirtear(clf: TurnClassifier) -> None:
    c = clf.classify("me gustas mucho", _comp(intent="flirtear"))
    assert c.category == "emocional"


def test_emocional_topic_pesado(clf: TurnClassifier) -> None:
    c = clf.classify(
        "quiero hablar de algo", _comp(intent="otro", topics=["tema_pesado"])
    )
    assert c.category == "emocional"


@pytest.mark.parametrize(
    ("comp", "expected"),
    [
        # EA-03 hard rule: risk alto → sensitive, never fático.
        (dict(intent="saludar", emotion="neutral", risk="alto"), "sensible"),
        # EA-03: emotion molesta + risk medio → sensitive.
        (dict(intent="otro", emotion="molesta", risk="medio"), "sensible"),
        # EA-03: emotion triste + risk alto → sensitive.
        (dict(intent="otro", emotion="triste", risk="alto"), "sensible"),
    ],
)
def test_ea03_sensitive_never_phatic(clf: TurnClassifier, comp: dict, expected: str) -> None:
    c = clf.classify("hola", _comp(**comp))
    assert c.category == expected
    assert c.category != "fatico"
    assert c.confidence == 1.0


def test_sensitive_risk_alto(clf: TurnClassifier) -> None:
    c = clf.classify("hola", _comp(intent="saludar", risk="alto"))
    assert c.category == "sensible"


def test_sensitive_emotion_molesta_risk_medio(clf: TurnClassifier) -> None:
    c = clf.classify("me enoja esto", _comp(intent="otro", emotion="molesta", risk="medio"))
    assert c.category == "sensible"


def test_no_estoy_seguro_ambiguo(clf: TurnClassifier) -> None:
    """Saludo con carga emocional → fático 0.3 (< min → nunca fast-lane)."""
    c = clf.classify(
        "qué haces... es que no sé si contarte algo",
        _comp(intent="saludar"),
    )
    assert c.category == "fatico"
    assert c.confidence == 0.3
    assert not clf.is_confident(c)


def test_no_estoy_seguro_agradecer_con_carga(clf: TurnClassifier) -> None:
    """S2: un agradecer con carga emocional NO queda fático 1.0."""
    c = clf.classify(
        "gracias... es que no sé si contarte algo",
        _comp(intent="agradecer"),
    )
    assert c.category == "fatico"
    assert c.confidence == 0.3
    assert not clf.is_confident(c)


def test_no_estoy_seguro_despedirse_con_carga(clf: TurnClassifier) -> None:
    """S2: un despedirse con carga emocional tampoco queda fático 1.0."""
    c = clf.classify(
        "nos vemos... tengo miedo de contarte esto",
        _comp(intent="despedirse"),
    )
    assert c.category == "fatico"
    assert c.confidence == 0.3
    assert not clf.is_confident(c)


def test_phatic_texto_muy_corto(clf: TurnClassifier) -> None:
    """S10: branch texto_muy_corto — phatic intent + text <= 2 chars → 0.5."""
    c = clf.classify("ok", _comp(intent="saludar"))
    assert c.category == "fatico"
    assert c.confidence == 0.5
    assert not clf.is_confident(c)


def test_no_estoy_seguro_texto_corto(clf: TurnClassifier) -> None:
    """Texto muy corto sin intent → fallback informativo 0.5 (< min)."""
    c = clf.classify("ok", _comp(intent="otro"))
    assert c.category == "informativo"
    assert c.confidence == 0.5
    assert not clf.is_confident(c)


def test_comprehension_none_conservative(clf: TurnClassifier) -> None:
    c = clf.classify("hola", None)
    assert c.category == "fatico"
    assert c.confidence == 0.3
    assert not clf.is_confident(c)


def test_comprehension_dict_input(clf: TurnClassifier) -> None:
    """The persisted trace comprehension is a dict — accept it directly."""
    c = clf.classify(
        "hola", {"intent": "saludar", "emotion": "neutral", "urgency": "baja", "risk": "bajo"}
    )
    assert c.category == "fatico"
    assert c.confidence == 1.0


def test_comprehension_partial_dict_falls_back(clf: TurnClassifier) -> None:
    """S11: partial dict (no emotion/urgency/risk) → safe fallback, never fast-lane.

    Without emotion/urgency/risk the phatic/informational branches cannot fire,
    so a saludo-like partial comprehension falls to informativo 0.5 — pinned
    here so a regression that classifies partial input as a confident fático
    (inflating F2) would fail."""
    c = clf.classify("hola", {"intent": "saludar"})
    assert c.category == "informativo"
    assert c.confidence == 0.5
    assert not clf.is_confident(c)


def test_apply_overrides(clf: TurnClassifier) -> None:
    clf.apply_overrides({"confidence_min": 0.9})
    assert clf.confidence_min == 0.9
    # A fático 1.0 sigue confiado; el "no estoy seguro" 0.3 no.
    assert clf.is_confident(TurnClassification("fatico", 1.0, "x")) is True
    assert clf.is_confident(TurnClassification("fatico", 0.3, "x")) is False


def test_apply_overrides_invalid_config_does_not_crash(clf: TurnClassifier) -> None:
    clf.apply_overrides({"confidence_min": "not-a-number"})
    assert clf.confidence_min == CLASSIFIER_CONFIDENCE_MIN
    clf.apply_overrides({"confidence_min": 2.0})  # out of range → rejected
    assert clf.confidence_min == CLASSIFIER_CONFIDENCE_MIN
    clf.apply_overrides(None)  # type: ignore[arg-type]
    assert clf.confidence_min == CLASSIFIER_CONFIDENCE_MIN
    clf.apply_overrides({})  # missing key → no-op
    assert clf.confidence_min == CLASSIFIER_CONFIDENCE_MIN


def test_apply_overrides_without_key_keeps_default(clf: TurnClassifier) -> None:
    clf.apply_overrides({"other_key": 1})
    assert clf.confidence_min == CLASSIFIER_CONFIDENCE_MIN


def test_import_purity() -> None:
    """The classifier is a pure application module: no aiogram, no infra."""
    import diana
    from diana.application import turn_classifier

    path = Path(turn_classifier.__file__)
    text = path.read_text(encoding="utf-8")
    assert "diana" in text  # module references the package (sanity)
    forbidden = ("aiogram", "infrastructure", "telegram", "sqlalchemy")
    for token in forbidden:
        assert token not in text, token
    root = Path(diana.__file__).resolve().parent
    assert root.name == "diana"


def test_is_pure_greeting_saludar_confident(clf: TurnClassifier) -> None:
    assert is_pure_greeting("Hola", _comp(intent="saludar"), classifier=clf) is True


def test_is_pure_greeting_rejects_agradecer(clf: TurnClassifier) -> None:
    assert is_pure_greeting("gracias", _comp(intent="agradecer"), classifier=clf) is False


def test_is_pure_greeting_rejects_ambiguous_and_short(clf: TurnClassifier) -> None:
    amb = _comp(intent="saludar")
    assert (
        is_pure_greeting("Hola, es que no sé si contarte algo", amb, classifier=clf)
        is False
    )
    assert is_pure_greeting("hi", amb, classifier=clf) is False


def test_is_pure_greeting_carinosa_boundary(clf: TurnClassifier) -> None:
    """saludo_con_afecto (0.7 == default min) remains pure greeting."""
    assert (
        is_pure_greeting(
            "Hola amor",
            _comp(intent="saludar", emotion="cariñosa"),
            classifier=clf,
        )
        is True
    )


def test_make_pure_greeting_cut_binds_classifier(clf: TurnClassifier) -> None:
    cut = make_pure_greeting_cut(clf)
    assert cut("Hola", _comp(intent="saludar")) is True
    assert cut("gracias", _comp(intent="agradecer")) is False
