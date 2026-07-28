"""SandboxKnowledgeAugmenter — force fixture profile into retrieved map."""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.application.sandbox import SandboxService
from diana.application.sandbox_knowledge import SandboxKnowledgeAugmenter
from diana.cognitive.models import IncomingTurn

# Minimal catalog (mirrors test_sandbox_service.MINIMAL_SIX).
_MINIMAL_SIX: dict[str, dict] = {
    "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
    "cercano": {
        "label": "VIP cercano",
        "description": "",
        "facts": {"name": "Mateo", "personality": "confiado"},
        "notes": [{"date": "2026-05-10", "text": "Le gusta el trato cercano"}],
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


def _turn(chat_id: int = 100) -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=chat_id, text="hola")


@pytest.mark.asyncio
async def test_inactive_returns_retrieved_unchanged() -> None:
    sandbox = SandboxService(profiles=_MINIMAL_SIX)
    aug = SandboxKnowledgeAugmenter(sandbox)
    retrieved: dict = {"knowledge.memory": None}
    out = await aug.augment_retrieved(_turn(100), retrieved)
    assert out is retrieved or out == retrieved
    assert "knowledge.profile" not in out


@pytest.mark.asyncio
async def test_active_cercano_injects_profile() -> None:
    sandbox = SandboxService(profiles=_MINIMAL_SIX)
    sandbox.activate(100, "cercano")
    aug = SandboxKnowledgeAugmenter(sandbox)
    retrieved: dict = {}
    out = await aug.augment_retrieved(_turn(100), retrieved)
    assert "knowledge.profile" in out
    block = out["knowledge.profile"]
    assert block["tipo"] == "sandbox_fixture"
    assert block["content"]["facts"]["name"] == "Mateo"
    # Original map not mutated when we copy
    assert "knowledge.profile" not in retrieved


@pytest.mark.asyncio
async def test_active_replaces_real_history_with_fixture() -> None:
    """Regression test for the real-history-leak bug found in production.

    Sandbox was active but knowledge.history still carried the tester's real
    chat — profile got faked, history didn't. This is the fix.
    """
    catalog = dict(_MINIMAL_SIX)
    catalog["intenso"] = {
        **catalog["intenso"],
        "history": [
            {"autor": "vip", "texto": "Terminé con mi novia hace poco"},
            {"autor": "dueña", "texto": "no te preocupes amor, aquí estoy"},
        ],
    }
    sandbox = SandboxService(profiles=catalog)
    sandbox.activate(100, "intenso")
    aug = SandboxKnowledgeAugmenter(sandbox)

    # Simulate a real HistoryRetriever result already sitting in `retrieved`
    # (this is the leak: real VIP messages from a genuine prior conversation).
    real_history = [
        {"autor": "vip", "texto": "Hola de una conversación REAL", "timestamp": "2026-07-01T00:00:00"},
    ]
    retrieved = {"knowledge.history": real_history}
    out = await aug.augment_retrieved(_turn(100), retrieved)

    assert out["knowledge.history"] != real_history
    assert out["knowledge.history"] == [
        {"autor": "vip", "texto": "Terminé con mi novia hace poco", "timestamp": ""},
        {"autor": "dueña", "texto": "no te preocupes amor, aquí estoy", "timestamp": ""},
    ]
    # Original map not mutated
    assert retrieved["knowledge.history"] == real_history


@pytest.mark.asyncio
async def test_active_does_not_add_history_when_not_requested() -> None:
    """Discipline: don't inject knowledge.history if the Planner never asked for it."""
    sandbox = SandboxService(profiles=_MINIMAL_SIX)
    sandbox.activate(100, "cercano")
    aug = SandboxKnowledgeAugmenter(sandbox)
    retrieved: dict = {}  # knowledge.history key absent = not requested
    out = await aug.augment_retrieved(_turn(100), retrieved)
    assert "knowledge.history" not in out


@pytest.mark.asyncio
async def test_active_nuevo_profile_yields_empty_history() -> None:
    sandbox = SandboxService(profiles=_MINIMAL_SIX)  # "nuevo" has no history key -> []
    sandbox.activate(100, "nuevo")
    aug = SandboxKnowledgeAugmenter(sandbox)
    retrieved = {"knowledge.history": [{"autor": "vip", "texto": "real leak", "timestamp": "x"}]}
    out = await aug.augment_retrieved(_turn(100), retrieved)
    assert out["knowledge.history"] == []


@pytest.mark.asyncio
async def test_active_but_missing_content_noop() -> None:
    """If get_profile_content returns None, leave retrieved alone."""
    class _Stub:
        def is_active(self, chat_id: int) -> bool:
            return True

        def get_profile_content(self, chat_id: int):
            return None

    aug = SandboxKnowledgeAugmenter(_Stub())  # type: ignore[arg-type]
    retrieved = {"knowledge.memory": {"x": 1}}
    out = await aug.augment_retrieved(_turn(1), retrieved)
    assert out == retrieved
    assert "knowledge.profile" not in out
