"""SqlPendingApprovalStore — CAS claim_waiting parity with InMemory."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.memory import OPEN_APPROVAL_STATUSES
from diana.application.ports import ApprovalRecord
from diana.infrastructure.db.models import PendingApproval, Turn


def approval_orm_to_record(
    row: PendingApproval, *, trigger_message_id: int | None = None
) -> ApprovalRecord:
    return ApprovalRecord(
        id=row.id,
        turn_id=row.turn_id,
        chat_id=row.chat_id,
        business_connection_id=row.business_connection_id,
        draft_text=row.draft_text,
        status=row.status,
        vip_id=row.vip_id,
        cognitive_summary=row.cognitive_summary,
        evaluation=row.evaluation,
        owner_message_id=row.owner_message_id,
        # Schema gap: join turns.trigger_message_id when loading if not on row.
        trigger_message_id=trigger_message_id,
    )


class SqlPendingApprovalStore:
    """Postgres-backed approvals with atomic waiting → claimed CAS."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def _trigger_for(self, session: AsyncSession, turn_id: UUID) -> int | None:
        turn = await session.get(Turn, turn_id)
        return turn.trigger_message_id if turn else None

    async def create_waiting(self, record: ApprovalRecord) -> ApprovalRecord:
        async with self._sf() as session:
            row = PendingApproval(
                id=record.id,
                turn_id=record.turn_id,
                vip_id=record.vip_id,
                chat_id=record.chat_id,
                business_connection_id=record.business_connection_id,
                draft_text=record.draft_text,
                cognitive_summary=record.cognitive_summary,
                evaluation=record.evaluation,
                status="waiting",
                owner_message_id=record.owner_message_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return approval_orm_to_record(
                row, trigger_message_id=record.trigger_message_id
            )

    async def get_by_turn(self, turn_id: UUID) -> ApprovalRecord | None:
        async with self._sf() as session:
            result = await session.execute(
                select(PendingApproval).where(PendingApproval.turn_id == turn_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            trigger = await self._trigger_for(session, turn_id)
            return approval_orm_to_record(row, trigger_message_id=trigger)

    async def mark_status(self, turn_id: UUID, status: str) -> None:
        async with self._sf() as session:
            result = await session.execute(
                update(PendingApproval)
                .where(PendingApproval.turn_id == turn_id)
                .values(status=status)
                .returning(PendingApproval.id)
            )
            if result.scalar_one_or_none() is None:
                raise KeyError(f"approval not found for turn: {turn_id}")
            await session.commit()

    async def claim_waiting(self, turn_id: UUID) -> ApprovalRecord | None:
        """CAS: UPDATE … SET status='claimed' WHERE turn_id=? AND status='waiting'."""
        async with self._sf() as session:
            result = await session.execute(
                update(PendingApproval)
                .where(
                    PendingApproval.turn_id == turn_id,
                    PendingApproval.status == "waiting",
                )
                .values(status="claimed")
                .returning(PendingApproval)
            )
            row = result.scalar_one_or_none()
            if row is None:
                await session.rollback()
                return None
            await session.commit()
            trigger = await self._trigger_for(session, turn_id)
            return approval_orm_to_record(row, trigger_message_id=trigger)

    async def set_owner_message_id(self, turn_id: UUID, message_id: int) -> None:
        async with self._sf() as session:
            result = await session.execute(
                update(PendingApproval)
                .where(PendingApproval.turn_id == turn_id)
                .values(owner_message_id=message_id)
                .returning(PendingApproval.id)
            )
            if result.scalar_one_or_none() is None:
                raise KeyError(f"approval not found for turn: {turn_id}")
            await session.commit()

    async def update_draft(
        self,
        turn_id: UUID,
        *,
        draft_text: str,
        evaluation: dict | None = None,
        cognitive_summary: str | None = None,
    ) -> ApprovalRecord | None:
        """CAS: update only while status is ``waiting``. None if missing/raced."""
        values: dict = {"draft_text": draft_text}
        if evaluation is not None:
            values["evaluation"] = evaluation
        if cognitive_summary is not None:
            values["cognitive_summary"] = cognitive_summary
        async with self._sf() as session:
            result = await session.execute(
                update(PendingApproval)
                .where(
                    PendingApproval.turn_id == turn_id,
                    PendingApproval.status == "waiting",
                )
                .values(**values)
                .returning(PendingApproval)
            )
            row = result.scalar_one_or_none()
            if row is None:
                await session.rollback()
                return None
            await session.commit()
            trigger = await self._trigger_for(session, turn_id)
            return approval_orm_to_record(row, trigger_message_id=trigger)

    async def cancel_waiting_for_chat(self, chat_id: int) -> int:
        async with self._sf() as session:
            result = await session.execute(
                update(PendingApproval)
                .where(
                    PendingApproval.chat_id == chat_id,
                    PendingApproval.status.in_(tuple(OPEN_APPROVAL_STATUSES)),
                )
                .values(status="cancelled")
                .returning(PendingApproval.id)
            )
            ids = result.scalars().all()
            await session.commit()
            return len(ids)

    async def list_waiting(self) -> list[ApprovalRecord]:
        async with self._sf() as session:
            result = await session.execute(
                select(PendingApproval).where(PendingApproval.status == "waiting")
            )
            rows = result.scalars().all()
            out: list[ApprovalRecord] = []
            for row in rows:
                trigger = await self._trigger_for(session, row.turn_id)
                out.append(approval_orm_to_record(row, trigger_message_id=trigger))
            return out

    async def list_open(self) -> list[ApprovalRecord]:
        """Waiting + claimed (still in flight for recontact / route)."""
        async with self._sf() as session:
            result = await session.execute(
                select(PendingApproval).where(
                    PendingApproval.status.in_(tuple(OPEN_APPROVAL_STATUSES))
                )
            )
            rows = result.scalars().all()
            out: list[ApprovalRecord] = []
            for row in rows:
                trigger = await self._trigger_for(session, row.turn_id)
                out.append(approval_orm_to_record(row, trigger_message_id=trigger))
            return out

    async def delete_for_turn(self, turn_id: UUID) -> bool:
        """Delete the approval row for ``turn_id`` (clears unique slot for retry)."""
        async with self._sf() as session:
            result = await session.execute(
                delete(PendingApproval).where(PendingApproval.turn_id == turn_id)
            )
            await session.commit()
            return (result.rowcount or 0) > 0


__all__ = ["SqlPendingApprovalStore", "approval_orm_to_record"]
