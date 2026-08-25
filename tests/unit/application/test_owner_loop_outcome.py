"""Owner-loop C1: doctrine escalate, Destacar/Reprender, gray-zone resolve."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from diana.application.admin_service import AdminService
from diana.application.gray_zone_service import GrayZoneService
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryTraceReaderWriter,
    InMemoryTurnStore,
    InMemoryVipStore,
)
from diana.application.ports import TurnOutcomeLogRecord
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import (
    AlwaysLiveTurnStatusReader,
    FakeTelegramActuator,
    FixedDelayPolicy,
    ImmediateClock,
)
from diana.cognitive.models import Decision, EvaluationProfile, IncomingTurn
from diana.cognitive.policy_distiller import PolicyDistiller
from diana.telegram.handlers.doctrine import (
    handle_doctrine_escalate,
)

from tests.unit.application.test_admin_service import _real_staging
from tests.unit.application.test_outcome_log_service import (
    FakeOutcomeStore,
    FakeTrustBudget,
    _fase_b_service,
    _trace,
)

OWNER_ID = 999001


def _eval() -> EvaluationProfile:
    return EvaluationProfile(
        naturalness=0.9,
        precision=0.9,
        doctrine=0.9,
        consistency=0.9,
        safety=0.95,
        coverage=0.9,
        empathy=0.9,
    )


def _decision(draft: str = "hola VIP") -> Decision:
    return Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text=draft,
    )


class _MemQueries:
    def __init__(self) -> None:
        self._by_id: dict = {}

    async def insert(
        self,
        vip_id,
        turn_id,
        question,
        draft,
        freeze_until=None,
        chat_id=None,
        business_connection_id=None,
    ):
        row = SimpleNamespace(
            id=uuid4(),
            vip_id=vip_id,
            turn_id=turn_id,
            question=question,
            draft=draft,
            status="open",
            freeze_until=freeze_until,
            chat_id=chat_id,
            business_connection_id=business_connection_id,
        )
        self._by_id[row.id] = row
        return row

    async def get_by_id(self, query_id):
        return self._by_id.get(query_id)

    async def get_open_by_turn_id(self, turn_id):
        for row in self._by_id.values():
            if row.turn_id == turn_id and row.status == "open":
                return row
        return None

    async def update_status(self, query_id, status, resolved_at=None):
        row = self._by_id.get(query_id)
        if row is None:
            return False
        row.status = status
        row.resolved_at = resolved_at
        return True


class _MemStaging:
    def __init__(self) -> None:
        self._by_id: dict = {}

    async def insert(self, candidate_type, payload, turn_id):
        row = SimpleNamespace(
            id=uuid4(),
            candidate_type=candidate_type,
            payload=payload,
            status="pending",
            turn_id=turn_id,
        )
        self._by_id[row.id] = row
        return row


def _memory_gray_zone(vip_store) -> GrayZoneService:
    return GrayZoneService(
        query_repo=_MemQueries(),
        vip_store=vip_store,
        staging_repo=_MemStaging(),
        distiller=PolicyDistiller(),
    )


def _admin_graph(*, outcome, staging=None, quality: bool = False) -> dict:
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
    from diana.application.approval_ui import ApprovalDraftVoider

    coordinator = TurnCoordinator(
        turns,
        approvals,
        behavior,  # type: ignore[arg-type]
        approval_ui=ApprovalDraftVoider(notifier),
    )
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,  # type: ignore[arg-type]
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER_ID,
        delivery_mode="supervised",
        vip_store=vips,  # type: ignore[arg-type]
        staging=staging,
        outcome=outcome,
        feature_quality_feedback_enabled=quality,
        feature_autonomy_readiness_enabled=True,
    )
    return {
        "admin": admin,
        "turns": turns,
        "approvals": approvals,
        "coordinator": coordinator,
        "actuator": actuator,
        "notifier": notifier,
        "vips": vips,
        "owner_id": OWNER_ID,
        "outcome": outcome,
    }


def _label_events(trust: FakeTrustBudget) -> list[tuple[str, str]]:
    return [(event, value) for _turn, event, value in trust.calls]


async def _seed_pending(g, *, draft: str, vip_id, outcome):
    turn = await g["coordinator"].begin_turn(
        chat_id=42, trigger_message_id=7, vip_id=vip_id
    )
    await g["admin"].send_draft_for_approval(
        IncomingTurn(
            turn_id=turn.id,
            chat_id=42,
            text="vip says hi",
            business_connection_id="bc-1",
            telegram_message_id=7,
            vip_id=vip_id,
        ),
        _decision(draft=draft),
        turn.id,
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    await outcome.record_shadow(turn.id, vip_id=vip_id, trace=_trace(draft=draft))
    return turn


async def _seed_gray_zone(g, gz, store, *, shadow: str, draft: str = "borrador zona"):
    vip = await g["vips"].add(10001, display_name="TestVIP")
    turn = await g["coordinator"].begin_turn(
        chat_id=42, trigger_message_id=7, vip_id=vip.id
    )
    await g["coordinator"].transition(turn.id, "gray_zone")
    await gz.create_query(
        vip_id=vip.id,
        turn_id=turn.id,
        question="hay descuento?",
        draft=draft,
        chat_id=42,
        business_connection_id="bc-1",
    )
    await store.insert(
        TurnOutcomeLogRecord(
            turn_id=turn.id, vip_id=vip.id, shadow_verdict=shadow
        )
    )
    return turn


@pytest.mark.asyncio
async def test_doctrine_escalate_writes_owner_outcome_escalated() -> None:
    store = FakeOutcomeStore()
    trust = FakeTrustBudget()
    outcome = _fase_b_service(store, trust)
    g = _admin_graph(outcome=outcome)
    gz = _memory_gray_zone(g["vips"])
    turn = await _seed_gray_zone(g, gz, store, shadow="doctrine")

    status = await handle_doctrine_escalate(
        gray_zone=gz,
        coordinator=g["coordinator"],
        turn_id=turn.id,
        admin=g["admin"],
        actor_id=OWNER_ID,
    )

    assert status == "escalated"
    rec = store.rows[str(turn.id)]
    assert rec.owner_outcome == "escalated"
    persisted = await g["turns"].get(turn.id)
    assert persisted is not None and persisted.status == "escalated"
    assert await gz.get_open_query_by_turn_id(turn.id) is None
    assert _label_events(trust) == []


@pytest.mark.asyncio
async def test_doctrine_escalate_send_shadow_is_desacuerdo() -> None:
    store = FakeOutcomeStore()
    trust = FakeTrustBudget()
    outcome = _fase_b_service(store, trust)
    g = _admin_graph(outcome=outcome)
    gz = _memory_gray_zone(g["vips"])
    turn = await _seed_gray_zone(g, gz, store, shadow="send")

    status = await handle_doctrine_escalate(
        gray_zone=gz,
        coordinator=g["coordinator"],
        turn_id=turn.id,
        admin=g["admin"],
        actor_id=OWNER_ID,
    )

    assert status == "escalated"
    events = _label_events(trust)
    assert ("label", "desacuerdo") in events
    assert ("label", "escalated") not in events
    assert store.rows[str(turn.id)].owner_outcome == "escalated"


@pytest.mark.asyncio
async def test_doctrine_escalate_discards_when_owner_notify_fails() -> None:
    """Telegram notify must not skip discard_and_close / VIP unfreeze."""
    store = FakeOutcomeStore()
    trust = FakeTrustBudget()
    outcome = _fase_b_service(store, trust)
    g = _admin_graph(outcome=outcome)
    gz = _memory_gray_zone(g["vips"])
    turn = await _seed_gray_zone(g, gz, store, shadow="doctrine")

    async def _boom(text: str, *, chat_id: int | None = None) -> None:
        raise RuntimeError("telegram notify failed")

    g["notifier"].notify_info = _boom  # type: ignore[method-assign]

    status = await handle_doctrine_escalate(
        gray_zone=gz,
        coordinator=g["coordinator"],
        turn_id=turn.id,
        admin=g["admin"],
        actor_id=OWNER_ID,
    )

    assert status == "escalated"
    assert await gz.get_open_query_by_turn_id(turn.id) is None
    vip = await g["vips"].get_by_id(turn.vip_id)
    assert vip is not None and vip.frozen_until is None
    assert store.rows[str(turn.id)].owner_outcome == "escalated"


@pytest.mark.asyncio
async def test_mark_gold_fires_acierto() -> None:
    store = FakeOutcomeStore()
    trust = FakeTrustBudget()
    outcome = _fase_b_service(store, trust)
    staging, _ = _real_staging()
    g = _admin_graph(outcome=outcome, staging=staging, quality=True)
    vip_id = uuid4()
    turn = await _seed_pending(g, draft="send me", vip_id=vip_id, outcome=outcome)

    result = await g["admin"].handle_mark_gold(
        turn.id, scope="global", actor_id=OWNER_ID
    )

    assert result is not None and result.success is True
    events = _label_events(trust)
    assert ("label", "acierto") in events
    assert ("label", "approved_as_is") not in events


@pytest.mark.asyncio
async def test_reprimand_new_correction_fires_desacuerdo() -> None:
    store = FakeOutcomeStore()
    trust = FakeTrustBudget()
    outcome = _fase_b_service(store, trust)
    staging, staging_repo = _real_staging()
    row = staging_repo.insert.return_value
    row.candidate_type = "example"
    row.status = "pending"
    row.payload = {
        "original_draft": "original draft",
        "corrected_text": "texto corregido",
        "context": {"turn_text": "vip says hi"},
        "channel_type": "vip",
    }
    staging_repo.get_by_id = AsyncMock(return_value=row)
    staging_repo.update_status = AsyncMock(return_value=True)
    g = _admin_graph(outcome=outcome, staging=staging, quality=True)
    vip_id = uuid4()
    turn = await _seed_pending(
        g, draft="original draft", vip_id=vip_id, outcome=outcome
    )

    result = await g["admin"].handle_reprimand(
        turn.id,
        "texto corregido",
        mode="counter_example",
        candidate_id=None,
        scope="global",
        actor_id=OWNER_ID,
    )

    assert result is not None and result.success is True
    events = _label_events(trust)
    assert ("label", "desacuerdo") in events
    assert g["actuator"].calls[-1]["text"] == "texto corregido"


@pytest.mark.asyncio
async def test_gray_zone_resolve_then_approve_is_conservadora() -> None:
    store = FakeOutcomeStore()
    trust = FakeTrustBudget()
    outcome = _fase_b_service(store, trust)
    g = _admin_graph(outcome=outcome)
    gz = _memory_gray_zone(g["vips"])
    turn = await _seed_gray_zone(g, gz, store, shadow="doctrine")

    status = await g["admin"].resolve_doctrine_rule_and_enqueue(
        turn_id=turn.id,
        rule_text="Ofrecer descuento 10% en 3+",
        scope="all",
        vip_id=None,
        gray_zone=gz,
        actor_id=OWNER_ID,
    )
    assert status == "resolved"
    # Query moves to awaiting_send (still held), not closed/open.
    open_q = await gz.get_open_query_by_turn_id(turn.id)
    assert open_q is None or getattr(open_q, "status", None) != "open"

    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)

    assert result is not None and result.success is True
    rec = store.rows[str(turn.id)]
    assert rec.owner_outcome == "approved_as_is"
    events = _label_events(trust)
    assert ("label", "conservadora") in events
    persisted = await g["turns"].get(turn.id)
    assert persisted is not None and persisted.status == "delivered"
