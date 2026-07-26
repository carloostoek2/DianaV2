"""Offline source asserts for F3 calibration migration (009)."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_009 = REPO_ROOT / "alembic" / "versions" / "009_f3_calibration.py"

REVISION = "009_f3_calibration"


def _migration_text() -> str:
    assert MIGRATION_009.is_file(), f"missing migration: {MIGRATION_009}"
    return MIGRATION_009.read_text(encoding="utf-8")


def _extract_seed_json(text: str, key: str) -> dict:
    pattern = rf"\('{re.escape(key)}',\s*'(\{{.*?\}})'::jsonb\)"
    match = re.search(pattern, text, re.DOTALL)
    assert match is not None, f"seed JSON for key {key!r} not found"
    return json.loads(match.group(1))


def test_009_file_exists_and_revision_chain() -> None:
    assert MIGRATION_009.is_file()
    text = _migration_text()
    assert f'revision: str = "{REVISION}"' in text
    assert (
        'down_revision: Union[str, Sequence[str], None] = "008_recontact_promo"'
        in text
    )
    assert len(REVISION) <= 32


def test_009_seeds_calibration_json_on_conflict_do_nothing() -> None:
    text = _migration_text()
    assert "ON CONFLICT (key) DO NOTHING" in text
    cal = _extract_seed_json(text, "calibration")
    assert cal["window_days"] == 30
    assert cal["min_samples"] == 50
    assert cal["autonomous_margin_min"] == 0.05
    assert cal["drift_alert_threshold"] == 0.1
    assert cal["drift_sample_size"] == 50
    assert cal["baseline_weeks"] == 4


def test_009_no_learning_metrics_alter() -> None:
    text = _migration_text()
    # Docstring may mention EAV learning_metrics; body must not ALTER it.
    assert "ALTER TABLE" not in text.upper() or "learning_metrics" not in text
    assert "ADD COLUMN" not in text.upper()
    assert "style_drift_score" not in text
    # No DDL beyond INSERT/DELETE seeds
    body = text.split("def upgrade", 1)[-1]
    assert "learning_metrics" not in body
    assert "create_table" not in body.lower()


def test_009_downgrade_deletes_calibration_key() -> None:
    text = _migration_text()
    assert "DELETE FROM system_config" in text
    assert "calibration" in text


def test_calibration_data_parsers() -> None:
    from uuid import uuid4

    from diana.infrastructure.db.repositories.calibration_data import (
        parse_evaluation_dims,
        row_to_calibration_sample,
    )

    assert parse_evaluation_dims(None) is None
    assert parse_evaluation_dims({"safety": 0.9}) is None
    dims = parse_evaluation_dims(
        {"safety": 0.9, "doctrine": 0.8, "naturalness": 0.7, "empathy": 0.5}
    )
    assert dims == {"safety": 0.9, "doctrine": 0.8, "naturalness": 0.7}

    tid = uuid4()
    sample = row_to_calibration_sample(
        turn_id=tid,
        evaluation={"safety": 0.5, "doctrine": 0.4, "naturalness": 0.6},
        corrected=True,
    )
    assert sample is not None
    assert sample.turn_id == tid
    assert sample.corrected is True
    assert sample.safety == 0.5
