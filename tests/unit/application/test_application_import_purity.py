"""Architecture boundary: application must not import aiogram."""

from __future__ import annotations

import ast
from pathlib import Path

APPLICATION_ROOT = Path(__file__).resolve().parents[3] / "src" / "diana" / "application"

FORBIDDEN_PREFIXES = (
    "aiogram",
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


def test_application_package_has_no_aiogram_imports() -> None:
    py_files = sorted(APPLICATION_ROOT.rglob("*.py"))
    assert py_files, "expected application package sources"
    violations: list[str] = []
    for path in py_files:
        for module in _imported_modules(path):
            if any(module == p or module.startswith(p + ".") for p in FORBIDDEN_PREFIXES):
                violations.append(f"{path.name}: {module}")
    assert violations == []
