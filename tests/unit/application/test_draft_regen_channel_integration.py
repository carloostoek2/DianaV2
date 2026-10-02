"""Draft regenerate → real CognitiveDirector: persona follows the turn channel.

Integration counterpart of the ``-k channel`` tests in ``test_draft_variants.py``
(which stop at a ``FakeDirector`` boundary). Here the real ``DraftVariantService``
drives the real ``CognitiveDirector`` (only the LLM and the persona catalog are
doubles), so the assertion is on the actual prompt the Generator received and on
the persisted approval state.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

import pytest

from diana.application.draft_variants import (
    DraftVariantService,
    ensure_versions,
    read_versions,
)
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryPendingApprovalStore,
    InMemoryTurnStore,
)
from diana.application.ports import ApprovalRecord, TurnRecord
from diana.cognitive.analyst import Analyst
from diana.cognitive.context_builder import ContextBuilder
from diana.cognitive.decider import Decider
from diana.cognitive.director import CognitiveDirector
from diana.cognitive.evaluator import Evaluator
from diana.cognitive.generator import Generator
from diana.cognitive.models import Comprehension, EvaluationProfile
from diana.cognitive.planner import Planner
from diana.cognitive.ports import InMemoryMessageHistory, InMemoryTraceStore
from diana.cognitive.registry import build_default_registry
from diana.llm.fake import FakeLLM

OWNER = 99
VIP_PERSONA = "Persona VIP de Diana"
ATN_PERSONA = "Persona de Atención general"


class _ChannelPersonaProvider:
    """Persona catalog double keyed by channel (stands in for the DB catalog)."""

    def __init__(self) -> None:
        self.requested_channels: list[str] = []
        self._catalogs: dict[str, dict[str, Any]] = {
            "vip": {
                "voz_configurada": {
                    "persona": VIP_PERSONA,
                    "reglas_estilo": ["regla vip"],
                }
            },
            "atencion": {
                "voz_configurada": {
                    "persona": ATN_PERSONA,
                    "reglas_estilo": ["regla atencion"],
                }
            },
        }

    async def get_catalog(self, channel_type: str = "vip") -> dict[str, Any]:
        self.requested_channels.append(channel_type)
        return self._catalogs[channel_type]


def _comprehension() -> Comprehension:
    return Comprehension(
        intent="chat",
        topics=["general"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_history=False,
        needs_context=True,
        needs_memory=False,
        needs_policy=False,
        needs_examples=False,
        needs_schedule=False,
    )


def _profile() -> EvaluationProfile:
    return EvaluationProfile(
        naturalness=0.9,
        precision=0.9,
        doctrine=0.9,
        consistency=0.9,
        safety=0.95,
        coverage=0.9,
        empathy=0.9,
    )


def _real_director(
    draft: str,
) -> tuple[CognitiveDirector, InMemoryTraceStore, _ChannelPersonaProvider]:
    llm = FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=[draft],
    )
    history = InMemoryMessageHistory()
    trace = InMemoryTraceStore()
    provider = _ChannelPersonaProvider()
    director = CognitiveDirector(
        analyst=Analyst(llm),
        planner=Planner(),
        registry=build_default_registry(history),
        context_builder=ContextBuilder(),
        generator=Generator(llm),
        evaluator=Evaluator(llm),
        decider=Decider(),
        trace=trace,
        persona="Boot persona",
        history=history,
        persona_catalog_provider=provider,
    )
    return director, trace, provider


async def _seed(channel_type: Literal["vip", "atencion"]) -> tuple:
    approvals = InMemoryPendingApprovalStore()
    turns = InMemoryTurnStore()
    turn_id = uuid4()
    await turns.create(
        TurnRecord(
            id=turn_id,
            chat_id=1,
            status="pending_approval",
            channel_type=channel_type,
            trigger_message_id=10,
        )
    )
    await approvals.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=turn_id,
            chat_id=1,
            business_connection_id="bc",
            draft_text="primera",
            evaluation=ensure_versions(
                {"naturalness": 0.8},
                draft_text="primera",
                reason="ok",
                vip_text="hola, ¿cuánto cuesta?",
            ),
            owner_message_id=501,
            trigger_message_id=10,
        )
    )
    return approvals, turns, turn_id


@pytest.mark.asyncio
async def test_regenerate_atencion_channel_reaches_real_director_persona() -> None:
    approvals, turns, turn_id = await _seed("atencion")
    director, trace, provider = _real_director("borrador de atención")
    svc = DraftVariantService(
        approvals=approvals,
        turns=turns,
        director=director,
        notifier=FakeOwnerNotifier(),
        owner_telegram_id=OWNER,
    )

    r = await svc.regenerate(turn_id, actor_id=OWNER)

    assert r.ok and r.token == "regen_ok"
    # Every catalog read during the regen is scoped to Atención (no VIP leak).
    assert provider.requested_channels
    assert set(provider.requested_channels) == {"atencion"}
    prompt = trace.get(turn_id, "prompt_text")
    assert ATN_PERSONA in prompt
    assert "regla atencion" in prompt
    assert VIP_PERSONA not in prompt
    assert "regla vip" not in prompt
    # Persisted state: new variant appended and selected; turn back in queue.
    stored = await approvals.get_by_turn(turn_id)
    assert stored is not None and stored.status == "waiting"
    assert stored.draft_text == "borrador de atención"
    v = read_versions(stored.evaluation)
    assert [i["text"] for i in v["items"]] == ["primera", "borrador de atención"]
    assert v["selected"] == 1 and v["regenerating"] is False
    turn = await turns.get(turn_id)
    assert turn is not None and turn.status == "pending_approval"
    assert turn.channel_type == "atencion"


@pytest.mark.asyncio
async def test_regenerate_vip_channel_reaches_real_director_vip_persona() -> None:
    approvals, turns, turn_id = await _seed("vip")
    director, trace, provider = _real_director("borrador vip")
    svc = DraftVariantService(
        approvals=approvals,
        turns=turns,
        director=director,
        notifier=FakeOwnerNotifier(),
        owner_telegram_id=OWNER,
    )

    r = await svc.regenerate(turn_id, actor_id=OWNER)

    assert r.ok and r.token == "regen_ok"
    assert provider.requested_channels
    assert set(provider.requested_channels) == {"vip"}
    prompt = trace.get(turn_id, "prompt_text")
    assert VIP_PERSONA in prompt
    assert ATN_PERSONA not in prompt
    stored = await approvals.get_by_turn(turn_id)
    assert stored is not None and stored.draft_text == "borrador vip"


@pytest.mark.asyncio
async def test_regen_hint_on_atencion_reaches_real_director_with_hint() -> None:
    approvals, turns, turn_id = await _seed("atencion")
    director, trace, provider = _real_director("atención con contexto")
    svc = DraftVariantService(
        approvals=approvals,
        turns=turns,
        director=director,
        notifier=FakeOwnerNotifier(),
        owner_telegram_id=OWNER,
    )

    r = await svc.persist_regen_hint_and_regenerate(
        turn_id, "responde como servicio al cliente", actor_id=OWNER
    )

    assert r.ok and r.token == "regen_ok"
    assert set(provider.requested_channels) == {"atencion"}
    prompt = trace.get(turn_id, "prompt_text")
    assert ATN_PERSONA in prompt
    assert VIP_PERSONA not in prompt
    assert "responde como servicio al cliente" in prompt
    stored = await approvals.get_by_turn(turn_id)
    assert stored is not None and stored.draft_text == "atención con contexto"
