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


__all__ = ["SqlSystemConfigStore"]
