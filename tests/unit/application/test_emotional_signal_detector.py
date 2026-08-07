"""Table-of-cases tests for the heuristic EmotionalSignalDetector (no LLM/DB)."""

from __future__ import annotations

from ast import parse
from pathlib import Path

from diana.application.emotional_signal_detector import (
    BASELINE_WARM_RATIO_COOL,
    BASELINE_WARM_RATIO_OPEN,
    ESCALATE_THRESHOLD,
    MIN_BASELINE_TURNS,
    MIN_BASELINE_TURNS_MAX,
    MIN_BASELINE_TURNS_MIN,
    SYNTHESIS_THRESHOLD,
    EmotionalSignalDetector,
)
from diana.cognitive.models import Comprehension


def _comp(**kw) -> dict:
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
    return data


def _model(**kw) -> Comprehension:
    return Comprehension(**_comp(**kw))


def _detector(**kw) -> EmotionalSignalDetector:
    return EmotionalSignalDetector(**kw)


def test_angustia_signal() -> None:
    for emotion in ("ansiosa", "molesta", "triste"):
        for risk in ("medio", "alto"):
            sig = _detector().detect(
                _comp(emotion=emotion, urgency="alta", risk=risk),
                None,
                "approve",
            )
            assert sig.signal_type == "angustia", (emotion, risk)
            assert sig.intensity == 0.85
            assert sig.should_trigger_synthesis is True
            assert sig.should_escalate_to_owner is True


def test_angustia_requires_high_urgency() -> None:
    sig = _detector().detect(
        _comp(emotion="triste", urgency="media", risk="alto"), None, None
    )
    assert sig.signal_detected is False


def test_vulnerabilidad_signal_by_intent() -> None:
    for intent in ("pedir_consejo", "contar_anecdota", "compartir_logro"):
        sig = _detector().detect(
            _comp(emotion="triste", intent=intent), None, "approve"
        )
        assert sig.signal_type == "vulnerabilidad", intent
        assert sig.intensity == 0.6
        assert sig.should_trigger_synthesis is True
        assert sig.should_escalate_to_owner is False


def test_vulnerabilidad_requires_personal_opening_intent() -> None:
    """Spec contract: emotion {triste, ansiosa} AND a personal-opening intent.

    Topics alone must NOT trigger vulnerabilidad (opening is behavioural, not
    topical). A topical-only turn either falls through to revelacion_de_vida
    (when a revelation topic matches) or produces no signal.
    """
    for intent in ("pedir_consejo", "contar_anecdota", "compartir_logro"):
        sig = _detector().detect(
            _comp(emotion="ansiosa", intent=intent), None, None
        )
        assert sig.signal_type == "vulnerabilidad", intent
    # ansiosa + a revelation topic but NO opening intent → revelacion_de_vida.
    for topic in ("conexion", "tema_pesado", "honestidad"):
        sig = _detector().detect(
            _comp(emotion="ansiosa", topics=[topic]), None, None
        )
        assert sig.signal_type == "revelacion_de_vida", topic
    # ansiosa + a non-revelation topic + no opening intent → no signal.
    sig = _detector().detect(
        _comp(emotion="ansiosa", topics=["apertura"]), None, None
    )
    assert sig.signal_detected is False


def test_vulnerabilidad_negative_no_opening() -> None:
    """triste without a personal-opening intent → no signal."""
    sig = _detector().detect(
        _comp(emotion="triste", intent="saludar", topics=["saludo"]),
        None,
        None,
    )
    assert sig.signal_detected is False


def test_topics_filters_non_string_tokens() -> None:
    """None/ints in topics are analyst artifacts, never vocabulary tokens."""
    sig = _detector().detect(
        _comp(topics=["tema_pesado", None, 123]), None, None
    )
    assert sig.signal_type == "revelacion_de_vida"
    sig2 = _detector().detect(_comp(topics=[None, 123]), None, None)
    assert sig2.signal_detected is False


