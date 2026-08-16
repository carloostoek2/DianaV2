"""PoliciesRepo vip_id helpers: visibility clause + dict mapping. No Postgres."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from diana.infrastructure.db.models import Policy
from diana.infrastructure.db.repositories import policies as policies_mod


def _compile(clause) -> str:
    return str(
        clause.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_policy_vip_id_visibility_atencion_is_null_only() -> None:
    sql = _compile(
        policies_mod.vip_id_visibility_clause(Policy.vip_id, None)
    ).upper()
    assert "IS NULL" in sql
    assert " OR " not in sql


def test_policy_vip_id_visibility_vip_is_null_or_equals() -> None:
    vip_id = uuid4()
    sql = _compile(
        policies_mod.vip_id_visibility_clause(Policy.vip_id, vip_id)
    ).upper()
    assert "IS NULL" in sql
    assert " OR " in sql
    assert str(vip_id).upper() in sql


def test_policy_to_dict_includes_vip_id() -> None:
    vip_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        trigger_description="when VIP asks price",
        rule="do not discount",
        scope="all",
        is_active=True,
        valid_until=None,
        source_query_id=None,
        vip_id=vip_id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    out = policies_mod.policy_to_dict(row)  # type: ignore[arg-type]
    assert out["vip_id"] == str(vip_id)
    assert out["scope"] == "all"

    row.vip_id = None
    out = policies_mod.policy_to_dict(row)  # type: ignore[arg-type]
    assert out["vip_id"] is None
