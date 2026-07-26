"""Pure calibration math — percentile, margin, smooth, vector drift (no I/O)."""

from __future__ import annotations

import math
from typing import Mapping

__all__ = [
    "THRESHOLD_DIMS",
    "percentile_linear",
    "enforce_margin",
    "smooth_thresholds",
    "mean_vector",
    "l2_normalize",
    "cosine_similarity",
    "style_drift_score",
    "clamp01",
]

THRESHOLD_DIMS: tuple[str, ...] = ("safety_min", "doctrine_min", "naturalness_min")


def clamp01(value: float) -> float:
    """Clamp *value* to the closed unit interval [0, 1]."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


def percentile_linear(sorted_values: list[float], p: float) -> float:
    """Linear-interpolation percentile on a pre-sorted ascending list.

    ``p`` is in [0, 1]. Uses the index formula ``p * (n - 1)``.
    """
    if not sorted_values:
        raise ValueError("percentile_linear requires a non-empty list")
    if p < 0.0 or p > 1.0:
        raise ValueError(f"p must be in [0, 1], got {p}")
    n = len(sorted_values)
    if n == 1:
        return float(sorted_values[0])
    index = p * (n - 1)
    low = int(math.floor(index))
    high = int(math.ceil(index))
    if low == high:
        return float(sorted_values[low])
    frac = index - low
    return float(sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac)


def enforce_margin(
    supervised: Mapping[str, float],
    autonomous: Mapping[str, float],
    margin: float,
) -> tuple[dict[str, float], dict[str, float]]:
    """Ensure autonomous[dim] >= supervised[dim] + margin for each dual-threshold dim.

    Clamps autonomous to <= 1.0. If that forces auto==1.0 and supervised would
    violate the inequality, clamp supervised to ``1.0 - margin``.
    """
    out_sup = {k: float(supervised[k]) for k in THRESHOLD_DIMS if k in supervised}
    out_auto = {k: float(autonomous[k]) for k in THRESHOLD_DIMS if k in autonomous}
    # Include any extra keys from either side (defensive); only enforce known dims.
    for k, v in supervised.items():
        out_sup.setdefault(k, float(v))
    for k, v in autonomous.items():
        out_auto.setdefault(k, float(v))

    for dim in THRESHOLD_DIMS:
        if dim not in out_sup or dim not in out_auto:
            continue
        sup = clamp01(out_sup[dim])
        auto = clamp01(out_auto[dim])
        auto = max(auto, sup + margin)
        if auto > 1.0:
            auto = 1.0
        if auto + 1e-12 < sup + margin:
            # auto clamped to 1.0 and still cannot meet margin → lower sup
            sup = max(0.0, 1.0 - margin)
            auto = 1.0
        # Final pass: if still short after clamp (e.g. margin>1), keep auto=1,sup=0
        if auto < sup + margin - 1e-12:
            sup = max(0.0, min(sup, auto - margin))
        out_sup[dim] = clamp01(sup)
        out_auto[dim] = clamp01(auto)
    return out_sup, out_auto


def smooth_thresholds(
    previous: Mapping[str, float],
    new: Mapping[str, float],
    alpha: float = 0.5,
) -> dict[str, float]:
    """Blend thresholds: ``final = alpha * previous + (1 - alpha) * new``."""
    keys = set(previous) | set(new)
    result: dict[str, float] = {}
    for key in keys:
        prev = float(previous.get(key, new[key] if key in new else 0.0))
        nxt = float(new.get(key, previous[key] if key in previous else 0.0))
        result[key] = alpha * prev + (1.0 - alpha) * nxt
    return result


def mean_vector(vectors: list[list[float]]) -> list[float]:
    """Component-wise mean of equal-length vectors."""
    if not vectors:
        raise ValueError("mean_vector requires a non-empty list")
    dim = len(vectors[0])
    if dim == 0:
        raise ValueError("vectors must have non-zero dimension")
    acc = [0.0] * dim
    for vec in vectors:
        if len(vec) != dim:
            raise ValueError("all vectors must share the same dimension")
        for i, v in enumerate(vec):
            acc[i] += float(v)
    n = float(len(vectors))
    return [x / n for x in acc]


def l2_normalize(vector: list[float]) -> list[float]:
    """Return L2-normalized copy; zero vector stays zero."""
    norm = math.sqrt(sum(float(x) * float(x) for x in vector))
    if norm == 0.0:
        return [0.0] * len(vector)
    return [float(x) / norm for x in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors (not pre-normalized required)."""
    if len(a) != len(b):
        raise ValueError("vectors must have the same dimension")
    if not a:
        return 0.0
    na = l2_normalize(a)
    nb = l2_normalize(b)
    return sum(x * y for x, y in zip(na, nb, strict=True))


def style_drift_score(a: list[float], b: list[float]) -> float:
    """``1 - cosine_similarity``, clamped to [0, 2]."""
    score = 1.0 - cosine_similarity(a, b)
    if score < 0.0:
        return 0.0
    if score > 2.0:
        return 2.0
    return float(score)
