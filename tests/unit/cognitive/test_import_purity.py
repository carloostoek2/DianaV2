"""Architecture boundary: cognitive must not import infra/telegram/behavior stacks."""

from __future__ import annotations

import ast
from pathlib import Path

COGNITIVE_ROOT = Path(__file__).resolve().parents[3] / "src" / "diana" / "cognitive"

FORBIDDEN_PREFIXES = (
    "sqlalchemy",
    "aiogram",
    "telegram",
    "diana.infrastructure",
    "diana.telegram",
    "diana.behavior",
    "diana.learning",
    "diana.llm",
    "diana.application",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_cognitive_package_has_no_forbidden_imports() -> None:
    py_files = sorted(COGNITIVE_ROOT.rglob("*.py"))
    assert py_files, "expected cognitive package sources"
    violations: list[str] = []
    for path in py_files:
        for module in _imported_modules(path):
            if any(module == p or module.startswith(p + ".") for p in FORBIDDEN_PREFIXES):
                violations.append(f"{path.name}: {module}")
    assert violations == []
