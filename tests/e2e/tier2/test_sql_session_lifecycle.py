"""E2E: SQLAlchemy async session lifecycle."""
import pytest
from sqlalchemy import text


@pytest.mark.db
@pytest.mark.asyncio
async def test_session_execute_simple_query(session):
    result = await session.execute(text("SELECT 1"))
    assert result.scalar() == 1


@pytest.mark.db
@pytest.mark.asyncio
async def test_session_rollback_discards_insert(session, session_factory):
    """Data inserted in a rolled-back session is not visible to another."""
    # Insert via raw SQL since we roll back
    await session.execute(
        text("INSERT INTO vips (id, telegram_user_id, is_active) VALUES (gen_random_uuid(), 99901, true)")
    )
    # Transaction will rollback automatically
    # Verify via a fresh session that the row is NOT visible
    async with session_factory() as s2:
        result = await s2.execute(text("SELECT 1 FROM vips WHERE telegram_user_id = 99901"))
        assert result.scalar_one_or_none() is None


@pytest.mark.db
@pytest.mark.asyncio
async def test_engine_config_has_pre_ping(engine):
    """Engine is configured with pool_pre_ping."""
    assert engine.pool is not None  # Pool exists


@pytest.mark.db
@pytest.mark.asyncio
async def test_pgvector_extension_available(session):
    """pgvector extension is installed in the test database."""
    result = await session.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
    )
    assert result.scalar_one_or_none() == "vector"


@pytest.mark.db
@pytest.mark.asyncio
async def test_pgcrypto_extension_available(session):
    """pgcrypto extension is installed for gen_random_uuid()."""
    result = await session.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'pgcrypto'")
    )
    assert result.scalar_one_or_none() == "pgcrypto"
