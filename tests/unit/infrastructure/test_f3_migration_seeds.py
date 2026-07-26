"""Source-level asserts for F3 foundation migration seeds (006)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from diana.cognitive.thresholds import (
    DEFAULT_AUTONOMOUS_THRESHOLDS,
    DEFAULT_SUPERVISED_THRESHOLDS,
)

MIGRATION_006 = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "006_f3_flags_thresholds.py"
)

MIGRATION_001 = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "001_f1_foundation.py"
)

F3_FEATURE_KEYS = (
    "FEATURE_AUTONOMOUS_MODE",
    "FEATURE_RECONTACT_ENABLED",
    "FEATURE_PROMO_ENABLED",
    "FEATURE_CALIBRATION_ENABLED",
    "FEATURE_ADVANCED_BEHAVIOR",
)

# Settings snake_case ↔ DB/env FEATURE_* (F2 naming mirror).
F3_SETTINGS_TO_FEATURE_KEY = (
    ("feature_autonomous_mode", "FEATURE_AUTONOMOUS_MODE"),
    ("feature_recontact_enabled", "FEATURE_RECONTACT_ENABLED"),
    ("feature_promo_enabled", "FEATURE_PROMO_ENABLED"),
    ("feature_calibration_enabled", "FEATURE_CALIBRATION_ENABLED"),
    ("feature_advanced_behavior", "FEATURE_ADVANCED_BEHAVIOR"),
)


def _migration_text() -> str:
    return MIGRATION_006.read_text(encoding="utf-8")


def _extract_seed_json(text: str, key: str) -> dict:
    """Parse exact JSON blob bound to a system_config seed key."""
    pattern = rf"\('{re.escape(key)}',\s*'(\{{.*?\}})'::jsonb\)"
    match = re.search(pattern, text, re.DOTALL)
    assert match is not None, f"seed JSON for key {key!r} not found"
    return json.loads(match.group(1))


def test_f3_migration_006_file_exists() -> None:
    assert MIGRATION_006.is_file(), f"missing migration: {MIGRATION_006}"


def test_f3_migration_006_revision_chain() -> None:
    text = _migration_text()
    assert 'revision: str = "006_f3_flags_thresholds"' in text
    # Exact assignment — not merely "005_trace_timings" in docstring/comments.
    assert (
        'down_revision: Union[str, Sequence[str], None] = "005_trace_timings"'
        in text
    )
    assert "ON CONFLICT (key) DO NOTHING" in text


def test_f3_feature_flags_seeded_false_key_value_bound() -> None:
    """Each FEATURE_* key is bound to false — not merely present as a substring."""
    text = _migration_text()
    for key in F3_FEATURE_KEYS:
        assert f"('{key}', 'false'::jsonb)" in text, f"unbound or wrong value for {key}"


def test_f3_threshold_seeds_match_default_constants() -> None:
    """Dual surface lock: migration JSON == pure DEFAULT_* constants."""
    text = _migration_text()
    auto = _extract_seed_json(text, "autonomous_thresholds")
    supervised = _extract_seed_json(text, "supervised_thresholds")
    assert auto == dict(DEFAULT_AUTONOMOUS_THRESHOLDS)
    assert supervised == dict(DEFAULT_SUPERVISED_THRESHOLDS)


def test_f3_settings_attrs_map_to_feature_seed_keys() -> None:
    """Settings field names and DB FEATURE_* seed keys stay paired."""
    from diana.config import Settings

    text = _migration_text()
    for attr, feature_key in F3_SETTINGS_TO_FEATURE_KEY:
        assert attr in Settings.model_fields, f"missing Settings field {attr}"
        assert f"('{feature_key}', 'false'::jsonb)" in text


def test_f1_eval_thresholds_seed_untouched_by_006() -> None:
    """F1 eval_thresholds {safety: 0.3} remains; 006 does not rewrite it."""
    f1 = MIGRATION_001.read_text(encoding="utf-8")
    assert "('eval_thresholds', '{\"safety\": 0.3}'::jsonb)" in f1 or (
        "eval_thresholds" in f1 and '"safety": 0.3' in f1
    )
    text_006 = _migration_text()
    assert "eval_thresholds" not in text_006


def test_f3_migration_006_does_not_seed_pool2_config_blobs() -> None:
    """calibration / recontact / promo config blobs are out of foundation scope."""
    text = _migration_text()
    # Feature flags for those domains are allowed; config *blobs* are not.
    for blob_key in ("'calibration'", "'recontact'", "'promo'"):
        assert blob_key not in text
    assert "('calibration'" not in text
    assert "('recontact'" not in text
    assert "('promo'" not in text
