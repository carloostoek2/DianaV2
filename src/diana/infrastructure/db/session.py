"""Async SQLAlchemy engine and session factory.

Callers in later items MUST inject a shared ``async_sessionmaker`` (or engine)
rather than calling ``get_session()`` / ``create_session_factory()`` with no
arguments. The uninjected path builds a new engine/pool per call and is only
acceptable for one-off scripts.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from diana.config import Settings


def create_engine(database_url: str | None = None) -> AsyncEngine:
    """Create an async engine from an explicit URL or Settings.database_url."""
    if database_url is None:
        database_url = Settings().database_url.get_secret_value()
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine | None = None) -> async_sessionmaker[AsyncSession]:
    """Build an async sessionmaker with expire_on_commit=False.

    Prefer passing a process-wide ``engine`` so the connection pool is shared.
    """
    eng = engine or create_engine()
    return async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)


async def get_session(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession and close it afterwards.

    Always pass ``session_factory`` from application wiring when available.
    """
    factory = session_factory or create_session_factory()
    async with factory() as session:
        yield session
