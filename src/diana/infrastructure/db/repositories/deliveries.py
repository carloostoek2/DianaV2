"""SqlPendingDeliveryStore — transition table parity with InMemory."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.memory import DELIVERY_TRANSITIONS
from diana.application.ports import DeliveryRecord
from diana.infrastructure.db.models import PendingDelivery


def can_transition_delivery(current: str, new_status: str) -> bool:
    """Pure transition check used by SQL and unit tests."""
    return new_status in DELIVERY_TRANSITIONS.get(current, frozenset())


def delivery_orm_to_record(row: PendingDelivery) -> DeliveryRecord:
    texts = row.texts if isinstance(row.texts, list) else list(row.texts or [])
    decision = row.decision if isinstance(row.decision, dict) else dict(row.decision or {})
    return DeliveryRecord(
        id=row.id,
        chat_id=row.chat_id,
        business_connection_id=row.business_connection_id,
        texts=[str(t) for t in texts],
        decision=decision,
        scheduled_at=row.scheduled_at,
        status=row.status,
        turn_id=row.turn_id,
        vip_id=row.vip_id,
    )


class SqlPendingDeliveryStore:
    """Postgres-backed deliveries with monotonic status machine."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def insert_pending(self, record: DeliveryRecord) -> DeliveryRecord:
        async with self._sf() as session:
            row = PendingDelivery(
                id=record.id,
                chat_id=record.chat_id,
                vip_id=record.vip_id,
                business_connection_id=record.business_connection_id,
                texts=list(record.texts),
                decision=dict(record.decision),
                scheduled_at=record.scheduled_at,
                status=record.status or "pending",
                turn_id=record.turn_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return delivery_orm_to_record(row)

    async def update_status(
        self, delivery_id: UUID, status: str, **meta: Any
    ) -> bool:
        _ = meta
        async with self._sf() as session:
            row = await session.get(PendingDelivery, delivery_id)
            if row is None:
                raise KeyError(f"delivery not found: {delivery_id}")
            if not can_transition_delivery(row.status, status):
                return False
            row.status = status
            await session.commit()
            return True

    async def cancel_for_chat(self, chat_id: int) -> int:
        async with self._sf() as session:
            result = await session.execute(
                select(PendingDelivery).where(
                    PendingDelivery.chat_id == chat_id,
                    PendingDelivery.status.in_(("pending", "delivering")),
                )
            )
            rows = result.scalars().all()
            count = 0
            for row in rows:
                if can_transition_delivery(row.status, "cancelled"):
                    row.status = "cancelled"
                    count += 1
            await session.commit()
            return count

    async def list_pending(self) -> list[DeliveryRecord]:
        async with self._sf() as session:
            result = await session.execute(
                select(PendingDelivery).where(PendingDelivery.status == "pending")
            )
            return [delivery_orm_to_record(r) for r in result.scalars().all()]

    async def list_active(self) -> list[DeliveryRecord]:
        async with self._sf() as session:
            result = await session.execute(
                select(PendingDelivery).where(
                    PendingDelivery.status.in_(("pending", "delivering"))
                )
            )
            return [delivery_orm_to_record(r) for r in result.scalars().all()]

    async def get(self, delivery_id: UUID) -> DeliveryRecord | None:
        async with self._sf() as session:
            row = await session.get(PendingDelivery, delivery_id)
            return delivery_orm_to_record(row) if row else None


__all__ = [
    "SqlPendingDeliveryStore",
    "can_transition_delivery",
    "delivery_orm_to_record",
]
