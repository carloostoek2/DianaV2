"""E2E: PoliciesRepo.find_active_by_topics (migración 038, doctrinas por tema).

The topic path is what makes a gray-zone doctrine findable when the VIP says
the same thing in different words, so the filters that decide WHICH rules can
reach WHICH chat must be verified against real PostgreSQL, not mocks:

- jsonb overlap (``temas ?| signals``) matches and does not match;
- inactive or expired rows never surface;
- ``vip_id`` visibility (global vs per-VIP) and the atencion scope filter;
- the optional similarity floor keeps unrelated rules out.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from diana.infrastructure.db.repositories.policies import PoliciesRepo

_DIM = 384


def _unit(index: int) -> list[float]:
    vec = [0.0] * _DIM
    vec[index] = 1.0
    return vec


def _seed(index: int, scale: float = 1.0) -> list[float]:
    """Unit-ish vector shifted so cosine against ``_unit(0)`` is controlled."""
    vec = [0.0] * _DIM
    vec[0] = scale
    vec[index] = (1 - scale**2) ** 0.5 if scale <= 1 else 0.0
    return vec


async def _create_vip(session_factory, telegram_user_id: int):
    async with session_factory() as session:
        vip_id = (
            await session.execute(
                text(
                    "INSERT INTO vips (telegram_user_id) VALUES (:t) RETURNING id"
                ),
                {"t": telegram_user_id},
            )
        ).scalar_one()
        await session.commit()
        return vip_id


async def _insert_policy(
    session_factory,
    *,
    temas: list[str],
    embedding: list[float],
    scope: str = "all",
    is_active: bool = True,
    valid_until: datetime | None = None,
    vip_id=None,
    rule: str = "regla de prueba",
):
    async with session_factory() as session:
        policy_id = (
            await session.execute(
                text(
                    "INSERT INTO policies "
                    "(trigger_description, rule, scope, is_active, temas, "
                    " embedding, valid_until, vip_id) "
                    "VALUES (:t, :r, :s, :a, CAST(:temas AS jsonb), "
                    "        CAST(:emb AS vector), :vu, :vip) RETURNING id"
                ),
                {
                    "t": "disparador de prueba",
                    "r": rule,
                    "s": scope,
                    "a": is_active,
                    "temas": '["' + '","'.join(temas) + '"]',
                    "emb": "[" + ",".join(str(x) for x in embedding) + "]",
                    "vu": valid_until,
                    "vip": vip_id,
                },
            )
        ).scalar_one()
        await session.commit()
        return policy_id


async def _cleanup(session_factory, ids: list) -> None:
    if not ids:
        return
    async with session_factory() as session:
        await session.execute(
            text("DELETE FROM policies WHERE id = ANY(:ids)"), {"ids": ids}
        )
        await session.commit()


async def _cleanup_vips(session_factory, ids: list) -> None:
    if not ids:
        return
    async with session_factory() as session:
        await session.execute(
            text("DELETE FROM vips WHERE id = ANY(:ids)"), {"ids": ids}
        )
        await session.commit()


@pytest.mark.db
@pytest.mark.asyncio
async def test_topic_match_returns_overlapping_active_policy(session_factory):
    repo = PoliciesRepo(session_factory)
    hit = await _insert_policy(
        session_factory, temas=["conocerse", "dinamica_novia_virtual"], embedding=_unit(0)
    )
    miss = await _insert_policy(
        session_factory, temas=["contenido"], embedding=_unit(0)
    )
    try:
        rows = await repo.find_active_by_topics(["conocerse"])
        ids = {row["id"] for row in rows}
        assert str(hit) in ids
        assert str(miss) not in ids
        matched = next(row for row in rows if row["id"] == str(hit))
        assert matched["temas"] == ["conocerse", "dinamica_novia_virtual"]
    finally:
        await _cleanup(session_factory, [hit, miss])


@pytest.mark.db
@pytest.mark.asyncio
async def test_topic_match_excludes_inactive_and_expired(session_factory):
    repo = PoliciesRepo(session_factory)
    # Tema único: la copia restaurada puede traer políticas reales con temas
    # comunes, así que la prueba no puede exigir un resultado global vacío.
    tema = f"tema_efimero_{uuid4().hex}"
    expired = await _insert_policy(
        session_factory,
        temas=[tema],
        embedding=_unit(0),
        valid_until=datetime.now(UTC) - timedelta(days=1),
    )
    inactive = await _insert_policy(
        session_factory, temas=[tema], embedding=_unit(0), is_active=False
    )
    try:
        ids = {row["id"] for row in await repo.find_active_by_topics([tema])}
        assert str(expired) not in ids
        assert str(inactive) not in ids
    finally:
        await _cleanup(session_factory, [expired, inactive])


@pytest.mark.db
@pytest.mark.asyncio
async def test_topic_match_respects_vip_visibility(session_factory):
    repo = PoliciesRepo(session_factory)
    # Identificadores únicos: la misma base puede reutilizarse entre corridas.
    vip_a = await _create_vip(session_factory, uuid4().int % 9_000_000_000 + 1_000)
    vip_b = await _create_vip(session_factory, uuid4().int % 9_000_000_000 + 1_000)
    scoped = await _insert_policy(
        session_factory, temas=["conocerse"], embedding=_unit(0), scope="vip", vip_id=vip_a
    )
    global_rule = await _insert_policy(
        session_factory, temas=["conocerse"], embedding=_unit(0)
    )
    try:
        own = {
            row["id"]
            for row in await repo.find_active_by_topics(["conocerse"], vip_id=vip_a)
        }
        other = {
            row["id"]
            for row in await repo.find_active_by_topics(["conocerse"], vip_id=vip_b)
        }
        atencion = {
            row["id"]
            for row in await repo.find_active_by_topics(
                ["conocerse"], scope="all", vip_id=None
            )
        }
        assert str(scoped) in own and str(global_rule) in own
        assert str(scoped) not in other and str(global_rule) in other
        assert str(scoped) not in atencion and str(global_rule) in atencion
    finally:
        await _cleanup(session_factory, [scoped, global_rule])
        await _cleanup_vips(session_factory, [vip_a, vip_b])


@pytest.mark.db
@pytest.mark.asyncio
async def test_topic_match_applies_similarity_floor(session_factory):
    repo = PoliciesRepo(session_factory)
    close = await _insert_policy(
        session_factory, temas=["conocerse"], embedding=_seed(1, scale=0.95)
    )
    far = await _insert_policy(
        session_factory, temas=["conocerse"], embedding=_unit(1)
    )
    try:
        rows = await repo.find_active_by_topics(
            ["conocerse"], embedding=_unit(0), min_similarity=0.30
        )
        ids = {row["id"] for row in rows}
        assert str(close) in ids
        assert str(far) not in ids
    finally:
        await _cleanup(session_factory, [close, far])
