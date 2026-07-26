"""Package data and env-driven application settings.

- ``Settings``: runtime configuration (env / .env) — lazy import so catalog
  loaders that only need package resources do not pull pydantic-settings.
- ``persona_diana.json``: static Anexo J catalog (package data)
"""

from __future__ import annotations

from typing import Any

__all__ = ["Settings"]


def __getattr__(name: str) -> Any:
    if name == "Settings":
        from diana.config.settings import Settings

        return Settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
