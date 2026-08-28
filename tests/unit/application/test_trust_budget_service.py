"""TrustBudgetService — pure mechanics (no DB, no LLM, no aiogram)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
from diana.cognitive.models import EvaluationProfile

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


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
            score = min(1.0, max(0.0, float(initial) + float(delta)))
            record = VipTrustBudgetRecord(
                vip_id=vip_id,
                turn_category=turn_category,
                trust_score=score,
                autonomous_count=1,
            )
        else:
            score = min(1.0, max(0.0, current.trust_score + float(delta)))
            record = current.model_copy(
                update={"trust_score": score, "autonomous_count": current.autonomous_count + 1}
            )
        self.rows[key] = record
        return record

    async def decrement_correction(
        self, vip_id, turn_category, *, delta, initial, correction_time
    ):
        key = (vip_id, turn_category)
        current = self.rows.get(key)
        if current is None:
            score = min(1.0, max(0.0, float(initial) - float(delta)))
            record = VipTrustBudgetRecord(
                vip_id=vip_id,
                turn_category=turn_category,
                trust_score=score,
                correction_count=1,
                last_correction_at=correction_time,
            )
        else:
            score = min(1.0, max(0.0, current.trust_score - float(delta)))
            record = current.model_copy(
                update={
                    "trust_score": score,
                    "correction_count": current.correction_count + 1,
                    "last_correction_at": correction_time,
                }
            )
        self.rows[key] = record
        return record

    async def list_by_vip(self, vip_id):
        rows = [r for (vid, _cat), r in self.rows.items() if vid == vip_id]
        return sorted(rows, key=lambda r: r.turn_category)


class _FakeTurnCategoryLogReader:
    """In-memory turn_category_log reader keyed by turn_id."""

    def __init__(self, rows: dict | None = None) -> None:
        self.rows: dict = dict(rows or {})

    async def get_by_turn_id(self, turn_id):
        return self.rows.get(turn_id)


def _service(
    *,
    store: _MemoryVipTrustBudgetStore | None = None,
    cat_log: _FakeTurnCategoryLogReader | None = None,
    **kwargs,
) -> TrustBudgetService:
    return TrustBudgetService(
        store=store or _MemoryVipTrustBudgetStore(),
        turn_category_log=cat_log or _FakeTurnCategoryLogReader(),
        clock=lambda: NOW,
        **kwargs,
    )


def _profile(**overrides) -> EvaluationProfile:
    data = dict(
        naturalness=0.9,
        precision=0.9,
        doctrine=0.9,
        consistency=0.9,
        safety=0.95,
        coverage=0.9,
        empathy=0.9,
    )
    data.update(overrides)
    return EvaluationProfile(**data)


def _log_record(*, turn_id, vip_id, category="fatico", would_autonomous=True):
    return TurnCategoryLogRecord(
        turn_id=turn_id,
        vip_id=vip_id,
        chat_id=100,
        category=category,
        would_autonomous=would_autonomous,
    )


# --- increments / clamp ------------------------------------------------------


@pytest.mark.asyncio
async def test_increment_creates_row_with_initial_plus_delta() -> None:
    store = _MemoryVipTrustBudgetStore()
    svc = _service(store=store)
    vip = uuid4()

    rec = await svc.record_autonomous(vip, "fatico")

    assert rec.trust_score == pytest.approx(0.25)  # 0.2 + 0.05
    assert rec.autonomous_count == 1
    assert rec.correction_count == 0


@pytest.mark.asyncio
async def test_repeated_increments_clamp_to_1() -> None:
    store = _MemoryVipTrustBudgetStore()
    svc = _service(store=store, increment=0.4)
    vip = uuid4()

    for _ in range(4):
        await svc.record_autonomous(vip, "fatico")

    rec = await store.get_by_vip_and_category(vip, "fatico")
    assert rec is not None
    assert rec.trust_score == pytest.approx(1.0)  # clamped, not 1.8
    assert rec.autonomous_count == 4


# --- correction event --------------------------------------------------------


@pytest.mark.asyncio
async def test_record_correction_resolves_by_turn_id_and_decrements() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    cat_log = _FakeTurnCategoryLogReader(
        {turn_id: _log_record(turn_id=turn_id, vip_id=vip, category="informativo")}
    )
    svc = _service(store=store, cat_log=cat_log)
    await svc.record_autonomous(vip, "informativo")

    rec = await svc.record_correction(turn_id)

    assert rec is not None
    assert rec.turn_category == "informativo"
    assert rec.correction_count == 1
    assert rec.last_correction_at == NOW
    assert rec.trust_score == pytest.approx(0.25 - 0.2)  # 0.25 then -0.2


@pytest.mark.asyncio
async def test_record_correction_noop_when_turn_not_classified() -> None:
    store = _MemoryVipTrustBudgetStore()
    svc = _service(store=store, cat_log=_FakeTurnCategoryLogReader())

    rec = await svc.record_correction(uuid4())

    assert rec is None
    assert store.rows == {}


@pytest.mark.asyncio
async def test_record_correction_noop_when_vip_none() -> None:
    store = _MemoryVipTrustBudgetStore()
    turn_id = uuid4()
    cat_log = _FakeTurnCategoryLogReader(
        {turn_id: _log_record(turn_id=turn_id, vip_id=None, category="fatico")}
    )
    svc = _service(store=store, cat_log=cat_log)

    rec = await svc.record_correction(turn_id)

    assert rec is None
    assert store.rows == {}


@pytest.mark.asyncio
async def test_record_correction_noop_when_turn_was_supervised() -> None:
    """S2: a supervised turn (``would_autonomous`` False/None) never increments,
    so a correction on it must not seed a 0.0 row with an inflated count."""
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    cat_log = _FakeTurnCategoryLogReader(
        {
            turn_id: _log_record(
                turn_id=turn_id, vip_id=vip, category="informativo",
                would_autonomous=False,
            )
        }
    )
    svc = _service(store=store, cat_log=cat_log)

    rec = await svc.record_correction(turn_id)

    assert rec is None
    assert store.rows == {}


# --- asymmetry + clamp to 0 ---------------------------------------------------


@pytest.mark.asyncio
async def test_asymmetry_decrement_outweighs_increment() -> None:
    """1 autonomous (+0.05) then 1 correction (-0.2) → net below initial."""
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    cat_log = _FakeTurnCategoryLogReader(
        {turn_id: _log_record(turn_id=turn_id, vip_id=vip)}
    )
    svc = _service(store=store, cat_log=cat_log)

    await svc.record_autonomous(vip, "fatico")
    await svc.record_correction(turn_id)

    rec = await store.get_by_vip_and_category(vip, "fatico")
    assert rec is not None
    assert rec.trust_score == pytest.approx(0.25 - 0.2)
    assert rec.trust_score < 0.2  # initial


@pytest.mark.asyncio
async def test_cascade_decrements_clamp_to_0() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    cat_log = _FakeTurnCategoryLogReader()
    svc = _service(store=store, cat_log=cat_log, decrement=0.5)
    await svc.record_autonomous(vip, "fatico")

    # Direct corrections via the store event with a pre-existing row.
    for _ in range(3):
        await store.decrement_correction(
            vip, "fatico", delta=0.5, initial=0.2, correction_time=NOW
        )

    rec = await store.get_by_vip_and_category(vip, "fatico")
    assert rec is not None
    assert rec.trust_score == pytest.approx(0.0)  # clamped, not negative
    assert rec.correction_count == 3


@pytest.mark.asyncio
async def test_cascade_clamp_to_0_through_record_correction() -> None:
    """S10: the clamp propagates through the SERVICE event (record_correction),
    not just the store fake — a regression in the service's delta propagation
    would surface here."""
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turns = [uuid4() for _ in range(3)]
    cat_log = _FakeTurnCategoryLogReader(
        {t: _log_record(turn_id=t, vip_id=vip, category="fatico") for t in turns}
    )
    svc = _service(store=store, cat_log=cat_log, decrement=0.5)
    await svc.record_autonomous(vip, "fatico")  # 0.2 + 0.05 = 0.25

    for t in turns:
        await svc.record_correction(t)  # 0.25 → 0.0 after the first -0.5

    rec = await store.get_by_vip_and_category(vip, "fatico")
    assert rec is not None
    assert rec.trust_score == pytest.approx(0.0)  # clamped, not negative
    assert rec.correction_count == 3


# --- double gate --------------------------------------------------------------


@pytest.mark.asyncio
async def test_can_autonomous_no_row_is_false() -> None:
    svc = _service()
    assert await svc.can_autonomous(uuid4(), "fatico") is False


@pytest.mark.asyncio
async def test_can_autonomous_threshold_gate() -> None:
    store = _MemoryVipTrustBudgetStore()
    svc = _service(store=store, threshold=0.5)
    vip = uuid4()
    await store.increment_autonomous(vip, "fatico", delta=0.4, initial=0.2)  # 0.6

    assert await svc.can_autonomous(vip, "fatico") is True

    await store.decrement_correction(vip, "fatico", delta=0.3, initial=0.2, correction_time=NOW)  # 0.3
    assert await svc.can_autonomous(vip, "fatico") is False


@pytest.mark.asyncio
async def test_can_autonomous_per_category_override() -> None:
    store = _MemoryVipTrustBudgetStore()
    svc = _service(
        store=store,
        threshold=0.9,
        thresholds_by_category={"fatico": 0.3, "emocional": 0.8},
    )
    vip = uuid4()
    await store.increment_autonomous(vip, "fatico", delta=0.1, initial=0.2)  # 0.3
    await store.increment_autonomous(vip, "emocional", delta=0.2, initial=0.2)  # 0.4

    # fatico threshold overridden down to 0.3 → passes; emocional 0.4 < 0.8 → not.
    assert await svc.can_autonomous(vip, "fatico") is True
    assert await svc.can_autonomous(vip, "emocional") is False


@pytest.mark.asyncio
async def test_would_autonomous_with_trust_double_condition() -> None:
    store = _MemoryVipTrustBudgetStore()
    svc = _service(store=store, threshold=0.5, dispersion_high=0.25)
    vip = uuid4()
    await store.increment_autonomous(vip, "fatico", delta=0.4, initial=0.2)  # 0.6

    assert await svc.would_autonomous_with_trust(vip, "fatico", _profile()) is True
    # Low trust → False even with low dispersion.
    await store.decrement_correction(vip, "fatico", delta=0.5, initial=0.2, correction_time=NOW)  # 0.1
    assert await svc.would_autonomous_with_trust(vip, "fatico", _profile()) is False
    # High dispersion → False even with high trust.
    await store.increment_autonomous(vip, "fatico", delta=0.5, initial=0.2)  # 0.6
    scattered = _profile(naturalness=0.1, doctrine=0.9, empathy=0.2, precision=0.9)
    assert await svc.would_autonomous_with_trust(vip, "fatico", scattered) is False
    # No evaluation → the dispersion gate is skipped (trust alone decides).
    assert await svc.would_autonomous_with_trust(vip, "fatico", None) is True


def test_dispersion_ok_threshold() -> None:
    svc = _service(dispersion_high=0.25)
    assert svc.dispersion_ok(_profile()) is True          # uniform → std 0
    scattered = _profile(naturalness=0.1, doctrine=0.9, empathy=0.2)
    assert svc.dispersion_ok(scattered) is False
    assert svc.dispersion_ok(None) is True


# --- apply_overrides ----------------------------------------------------------


def test_apply_overrides_changes_thresholds_and_deltas() -> None:
    svc = _service()
    svc.apply_overrides(
        {
            "initial": 0.1,
            "increment": 0.2,
            "decrement": 0.3,
            "threshold": 0.6,
            "dispersion_high": 0.5,
            "trend_window_days": 7,
            "thresholds": {"fatico": 0.4},
        }
    )
    assert svc._initial == 0.1  # noqa: SLF001
    assert svc._increment == 0.2  # noqa: SLF001
    assert svc._decrement == 0.3  # noqa: SLF001
    assert svc._threshold == 0.6  # noqa: SLF001
    assert svc._dispersion_high == 0.5  # noqa: SLF001
    assert svc._trend_window_days == 7  # noqa: SLF001
    assert svc.get_threshold("fatico") == 0.4
    assert svc.get_threshold("emocional") == 0.6


def test_apply_overrides_invalid_and_absent_are_ignored() -> None:
    svc = _service()
    svc.apply_overrides(
        {
            "initial": "bogus",
            "threshold": 1.5,  # out of range
            "decrement": -0.1,  # out of range
            "trend_window_days": 0,  # invalid window
            "thresholds": {"fatico": "x", "emocional": 2.0},
        }
    )
    # Defaults untouched; nothing crashed.
    assert svc._initial == 0.2  # noqa: SLF001
    assert svc._threshold == 0.9  # noqa: SLF001
    assert svc._decrement == 0.2  # noqa: SLF001
    assert svc._trend_window_days == 14  # noqa: SLF001
    assert svc.get_threshold("fatico") == 0.9
    assert svc.get_threshold("emocional") == 0.9

    svc.apply_overrides(None)  # type: ignore[arg-type]
    assert svc._initial == 0.2  # noqa: SLF001


def test_apply_overrides_rejects_asymmetry_inversion() -> None:
    """S7: a manual override that would invert the conservative asymmetry
    (decrement > increment) is rejected as a whole — nothing is applied."""
    svc = _service()
    svc.apply_overrides(
        {"increment": 0.5, "decrement": 0.1, "threshold": 0.4}
    )
    # Asymmetry inverted → the WHOLE config is dropped (threshold too).
    assert svc._increment == 0.05  # noqa: SLF001
    assert svc._decrement == 0.2  # noqa: SLF001
    assert svc._threshold == 0.9  # noqa: SLF001

    # An equal pair is also rejected (must be STRICTLY decrement > increment).
    svc.apply_overrides({"increment": 0.2, "decrement": 0.2})
    assert svc._increment == 0.05  # noqa: SLF001
    assert svc._decrement == 0.2  # noqa: SLF001

    # A valid conservative pair still applies.
    svc.apply_overrides({"increment": 0.1, "decrement": 0.4})
    assert svc._increment == 0.1  # noqa: SLF001
    assert svc._decrement == 0.4  # noqa: SLF001


# --- trend --------------------------------------------------------------------


def _trust_record(*, trust_score=0.5, autonomous_count=0, correction_count=0,
                  last_correction_at=None) -> VipTrustBudgetRecord:
    return VipTrustBudgetRecord(
        vip_id=uuid4(),
        turn_category="fatico",
        trust_score=trust_score,
        autonomous_count=autonomous_count,
        correction_count=correction_count,
        last_correction_at=last_correction_at,
    )


def test_trend_down_when_recent_correction() -> None:
    svc = _service(trend_window_days=14)
    recent = NOW - timedelta(days=2)
    rec = _trust_record(autonomous_count=3, correction_count=1, last_correction_at=recent)
    assert svc.trend_for(rec, now=NOW) == "down"


def test_trend_up_when_autonomous_without_recent_correction() -> None:
    svc = _service(trend_window_days=14)
    # Old correction (outside the window) + autonomous runs → up.
    old = NOW - timedelta(days=20)
    rec = _trust_record(autonomous_count=3, correction_count=1, last_correction_at=old)
    assert svc.trend_for(rec, now=NOW) == "up"
    # Autonomous without any correction → up.
    assert svc.trend_for(_trust_record(autonomous_count=1), now=NOW) == "up"


def test_trend_flat_when_no_data() -> None:
    svc = _service()
    assert svc.trend_for(_trust_record(), now=NOW) == "flat"


def test_trend_custom_window() -> None:
    svc = _service(trend_window_days=14)
    correction = NOW - timedelta(days=10)
    rec = _trust_record(autonomous_count=1, correction_count=1, last_correction_at=correction)
    # 10 days old is inside the default 14-day window → down.
    assert svc.trend_for(rec, now=NOW) == "down"
    # With a 5-day window the same correction is no longer recent → up.
    assert svc.trend_for(rec, now=NOW, window_days=5) == "up"


def test_trend_up_requires_positive_score() -> None:
    """S4: an autonomous with the score punished back to 0.0 (corrections
    dominated) is NOT "up" — a VIP with 1 old autonomous + score 0.0 must not
    show "▲ up" forever."""
    svc = _service(trend_window_days=14)
    rec = _trust_record(autonomous_count=1, trust_score=0.0)
    assert svc.trend_for(rec, now=NOW) == "flat"
    # A positive score still trends up (positive trust exists).
    assert svc.trend_for(_trust_record(autonomous_count=1, trust_score=0.01), now=NOW) == "up"


def test_trend_future_correction_is_ignored() -> None:
    """Clock-skew robustness: a last_correction_at in the future must not report
    "down" forever — the windowed check ignores future stamps."""
    svc = _service(trend_window_days=14)
    future = NOW + timedelta(days=1)
    rec = _trust_record(autonomous_count=1, correction_count=1, last_correction_at=future)
    assert svc.trend_for(rec, now=NOW) == "up"
    # With no autonomous history the future stamp also cannot claim "down".
    rec2 = _trust_record(correction_count=1, last_correction_at=future)
    assert svc.trend_for(rec2, now=NOW) == "flat"


def test_trend_window_zero_clamps_to_minimum() -> None:
    """window_days <= 0 clamps to a 1-day minimum instead of silently falling
    back to the instance default."""
    svc = _service(trend_window_days=14)
    correction = NOW - timedelta(days=10)
    rec = _trust_record(autonomous_count=1, correction_count=1, last_correction_at=correction)
    # 10 days is beyond even the 1-day clamped window → not "down".
    assert svc.trend_for(rec, now=NOW, window_days=0) == "up"
    assert svc.trend_for(rec, now=NOW, window_days=-3) == "up"


# --- ficha --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_ficha_shape() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    cat_log = _FakeTurnCategoryLogReader(
        {turn_id: _log_record(turn_id=turn_id, vip_id=vip, category="fatico")}
    )
    svc = _service(store=store, cat_log=cat_log)
    await svc.record_autonomous(vip, "fatico")
    await svc.record_autonomous(vip, "informativo")
    await svc.record_correction(turn_id)

    rows = await svc.list_for_ficha(vip)

    assert len(rows) == 2
    by_cat = {r["category"]: r for r in rows}
    fatico = by_cat["fatico"]
    assert set(fatico) == {
        "category", "trust_score", "autonomous_count",
        "correction_count", "last_correction_at", "trend",
    }
    assert fatico["trust_score"] == pytest.approx(0.25 - 0.2)
    assert fatico["autonomous_count"] == 1
    assert fatico["correction_count"] == 1
    assert fatico["last_correction_at"] == NOW.isoformat()
    assert fatico["trend"] == "down"
    assert by_cat["informativo"]["trend"] == "up"
    # list_by_vip is ordered by category.
    assert [r["category"] for r in rows] == ["fatico", "informativo"]


# --- SPEC-EA-07: severity-graded decrement ------------------------------------


def _severity_service(
    store: _MemoryVipTrustBudgetStore | None = None,
    cat_log: _FakeTurnCategoryLogReader | None = None,
    **kwargs,
) -> TrustBudgetService:
    kwargs.setdefault(
        "decrement_by_severity", dict(DEFAULT_TRUST_BUDGET_DECREMENT_BY_SEVERITY)
    )
    return _service(store=store, cat_log=cat_log, **kwargs)


@pytest.mark.asyncio
async def test_default_moderate_is_parity_flag_off() -> None:
    """Flag OFF + default severity → the classic -0.20 (byte-identical)."""
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    cat_log = _FakeTurnCategoryLogReader(
        {turn_id: _log_record(turn_id=turn_id, vip_id=vip, category="informativo")}
    )
    svc = _severity_service(store=store, cat_log=cat_log)
    await svc.record_autonomous(vip, "informativo")  # 0.25

    rec = await svc.record_correction(turn_id)  # default severity=moderate

    assert rec is not None
    assert rec.trust_score == pytest.approx(0.25 - 0.2)


@pytest.mark.asyncio
async def test_flag_off_severity_major_is_byte_identical_with_shadow(caplog) -> None:
    """Regla de oro: flag OFF → severity="major" still applies 0.20, and the
    hypothetical 0.35 is only logged (metadata shadow, never touches the score)."""
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    cat_log = _FakeTurnCategoryLogReader(
        {turn_id: _log_record(turn_id=turn_id, vip_id=vip, category="informativo")}
    )
    svc = _severity_service(store=store, cat_log=cat_log)  # flag OFF (default)
    await svc.record_autonomous(vip, "informativo")  # 0.25

    with caplog.at_level(logging.INFO, logger="diana.application"):
        rec = await svc.record_correction(turn_id, severity="major")

    assert rec is not None
    assert rec.trust_score == pytest.approx(0.25 - 0.2)  # NOT 0.25 - 0.35
    shadow = [
        r for r in caplog.records
        if r.message == "trust_severity_shadow" and r.severity == "major"
    ]
    assert shadow, "shadow log missing for severity != default with flag OFF"
    assert shadow[0].applied_delta == pytest.approx(0.2)
    assert shadow[0].hypothetical_delta == pytest.approx(0.35)


@pytest.mark.asyncio
async def test_flag_off_moderate_does_not_log_shadow(caplog) -> None:
    """Default severity (moderate) is the byte-identical path → no shadow noise."""
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    cat_log = _FakeTurnCategoryLogReader(
        {turn_id: _log_record(turn_id=turn_id, vip_id=vip)}
    )
    svc = _severity_service(store=store, cat_log=cat_log)

    with caplog.at_level(logging.INFO, logger="diana.application"):
        await svc.record_correction(turn_id, severity="moderate")

    assert not [r for r in caplog.records if r.message == "trust_severity_shadow"]


@pytest.mark.asyncio
async def test_flag_on_applies_severity_table() -> None:
    """Flag ON → each severity applies its own delta. Distinct VIP per severity
    (isolated rows) with a 0.7 baseline so no delta clamps to 0."""
    expected = {"minor": 0.08, "moderate": 0.20, "major": 0.35}
    store = _MemoryVipTrustBudgetStore()
    for severity, delta in expected.items():
        vip = uuid4()
        turn_id = uuid4()
        cat_log = _FakeTurnCategoryLogReader(
            {turn_id: _log_record(turn_id=turn_id, vip_id=vip, category="informativo")}
        )
        svc = _severity_service(
            store=store, cat_log=cat_log, severity_decrement_enabled=True
        )
        await store.increment_autonomous(
            vip, "informativo", delta=0.5, initial=0.2
        )  # baseline 0.7
        rec = await svc.record_correction(turn_id, severity=severity)
        assert rec is not None
        assert rec.trust_score == pytest.approx(0.7 - delta)


@pytest.mark.asyncio
async def test_flag_on_unknown_severity_falls_back_to_decrement() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    turn_id = uuid4()
    cat_log = _FakeTurnCategoryLogReader(
        {turn_id: _log_record(turn_id=turn_id, vip_id=vip)}
    )
    svc = _severity_service(store=store, cat_log=cat_log, severity_decrement_enabled=True)
    await svc.record_autonomous(vip, "fatico")  # 0.25

    rec = await svc.record_correction(turn_id, severity="critical")

    assert rec is not None
    assert rec.trust_score == pytest.approx(0.25 - 0.2)


def test_severity_table_constructor_clamped_to_unit_interval() -> None:
    svc = _severity_service(
        decrement_by_severity={"minor": -1.0, "moderate": 2.0, "major": 0.5}
    )
    assert svc._decrement_by_severity["minor"] == pytest.approx(0.0)  # noqa: SLF001
    assert svc._decrement_by_severity["moderate"] == pytest.approx(1.0)  # noqa: SLF001
    assert svc._decrement_by_severity["major"] == pytest.approx(0.5)  # noqa: SLF001


def test_decrement_for_flag_off_is_always_decrement() -> None:
    """The single switch: flag OFF returns self._decrement for ANY severity."""
    svc = _severity_service()
    assert svc._decrement_for("minor") == pytest.approx(0.2)  # noqa: SLF001
    assert svc._decrement_for("moderate") == pytest.approx(0.2)  # noqa: SLF001
    assert svc._decrement_for("major") == pytest.approx(0.2)  # noqa: SLF001
    assert svc._decrement_for("bogus") == pytest.approx(0.2)  # noqa: SLF001


def test_apply_overrides_severity_rejects_minor_le_increment() -> None:
    """Minor <= increment inverts the conservative asymmetry → whole config dropped."""
    svc = _severity_service()
    svc.apply_overrides(
        {
            "increment": 0.1,
            "decrement_by_severity": {"minor": 0.1, "moderate": 0.2, "major": 0.3},
        }
    )
    # minor == increment → rejected; nothing (not even increment) applied.
    assert svc._increment == 0.05  # noqa: SLF001
    assert svc._decrement_by_severity["minor"] == pytest.approx(0.08)  # noqa: SLF001


def test_apply_overrides_severity_rejects_non_monotonic() -> None:
    svc = _severity_service()
    svc.apply_overrides(
        {
            "decrement_by_severity": {"minor": 0.2, "moderate": 0.1, "major": 0.3},
        }
    )
    # major >= moderate >= minor violated (moderate < minor) → whole config dropped.
    assert svc._decrement_by_severity["minor"] == pytest.approx(0.08)  # noqa: SLF001
    assert svc._decrement_by_severity["moderate"] == pytest.approx(0.20)  # noqa: SLF001

    svc.apply_overrides(
        {
            "decrement_by_severity": {"minor": 0.2, "moderate": 0.3, "major": 0.1},
        }
    )
    # major < moderate → rejected too.
    assert svc._decrement_by_severity["major"] == pytest.approx(0.35)  # noqa: SLF001


def test_apply_overrides_severity_rejects_out_of_range() -> None:
    svc = _severity_service()
    svc.apply_overrides(
        {
            "decrement_by_severity": {"minor": 0.1, "moderate": 0.2, "major": 1.5},
        }
    )
    # major out of [0,1] → REJECT (not clamped), whole config dropped.
    assert svc._decrement_by_severity["major"] == pytest.approx(0.35)  # noqa: SLF001


def test_apply_overrides_severity_accepts_valid_table() -> None:
    svc = _severity_service()
    svc.apply_overrides(
        {
            "decrement_by_severity": {"minor": 0.1, "moderate": 0.3, "major": 0.5},
        }
    )
    assert svc._decrement_by_severity["minor"] == pytest.approx(0.1)  # noqa: SLF001
    assert svc._decrement_by_severity["moderate"] == pytest.approx(0.3)  # noqa: SLF001
    assert svc._decrement_by_severity["major"] == pytest.approx(0.5)  # noqa: SLF001


# --- import purity ------------------------------------------------------------


def test_import_purity() -> None:
    from diana.application import trust_budget_service

    text = Path(trust_budget_service.__file__).read_text(encoding="utf-8")
    for token in ("aiogram", "infrastructure", "telegram", "sqlalchemy", "diana.llm"):
        assert token not in text, token
