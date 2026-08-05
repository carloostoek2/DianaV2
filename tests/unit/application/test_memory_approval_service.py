"""MemoryApprovalService unit tests — fakes only (no DB / no network)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from diana.application.admin_service import OwnerAuthError
from diana.application.memory_approval_service import MemoryApprovalService
from diana.application.ports import VipRecord

OWNER = 999002
OTHER = 111222


class FakeMemories:
    """MemoryDecisionWriter double; records every decision call."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows: dict[str, dict] = {}
        for r in rows or []:
            self.rows[str(r["id"])] = dict(r)
        self.set_calls: list[tuple[str, str, str]] = []
        self.list_limits: list[int] = []

    def add(self, row: dict) -> None:
        self.rows[str(row["id"])] = dict(row)

    async def list_pending_owner(self, limit: int = 50) -> list[dict]:
        self.list_limits.append(limit)
        return [
            dict(r)
            for r in self.rows.values()
            if r.get("status") == "pending_owner"
        ]

    async def get_fact(self, fact_id: UUID) -> dict | None:
        row = self.rows.get(str(fact_id))
        return dict(row) if row is not None else None

    async def set_fact_status(
        self,
        fact_id: UUID,
        *,
        vip_id: UUID,
        new_status: str,
    ) -> bool:
        self.set_calls.append((str(fact_id), str(vip_id), new_status))
        row = self.rows.get(str(fact_id))
        if (
            row is None
            or row.get("status") != "pending_owner"
            or row.get("vip_id") != str(vip_id)
        ):
            return False
        row["status"] = new_status
        return True


class FakeVips:
    def __init__(self, name: str | None = None) -> None:
        self._name = name

    async def get_by_id(self, vip_id: UUID) -> Any:
        if self._name is None:
            return None
        return VipRecord(id=vip_id, telegram_user_id=111, display_name=self._name)


def _row(vip_id: UUID, *, status: str = "pending_owner") -> dict:
    return {
        "id": str(uuid4()),
        "vip_id": str(vip_id),
        "category": "sensible",
        "status": status,
        "content": {"texto": "hecho secreto", "fact": "hecho secreto"},
    }


def _build(memories: FakeMemories, *, vips: FakeVips | None = None) -> MemoryApprovalService:
    return MemoryApprovalService(
        memories=memories,
        owner_telegram_id=OWNER,
        vips=vips,
    )


@pytest.mark.asyncio
async def test_non_owner_raises_on_approve_and_list() -> None:
    vip = uuid4()
    memories = FakeMemories([_row(vip)])
    svc = _build(memories)

    with pytest.raises(OwnerAuthError):
        await svc.approve(OTHER, uuid4())
    with pytest.raises(OwnerAuthError):
        await svc.discard(None, uuid4())
    with pytest.raises(OwnerAuthError):
        await svc.list_pending(OTHER)
    assert memories.set_calls == []


@pytest.mark.asyncio
async def test_list_pending_enriches_vip_name() -> None:
    vip = uuid4()
    memories = FakeMemories([_row(vip)])
    svc = _build(memories, vips=FakeVips(name="Ana"))

    rows = await svc.list_pending(OWNER, limit=7)
    assert len(rows) == 1
    assert rows[0]["vip_name"] == "Ana"
    assert memories.list_limits == [7]


@pytest.mark.asyncio
async def test_list_pending_fallback_short_uuid() -> None:
    vip = uuid4()
    memories = FakeMemories([_row(vip)])
    svc = _build(memories)  # vips None

    rows = await svc.list_pending(OWNER)
    assert len(rows) == 1
    assert rows[0]["vip_name"] == str(vip)[:8]


@pytest.mark.asyncio
async def test_approve_ok() -> None:
    vip = uuid4()
    row = _row(vip)
    memories = FakeMemories([row])
    svc = _build(memories)

    token = await svc.approve(OWNER, UUID(row["id"]))
    assert token == "approved"
    assert memories.set_calls == [(row["id"], str(vip), "approved")]


@pytest.mark.asyncio
async def test_discard_ok() -> None:
    vip = uuid4()
    row = _row(vip)
    memories = FakeMemories([row])
    svc = _build(memories)

    token = await svc.discard(OWNER, UUID(row["id"]))
    assert token == "discarded"
    assert memories.set_calls == [(row["id"], str(vip), "discarded")]


@pytest.mark.asyncio
async def test_decide_stale_when_missing_or_decided() -> None:
    vip = uuid4()
    row = _row(vip, status="auto")  # already decided (auto)
    memories = FakeMemories([row])
    svc = _build(memories)

    # Missing row → stale, no write attempted.
    assert await svc.approve(OWNER, uuid4()) == "stale"
    # Row not pending_owner (auto) → stale, no write attempted.
    assert await svc.approve(OWNER, UUID(row["id"])) == "stale"
    assert memories.set_calls == []


@pytest.mark.asyncio
async def test_set_fact_status_false_maps_to_stale() -> None:
    vip = uuid4()
    row = _row(vip)
    memories = FakeMemories([row])

    async def _refuse(fact_id: UUID, *, vip_id: UUID, new_status: str) -> bool:
        memories.set_calls.append((str(fact_id), str(vip_id), new_status))
        return False

    memories.set_fact_status = _refuse  # type: ignore[method-assign]
    svc = _build(memories)

    assert await svc.approve(OWNER, UUID(row["id"])) == "stale"
    assert memories.set_calls == [(row["id"], str(vip), "approved")]
