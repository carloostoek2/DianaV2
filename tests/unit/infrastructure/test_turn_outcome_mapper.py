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


def test_insert_on_conflict_preserves_owner_and_first_shadow() -> None:
    """Source pin: upsert must COALESCE owner/reaction and keep first shadow.

    Live bug: post-approve finally re-inserts with NULL owner defaults and can
    flip shadow_verdict. The ON CONFLICT SET list is the SQL root fix; e2e
    exercises it on real Postgres when Docker is available.
    """
    import inspect

    from diana.infrastructure.db.repositories.turn_outcome import (
        SqlTurnOutcomeLogRepo,
    )

    source = inspect.getsource(SqlTurnOutcomeLogRepo.insert)
    assert "on_conflict_do_update(" in source
    assert "func.coalesce(" in source
    for col in (
        "owner_outcome",
        "sent_score",
        "quality_delta",
        "correction_severity",
        "vip_signal",
    ):
        assert f"TurnOutcomeLog.{col}" in source, col
        assert f'"{col}": record.{col}' not in source, col
    # First shadow decision sticks (table column, not excluded/record).
    assert '"shadow_verdict": TurnOutcomeLog.shadow_verdict' in source
    assert '"shadow_reason": TurnOutcomeLog.shadow_reason' in source
    assert '"shadow_verdict": record.shadow_verdict' not in source


def test_upsert_conflict_sql_uses_coalesce_for_owner_cols() -> None:
    """Compile mirror of the ON CONFLICT SET list (no live Postgres needed)."""
    from uuid import uuid4

    from sqlalchemy import func
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.dialects.postgresql import insert

    from diana.infrastructure.db.models import TurnOutcomeLog

    insert_stmt = insert(TurnOutcomeLog).values(
        turn_id=uuid4(),
        vip_id=uuid4(),
        shadow_verdict="send",
        shadow_reason="ok",
        owner_outcome=None,
        draft_score=0.7,
        sent_score=None,
        quality_delta=None,
        blocked_dims=None,
        vip_signal=None,
        correction_severity=None,
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[TurnOutcomeLog.turn_id],
        set_={
            "shadow_verdict": TurnOutcomeLog.shadow_verdict,
            "shadow_reason": TurnOutcomeLog.shadow_reason,
            "draft_score": func.coalesce(
                TurnOutcomeLog.draft_score, insert_stmt.excluded.draft_score
            ),
            "blocked_dims": func.coalesce(
                TurnOutcomeLog.blocked_dims, insert_stmt.excluded.blocked_dims
            ),
            "owner_outcome": func.coalesce(
                TurnOutcomeLog.owner_outcome, insert_stmt.excluded.owner_outcome
            ),
            "sent_score": func.coalesce(
                TurnOutcomeLog.sent_score, insert_stmt.excluded.sent_score
            ),
            "quality_delta": func.coalesce(
                TurnOutcomeLog.quality_delta, insert_stmt.excluded.quality_delta
            ),
            "vip_signal": func.coalesce(
                TurnOutcomeLog.vip_signal, insert_stmt.excluded.vip_signal
            ),
            "correction_severity": func.coalesce(
                TurnOutcomeLog.correction_severity,
                insert_stmt.excluded.correction_severity,
            ),
            "updated_at": func.now(),
        },
    )
    sql = str(stmt.compile(dialect=postgresql.dialect())).upper()
    assert "ON CONFLICT" in sql
    assert "COALESCE(TURN_OUTCOME_LOG.OWNER_OUTCOME" in sql
    assert "COALESCE(TURN_OUTCOME_LOG.SENT_SCORE" in sql
    assert "COALESCE(TURN_OUTCOME_LOG.QUALITY_DELTA" in sql
    assert "COALESCE(TURN_OUTCOME_LOG.CORRECTION_SEVERITY" in sql
    assert "COALESCE(TURN_OUTCOME_LOG.VIP_SIGNAL" in sql
    # shadow_verdict kept from existing row (no excluded overwrite).
    assert "SHADOW_VERDICT = TURN_OUTCOME_LOG.SHADOW_VERDICT" in sql
