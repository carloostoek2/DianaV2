"""E2E: sandbox isolation of metric/learning readers (migration 037).

``turns.is_sandbox`` is frozen at turn creation. Every reader that aggregates
metrics or feeds learning/calibration must exclude sandbox turns (and their
``pipeline_traces``); operational readers must still see them. Real Postgres
(marker ``db``); skipped offline.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from diana.application.outcome_log_service import OutcomeLogService
from diana.application.ports import TurnOutcomeLogRecord, TurnRecord
from diana.cognitive.decider import Decider
from diana.infrastructure.db.models import PipelineTrace
from diana.infrastructure.db.repositories.calibration_data import (
    SqlCalibrationDataSource,
)
from diana.infrastructure.db.repositories.metrics_data import SqlMetricsDataSource
from diana.infrastructure.db.repositories.traces import SqlTraceStore
from diana.infrastructure.db.repositories.turn_outcome import SqlTurnOutcomeLogRepo
from diana.infrastructure.db.repositories.turns import SqlTurnStore

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_EVAL = {
    "safety": 0.95,
    "doctrine": 0.95,
    "naturalness": 0.95,
    "relevance": 0.95,
    "coherence": 0.95,
}


async def _vip(session_factory, tg: int):
    from diana.infrastructure.db.repositories.vips import SqlVipStore

    return await SqlVipStore(session_factory).add(tg, display_name="Sandbox VIP")


async def _turn(session_factory, *, chat_id, vip_id, sandbox, status="delivered"):
    return await SqlTurnStore(session_factory).create(
        TurnRecord(
            id=uuid4(), chat_id=chat_id, status=status, vip_id=vip_id, is_sandbox=sandbox
        )
    )


async def _trace(session_factory, turn, *, generated_text=None, created_at=None, **cols):
    async with session_factory() as sess:
        sess.add(
            PipelineTrace(
                turn_id=turn.id,
                chat_id=turn.chat_id,
                vip_id=turn.vip_id,
                channel_type="vip",
                generated_text=generated_text,
                **({"created_at": created_at} if created_at is not None else {}),
                **cols,
            )
        )
        await sess.commit()


async def _set_created(session_factory, turn_id, when):
    async with session_factory() as session:
        await session.execute(
            text("UPDATE turns SET created_at = :w WHERE id = :t"), {"w": when, "t": turn_id}
        )
        await session.commit()


@pytest.mark.db
@pytest.mark.asyncio
async def test_turn_store_roundtrips_is_sandbox(session_factory) -> None:
    vip = await _vip(session_factory, 937001)
    real = await _turn(session_factory, chat_id=937001, vip_id=vip.id, sandbox=False)
    sb = await _turn(session_factory, chat_id=937001, vip_id=vip.id, sandbox=True)
    store = SqlTurnStore(session_factory)
    assert (await store.get(real.id)).is_sandbox is False
    assert (await store.get(sb.id)).is_sandbox is True


@pytest.mark.db
@pytest.mark.asyncio
async def test_count_messages_since_excludes_sandbox(session_factory) -> None:
    vip = await _vip(session_factory, 937002)
    await _turn(session_factory, chat_id=937002, vip_id=vip.id, sandbox=False)
    await _turn(session_factory, chat_id=937002, vip_id=vip.id, sandbox=True)
    await _turn(session_factory, chat_id=937002, vip_id=vip.id, sandbox=True)
    store = SqlTurnStore(session_factory)
    assert await store.count_messages_since(vip.id, since=None) == 1
    since = datetime.now(UTC) - timedelta(hours=1)
    assert await store.count_messages_since(vip.id, since=since) == 1


@pytest.mark.db
@pytest.mark.asyncio
async def test_scan_inactivity_mixed_real_and_sandbox(session_factory) -> None:
    """Last activity = newest REAL turn; a recent sandbox turn never refreshes it."""
    store = SqlTurnStore(session_factory)
    now = datetime.now(UTC)
    cut = now - timedelta(days=2)
    # A: old real turn + recent sandbox turn -> still inactive (sandbox ignored).
    a = await _vip(session_factory, 937003)
    a_real = await _turn(session_factory, chat_id=937003, vip_id=a.id, sandbox=False)
    await _set_created(session_factory, a_real.id, now - timedelta(days=5))
    await _turn(session_factory, chat_id=937003, vip_id=a.id, sandbox=True)
    # B: only sandbox turns (old) -> never listed (no real activity).
    b = await _vip(session_factory, 937004)
    b_sb = await _turn(session_factory, chat_id=937004, vip_id=b.id, sandbox=True)
    await _set_created(session_factory, b_sb.id, now - timedelta(days=5))
    # C: recent real turn -> active, not listed.
    c = await _vip(session_factory, 937005)
    await _turn(session_factory, chat_id=937005, vip_id=c.id, sandbox=False)

    rows = dict(await store.list_vips_with_activity_older_than(cut, limit=10_000))
    assert a.id in rows
    assert abs((rows[a.id] - (now - timedelta(days=5))).total_seconds()) < 5
    assert b.id not in rows
    assert c.id not in rows


@pytest.mark.db
@pytest.mark.asyncio
async def test_operational_readers_still_see_sandbox(session_factory) -> None:
    """list_non_terminal / latest_turn_id are operational: sandbox stays visible."""
    vip = await _vip(session_factory, 937006)
    sb = await _turn(
        session_factory, chat_id=937006, vip_id=vip.id, sandbox=True, status="deciding"
    )
    store = SqlTurnStore(session_factory)
    assert [t.id for t in await store.list_non_terminal(937006)] == [sb.id]
    assert await store.latest_turn_id(937006) == sb.id


@pytest.mark.db
@pytest.mark.asyncio
async def test_coincidence_summary_and_comparativas_exclude_sandbox(session_factory) -> None:
    vip = await _vip(session_factory, 937007)
    repo = SqlTurnOutcomeLogRepo(session_factory)
    service = OutcomeLogService(decider=Decider(feature_autonomous_mode=True), source=repo)
    comp = {"intent": "saludo", "emotion": "neutral"}
    before = (await service.coincidence_summary(window_days=1))["n"]

    real = await _turn(session_factory, chat_id=937007, vip_id=vip.id, sandbox=False)
    await _trace(session_factory, real, generated_text="hola", evaluation=_EVAL, comprehension=comp)
    sb = await _turn(session_factory, chat_id=937007, vip_id=vip.id, sandbox=True)
    await _trace(session_factory, sb, generated_text="hola", evaluation=_EVAL, comprehension=comp)

    ids = {r.turn_id for r in await service.list_comparativas(window_days=1, limit=10_000)}
    assert real.id in ids
    assert sb.id not in ids
    after = (await service.coincidence_summary(window_days=1, limit=10_000))["n"]
    assert after == before + 1


@pytest.mark.db
@pytest.mark.asyncio
async def test_pending_signal_readers_exclude_sandbox(session_factory) -> None:
    vip = await _vip(session_factory, 937008)
    repo = SqlTurnOutcomeLogRepo(session_factory)
    sb = await _turn(session_factory, chat_id=937008, vip_id=vip.id, sandbox=True)
    await repo.insert(
        TurnOutcomeLogRecord(turn_id=sb.id, vip_id=vip.id, shadow_verdict="send", draft_score=0.7)
    )
    since = datetime.now(UTC) - timedelta(hours=1)
    assert await repo.find_pending_signal_for_chat(937008, since=since) is None
    await _set_created(session_factory, sb.id, datetime.now(UTC) - timedelta(days=3))
    async with session_factory() as session:
        await session.execute(
            text("UPDATE turns SET updated_at = created_at WHERE id = :t"), {"t": sb.id}
        )
        await session.commit()
    pending = await repo.list_signal_pending(window_hours=1, limit=10_000)
    assert sb.id not in {p["turn_id"] for p in pending}

    real = await _turn(session_factory, chat_id=937008, vip_id=vip.id, sandbox=False)
    await repo.insert(
        TurnOutcomeLogRecord(turn_id=real.id, vip_id=vip.id, shadow_verdict="send", draft_score=0.7)
    )
    found = await repo.find_pending_signal_for_chat(937008, since=since)
    assert found is not None and found.turn_id == real.id


@pytest.mark.db
@pytest.mark.asyncio
async def test_sandbox_traces_excluded_from_metrics_and_calibration(session_factory) -> None:
    vip = await _vip(session_factory, 937009)
    real = await _turn(session_factory, chat_id=937009, vip_id=vip.id, sandbox=False)
    sb = await _turn(session_factory, chat_id=937009, vip_id=vip.id, sandbox=True)
    await _trace(session_factory, real, generated_text="texto-real-937009", evaluation=_EVAL,
                 decision={"action": "approve"})
    await _trace(session_factory, sb, generated_text="texto-sandbox-937009", evaluation=_EVAL,
                 decision={"action": "approve"})

    today = datetime.now(UTC).date()
    week = await SqlMetricsDataSource(session_factory).iter_week_traces(
        today - timedelta(days=1), today + timedelta(days=1)
    )
    week_ids = {str(r["turn_id"]) for r in week}
    assert str(real.id) in week_ids
    assert str(sb.id) not in week_ids

    calib = SqlCalibrationDataSource(session_factory)
    samples = await calib.list_evaluated_samples(window_days=1)
    sample_ids = {str(s.turn_id) for s in samples}
    assert str(real.id) in sample_ids
    assert str(sb.id) not in sample_ids
    texts = await calib.sample_generated_texts(since_days=1, limit=10_000)
    assert "texto-real-937009" in texts
    assert "texto-sandbox-937009" not in texts


@pytest.mark.db
@pytest.mark.asyncio
async def test_baseline_texts_exclude_sandbox(session_factory) -> None:
    """Oldest-window baseline never anchors on (or samples) a sandbox trace."""
    oldest = datetime(2000, 6, 1, tzinfo=UTC)
    vip = await _vip(session_factory, 937010)
    sb = await _turn(session_factory, chat_id=937010, vip_id=vip.id, sandbox=True)
    await _trace(session_factory, sb, generated_text="baseline-sandbox", created_at=oldest)
    real = await _turn(session_factory, chat_id=937010, vip_id=vip.id, sandbox=False)
    await _trace(session_factory, real, generated_text="baseline-real",
                 created_at=oldest + timedelta(days=1))
    texts = await SqlCalibrationDataSource(session_factory).sample_baseline_generated_texts(
        baseline_weeks=1, limit=10_000
    )
    assert "baseline-sandbox" not in texts
    assert "baseline-real" in texts


@pytest.mark.db
@pytest.mark.asyncio
async def test_chat_cognition_reads_same_sandbox_mode(session_factory) -> None:
    """Repetition guard / emotional baseline: real turns never see sandbox history."""
    vip = await _vip(session_factory, 937011)
    traces = SqlTraceStore(session_factory)
    real_old = await _turn(session_factory, chat_id=937011, vip_id=vip.id, sandbox=False)
    await _trace(session_factory, real_old, comprehension={"intent": "real_intent"})
    sb_old = await _turn(session_factory, chat_id=937011, vip_id=vip.id, sandbox=True)
    await _trace(session_factory, sb_old, comprehension={"intent": "sandbox_intent"})
    real_now = await _turn(session_factory, chat_id=937011, vip_id=vip.id, sandbox=False)
    sb_now = await _turn(session_factory, chat_id=937011, vip_id=vip.id, sandbox=True)

    assert await traces.get_recent_intents(937011, limit=5, exclude_turn_id=real_now.id) == [
        "real_intent"
    ]
    assert await traces.get_recent_intents(937011, limit=5, exclude_turn_id=sb_now.id) == [
        "sandbox_intent"
    ]
    comp = await traces.get_recent_comprehension(937011, limit=5, exclude_turn_id=real_now.id)
    assert [c.get("intent") for c in comp] == ["real_intent"]
    assert await traces.get_recent_intents(937011, limit=5) == ["real_intent"]


@pytest.mark.db
@pytest.mark.asyncio
async def test_staging_corrections_exclude_sandbox_turns(session_factory) -> None:
    """Synthesis feedback_signals never read corrections of sandbox turns."""
    from diana.infrastructure.db.repositories.staging import StagingCandidateRepo

    vip = await _vip(session_factory, 937012)
    repo = StagingCandidateRepo(session_factory)
    real = await _turn(session_factory, chat_id=937012, vip_id=vip.id, sandbox=False)
    sb = await _turn(session_factory, chat_id=937012, vip_id=vip.id, sandbox=True)
    payload = {"original_draft": "a", "corrected_text": "b", "context": {"turn_text": "c"}}
    await repo.insert("example", dict(payload, corrected_text="real"), real.id)
    await repo.insert("example", dict(payload, corrected_text="sandbox"), sb.id)
    rows = await repo.list_corrections_by_vip_since(vip.id, since=None)
    assert [r["payload"]["corrected_text"] for r in rows] == ["real"]


def _alembic(cmd: str, target: str, url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", cmd, target],
        cwd=str(PROJECT_ROOT), env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"alembic {cmd} {target}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.db
@pytest.mark.asyncio
async def test_037_upgrade_downgrade_upgrade(database_url: str) -> None:
    name = "diana_migration_037_test"
    maint = create_async_engine(database_url.rsplit("/", 1)[0] + "/postgres",
                                isolation_level="AUTOCOMMIT")
    async with maint.begin() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    db_url = database_url.rsplit("/", 1)[0] + f"/{name}"

    async def _col():
        eng = create_async_engine(db_url)
        try:
            async with eng.begin() as conn:
                return (await conn.execute(text(
                    "SELECT is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_name='turns' AND column_name='is_sandbox'"
                ))).first()
        finally:
            await eng.dispose()

    try:
        _alembic("upgrade", "036_correction_severity", db_url)
        eng = create_async_engine(db_url)
        async with eng.begin() as conn:
            await conn.execute(text("INSERT INTO turns (chat_id, status) VALUES (1, 'delivered')"))
        await eng.dispose()
        _alembic("upgrade", "037_turns_is_sandbox", db_url)
        col = await _col()
        assert col is not None and col[0] == "NO" and "false" in str(col[1])
        eng = create_async_engine(db_url)
        async with eng.begin() as conn:
            assert (await conn.execute(text("SELECT bool_or(is_sandbox) FROM turns"))).scalar() is False
        await eng.dispose()
        _alembic("downgrade", "036_correction_severity", db_url)
        assert await _col() is None
        _alembic("upgrade", "head", db_url)
        assert await _col() is not None
    finally:
        async with maint.begin() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await maint.dispose()
