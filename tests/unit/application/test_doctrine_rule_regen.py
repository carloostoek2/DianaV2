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
    policies_repo.find_active_by_source_query_id = AsyncMock(return_value=None)

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
    await service.deactivate_policy(policy_id)
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

    assert status == "resolved"
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
async def test_resolve_doctrine_terminal_turn_returns_stale() -> None:
    """Terminal turn guard: never persist a live policy / regen for a dead turn."""
    from diana.application.admin_service import AdminService

    gray_zone = AsyncMock()
    query = _fake_query()
    gray_zone.get_open_query_by_turn_id.return_value = query
    gray_zone.discard_and_close = AsyncMock(return_value=object())

    admin = object.__new__(AdminService)
    admin._director = AsyncMock()  # type: ignore[attr-defined]
    admin._gray_zone = gray_zone  # type: ignore[attr-defined]
    admin._notifier = AsyncMock()  # type: ignore[attr-defined]
    admin._turns = AsyncMock()  # type: ignore[attr-defined]
    admin._turns.get.return_value = SimpleNamespace(
        id=query.turn_id,
        chat_id=42,
        vip_id=None,
        trigger_message_id=7,
        channel_type="vip",
        status="superseded",
    )

    status = await AdminService.resolve_doctrine_rule_and_enqueue(
        admin,
        turn_id=query.turn_id,
        rule_text="regla",
        scope="all",
        vip_id=None,
        gray_zone=gray_zone,
    )

    assert status == "stale"
    gray_zone.persist_live_policy.assert_not_awaited()
    admin._director.handle_turn.assert_not_awaited()
    gray_zone.discard_and_close.assert_awaited_once()


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
async def test_regen_empty_draft_deactivates_policy() -> None:
    """Empty regenerated draft is fail-closed: deactivate policy, no approval."""
    from diana.application.admin_service import AdminService

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
        action="approve",
        reason="ok",
        evaluation=_profile(),
        draft_text="   ",
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

    assert status == "regen_failed"
    gray_zone.deactivate_policy.assert_awaited()
    admin.create_supervised_delivery_from_gray_zone.assert_not_awaited()
    gray_zone.mark_awaiting_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_approve_skips_vip_frozen_when_awaiting_send() -> None:
    """Frozen VIP + awaiting_send hold → approve delivers and unfreezes (not vip_frozen)."""
    from diana.application.admin_service import AdminService
    from diana.application.approval_ui import ApprovalDraftVoider
    from diana.application.memory import (
        FakeOwnerNotifier,
        InMemoryEscalationStore,
        InMemoryPendingApprovalStore,
        InMemoryPendingDeliveryStore,
        InMemoryTraceReaderWriter,
        InMemoryTurnStore,
    )
    from diana.application.turn_coordinator import TurnCoordinator
    from diana.behavior.engine import BehaviorEngine
    from diana.behavior.fake import (
        AlwaysLiveTurnStatusReader,
        FakeTelegramActuator,
        FixedDelayPolicy,
        ImmediateClock,
    )
    from tests.unit.application.test_owner_loop_outcome import _memory_gray_zone

    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    vips = InMemoryVipStore()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
        turn_status=AlwaysLiveTurnStatusReader(),
    )
    coordinator = TurnCoordinator(
        turns,
        approvals,
        behavior,  # type: ignore[arg-type]
        approval_ui=ApprovalDraftVoider(notifier),
    )
    regen_draft = "Claro, con 3 piezas te hago el 10%"
    director = AsyncMock()
    director.handle_turn.return_value = Decision(
        action="approve",
        reason="ok",
        evaluation=_profile(),
        draft_text=regen_draft,
    )
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,  # type: ignore[arg-type]
        traces=traces,
        turns=turns,
        owner_telegram_id=999001,
        delivery_mode="supervised",
        vip_store=vips,  # type: ignore[arg-type]
        director=director,
    )
    gz = _memory_gray_zone(vips)
    admin.set_gray_zone(gz)

    vip = await vips.add(42099, display_name="FrozenDoctrineVIP")
    turn = await coordinator.begin_turn(
        chat_id=42, trigger_message_id=7, vip_id=vip.id
    )
    await coordinator.transition(turn.id, "gray_zone")
    await gz.create_query(
        vip_id=vip.id,
        turn_id=turn.id,
        question="hay descuento por volumen?",
        draft="borrador original",
        chat_id=42,
        business_connection_id="bc-1",
    )
    frozen_before = await vips.get_by_id(vip.id)
    assert frozen_before is not None and frozen_before.frozen_until is not None

    status = await admin.resolve_doctrine_rule_and_enqueue(
        turn_id=turn.id,
        rule_text="Ofrecer 10% si piden 3 o más",
        scope="vip",
        vip_id=vip.id,
        gray_zone=gz,
        actor_id=999001,
    )
    assert status == "resolved"
    hold = await gz.get_awaiting_send_by_turn_id(turn.id)
    assert hold is not None
    still_frozen = await vips.get_by_id(vip.id)
    assert still_frozen is not None and still_frozen.frozen_until is not None

    result = await admin.handle_approve(turn.id, actor_id=999001)

    assert result is not None
    assert result.success is True
    assert result.error != "vip_frozen"
    assert actuator.send_count() >= 1
    after = await vips.get_by_id(vip.id)
    assert after is not None and after.frozen_until is None
    assert await gz.get_awaiting_send_by_turn_id(turn.id) is None
    persisted = await turns.get(turn.id)
    assert persisted is not None and persisted.status == "delivered"



