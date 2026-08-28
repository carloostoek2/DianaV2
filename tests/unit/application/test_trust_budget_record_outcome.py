"""TrustBudgetService.record_outcome — Fila 4 outcome-driven adjustments."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from diana.application.ports import (
    TurnCategoryLogRecord,
    VipTrustBudgetRecord,
)
from diana.application.trust_budget_service import (
    DEFAULT_TRUST_BUDGET_DECREMENT_BY_SEVERITY,
    TrustBudgetService,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class _MemoryVipTrustBudgetStore:
    """In-memory store replicating the SQL repo semantics (clamp + counters)."""

    def __init__(self) -> None:
        self.rows: dict[tuple, VipTrustBudgetRecord] = {}

    async def get_by_vip_and_category(self, vip_id, turn_category):
        return self.rows.get((vip_id, turn_category))

    async def increment_autonomous(self, vip_id, turn_category, *, delta, initial):
        key = (vip_id, turn_category)
        current = self.rows.get(key)
        if current is None:
            record = VipTrustBudgetRecord(
                vip_id=vip_id,
                turn_category=turn_category,
                trust_score=min(1.0, max(0.0, float(initial) + float(delta))),
                autonomous_count=1,
            )
        else:
            record = current.model_copy(
                update={
                    "trust_score": min(1.0, max(0.0, current.trust_score + float(delta))),
                    "autonomous_count": current.autonomous_count + 1,
                }
            )
        self.rows[key] = record
        return record

    async def decrement_correction(
        self, vip_id, turn_category, *, delta, initial, correction_time
    ):
        key = (vip_id, turn_category)
        current = self.rows.get(key)
        if current is None:
            record = VipTrustBudgetRecord(
                vip_id=vip_id,
                turn_category=turn_category,
                trust_score=min(1.0, max(0.0, float(initial) - float(delta))),
                correction_count=1,
                last_correction_at=correction_time,
            )
        else:
            record = current.model_copy(
                update={
                    "trust_score": min(1.0, max(0.0, current.trust_score - float(delta))),
                    "correction_count": current.correction_count + 1,
                    "last_correction_at": correction_time,
                }
            )
        self.rows[key] = record
        return record

    async def list_by_vip(self, vip_id):
        return [r for (vid, _cat), r in self.rows.items() if vid == vip_id]


class _FakeTurnCategoryLogReader:
    def __init__(self, rows: dict | None = None) -> None:
        self.rows: dict = dict(rows or {})

    async def get_by_turn_id(self, turn_id):
        return self.rows.get(turn_id)


def _log_record(*, turn_id, vip_id, category="informativo"):
    return TurnCategoryLogRecord(
        turn_id=turn_id,
        vip_id=vip_id,
        chat_id=100,
        category=category,
        would_autonomous=True,
    )


def _service(store, cat_log, **kwargs) -> TrustBudgetService:
    return TrustBudgetService(
        store=store,
        turn_category_log=cat_log,
        clock=lambda: NOW,
        decrement_by_severity=dict(DEFAULT_TRUST_BUDGET_DECREMENT_BY_SEVERITY),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_label_desacuerdo_decrements() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    svc = _service(
        store,
        _FakeTurnCategoryLogReader({turn_id: _log_record(turn_id=turn_id, vip_id=vip)}),
    )
    await svc.record_autonomous(vip, "informativo")  # 0.25

    rec = await svc.record_outcome(turn_id, event="label", value="desacuerdo")

    assert rec is not None
    assert rec.trust_score == pytest.approx(0.25 - 0.2)
    assert rec.correction_count == 1
    assert rec.last_correction_at == NOW


@pytest.mark.asyncio
async def test_label_acierto_increments() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    svc = _service(
        store,
        _FakeTurnCategoryLogReader({turn_id: _log_record(turn_id=turn_id, vip_id=vip)}),
    )

    rec = await svc.record_outcome(turn_id, event="label", value="acierto")

    assert rec is not None
    assert rec.trust_score == pytest.approx(0.2 + 0.05)
    assert rec.autonomous_count == 1
    assert rec.correction_count == 0


@pytest.mark.asyncio
async def test_label_conservadora_no_change() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    svc = _service(
        store,
        _FakeTurnCategoryLogReader({turn_id: _log_record(turn_id=turn_id, vip_id=vip)}),
    )
    await svc.record_autonomous(vip, "informativo")  # 0.25

    rec = await svc.record_outcome(turn_id, event="label", value="conservadora")

    assert rec is None
    assert store.rows[(vip, "informativo")].trust_score == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_signal_negative_decrements() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    svc = _service(
        store,
        _FakeTurnCategoryLogReader({turn_id: _log_record(turn_id=turn_id, vip_id=vip)}),
    )
    await svc.record_autonomous(vip, "informativo")  # 0.25

    rec = await svc.record_outcome(turn_id, event="signal", value="negative")

    assert rec is not None
    assert rec.trust_score == pytest.approx(0.25 - 0.2)


@pytest.mark.asyncio
async def test_signal_positive_increments() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    svc = _service(
        store,
        _FakeTurnCategoryLogReader({turn_id: _log_record(turn_id=turn_id, vip_id=vip)}),
    )

    rec = await svc.record_outcome(turn_id, event="signal", value="positive")

    assert rec is not None
    assert rec.trust_score == pytest.approx(0.25)
    assert rec.autonomous_count == 1


@pytest.mark.asyncio
async def test_signal_neutral_and_silence_no_change() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    svc = _service(
        store,
        _FakeTurnCategoryLogReader({turn_id: _log_record(turn_id=turn_id, vip_id=vip)}),
    )

    assert await svc.record_outcome(turn_id, event="signal", value="neutral") is None
    assert await svc.record_outcome(turn_id, event="signal", value="silence") is None
    assert store.rows == {}


@pytest.mark.asyncio
async def test_unclassified_turn_noop() -> None:
    store = _MemoryVipTrustBudgetStore()
    svc = _service(store, _FakeTurnCategoryLogReader())

    rec = await svc.record_outcome(uuid4(), event="label", value="desacuerdo")

    assert rec is None
    assert store.rows == {}


# --- SPEC-EA-07: severity through record_outcome -------------------------------


@pytest.mark.asyncio
async def test_label_desacuerdo_major_flag_on_decrements_035() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    svc = _service(
        store,
        _FakeTurnCategoryLogReader({turn_id: _log_record(turn_id=turn_id, vip_id=vip)}),
        severity_decrement_enabled=True,
    )
    await store.increment_autonomous(vip, "informativo", delta=0.5, initial=0.2)  # 0.7

    rec = await svc.record_outcome(
        turn_id, event="label", value="desacuerdo", severity="major"
    )

    assert rec is not None
    assert rec.trust_score == pytest.approx(0.7 - 0.35)


@pytest.mark.asyncio
async def test_label_desacuerdo_major_flag_off_is_020_with_shadow(caplog) -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    svc = _service(
        store,
        _FakeTurnCategoryLogReader({turn_id: _log_record(turn_id=turn_id, vip_id=vip)}),
    )  # flag OFF (default)
    await svc.record_autonomous(vip, "informativo")  # 0.25

    with caplog.at_level(logging.INFO, logger="diana.application"):
        rec = await svc.record_outcome(
            turn_id, event="label", value="desacuerdo", severity="major"
        )

    assert rec is not None
    assert rec.trust_score == pytest.approx(0.25 - 0.2)  # NOT 0.25 - 0.35
    shadow = [r for r in caplog.records if r.message == "trust_severity_shadow"]
    assert shadow, "shadow log missing for severity != default with flag OFF"
    assert shadow[0].hypothetical_delta == pytest.approx(0.35)


@pytest.mark.asyncio
async def test_signal_negative_minor_flag_on_decrements_008() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    svc = _service(
        store,
        _FakeTurnCategoryLogReader({turn_id: _log_record(turn_id=turn_id, vip_id=vip)}),
        severity_decrement_enabled=True,
    )
    await store.increment_autonomous(vip, "informativo", delta=0.5, initial=0.2)  # 0.7

    rec = await svc.record_outcome(
        turn_id, event="signal", value="negative", severity="minor"
    )

    assert rec is not None
    assert rec.trust_score == pytest.approx(0.7 - 0.08)
