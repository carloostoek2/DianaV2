"""E2E: SqlVipTrustBudgetRepo atomic deltas + list_by_vip on real Postgres.

The Fase 5 trust budget updates are the ONLY writers of ``vip_trust_budget``:
``increment_autonomous`` (event: autonomous without correction) and
``decrement_correction`` (event: owner correction). Both must be ATOMIC SQL
updates (no read-modify-write race between concurrent correction/autonomous
events) with a server-side clamp to [0, 1]. This suite verifies the real SQL
on Postgres, plus ``get_by_turn_id`` resolution on ``turn_category_log``.

Requires Docker/testcontainers (marker ``db``); skipped offline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from diana.application.ports import TurnCategoryLogRecord, TurnRecord
from diana.infrastructure.db.repositories.turn_category import (
    SqlTurnCategoryLogRepo,
)
from diana.infrastructure.db.repositories.turns import SqlTurnStore
from diana.infrastructure.db.repositories.vip_trust_budget import (
    SqlVipTrustBudgetRepo,
)


async def _create_vip(session_factory, telegram_user_id: int):
    from diana.infrastructure.db.repositories.vips import SqlVipStore

    vip_store = SqlVipStore(session_factory)
    return await vip_store.add(telegram_user_id, display_name="Trust VIP")


def _now() -> datetime:
    return datetime.now(UTC)


@pytest.mark.db
@pytest.mark.asyncio
async def test_increment_creates_row_with_clamped_seed(session_factory) -> None:
    repo = SqlVipTrustBudgetRepo(session_factory)
    vip = await _create_vip(session_factory, 9501)

    first = await repo.increment_autonomous(vip.id, "fatico", delta=0.05, initial=0.2)
    assert first.trust_score == pytest.approx(0.25)
    assert first.autonomous_count == 1
    assert first.correction_count == 0

    second = await repo.increment_autonomous(vip.id, "fatico", delta=0.05, initial=0.2)
    assert second.trust_score == pytest.approx(0.3)
    assert second.autonomous_count == 2

    # Overload clamps server-side.
    top = await repo.increment_autonomous(vip.id, "fatico", delta=9.0, initial=0.2)
    assert top.trust_score == pytest.approx(1.0)


@pytest.mark.db
@pytest.mark.asyncio
async def test_decrement_on_existing_row(session_factory) -> None:
    repo = SqlVipTrustBudgetRepo(session_factory)
    vip = await _create_vip(session_factory, 9502)

    await repo.increment_autonomous(vip.id, "informativo", delta=0.05, initial=0.2)
    corrected = await repo.decrement_correction(
        vip.id,
        "informativo",
        delta=0.2,
        initial=0.2,
        correction_time=_now(),
    )
    assert corrected.trust_score == pytest.approx(0.25 - 0.2)
    assert corrected.correction_count == 1
    assert corrected.last_correction_at is not None

    # Cascade decay clamps at 0 (never negative).
    for _ in range(3):
        corrected = await repo.decrement_correction(
            vip.id,
            "informativo",
            delta=0.2,
            initial=0.2,
            correction_time=_now(),
        )
    assert corrected.trust_score == pytest.approx(0.0)
    assert corrected.correction_count == 4


@pytest.mark.db
@pytest.mark.asyncio
async def test_decrement_insert_branch_seeds_corrected(session_factory) -> None:
    """A correction with no prior autonomous row seeds clamp(initial - delta)."""
    repo = SqlVipTrustBudgetRepo(session_factory)
    vip = await _create_vip(session_factory, 9503)

    rec = await repo.decrement_correction(
        vip.id, "emocional", delta=0.2, initial=0.2, correction_time=_now()
    )
    assert rec.trust_score == pytest.approx(0.0)
    assert rec.correction_count == 1


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_by_vip_ordered_by_category(session_factory) -> None:
    repo = SqlVipTrustBudgetRepo(session_factory)
    vip = await _create_vip(session_factory, 9504)

    for cat in ("informativo", "fatico", "emocional"):
        await repo.increment_autonomous(vip.id, cat, delta=0.05, initial=0.2)

    rows = await repo.list_by_vip(vip.id)
    assert [r.turn_category for r in rows] == ["emocional", "fatico", "informativo"]
    assert all(r.vip_id == vip.id for r in rows)


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_by_turn_id_resolves_classification(session_factory) -> None:
    repo = SqlTurnCategoryLogRepo(session_factory)
    vip = await _create_vip(session_factory, 9505)
    turn_id = uuid4()

    # turn_category_log.turn_id FK -> turns.id: create the real turn row first.
    await SqlTurnStore(session_factory).create(
        TurnRecord(id=turn_id, chat_id=100, status="received", vip_id=vip.id)
    )

    await repo.insert(
        TurnCategoryLogRecord(
            turn_id=turn_id,
            vip_id=vip.id,
            chat_id=100,
            category="fatico",
            would_autonomous=True,
        )
    )

    found = await repo.get_by_turn_id(turn_id)
    assert found is not None
    assert found.turn_id == turn_id
    assert found.vip_id == vip.id
    assert found.category == "fatico"
    assert found.would_autonomous is True
    assert await repo.get_by_turn_id(uuid4()) is None
