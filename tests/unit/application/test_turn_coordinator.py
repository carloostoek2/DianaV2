"""TurnCoordinator: G.3 coordinate matrix + one non-terminal turn per chat."""

from __future__ import annotations

import asyncio
import time
from uuid import UUID, uuid4

import pytest

from diana.application.memory import (
    InMemoryPendingApprovalStore,
    InMemoryTurnStore,
)
from diana.application.ports import ApprovalRecord, TurnRecord
from diana.application.turn_coordinator import (
    ChatLockTimeoutError,
    CoordinateResult,
    TurnCoordinator,
)
from diana.cognitive.models import TurnStatus


class FakeCanceller:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    async def cancel_pending(self, chat_id: int, reason: str = "new_message") -> None:
        self.calls.append((chat_id, reason))


@pytest.fixture
def coordinator() -> tuple[
    TurnCoordinator, InMemoryTurnStore, InMemoryPendingApprovalStore, FakeCanceller
]:
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    canceller = FakeCanceller()
    coord = TurnCoordinator(turns, approvals, canceller)
    return coord, turns, approvals, canceller


@pytest.mark.asyncio
async def test_first_begin_turn_waiting_delay_single_non_terminal(
    coordinator: tuple,
) -> None:
    coord, turns, _, _ = coordinator
    rec = await coord.begin_turn(chat_id=100, trigger_message_id=1)
    assert rec.status == TurnStatus.WAITING_DELAY.value
    assert rec.chat_id == 100
    non_term = await turns.list_non_terminal(100)
    assert len(non_term) == 1
    assert non_term[0].id == rec.id


@pytest.mark.asyncio
async def test_supersede_chat_cascades_cancel(
    coordinator: tuple,
) -> None:
    """Public supersede_chat marks turns superseded and cancels approvals."""
    coord, turns, approvals, canceller = coordinator
    first = await coord.begin_turn(chat_id=50)
    await approvals.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=first.id,
            chat_id=50,
            business_connection_id="bc",
            draft_text="draft",
            status="waiting",
        )
    )
    async with coord.chat_scope(50):
        prior = await coord.supersede_chat(
            50, reason="owner_message", superseded_by=None
        )
    assert len(prior) == 1
    assert prior[0].id == first.id
    old = await turns.get(first.id)
    assert old is not None
    assert old.status == TurnStatus.SUPERSEDED.value
    appr = await approvals.get_by_turn(first.id)
    assert appr is not None
    assert appr.status == "cancelled"
    assert canceller.calls == [(50, "owner_message")]


@pytest.mark.asyncio
async def test_second_begin_turn_supersedes_previous(
    coordinator: tuple,
) -> None:
    coord, turns, _, _ = coordinator
    first = await coord.begin_turn(chat_id=100)
    second = await coord.begin_turn(chat_id=100)
    assert second.id != first.id
    old = await turns.get(first.id)
    assert old is not None
    assert old.status == TurnStatus.SUPERSEDED.value
    assert old.superseded_by == second.id
    assert second.status == TurnStatus.WAITING_DELAY.value
    non_term = await turns.list_non_terminal(100)
    assert len(non_term) == 1
    assert non_term[0].id == second.id


@pytest.mark.asyncio
async def test_supersede_calls_cancel_pending_once(
    coordinator: tuple,
) -> None:
    coord, _, _, canceller = coordinator
    await coord.begin_turn(chat_id=5)
    await coord.begin_turn(chat_id=5)
    assert canceller.calls == [(5, "new_message")]


@pytest.mark.asyncio
async def test_supersede_cancels_waiting_approvals(
    coordinator: tuple,
) -> None:
    coord, _, approvals, _ = coordinator
    first = await coord.begin_turn(chat_id=8)
    await approvals.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=first.id,
            chat_id=8,
            business_connection_id="bc",
            draft_text="draft",
            status="waiting",
        )
    )
    await coord.begin_turn(chat_id=8)
    appr = await approvals.get_by_turn(first.id)
    assert appr is not None
    assert appr.status == "cancelled"


