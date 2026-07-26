"""CalibrationService — post-hoc dual-threshold calibration + style drift (jobs only).

Never invoked from the turn pipeline (AGENTS.md). Flag-gated; composition may
always construct the service.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from diana.application.calibration_math import (
    THRESHOLD_DIMS,
    clamp01,
    enforce_margin,
    mean_vector,
    percentile_linear,
    smooth_thresholds,
    style_drift_score,
)
from diana.application.ports import OwnerNotifierPort
from diana.cognitive.thresholds import (
    DEFAULT_AUTONOMOUS_THRESHOLDS,
    DEFAULT_SUPERVISED_THRESHOLDS,
)

logger = logging.getLogger("diana.application")

__all__ = [
    "CalibrationSample",
    "CalibrationReport",
    "CalibrationService",
    "CalibrationTraceSource",
    "DriftTextSource",
    "EmbeddingPort",
    "ThresholdConfigStore",
    "DEFAULT_CALIBRATION_CONFIG",
]

DEFAULT_CALIBRATION_CONFIG: dict[str, Any] = {
    "window_days": 30,
    "min_samples": 50,
    "autonomous_margin_min": 0.05,
    "drift_alert_threshold": 0.1,
    "drift_sample_size": 50,
    "baseline_weeks": 4,
}

_BASELINE_CACHE_KEY = "calibration.style_baseline_embedding"
_LAST_RUN_KEY = "calibration.last_run"


class EmbeddingPort(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class ThresholdConfigStore(Protocol):
    async def get_autonomous_thresholds(self) -> dict: ...

    async def get_supervised_thresholds(self) -> dict: ...

    async def get_calibration_config(self) -> dict: ...

    async def set_autonomous_thresholds(self, value: dict) -> None: ...

    async def set_supervised_thresholds(self, value: dict) -> None: ...

    async def set(self, key: str, value: object) -> None: ...

    async def get(self, key: str) -> object | None: ...


@dataclass(frozen=True)
class CalibrationSample:
    turn_id: UUID | object
    safety: float
    doctrine: float
    naturalness: float
    corrected: bool


class CalibrationTraceSource(Protocol):
    async def list_evaluated_samples(
        self, *, window_days: int
    ) -> list[CalibrationSample]: ...


class DriftTextSource(Protocol):
    async def sample_generated_texts(
        self, *, since_days: int, limit: int
    ) -> list[str]: ...

    async def sample_baseline_generated_texts(
        self, *, baseline_weeks: int, limit: int
    ) -> list[str]: ...


@dataclass
class CalibrationReport:
    status: str  # ok | disabled | insufficient_samples | no_corrections
    n_samples: int = 0
    n_corrected: int = 0
    supervised: dict[str, float] | None = None
    autonomous: dict[str, float] | None = None
    margin: float = 0.05
    extra: dict[str, Any] = field(default_factory=dict)


class CalibrationService:
    """Recalculate dual eval thresholds + detect style drift (post-hoc only)."""

    def __init__(
        self,
        *,
        feature_calibration_enabled: bool,
        traces: CalibrationTraceSource,
        config: ThresholdConfigStore,
        embeddings: EmbeddingPort,
        drift_texts: DriftTextSource,
        notifier: OwnerNotifierPort | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._enabled = feature_calibration_enabled
        self._traces = traces
        self._config = config
        self._embeddings = embeddings
        self._drift_texts = drift_texts
        self._notifier = notifier
        self._clock = clock or (lambda: datetime.now(UTC))

    async def calibrate_thresholds(
        self, window_days: int | None = None
    ) -> CalibrationReport:
        if not self._enabled:
            logger.info("calibration_skipped_disabled")
            return CalibrationReport(status="disabled")

        cal_cfg = await self._load_calibration_config()
        window = int(window_days if window_days is not None else cal_cfg["window_days"])
        min_samples = int(cal_cfg["min_samples"])
        margin = float(cal_cfg["autonomous_margin_min"])

        samples = await self._traces.list_evaluated_samples(window_days=window)
        n_samples = len(samples)
        corrected = [s for s in samples if s.corrected]
        n_corrected = len(corrected)

        if n_samples < min_samples:
            logger.info(
                "calibration_insufficient_samples",
                extra={"n_samples": n_samples, "min_samples": min_samples},
            )
            return CalibrationReport(
                status="insufficient_samples",
                n_samples=n_samples,
                n_corrected=n_corrected,
                margin=margin,
            )

        if n_corrected == 0:
            logger.info(
                "calibration_no_corrections",
                extra={"n_samples": n_samples},
            )
            return CalibrationReport(
                status="no_corrections",
                n_samples=n_samples,
                n_corrected=0,
                margin=margin,
            )

        raw_sup, raw_auto = self._percentiles_from_corrected(corrected)
        raw_sup, raw_auto = enforce_margin(raw_sup, raw_auto, margin)

        prev_sup = await self._previous_thresholds(
            await self._config.get_supervised_thresholds(),
            DEFAULT_SUPERVISED_THRESHOLDS,
        )
        prev_auto = await self._previous_thresholds(
            await self._config.get_autonomous_thresholds(),
            DEFAULT_AUTONOMOUS_THRESHOLDS,
        )

        final_sup = smooth_thresholds(prev_sup, raw_sup, alpha=0.5)
        final_auto = smooth_thresholds(prev_auto, raw_auto, alpha=0.5)
        # Re-enforce margin after smoothing so invariant always holds on write
        final_sup, final_auto = enforce_margin(final_sup, final_auto, margin)
        final_sup = {k: clamp01(final_sup[k]) for k in THRESHOLD_DIMS}
        final_auto = {k: clamp01(final_auto[k]) for k in THRESHOLD_DIMS}

        await self._config.set_supervised_thresholds(final_sup)
        await self._config.set_autonomous_thresholds(final_auto)

        now = self._clock()
        ts = now.isoformat() if now.tzinfo else now.replace(tzinfo=UTC).isoformat()
        await self._config.set(
            _LAST_RUN_KEY,
            {
                "ts": ts,
                "window_days": window,
                "n_samples": n_samples,
                "n_corrected": n_corrected,
                "supervised": final_sup,
                "autonomous": final_auto,
            },
        )

        logger.info(
            "calibration_applied",
            extra={
                "n_samples": n_samples,
                "n_corrected": n_corrected,
                "window_days": window,
            },
        )
        return CalibrationReport(
            status="ok",
            n_samples=n_samples,
            n_corrected=n_corrected,
            supervised=final_sup,
            autonomous=final_auto,
            margin=margin,
        )

    async def detect_drift(self) -> dict[str, float]:
        """Return float scores only (status goes to logs).

        Read-only for metrics even when ``feature_calibration_enabled`` is false.
        Threshold mutation stays in ``calibrate_thresholds`` only. Owner drift
        alerts fire only when the calibration flag is on **and** a notifier is set.
        """
        cal_cfg = await self._load_calibration_config()
        sample_size = int(cal_cfg["drift_sample_size"])
        baseline_weeks = int(cal_cfg["baseline_weeks"])
        alert_threshold = float(cal_cfg["drift_alert_threshold"])

        recent_texts = await self._drift_texts.sample_generated_texts(
            since_days=7, limit=sample_size
        )
        recent_texts = [t for t in recent_texts if t and t.strip()]

        if not recent_texts:
            logger.info("drift_computed", extra={"status": "insufficient_text"})
            return {"style_drift_score": 0.0}

        recent_mean = await self._mean_embedding(recent_texts)
        if recent_mean is None:
            logger.info("drift_computed", extra={"status": "insufficient_text"})
            return {"style_drift_score": 0.0}

        baseline_mean = await self._resolve_baseline_mean(
            cal_cfg, baseline_weeks=baseline_weeks, limit=sample_size
        )
        if baseline_mean is None:
            logger.info("drift_computed", extra={"status": "insufficient_text"})
            return {"style_drift_score": 0.0}

        score = style_drift_score(recent_mean, baseline_mean)
        logger.info(
            "drift_computed",
            extra={"style_drift_score": score},
        )

        # A6: alert only when calibration flag is on (avoids surprise DMs).
        if (
            self._enabled
            and score > alert_threshold
            and self._notifier is not None
        ):
            try:
                await self._notifier.notify_info(
                    f"Alerta de deriva de estilo: score={score:.3f} "
                    f"(umbral={alert_threshold}). Revisá el tono reciente."
                )
                logger.info("drift_alert", extra={"style_drift_score": score})
            except Exception:
                logger.exception("drift_alert_notify_failed")

        return {"style_drift_score": score}

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    async def _load_calibration_config(self) -> dict[str, Any]:
        raw = await self._config.get_calibration_config()
        merged = dict(DEFAULT_CALIBRATION_CONFIG)
        if isinstance(raw, dict):
            merged.update(raw)
        return merged

    @staticmethod
    async def _previous_thresholds(
        stored: Mapping[str, Any],
        defaults: Mapping[str, float],
    ) -> dict[str, float]:
        if not stored:
            return {k: float(defaults[k]) for k in THRESHOLD_DIMS}
        out: dict[str, float] = {}
        for dim in THRESHOLD_DIMS:
            if dim in stored and isinstance(stored[dim], (int, float)):
                out[dim] = float(stored[dim])
            else:
                out[dim] = float(defaults[dim])
        return out

    @staticmethod
    def _percentiles_from_corrected(
        corrected: list[CalibrationSample],
    ) -> tuple[dict[str, float], dict[str, float]]:
        field_map = {
            "safety_min": "safety",
            "doctrine_min": "doctrine",
            "naturalness_min": "naturalness",
        }
        raw_sup: dict[str, float] = {}
        raw_auto: dict[str, float] = {}
        for dim_key, attr in field_map.items():
            scores = sorted(float(getattr(s, attr)) for s in corrected)
            raw_sup[dim_key] = clamp01(percentile_linear(scores, 0.70))
            raw_auto[dim_key] = clamp01(percentile_linear(scores, 0.90))
        return raw_sup, raw_auto

    async def _mean_embedding(self, texts: list[str]) -> list[float] | None:
        vectors: list[list[float]] = []
        for text in texts:
            try:
                vec = await self._embeddings.embed(text)
            except Exception:
                logger.exception("calibration_embed_failed")
                continue
            if vec:
                vectors.append([float(x) for x in vec])
        if not vectors:
            return None
        return mean_vector(vectors)

    async def _resolve_baseline_mean(
        self,
        cal_cfg: Mapping[str, Any],
        *,
        baseline_weeks: int,
        limit: int,
    ) -> list[float] | None:
        cached = await self._read_cached_baseline(cal_cfg)
        if cached is not None:
            return cached

        baseline_texts = await self._drift_texts.sample_baseline_generated_texts(
            baseline_weeks=baseline_weeks, limit=limit
        )
        baseline_texts = [t for t in baseline_texts if t and t.strip()]
        if not baseline_texts:
            return None

        baseline_mean = await self._mean_embedding(baseline_texts)
        if baseline_mean is None:
            return None

        # Freeze baseline once on first successful compute (flat system_config key)
        try:
            await self._config.set(_BASELINE_CACHE_KEY, baseline_mean)
        except Exception:
            logger.exception("calibration_baseline_cache_write_failed")

        return baseline_mean

    async def _read_cached_baseline(
        self, cal_cfg: Mapping[str, Any]
    ) -> list[float] | None:
        """Prefer flat key ``calibration.style_baseline_embedding``, else blob field."""
        candidates: list[Any] = []
        try:
            flat = await self._config.get(_BASELINE_CACHE_KEY)
            candidates.append(flat)
        except Exception:
            logger.exception("calibration_baseline_cache_read_failed")
        candidates.append(cal_cfg.get("style_baseline_embedding"))
        for cached in candidates:
            if (
                isinstance(cached, list)
                and cached
                and all(isinstance(x, (int, float)) for x in cached)
            ):
                # Any positive length (unit fakes use small dims; prod ST is 384).
                return [float(x) for x in cached]
        return None
