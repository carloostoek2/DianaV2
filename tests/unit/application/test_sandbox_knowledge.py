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
