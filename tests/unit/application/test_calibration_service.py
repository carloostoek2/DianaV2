"""CalibrationService unit tests — fakes only (no DB / no ST model)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from diana.application.calibration_service import (
    CalibrationReport,
    CalibrationSample,
    CalibrationService,
)
from diana.cognitive.thresholds import (
    DEFAULT_AUTONOMOUS_THRESHOLDS,
    DEFAULT_SUPERVISED_THRESHOLDS,
)


class FakeClock:
    def __init__(self, now: datetime | None = None) -> None:
        self._now = now or datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self._now


class FakeTraceSource:
    def __init__(self, samples: list[CalibrationSample] | None = None) -> None:
        self.samples = list(samples or [])
        self.last_window_days: int | None = None

    async def list_evaluated_samples(self, *, window_days: int) -> list[CalibrationSample]:
        self.last_window_days = window_days
        return list(self.samples)


class FakeConfigStore:
    def __init__(
        self,
        *,
        supervised: dict[str, float] | None = None,
        autonomous: dict[str, float] | None = None,
        calibration: dict[str, Any] | None = None,
    ) -> None:
        self.supervised = dict(supervised or {})
        self.autonomous = dict(autonomous or {})
        self.calibration = dict(calibration or {})
        self.kv: dict[str, object] = {}
        self.sets: list[tuple[str, object]] = []
        self.set_auto_calls: list[dict] = []
        self.set_sup_calls: list[dict] = []

    async def get_autonomous_thresholds(self) -> dict:
        return dict(self.autonomous)

    async def get_supervised_thresholds(self) -> dict:
        return dict(self.supervised)

    async def get_calibration_config(self) -> dict:
        return dict(self.calibration)

    async def set_autonomous_thresholds(self, value: dict) -> None:
        self.autonomous = dict(value)
        self.set_auto_calls.append(dict(value))

    async def set_supervised_thresholds(self, value: dict) -> None:
        self.supervised = dict(value)
        self.set_sup_calls.append(dict(value))

    async def get(self, key: str) -> object | None:
        if key in self.kv:
            return self.kv[key]
        if key == "autonomous_thresholds":
            return dict(self.autonomous) if self.autonomous else None
        if key == "supervised_thresholds":
            return dict(self.supervised) if self.supervised else None
        if key == "calibration":
            return dict(self.calibration) if self.calibration else None
        return None

    async def set(self, key: str, value: object) -> None:
        self.sets.append((key, value))
        self.kv[key] = value
        if key == "calibration":
            assert isinstance(value, dict)
            self.calibration = dict(value)
        elif key == "autonomous_thresholds" and isinstance(value, dict):
            self.autonomous = dict(value)
        elif key == "supervised_thresholds" and isinstance(value, dict):
            self.supervised = dict(value)


class FakeEmbedder:
    """Map text → fixed-size vector (bag-of-char hash style)."""

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.calls: list[str] = []
        self._overrides: dict[str, list[float]] = {}

    def override(self, text: str, vector: list[float]) -> None:
        self._overrides[text] = list(vector)

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        if text in self._overrides:
            return list(self._overrides[text])
        # deterministic pseudo-embedding from character codes
        vec = [0.0] * self.dim
        for i, ch in enumerate(text.encode("utf-8")):
            vec[i % self.dim] += float(ch) / 255.0
        return vec


class FakeDriftTexts:
    def __init__(
        self,
        *,
        recent: list[str] | None = None,
        baseline: list[str] | None = None,
    ) -> None:
        self.recent = list(recent or [])
        self.baseline = list(baseline or [])

    async def sample_generated_texts(self, *, since_days: int, limit: int) -> list[str]:
        return list(self.recent)[:limit]

    async def sample_baseline_generated_texts(
        self, *, baseline_weeks: int, limit: int
    ) -> list[str]:
        return list(self.baseline)[:limit]


class FakeNotifier:
    def __init__(self) -> None:
        self.infos: list[str] = []

    async def notify_draft(self, payload: object) -> int | None:
        return None

    async def notify_escalation(self, payload: object) -> None:
        return None

    async def notify_info(self, text: str, *, chat_id: int | None = None) -> None:
        self.infos.append(text)

    async def notify_doctrine(self, payload: object) -> int | None:
        return None


def _sample(
    *,
    safety: float,
    doctrine: float,
    naturalness: float,
    corrected: bool,
) -> CalibrationSample:
    return CalibrationSample(
        turn_id=uuid4(),
        safety=safety,
        doctrine=doctrine,
        naturalness=naturalness,
        corrected=corrected,
    )


def _many_samples(
    n: int,
    *,
    n_corrected: int,
    base: float = 0.6,
) -> list[CalibrationSample]:
    """Build n samples; first n_corrected are corrected with varying scores."""
    out: list[CalibrationSample] = []
    for i in range(n):
        corrected = i < n_corrected
        # spread corrected scores so percentiles are meaningful
        offset = (i % 10) * 0.02 if corrected else 0.0
        out.append(
            _sample(
                safety=min(1.0, base + offset),
                doctrine=min(1.0, base + offset - 0.05),
                naturalness=min(1.0, base + offset - 0.1),
                corrected=corrected,
            )
        )
    return out


def _build_service(
    *,
    enabled: bool = True,
    traces: FakeTraceSource | None = None,
    config: FakeConfigStore | None = None,
    embeddings: FakeEmbedder | None = None,
    drift_texts: FakeDriftTexts | None = None,
    notifier: FakeNotifier | None = None,
    clock: FakeClock | None = None,
) -> tuple[CalibrationService, FakeTraceSource, FakeConfigStore, FakeEmbedder, FakeDriftTexts]:
    t = traces or FakeTraceSource()
    c = config or FakeConfigStore()
    e = embeddings or FakeEmbedder()
    d = drift_texts or FakeDriftTexts()
    svc = CalibrationService(
        feature_calibration_enabled=enabled,
        traces=t,
        config=c,
        embeddings=e,
        drift_texts=d,
        notifier=notifier,
        clock=clock or FakeClock(),
    )
    return svc, t, c, e, d


# ---------------------------------------------------------------------------
# calibrate_thresholds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calibrate_disabled_no_writes() -> None:
    samples = _many_samples(60, n_corrected=20)
    svc, _, cfg, _, _ = _build_service(
        enabled=False, traces=FakeTraceSource(samples)
    )
    report = await svc.calibrate_thresholds()
    assert report.status == "disabled"
    assert report.n_samples == 0
    assert cfg.set_auto_calls == []
    assert cfg.set_sup_calls == []
    assert cfg.sets == []


@pytest.mark.asyncio
async def test_calibrate_insufficient_samples_no_writes() -> None:
    # default min_samples=50; provide 10
    samples = _many_samples(10, n_corrected=5)
    svc, _, cfg, _, _ = _build_service(traces=FakeTraceSource(samples))
    report = await svc.calibrate_thresholds()
    assert report.status == "insufficient_samples"
    assert report.n_samples == 10
    assert report.n_corrected == 5
    assert cfg.set_auto_calls == []
    assert cfg.set_sup_calls == []


@pytest.mark.asyncio
async def test_calibrate_no_corrections_keeps_previous() -> None:
    samples = _many_samples(60, n_corrected=0)
    prev_sup = dict(DEFAULT_SUPERVISED_THRESHOLDS)
    prev_auto = dict(DEFAULT_AUTONOMOUS_THRESHOLDS)
    cfg = FakeConfigStore(supervised=prev_sup, autonomous=prev_auto)
    svc, _, cfg, _, _ = _build_service(
        traces=FakeTraceSource(samples), config=cfg
    )
    report = await svc.calibrate_thresholds()
    assert report.status == "no_corrections"
    assert report.n_samples == 60
    assert report.n_corrected == 0
    assert cfg.set_auto_calls == []
    assert cfg.set_sup_calls == []


@pytest.mark.asyncio
async def test_calibrate_happy_path_margin_and_keys() -> None:
    samples = _many_samples(60, n_corrected=25, base=0.5)
    prev_sup = {
        "safety_min": 0.5,
        "doctrine_min": 0.4,
        "naturalness_min": 0.5,
    }
    prev_auto = {
        "safety_min": 0.9,
        "doctrine_min": 0.8,
        "naturalness_min": 0.7,
    }
    cfg = FakeConfigStore(supervised=prev_sup, autonomous=prev_auto)
    svc, _, cfg, _, _ = _build_service(
        traces=FakeTraceSource(samples), config=cfg
    )
    report = await svc.calibrate_thresholds()
    assert report.status == "ok"
    assert report.n_samples == 60
    assert report.n_corrected == 25
    assert report.margin == pytest.approx(0.05)
    assert report.supervised is not None
    assert report.autonomous is not None
    keys = {"safety_min", "doctrine_min", "naturalness_min"}
    assert set(report.supervised) == keys
    assert set(report.autonomous) == keys
    assert len(cfg.set_sup_calls) == 1
    assert len(cfg.set_auto_calls) == 1
    assert set(cfg.set_sup_calls[0]) == keys
    assert set(cfg.set_auto_calls[0]) == keys
    for dim in keys:
        assert cfg.set_auto_calls[0][dim] >= cfg.set_sup_calls[0][dim] + 0.05 - 1e-9


@pytest.mark.asyncio
async def test_calibrate_smoothing_uses_previous() -> None:
    """With fixed corrected scores, smooth blends previous store values."""
    # All corrected samples share the same scores → raw percentiles = that score
    samples = [
        _sample(safety=0.8, doctrine=0.8, naturalness=0.8, corrected=True)
        for _ in range(55)
    ]
    prev_sup = {
        "safety_min": 0.4,
        "doctrine_min": 0.4,
        "naturalness_min": 0.4,
    }
    prev_auto = {
        "safety_min": 0.6,
        "doctrine_min": 0.6,
        "naturalness_min": 0.6,
    }
    cfg = FakeConfigStore(supervised=prev_sup, autonomous=prev_auto)
    svc, _, cfg, _, _ = _build_service(
        traces=FakeTraceSource(samples), config=cfg
    )
    report = await svc.calibrate_thresholds()
    assert report.status == "ok"
    assert report.supervised is not None
    # raw_sup = 0.8 (p70 of constants), smooth: 0.5*0.4 + 0.5*0.8 = 0.6
    # raw_auto = 0.8 (p90), then margin max(0.8, 0.8+0.05)=0.85
    # smooth auto: 0.5*0.6 + 0.5*0.85 = 0.725 — then margin re-check after smooth
    assert report.supervised["safety_min"] == pytest.approx(0.6)
    # After smooth, margin re-enforced: auto >= sup + 0.05
    assert report.autonomous is not None
    assert report.autonomous["safety_min"] >= report.supervised["safety_min"] + 0.05 - 1e-9


@pytest.mark.asyncio
async def test_calibrate_writes_audit_last_run() -> None:
    samples = _many_samples(55, n_corrected=15)
    clock = FakeClock(datetime(2026, 7, 26, 15, 30, 0, tzinfo=UTC))
    svc, _, cfg, _, _ = _build_service(
        traces=FakeTraceSource(samples), clock=clock
    )
    report = await svc.calibrate_thresholds(window_days=14)
    assert report.status == "ok"
    audit_keys = [k for k, _ in cfg.sets if k == "calibration.last_run"]
    assert len(audit_keys) == 1
    payload = next(v for k, v in cfg.sets if k == "calibration.last_run")
    assert isinstance(payload, dict)
    assert payload["window_days"] == 14
    assert payload["n_samples"] == 55
    assert payload["n_corrected"] == 15
    assert "supervised" in payload
    assert "autonomous" in payload
    assert "ts" in payload


@pytest.mark.asyncio
async def test_calibrate_window_days_override_passed_to_source() -> None:
    samples = _many_samples(55, n_corrected=10)
    traces = FakeTraceSource(samples)
    svc, traces, _, _, _ = _build_service(traces=traces)
    await svc.calibrate_thresholds(window_days=21)
    assert traces.last_window_days == 21


@pytest.mark.asyncio
async def test_calibrate_uses_config_min_samples_and_margin() -> None:
    samples = _many_samples(20, n_corrected=8)
    cfg = FakeConfigStore(
        calibration={"min_samples": 20, "autonomous_margin_min": 0.1}
    )
    svc, _, cfg, _, _ = _build_service(
        traces=FakeTraceSource(samples), config=cfg
    )
    report = await svc.calibrate_thresholds()
    assert report.status == "ok"
    assert report.margin == pytest.approx(0.1)
    assert report.autonomous is not None and report.supervised is not None
    for dim in ("safety_min", "doctrine_min", "naturalness_min"):
        assert report.autonomous[dim] >= report.supervised[dim] + 0.1 - 1e-9


@pytest.mark.asyncio
async def test_calibrate_missing_previous_uses_defaults() -> None:
    samples = [
        _sample(safety=0.7, doctrine=0.7, naturalness=0.7, corrected=True)
        for _ in range(50)
    ]
    cfg = FakeConfigStore()  # empty previous
    svc, _, cfg, _, _ = _build_service(
        traces=FakeTraceSource(samples), config=cfg
    )
    report = await svc.calibrate_thresholds()
    assert report.status == "ok"
    # Smooth against pure defaults — values should be finite dual keys
    assert report.supervised is not None
    assert set(report.supervised) == {
        "safety_min",
        "doctrine_min",
        "naturalness_min",
    }


# ---------------------------------------------------------------------------
# detect_drift
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_drift_runs_when_calibration_flag_disabled() -> None:
    """Flag gates calibrate_thresholds only; detect_drift stays readable (A2)."""
    texts = ["hola estilo natural"]
    base = ["hola estilo base"]
    emb = FakeEmbedder(dim=8)
    emb.override(texts[0], [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    emb.override(base[0], [0.99, 0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    svc, _, _, emb, _ = _build_service(
        enabled=False,
        embeddings=emb,
        drift_texts=FakeDriftTexts(recent=texts, baseline=base),
        notifier=None,
    )
    result = await svc.detect_drift()
    assert "style_drift_score" in result
    assert emb.calls  # embeddings used even when flag false


@pytest.mark.asyncio
async def test_detect_drift_no_alert_when_flag_disabled() -> None:
    """Owner drift alerts only fire when calibration flag is on (A6)."""
    emb = FakeEmbedder(dim=2)
    emb.override("r1", [1.0, 0.0])
    emb.override("b1", [0.0, 1.0])
    notifier = FakeNotifier()
    cfg = FakeConfigStore(calibration={"drift_alert_threshold": 0.1})
    svc, _, _, _, _ = _build_service(
        enabled=False,
        embeddings=emb,
        config=cfg,
        drift_texts=FakeDriftTexts(recent=["r1"], baseline=["b1"]),
        notifier=notifier,
    )
    result = await svc.detect_drift()
    assert result["style_drift_score"] > 0.1
    assert notifier.infos == []


@pytest.mark.asyncio
async def test_detect_drift_empty_texts_zero_score() -> None:
    svc, _, _, emb, _ = _build_service(
        drift_texts=FakeDriftTexts(recent=[], baseline=[])
    )
    result = await svc.detect_drift()
    assert result["style_drift_score"] == pytest.approx(0.0)
    assert emb.calls == []


@pytest.mark.asyncio
async def test_detect_drift_similar_texts_low_score() -> None:
    texts = ["hola mundo estilo natural", "hola mundo estilo natural x"]
    emb = FakeEmbedder(dim=8)
    # force nearly identical embeddings
    emb.override(texts[0], [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    emb.override(texts[1], [0.99, 0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    # baseline same family
    base = ["hola mundo base uno", "hola mundo base dos"]
    emb.override(base[0], [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    emb.override(base[1], [0.98, 0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    svc, _, _, emb, _ = _build_service(
        embeddings=emb,
        drift_texts=FakeDriftTexts(recent=texts, baseline=base),
    )
    result = await svc.detect_drift()
    assert result["style_drift_score"] < 0.1


@pytest.mark.asyncio
async def test_detect_drift_dissimilar_texts_high_score() -> None:
    emb = FakeEmbedder(dim=4)
    recent = ["aaa", "bbb"]
    base = ["xxx", "yyy"]
    emb.override("aaa", [1.0, 0.0, 0.0, 0.0])
    emb.override("bbb", [1.0, 0.0, 0.0, 0.0])
    emb.override("xxx", [0.0, 1.0, 0.0, 0.0])
    emb.override("yyy", [0.0, 1.0, 0.0, 0.0])
    svc, _, _, emb, _ = _build_service(
        embeddings=emb,
        drift_texts=FakeDriftTexts(recent=recent, baseline=base),
    )
    result = await svc.detect_drift()
    assert result["style_drift_score"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_detect_drift_notifies_when_above_threshold() -> None:
    emb = FakeEmbedder(dim=2)
    emb.override("r1", [1.0, 0.0])
    emb.override("b1", [0.0, 1.0])
    notifier = FakeNotifier()
    cfg = FakeConfigStore(calibration={"drift_alert_threshold": 0.1})
    # Provide cached baseline so we don't require 384-dim baseline seed path only
    svc, _, cfg, emb, _ = _build_service(
        embeddings=emb,
        config=cfg,
        drift_texts=FakeDriftTexts(recent=["r1"], baseline=["b1"]),
        notifier=notifier,
    )
    result = await svc.detect_drift()
    assert result["style_drift_score"] > 0.1
    assert len(notifier.infos) == 1
    assert "deriva" in notifier.infos[0].lower() or "estilo" in notifier.infos[0].lower()


@pytest.mark.asyncio
async def test_detect_drift_no_notify_without_notifier() -> None:
    emb = FakeEmbedder(dim=2)
    emb.override("r1", [1.0, 0.0])
    emb.override("b1", [0.0, 1.0])
    svc, _, _, emb, _ = _build_service(
        embeddings=emb,
        drift_texts=FakeDriftTexts(recent=["r1"], baseline=["b1"]),
        notifier=None,
    )
    result = await svc.detect_drift()
    assert result["style_drift_score"] > 0.1


@pytest.mark.asyncio
async def test_detect_drift_uses_cached_baseline_embedding() -> None:
    emb = FakeEmbedder(dim=4)
    emb.override("r1", [1.0, 0.0, 0.0, 0.0])
    # cache baseline orthogonal
    cfg = FakeConfigStore(
        calibration={
            "style_baseline_embedding": [0.0, 1.0, 0.0, 0.0],
        }
    )
    drift = FakeDriftTexts(recent=["r1"], baseline=["should_not_use"])
    svc, _, cfg, emb, _ = _build_service(
        embeddings=emb, config=cfg, drift_texts=drift
    )
    result = await svc.detect_drift()
    assert result["style_drift_score"] == pytest.approx(1.0)
    # baseline texts should not be embedded when cache hit (dim match)
    assert "should_not_use" not in emb.calls


@pytest.mark.asyncio
async def test_detect_drift_freezes_baseline_on_first_compute() -> None:
    emb = FakeEmbedder(dim=4)
    emb.override("r1", [1.0, 0.0, 0.0, 0.0])
    emb.override("b1", [1.0, 0.0, 0.0, 0.0])
    cfg = FakeConfigStore()
    svc, _, cfg, emb, _ = _build_service(
        embeddings=emb,
        config=cfg,
        drift_texts=FakeDriftTexts(recent=["r1"], baseline=["b1"]),
    )
    await svc.detect_drift()
    baseline_writes = [
        v for k, v in cfg.sets if k == "calibration.style_baseline_embedding"
    ]
    assert len(baseline_writes) == 1
    assert isinstance(baseline_writes[0], list)
    assert len(baseline_writes[0]) == 4


@pytest.mark.asyncio
async def test_calibrate_report_type() -> None:
    svc, _, _, _, _ = _build_service(enabled=False)
    report = await svc.calibrate_thresholds()
    assert isinstance(report, CalibrationReport)