def _stub_admin_for_resolve(*, director, gray_zone, query, create_side_effect=None, create_return=True):
    """Minimal AdminService shell for resolve_doctrine_rule_and_enqueue unit tests."""
    from diana.application.admin_service import AdminService

    admin = object.__new__(AdminService)
    admin._director = director
    admin._gray_zone = gray_zone
    admin._notifier = AsyncMock()
    admin._turns = AsyncMock()
    admin._turns.get.return_value = SimpleNamespace(
        id=query.turn_id,
        chat_id=42,
        vip_id=None,
        trigger_message_id=7,
        channel_type="vip",
        status="gray_zone",
    )
    admin._approvals = AsyncMock()
    admin._cancel_waiting_approval = AsyncMock()
    admin.handle_owner_escalate = AsyncMock(return_value=True)
    if create_side_effect is not None:
        admin.create_supervised_delivery_from_gray_zone = AsyncMock(
            side_effect=create_side_effect
        )
    else:
        admin.create_supervised_delivery_from_gray_zone = AsyncMock(
            return_value=create_return
        )
    gray_zone.policy_override_payload = lambda p: {
        "trigger_description": getattr(query, "question", "q"),
        "rule": getattr(p, "rule", "regla"),
        "scope": "all",
        "is_active": True,
    }
    return admin


def _policy_and_gz(query):
    gray_zone = AsyncMock()
    gray_zone.get_open_query_by_turn_id.return_value = query
    policy = SimpleNamespace(
        id=uuid4(),
        rule="regla viva",
        is_active=True,
        trigger_description=query.question,
        scope="all",
        vip_id=None,
        source_query_id=query.id,
    )
    gray_zone.persist_live_policy.return_value = policy
    gray_zone.deactivate_policy = AsyncMock()
    gray_zone.reopen_query = AsyncMock(return_value=True)
    gray_zone.mark_awaiting_send = AsyncMock()
    return gray_zone, policy


# --- Failure matrix (approval create / lock / mark / unexpected escalate) ---


@pytest.mark.asyncio
async def test_approval_create_fail_keeps_freeze_and_live_policy() -> None:
    """create_supervised False → error retryable; no escalate; policy stays live."""
    from diana.application.admin_service import AdminService

    query = _fake_query()
    gray_zone, policy = _policy_and_gz(query)
    director = AsyncMock()
    director.handle_turn.return_value = Decision(
        action="approve",
        reason="ok",
        evaluation=_profile(),
        draft_text="Borrador regenerado usable",
    )
    admin = _stub_admin_for_resolve(
        director=director, gray_zone=gray_zone, query=query, create_return=False
    )

    status = await AdminService.resolve_doctrine_rule_and_enqueue(
        admin,
        turn_id=query.turn_id,
        rule_text="regla viva",
        scope="all",
        vip_id=None,
        gray_zone=gray_zone,
        actor_id=999001,
    )

    assert status == "error"
    admin.handle_owner_escalate.assert_not_awaited()
    gray_zone.deactivate_policy.assert_not_awaited()
    gray_zone.mark_awaiting_send.assert_not_awaited()
    gray_zone.reopen_query.assert_awaited()
    admin._notifier.notify_info.assert_awaited()
    notify_text = admin._notifier.notify_info.await_args.args[0]
    assert "congelado" in notify_text.lower() or "reintenta" in notify_text.lower()


