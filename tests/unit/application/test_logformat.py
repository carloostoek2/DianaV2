"""ColorExtraFormatter unit tests — console rendering of level + extra."""

from __future__ import annotations

import logging

from diana.application.logformat import ColorExtraFormatter


def _record(
    msg: str = "hola",
    *,
    level: int = logging.INFO,
    extra: dict | None = None,
    exc_info=None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="diana.test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    for key, value in (extra or {}).items():
        setattr(record, key, value)
    return record


def test_level_colored() -> None:
    out = ColorExtraFormatter().format(_record(level=logging.INFO))
    assert "\033[36m" in out
    assert "INFO" in out


def test_warning_and_error_colors() -> None:
    warning = ColorExtraFormatter().format(_record(level=logging.WARNING))
    error = ColorExtraFormatter().format(_record(level=logging.ERROR))
    assert "\033[33m" in warning
    assert "\033[31m" in error


def test_extra_rendered_as_key_value() -> None:
    out = ColorExtraFormatter().format(
        _record("coordinate_result", extra={"chat_id": 5, "action": "approve"})
    )
    assert "coordinate_result" in out
    assert "chat_id=5" in out
    assert "action=approve" in out


def test_internal_attrs_not_leaked() -> None:
    out = ColorExtraFormatter().format(_record("mi mensaje"))
    assert "mi mensaje" in out
    assert "msg=mi mensaje" not in out
    assert "name=diana.test" not in out
    assert "levelno=" not in out


def test_exc_info_includes_traceback() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        out = ColorExtraFormatter().format(_record("fallo", exc_info=True))
    assert "Traceback" in out
    assert "ValueError" in out
    assert "boom" in out
