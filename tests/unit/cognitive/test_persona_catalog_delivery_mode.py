"""REQ-ATN-05: optional ``delivery_mode`` in ``validate_persona_catalog``.

The field is optional-with-default: absent → no-op (consumer applies the
default at read time); invalid literal → ValueError. No schema/migration.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from diana.cognitive.persona_catalog import (
    get_persona_catalog,
    validate_persona_catalog,
)


def _base() -> dict:
    return deepcopy(get_persona_catalog())


def test_delivery_mode_optional_absent_ok() -> None:
    """Absent field validates and returns the dict unchanged (no default added)."""
    base = _base()
    result = validate_persona_catalog(base)
    assert result is base
    assert "delivery_mode" not in result


def test_delivery_mode_supervised_ok() -> None:
    base = _base()
    base["delivery_mode"] = "supervised"
    assert validate_persona_catalog(base)["delivery_mode"] == "supervised"


def test_delivery_mode_autonomous_ok() -> None:
    base = _base()
    base["delivery_mode"] = "autonomous"
    assert validate_persona_catalog(base)["delivery_mode"] == "autonomous"


def test_delivery_mode_fake_delivery_ok() -> None:
    base = _base()
    base["delivery_mode"] = "fake_delivery"
    assert validate_persona_catalog(base)["delivery_mode"] == "fake_delivery"


def test_delivery_mode_invalid_raises() -> None:
    base = _base()
    base["delivery_mode"] = "fast"
    with pytest.raises(ValueError, match="delivery_mode must be"):
        validate_persona_catalog(base)


def test_delivery_mode_null_ignored() -> None:
    """Field present but None → skip check, same as absent (no default injected)."""
    base = _base()
    base["delivery_mode"] = None
    result = validate_persona_catalog(base)
    assert result is base
    assert result["delivery_mode"] is None
