"""Unit tests for deterministic Planner (Anexo C.1–C.4, no LLM)."""

from __future__ import annotations

import pytest

from diana.cognitive.models import Comprehension
from diana.cognitive.planner import Planner, _NEED_TO_CAPABILITY

_NEED_FLAGS = tuple(attr for attr, _ in _NEED_TO_CAPABILITY)
_FLAG_TO_CAP = dict(_NEED_TO_CAPABILITY)
_STABLE_CAPS = [cap for _, cap in _NEED_TO_CAPABILITY]


def _comprehension(**overrides) -> Comprehension:
    data = {
        "intent": "chat",
        "topics": ["general"],
        "emotion": "neutral",
        "urgency": "baja",
        "risk": "bajo",
        "needs_history": True,
        "needs_context": True,
        "needs_memory": False,
        "needs_policy": False,
        "needs_examples": False,
        "needs_schedule": False,
    }
    data.update(overrides)
    return Comprehension(**data)


def _all_needs(value: bool) -> dict[str, bool]:
    return {flag: value for flag in _NEED_FLAGS}


def test_planner_maps_default_needs_to_history_and_context() -> None:
    plan = Planner().plan(_comprehension())
    assert plan.capabilities == ["knowledge.history", "knowledge.context"]


def test_planner_includes_all_needs_in_stable_order() -> None:
    plan = Planner().plan(_comprehension(**_all_needs(True)))
    assert plan.capabilities == _STABLE_CAPS


def test_planner_omits_history_when_needs_history_false() -> None:
    """C.3: never request knowledge.history when needs_history is false."""
    plan = Planner().plan(
        _comprehension(
            needs_history=False,
            needs_context=True,
            needs_memory=True,
        )
    )
    assert plan.capabilities == ["knowledge.context", "knowledge.memory"]
    assert "knowledge.history" not in plan.capabilities


def test_planner_returns_empty_when_all_needs_false() -> None:
    """C.3/C.4: empty plan is legal when all needs_* are false."""
    plan = Planner().plan(_comprehension(**_all_needs(False)))
    assert plan.capabilities == []


@pytest.mark.parametrize("false_flag", _NEED_FLAGS)
def test_planner_never_requests_cap_when_need_false(false_flag: str) -> None:
    """C.3: exact ordered list = full map minus the false flag (no extras/dupes)."""
    flags = _all_needs(True)
    flags[false_flag] = False
    plan = Planner().plan(_comprehension(**flags))
    expected = [cap for attr, cap in _NEED_TO_CAPABILITY if attr != false_flag]
    assert plan.capabilities == expected
    assert len(plan.capabilities) == len(_NEED_FLAGS) - 1


@pytest.mark.parametrize("true_flag,expected_cap", list(_NEED_TO_CAPABILITY))
def test_planner_single_true_flag_maps_to_single_cap(
    true_flag: str, expected_cap: str
) -> None:
    """C.2/C.3: one needs_* true → exact single-element capabilities list."""
    flags = _all_needs(False)
    flags[true_flag] = True
    plan = Planner().plan(_comprehension(**flags))
    assert plan.capabilities == [expected_cap]


def test_planner_determinism_same_comprehension_same_plan() -> None:
    """C.3: same Comprehension → same Plan."""
    comp = _comprehension(
        needs_history=True,
        needs_context=False,
        needs_memory=True,
        needs_policy=False,
        needs_examples=True,
        needs_schedule=False,
    )
    planner = Planner()
    plan1 = planner.plan(comp)
    plan2 = planner.plan(comp)
    assert plan1.capabilities == plan2.capabilities
    assert plan1 == plan2


def test_planner_c4_example_set() -> None:
    """C.4 set equality (contract example is a set) + stable list order (L5)."""
    plan = Planner().plan(
        _comprehension(
            needs_history=True,
            needs_context=True,
            needs_memory=True,
            needs_policy=False,
            needs_examples=True,
            needs_schedule=True,
        )
    )
    expected_stable = [
        "knowledge.history",
        "knowledge.context",
        "knowledge.memory",
        "knowledge.examples",
        "knowledge.schedule",
    ]
    # Set assert documents C.4 set-equality; list assert locks L5 order.
    assert set(plan.capabilities) == set(expected_stable)
    assert plan.capabilities == expected_stable
    assert "knowledge.policy" not in plan.capabilities


def test_planner_has_no_llm_dependency() -> None:
    import inspect

    from diana.cognitive import planner as planner_mod

    source = inspect.getsource(planner_mod)
    assert "LLM" not in source
    assert "generate" not in source


def test_planner_persona_voice_order_between_context_and_memory() -> None:
    """H2: persona_facts, voice_patterns, profile sit after context, before memory."""
    expected = [
        "knowledge.history",
        "knowledge.context",
        "knowledge.persona_facts",
        "knowledge.voice_patterns",
        "knowledge.profile",
        "knowledge.memory",
        "knowledge.policy",
        "knowledge.examples",
        "knowledge.schedule",
    ]
    assert _STABLE_CAPS == expected
    plan = Planner().plan(_comprehension(**_all_needs(True)))
    assert plan.capabilities == expected


def test_planner_needs_profile_alone_maps_to_profile() -> None:
    """Option B: needs_profile=True alone → [knowledge.profile]."""
    plan = Planner().plan(_comprehension(**_all_needs(False), needs_profile=True))
    assert plan.capabilities == ["knowledge.profile"]