@pytest.mark.asyncio
async def test_concurrent_begin_turn_one_non_terminal(
    coordinator: tuple,
) -> None:
    coord, turns, _, _ = coordinator
    results = await asyncio.gather(
        coord.begin_turn(chat_id=77),
        coord.begin_turn(chat_id=77),
        coord.begin_turn(chat_id=77),
    )
    assert len({r.id for r in results}) == 3
    non_term = await turns.list_non_terminal(77)
    assert len(non_term) == 1


@pytest.mark.asyncio
async def test_transition_terminal_and_pending(
    coordinator: tuple,
) -> None:
    coord, turns, _, _ = coordinator
    rec = await coord.begin_turn(chat_id=1)
    await coord.transition(rec.id, TurnStatus.PENDING_APPROVAL)
    assert (await turns.get(rec.id)).status == "pending_approval"
    await coord.transition(rec.id, TurnStatus.DELIVERED)
    assert (await turns.get(rec.id)).status == "delivered"
    rec2 = await coord.begin_turn(chat_id=2)
    await coord.transition(rec2.id, "escalated")
    assert (await turns.get(rec2.id)).status == "escalated"
    rec3 = await coord.begin_turn(chat_id=3)
    await coord.mark_failed(rec3.id, error="boom")
    failed = await turns.get(rec3.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "boom"


@pytest.mark.asyncio
async def test_transition_sink_for_director(
    coordinator: tuple,
) -> None:
    coord, turns, _, _ = coordinator
    rec = await coord.begin_turn(chat_id=1)
    await coord.transition_sink(rec.id, TurnStatus.ANALYZING)
    assert (await turns.get(rec.id)).status == "analyzing"


@pytest.mark.asyncio
async def test_begin_turn_accepts_explicit_turn_id(
    coordinator: tuple,
) -> None:
    coord, _, _, _ = coordinator
    tid = uuid4()
    rec = await coord.begin_turn(chat_id=1, turn_id=tid, vip_id=uuid4())
    assert rec.id == tid
    assert isinstance(rec.id, UUID)
    assert rec.vip_id is not None


# --- Anexo G.3 coordinate matrix ---


@pytest.mark.asyncio
async def test_coordinate_vip_idle_creates(coordinator: tuple) -> None:
    coord, turns, _, _ = coordinator
    result = await coord.coordinate(chat_id=200, autor="vip", trigger_message_id=9)
    assert isinstance(result, CoordinateResult)
    assert result.action == "create"
    assert result.turn_id is not None
    non_term = await turns.list_non_terminal(200)
    assert len(non_term) == 1
    assert non_term[0].id == result.turn_id
    assert non_term[0].status == TurnStatus.WAITING_DELAY.value


@pytest.mark.asyncio
async def test_coordinate_vip_nonterminal_replaces(coordinator: tuple) -> None:
    coord, turns, _, _ = coordinator
    first = await coord.coordinate(chat_id=201, autor="vip")
    assert first.action == "create"
    second = await coord.coordinate(chat_id=201, autor="vip")
    assert second.action == "replace"
    assert second.turn_id is not None
    assert second.turn_id != first.turn_id
    old = await turns.get(first.turn_id)  # type: ignore[arg-type]
    assert old is not None
    assert old.status == TurnStatus.SUPERSEDED.value
    assert old.superseded_by == second.turn_id
    non_term = await turns.list_non_terminal(201)
    assert len(non_term) == 1
    assert non_term[0].id == second.turn_id


@pytest.mark.asyncio
async def test_coordinate_owner_nonterminal_discards(coordinator: tuple) -> None:
    coord, turns, _, _ = coordinator
    created = await coord.coordinate(chat_id=202, autor="vip")
    assert created.turn_id is not None
    result = await coord.coordinate(chat_id=202, autor="owner")
    assert result.action == "discard_owner_message"
    assert result.turn_id is None
    non_term = await turns.list_non_terminal(202)
    assert non_term == []
    old = await turns.get(created.turn_id)
    assert old is not None
    assert old.status == TurnStatus.SUPERSEDED.value
    assert old.superseded_by is None


@pytest.mark.asyncio
async def test_coordinate_owner_idle_discards_no_create(coordinator: tuple) -> None:
    coord, turns, _, _ = coordinator
    result = await coord.coordinate(chat_id=203, autor="owner")
    assert result.action == "discard_owner_message"
    assert result.turn_id is None
    non_term = await turns.list_non_terminal(203)
    assert non_term == []
    # No turn rows created for owner path.
    all_for_chat = [
        t for t in turns._turns.values() if t.chat_id == 203  # type: ignore[attr-defined]
    ]
    assert all_for_chat == []


@pytest.mark.asyncio
async def test_coordinate_owner_discards_cancels_approvals_and_pending(
    coordinator: tuple,
) -> None:
    coord, turns, approvals, canceller = coordinator
    first = await coord.begin_turn(chat_id=204)
    await coord.transition(first.id, TurnStatus.PENDING_APPROVAL)
    await approvals.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=first.id,
            chat_id=204,
            business_connection_id="bc",
            draft_text="draft",
            status="waiting",
        )
    )
    result = await coord.coordinate(chat_id=204, autor="owner")
    assert result.action == "discard_owner_message"
    assert result.turn_id is None
    assert await turns.list_non_terminal(204) == []
    appr = await approvals.get_by_turn(first.id)
    assert appr is not None
    assert appr.status == "cancelled"
    assert canceller.calls == [(204, "owner_message")]


