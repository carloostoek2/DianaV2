"""PromoTriggerRepo — thin lookup for promo_triggers."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import PromoTriggerRecord
from diana.infrastructure.db.models import PromoTrigger


def normalize_trigger_text(text: str) -> str:
    """Exact case-insensitive match key: strip + lower."""
    return text.strip().lower()


def promo_trigger_orm_to_record(row: PromoTrigger) -> PromoTriggerRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    sequence = row.response_sequence
    if isinstance(sequence, list):
        seq_list = [str(item) for item in sequence]
    else:
        seq_list = []
    return PromoTriggerRecord(
        id=row.id,
        trigger_text=row.trigger_text,
        response_sequence=seq_list,
        repeat_first_message=row.repeat_first_message,
        is_active=bool(row.is_active),
    )


class PromoTriggerRepo:
    """Thin trigger lookup — no LLM, no feature flags, exact text match only."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_active_by_trigger_text(
        self, text: str
    ) -> PromoTriggerRecord | None:
        normalized = normalize_trigger_text(text)
        async with self._sf() as session:
            result = await session.execute(
                select(PromoTrigger).where(
                    PromoTrigger.is_active.is_(True),
                    func.lower(PromoTrigger.trigger_text) == normalized,
                )
            )
            row = result.scalar_one_or_none()
            return promo_trigger_orm_to_record(row) if row else None

    async def list_active(self) -> list[PromoTriggerRecord]:
        async with self._sf() as session:
            result = await session.execute(
                select(PromoTrigger).where(PromoTrigger.is_active.is_(True))
            )
            return [promo_trigger_orm_to_record(r) for r in result.scalars().all()]


__all__ = [
    "PromoTriggerRepo",
    "normalize_trigger_text",
    "promo_trigger_orm_to_record",
]
