"""E2E: R-A supervised delivery from resolved/expired gray zone queries (real DB).

Covers the full post-resolution flow for both channels:
- VIP: gray zone turn + draft query → create_supervised_delivery_from_gray_zone
  → PENDING_APPROVAL with the draft → handle_approve → DELIVERED to the chat.
- atencion: same flow with vip_id=None (no VIP to unfreeze), delivery anchored
  to chat_id, business_connection_id taken from the persisted query.
- Expiry with draft → supervised PendingApproval (draft is delivered later).
- Expiry without draft → no approval (the job escalates instead).

Rows are deleted in ``finally`` so other tier2 tests are never polluted.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.admin_service import AdminService
from diana.application.approval_ui import ApprovalDraftVoider
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryTraceReaderWriter,
)
from diana.application.ports import TurnRecord
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import (
    FakeTelegramActuator,
    FixedDelayPolicy,
    ImmediateClock,
)
from diana.composition import TurnStoreStatusReader
from diana.infrastructure.db.repositories.approvals import SqlPendingApprovalStore
from diana.infrastructure.db.repositories.deliveries import SqlPendingDeliveryStore
from diana.infrastructure.db.repositories.gray_zone import GrayZoneQueryRepo
from diana.infrastructure.db.repositories.turns import SqlTurnStore
from diana.infrastructure.db.repositories.vips import SqlVipStore

OWNER_ID = 999001
_GRAY_CHAT = 977100
_GRAY_CHAT_ATENCION = 977101

_DELETE_QUERY = text("DELETE FROM gray_zone_queries WHERE turn_id = :turn_id")
_DELETE_APPROVAL = text("DELETE FROM pending_approvals WHERE turn_id = :turn_id")
_DELETE_DELIVERY = text("DELETE FROM pending_deliveries WHERE turn_id = :turn_id")
_DELETE_TURN = text("DELETE FROM turns WHERE id = :turn_id")
_DELETE_VIP = text("DELETE FROM vips WHERE id = :vip_id")


def _build_graph(sf):
    """Assemble AdminService + coordinator + stores over the real DB."""
    turns = SqlTurnStore(sf)
    approvals = SqlPendingApprovalStore(sf)
    deliveries = SqlPendingDeliveryStore(sf)
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    notifier = FakeOwnerNotifier()
    vips = SqlVipStore(sf)
    act = FakeTelegramActuator()
    behavior = BehaviorEngine(
        act,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
        turn_status=TurnStoreStatusReader(turns),
    )
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
        vip_store=vips,
    )
    return {
        "admin": admin,
        "turns": turns,
        "approvals": approvals,
        "coordinator": coordinator,
        "notifier": notifier,
        "actuator": act,
        "vips": vips,
        "gray_zone": GrayZoneQueryRepo(sf),
        "behavior": behavior,
    }


async def _cleanup(engine, turn_id, *, vip_id=None) -> None:
    async with engine.begin() as conn:
        await conn.execute(_DELETE_QUERY, {"turn_id": turn_id})
        await conn.execute(_DELETE_APPROVAL, {"turn_id": turn_id})
        await conn.execute(_DELETE_DELIVERY, {"turn_id": turn_id})
        await conn.execute(_DELETE_TURN, {"turn_id": turn_id})
        if vip_id is not None:
            await conn.execute(_DELETE_VIP, {"vip_id": vip_id})


@pytest.mark.db
@pytest.mark.asyncio
async def test_vip_gray_zone_supervised_delivery_full_flow(engine) -> None:
    """VIP: gray zone draft → supervised approval → owner approve → DELIVERED."""
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    g = _build_graph(sf)
    vip = await g["vips"].add(770011, display_name="GrayVip")
    turn = await g["turns"].create(
        TurnRecord(
            id=uuid4(),
            chat_id=_GRAY_CHAT,
            status="gray_zone",
            vip_id=vip.id,
            channel_type="vip",
            trigger_message_id=11,
        )
    )
    try:
        query = await g["gray_zone"].insert(
            vip_id=vip.id,
            turn_id=turn.id,
            question="Que oferta tengo?",
            draft="Te ofrecemos 10% en tu primera compra",
            business_connection_id="bc-vip-011",
        )
        result = await g["admin"].create_supervised_delivery_from_gray_zone(
            turn.id, query
        )
        assert result is True

        stored = await g["turns"].get(turn.id)
        assert stored is not None
        assert stored.status == "pending_approval"

        approval = await g["approvals"].get_by_turn(turn.id)
        assert approval is not None
        assert approval.status == "waiting"
        assert approval.draft_text == "Te ofrecemos 10% en tu primera compra"
        assert approval.business_connection_id == "bc-vip-011"
        assert approval.chat_id == _GRAY_CHAT

        dr = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
        assert dr is not None
        assert dr.success is True

        after = await g["turns"].get(turn.id)
        assert after is not None
        assert after.status == "delivered"

        sent = [c for c in g["actuator"].calls if c["op"] == "send_message"]
        assert sent, "engine never delivered the approved draft"
        assert sent[-1]["chat_id"] == _GRAY_CHAT
        assert sent[-1]["text"] == "Te ofrecemos 10% en tu primera compra"
    finally:
        await _cleanup(engine, turn.id, vip_id=vip.id)


@pytest.mark.db
@pytest.mark.asyncio
async def test_atencion_gray_zone_supervised_delivery_full_flow(engine) -> None:
    """atencion: vip_id=None flows to supervised approval and delivers to chat."""
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    g = _build_graph(sf)
    turn = await g["turns"].create(
        TurnRecord(
            id=uuid4(),
            chat_id=_GRAY_CHAT_ATENCION,
            status="gray_zone",
            vip_id=None,
            channel_type="atencion",
            trigger_message_id=12,
        )
    )
    try:
        query = await g["gray_zone"].insert(
            vip_id=None,
            turn_id=turn.id,
            question="Cuando abren?",
            draft="Abrimos de lunes a sabado de 9 a 19h",
            business_connection_id="bc-atencion-012",
            chat_id=_GRAY_CHAT_ATENCION,
        )
        result = await g["admin"].create_supervised_delivery_from_gray_zone(
            turn.id, query
        )
        assert result is True

        stored = await g["turns"].get(turn.id)
        assert stored is not None
        assert stored.status == "pending_approval"

        approval = await g["approvals"].get_by_turn(turn.id)
        assert approval is not None
        assert approval.vip_id is None
        assert approval.business_connection_id == "bc-atencion-012"
        assert approval.chat_id == _GRAY_CHAT_ATENCION

        dr = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
        assert dr is not None
        assert dr.success is True

        after = await g["turns"].get(turn.id)
        assert after is not None
        assert after.status == "delivered"

        sent = [c for c in g["actuator"].calls if c["op"] == "send_message"]
        assert sent, "engine never delivered the atencion draft"
        assert sent[-1]["chat_id"] == _GRAY_CHAT_ATENCION
        assert sent[-1]["text"] == "Abrimos de lunes a sabado de 9 a 19h"
    finally:
        await _cleanup(engine, turn.id)


@pytest.mark.db
@pytest.mark.asyncio
async def test_expired_query_with_draft_creates_pending_approval(engine) -> None:
    """Expiry with draft: supervised PendingApproval created, turn → pending."""
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    g = _build_graph(sf)
    turn = await g["turns"].create(
        TurnRecord(id=uuid4(), chat_id=_GRAY_CHAT, status="gray_zone")
    )
    try:
        query = await g["gray_zone"].insert(
            vip_id=None,
            turn_id=turn.id,
            question="Dudas",
            draft="Respuesta pendiente de revision",
            business_connection_id="bc-expiry-013",
        )
        await g["gray_zone"].update_status(query.id, "expired")

        result = await g["admin"].create_supervised_delivery_from_gray_zone(
            turn.id, query
        )
        assert result is True

        stored = await g["turns"].get(turn.id)
        assert stored is not None
        assert stored.status == "pending_approval"

        approval = await g["approvals"].get_by_turn(turn.id)
        assert approval is not None
        assert approval.status == "waiting"
        assert approval.draft_text == "Respuesta pendiente de revision"
    finally:
        await _cleanup(engine, turn.id)


@pytest.mark.db
@pytest.mark.asyncio
async def test_expired_query_without_draft_creates_no_approval(engine) -> None:
    """Expiry without draft: fail-soft — no approval, turn stays gray zone."""
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    g = _build_graph(sf)
    turn = await g["turns"].create(
        TurnRecord(id=uuid4(), chat_id=_GRAY_CHAT, status="gray_zone")
    )
    try:
        query = await g["gray_zone"].insert(
            vip_id=None,
            turn_id=turn.id,
            question="Sin respuesta",
            draft="",
            business_connection_id="bc-no-draft-014",
        )
        await g["gray_zone"].update_status(query.id, "expired")

        result = await g["admin"].create_supervised_delivery_from_gray_zone(
            turn.id, query
        )
        assert result is False
        # Nothing to deliver → the job escalates instead; no orphan approval.
        assert await g["approvals"].get_by_turn(turn.id) is None
        stored = await g["turns"].get(turn.id)
        assert stored is not None
        assert stored.status == "gray_zone"
    finally:
        await _cleanup(engine, turn.id)