def test_revelacion_de_vida_by_useful_tag() -> None:
    """honestidad is an analyst useful tag, not a mandatory topic."""
    sig = _detector().detect(_comp(topics=["honestidad"]), None, None)
    assert sig.signal_type == "revelacion_de_vida"
    assert sig.intensity == 0.5
    assert sig.should_trigger_synthesis is True
    assert sig.should_escalate_to_owner is False


def test_revelacion_de_vida_by_mandatory_topic() -> None:
    sig = _detector().detect(_comp(topics=["tema_pesado"]), None, None)
    assert sig.signal_type == "revelacion_de_vida"


def test_revelacion_de_vida_matches_extrañar_and_reencuentro() -> None:
    for topic in ("extrañar", "reencuentro", "conexion"):
        sig = _detector().detect(_comp(topics=[topic]), None, None)
        assert sig.signal_type == "revelacion_de_vida", topic


def test_ruptura_de_patron_distant_opens_up() -> None:
    """Cold baseline (warm_ratio 0) + current warm emotion → signal."""
    baseline = [
        _comp(emotion="neutral"),
        _comp(emotion="neutral"),
        _comp(emotion="molesta"),
        _comp(emotion="ansiosa"),
        _comp(emotion="triste"),
    ]
    sig = _detector().detect(_comp(emotion="positiva"), baseline, None)
    assert sig.signal_type == "ruptura_de_patron"
    assert sig.intensity == 0.55
    assert sig.should_trigger_synthesis is True
    assert sig.should_escalate_to_owner is False


def test_ruptura_de_patron_warm_cools_off() -> None:
    """Warm baseline (warm_ratio >= 0.7) + current cold emotion → signal."""
    baseline = [
        _comp(emotion="positiva"),
        _comp(emotion="cariñosa"),
        _comp(emotion="positiva"),
        _comp(emotion="cariñosa"),
        _comp(emotion="positiva"),
    ]
    sig = _detector().detect(_comp(emotion="triste"), baseline, None)
    assert sig.signal_type == "ruptura_de_patron"
    assert sig.intensity == 0.55


def test_ruptura_de_patron_no_signal_below_min_baseline() -> None:
    """Under MIN_BASELINE_TURNS → no signal (no noise in new chats)."""
    baseline = [
        _comp(emotion="neutral"),
        _comp(emotion="molesta"),
        _comp(emotion="triste"),
    ]  # only 3 < 5
    sig = _detector().detect(_comp(emotion="positiva"), baseline, None)
    assert sig.signal_detected is False


def test_ruptura_de_patron_no_signal_on_empty_baseline() -> None:
    sig = _detector().detect(_comp(emotion="positiva"), None, None)
    assert sig.signal_detected is False


def test_signal_priority_angustia_over_vulnerabilidad() -> None:
    """angustia (most urgent) wins over vulnerabilidad."""
    sig = _detector().detect(
        _comp(
            emotion="triste",
            urgency="alta",
            risk="alto",
            intent="contar_anecdota",
        ),
        None,
        None,
    )
    assert sig.signal_type == "angustia"


def test_flag_derivation_thresholds() -> None:
    d = _detector()
    # Below synthesis threshold → neither flag.
    low = d._build(  # noqa: SLF001
        signal_type="vulnerabilidad", intensity=0.49, decision_action=None
    )
    assert low.should_trigger_synthesis is False
    assert low.should_escalate_to_owner is False
    # At exactly escalate threshold → escalate True.
    high = d._build(  # noqa: SLF001
        signal_type="angustia", intensity=0.8, decision_action=None
    )
    assert high.should_escalate_to_owner is True


def test_pipeline_would_have_escalated() -> None:
    d = _detector()
    assert d.detect(_comp(emotion="molesta", urgency="alta", risk="alto"), None, "escalate").pipeline_would_have_escalated is True
    assert d.detect(_comp(emotion="molesta", urgency="alta", risk="alto"), None, "approve").pipeline_would_have_escalated is False
    assert d.detect(_comp(emotion="molesta", urgency="alta", risk="alto"), None, None).pipeline_would_have_escalated is None


