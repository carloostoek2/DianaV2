"""Unit tests for persona catalog loader (Anexo J.1 / J.2 / J.3.3 / J.5)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


_VALID_WEEKDAYS = frozenset(
    {"lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"}
)

_MIN_SCHEDULE = {
    "timezone": "America/Mexico_City",
    "default_responses": ["Pues aquí entre cosas jsjsjs y tú?"],
    "bloques": [
        {
            "dias": ["lunes"],
            "inicio": "09:00",
            "fin": "12:00",
            "actividad": "en el servicio social",
        }
    ],
}


def _minimal_catalog(**overrides: object) -> dict:
    base = {
        "voz_configurada": {
            "persona": "Eres Diana",
            "reglas_estilo": ["r1", "r2", "r3", "r4", "r5", "r6"],
        },
        "persona_facts": [
            {"id": "f1", "tema": ["familia"], "hecho": "x"},
        ],
        "voice_patterns": [
            {"id": "p1", "tags": ["a"], "patron": "x", "uso": "y"},
        ],
        "policies": [
            {"id": "pol", "tema": ["t"], "regla": "r"},
        ],
        "schedule": dict(_MIN_SCHEDULE),
    }
    base.update(overrides)
    return base


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

    # Communication standard (product): zero Mexican slang / profanity; warm base.
    joined_rules = " ".join(rules).lower()
    persona_l = voz["persona"].lower()
    assert "slang" in joined_rules or "slang" in persona_l
    assert any(
        token in joined_rules or token in persona_l
        for token in ("groser", "vulgar", "profan")
    )
    assert any(
        token in joined_rules or token in persona_l
        for token in ("cálid", "calid", "cercan", "alegr", "risue")
    )
    # First variable style: sensitive tone → acompañamiento (emotion triste/ansiosa).
    assert any("triste" in r.lower() or "ansiosa" in r.lower() for r in rules)
    assert any("acompañ" in r.lower() or "acompagn" in r.lower() for r in rules)

    # Always-on laughter voice: jsjs family, never classic jaja/haha.
    assert any("jsjs" in r.lower() for r in rules)
    assert any("jaja" in r.lower() for r in rules)

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


def test_load_persona_catalog_schedule_structure() -> None:
    """H9.2: production catalog ships fixed weekly agenda."""
    from diana.cognitive.persona_catalog import load_persona_catalog

    data = load_persona_catalog()
    schedule = data["schedule"]
    assert schedule["timezone"] == "America/Mexico_City"
    defaults = schedule["default_responses"]
    assert isinstance(defaults, list) and len(defaults) == 3
    assert all(isinstance(s, str) and s.strip() for s in defaults)
    bloques = schedule["bloques"]
    assert isinstance(bloques, list) and len(bloques) == 6
    for bloque in bloques:
        assert isinstance(bloque["dias"], list) and bloque["dias"]
        assert all(d in _VALID_WEEKDAYS for d in bloque["dias"])
        assert isinstance(bloque["inicio"], str) and len(bloque["inicio"]) == 5
        assert isinstance(bloque["fin"], str) and len(bloque["fin"]) == 5
        assert isinstance(bloque["actividad"], str) and bloque["actividad"].strip()
        assert bloque["inicio"] < bloque["fin"]


def test_load_rejects_missing_schedule() -> None:
    from diana.cognitive.persona_catalog import _parse_and_validate

    payload = _minimal_catalog()
    del payload["schedule"]
    with pytest.raises(ValueError, match="schedule"):
        _parse_and_validate(json.dumps(payload))


def test_load_rejects_empty_default_responses() -> None:
    from diana.cognitive.persona_catalog import _parse_and_validate

    schedule = dict(_MIN_SCHEDULE)
    schedule["default_responses"] = []
    with pytest.raises(ValueError, match="default_responses"):
        _parse_and_validate(json.dumps(_minimal_catalog(schedule=schedule)))


def test_load_rejects_bad_schedule_time() -> None:
    from diana.cognitive.persona_catalog import _parse_and_validate

    schedule = dict(_MIN_SCHEDULE)
    schedule["bloques"] = [
        {
            "dias": ["lunes"],
            "inicio": "9:00",
            "fin": "12:00",
            "actividad": "x",
        }
    ]
    with pytest.raises(ValueError, match="inicio|fin|time|HH:MM"):
        _parse_and_validate(json.dumps(_minimal_catalog(schedule=schedule)))


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

    base = _minimal_catalog(
        persona_facts=[{"id": "f1", "tema": [], "hecho": "x"}],
    )
    with pytest.raises(ValueError, match="tema"):
        _parse_and_validate(json.dumps(base))

    base = _minimal_catalog(
        persona_facts=[{"id": "f1", "tema": ["familia"], "hecho": "x"}],
        voice_patterns=[{"id": "p1", "tags": ["a"], "patron": "  ", "uso": "y"}],
    )
    with pytest.raises(ValueError, match="patron"):
        _parse_and_validate(json.dumps(base))


def test_validate_persona_catalog_accepts_minimal_and_roundtrip() -> None:
    """Pure dict validator: accepts a minimal valid catalog and is idempotent."""
    from diana.cognitive.persona_catalog import (
        load_persona_catalog,
        validate_persona_catalog,
    )

    data = validate_persona_catalog(_minimal_catalog())
    assert set(data) == {
        "voz_configurada",
        "persona_facts",
        "voice_patterns",
        "policies",
        "schedule",
    }
    # Round-trip over the real static catalog must be a no-op.
    real = load_persona_catalog()
    assert validate_persona_catalog(real) == real


def test_validate_persona_catalog_rejects_missing_schedule() -> None:
    from diana.cognitive.persona_catalog import validate_persona_catalog

    payload = _minimal_catalog()
    del payload["schedule"]
    with pytest.raises(ValueError, match="schedule"):
        validate_persona_catalog(payload)


def test_validate_persona_catalog_exported_in_all() -> None:
    import diana.cognitive.persona_catalog as pc

    assert "validate_persona_catalog" in pc.__all__
