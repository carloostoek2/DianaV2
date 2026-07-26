"""Offline source + ORM asserts for F3 recontact/promo schema (008)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from diana.infrastructure.db.models import Base

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_008 = REPO_ROOT / "alembic" / "versions" / "008_recontact_promo.py"

REVISION = "008_recontact_promo"


def _migration_text() -> str:
    assert MIGRATION_008.is_file(), f"missing migration: {MIGRATION_008}"
    return MIGRATION_008.read_text(encoding="utf-8")


def _extract_seed_json(text: str, key: str) -> dict:
    """Parse exact JSON blob bound to a system_config seed key."""
    pattern = rf"\('{re.escape(key)}',\s*'(\{{.*?\}})'::jsonb\)"
    match = re.search(pattern, text, re.DOTALL)
    assert match is not None, f"seed JSON for key {key!r} not found"
    return json.loads(match.group(1))


def test_008_file_exists_and_revision_chain() -> None:
    assert MIGRATION_008.is_file()
    text = _migration_text()
    assert f'revision: str = "{REVISION}"' in text
    assert (
        'down_revision: Union[str, Sequence[str], None] = "007_vip_auto_send"'
        in text
    )
    assert len(REVISION) <= 32


def test_008_creates_three_tables_and_indexes() -> None:
    text = _migration_text()
    for table in ("recontact_schedules", "promo_triggers", "promo_executions"):
        assert f'"{table}"' in text or f"'{table}'" in text

    # Indexes: recontact due lookups + promo history
    assert "next_contact_at" in text and "status" in text
    assert "ix_recontact_schedules_next_status" in text or (
        "CREATE INDEX" in text and "next_contact_at" in text
    )
    assert "ix_promo_executions_chat_trigger_sent" in text or (
        "chat_id" in text and "trigger_id" in text and "sent_at" in text
    )


def test_008_promo_triggers_has_repeat_first_message() -> None:
    text = _migration_text()
    assert "repeat_first_message" in text
    # Column must appear in promo_triggers create path
    assert "promo_triggers" in text


def test_008_seeds_system_config_recontact_and_promo() -> None:
    text = _migration_text()
    assert "ON CONFLICT (key) DO NOTHING" in text
    recontact = _extract_seed_json(text, "recontact")
    promo = _extract_seed_json(text, "promo")

    assert isinstance(recontact.get("inactivity_days"), int)
    templates = recontact.get("templates")
    assert isinstance(templates, list) and len(templates) > 0
    assert all(isinstance(t, str) and t for t in templates)
    assert promo.get("repeat_days") == 30


def test_008_seeds_promo_trigger_rows() -> None:
    text = _migration_text()
    assert "INSERT INTO promo_triggers" in text
    assert "response_sequence" in text
    assert "repeat_first_message" in text

    # At least one known trigger phrase (case-friendly Spanish)
    lowered = text.lower()
    assert (
        "información" in lowered
        or "promociones" in lowered
        or "precios" in lowered
    )

    # Feminine first-person intent spot-checks in seed copy
    assert "te cuento" in lowered or "te mando" in lowered or "me acordé" in lowered


def test_orm_models_expose_recontact_promo_tables() -> None:
    tables = set(Base.metadata.tables.keys())
    assert "recontact_schedules" in tables
    assert "promo_triggers" in tables
    assert "promo_executions" in tables

    from diana.infrastructure.db.models import (
        PromoExecution,
        PromoTrigger,
        RecontactSchedule,
    )

    recontact_cols = set(RecontactSchedule.__table__.c.keys())
    assert {
        "id",
        "vip_id",
        "last_contact_at",
        "next_contact_at",
        "status",
        "created_at",
    }.issubset(recontact_cols)

    promo_trigger_cols = set(PromoTrigger.__table__.c.keys())
    assert {
        "id",
        "trigger_text",
        "response_sequence",
        "repeat_first_message",
        "is_active",
        "created_at",
    }.issubset(promo_trigger_cols)

    promo_exec_cols = set(PromoExecution.__table__.c.keys())
    assert {
        "id",
        "chat_id",
        "trigger_id",
        "sent_at",
        "sequence_sent",
        "status",
    }.issubset(promo_exec_cols)

    # FK: recontact vip_id → vips
    vip_fks = list(RecontactSchedule.__table__.c.vip_id.foreign_keys)
    assert len(vip_fks) == 1
    assert vip_fks[0].column.table.name == "vips"

    # FK: promo_executions.trigger_id → promo_triggers
    trigger_fks = list(PromoExecution.__table__.c.trigger_id.foreign_keys)
    assert len(trigger_fks) == 1
    assert trigger_fks[0].column.table.name == "promo_triggers"