@pytest.mark.asyncio
async def test_coordinate_vip_replace_cancel_reason_new_message(
    coordinator: tuple,
) -> None:
    coord, _, _, canceller = coordinator
    await coord.coordinate(chat_id=205, autor="vip")
    await coord.coordinate(chat_id=205, autor="vip")
    assert canceller.calls == [(205, "new_message")]


@pytest.mark.asyncio
async def test_concurrent_coordinate_vip_one_non_terminal(
    coordinator: tuple,
) -> None:
    coord, turns, _, _ = coordinator
    results = await asyncio.gather(
        coord.coordinate(chat_id=206, autor="vip"),
        coord.coordinate(chat_id=206, autor="vip"),
        coord.coordinate(chat_id=206, autor="vip"),
    )
    assert all(r.action in ("create", "replace") for r in results)
    assert len({r.turn_id for r in results}) == 3
    non_term = await turns.list_non_terminal(206)
    assert len(non_term) == 1


@pytest.mark.asyncio
async def test_begin_turn_still_vip_create_replace(coordinator: tuple) -> None:
    """VIP wrappers still supersede on second begin_turn."""
    coord, turns, _, _ = coordinator
    first = await coord.begin_turn(chat_id=207)
    second = await coord.begin_turn(chat_id=207)
    old = await turns.get(first.id)
    assert old is not None
    assert old.status == TurnStatus.SUPERSEDED.value
    assert old.superseded_by == second.id
    non_term = await turns.list_non_terminal(207)
    assert len(non_term) == 1
    assert non_term[0].id == second.id


@pytest.mark.asyncio
async def test_chat_scope_lock_timeout_raises() -> None:
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    canceller = FakeCanceller()
    coord = TurnCoordinator(
        turns,
        approvals,
        canceller,
        lock_acquire_timeout_s=0.05,
        lock_acquire_retries=0,
    )
    lock = await coord._locks.lock_for(208)
    await lock.acquire()
    try:
        with pytest.raises(ChatLockTimeoutError):
            await coord.coordinate(chat_id=208, autor="vip")
        # No silent success / no turn created while lock held.
        assert await turns.list_non_terminal(208) == []
    finally:
        lock.release()


# --- BR-07: cancel pending recontact on VIP coordinate ---


