"""TurnOutcomeLog ORM mapping carries correction_severity (SPEC-EA-07, 036)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from diana.infrastructure.db.repositories.turn_outcome import (
    turn_outcome_orm_to_record,
)


def _row(**overrides) -> SimpleNamespace:
    base = dict(
        id=uuid4(),
        turn_id=uuid4(),
        vip_id=uuid4(),
        shadow_verdict="send",
        shadow_reason=None,
        owner_outcome=None,
        draft_score=0.7,
        sent_score=None,
        quality_delta=None,
        blocked_dims=None,
        vip_signal=None,
        correction_severity=None,
        created_at=datetime(2026, 8, 28, tzinfo=UTC),
        updated_at=datetime(2026, 8, 28, tzinfo=UTC),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_orm_to_record_carries_correction_severity() -> None:
    record = turn_outcome_orm_to_record(_row(correction_severity="major"))
    assert record.correction_severity == "major"


def test_orm_to_record_defaults_severity_to_none() -> None:
    record = turn_outcome_orm_to_record(_row(correction_severity=None))
    assert record.correction_severity is None
