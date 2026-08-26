"""Approval ORM mapping carries photo_file_id (image vision, migration 035)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from diana.infrastructure.db.repositories.approvals import (
    approval_orm_to_record,
)


def _row(**overrides) -> SimpleNamespace:
    base = dict(
        id=uuid4(),
        turn_id=uuid4(),
        chat_id=42,
        business_connection_id="bc",
        draft_text="draft",
        status="waiting",
        vip_id=None,
        cognitive_summary=None,
        evaluation=None,
        owner_message_id=None,
        photo_file_id=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_orm_to_record_carries_photo_file_id() -> None:
    record = approval_orm_to_record(_row(photo_file_id="big"))
    assert record.photo_file_id == "big"


def test_orm_to_record_defaults_photo_to_none() -> None:
    record = approval_orm_to_record(_row(photo_file_id=None))
    assert record.photo_file_id is None