class FakeRecontactCanceller:
    def __init__(
        self,
        *,
        raise_on_cancel: bool = False,
        raise_on_schedule: bool = False,
    ) -> None:
        self.calls: list[UUID] = []
        self.schedule_calls: list[UUID] = []
        self._raise = raise_on_cancel
        self._raise_schedule = raise_on_schedule

    async def cancel_recontact(self, vip_id: UUID) -> bool:
        self.calls.append(vip_id)
        if self._raise:
            raise RuntimeError("cancel boom")
        return True

    async def schedule_recontact(self, vip_id: UUID) -> object | None:
        self.schedule_calls.append(vip_id)
        if self._raise_schedule:
            raise RuntimeError("schedule boom")
        return object()


def _coord_with_recontact(
    *,
    recontact: FakeRecontactCanceller | None,
    feature_recontact_enabled: bool,
) -> tuple[TurnCoordinator, InMemoryTurnStore, FakeRecontactCanceller | None]:
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    behavior = FakeCanceller()
    coord = TurnCoordinator(
        turns,
        approvals,
        behavior,
        recontact=recontact,
        feature_recontact_enabled=feature_recontact_enabled,
    )
    return coord, turns, recontact


@pytest.mark.asyncio
async def test_vip_coordinate_cancels_recontact_when_flag_on() -> None:
    vip_id = uuid4()
    recontact = FakeRecontactCanceller()
    coord, turns, _ = _coord_with_recontact(
        recontact=recontact, feature_recontact_enabled=True
    )
    result = await coord.coordinate(chat_id=300, autor="vip", vip_id=vip_id)
    assert result.action == "create"
    assert result.turn_id is not None
    assert recontact.calls == [vip_id]
    assert recontact.schedule_calls == [vip_id]
    assert len(await turns.list_non_terminal(300)) == 1


@pytest.mark.asyncio
async def test_vip_coordinate_unlocked_cancels_recontact_when_flag_on() -> None:
    vip_id = uuid4()
    recontact = FakeRecontactCanceller()
    coord, turns, _ = _coord_with_recontact(
        recontact=recontact, feature_recontact_enabled=True
    )
    async with coord.chat_scope(301):
        result = await coord.coordinate_unlocked(
            chat_id=301, autor="vip", vip_id=vip_id
        )
    assert result.action == "create"
    assert recontact.calls == [vip_id]
    assert recontact.schedule_calls == [vip_id]
    assert len(await turns.list_non_terminal(301)) == 1


@pytest.mark.asyncio
async def test_vip_coordinate_no_cancel_when_flag_off() -> None:
    vip_id = uuid4()
    recontact = FakeRecontactCanceller()
    coord, _, _ = _coord_with_recontact(
        recontact=recontact, feature_recontact_enabled=False
    )
    await coord.coordinate(chat_id=302, autor="vip", vip_id=vip_id)
    assert recontact.calls == []


@pytest.mark.asyncio
async def test_vip_coordinate_no_cancel_when_recontact_none() -> None:
    vip_id = uuid4()
    coord, turns, _ = _coord_with_recontact(
        recontact=None, feature_recontact_enabled=True
    )
    result = await coord.coordinate(chat_id=303, autor="vip", vip_id=vip_id)
    assert result.action == "create"
    assert result.turn_id is not None
    assert len(await turns.list_non_terminal(303)) == 1


@pytest.mark.asyncio
async def test_vip_coordinate_no_cancel_when_vip_id_none() -> None:
    recontact = FakeRecontactCanceller()
    coord, _, _ = _coord_with_recontact(
        recontact=recontact, feature_recontact_enabled=True
    )
    await coord.coordinate(chat_id=304, autor="vip", vip_id=None)
    assert recontact.calls == []


@pytest.mark.asyncio
async def test_vip_coordinate_fail_soft_when_cancel_raises() -> None:
    from diana.application.observability import (
        get_swallowed_counts,
        reset_swallowed_counts,
    )

    reset_swallowed_counts()
    vip_id = uuid4()
    recontact = FakeRecontactCanceller(raise_on_cancel=True)
    coord, turns, _ = _coord_with_recontact(
        recontact=recontact, feature_recontact_enabled=True
    )
    result = await coord.coordinate(chat_id=305, autor="vip", vip_id=vip_id)
    assert result.action == "create"
    assert result.turn_id is not None
    assert recontact.calls == [vip_id]
    # Schedule still attempted after cancel failure (independent fail-soft).
    assert recontact.schedule_calls == [vip_id]
    rec = await turns.get(result.turn_id)
    assert rec is not None
    assert rec.status == TurnStatus.WAITING_DELAY.value
    assert get_swallowed_counts().get(
        "recontact_cancel_on_vip_message_failed", 0
    ) == 1


