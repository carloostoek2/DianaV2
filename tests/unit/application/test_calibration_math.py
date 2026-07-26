"""Unit tests for pure calibration math (no I/O)."""

from __future__ import annotations

import math

import pytest

from diana.application.calibration_math import (
    cosine_similarity,
    enforce_margin,
    mean_vector,
    percentile_linear,
    smooth_thresholds,
    style_drift_score,
)


class TestPercentileLinear:
    def test_percentile_0_is_min(self) -> None:
        assert percentile_linear([1.0, 2.0, 3.0, 4.0, 5.0], 0.0) == 1.0

    def test_percentile_1_is_max(self) -> None:
        assert percentile_linear([1.0, 2.0, 3.0, 4.0, 5.0], 1.0) == 5.0

    def test_percentile_0_7_linear_interpolation(self) -> None:
        # sorted n=5; index = 0.7 * 4 = 2.8 → between 3.0 and 4.0
        result = percentile_linear([1.0, 2.0, 3.0, 4.0, 5.0], 0.7)
        assert result == pytest.approx(3.8)

    def test_percentile_0_9_linear_interpolation(self) -> None:
        # index = 0.9 * 4 = 3.6 → between 4.0 and 5.0
        result = percentile_linear([1.0, 2.0, 3.0, 4.0, 5.0], 0.9)
        assert result == pytest.approx(4.6)

    def test_single_value(self) -> None:
        assert percentile_linear([0.75], 0.7) == 0.75
        assert percentile_linear([0.75], 0.9) == 0.75

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            percentile_linear([], 0.7)


class TestEnforceMargin:
    def test_raises_autonomous_by_margin(self) -> None:
        sup = {"safety_min": 0.5, "doctrine_min": 0.4, "naturalness_min": 0.5}
        auto = {"safety_min": 0.5, "doctrine_min": 0.4, "naturalness_min": 0.5}
        out_sup, out_auto = enforce_margin(sup, auto, margin=0.05)
        assert out_auto["safety_min"] == pytest.approx(0.55)
        assert out_auto["doctrine_min"] == pytest.approx(0.45)
        assert out_auto["naturalness_min"] == pytest.approx(0.55)
        assert out_sup == sup

    def test_already_satisfied_unchanged(self) -> None:
        sup = {"safety_min": 0.5, "doctrine_min": 0.4, "naturalness_min": 0.5}
        auto = {"safety_min": 0.9, "doctrine_min": 0.8, "naturalness_min": 0.7}
        out_sup, out_auto = enforce_margin(sup, auto, margin=0.05)
        assert out_auto == auto
        assert out_sup == sup

    def test_clamp_auto_at_1_and_adjust_sup(self) -> None:
        sup = {"safety_min": 0.98, "doctrine_min": 0.98, "naturalness_min": 0.98}
        auto = {"safety_min": 0.99, "doctrine_min": 0.99, "naturalness_min": 0.99}
        out_sup, out_auto = enforce_margin(sup, auto, margin=0.05)
        for dim in ("safety_min", "doctrine_min", "naturalness_min"):
            assert out_auto[dim] == pytest.approx(1.0)
            assert out_sup[dim] == pytest.approx(0.95)
            assert out_auto[dim] >= out_sup[dim] + 0.05 - 1e-9

    def test_margin_invariant_property(self) -> None:
        pairs = [
            ({"safety_min": 0.1, "doctrine_min": 0.2, "naturalness_min": 0.3},
             {"safety_min": 0.1, "doctrine_min": 0.2, "naturalness_min": 0.3}),
            ({"safety_min": 0.6, "doctrine_min": 0.7, "naturalness_min": 0.8},
             {"safety_min": 0.61, "doctrine_min": 0.72, "naturalness_min": 0.9}),
            ({"safety_min": 0.96, "doctrine_min": 0.97, "naturalness_min": 0.99},
             {"safety_min": 0.97, "doctrine_min": 0.98, "naturalness_min": 1.0}),
        ]
        for sup, auto in pairs:
            out_sup, out_auto = enforce_margin(sup, auto, margin=0.05)
            for dim in ("safety_min", "doctrine_min", "naturalness_min"):
                assert out_auto[dim] >= out_sup[dim] + 0.05 - 1e-9
                assert 0.0 <= out_sup[dim] <= 1.0
                assert 0.0 <= out_auto[dim] <= 1.0


class TestSmoothThresholds:
    def test_fifty_fifty_blend(self) -> None:
        previous = {"safety_min": 0.5, "doctrine_min": 0.4, "naturalness_min": 0.5}
        new = {"safety_min": 0.7, "doctrine_min": 0.6, "naturalness_min": 0.9}
        result = smooth_thresholds(previous, new, alpha=0.5)
        assert result["safety_min"] == pytest.approx(0.6)
        assert result["doctrine_min"] == pytest.approx(0.5)
        assert result["naturalness_min"] == pytest.approx(0.7)

    def test_alpha_one_keeps_previous(self) -> None:
        previous = {"safety_min": 0.5}
        new = {"safety_min": 0.9}
        assert smooth_thresholds(previous, new, alpha=1.0)["safety_min"] == 0.5

    def test_alpha_zero_keeps_new(self) -> None:
        previous = {"safety_min": 0.5}
        new = {"safety_min": 0.9}
        assert smooth_thresholds(previous, new, alpha=0.0)["safety_min"] == 0.9


class TestVectorMath:
    def test_mean_vector(self) -> None:
        vectors = [[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]]
        assert mean_vector(vectors) == pytest.approx([2.0, 3.0, 4.0])

    def test_mean_vector_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            mean_vector([])

    def test_cosine_identical_is_one(self) -> None:
        a = [1.0, 2.0, 3.0]
        assert cosine_similarity(a, a) == pytest.approx(1.0)

    def test_cosine_orthogonal_near_zero(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_style_drift_identical_is_zero(self) -> None:
        a = [0.5, 0.5, 0.5]
        assert style_drift_score(a, a) == pytest.approx(0.0)

    def test_style_drift_orthogonal_near_one(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert style_drift_score(a, b) == pytest.approx(1.0)

    def test_style_drift_clamped_non_negative(self) -> None:
        # identical after normalization still 0
        a = [2.0, 0.0]
        b = [4.0, 0.0]
        assert style_drift_score(a, b) == pytest.approx(0.0)
        assert not math.isnan(style_drift_score(a, b))
