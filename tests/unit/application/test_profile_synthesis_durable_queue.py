"""Durable synthesis queue (Fila 4 C4) — trigger service + job durable path."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from diana.application.ports import (
    ProfileSynthesisQueueRecord,
    VipProfileRecord,
)
from diana.application.profile_synthesis_trigger_service import (
    ProfileSynthesisTriggerService,
)
from diana.jobs.profile_synthesis_job import run_profile_synthesis_cycle


class _MemoryProfileReader:
    async def get_or_create(self, vip_id):
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
    def __init__(self, counts: dict | None = None) -> None:
        self.counts = dict(counts or {})

    async def count_messages_since(self, vip_id, *, since):
        return self.counts.get(vip_id, 0)

    async def list_vips_with_activity_older_than(self, older_than, *, limit):
        return []


class _FakeQueue:
    """In-memory ProfileSynthesisQueueStore for tests."""

    def __init__(self) -> None:
        self.rows: dict = {}
        self.recover_calls: int = 0

    async def upsert_pending(self, vip_id, trigger):
        row = self.rows.get(vip_id)
        if row is None:
            row = ProfileSynthesisQueueRecord(vip_id=vip_id, trigger=trigger)
        self.rows[vip_id] = row.model_copy(update={"trigger": trigger})
        return self.rows[vip_id]

    async def drain(self, limit=100):
        claimed = []
        for vip_id, row in list(self.rows.items()):
            if row.status == "pending":
                claimed.append(
                    row.model_copy(
                        update={
                            "status": "processing",
                            "started_at": datetime.now(UTC),
                        }
                    )
                )
                self.rows[vip_id] = claimed[-1]
        return claimed[:limit]

    async def complete(self, vip_id):
        return self.rows.pop(vip_id, None) is not None

    async def recover_stale(self, *, max_age_seconds=3600):
        self.recover_calls += 1
        return 0

    async def list_pending(self, limit=100):
        return [r for r in self.rows.values() if r.status == "pending"]


def _service(queue=None, *, volume_threshold: int = 3, vip=None):
    return ProfileSynthesisTriggerService(
        profile_reader=_MemoryProfileReader(),
        activity=_MemoryActivity(
            counts={vip: 5} if vip is not None else {}
        ),
        volume_threshold=volume_threshold,
        inactivity_minutes=30,
        queue=queue,
    )


@pytest.mark.asyncio
async def test_enqueue_durable_persists() -> None:
    queue = _FakeQueue()
    svc = _service(queue)
    vip = uuid4()

    ok = await svc.enqueue_durable(vip, "volume")

    assert ok is True
    assert vip in queue.rows
    assert queue.rows[vip].status == "pending"
    assert queue.rows[vip].trigger == "volume"


@pytest.mark.asyncio
async def test_drain_durable_claims_and_release_removes() -> None:
    queue = _FakeQueue()
    svc = _service(queue)
    vip = uuid4()
    await svc.enqueue_durable(vip, "volume")

    items = await svc.drain_pending_durable()

    assert items == [(vip, "volume")]
    assert queue.rows[vip].status == "processing"
    await svc.release_durable(vip)
    assert vip not in queue.rows
    # In-memory guard released → re-enqueueable.
    assert await svc.enqueue_durable(vip, "volume") is True


@pytest.mark.asyncio
async def test_recover_stale_delegates() -> None:
    queue = _FakeQueue()
    svc = _service(queue)

    recovered = await svc.recover_stale(max_age_seconds=60)

    assert recovered == 0
    assert queue.recover_calls == 1


@pytest.mark.asyncio
async def test_evaluate_and_maybe_enqueue_uses_durable_path() -> None:
    queue = _FakeQueue()
    vip = uuid4()
    svc = _service(queue, vip=vip)

    trigger = await svc.evaluate_and_maybe_enqueue(vip, text="algo")

    assert trigger == "volume"
    assert vip in queue.rows


@pytest.mark.asyncio
async def test_job_durable_cycle_releases_every_item() -> None:
    queue = _FakeQueue()
    svc = _service(queue)
    vip_a = uuid4()
    vip_b = uuid4()
    await svc.enqueue_durable(vip_a, "volume")
    await svc.enqueue_durable(vip_b, "volume")

    class _Synthesis:
        async def synthesize(self, vip_id, trigger):
            return SimpleNamespace(status="ok")

    report = await run_profile_synthesis_cycle(svc, _Synthesis())

    assert report["items"] == 2
    assert report["results"] == ["ok", "ok"]
    assert queue.rows == {}  # both released durably
    assert queue.recover_calls == 1


@pytest.mark.asyncio
async def test_job_durable_cycle_failure_still_releases() -> None:
    queue = _FakeQueue()
    svc = _service(queue)
    vip = uuid4()
    await svc.enqueue_durable(vip, "volume")

    class _BoomSynthesis:
        async def synthesize(self, vip_id, trigger):
            raise RuntimeError("boom")

    report = await run_profile_synthesis_cycle(svc, _BoomSynthesis())

    assert report["results"] == ["failed"]
    assert queue.rows == {}


def test_no_queue_keeps_sync_path() -> None:
    svc = _service(queue=None)
    assert svc.has_durable_queue() is False
    vip = uuid4()
    assert svc.enqueue(vip, "volume") is True
    assert svc.drain_pending() == [(vip, "volume")]
