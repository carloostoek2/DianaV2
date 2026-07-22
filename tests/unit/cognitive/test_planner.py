"""Unit tests for deterministic Planner (no LLM)."""

from __future__ import annotations

from diana.cognitive.models import Comprehension
from diana.cognitive.planner import Planner


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


def test_planner_inserts_history_first_when_missing() -> None:
    plan = Planner().plan(
        _comprehension(
            needs_history=False,
            needs_context=True,
            needs_memory=True,
        )
    )
    assert plan.capabilities[0] == "knowledge.history"
    assert "knowledge.context" in plan.capabilities
    assert "knowledge.memory" in plan.capabilities


def test_planner_forces_history_even_when_all_false() -> None:
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
    assert plan.capabilities == ["knowledge.history"]


def test_planner_has_no_llm_dependency() -> None:
    import inspect

    from diana.cognitive import planner as planner_mod

    source = inspect.getsource(planner_mod)
    assert "LLM" not in source
    assert "generate" not in source