@pytest.mark.asyncio
async def test_approval_create_fail_without_actor_id_is_error_not_escalated() -> None:
    """actor_id=None must not return 'escalated' without escalating."""
    from diana.application.admin_service import AdminService

    query = _fake_query()
    gray_zone, _policy = _policy_and_gz(query)
    director = AsyncMock()
    director.handle_turn.return_value = Decision(
        action="approve",
        reason="ok",
        evaluation=_profile(),
        draft_text="Borrador regenerado usable",
    )
    admin = _stub_admin_for_resolve(
        director=director, gray_zone=gray_zone, query=query, create_return=False
    )

    status = await AdminService.resolve_doctrine_rule_and_enqueue(
        admin,
        turn_id=query.turn_id,
        rule_text="regla viva",
        scope="all",
        vip_id=None,
        gray_zone=gray_zone,
        actor_id=None,
    )

    assert status == "error"
    assert status != "escalated"
    admin.handle_owner_escalate.assert_not_awaited()
    gray_zone.deactivate_policy.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_lock_timeout_reopens_notifies_keeps_policy() -> None:
    """ChatLockTimeoutError → retryable error, reopen, notify, policy live."""
    from diana.application.admin_service import AdminService
    from diana.application.turn_coordinator import ChatLockTimeoutError

    query = _fake_query()
    gray_zone, _policy = _policy_and_gz(query)
    director = AsyncMock()
    director.handle_turn.return_value = Decision(
        action="approve",
        reason="ok",
        evaluation=_profile(),
        draft_text="Borrador regenerado usable",
    )
    admin = _stub_admin_for_resolve(
        director=director,
        gray_zone=gray_zone,
        query=query,
        create_side_effect=ChatLockTimeoutError("busy"),
    )

    status = await AdminService.resolve_doctrine_rule_and_enqueue(
        admin,
        turn_id=query.turn_id,
        rule_text="regla viva",
        scope="all",
        vip_id=None,
        gray_zone=gray_zone,
        actor_id=999001,
    )

    assert status == "error"
    gray_zone.reopen_query.assert_awaited()
    gray_zone.deactivate_policy.assert_not_awaited()
    gray_zone.mark_awaiting_send.assert_not_awaited()
    admin.handle_owner_escalate.assert_not_awaited()
    admin._notifier.notify_info.assert_awaited()
    notify_text = admin._notifier.notify_info.await_args.args[0]
    assert "reintenta" in notify_text.lower() or "congelado" in notify_text.lower()


@pytest.mark.asyncio
async def test_mark_awaiting_send_fail_cancels_approval_keeps_open() -> None:
    """mark_awaiting_send fail after create → cancel approval; restore GRAY_ZONE; policy live."""
    from diana.application.admin_service import AdminService
    from diana.cognitive.models import TurnStatus

    query = _fake_query()
    gray_zone, _policy = _policy_and_gz(query)
    gray_zone.mark_awaiting_send.side_effect = RuntimeError("db down")
    director = AsyncMock()
    director.handle_turn.return_value = Decision(
        action="approve",
        reason="ok",
        evaluation=_profile(),
        draft_text="Borrador regenerado usable",
    )
    admin = _stub_admin_for_resolve(
        director=director, gray_zone=gray_zone, query=query, create_return=True
    )
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _scope(*_a, **_k):
        yield

    admin._coordinator = AsyncMock()
    admin._coordinator.chat_scope = _scope
    admin._approvals.delete_for_turn = AsyncMock()

    status = await AdminService.resolve_doctrine_rule_and_enqueue(
        admin,
        turn_id=query.turn_id,
        rule_text="regla viva",
        scope="all",
        vip_id=None,
        gray_zone=gray_zone,
        actor_id=999001,
    )

    assert status == "error"
    admin._cancel_waiting_approval.assert_awaited_once_with(query.turn_id)
    admin._approvals.delete_for_turn.assert_awaited_once_with(query.turn_id)
    admin._coordinator.transition.assert_awaited()
    transition_args = admin._coordinator.transition.await_args
    assert transition_args.args[0] == query.turn_id
    assert transition_args.args[1] in {
        TurnStatus.GRAY_ZONE,
        "gray_zone",
        TurnStatus.GRAY_ZONE.value,
    }
    gray_zone.reopen_query.assert_awaited()
    gray_zone.deactivate_policy.assert_not_awaited()
    admin.handle_owner_escalate.assert_not_awaited()
    admin._notifier.notify_info.assert_awaited()