@pytest.mark.asyncio
async def test_owner_coordinate_does_not_cancel_recontact() -> None:
    vip_id = uuid4()
    recontact = FakeRecontactCanceller()
    coord, _, _ = _coord_with_recontact(
        recontact=recontact, feature_recontact_enabled=True
    )
    result = await coord.coordinate(chat_id=306, autor="owner", vip_id=vip_id)
    assert result.action == "discard_owner_message"
    assert recontact.calls == []



@pytest.mark.asyncio
async def test_vip_coordinate_schedules_recontact_after_cancel() -> None:
    """R3: VIP path cancels then schedules recontact (seed inactivity clock)."""
    vip_id = uuid4()
    recontact = FakeRecontactCanceller()
    coord, turns, _ = _coord_with_recontact(
        recontact=recontact, feature_recontact_enabled=True
    )
    result = await coord.coordinate(chat_id=310, autor="vip", vip_id=vip_id)
    assert result.action == "create"
    assert recontact.calls == [vip_id]
    assert recontact.schedule_calls == [vip_id]
    assert len(await turns.list_non_terminal(310)) == 1


@pytest.mark.asyncio
async def test_vip_coordinate_no_schedule_when_flag_off() -> None:
    vip_id = uuid4()
    recontact = FakeRecontactCanceller()
    coord, _, _ = _coord_with_recontact(
        recontact=recontact, feature_recontact_enabled=False
    )
    await coord.coordinate(chat_id=311, autor="vip", vip_id=vip_id)
    assert recontact.calls == []
    assert recontact.schedule_calls == []


@pytest.mark.asyncio
async def test_vip_coordinate_fail_soft_when_schedule_raises() -> None:
    from diana.application.observability import (
        get_swallowed_counts,
        reset_swallowed_counts,
    )

    reset_swallowed_counts()
    vip_id = uuid4()
    recontact = FakeRecontactCanceller(raise_on_schedule=True)
    coord, turns, _ = _coord_with_recontact(
        recontact=recontact, feature_recontact_enabled=True
    )
    result = await coord.coordinate(chat_id=312, autor="vip", vip_id=vip_id)
    assert result.action == "create"
    assert recontact.calls == [vip_id]
    assert recontact.schedule_calls == [vip_id]
    assert result.turn_id is not None
    rec = await turns.get(result.turn_id)
    assert rec is not None
    assert rec.status == TurnStatus.WAITING_DELAY.value
    assert get_swallowed_counts().get(
        "recontact_schedule_on_vip_message_failed", 0
    ) == 1


@pytest.mark.asyncio
async def test_owner_coordinate_does_not_schedule_recontact() -> None:
    vip_id = uuid4()
    recontact = FakeRecontactCanceller()
    coord, _, _ = _coord_with_recontact(
        recontact=recontact, feature_recontact_enabled=True
    )
    result = await coord.coordinate(chat_id=313, autor="owner", vip_id=vip_id)
    assert result.action == "discard_owner_message"
    assert recontact.schedule_calls == []



@pytest.mark.asyncio
async def test_reset_chat_session_supersedes_keeps_going(coordinator: tuple) -> None:
    """reset_chat_session supersedes non-terminal turns under chat_scope."""
    coord, turns, approvals, behavior = coordinator
    t1 = await coord.begin_turn(chat_id=7, trigger_message_id=1)
    n = await coord.reset_chat_session(7, reason="sandbox_reset")
    assert n == 1
    rec = await turns.get(t1.id)
    assert rec is not None
    assert rec.status == "superseded"


