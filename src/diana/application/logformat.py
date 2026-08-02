"""Console log formatting: per-level ANSI color + structured `extra` fields.

Renders `%(asctime)s %(levelname)-7s | %(message)s` with the level name
colored, then appends any ``extra`` fields as ``key=value`` so structured
event logs (event name + extra) become readable in the console instead of
showing a bare event name.
"""

from __future__ import annotations

import logging
import sys

_RESET = "\033[0m"

_LEVEL_COLORS: dict[int, str] = {
    logging.DEBUG: "\033[90m",  # gray
    logging.INFO: "\033[36m",  # cyan
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[1;31m",  # bold red
}

# Standard attributes every LogRecord carries; anything else on the record is
# an explicit `extra` field the caller attached and must be rendered.
_INTERNAL_ATTRS: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class ColorExtraFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, self.datefmt)
        level = record.levelname
        color = _LEVEL_COLORS.get(record.levelno, "")
        colored = f"{color}{level:<7}{_RESET}"
        line = f"{ts} {colored} | {record.getMessage()}"

        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _INTERNAL_ATTRS and not key.startswith("_")
        }
        if extra:
            line += " " + " ".join(f"{key}={value}" for key, value in extra.items())

        if record.exc_info:
            exc_info = record.exc_info
            if not isinstance(exc_info, tuple):
                exc_info = sys.exc_info()
            line += "\n" + self.formatException(exc_info)
        return line
