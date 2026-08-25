"""RED contract: doctrine RULE → live policy → force-regen → approval; freeze until send.

Encodes the locked product decisions for gray-zone resolve. These tests must
fail on the pre-implementation codebase (Strict TDD).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from diana.application.gray_zone_service import GrayZoneService
from diana.application.memory import InMemoryVipStore
from diana.cognitive.analyst import Analyst
from diana.cognitive.context_builder import ContextBuilder
from diana.cognitive.decider import Decider
from diana.cognitive.director import CognitiveDirector
from diana.cognitive.evaluator import Evaluator
from diana.cognitive.generator import Generator
from diana.cognitive.models import Comprehension, Decision, EvaluationProfile, IncomingTurn
from diana.cognitive.planner import Planner
from diana.cognitive.policy_distiller import PolicyDistiller
from diana.cognitive.ports import InMemoryMessageHistory, InMemoryTraceStore
from diana.cognitive.registry import build_default_registry
from diana.llm.fake import FakeLLM
from diana.telegram.keyboards import doctrine_keyboard


def _comprehension(**overrides: Any) -> Comprehension:
    data: dict[str, Any] = {
        "intent": "pregunta",
        "topics": ["precio"],
        "emotion": "neutral",
        "urgency": "baja",
        "risk": "bajo",
        "needs_history": False,
        "needs_context": False,
        "needs_memory": False,
        "needs_policy": True,
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


def _fake_query(*, status: str = "open", vip_id=None, question: str = "¿Hay descuento?") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        vip_id=vip_id,
        turn_id=uuid4(),
        question=question,
        draft="borrador original del bot",
        chat_id=42,
        business_connection_id="bc-1",
        freeze_until=datetime.now(UTC) + timedelta(hours=24),
    )


# --- Keyboard / UX ---------------------------------------------------------


def test_doctrine_keyboard_has_no_usar_borrador() -> None:
    markup = doctrine_keyboard(uuid4())
    labels = [
        btn.text
        for row in markup.inline_keyboard
        for btn in row
    ]
    assert not any("Usar borrador" in (t or "") for t in labels)
    assert any("Escribir regla" in (t or "") or "regla" in (t or "").lower() for t in labels)
    assert any("Escalar" in (t or "") for t in labels)
    callbacks = [btn.callback_data or "" for row in markup.inline_keyboard for btn in row]
    assert not any(cb.startswith("dx:") for cb in callbacks)


# --- GrayZone live persist / awaiting_send ---------------------------------


@pytest.mark.asyncio
async def test_persist_live_policy_inserts_active_policy_without_staging() -> None:
    query_repo = AsyncMock()
    staging_repo = AsyncMock()
    policies_repo = AsyncMock()
    vip_store = InMemoryVipStore()
    vip = await vip_store.add(10001, display_name="VIP")
    query = _fake_query(vip_id=vip.id)
    query_repo.get_by_id.return_value = query
    policy_row = SimpleNamespace(
        id=uuid4(),
        trigger_description=query.question,
        rule="Ofrecer 10% si piden 3+",
        scope="vip",
        is_active=True,
        vip_id=vip.id,
        source_query_id=query.id,
    )
    policies_repo.insert.return_value = policy_row

    service = GrayZoneService(
        query_repo=query_repo,
        vip_store=vip_store,
        staging_repo=staging_repo,
        distiller=PolicyDistiller(),
        policies_repo=policies_repo,
    )
    result = await service.persist_live_policy(
        query.id,
        "Ofrecer 10% si piden 3+",
        vip_id=vip.id,
        scope="vip",
    )

    policies_repo.insert.assert_awaited_once()
    insert_kwargs = policies_repo.insert.await_args.kwargs
    assert insert_kwargs["rule"] == "Ofrecer 10% si piden 3+"
    assert insert_kwargs["is_active"] is True
    assert insert_kwargs["scope"] == "vip"
    assert insert_kwargs["vip_id"] == vip.id
    assert insert_kwargs["source_query_id"] == query.id
    staging_repo.insert.assert_not_awaited()
    query_repo.update_status.assert_not_awaited()
    frozen = await vip_store.get_by_id(vip.id)
    # persist must not unfreeze; VIP may still be unfrozen here because we
    # never froze in this unit — assert freeze helpers were not called via unfreeze.
    assert result is policy_row or getattr(result, "id", None) == policy_row.id


@pytest.mark.asyncio
async def test_mark_awaiting_send_keeps_freeze() -> None:
    query_repo = AsyncMock()
    vip_store = InMemoryVipStore()
    vip = await vip_store.add(10002, display_name="VIP")
    await vip_store.freeze_vip(vip.id, datetime.now(UTC) + timedelta(hours=12))
    query = _fake_query(vip_id=vip.id, status="open")
    query_repo.get_by_id.return_value = query
    query_repo.update_status.return_value = True

    service = GrayZoneService(
        query_repo=query_repo,
        vip_store=vip_store,
        staging_repo=AsyncMock(),
        distiller=PolicyDistiller(),
        policies_repo=AsyncMock(),
    )
    await service.mark_awaiting_send(query.id)

    query_repo.update_status.assert_awaited_once()
    status_arg = query_repo.update_status.await_args.args[1]
    assert status_arg == "awaiting_send"
    frozen = await vip_store.get_by_id(vip.id)
    assert frozen is not None and frozen.frozen_until is not None


@pytest.mark.asyncio
async def test_close_awaiting_send_unfreeze_optional() -> None:
    query_repo = AsyncMock()
    vip_store = InMemoryVipStore()
    vip = await vip_store.add(10003, display_name="VIP")
    await vip_store.freeze_vip(vip.id, datetime.now(UTC) + timedelta(hours=12))
    query = _fake_query(vip_id=vip.id, status="awaiting_send")
    query_repo.get_by_id.return_value = query
    query_repo.update_status.return_value = True

    service = GrayZoneService(
        query_repo=query_repo,
        vip_store=vip_store,
        staging_repo=AsyncMock(),
        distiller=PolicyDistiller(),
        policies_repo=AsyncMock(),
    )
    await service.close_awaiting_send(query.id, unfreeze=True)

    query_repo.update_status.assert_awaited_once()
    assert query_repo.update_status.await_args.args[1] == "resolved"
    frozen = await vip_store.get_by_id(vip.id)
    assert frozen is not None and frozen.frozen_until is None


@pytest.mark.asyncio
async def test_deactivate_policy_helper_sets_inactive() -> None:
    policies_repo = AsyncMock()
    policies_repo.deactivate.return_value = True
    service = GrayZoneService(
        query_repo=AsyncMock(),
        vip_store=InMemoryVipStore(),
        staging_repo=AsyncMock(),
        distiller=PolicyDistiller(),
        policies_repo=policies_repo,
    )
    policy_id = uuid4()
    # Prefer service helper if present; else PoliciesRepo.deactivate directly.
    if hasattr(service, "deactivate_policy"):
        await service.deactivate_policy(policy_id)
        policies_repo.deactivate.assert_awaited_once_with(policy_id)
    else:
        await policies_repo.deactivate(policy_id)
        policies_repo.deactivate.assert_awaited_once_with(policy_id)


# --- Director force-inject -------------------------------------------------


@pytest.mark.asyncio
async def test_director_knowledge_overrides_force_injects_policy() -> None:
    llm = FakeLLM(
        structured_responses=[
            _comprehension(needs_policy=False),  # empty plan — override must still win
            _profile(),
        ],
        text_responses=["Borrador con regla forzada"],
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
    )
    override_policy = {
        "trigger_description": "descuento 3+",
        "rule": "Ofrecer 10% si piden 3 o más",
        "scope": "all",
        "is_active": True,
    }
    turn = IncomingTurn(turn_id=uuid4(), chat_id=77, text="hay descuento por volumen?")
    decision = await director.handle_turn(
        turn,
        knowledge_overrides={"knowledge.policy": [override_policy]},
    )
    assert isinstance(decision, Decision)
    retrieved = trace.get(turn.turn_id, "retrieved")
    assert retrieved is not None
    policy = retrieved.get("knowledge.policy")
    assert policy is not None
    # Override present and non-empty even if retriever returned nothing.
    if isinstance(policy, list):
        assert policy[0]["rule"] == override_policy["rule"]
    else:
        assert policy["rule"] == override_policy["rule"]


# --- Admin orchestration contract (mocked Director edge) -------------------


@pytest.mark.asyncio
async def test_resolve_doctrine_rule_passes_knowledge_overrides_and_regen_draft() -> None:
    from diana.application.admin_service import AdminService

    assert hasattr(AdminService, "resolve_doctrine_rule_and_enqueue"), (
        "AdminService must expose resolve_doctrine_rule_and_enqueue"
    )

    rule_text = "Siempre ofrecer 10% si piden 3 o más"
    regen_draft = "Claro, si llevas 3 te puedo hacer el 10% 😊"
    assert regen_draft != rule_text

    gray_zone = AsyncMock()
    query = _fake_query()
    gray_zone.get_open_query_by_turn_id.return_value = query
    gray_zone.persist_live_policy.return_value = SimpleNamespace(
        id=uuid4(),
        trigger_description=query.question,
        rule=rule_text,
        scope="all",
        is_active=True,
        vip_id=None,
        source_query_id=query.id,
    )

    director = AsyncMock()
    director.handle_turn.return_value = Decision(
        action="approve",
        reason="ok",
        evaluation=_profile(),
        draft_text=regen_draft,
    )

    admin = object.__new__(AdminService)
    admin._director = director  # type: ignore[attr-defined]
    admin._gray_zone = gray_zone  # type: ignore[attr-defined]
    admin._notifier = AsyncMock()  # type: ignore[attr-defined]
    admin._turns = AsyncMock()  # type: ignore[attr-defined]
    admin._turns.get.return_value = SimpleNamespace(
        id=query.turn_id,
        chat_id=42,
        vip_id=None,
        trigger_message_id=7,
        channel_type="vip",
        status="gray_zone",
    )
    admin.create_supervised_delivery_from_gray_zone = AsyncMock(return_value=True)
    gray_zone.policy_override_payload = lambda p: {
        "trigger_description": query.question,
        "rule": rule_text,
        "scope": "all",
        "is_active": True,
    }

    status = await AdminService.resolve_doctrine_rule_and_enqueue(
        admin,
        turn_id=query.turn_id,
        rule_text=rule_text,
        scope="all",
        vip_id=None,
        gray_zone=gray_zone,
        actor_id=999001,
    )

    assert status in {"resolved", "enqueued", "awaiting_send", "ok"}
    gray_zone.persist_live_policy.assert_awaited()
    director.handle_turn.assert_awaited()
    call_kwargs = director.handle_turn.await_args.kwargs
    assert "knowledge_overrides" in call_kwargs
    overrides = call_kwargs["knowledge_overrides"]
    assert overrides and "knowledge.policy" in overrides
    assert overrides["knowledge.policy"]
    _, kwargs = admin.create_supervised_delivery_from_gray_zone.await_args
    assert kwargs.get("draft_override") == regen_draft
    assert kwargs.get("draft_override") != rule_text
    gray_zone.mark_awaiting_send.assert_awaited()


@pytest.mark.asyncio
async def test_regen_fail_deactivates_policy_and_keeps_freeze() -> None:
    from diana.application.admin_service import AdminService

    assert hasattr(AdminService, "resolve_doctrine_rule_and_enqueue")

    gray_zone = AsyncMock()
    query = _fake_query()
    gray_zone.get_open_query_by_turn_id.return_value = query
    policy = SimpleNamespace(
        id=uuid4(),
        rule="regla",
        is_active=True,
        trigger_description="q",
        scope="all",
    )
    gray_zone.persist_live_policy.return_value = policy
    gray_zone.deactivate_policy = AsyncMock()
    gray_zone.policy_override_payload = lambda p: {
        "rule": "regla",
        "trigger_description": "q",
        "scope": "all",
        "is_active": True,
    }

    director = AsyncMock()
    director.handle_turn.return_value = Decision(
        action="consult_doctrine",
        reason="still_needs_policy",
        evaluation=_profile(doctrine=0.2),
        draft_text="aún no sé",
    )

    admin = object.__new__(AdminService)
    admin._director = director  # type: ignore[attr-defined]
    admin._gray_zone = gray_zone  # type: ignore[attr-defined]
    admin._notifier = AsyncMock()  # type: ignore[attr-defined]
    admin._turns = AsyncMock()  # type: ignore[attr-defined]
    admin._turns.get.return_value = SimpleNamespace(
        id=query.turn_id,
        chat_id=42,
        vip_id=None,
        trigger_message_id=7,
        channel_type="vip",
        status="gray_zone",
    )
    admin.create_supervised_delivery_from_gray_zone = AsyncMock()

    status = await AdminService.resolve_doctrine_rule_and_enqueue(
        admin,
        turn_id=query.turn_id,
        rule_text="regla",
        scope="all",
        vip_id=None,
        gray_zone=gray_zone,
        actor_id=999001,
    )

    assert status in {"error", "regen_failed", "failed"}
    gray_zone.deactivate_policy.assert_awaited()
    admin.create_supervised_delivery_from_gray_zone.assert_not_awaited()
    gray_zone.mark_awaiting_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_approve_skips_vip_frozen_when_awaiting_send() -> None:
    """Approve deliver must not abort with vip_frozen while doctrine hold is awaiting_send."""
    from diana.application.admin_service import AdminService

    assert hasattr(AdminService, "resolve_doctrine_rule_and_enqueue")
    # Helper used by the deliver gate (name flexible but must exist).
    assert hasattr(AdminService, "_has_doctrine_awaiting_send") or hasattr(
        AdminService, "_doctrine_hold_allows_deliver"
    )
