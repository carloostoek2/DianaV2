"""Telegram layer may import aiogram; application/behavior still must not."""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TELEGRAM = REPO / "src" / "diana" / "telegram"
APPLICATION = REPO / "src" / "diana" / "application"
BEHAVIOR = REPO / "src" / "diana" / "behavior"


def _is_type_checking_guard(node: ast.AST) -> bool:
    """True for ``if TYPE_CHECKING:`` / ``if typing.TYPE_CHECKING:`` guards.

    Type-only imports create no runtime coupling, so the purity guard skips
    their subtrees.
    """
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: set[str] = set()

    def walk(node: ast.AST) -> None:
        if _is_type_checking_guard(node):
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
        for child in ast.iter_child_nodes(node):
            walk(child)

    walk(tree)
    return out


def test_telegram_may_import_aiogram() -> None:
    found = False
    for path in TELEGRAM.rglob("*.py"):
        for mod in _modules(path):
            if mod == "aiogram" or mod.startswith("aiogram."):
                found = True
    assert found, "expected telegram layer to use aiogram"


def test_application_still_forbids_aiogram() -> None:
    for path in APPLICATION.rglob("*.py"):
        for mod in _modules(path):
            assert not (mod == "aiogram" or mod.startswith("aiogram.")), path.name


def test_behavior_still_forbids_aiogram() -> None:
    for path in BEHAVIOR.rglob("*.py"):
        for mod in _modules(path):
            assert not (mod == "aiogram" or mod.startswith("aiogram.")), path.name
