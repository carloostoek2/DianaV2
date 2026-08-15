"""LinkCoordinator — dedup, VIP verify, kick decision orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from diana.application.link import LinkCoordinator
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryLinkEventStore,
    InMemoryVipStore,
)
from diana.application.ports import LinkEventRecord, LinkNotification

DISABLE_FROZEN_UNTIL = datetime(2099, 12, 31, tzinfo=UTC)
CLOCK_NOW = datetime(2026, 1, 1, tzinfo=UTC)


async def _seed_event(
    links: InMemoryLinkEventStore,
    *,
    event_id: str,
    vip_id: UUID | None,
    user_id: int = 12345,
    state: str = "pending",
) -> None:
    await links.create(
        LinkEventRecord(
            event_id=event_id,
            user_id=user_id,
            username="@ana",
            channel_id=777,
            channel_name="Canal VIP",
            reason="r",
            vip_id=vip_id,
            state=state,
        )
    )


def _coordinator(
    *, enabled: bool = True,
) -> tuple[
    LinkCoordinator,
    InMemoryVipStore,
    InMemoryLinkEventStore,
    FakeOwnerNotifier,
]:
    vips = InMemoryVipStore()
    links = InMemoryLinkEventStore()
    notifier = FakeOwnerNotifier()
    coord = LinkCoordinator(
        vips=vips,
        links=links,
        notifier=notifier,
        owner_telegram_id=999001,
        clock=lambda: CLOCK_NOW,
        disable_frozen_until=DISABLE_FROZEN_UNTIL,
        enabled=enabled,
    )
    return coord, vips, links, notifier


@pytest.fixture
def coordinator() -> tuple[
    LinkCoordinator,
    InMemoryVipStore,
    InMemoryLinkEventStore,
    FakeOwnerNotifier,
]:
    return _coordinator()


# --- handle_kick_event ---


@pytest.mark.asyncio
async def test_handle_kick_event_vip_notifies(
    coordinator: tuple,
) -> None:
    coord, vips, links, notifier = coordinator
    await vips.add(12345, display_name="Ana")
    await coord.handle_kick_event(
        event_id="evt-1",
        user_id=12345,
        username="@ana",
        reason="quitó el acceso",
        channel_id=777,
        channel_name="Canal VIP",
    )
    rec = await links.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.state == "notified"
    assert rec.vip_id is not None
    assert notifier.links == [
        LinkNotification(display_name="Ana", username="@ana", event_id="evt-1")
    ]


@pytest.mark.asyncio
async def test_handle_kick_event_dedup_no_re_notify(
    coordinator: tuple,
) -> None:
    coord, vips, links, notifier = coordinator
    await vips.add(12345, display_name="Ana")
    await coord.handle_kick_event(
        event_id="evt-1",
        user_id=12345,
        username="@ana",
        reason="r",
        channel_id=777,
        channel_name="Canal VIP",
    )
    await coord.handle_kick_event(
        event_id="evt-1",
        user_id=12345,
        username="@ana",
        reason="r",
        channel_id=777,
        channel_name="Canal VIP",
    )
    assert len(notifier.links) == 1
    rec = await links.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.state == "notified"


@pytest.mark.asyncio
async def test_handle_kick_event_non_vip_ignored(
    coordinator: tuple,
) -> None:
    coord, vips, links, notifier = coordinator
    await coord.handle_kick_event(
        event_id="evt-1",
        user_id=99999,
        username="@ghost",
        reason="r",
        channel_id=777,
        channel_name="Canal VIP",
    )
    rec = await links.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.state == "ignored_not_vip"
    assert rec.vip_id is None
    assert notifier.links == []


@pytest.mark.asyncio
async def test_handle_kick_event_flag_off_noop() -> None:
    coord, vips, links, notifier = _coordinator(enabled=False)
    await vips.add(12345, display_name="Ana")
    await coord.handle_kick_event(
        event_id="evt-1",
        user_id=12345,
        username="@ana",
        reason="r",
        channel_id=777,
        channel_name="Canal VIP",
    )
    assert await links.get_by_event_id("evt-1") is None
    assert notifier.links == []


# --- handle_decision ---


@pytest.mark.asyncio
async def test_handle_decision_expel_deactivates_vip(
    coordinator: tuple,
) -> None:
    coord, vips, links, _ = coordinator
    ana = await vips.add(12345, display_name="Ana")
    await _seed_event(links, event_id="evt-1", vip_id=ana.id)
    reply = await coord.handle_decision("evt-1", "expel")
    assert reply == "Suscriptor expulsado."
    rec = await links.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.state == "decided_expel"
    updated = await vips.get_by_telegram_user_id(12345)
    assert updated is not None
    assert updated.is_active is False


@pytest.mark.asyncio
async def test_handle_decision_disable_freezes_vip(
    coordinator: tuple,
) -> None:
    coord, vips, links, _ = coordinator
    ana = await vips.add(12345, display_name="Ana")
    await _seed_event(links, event_id="evt-1", vip_id=ana.id)
    reply = await coord.handle_decision("evt-1", "disable")
    assert reply == "VIP inhabilitado."
    rec = await links.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.state == "decided_disable"
    updated = await vips.get_by_telegram_user_id(12345)
    assert updated is not None
    assert updated.frozen_until == DISABLE_FROZEN_UNTIL


@pytest.mark.asyncio
async def test_handle_decision_keep_leaves_vip_unchanged(
    coordinator: tuple,
) -> None:
    coord, vips, links, _ = coordinator
    ana = await vips.add(12345, display_name="Ana")
    await _seed_event(links, event_id="evt-1", vip_id=ana.id)
    reply = await coord.handle_decision("evt-1", "keep")
    assert reply == "Sin cambios."
    rec = await links.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.state == "decided_keep"
    updated = await vips.get_by_telegram_user_id(12345)
    assert updated is not None
    assert updated.is_active is True
    assert updated.frozen_until is None


@pytest.mark.asyncio
async def test_handle_decision_stale_terminal_noop_early_return(
    coordinator: tuple,
) -> None:
    coord, vips, links, _ = coordinator
    ana = await vips.add(12345, display_name="Ana")
    await _seed_event(links, event_id="evt-1", vip_id=ana.id, state="decided_keep")
    reply = await coord.handle_decision("evt-1", "expel")
    assert reply == "ya no aplica"
    rec = await links.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.state == "decided_keep"  # terminal state untouched
    updated = await vips.get_by_telegram_user_id(12345)
    assert updated is not None
    assert updated.is_active is True


@pytest.mark.asyncio
async def test_handle_decision_ignored_not_vip_noop(
    coordinator: tuple,
) -> None:
    coord, vips, links, _ = coordinator
    await _seed_event(links, event_id="evt-1", vip_id=uuid4(), state="ignored_not_vip")
    reply = await coord.handle_decision("evt-1", "expel")
    assert reply == "ya no aplica"
    rec = await links.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.state == "ignored_not_vip"


@pytest.mark.asyncio
async def test_handle_decision_vip_id_none_marks_noop(
    coordinator: tuple,
) -> None:
    coord, vips, links, _ = coordinator
    await _seed_event(links, event_id="evt-1", vip_id=None)
    reply = await coord.handle_decision("evt-1", "expel")
    assert reply == "ya no aplica"
    rec = await links.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.state == "noop"


@pytest.mark.asyncio
async def test_handle_decision_unknown_action_marks_noop(
    coordinator: tuple,
) -> None:
    coord, vips, links, _ = coordinator
    ana = await vips.add(12345, display_name="Ana")
    await _seed_event(links, event_id="evt-1", vip_id=ana.id)
    reply = await coord.handle_decision("evt-1", "explode")
    assert reply == "ya no aplica"
    rec = await links.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.state == "noop"


@pytest.mark.asyncio
async def test_handle_decision_deactivate_failed_marks_noop(
    coordinator: tuple,
) -> None:
    coord, vips, links, _ = coordinator
    # vip_id points nowhere AND user_id has no VIP row → deactivate() is False.
    await _seed_event(links, event_id="evt-1", vip_id=uuid4(), user_id=55555)
    reply = await coord.handle_decision("evt-1", "expel")
    assert reply == "ya no aplica"
    rec = await links.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.state == "noop"


@pytest.mark.asyncio
async def test_handle_decision_vip_missing_on_disable_marks_noop(
    coordinator: tuple,
) -> None:
    coord, vips, links, _ = coordinator
    # vip_id absent from the store → freeze_vip raises ValueError.
    await _seed_event(links, event_id="evt-1", vip_id=uuid4(), user_id=12345)
    reply = await coord.handle_decision("evt-1", "disable")
    assert reply == "ya no aplica"
    rec = await links.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.state == "noop"


@pytest.mark.asyncio
async def test_handle_decision_flag_off_noop_no_mutation() -> None:
    coord, vips, links, _ = _coordinator(enabled=False)
    ana = await vips.add(12345, display_name="Ana")
    await _seed_event(links, event_id="evt-1", vip_id=ana.id)
    reply = await coord.handle_decision("evt-1", "expel")
    assert reply == "ya no aplica"
    rec = await links.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.state == "pending"  # untouched
    updated = await vips.get_by_telegram_user_id(12345)
    assert updated is not None
    assert updated.is_active is True
