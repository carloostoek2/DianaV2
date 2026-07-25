"""Source-level asserts for F3 foundation migration seeds (006)."""

from __future__ import annotations

from pathlib import Path

MIGRATION_006 = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "006_f3_foundation_flags_thresholds.py"
)

F3_FEATURE_KEYS = (
    "FEATURE_AUTONOMOUS_MODE",
    "FEATURE_RECONTACT_ENABLED",
    "FEATURE_PROMO_ENABLED",
    "FEATURE_CALIBRATION_ENABLED",
    "FEATURE_ADVANCED_BEHAVIOR",
)


def test_f3_migration_006_file_exists() -> None:
    assert MIGRATION_006.is_file(), f"missing migration: {MIGRATION_006}"


def test_f3_migration_006_revision_chain_and_seeds() -> None:
    text = MIGRATION_006.read_text(encoding="utf-8")

    assert 'revision: str = "006_f3_foundation_flags_thresholds"' in text
    assert "005_trace_timings" in text
    assert "down_revision" in text

    for key in F3_FEATURE_KEYS:
        assert key in text

    assert "'false'::jsonb" in text
    assert "'autonomous_thresholds'" in text
    assert "'supervised_thresholds'" in text

    # SPEC §4.2 autonomous 0.9 / 0.8 / 0.7
    assert "0.9" in text
    assert "0.8" in text
    assert "0.7" in text
    # supervised 0.5 / 0.4 / 0.5
    assert "0.5" in text
    assert "0.4" in text

    assert "safety_min" in text
    assert "doctrine_min" in text
    assert "naturalness_min" in text
    assert "ON CONFLICT (key) DO NOTHING" in text


def test_f3_migration_006_does_not_seed_pool2_config_blobs() -> None:
    """calibration / recontact / promo config blobs are out of foundation scope."""
    text = MIGRATION_006.read_text(encoding="utf-8")
    # Feature flags for those domains are allowed; config *blobs* are not.
    for blob_key in ("'calibration'", "'recontact'", "'promo'"):
        assert blob_key not in text
    assert "('calibration'" not in text
    assert "('recontact'" not in text
    assert "('promo'" not in text