@pytest.mark.asyncio
async def test_retry_after_mark_awaiting_send_fail_reenqueues() -> None:
    """After mark-fail compensate, owner retry must create a new waiting approval.

    Turn returns to gray_zone, cancelled approval row is cleared, query stays
    open / freeze held, and a second resolve does not leave a stranded
    PENDING_APPROVAL with a non-recreatable cancelled unique row. Policy count
    stays at one (idempotent live persist by source_query_id).
    """
    from diana.application.admin_service import AdminService
    from diana.application.approval_ui import ApprovalDraftVoider
    from diana.application.memory import (
        FakeOwnerNotifier,
        InMemoryEscalationStore,
        InMemoryPendingApprovalStore,
        InMemoryPendingDeliveryStore,
        InMemoryTraceReaderWriter,
        InMemoryTurnStore,
    )
    from diana.application.turn_coordinator import TurnCoordinator
    from diana.behavior.engine import BehaviorEngine
    from diana.behavior.fake import (
        AlwaysLiveTurnStatusReader,
        FakeTelegramActuator,
        FixedDelayPolicy,
        ImmediateClock,
    )
    from tests.unit.application.test_owner_loop_outcome import _memory_gray_zone

    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    vips = InMemoryVipStore()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
        turn_status=AlwaysLiveTurnStatusReader(),
    )
    coordinator = TurnCoordinator(
        turns,
        approvals,
        behavior,  # type: ignore[arg-type]
        approval_ui=ApprovalDraftVoider(notifier),
    )
    director = AsyncMock()
    director.handle_turn.return_value = Decision(
        action="approve",
        reason="ok",
        evaluation=_profile(),
        draft_text="Borrador regenerado v1",
    )
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,  # type: ignore[arg-type]
        traces=traces,
        turns=turns,
        owner_telegram_id=999001,
        delivery_mode="supervised",
        vip_store=vips,  # type: ignore[arg-type]
        director=director,
    )
    gz = _memory_gray_zone(vips)
    admin.set_gray_zone(gz)

    vip = await vips.add(42101, display_name="MarkFailRetryVIP")
    turn = await coordinator.begin_turn(
        chat_id=42, trigger_message_id=7, vip_id=vip.id
    )
    await coordinator.transition(turn.id, "gray_zone")
    await gz.create_query(
        vip_id=vip.id,
        turn_id=turn.id,
        question="hay descuento?",
        draft="borrador original",
        chat_id=42,
        business_connection_id="bc-1",
    )

    # First resolve: create succeeds, mark_awaiting_send fails once.
    real_mark = gz.mark_awaiting_send
    calls = {"n": 0}

    async def mark_once_then_ok(query_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db down on mark")
        return await real_mark(query_id)

    gz.mark_awaiting_send = mark_once_then_ok  # type: ignore[method-assign]

    status1 = await admin.resolve_doctrine_rule_and_enqueue(
        turn_id=turn.id,
        rule_text="Ofrecer 10% en 3+",
        scope="vip",
        vip_id=vip.id,
        gray_zone=gz,
        actor_id=999001,
    )
    assert status1 == "error"
    persisted = await turns.get(turn.id)
    assert persisted is not None
    assert persisted.status == "gray_zone"
    assert await approvals.get_by_turn(turn.id) is None
    assert await gz.get_open_query_by_turn_id(turn.id) is not None
    frozen = await vips.get_by_id(vip.id)
    assert frozen is not None and frozen.frozen_until is not None
    assert len(gz._policies.inserts) == 1
    policy_id = gz._policies.inserts[0].id
    assert gz._policies.rows[policy_id].is_active is True

    # Retry: must enqueue waiting approval and mark awaiting_send.
    director.handle_turn.return_value = Decision(
        action="approve",
        reason="ok",
        evaluation=_profile(),
        draft_text="Borrador regenerado v2",
    )
    status2 = await admin.resolve_doctrine_rule_and_enqueue(
        turn_id=turn.id,
        rule_text="Ofrecer 10% en 3+",
        scope="vip",
        vip_id=vip.id,
        gray_zone=gz,
        actor_id=999001,
    )
    assert status2 == "resolved"
    approval = await approvals.get_by_turn(turn.id)
    assert approval is not None
    assert approval.status == "waiting"
    assert approval.draft_text == "Borrador regenerado v2"
    hold = await gz.get_awaiting_send_by_turn_id(turn.id)
    assert hold is not None
    # Idempotent policy: still one active live row for this query.
    assert len(gz._policies.inserts) == 1
    assert gz._policies.rows[policy_id].is_active is True
    after = await turns.get(turn.id)
    assert after is not None and after.status == "pending_approval"


@pytest.mark.asyncio
async def test_regen_action_escalate_is_fail_closed() -> None:
    """Unexpected Decision.action=escalate after inject → deactivate + regen_failed."""
    from diana.application.admin_service import AdminService

    query = _fake_query()
    gray_zone, _policy = _policy_and_gz(query)
    director = AsyncMock()
    director.handle_turn.return_value = Decision(
        action="escalate",
        reason="risk_high",
        evaluation=_profile(safety=0.2),
        draft_text="texto que no debe encolarse",
    )
    admin = _stub_admin_for_resolve(
        director=director, gray_zone=gray_zone, query=query
    )

    status = await AdminService.resolve_doctrine_rule_and_enqueue(
        admin,
        turn_id=query.turn_id,
        rule_text="regla",
        scope="all",
        vip_id=None,
        gray_zone=gray_zone,
        actor_id=999001,
    )

    assert status == "regen_failed"
    gray_zone.deactivate_policy.assert_awaited()
    admin.create_supervised_delivery_from_gray_zone.assert_not_awaited()
    gray_zone.mark_awaiting_send.assert_not_awaited()
    admin._notifier.notify_info.assert_awaited()


@pytest.mark.asyncio
async def test_owner_escalate_from_awaiting_send_keeps_live_policy() -> None:
    """Escalate from approval after awaiting_send: release freeze, keep policy."""
    from diana.application.admin_service import AdminService
    from diana.application.approval_ui import ApprovalDraftVoider
    from diana.application.memory import (
        FakeOwnerNotifier,
        InMemoryEscalationStore,
        InMemoryPendingApprovalStore,
        InMemoryPendingDeliveryStore,
        InMemoryTraceReaderWriter,
        InMemoryTurnStore,
    )
    from diana.application.turn_coordinator import TurnCoordinator
    from diana.behavior.engine import BehaviorEngine
    from diana.behavior.fake import (
        AlwaysLiveTurnStatusReader,
        FakeTelegramActuator,
        FixedDelayPolicy,
        ImmediateClock,
    )
    from tests.unit.application.test_owner_loop_outcome import _memory_gray_zone

    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    vips = InMemoryVipStore()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
        turn_status=AlwaysLiveTurnStatusReader(),
    )
    coordinator = TurnCoordinator(
        turns,
        approvals,
        behavior,  # type: ignore[arg-type]
        approval_ui=ApprovalDraftVoider(notifier),
    )
    director = AsyncMock()
    director.handle_turn.return_value = Decision(
        action="approve",
        reason="ok",
        evaluation=_profile(),
        draft_text="Borrador regenerado",
    )
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,  # type: ignore[arg-type]
        traces=traces,
        turns=turns,
        owner_telegram_id=999001,
        delivery_mode="supervised",
        vip_store=vips,  # type: ignore[arg-type]
        director=director,
    )
    gz = _memory_gray_zone(vips)
    admin.set_gray_zone(gz)

    vip = await vips.add(42100, display_name="EscalateHoldVIP")
    turn = await coordinator.begin_turn(
        chat_id=42, trigger_message_id=7, vip_id=vip.id
    )
    await coordinator.transition(turn.id, "gray_zone")
    await gz.create_query(
        vip_id=vip.id,
        turn_id=turn.id,
        question="pregunta",
        draft="borrador",
        chat_id=42,
        business_connection_id="bc-1",
    )
    status = await admin.resolve_doctrine_rule_and_enqueue(
        turn_id=turn.id,
        rule_text="Norma viva que debe conservarse",
        scope="vip",
        vip_id=vip.id,
        gray_zone=gz,
        actor_id=999001,
    )
    assert status == "resolved"
    assert await gz.get_awaiting_send_by_turn_id(turn.id) is not None
    policies = gz._policies
    assert len(policies.inserts) == 1
    policy_id = policies.inserts[0].id
    assert policies.rows[policy_id].is_active is True

    applied = await admin.handle_owner_escalate(turn.id, actor_id=999001)
    assert applied is True
    assert await gz.get_awaiting_send_by_turn_id(turn.id) is None
    after = await vips.get_by_id(vip.id)
    assert after is not None and after.frozen_until is None
    assert policies.rows[policy_id].is_active is True
