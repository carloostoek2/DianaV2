"""E2E: SqlCalibrationDataSource VIP-only sampling against real PostgreSQL.

REQ-ATN-13 anti-contamination: calibration/drift must read ONLY
``channel_type='vip'`` traces. Every reader (list_evaluated_samples,
sample_generated_texts, sample_baseline_generated_texts) must exclude
atencion-originated traces.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.application.ports import TurnRecord
from diana.infrastructure.db.models import PipelineTrace
from diana.infrastructure.db.repositories.calibration_data import (
    SqlCalibrationDataSource,
)
from diana.infrastructure.db.repositories.turns import SqlTurnStore

_VIP_TEXT = "vip-generated-sample"
_ATENCION_TEXT = "atencion-generated-sample"


async def _insert_turn_and_trace(
    session_factory,
    *,
    chat_id: int,
    channel_type: str,
    generated_text: str | None = None,
    evaluation: dict | None = None,
) -> object:
    """Create a real turn + pipeline_trace row for the given channel."""
    store = SqlTurnStore(session_factory)
    turn = await store.create(
        TurnRecord(id=uuid4(), chat_id=chat_id, status="received", channel_type=channel_type)
    )
    async with session_factory() as sess:
        sess.add(
            PipelineTrace(
                turn_id=turn.id,
                chat_id=chat_id,
                channel_type=channel_type,
                generated_text=generated_text,
                evaluation=evaluation,
            )
        )
        await sess.commit()
    return turn


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_evaluated_samples_filters_vip_only(session_factory) -> None:
    """REQ-ATN-13: only VIP evaluated traces reach calibration samples."""
    vip = await _insert_turn_and_trace(
        session_factory,
        chat_id=101,
        channel_type="vip",
        evaluation={"safety": 0.9, "doctrine": 0.9, "naturalness": 0.9},
    )
    await _insert_turn_and_trace(
        session_factory,
        chat_id=102,
        channel_type="atencion",
        evaluation={"safety": 0.8, "doctrine": 0.8, "naturalness": 0.8},
    )

    source = SqlCalibrationDataSource(session_factory)
    samples = await source.list_evaluated_samples(window_days=30)

    turn_ids = {str(s.turn_id) for s in samples}
    assert str(vip.id) in turn_ids


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_evaluated_samples_excludes_atencion_turn_id(session_factory) -> None:
    """REQ-ATN-13: the specific atencion turn id never appears as a sample."""
    atencion = await _insert_turn_and_trace(
        session_factory,
        chat_id=103,
        channel_type="atencion",
        evaluation={"safety": 0.8, "doctrine": 0.8, "naturalness": 0.8},
    )
    await _insert_turn_and_trace(
        session_factory,
        chat_id=104,
        channel_type="vip",
        evaluation={"safety": 0.9, "doctrine": 0.9, "naturalness": 0.9},
    )

    source = SqlCalibrationDataSource(session_factory)
    samples = await source.list_evaluated_samples(window_days=30)
    assert str(atencion.id) not in {str(s.turn_id) for s in samples}


@pytest.mark.db
@pytest.mark.asyncio
async def test_sample_generated_texts_filters_vip_only(session_factory) -> None:
    """REQ-ATN-13: drift text sampling never includes atencion text."""
    await _insert_turn_and_trace(
        session_factory,
        chat_id=105,
        channel_type="vip",
        generated_text=_VIP_TEXT,
    )
    await _insert_turn_and_trace(
        session_factory,
        chat_id=106,
        channel_type="atencion",
        generated_text=_ATENCION_TEXT,
    )

    source = SqlCalibrationDataSource(session_factory)
    texts = await source.sample_generated_texts(since_days=30, limit=5000)

    assert _VIP_TEXT in texts
    assert _ATENCION_TEXT not in texts


@pytest.mark.db
@pytest.mark.asyncio
async def test_sample_baseline_generated_texts_filters_vip_only(session_factory) -> None:
    """REQ-ATN-13: baseline drift window also reads VIP traces only."""
    await _insert_turn_and_trace(
        session_factory,
        chat_id=107,
        channel_type="vip",
        generated_text=_VIP_TEXT,
    )
    await _insert_turn_and_trace(
        session_factory,
        chat_id=108,
        channel_type="atencion",
        generated_text=_ATENCION_TEXT,
    )

    source = SqlCalibrationDataSource(session_factory)
    texts = await source.sample_baseline_generated_texts(baseline_weeks=4, limit=5000)

    assert _VIP_TEXT in texts
    assert _ATENCION_TEXT not in texts
