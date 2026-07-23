"""Unit tests for deterministic Planner (Anexo C.1–C.4, no LLM)."""

from __future__ import annotations

import pytest

from diana.cognitive.models import Comprehension
from diana.cognitive.planner import Planner

_NEED_FLAGS = (
    "needs_history",
    "needs_context",
    "needs_memory",
    "needs_policy",
    "needs_examples",
    "needs_schedule",
)

_FLAG_TO_CAP = {
    "needs_history": "knowledge.history",
    "needs_context": "knowledge.context",
    "needs_memory": "knowledge.memory",
    "needs_policy": "knowledge.policy",
    "needs_examples": "knowledge.examples",
    "needs_schedule": "knowledge.schedule",
}


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


def test_planner_maps_default_needs_to_history_and_context() -> None:
    plan = Planner().plan(_comprehension())
    assert plan.capabilities == ["knowledge.history", "knowledge.context"]


def test_planner_includes_all_needs_in_stable_order() -> None:
    plan = Planner().plan(
        _comprehension(
            needs_history=True,
            needs_context=True,
            needs_memory=True,
            needs_policy=True,
            needs_examples=True,
            needs_schedule=True,
        )
    )
    assert plan.capabilities == [
        "knowledge.history",
        "knowledge.context",
        "knowledge.memory",
        "knowledge.policy",
        "knowledge.examples",
        "knowledge.schedule",
    ]


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
    plan = Planner().plan(
        _comprehension(
            needs_history=False,
            needs_context=False,
            needs_memory=False,
            needs_policy=False,
            needs_examples=False,
            needs_schedule=False,
        )
    )
    assert plan.capabilities == []


@pytest.mark.parametrize("false_flag", _NEED_FLAGS)
def test_planner_never_requests_cap_when_need_false(false_flag: str) -> None:
    """C.3: each capability is present iff its needs_* flag is true."""
    flags = {flag: True for flag in _NEED_FLAGS}
    flags[false_flag] = False
    plan = Planner().plan(_comprehension(**flags))
    absent_cap = _FLAG_TO_CAP[false_flag]
    assert absent_cap not in plan.capabilities
    for flag, cap in _FLAG_TO_CAP.items():
        if flag == false_flag:
            continue
        assert cap in plan.capabilities


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
    """C.4 set equality; list order follows stable _NEED_TO_CAPABILITY map."""
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
    assert set(plan.capabilities) == set(expected_stable)
    assert plan.capabilities == expected_stable
    assert "knowledge.policy" not in plan.capabilities


def test_planner_has_no_llm_dependency() -> None:
    import inspect

    from diana.cognitive import planner as planner_mod

    source = inspect.getsource(planner_mod)
    assert "LLM" not in source
    assert "generate" not in source