# ── owner intervention lifecycle ──────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_owner_intervened_sets_flag(coordinator: tuple) -> None:
    coord, _, _, _ = coordinator
    coord.mark_owner_intervened(10)
    assert coord.is_owner_intervened(10) is True


@pytest.mark.asyncio
async def test_is_owner_intervened_false_when_never_marked(coordinator: tuple) -> None:
    coord, _, _, _ = coordinator
    assert coord.is_owner_intervened(99) is False


@pytest.mark.asyncio
async def test_clear_owner_intervention_removes_flag(coordinator: tuple) -> None:
    coord, _, _, _ = coordinator
    coord.mark_owner_intervened(20)
    coord.clear_owner_intervention(20)
    assert coord.is_owner_intervened(20) is False


@pytest.mark.asyncio
async def test_is_owner_intervened_since_filters_old_timestamps(
    coordinator: tuple,
) -> None:
    coord, _, _, _ = coordinator
    coord.mark_owner_intervened(30)
    # Intervention happened before 'since' — should be ignored.
    later = time.monotonic()
    assert coord.is_owner_intervened(30, since=later) is False


@pytest.mark.asyncio
async def test_is_owner_intervened_since_sees_recent_timestamps(
    coordinator: tuple,
) -> None:
    coord, _, _, _ = coordinator
    before = time.monotonic()
    coord.mark_owner_intervened(40)
    # Intervention happened after 'since' — should be detected.
    assert coord.is_owner_intervened(40, since=before) is True


@pytest.mark.asyncio
async def test_coordinate_owner_clears_intervention_flag(
    coordinator: tuple,
) -> None:
    """Owner coordinate path must clear the flag so future VIP messages proceed."""
    coord, _, _, _ = coordinator
    coord.mark_owner_intervened(50)
    result = await coord.coordinate(chat_id=50, autor="owner")
    assert result.action == "discard_owner_message"
    assert coord.is_owner_intervened(50) is False


@pytest.mark.asyncio
async def test_coordinate_unlocked_owner_clears_intervention_flag(
    coordinator: tuple,
) -> None:
    """coordinate_unlocked with autor='owner' must clear the flag (regression)."""
    coord, _, _, _ = coordinator
    coord.mark_owner_intervened(60)
    async with coord.chat_scope(60):
        result = await coord.coordinate_unlocked(chat_id=60, autor="owner")
    assert result.action == "discard_owner_message"
    assert coord.is_owner_intervened(60) is False


@pytest.mark.asyncio
async def test_subsequent_vip_message_not_aborted_after_owner_coordinate(
    coordinator: tuple,
) -> None:
    """Full lifecycle: owner writes → coordinate clears → next VIP proceeds."""
    coord, _, _, _ = coordinator
    # Owner writes — middleware marks and coordinates.
    coord.mark_owner_intervened(70)
    await coord.coordinate(chat_id=70, autor="owner")
    # Flag must be clear now.
    assert coord.is_owner_intervened(70) is False
    # A VIP message arriving later should see no intervention.
    result = await coord.coordinate(chat_id=70, autor="vip")
    assert result.action == "create"
    assert result.turn_id is not None


@pytest.mark.asyncio
async def test_is_owner_intervened_stale_flag_reproduction(coordinator: tuple) -> None:
    """Reproduce the bug: without the fix, flag survives owner coordinate.

    This test verifies the exact scenario that caused the false activation:
    mark → coordinate(owner) → flag MUST be gone so the next message works.
    """
    coord, _, _, _ = coordinator

    # Simulate what OwnerDetectionMiddleware does: mark then coordinate.
    coord.mark_owner_intervened(80)
    await coord.coordinate(chat_id=80, autor="owner")

    # After coordinate returns, the flag must be clear.
    # Before the fix this assertion FAILED — the flag leaked forever.
    assert not coord.is_owner_intervened(80), (
        "BUG: owner intervention flag leaked past coordinate(). "
        "Every subsequent VIP message in this chat would be falsely aborted."
    )
