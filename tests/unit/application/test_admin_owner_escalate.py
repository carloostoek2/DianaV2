"""AdminService.handle_owner_escalate — cancel approval, no deliver."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from diana.application.admin_service import AdminService, OwnerAuthError
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
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.cognitive.models import (
    Decision,
    EvaluationProfile,
    IncomingTurn,
    is_turn_status_terminal,
)

OWNER_ID = 999001
OTHER_USER = 111


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


def _decision(draft: str = "hola") -> Decision:
    return Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text=draft,
    )


class _PersistThenRaiseStore(InMemoryTurnStore):
    """R4 fault injection: persists a terminal transition, then raises.

    Mirrors a store that commits the row then loses the connection — the turn
    is already terminal (the read-back gate in the post-turn hook sees
    ESCALATED / DELIVERED / FAILED), but the transition call raised, so the
    happy-path hook site would be skipped without the R4 fix.
    """

    def __init__(self) -> None:
        super().__init__()
        self.arm: bool = False
        self._disarmed: bool = False

    async def transition(
        self,
        turn_id,
        status,
        *,
        superseded_by=None,
        error=None,
    ):
        result = await super().transition(
            turn_id,
            status,
            superseded_by=superseded_by,
            error=error,
        )
        if self.arm and not self._disarmed and is_turn_status_terminal(result.status):
            self._disarmed = True
            raise RuntimeError("simulated persist-then-raise")
        return result


def _build_admin_graph(
    *, turns: InMemoryTurnStore | None = None, gray_zone: object | None = None
) -> dict:
    turns = turns or InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER_ID,
        gray_zone=gray_zone,
    )
    return {
        "admin": admin,
        "turns": turns,
        "approvals": approvals,
        "coordinator": coordinator,
        "notifier": notifier,
        "actuator": actuator,
        "owner_id": OWNER_ID,
    }


@pytest.fixture
def admin_graph() -> dict:
    return _build_admin_graph()


def _incoming(turn_id, **kw) -> IncomingTurn:
    data = {
        "turn_id": turn_id,
        "chat_id": 42,
        "text": "vip",
        "business_connection_id": "bc-1",
        "telegram_message_id": 7,
    }
    data.update(kw)
    return IncomingTurn(**data)


@pytest.mark.asyncio
async def test_owner_escalate_cancels_waiting_and_escalates_turn(
    admin_graph: dict,
) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="draft"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    applied = await g["admin"].handle_owner_escalate(turn.id, actor_id=OWNER_ID)
    assert applied is True
    appr = await g["approvals"].get_by_turn(turn.id)
    assert appr is not None
    assert appr.status == "cancelled"
    stored = await g["turns"].get(turn.id)
    assert stored is not None and stored.status == "escalated"
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_owner_escalate_non_owner_raises(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    with pytest.raises(OwnerAuthError):
        await g["admin"].handle_owner_escalate(turn.id, actor_id=OTHER_USER)
    with pytest.raises(OwnerAuthError):
        await g["admin"].handle_owner_escalate(turn.id, actor_id=None)
    assert g["actuator"].send_count() == 0
    appr = await g["approvals"].get_by_turn(turn.id)
    assert appr is not None and appr.status == "waiting"


@pytest.mark.asyncio
async def test_owner_escalate_terminal_is_noop(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    await g["coordinator"].transition(turn.id, "escalated")
    applied = await g["admin"].handle_owner_escalate(turn.id, actor_id=OWNER_ID)
    assert applied is False
    stored = await g["turns"].get(turn.id)
    assert stored is not None and stored.status == "escalated"
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_owner_escalate_runs_post_turn_hook_once(admin_graph: dict) -> None:
    """REQ-MEM-07 (R3): owner escalate ends the turn in ESCALATED — a terminal,
    extractable outcome — so the post-turn hook runs ONCE (best-effort, outside
    the chat lock), mirroring the autonomous path."""
    from unittest.mock import AsyncMock

    g = admin_graph
    hook = AsyncMock()
    g["admin"].set_post_turn_hook(hook)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="draft"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    applied = await g["admin"].handle_owner_escalate(turn.id, actor_id=OWNER_ID)
    assert applied is True
    stored = await g["turns"].get(turn.id)
    assert stored is not None and stored.status == "escalated"
    assert hook.await_count == 1
    called_args = hook.await_args.args
    assert called_args[0] == turn.id
    assert called_args[1] == 42


@pytest.mark.asyncio
async def test_owner_escalate_terminal_noop_skips_hook(admin_graph: dict) -> None:
    """R3 exactly-once: escalating an ALREADY-escalated turn is a no-op — the
    hook does NOT fire again (the path that escalated the turn owns the hook)."""
    from unittest.mock import AsyncMock

    g = admin_graph
    hook = AsyncMock()
    g["admin"].set_post_turn_hook(hook)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["coordinator"].transition(turn.id, "escalated")
    applied = await g["admin"].handle_owner_escalate(turn.id, actor_id=OWNER_ID)
    assert applied is False
    assert hook.await_count == 0


@pytest.mark.asyncio
async def test_owner_escalate_terminal_noop_discards_doctrine_hold() -> None:
    """Terminal no-op on a superseded turn closes a residual doctrine hold."""
    from unittest.mock import AsyncMock

    class GZ:
        def __init__(self) -> None:
            self.discarded: list = []
            self._holds: dict = {}

        def add_hold(self, turn_id) -> SimpleNamespace:
            query = SimpleNamespace(id=uuid4())
            self._holds[turn_id] = query
            return query

        async def get_hold_query_by_turn_id(self, turn_id):
            return self._holds.get(turn_id)

        async def discard_and_close(self, query_id):
            self.discarded.append(query_id)

    gz = GZ()
    g = _build_admin_graph(gray_zone=gz)
    hook = AsyncMock()
    g["admin"].set_post_turn_hook(hook)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["coordinator"].transition(turn.id, "superseded")
    query = gz.add_hold(turn.id)

    applied = await g["admin"].handle_owner_escalate(turn.id, actor_id=OWNER_ID)
    assert applied is False
    assert hook.await_count == 0
    assert gz.discarded == [query.id]


@pytest.mark.asyncio
async def test_owner_escalate_persist_then_raise_still_fires_hook() -> None:
    """R4: an ESCALATED transition inside ``handle_owner_escalate`` that persists
    then raises must still fire the post-turn hook — the ``finally`` keyed on
    ``escalated_here`` fires it OUTSIDE the chat lock (read-back gated), and the
    ESCALATED turn is extracted exactly once."""
    from unittest.mock import AsyncMock

    turns = _PersistThenRaiseStore()
    turns.arm = True
    g = _build_admin_graph(turns=turns)
    hook = AsyncMock()
    g["admin"].set_post_turn_hook(hook)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="draft"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    with pytest.raises(RuntimeError, match="simulated persist-then-raise"):
        await g["admin"].handle_owner_escalate(turn.id, actor_id=OWNER_ID)
    stored = await turns.get(turn.id)
    assert stored is not None and stored.status == "escalated"
    assert hook.await_count == 1
    called_args = hook.await_args.args
    assert called_args[0] == turn.id
    assert called_args[1] == 42
