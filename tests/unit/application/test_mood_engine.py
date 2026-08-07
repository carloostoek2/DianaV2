"""MoodEngine pure-unit tests: emotion→axes mapping, formula, stability, purity.

No DB, no LLM, no aiogram — pure math over a ``Comprehension`` + state.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from diana.application.mood_engine import (
    AXIS_NAMES,
    MOOD_NOISE,
    MOOD_RETURN_RATE,
    MOOD_SIGNAL_WEIGHT,
    MoodEngine,
    MoodSignal,
    MoodState,
)
from diana.application.ports import VipMoodStateRecord


def _engine(**kw) -> MoodEngine:
    data = dict(return_rate=0.1, signal_weight=0.5, noise=0.0, seed=7)
    data.update(kw)
    return MoodEngine(**data)


@pytest.mark.parametrize(
    ("emotion", "expected"),
    [
        ("neutral", (0.0, 0.0, 0.0)),
        ("positiva", (0.4, 0.4, 0.0)),
        ("cariñosa", (0.5, 0.5, 0.3)),
        ("ansiosa", (-0.3, -0.3, 0.4)),
        ("molesta", (-0.5, -0.4, 0.2)),
        ("triste", (-0.4, -0.4, -0.4)),
        ("urgente", (-0.2, 0.0, 0.6)),
    ],
)
def test_emotion_to_signal_mapping_7_emotions(emotion: str, expected: tuple[float, float, float]) -> None:
    engine = _engine()
    signal = engine.signal_from_comprehension({"emotion": emotion})
    assert (signal.d_playful, signal.d_warm, signal.d_energy) == pytest.approx(expected)


def test_signal_from_none_comprehension() -> None:
    engine = _engine()
    assert engine.signal_from_comprehension(None) == MoodSignal(0.0, 0.0, 0.0)
    assert engine.signal_from_comprehension({}) == MoodSignal(0.0, 0.0, 0.0)
    assert engine.signal_from_comprehension({"emotion": "bogus"}) == MoodSignal(0.0, 0.0, 0.0)


def test_update_formula() -> None:
    """current None → base (0,0,0); nuevo = señal * peso."""
    engine = _engine()  # return_rate 0.1, signal_weight 0.5, noise 0
    state = engine.update(None, MoodSignal(0.4, 0.2, 0.0))
    assert (state.axis_playful_serious, state.axis_warm_distant, state.axis_energy) == (
        pytest.approx(0.2),
        pytest.approx(0.1),
        pytest.approx(0.0),
    )


def test_update_from_existing_state() -> None:
    """nuevo = actual*(1-return_rate) + señal*peso."""
    engine = _engine()  # return_rate 0.1, signal_weight 0.5
    current = MoodState(0.5, -0.3, 0.2)
    state = engine.update(current, MoodSignal(0.4, 0.2, 0.0))
    assert state.axis_playful_serious == pytest.approx(0.5 * 0.9 + 0.4 * 0.5)  # 0.65
    assert state.axis_warm_distant == pytest.approx(-0.3 * 0.9 + 0.2 * 0.5)  # -0.17
    assert state.axis_energy == pytest.approx(0.2 * 0.9)  # 0.18


def test_convergence_constant_signal() -> None:
    """Señal constante → el eje converge al punto fijo (bajo el clamp)."""
    engine = MoodEngine(return_rate=0.5, signal_weight=0.3, noise=0.0, seed=1)
    state = MoodState(0.0, 0.0, 0.0)
    signal = MoodSignal(0.4, 0.0, 0.0)
    for _ in range(200):
        state = engine.update(state, signal)
    fixed = min(1.0, 0.4 * 0.3 / 0.5)  # 0.24
    assert state.axis_playful_serious == pytest.approx(fixed, abs=1e-6)
    # No further movement between final steps.
    next_state = engine.update(state, signal)
    assert abs(next_state.axis_playful_serious - state.axis_playful_serious) < 1e-9


def test_return_to_base_zero_signal() -> None:
    """Sin señal → el estado regresa a la base (0)."""
    engine = MoodEngine(return_rate=0.1, signal_weight=0.5, noise=0.0, seed=1)
    state = MoodState(0.8, 0.6, -0.4)
    for _ in range(200):
        state = engine.update(state, MoodSignal(0.0, 0.0, 0.0))
    assert state.axis_playful_serious == pytest.approx(0.0, abs=1e-6)
    assert state.axis_warm_distant == pytest.approx(0.0, abs=1e-6)
    assert state.axis_energy == pytest.approx(0.0, abs=1e-6)


def test_noise_bounded() -> None:
    """Ruido acotado a ±noise por eje en cada paso (single-step from base).

    The boundedness guarantee is per-draw: each ``update`` adds one
    ``uniform(-noise, noise)`` per axis. Comparing single steps from the same
    base keeps the diff equal to the draw itself — accumulating states would
    sum decaying draws and legitimately exceed one ``noise`` width.
    """
    engine_noise = MoodEngine(return_rate=0.1, signal_weight=0.5, noise=0.05, seed=42)
    engine_clean = MoodEngine(return_rate=0.1, signal_weight=0.5, noise=0.0, seed=42)
    signal = MoodSignal(0.4, 0.2, -0.1)
    for _ in range(200):
        noisy = engine_noise.update(None, signal)
        clean = engine_clean.update(None, signal)
        assert abs(noisy.axis_playful_serious - clean.axis_playful_serious) <= 0.05 + 1e-9
        assert abs(noisy.axis_warm_distant - clean.axis_warm_distant) <= 0.05 + 1e-9
        assert abs(noisy.axis_energy - clean.axis_energy) <= 0.05 + 1e-9


def test_range_clamped() -> None:
    """Señal extrema → ejes siempre en [-1, 1]."""
    engine = _engine(noise=0.0)
    state = MoodState(0.0, 0.0, 0.0)
    state = engine.update(state, MoodSignal(10.0, -10.0, 10.0))
    for value in (state.axis_playful_serious, state.axis_warm_distant, state.axis_energy):
        assert -1.0 <= value <= 1.0


def test_determinism_same_seed() -> None:
    """Dos engines con la misma semilla → secuencias idénticas."""
    a = MoodEngine(noise=0.05, seed=42)
    b = MoodEngine(noise=0.05, seed=42)
    signal = MoodSignal(0.4, 0.2, -0.1)
    sa: MoodState | None = None
    sb: MoodState | None = None
    for _ in range(100):
        sa = a.update(sa, signal)
        sb = b.update(sb, signal)
    assert sa == sb


def test_axis_weights_scale() -> None:
    """axis_weights escala la señal por eje (playful recibe el doble)."""
    engine = MoodEngine(
        return_rate=0.0,
        signal_weight=0.5,
        axis_weights={"playful": 2.0, "warm": 0.5, "energy": 1.0},
        noise=0.0,
        seed=1,
    )
    state = engine.update(None, MoodSignal(0.4, 0.2, 0.0))
    assert state.axis_playful_serious == pytest.approx(0.4 * 0.5 * 2.0)  # 0.4
    assert state.axis_warm_distant == pytest.approx(0.2 * 0.5 * 0.5)  # 0.05
    assert state.axis_energy == pytest.approx(0.0)


def test_axis_weights_cover_axis_names() -> None:
    engine = _engine()
    assert set(engine.axis_weights) == set(AXIS_NAMES)


def test_tone_distance() -> None:
    engine = _engine()
    triste = MoodState(-0.4, -0.4, -0.4)
    assert engine.tone_distance(triste, "triste") == pytest.approx(0.0)
    opposite = MoodState(0.4, 0.4, 0.4)
    assert engine.tone_distance(opposite, "triste") > 1.0
    # Unknown emotion falls back to neutral tone point.
    neutral = MoodState(0.0, 0.0, 0.0)
    assert engine.tone_distance(neutral, "bogus") == pytest.approx(0.0)


def test_apply_overrides() -> None:
    engine = _engine()
    engine.apply_overrides({"return_rate": 0.2, "signal_weight": 0.6, "noise": 0.1})
    assert engine.return_rate == pytest.approx(0.2)
    assert engine.signal_weight == pytest.approx(0.6)
    assert engine.noise == pytest.approx(0.1)


def test_apply_overrides_invalid_config_does_not_crash() -> None:
    engine = _engine()
    engine.apply_overrides({"return_rate": "nope"})
    assert engine.return_rate == pytest.approx(0.1)
    engine.apply_overrides({"return_rate": 2.0})  # out of range → rejected
    assert engine.return_rate == pytest.approx(0.1)
    engine.apply_overrides({"axis_weights": {"playful": -1.0}})  # negative → rejected
    assert engine.axis_weights["playful"] == pytest.approx(1.0)
    engine.apply_overrides(None)  # type: ignore[arg-type]
    engine.apply_overrides({})
    assert engine.signal_weight == pytest.approx(0.5)


def test_axis_weights_override_applies() -> None:
    engine = _engine()
    engine.apply_overrides({"axis_weights": {"warm": 2.0}})
    assert engine.axis_weights["warm"] == pytest.approx(2.0)
    assert engine.axis_weights["playful"] == pytest.approx(1.0)  # untouched


def test_defaults_match_module_constants() -> None:
    engine = MoodEngine()
    assert engine.return_rate == MOOD_RETURN_RATE
    assert engine.signal_weight == MOOD_SIGNAL_WEIGHT
    assert engine.noise == MOOD_NOISE


def test_update_accepts_vip_mood_state_record() -> None:
    """S1: update normalizes a persisted VipMoodStateRecord like a MoodState."""
    engine = _engine()  # return_rate 0.1, signal_weight 0.5, noise 0
    current = VipMoodStateRecord(
        vip_id=uuid4(),
        axis_playful_serious=0.5,
        axis_warm_distant=-0.3,
        axis_energy=0.2,
        updated_at=None,
    )
    state = engine.update(current, MoodSignal(0.4, 0.2, 0.0))
    # Same formula as test_update_from_existing_state over a MoodState.
    assert state.axis_playful_serious == pytest.approx(0.5 * 0.9 + 0.4 * 0.5)
    assert state.axis_warm_distant == pytest.approx(-0.3 * 0.9 + 0.2 * 0.5)
    assert state.axis_energy == pytest.approx(0.2 * 0.9)


def test_tone_distance_accepts_vip_mood_state_record() -> None:
    """S1: tone_distance normalizes a persisted VipMoodStateRecord."""
    engine = _engine()
    triste = VipMoodStateRecord(
        vip_id=uuid4(),
        axis_playful_serious=-0.4,
        axis_warm_distant=-0.4,
        axis_energy=-0.4,
        updated_at=None,
    )
    assert engine.tone_distance(triste, "triste") == pytest.approx(0.0)


def test_fork_preserves_params_and_seed_determinism() -> None:
    """S5: fork() keeps the (possibly overridden) params; two forks with the
    same seed produce identical sequences (stable per-VIP noise)."""
    prototype = MoodEngine(
        return_rate=0.1,
        signal_weight=0.5,
        axis_weights={"playful": 2.0, "warm": 1.0, "energy": 1.0},
        noise=0.05,
    )
    prototype.apply_overrides({"return_rate": 0.2})
    forked = prototype.fork(seed=1234)
    assert forked.return_rate == pytest.approx(0.2)
    assert forked.signal_weight == pytest.approx(0.5)
    assert forked.noise == pytest.approx(0.05)
    assert forked.axis_weights == prototype.axis_weights

    a = prototype.fork(seed=1234)
    b = prototype.fork(seed=1234)
    signal = MoodSignal(0.4, 0.2, -0.1)
    sa: MoodState | None = None
    sb: MoodState | None = None
    for _ in range(50):
        sa = a.update(sa, signal)
        sb = b.update(sb, signal)
    assert sa == sb


def test_no_noise_on_neutral_signal() -> None:
    """S14: a neutral signal (all deltas 0) decays to base deterministically —
    no noise draw, so all-neutral conversations never accumulate a random walk
    (F3 "ejes estables")."""
    engine = MoodEngine(return_rate=0.1, signal_weight=0.5, noise=0.05, seed=1)
    # From base: neutral signal → exact (0, 0, 0), no jitter.
    state = engine.update(None, MoodSignal(0.0, 0.0, 0.0))
    assert (state.axis_playful_serious, state.axis_warm_distant, state.axis_energy) == (
        pytest.approx(0.0),
        pytest.approx(0.0),
        pytest.approx(0.0),
    )
    # From a warm state: pure exponential decay (base * (1 - return_rate)).
    state = engine.update(MoodState(0.8, 0.6, -0.4), MoodSignal(0.0, 0.0, 0.0))
    assert state.axis_playful_serious == pytest.approx(0.8 * 0.9)
    assert state.axis_warm_distant == pytest.approx(0.6 * 0.9)
    assert state.axis_energy == pytest.approx(-0.4 * 0.9)


def test_import_purity() -> None:
    """The mood engine is a pure application module: no chat-framework/infra."""
    from diana.application import mood_engine

    text = Path(mood_engine.__file__).read_text(encoding="utf-8")
    for token in ("aiogram", "infrastructure", "telegram", "sqlalchemy"):
        assert token not in text, token