def test_detector_accepts_comprehension_model() -> None:
    sig = _detector().detect(
        _model(emotion="ansiosa", urgency="alta", risk="alto"), None, None
    )
    assert sig.signal_type == "angustia"


def test_detector_handles_non_dict_comprehension() -> None:
    sig = _detector().detect("not-a-dict", None, None)
    assert sig.signal_detected is False


def test_apply_overrides_changes_outcome() -> None:
    d = _detector(synthesis_threshold=0.5, escalate_threshold=0.8)
    # revelacion_de_vida intensity 0.5 triggers synthesis at default.
    assert d.detect(_comp(topics=["honestidad"]), None, None).should_trigger_synthesis is True
    d.apply_overrides({"synthesis_threshold": 0.6})
    assert d.detect(_comp(topics=["honestidad"]), None, None).should_trigger_synthesis is False


def test_apply_overrides_invalid_config_does_not_crash() -> None:
    d = _detector()
    d.apply_overrides({"synthesis_threshold": "bogus", "escalate_threshold": -5})
    assert d.synthesis_threshold == SYNTHESIS_THRESHOLD
    assert d.escalate_threshold == ESCALATE_THRESHOLD
    d.apply_overrides(None)
    # 0 clamps to the floor MIN_BASELINE_TURNS_MIN (1), not "keep the default".
    d.apply_overrides({"min_baseline_turns": 0})
    assert d.min_baseline_turns == MIN_BASELINE_TURNS_MIN
    # Negative values clamp to the floor too.
    d.apply_overrides({"min_baseline_turns": -3})
    assert d.min_baseline_turns == MIN_BASELINE_TURNS_MIN
    # Oversized values clamp to the ceiling.
    d.apply_overrides({"min_baseline_turns": 1_000_000})
    assert d.min_baseline_turns == MIN_BASELINE_TURNS_MAX


def test_apply_overrides_rejects_inverted_threshold_pair() -> None:
    """escalate_threshold must stay strictly above synthesis_threshold."""
    d = _detector()
    # Inverted pair (synthesis 0.95, escalate 0.2) → rejected wholesale.
    d.apply_overrides(
        {"synthesis_threshold": 0.95, "escalate_threshold": 0.2}
    )
    assert d.synthesis_threshold == SYNTHESIS_THRESHOLD
    assert d.escalate_threshold == ESCALATE_THRESHOLD
    # Equal pair → rejected.
    d.apply_overrides(
        {"synthesis_threshold": 0.5, "escalate_threshold": 0.5}
    )
    assert d.synthesis_threshold == SYNTHESIS_THRESHOLD
    # A synthesis raise that would exceed escalate → rejected as a pair.
    d.apply_overrides({"synthesis_threshold": 0.9})
    assert d.synthesis_threshold == SYNTHESIS_THRESHOLD
    # Valid asymmetric pair still applies.
    d.apply_overrides(
        {"synthesis_threshold": 0.6, "escalate_threshold": 0.9}
    )
    assert d.synthesis_threshold == 0.6
    assert d.escalate_threshold == 0.9


def test_apply_overrides_min_baseline_turns() -> None:
    d = _detector()
    d.apply_overrides({"min_baseline_turns": 2})
    assert d.min_baseline_turns == 2
    # With a 2-turn baseline a pattern break now fires.
    baseline = [_comp(emotion="neutral"), _comp(emotion="molesta")]
    sig = d.detect(_comp(emotion="positiva"), baseline, None)
    assert sig.signal_type == "ruptura_de_patron"


def test_no_llm_import_in_detector_module() -> None:
    """Import-purity: the detector must not import any LLM provider."""
    path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "diana"
        / "application"
        / "emotional_signal_detector.py"
    )
    tree = parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in __import__("ast").walk(tree):
        if isinstance(node, __import__("ast").Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, __import__("ast").ImportFrom) and node.module:
            imports.append(node.module)
    for module in imports:
        assert not module.startswith("diana.llm"), module
    assert "aiogram" not in " ".join(imports)
