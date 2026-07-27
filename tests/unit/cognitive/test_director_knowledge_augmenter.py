"""Director optional KnowledgeAugmenter hook (sandbox profile inject)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from diana.cognitive.analyst import Analyst
from diana.cognitive.context_builder import ContextBuilder
from diana.cognitive.decider import Decider
from diana.cognitive.director import CognitiveDirector
from diana.cognitive.evaluator import Evaluator
from diana.cognitive.generator import Generator
from diana.cognitive.models import Comprehension, Decision, EvaluationProfile, IncomingTurn
from diana.cognitive.planner import Planner
from diana.cognitive.ports import InMemoryMessageHistory, InMemoryTraceStore
from diana.cognitive.registry import build_default_registry
from diana.llm.fake import FakeLLM


def _comprehension(**overrides: Any) -> Comprehension:
    data: dict[str, Any] = {
        "intent": "saludo",
        "topics": ["general"],
        "emotion": "neutral",
        "urgency": "baja",
        "risk": "bajo",
        "needs_history": False,
        "needs_context": False,
        "needs_memory": False,
        "needs_policy": False,
        "needs_schedule": False,
        "needs_examples": False,
        "needs_profile": False,
    }
    data.update(overrides)
    return Comprehension(**data)


def _profile(**overrides: float) -> EvaluationProfile:
    base = dict(
        naturalness=0.9,
        precision=0.9,
        doctrine=0.9,
        consistency=0.9,
        safety=0.95,
        coverage=0.9,
        empathy=0.9,
    )
    base.update(overrides)
    return EvaluationProfile(**base)


class _ForceProfileAugmenter:
    async def augment_retrieved(
        self, turn: IncomingTurn, retrieved: dict[str, Any | None]
    ) -> dict[str, Any | None]:
        out = dict(retrieved)
        out["knowledge.profile"] = {
            "tipo": "sandbox_fixture",
            "content": {"facts": {"name": "Force"}, "notes": []},
        }
        return out


@pytest.mark.asyncio
async def test_director_augmenter_forces_profile_even_when_plan_omits_it() -> None:
    """Plan has no profile capability; augmenter still injects knowledge.profile."""
    llm = FakeLLM(
        structured_responses=[
            _comprehension(),  # all needs_* false → empty plan capabilities
            _profile(),
        ],
        text_responses=["Draft from sandbox"],
    )
    history = InMemoryMessageHistory()
    trace = InMemoryTraceStore()
    director = CognitiveDirector(
        analyst=Analyst(llm),
        planner=Planner(),
        registry=build_default_registry(history),
        context_builder=ContextBuilder(),
        generator=Generator(llm),
        evaluator=Evaluator(llm),
        decider=Decider(),
        trace=trace,
        persona="You are Diana.",
        history=history,
        knowledge_augmenter=_ForceProfileAugmenter(),
    )
    turn = IncomingTurn(turn_id=uuid4(), chat_id=77, text="hola")
    decision = await director.handle_turn(turn)
    assert isinstance(decision, Decision)
    retrieved = trace.get(turn.turn_id, "retrieved")
    assert retrieved is not None
    assert "knowledge.profile" in retrieved
    assert retrieved["knowledge.profile"]["tipo"] == "sandbox_fixture"
