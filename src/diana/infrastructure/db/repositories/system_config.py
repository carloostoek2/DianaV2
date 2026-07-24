"""SqlSystemConfigStore — read forbidden_keywords and optional thresholds."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import SystemConfig


class SqlSystemConfigStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get(self, key: str) -> Any | None:
        async with self._sf() as session:
            row = await session.get(SystemConfig, key)
            return row.value if row else None

    async def get_forbidden_keywords(self) -> list[str]:
        value = await self.get("forbidden_keywords")
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, dict) and "keywords" in value:
            return [str(v) for v in value["keywords"]]
        return []

    async def get_eval_thresholds(self) -> dict[str, Any]:
        value = await self.get("eval_thresholds")
        return dict(value) if isinstance(value, dict) else {}

    async def get_feature_flags(self) -> dict[str, bool]:
        """Read all FEATURE_* keys from system_config. Returns {key: bool_value}.

        If a known feature flag key is missing from the DB, it is omitted
        from the returned dict (caller applies defaults from Settings).
        """
        async with self._sf() as session:
            result = await session.execute(
                select(SystemConfig.key, SystemConfig.value).where(
                    SystemConfig.key.startswith("FEATURE_")
                )
            )
            flags: dict[str, bool] = {}
            for key, value in result.all():
                if isinstance(value, bool):
                    flags[key] = value
                elif isinstance(value, str):
                    flags[key] = value.lower() in ("true", "1", "yes", "on")
                elif isinstance(value, (int, float)):
                    flags[key] = bool(value)
                # Any other type → skip (no guesswork)
            return flags


__all__ = ["SqlSystemConfigStore"]
