"""SqlVipStore — allowlist adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uuid import UUID

from diana.application.ports import VipRecord
from diana.infrastructure.db.models import Vip


def vip_orm_to_record(row: Vip) -> VipRecord:
    """Pure mapper ORM Vip → VipRecord (unit-testable without DB)."""
    return VipRecord(
        id=row.id,
        telegram_user_id=row.telegram_user_id,
        display_name=row.display_name,
        is_active=bool(row.is_active),
        paused_until=row.paused_until,
        frozen_until=row.frozen_until,
        auto_send=bool(getattr(row, "auto_send", False)),
    )


def vip_is_allowed(
    rec: VipRecord, *, now: datetime | None = None
) -> bool:
    """Pure allowlist check shared with InMemory semantics."""
    if not rec.is_active:
        return False
    if rec.paused_until is None:
        return True
    clock = now or datetime.now(UTC)
    paused = rec.paused_until
    if paused.tzinfo is None and clock.tzinfo is not None:
        paused = paused.replace(tzinfo=clock.tzinfo)
    return paused < clock


class SqlVipStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_by_telegram_user_id(
        self, telegram_user_id: int
    ) -> VipRecord | None:
        async with self._sf() as session:
            result = await session.execute(
                select(Vip).where(Vip.telegram_user_id == telegram_user_id)
            )
            row = result.scalar_one_or_none()
            return vip_orm_to_record(row) if row else None

    async def is_allowed(
        self, telegram_user_id: int, *, now: datetime | None = None
    ) -> bool:
        rec = await self.get_by_telegram_user_id(telegram_user_id)
        if rec is None:
            return False
        return vip_is_allowed(rec, now=now)

    async def add(
        self, telegram_user_id: int, *, display_name: str | None = None
    ) -> VipRecord:
        async with self._sf() as session:
            result = await session.execute(
                select(Vip).where(Vip.telegram_user_id == telegram_user_id)
            )
            row = result.scalar_one_or_none()
            if row is not None:
                row.is_active = True
                if display_name is not None:
                    row.display_name = display_name
                await session.commit()
                await session.refresh(row)
                return vip_orm_to_record(row)
            row = Vip(
                id=uuid4(),
                telegram_user_id=telegram_user_id,
                display_name=display_name,
                is_active=True,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return vip_orm_to_record(row)

    async def deactivate(self, telegram_user_id: int) -> bool:
        async with self._sf() as session:
            result = await session.execute(
                select(Vip).where(Vip.telegram_user_id == telegram_user_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return False
            row.is_active = False
            await session.commit()
            return True

    async def get_by_id(self, vip_id: UUID) -> VipRecord | None:
        async with self._sf() as session:
            result = await session.execute(select(Vip).where(Vip.id == vip_id))
            row = result.scalar_one_or_none()
            return vip_orm_to_record(row) if row else None

    async def freeze_vip(self, vip_id: UUID, frozen_until: datetime) -> None:
        async with self._sf() as session:
            result = await session.execute(select(Vip).where(Vip.id == vip_id))
            row = result.scalar_one_or_none()
            if row is None:
                raise ValueError(f"VIP {vip_id} not found")
            row.frozen_until = frozen_until
            await session.commit()

    async def unfreeze_vip(self, vip_id: UUID) -> None:
        async with self._sf() as session:
            result = await session.execute(select(Vip).where(Vip.id == vip_id))
            row = result.scalar_one_or_none()
            if row is None:
                raise ValueError(f"VIP {vip_id} not found")
            row.frozen_until = None
            await session.commit()


__all__ = ["SqlVipStore", "vip_is_allowed", "vip_orm_to_record"]
