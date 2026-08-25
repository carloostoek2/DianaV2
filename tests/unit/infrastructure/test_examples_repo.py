"""ExamplesRepo query helpers: quality validation, vip visibility, gold-first order.

Compiles SQLAlchemy clauses with the PostgreSQL dialect — no AsyncSession/PG.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from diana.infrastructure.db.models import Example
from diana.infrastructure.db.repositories import examples as examples_mod


def _compile(clause) -> str:
    return str(
        clause.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_validate_example_quality_accepts_standard_and_gold() -> None:
    validate = examples_mod.validate_example_quality
    assert validate("standard") == "standard"
    assert validate("gold") == "gold"


def test_validate_example_quality_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="quality must be"):
        examples_mod.validate_example_quality("bogus")


def test_vip_id_visibility_atencion_is_null_only() -> None:
    sql = _compile(
        examples_mod.vip_id_visibility_clause(Example.vip_id, None)
    ).upper()
    assert "IS NULL" in sql
    assert " OR " not in sql


def test_vip_id_visibility_vip_is_null_or_equals() -> None:
    vip_id = uuid4()
    sql = _compile(
        examples_mod.vip_id_visibility_clause(Example.vip_id, vip_id)
    ).upper()
    assert "IS NULL" in sql
    assert " OR " in sql
    assert str(vip_id).upper() in sql


def test_example_similarity_order_gold_case_before_cosine() -> None:
    gold_first, _cosine = examples_mod.example_similarity_order([0.1] * 384)
    compiled = _compile(gold_first).upper()
    assert "QUALITY" in compiled
    assert "GOLD" in compiled
    assert "CASE" in compiled
    stmt = select(Example).order_by(gold_first, _cosine)
    assert "CASE" in str(stmt.compile(dialect=postgresql.dialect())).upper()


def test_example_to_dict_includes_quality_and_vip_id() -> None:
    vip_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        turn_text="t",
        draft_text="d",
        corrected_text="c",
        context={},
        is_counter_example=False,
        quality="gold",
        vip_id=vip_id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    out = examples_mod.example_to_dict(row)  # type: ignore[arg-type]
    assert out["quality"] == "gold"
    assert out["vip_id"] == str(vip_id)

    row.vip_id = None
    row.quality = "standard"
    out = examples_mod.example_to_dict(row)  # type: ignore[arg-type]
    assert out["quality"] == "standard"
    assert out["vip_id"] is None


def test_list_gold_global_clause_globals_only() -> None:
    """list_gold_global builds a SELECT restricted to global gold rows.

    Read-only general-context source for gray-zone proposals: quality=gold,
    NOT counter-example, vip_id IS NULL (never a VIP's own examples).
    """
    import inspect

    src = inspect.getsource(examples_mod.ExamplesRepo.list_gold_global)
    assert "quality" in src.lower()
    assert "gold" in src
    assert "vip_id.is_(None)" in src or "vip_id == None" in src or "is_(None)" in src
    assert "is_counter_example.is_(False)" in src
    # No insert/update/delete allowed in a read-only general-context source.
    for banned in ("session.add", "session.execute(update", "session.execute(delete"):
        assert banned not in src
