"""SQL repo pure mappers / shapes without live Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from diana.infrastructure.db.repositories.history import rows_to_recent_messages
from diana.infrastructure.db.repositories.turns import turn_orm_to_record
from diana.infrastructure.db.repositories.vips import vip_is_allowed, vip_orm_to_record


def test_vip_orm_to_record_mapper() -> None:
    vip_id = uuid4()
    paused = datetime(2026, 6, 1, tzinfo=UTC)
    orm = SimpleNamespace(
        id=vip_id,
        telegram_user_id=12345,
        display_name="Bob",
        is_active=True,
        paused_until=paused,
        frozen_until=None,
        auto_send=False,
    )
    rec = vip_orm_to_record(orm)  # type: ignore[arg-type]
    assert rec.id == vip_id
    assert rec.telegram_user_id == 12345
    assert rec.display_name == "Bob"
    assert rec.is_active is True
    assert rec.paused_until == paused
    assert rec.frozen_until is None
    assert rec.auto_send is False


def test_vip_orm_to_record_maps_auto_send_true() -> None:
    vip_id = uuid4()
    orm = SimpleNamespace(
        id=vip_id,
        telegram_user_id=99,
        display_name=None,
        is_active=True,
        paused_until=None,
        frozen_until=None,
        auto_send=True,
    )
    rec = vip_orm_to_record(orm)  # type: ignore[arg-type]
    assert rec.auto_send is True


def test_vip_is_allowed_respects_pause() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    rec = vip_orm_to_record(
        SimpleNamespace(
            id=uuid4(),
            telegram_user_id=1,
            display_name=None,
            is_active=True,
            paused_until=now + timedelta(hours=1),
            frozen_until=None,
            auto_send=False,
        )  # type: ignore[arg-type]
    )
    assert vip_is_allowed(rec, now=now) is False
    assert vip_is_allowed(rec, now=now + timedelta(hours=2)) is True


def test_vip_inactive_not_allowed() -> None:
    rec = vip_orm_to_record(
        SimpleNamespace(
            id=uuid4(),
            telegram_user_id=1,
            display_name=None,
            is_active=False,
            paused_until=None,
            frozen_until=None,
            auto_send=False,
        )  # type: ignore[arg-type]
    )
    assert vip_is_allowed(rec) is False


def test_history_get_recent_desc_then_chronological() -> None:
    t0 = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    # Simulate SQL ORDER BY timestamp DESC
    rows_desc = [
        SimpleNamespace(
            role="vip", text="c", telegram_message_id=3, timestamp=t2
        ),
        SimpleNamespace(
            role="bot", text="b", telegram_message_id=2, timestamp=t1
        ),
        SimpleNamespace(
            role="vip", text="a", telegram_message_id=1, timestamp=t0
        ),
    ]
    out = rows_to_recent_messages(rows_desc, limit=3)  # type: ignore[arg-type]
    assert [m["text"] for m in out] == ["a", "b", "c"]
    limited = rows_to_recent_messages(rows_desc, limit=2)  # type: ignore[arg-type]
    assert [m["text"] for m in limited] == ["b", "c"]


def test_turn_orm_to_record_maps_error() -> None:
    turn_id = uuid4()
    vip_id = uuid4()
    orm = SimpleNamespace(
        id=turn_id,
        chat_id=99,
        status="failed",
        vip_id=vip_id,
        trigger_message_id=42,
        superseded_by=None,
        error="analista_schema_invalido",
        channel_type="vip",
    )
    rec = turn_orm_to_record(orm)  # type: ignore[arg-type]
    assert rec.id == turn_id
    assert rec.chat_id == 99
    assert rec.status == "failed"
    assert rec.vip_id == vip_id
    assert rec.trigger_message_id == 42
    assert rec.error == "analista_schema_invalido"
    assert rec.channel_type == "vip"


def test_turn_orm_to_record_error_none_when_absent() -> None:
    rec = turn_orm_to_record(
        SimpleNamespace(
            id=uuid4(),
            chat_id=1,
            status="received",
            vip_id=None,
            trigger_message_id=None,
            superseded_by=None,
            error=None,
            channel_type="vip",
        )  # type: ignore[arg-type]
    )
    assert rec.error is None
    assert rec.channel_type == "vip"


def test_infrastructure_has_no_aiogram_imports() -> None:
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "src" / "diana" / "infrastructure"
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "aiogram" or alias.name.startswith("aiogram."):
                        violations.append(f"{path.name}: {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "aiogram" or node.module.startswith("aiogram."):
                    violations.append(f"{path.name}: {node.module}")
    assert violations == []


def test_profile_to_dict_mapper() -> None:
    """Pure mapper: Profile ORM-like row → dict with tipo/content (no live DB)."""
    from diana.infrastructure.db.repositories.profiles import profile_to_dict

    vip_id = uuid4()
    created = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    updated = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    row = SimpleNamespace(
        vip_id=vip_id,
        tipo="summary",
        content={"fact": "prefers morning"},
        created_at=created,
        updated_at=updated,
    )
    out = profile_to_dict(row)  # type: ignore[arg-type]
    assert out["vip_id"] == str(vip_id)
    assert out["tipo"] == "summary"
    assert out["content"] == {"fact": "prefers morning"}
    assert out["created_at"] == created.isoformat()
    assert out["updated_at"] == updated.isoformat()


def test_profiles_repo_source_scopes_by_vip_id() -> None:
    """BR-15 source lock: every ProfilesRepo method filters by vip_id."""
    from pathlib import Path

    import diana

    root = Path(diana.__file__).resolve().parent
    source = (
        root / "infrastructure" / "db" / "repositories" / "profiles.py"
    ).read_text(encoding="utf-8")
    assert "async def get_by_vip_id" in source
    assert "Profile.vip_id == vip_id" in source
    assert "select(Profile)" in source
    # Shared load helper is the single scoped SELECT.
    assert "async def _load" in source
    assert "select(Profile).where(Profile.vip_id == vip_id)" in source
    # Mutators exist (owner profile write path) and all go through _load.
    for name in (
        "set_fact",
        "delete_fact",
        "add_note",
        "delete_note",
        "delete_by_vip_id",
    ):
        assert f"async def {name}" in source
    # get + 4 writers + delete_by_vip_id
    assert source.count("await self._load(session, vip_id)") >= 6
    # No unscoped list-all helper.
    assert "def find_all" not in source
    assert "vip_id" in source
