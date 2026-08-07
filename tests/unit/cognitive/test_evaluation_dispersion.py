"""evaluation_dispersion — pure spread metric over the 7 evaluation dims (5.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from diana.cognitive.models import EvaluationProfile, _EVAL_DIMS, evaluation_dispersion


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


def test_uniform_profile_dispersion_zero() -> None:
    uniform = EvaluationProfile(
        naturalness=0.9,
        precision=0.9,
        doctrine=0.9,
        consistency=0.9,
        safety=0.9,
        coverage=0.9,
        empathy=0.9,
    )
    assert evaluation_dispersion(uniform) == pytest.approx(0.0)


def test_spread_profile_dispersion_positive_and_grows() -> None:
    mild = _profile(naturalness=0.5, doctrine=0.9)
    wide = _profile(naturalness=0.0, doctrine=1.0)
    d_mild = evaluation_dispersion(mild)
    d_wide = evaluation_dispersion(wide)
    assert d_mild > 0.0
    assert d_wide > 0.0
    assert d_wide > d_mild


def test_dispersion_uses_all_seven_dims() -> None:
    """A UNIFORM base profile makes a single dropped dim detectable: moving ANY
    one of the 7 dims away from the uniform value must change the std. If
    ``_EVAL_DIMS`` lost that dim, the perturbation would be a no-op and the
    test would fail (review round 1, S9)."""
    assert len(_EVAL_DIMS) == 7
    base = EvaluationProfile(**{dim: 0.5 for dim in _EVAL_DIMS})
    assert evaluation_dispersion(base) == pytest.approx(0.0)
    for dim in _EVAL_DIMS:
        shifted = base.model_copy(update={dim: 1.0})
        assert evaluation_dispersion(shifted) > 0.0, dim


def test_evaluation_profile_gains_no_new_field() -> None:
    """The contract 'never collapse to a single score' is preserved: the pure
    helper must not add any field to EvaluationProfile (spread is derived, not
    stored)."""
    fields = set(EvaluationProfile.model_fields)
    assert fields == {
        "naturalness", "precision", "doctrine", "consistency",
        "safety", "coverage", "empathy", "raw_llm_output",
    }
    assert "dispersion" not in fields
    assert "overall_score" not in fields
    assert "confidence" not in fields


def test_cognitive_import_purity() -> None:
    """The helper lives in the pure cognitive domain module (no framework)."""
    from diana.cognitive import models

    text = Path(models.__file__).read_text(encoding="utf-8")
    for token in ("aiogram", "sqlalchemy", "diana.llm"):
        assert token not in text, token
