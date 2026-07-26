"""Unit tests for persona catalog loader (Anexo J.1 / J.2 / J.3.3 / J.5)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_load_persona_catalog_counts_and_structure() -> None:
    from diana.cognitive.persona_catalog import load_persona_catalog

    data = load_persona_catalog()
    assert len(data["persona_facts"]) == 9
    assert len(data["voice_patterns"]) == 11
    assert len(data["policies"]) == 6

    voz = data["voz_configurada"]
    assert isinstance(voz["persona"], str) and voz["persona"].strip()
    assert "Diana" in voz["persona"]
    assert "warm and professional VIP chat assistant" not in voz["persona"]

    rules = voz["reglas_estilo"]
    assert isinstance(rules, list) and len(rules) >= 6
    assert all(isinstance(r, str) and r.strip() for r in rules)
    # At least one rule mentions closing '?' without requiring opening '¿'
    assert any("?" in r for r in rules)

    for fact in data["persona_facts"]:
        assert "id" in fact and fact["id"]
        assert "tema" in fact
        assert "hecho" in fact and isinstance(fact["hecho"], str)
        tema = fact["tema"]
        assert isinstance(tema, (str, list))
        if isinstance(tema, list):
            assert all(isinstance(t, str) for t in tema)

    for policy in data["policies"]:
        assert "id" in policy and policy["id"]
        assert "tema" in policy
        assert "regla" in policy and isinstance(policy["regla"], str)

    for pattern in data["voice_patterns"]:
        assert "id" in pattern and pattern["id"]
        assert isinstance(pattern["tags"], list)
        assert "patron" in pattern and pattern["patron"]
        assert "uso" in pattern and pattern["uso"]


def test_load_persona_catalog_fail_loud_on_missing_file() -> None:
    from diana.cognitive.persona_catalog import load_persona_catalog

    class _Missing:
        def joinpath(self, name: str) -> Path:
            return Path("/nonexistent/persona_diana.json")

    with patch(
        "diana.cognitive.persona_catalog.importlib.resources.files",
        return_value=_Missing(),
    ):
        with pytest.raises((FileNotFoundError, OSError, ValueError)):
            load_persona_catalog()


def test_load_persona_catalog_fail_loud_on_invalid_payload(tmp_path: Path) -> None:
    from diana.cognitive.persona_catalog import load_persona_catalog

    bad = tmp_path / "persona_diana.json"
    bad.write_text(json.dumps({"voz_configurada": {}}), encoding="utf-8")

    class _TmpRoot:
        def joinpath(self, name: str) -> Path:
            return bad

    with patch(
        "diana.cognitive.persona_catalog.importlib.resources.files",
        return_value=_TmpRoot(),
    ):
        with pytest.raises(ValueError):
            load_persona_catalog()



def test_catalog_package_resource_readable() -> None:
    """Issue 4: persona_diana.json must be importlib.resources-readable package data."""
    import importlib.resources

    raw = (
        importlib.resources.files("diana.config")
        .joinpath("persona_diana.json")
        .read_text(encoding="utf-8")
    )
    assert "voz_configurada" in raw
    assert "persona_facts" in raw


def test_load_rejects_empty_tema_and_empty_patron() -> None:
    """Issue 9: empty tema/tags/patron/uso rejected at load."""
    from diana.cognitive.persona_catalog import _parse_and_validate
    import json

    base = {
        "voz_configurada": {
            "persona": "Eres Diana",
            "reglas_estilo": ["r1", "r2", "r3", "r4", "r5", "r6"],
        },
        "persona_facts": [
            {"id": "f1", "tema": [], "hecho": "x"},
        ],
        "voice_patterns": [
            {"id": "p1", "tags": ["a"], "patron": "x", "uso": "y"},
        ],
        "policies": [
            {"id": "pol", "tema": ["t"], "regla": "r"},
        ],
    }
    with pytest.raises(ValueError, match="tema"):
        _parse_and_validate(json.dumps(base))

    base["persona_facts"] = [{"id": "f1", "tema": ["familia"], "hecho": "x"}]
    base["voice_patterns"] = [
        {"id": "p1", "tags": ["a"], "patron": "  ", "uso": "y"},
    ]
    with pytest.raises(ValueError, match="patron"):
        _parse_and_validate(json.dumps(base))
