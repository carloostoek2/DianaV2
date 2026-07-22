"""Telegram layer may import aiogram; application/behavior still must not."""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TELEGRAM = REPO / "src" / "diana" / "telegram"
APPLICATION = REPO / "src" / "diana" / "application"
BEHAVIOR = REPO / "src" / "diana" / "behavior"


def _modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
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
