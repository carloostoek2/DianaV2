"""MoodEngine — 3-axis mood moving average (Fase 3, shadow), no LLM.

Per-turn signal from the analyst ``emotion`` (7 closed values) mapped to three
axes (playful, warm, energy). ``update`` applies the moving-average-with-return
formula from SPEC-EVOLUCION-AGENTE v1.2 §3.1:

    nuevo = actual*(1 - return_rate) + señal_eje*peso_señal*peso_eje + ruido

with bounded, deterministic noise (injectable seed) and clamp to [-1, 1].
``tone_distance`` feeds the 3.3 shadow connection (mood→tone distance, logged
but never applied to variant selection).

Fase 2/3 shadow — no LLM, reusa la comprehension del analyst; constantes fijas
con override manual, nunca auto-calibradas. Pure application module: imports
only ``cognitive.models`` + stdlib (no chat-framework or persistence imports).
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from diana.cognitive.models import Comprehension

logger = logging.getLogger("diana.application")

# Fixed constants (never auto-calibrated). Manual override only.
MOOD_RETURN_RATE = 0.05
MOOD_SIGNAL_WEIGHT = 0.3
MOOD_NOISE = 0.05
AXIS_NAMES = ("playful", "warm", "energy")

# emotion → (d_playful, d_warm, d_energy) — fixed constants, manual override
# only (7 closed values from cognitive.models Emotion).
_EMOTION_SIGNAL: dict[str, tuple[float, float, float]] = {
    "neutral": (0.0, 0.0, 0.0),
    "positiva": (0.4, 0.4, 0.0),
    "cariñosa": (0.5, 0.5, 0.3),
    "ansiosa": (-0.3, -0.3, 0.4),
    "molesta": (-0.5, -0.4, 0.2),
    "triste": (-0.4, -0.4, -0.4),
    "urgente": (-0.2, 0.0, 0.6),
}


@dataclass(frozen=True, slots=True)
class MoodSignal:
    """Per-turn push on each axis (derived from the analyst emotion)."""

    d_playful: float
    d_warm: float
    d_energy: float


@dataclass(frozen=True, slots=True)
class MoodState:
    """3-axis mood vector for a VIP. Ranges are clamped to [-1, 1]."""

    axis_playful_serious: float
    axis_warm_distant: float
    axis_energy: float
    updated_at: datetime | None = None


class MoodEngine:
    """Moving-average mood per VIP with return to base + bounded noise."""

    def __init__(
        self,
        *,
        return_rate: float = MOOD_RETURN_RATE,
        signal_weight: float = MOOD_SIGNAL_WEIGHT,
        axis_weights: dict[str, float] | None = None,
        noise: float = MOOD_NOISE,
        seed: int | None = None,
    ) -> None:
        # Clamp to sane ranges so typo'd constructor args cannot invert axes.
        self._return_rate = min(max(float(return_rate), 0.0), 1.0)
        self._signal_weight = min(max(float(signal_weight), 0.0), 1.0)
        self._noise = min(max(float(noise), 0.0), 1.0)
        weights = axis_weights or {"playful": 1.0, "warm": 1.0, "energy": 1.0}
        self._axis_weights: dict[str, float] = {}
        for name in AXIS_NAMES:
            value = weights.get(name, 1.0)
            self._axis_weights[name] = max(float(value), 0.0)
        self._rng = random.Random(seed)  # seed None → system (os.urandom)

    @property
    def return_rate(self) -> float:
        return self._return_rate

    @property
    def signal_weight(self) -> float:
        return self._signal_weight

    @property
    def noise(self) -> float:
        return self._noise

    @property
    def axis_weights(self) -> dict[str, float]:
        return dict(self._axis_weights)

    def apply_overrides(self, config: dict[str, Any]) -> None:
        """Manual override from ``system_config`` (key ``mood_engine``).

        This is the ONLY override point — thresholds are never auto-calibrated.
        Missing keys are ignored; invalid values are rejected without crashing.
        """
        if not isinstance(config, dict):
            return
        try:
            raw = config.get("return_rate")
            if raw is not None:
                value = float(raw)
                if 0.0 <= value <= 1.0:
                    self._return_rate = value
        except (TypeError, ValueError):
            pass
        try:
            raw = config.get("signal_weight")
            if raw is not None:
                value = float(raw)
                if 0.0 <= value <= 1.0:
                    self._signal_weight = value
        except (TypeError, ValueError):
            pass
        try:
            raw = config.get("noise")
            if raw is not None:
                value = float(raw)
                if 0.0 <= value <= 1.0:
                    self._noise = value
        except (TypeError, ValueError):
            pass
        try:
            raw = config.get("axis_weights")
            if isinstance(raw, dict):
                for name in AXIS_NAMES:
                    value = raw.get(name)
                    if value is not None:
                        parsed = float(value)
                        if parsed >= 0.0:
                            self._axis_weights[name] = parsed
        except (TypeError, ValueError):
            pass

    def signal_from_comprehension(
        self,
        comprehension: dict[str, Any] | Comprehension | None,
    ) -> MoodSignal:
        """Map the analyst ``emotion`` to a per-turn signal (7 closed values)."""
        comp = self._comprehension_dict(comprehension)
        if comp is None:
            return MoodSignal(0.0, 0.0, 0.0)
        emotion = comp.get("emotion")
        if not isinstance(emotion, str):
            return MoodSignal(0.0, 0.0, 0.0)
        key = emotion.strip().lower()
        delta = _EMOTION_SIGNAL.get(key)
        if delta is None:
            return MoodSignal(0.0, 0.0, 0.0)
        return MoodSignal(delta[0], delta[1], delta[2])

    def update(self, current: MoodState | None, signal: MoodSignal) -> MoodState:
        """Moving average with return to base + bounded noise; clamp [-1, 1]."""
        if current is None:
            base = (0.0, 0.0, 0.0)
        else:
            base = (
                current.axis_playful_serious,
                current.axis_warm_distant,
                current.axis_energy,
            )
        deltas = (signal.d_playful, signal.d_warm, signal.d_energy)
        values: list[float] = []
        for i, name in enumerate(AXIS_NAMES):
            noise_draw = self._rng.uniform(-self._noise, self._noise)
            v = (
                base[i] * (1.0 - self._return_rate)
                + deltas[i] * self._signal_weight * self._axis_weights[name]
                + noise_draw
            )
            values.append(max(-1.0, min(1.0, v)))
        return MoodState(values[0], values[1], values[2])

    def tone_distance(self, mood: MoodState, emotion: str) -> float:
        """Euclidean distance between the mood vector and the emotion's tone point.

        Shadow 3.3 connection: logged, never applied to variant selection.
        An unknown/absent emotion falls back to the neutral tone point.
        """
        key = emotion.strip().lower() if isinstance(emotion, str) else "neutral"
        target = _EMOTION_SIGNAL.get(key, _EMOTION_SIGNAL["neutral"])
        return (
            (mood.axis_playful_serious - target[0]) ** 2
            + (mood.axis_warm_distant - target[1]) ** 2
            + (mood.axis_energy - target[2]) ** 2
        ) ** 0.5

    # --- internals -----------------------------------------------------------

    @staticmethod
    def _comprehension_dict(
        comp: dict[str, Any] | Comprehension | None,
    ) -> dict[str, Any] | None:
        if comp is None:
            return None
        if isinstance(comp, Comprehension):
            return comp.model_dump()
        if isinstance(comp, dict):
            return comp
        return None


__all__ = [
    "AXIS_NAMES",
    "MOOD_NOISE",
    "MOOD_RETURN_RATE",
    "MOOD_SIGNAL_WEIGHT",
    "MoodEngine",
    "MoodSignal",
    "MoodState",
]
