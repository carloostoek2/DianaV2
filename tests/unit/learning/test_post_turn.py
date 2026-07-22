"""LearningService: TRACE_KEYS completeness only; no Staging."""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.application.memory import InMemoryTraceReaderWriter
from diana.cognitive.ports import TRACE_KEYS
from diana.learning.post_turn import LearningService, PostTurnReport


@pytest.mark.asyncio
async def test_complete_when_all_trace_keys_present() -> None:
    traces = InMemoryTraceReaderWriter()
    tid = uuid4()
    traces.seed_keys(tid, TRACE_KEYS)
    svc = LearningService(traces)
    report = await svc.run_post_turn(tid)
    assert isinstance(report, PostTurnReport)
    assert report.complete is True
    assert report.missing == []


@pytest.mark.asyncio
async def test_missing_keys_reported_no_crash() -> None:
    traces = InMemoryTraceReaderWriter()
    tid = uuid4()
    await traces.store(tid, "comprehension", {})
    await traces.store(tid, "plan", {})
    svc = LearningService(traces)
    report = await svc.run_post_turn(tid)
    assert report.complete is False
    assert "decision" in report.missing
    assert "comprehension" not in report.missing


@pytest.mark.asyncio
async def test_no_staging_side_effects() -> None:
    traces = InMemoryTraceReaderWriter()
    tid = uuid4()
    traces.seed_keys(tid, TRACE_KEYS)
    svc = LearningService(traces)
    await svc.run_post_turn(tid)
    # Learning must not grow any staging-like attributes
    assert not hasattr(svc, "staging")
    assert not hasattr(svc, "candidates")
