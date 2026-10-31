"""Migración 038: upgrade y downgrade fijan lock_timeout antes de tocar tablas.

``policies`` y ``gray_zone_queries`` se leen en cada turno; un ALTER que queda
en cola detrás de una transacción larga bloquea también todas las lecturas que
llegan después. Con ``lock_timeout`` la migración falla rápido y se reintenta,
en vez de congelar el bot. Este test no necesita base de datos: registra las
operaciones de Alembic en orden.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_MIGRATION = (
    Path(__file__).resolve().parents[3] / "alembic" / "versions" / "038_policy_topics.py"
)


class _RecordingOp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql: str) -> None:
        self.calls.append(("execute", (sql,)))

    def add_column(self, table: str, column: object) -> None:
        self.calls.append(("add_column", (table,)))

    def drop_column(self, table: str, column: str) -> None:
        self.calls.append(("drop_column", (table, column)))


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_038", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_migration_038_sets_lock_timeout_before_any_ddl(
    monkeypatch: pytest.MonkeyPatch, direction: str
) -> None:
    module = _load_migration()
    recorder = _RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    getattr(module, direction)()

    assert recorder.calls, "la migración no ejecutó nada"
    first_name, first_args = recorder.calls[0]
    assert first_name == "execute"
    assert first_args[0] == "SET lock_timeout = '5s'"
    ddl = [name for name, _ in recorder.calls[1:]]
    assert ddl and all(name in {"add_column", "drop_column"} for name in ddl)


def test_migration_038_downgrade_drops_both_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_migration()
    recorder = _RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.downgrade()

    dropped = {args for name, args in recorder.calls if name == "drop_column"}
    assert dropped == {("gray_zone_queries", "topics"), ("policies", "temas")}
