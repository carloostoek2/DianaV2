"""Invariant tests: EvaluationProfile is a 7D vector, never a single score."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from diana.cognitive.models import EvaluationProfile

CANONICAL_DIMS = frozenset(
    {
        "naturalness",
        "precision",
        "doctrine",
        "consistency",
        "safety",
        "coverage",
        "empathy",
    }
)

FORBIDDEN_SCORE_NAMES = frozenset({"confidence", "overall_score", "score"})
FORBIDDEN_AGGREGATION_HELPERS = frozenset(
    {
        "mean",
        "average",
        "overall",
        "aggregate",
        "total_score",
        "as_score",
        "total",
    }
)


def _full_profile_kwargs() -> dict[str, float]:
    return {name: 0.8 for name in CANONICAL_DIMS}


def test_evaluation_profile_field_names_are_exactly_seven_canonical() -> None:
    float_fields = {
        name
        for name, info in EvaluationProfile.model_fields.items()
        if info.annotation is float
    }
    assert float_fields == CANONICAL_DIMS
    assert len(float_fields) == 7


def test_evaluation_profile_has_no_aggregate_score_fields() -> None:
    field_names = set(EvaluationProfile.model_fields.keys())
    assert field_names.isdisjoint(FORBIDDEN_SCORE_NAMES)
    # Strict: properties / class attrs / computed fields named as scores are forbidden.
    for forbidden in FORBIDDEN_SCORE_NAMES:
        assert not hasattr(EvaluationProfile, forbidden), forbidden
    computed = set(getattr(EvaluationProfile, "model_computed_fields", {}) or {})
    assert computed.isdisjoint(FORBIDDEN_SCORE_NAMES)


def test_evaluation_profile_rejects_forbidden_extra_score_fields() -> None:
    base = _full_profile_kwargs()
    for forbidden in FORBIDDEN_SCORE_NAMES:
        with pytest.raises(ValidationError):
            EvaluationProfile(**base, **{forbidden: 0.99})  # type: ignore[arg-type]


def test_evaluation_profile_has_no_aggregation_helpers() -> None:
    for name in FORBIDDEN_AGGREGATION_HELPERS:
        assert not hasattr(EvaluationProfile, name), name
        assert name not in EvaluationProfile.__dict__


def test_evaluation_profile_float_dims_are_all_required() -> None:
    """Every canonical float dimension must be required (no silent defaults)."""
    for name in CANONICAL_DIMS:
        info = EvaluationProfile.model_fields[name]
        assert info.is_required() is True, f"{name} must be required"
        assert info.annotation is float
