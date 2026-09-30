"""Option A: hard-OR needs_profile when VIP has non-empty profiles.content.notes."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from diana.application.sandbox import SandboxService
from diana.application.sandbox_knowledge import SandboxKnowledgeAugmenter
from diana.application.turn_classifier import TurnClassifier, make_pure_greeting_cut
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
        "intent": "preferencias",
        "topics": ["gustos"],
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


def _eval_profile(**overrides: float) -> EvaluationProfile:
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


class _FakeProfilesRepo:
    """Duck-typed ProfilesRepo: get_by_vip_id → profile dict or None."""

    def __init__(self, content: dict[str, Any] | None) -> None:
        self._content = content
        self.calls: list[Any] = []

    async def get_by_vip_id(self, vip_id: Any) -> dict | None:
        self.calls.append(vip_id)
        if self._content is None:
            return None
        return {
            "vip_id": str(vip_id),
            "tipo": "summary",
            "content": self._content,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }


def _make_director(
    llm: FakeLLM,
    *,
    force: bool = True,
    profiles_repo: Any | None = None,
    registry: Any | None = None,
    knowledge_augmenter: Any | None = None,
    pure_greeting_cut: Any | None = None,
    saludo_response_pool: list[str] | None = None,
) -> tuple[CognitiveDirector, InMemoryTraceStore]:
    history = InMemoryMessageHistory()
    trace = InMemoryTraceStore()
    director = CognitiveDirector(
        analyst=Analyst(llm),
        planner=Planner(),
        registry=registry or build_default_registry(history),
        context_builder=ContextBuilder(),
        generator=Generator(llm),
        evaluator=Evaluator(llm),
        decider=Decider(),
        trace=trace,
        persona="Eres Diana.",
        history=history,
        force_profile_when_notes=force,
        profiles_repo=profiles_repo,
        knowledge_augmenter=knowledge_augmenter,
        pure_greeting_cut=pure_greeting_cut,
        saludo_response_pool=saludo_response_pool,
    )
    return director, trace


@pytest.mark.asyncio
async def test_notes_present_forces_needs_profile_when_analyst_says_false() -> None:
    """VIP with notes + Analyst needs_profile=False → stored/plan include profile."""
    vip_id = uuid4()
    repo = _FakeProfilesRepo(
        {"facts": {}, "notes": [{"date": "2026-09-01", "text": "Prefiere tono suave"}]}
    )
    history = InMemoryMessageHistory()
    registry = build_default_registry(history, profile_repo=repo)
    llm = FakeLLM(
        structured_responses=[_comprehension(needs_profile=False), _eval_profile()],
        text_responses=["Ok amor, lo tengo en cuenta"],
    )
    director, trace = _make_director(llm, force=True, profiles_repo=repo, registry=registry)
    turn = IncomingTurn(turn_id=uuid4(), chat_id=10, text="qué plan hoy?", vip_id=vip_id)
    decision = await director.handle_turn(turn)

    assert isinstance(decision, Decision)
    stored = trace.get(turn.turn_id, "comprehension")
    assert stored["needs_profile"] is True
    assert stored["needs_profile_forced"] is True
    plan = trace.get(turn.turn_id, "plan")
    assert "knowledge.profile" in plan["capabilities"]
    # Force lookup + ProfileRetriever.fetch both hit the same repo.
    assert vip_id in repo.calls
    assert len(repo.calls) >= 1


@pytest.mark.asyncio
async def test_hollow_or_no_notes_leaves_flag_false() -> None:
    """VIP without notes / facts-only → needs_profile stays false."""
    vip_id = uuid4()
    repo = _FakeProfilesRepo({"facts": {"nombre": "Luis"}, "notes": []})
    llm = FakeLLM(
        structured_responses=[_comprehension(needs_profile=False), _eval_profile()],
        text_responses=["Draft"],
    )
    director, trace = _make_director(llm, force=True, profiles_repo=repo)
    turn = IncomingTurn(turn_id=uuid4(), chat_id=11, text="hola qué tal", vip_id=vip_id)
    await director.handle_turn(turn)

    stored = trace.get(turn.turn_id, "comprehension")
    assert stored["needs_profile"] is False
    assert stored["needs_profile_forced"] is False
    plan = trace.get(turn.turn_id, "plan")
    assert "knowledge.profile" not in plan["capabilities"]


@pytest.mark.asyncio
async def test_vip_id_none_no_force_br15() -> None:
    """vip_id None → no force even with a repo that would return notes."""
    repo = _FakeProfilesRepo(
        {"facts": {}, "notes": [{"date": "2026-09-01", "text": "no debería leerse"}]}
    )
    llm = FakeLLM(
        structured_responses=[_comprehension(needs_profile=False), _eval_profile()],
        text_responses=["Draft"],
    )
    director, trace = _make_director(llm, force=True, profiles_repo=repo)
    turn = IncomingTurn(turn_id=uuid4(), chat_id=12, text="pregunta", vip_id=None)
    await director.handle_turn(turn)

    stored = trace.get(turn.turn_id, "comprehension")
    assert stored["needs_profile"] is False
    assert stored["needs_profile_forced"] is False
    assert repo.calls == []


@pytest.mark.asyncio
async def test_flag_off_no_force_even_with_notes() -> None:
    """Flag OFF → no force even when notes exist."""
    vip_id = uuid4()
    repo = _FakeProfilesRepo(
        {"facts": {}, "notes": [{"date": "2026-09-01", "text": "nota real"}]}
    )
    llm = FakeLLM(
        structured_responses=[_comprehension(needs_profile=False), _eval_profile()],
        text_responses=["Draft"],
    )
    director, trace = _make_director(llm, force=False, profiles_repo=repo)
    turn = IncomingTurn(turn_id=uuid4(), chat_id=13, text="pregunta", vip_id=vip_id)
    await director.handle_turn(turn)

    stored = trace.get(turn.turn_id, "comprehension")
    assert stored["needs_profile"] is False
    assert stored["needs_profile_forced"] is False
    assert repo.calls == []


@pytest.mark.asyncio
async def test_analyst_already_true_not_marked_forced() -> None:
    """OR never clears True; natural Analyst hit keeps needs_profile_forced False."""
    vip_id = uuid4()
    repo = _FakeProfilesRepo(
        {"facts": {}, "notes": [{"date": "2026-09-01", "text": "nota"}]}
    )
    llm = FakeLLM(
        structured_responses=[_comprehension(needs_profile=True), _eval_profile()],
        text_responses=["Draft"],
    )
    director, trace = _make_director(llm, force=True, profiles_repo=repo)
    turn = IncomingTurn(turn_id=uuid4(), chat_id=14, text="mis gustos", vip_id=vip_id)
    await director.handle_turn(turn)

    stored = trace.get(turn.turn_id, "comprehension")
    assert stored["needs_profile"] is True
    assert stored["needs_profile_forced"] is False
    # Short-circuit: no lookup when Analyst already True
    assert repo.calls == []


@pytest.mark.asyncio
async def test_director_path_retrieved_profile_and_opd_fence() -> None:
    """Full Director path: retrieved has knowledge.profile + OPD fence when forced."""
    vip_id = uuid4()
    notes_content = {
        "facts": {},
        "notes": [{"date": "2026-09-01", "text": "Le gusta que le digan amor"}],
    }
    repo = _FakeProfilesRepo(notes_content)
    history = InMemoryMessageHistory()
    registry = build_default_registry(history, profile_repo=repo)
    llm = FakeLLM(
        structured_responses=[_comprehension(needs_profile=False), _eval_profile()],
        text_responses=["Claro amor"],
    )
    director, trace = _make_director(
        llm, force=True, profiles_repo=repo, registry=registry
    )
    turn = IncomingTurn(turn_id=uuid4(), chat_id=15, text="cómo me hablas?", vip_id=vip_id)
    await director.handle_turn(turn)

    retrieved = trace.get(turn.turn_id, "retrieved")
    assert retrieved is not None
    assert "knowledge.profile" in retrieved
    assert retrieved["knowledge.profile"] is not None
    prompt = trace.get(turn.turn_id, "prompt_text")
    assert "<<OWNER_PROFILE_DATA>>" in prompt
    assert "<</OWNER_PROFILE_DATA>>" in prompt
    assert "## Knowledge: knowledge.profile" in prompt


@pytest.mark.asyncio
async def test_early_exit_greeting_still_skips_profile() -> None:
    """Pure greeting early-exit still does not require/retrieve profile."""
    vip_id = uuid4()
    repo = _FakeProfilesRepo(
        {"facts": {}, "notes": [{"date": "2026-09-01", "text": "nota"}]}
    )
    history = InMemoryMessageHistory()
    registry = build_default_registry(history, profile_repo=repo)
    # Analyst returns a saludo-shaped comprehension; cut fires before Planner.
    llm = FakeLLM(
        structured_responses=[
            _comprehension(
                intent="saludar",
                topics=["apertura"],
                needs_profile=False,
                needs_history=False,
                needs_context=False,
            )
        ],
        text_responses=[],  # no Generator call expected
    )
    cut = make_pure_greeting_cut(TurnClassifier())
    director, trace = _make_director(
        llm,
        force=True,
        profiles_repo=repo,
        registry=registry,
        pure_greeting_cut=cut,
        saludo_response_pool=["Holis 😁"],
    )
    turn = IncomingTurn(turn_id=uuid4(), chat_id=16, text="hola", vip_id=vip_id)
    decision = await director.handle_turn(turn)

    assert decision.reason == "plantilla_saludo"
    assert decision.draft_text == "Holis 😁"
    assert trace.get(turn.turn_id, "plan") is None
    assert trace.get(turn.turn_id, "retrieved") is None
    assert trace.get(turn.turn_id, "prompt_text") is None


@pytest.mark.asyncio
async def test_sandbox_fixture_wins_over_forced_real_profile() -> None:
    """Sandbox active + notes force: SandboxKnowledgeAugmenter fixture still wins.

    Force puts knowledge.profile on the plan (real notes retrieved first);
    the augmenter then overwrites with the sandbox fixture (existing behavior).
    """
    vip_id = uuid4()
    real_notes = {
        "facts": {"name": "RealVIP"},
        "notes": [{"date": "2026-09-01", "text": "nota real del VIP"}],
    }
    repo = _FakeProfilesRepo(real_notes)
    history = InMemoryMessageHistory()
    registry = build_default_registry(history, profile_repo=repo)

    catalog = {
        "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
        "cercano": {
            "label": "VIP cercano",
            "description": "",
            "facts": {"name": "FixtureMateo"},
            "notes": [{"date": "2026-05-10", "text": "fixture note"}],
        },
        "distante": {
            "label": "VIP reservado",
            "description": "",
            "facts": {"personality": "formal"},
            "notes": [],
        },
        "intenso": {
            "label": "VIP emocional",
            "description": "",
            "facts": {"relationship": "recién separado"},
            "notes": [],
        },
        "vip_largo": {
            "label": "VIP largo",
            "description": "",
            "facts": {"name": "Sofía"},
            "notes": [],
        },
        "inyeccion_previa": {
            "label": "Fixture adversarial",
            "description": "",
            "facts": {"name": "TestUser"},
            "notes": [],
        },
    }
    sandbox = SandboxService(profiles=catalog)
    chat_id = 77
    sandbox.activate(chat_id, "cercano")
    augmenter = SandboxKnowledgeAugmenter(sandbox)

    llm = FakeLLM(
        structured_responses=[_comprehension(needs_profile=False), _eval_profile()],
        text_responses=["Draft sandbox"],
    )
    director, trace = _make_director(
        llm,
        force=True,
        profiles_repo=repo,
        registry=registry,
        knowledge_augmenter=augmenter,
    )
    turn = IncomingTurn(
        turn_id=uuid4(), chat_id=chat_id, text="cuéntame algo", vip_id=vip_id
    )
    await director.handle_turn(turn)

    plan = trace.get(turn.turn_id, "plan")
    assert "knowledge.profile" in plan["capabilities"]
    retrieved = trace.get(turn.turn_id, "retrieved")
    assert retrieved["knowledge.profile"]["tipo"] == "sandbox_fixture"
    assert retrieved["knowledge.profile"]["content"]["facts"]["name"] == "FixtureMateo"
