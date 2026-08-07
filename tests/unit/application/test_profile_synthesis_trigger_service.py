"""ProfileSynthesisTriggerService — 4 OR conditions + in-memory dedup (no LLM)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from diana.application.ports import VipProfileRecord
from diana.application.profile_synthesis_trigger_service import (
    ProfileSynthesisTriggerService,
)


def _now() -> datetime:
    return datetime.now(UTC)


class _MemoryProfileReader:
    """get_or_create fake: returns existing row or an empty version-0 default."""

    def __init__(self, rows: dict | None = None) -> None:
        self.rows = dict(rows or {})
        self.get_calls: list = []

    async def get_or_create(self, vip_id):
        self.get_calls.append(vip_id)
        row = self.rows.get(vip_id)
        if row is not None:
            return row
        return VipProfileRecord(
            vip_id=vip_id,
            stable_traits={},
            recent_trend={},
            sensitivities=[],
            version=0,
            last_synthesized_at=None,
            synthesis_trigger=None,
        )


class _MemoryActivity:
    def __init__(
        self,
        *,
        counts: dict | None = None,
        inactive: list[tuple] | None = None,
    ) -> None:
        self.counts = dict(counts or {})
        self.inactive = list(inactive or [])
        self.count_calls: list = []
        self.scan_calls: int = 0

    async def count_messages_since(self, vip_id, *, since):
        self.count_calls.append((vip_id, since))
        return self.counts.get(vip_id, 0)

    async def list_vips_with_activity_older_than(self, older_than, *, limit):
        self.scan_calls += 1
        return list(self.inactive)


def _signal(should: bool = True) -> SimpleNamespace:
    return SimpleNamespace(should_trigger_synthesis=should)


@pytest.mark.asyncio
async def test_volume_threshold_enqueues() -> None:
    vip = uuid4()
    reader = _MemoryProfileReader()
    activity = _MemoryActivity(counts={vip: 25})
    svc = ProfileSynthesisTriggerService(
        profile_reader=reader, activity=activity,
        volume_threshold=25, inactivity_minutes=30,
    )
    label = await svc.evaluate_and_maybe_enqueue(vip)
    assert label == "volume"
    assert svc.drain_pending() == [(vip, "volume")]


@pytest.mark.asyncio
async def test_below_threshold_no_enqueue() -> None:
    vip = uuid4()
    activity = _MemoryActivity(counts={vip: 24})
    svc = ProfileSynthesisTriggerService(
        profile_reader=_MemoryProfileReader(), activity=activity,
        volume_threshold=25, inactivity_minutes=30,
    )
    assert await svc.evaluate_and_maybe_enqueue(vip) is None
    assert svc.drain_pending() == []


@pytest.mark.asyncio
async def test_strong_signal_wins_over_volume() -> None:
    vip = uuid4()
    activity = _MemoryActivity(counts={vip: 100})  # would fire volume
    svc = ProfileSynthesisTriggerService(
        profile_reader=_MemoryProfileReader(), activity=activity,
        volume_threshold=25, inactivity_minutes=30,
    )
    label = await svc.evaluate_and_maybe_enqueue(vip, text="me siento raro")
    assert label == "strong_signal"  # priority c over a
    assert svc.drain_pending() == [(vip, "strong_signal")]


@pytest.mark.asyncio
async def test_emotional_signal_priority_no_message_count() -> None:
    vip = uuid4()
    activity = _MemoryActivity(counts={})  # would NOT fire volume
    svc = ProfileSynthesisTriggerService(
        profile_reader=_MemoryProfileReader(), activity=activity,
        volume_threshold=25, inactivity_minutes=30,
    )
    label = await svc.evaluate_and_maybe_enqueue(
        vip, text="me siento raro", signal=_signal(should=True)
    )
    assert label == "emotional_signal"  # priority d over c and a
    # The emotional signal is immediate — no message count was read.
    assert activity.count_calls == []


@pytest.mark.asyncio
async def test_dedup_same_vip_single_pending() -> None:
    vip = uuid4()
    activity = _MemoryActivity(counts={vip: 30})
    svc = ProfileSynthesisTriggerService(
        profile_reader=_MemoryProfileReader(), activity=activity,
        volume_threshold=25, inactivity_minutes=30,
    )
    assert await svc.evaluate_and_maybe_enqueue(vip, text="me siento raro") == "strong_signal"
    assert await svc.evaluate_and_maybe_enqueue(vip, text="no sé qué hacer") == "strong_signal"
    # Both conditions matched but only ONE pending item, labeled by the first.
    assert svc.drain_pending() == [(vip, "strong_signal")]


@pytest.mark.asyncio
async def test_in_flight_blocks_re_enqueue_until_release() -> None:
    vip = uuid4()
    activity = _MemoryActivity(counts={vip: 30})
    svc = ProfileSynthesisTriggerService(
        profile_reader=_MemoryProfileReader(), activity=activity,
        volume_threshold=25, inactivity_minutes=30,
    )
    assert await svc.evaluate_and_maybe_enqueue(vip) == "volume"
    drained = svc.drain_pending()
    assert drained == [(vip, "volume")]

    # While in-flight, the condition still fires (label returned) but the dedup
    # guard does NOT re-enqueue — pending stays empty.
    assert await svc.evaluate_and_maybe_enqueue(vip) == "volume"
    assert svc.drain_pending() == []

    svc.release(vip)
    assert await svc.evaluate_and_maybe_enqueue(vip) == "volume"
    assert svc.drain_pending() == [(vip, "volume")]


@pytest.mark.asyncio
async def test_scan_inactivity_enqueues_session_close() -> None:
    vip = uuid4()
    older = _now() - timedelta(minutes=60)
    activity = _MemoryActivity(inactive=[(vip, older)])
    svc = ProfileSynthesisTriggerService(
        profile_reader=_MemoryProfileReader(), activity=activity,
        volume_threshold=25, inactivity_minutes=30,
    )
    enqueued = await svc.scan_inactivity(_now())
    assert enqueued == 1
    assert svc.drain_pending() == [(vip, "session_close")]


@pytest.mark.asyncio
async def test_scan_inactivity_skips_no_new_activity() -> None:
    vip = uuid4()
    last_synth = _now() - timedelta(hours=2)
    older = _now() - timedelta(hours=1)  # older than cutoff but newer than last_synth
    reader = _MemoryProfileReader(
        rows={
            vip: VipProfileRecord(
                vip_id=vip, stable_traits={}, recent_trend={}, sensitivities=[],
                version=1, last_synthesized_at=last_synth, synthesis_trigger=None,
            )
        }
    )
    activity = _MemoryActivity(inactive=[(vip, older)])
    svc = ProfileSynthesisTriggerService(
        profile_reader=reader, activity=activity,
        volume_threshold=25, inactivity_minutes=30,
    )
    enqueued = await svc.scan_inactivity(_now())
    assert enqueued == 1  # last_activity (1h ago) > last_synthesized_at (2h ago)


@pytest.mark.asyncio
async def test_scan_inactivity_skips_when_last_activity_before_last_synthesis() -> None:
    vip = uuid4()
    last_synth = _now() - timedelta(hours=1)
    older = _now() - timedelta(hours=2)  # older than cutoff AND older than last_synth
    reader = _MemoryProfileReader(
        rows={
            vip: VipProfileRecord(
                vip_id=vip, stable_traits={}, recent_trend={}, sensitivities=[],
                version=1, last_synthesized_at=last_synth, synthesis_trigger=None,
            )
        }
    )
    activity = _MemoryActivity(inactive=[(vip, older)])
    svc = ProfileSynthesisTriggerService(
        profile_reader=reader, activity=activity,
        volume_threshold=25, inactivity_minutes=30,
    )
    enqueued = await svc.scan_inactivity(_now())
    assert enqueued == 0
    assert svc.drain_pending() == []


@pytest.mark.asyncio
async def test_apply_overrides_changes_thresholds() -> None:
    svc = ProfileSynthesisTriggerService(
        profile_reader=_MemoryProfileReader(), activity=_MemoryActivity(),
        volume_threshold=25, inactivity_minutes=30,
    )
    svc.apply_overrides({"volume_threshold": 40, "inactivity_minutes": 15})
    assert svc._volume_threshold == 40  # noqa: SLF001
    assert svc._inactivity_minutes == 15  # noqa: SLF001


@pytest.mark.asyncio
async def test_apply_overrides_invalid_and_min_clamp_no_crash() -> None:
    svc = ProfileSynthesisTriggerService(
        profile_reader=_MemoryProfileReader(), activity=_MemoryActivity(),
        volume_threshold=25, inactivity_minutes=30,
    )
    svc.apply_overrides({"volume_threshold": "no", "inactivity_minutes": 0})
    assert svc._volume_threshold == 25  # noqa: SLF001 — invalid rejected
    assert svc._inactivity_minutes == 1  # noqa: SLF001 — clamped to min 1
    svc.apply_overrides(None)  # non-dict → no-op
    assert svc._volume_threshold == 25  # noqa: SLF001


@pytest.mark.asyncio
async def test_vip_id_none_noop() -> None:
    activity = _MemoryActivity(counts={})
    svc = ProfileSynthesisTriggerService(
        profile_reader=_MemoryProfileReader(), activity=activity,
        volume_threshold=25, inactivity_minutes=30,
    )
    assert await svc.evaluate_and_maybe_enqueue(None, text="me siento raro") is None
    assert activity.count_calls == []
    assert svc.drain_pending() == []
