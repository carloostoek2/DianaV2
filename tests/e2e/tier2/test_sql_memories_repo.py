"""E2E: MemoriesRepo writer + visibility filter + VIP isolation (BR-15)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select, text

from diana.application.ports import MemoryInsert
from diana.infrastructure.db.repositories.memories import (
    MemoriesRepo,
    memory_to_dict,
)

_EMBEDDING_384 = [0.1] * 384
_EMBEDDING_SQL = "[" + ",".join(["0.1"] * 384) + "]"


async def _create_vip(session_factory, telegram_user_id: int):
    async with session_factory() as session:
        vip_id = (
            await session.execute(
                text(
                    "INSERT INTO vips (telegram_user_id) "
                    "VALUES (:t) RETURNING id"
                ),
                {"t": telegram_user_id},
            )
        ).scalar_one()
        await session.commit()
        return vip_id


async def _count_memories(session_factory, vip_id) -> int:
    async with session_factory() as session:
        return (
            await session.execute(
                text("SELECT count(*) FROM memories WHERE vip_id = :vip"),
                {"vip": vip_id},
            )
        ).scalar_one()


async def _insert_memory_row(
    session_factory, vip_id, *, category: str, status: str
) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO memories "
                "(vip_id, embedding, content, category, confidence, status) "
                "VALUES (:vip, CAST(:emb AS vector), CAST(:content AS jsonb), "
                "        :cat, 0.9, :status)"
            ),
            {
                "vip": vip_id,
                "emb": _EMBEDDING_SQL,
                "content": '{"texto":"x","fact":"x"}',
                "cat": category,
                "status": status,
            },
        )
        await session.commit()


@pytest.mark.db
@pytest.mark.asyncio
async def test_replace_vip_profile_inserts_sections_and_perfil(session_factory):
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 501)

    rows = [
        MemoryInsert(
            category="identidad",
            text="Vive en Buenos Aires",
            embedding=_EMBEDDING_384,
            confidence=0.9,
            status="auto",
            approved_by="auto",
        ),
        MemoryInsert(
            category="preferencias",
            text="Le gusta el tono juguetón",
            embedding=_EMBEDDING_384,
            confidence=0.8,
            status="auto",
            approved_by="auto",
        ),
        MemoryInsert(
            category="sensible",
            text="Mencionó problemas de salud",
            embedding=_EMBEDDING_384,
            confidence=0.7,
            status="pending_owner",
            approved_by=None,
        ),
    ]
    perfil = {
        "vip_id": str(vip_id),
        "secciones": {"identidad": ["Vive en Buenos Aires"]},
        "generado_el": "2026-08-05T12:00:00+00:00",
        "actualizado_el": "2026-08-05T12:00:00+00:00",
        "fuente": "backfill",
        "version": 1,
    }
    inserted = await repo.replace_vip_profile(
        vip_id, rows=rows, perfil=perfil, perfil_embedding=_EMBEDDING_384
    )
    assert inserted == 4  # 3 sections + perfil row

    assert await _count_memories(session_factory, vip_id) == 4

    async with session_factory() as session:
        section_content = (
            await session.execute(
                text(
                    "SELECT content FROM memories "
                    "WHERE vip_id = :vip AND category = 'preferencias'"
                ),
                {"vip": vip_id},
            )
        ).scalar_one()
        assert section_content["texto"] == "Le gusta el tono juguetón"
        assert section_content["fact"] == section_content["texto"]

        perfil_content = (
            await session.execute(
                text(
                    "SELECT content FROM memories "
                    "WHERE vip_id = :vip AND category = 'perfil'"
                ),
                {"vip": vip_id},
            )
        ).scalar_one()
        assert "secciones" in perfil_content
        assert perfil_content["fuente"] == "backfill"

        status_row = (
            await session.execute(
                text(
                    "SELECT status, source_turn_id FROM memories "
                    "WHERE vip_id = :vip AND category = 'sensible'"
                ),
                {"vip": vip_id},
            )
        ).one()
        assert status_row.status == "pending_owner"
        assert status_row.source_turn_id is None

    # memory_to_dict exposes the F5 columns.
    found = await repo.find_by_vip_and_similarity(vip_id, _EMBEDDING_384)
    assert len(found) == 3  # sensible pending_owner filtered out
    first = found[0]
    assert "status" in first
    assert "source_turn_id" in first
    assert first["source_turn_id"] is None
    # dict conversion of an ORM row round-trips the new columns too.
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT * FROM memories "
                    "WHERE vip_id = :vip AND category = 'preferencias'"
                ),
                {"vip": vip_id},
            )
        ).mappings().one()
    # Re-read via ORM to exercise memory_to_dict on the model.
    from diana.infrastructure.db.models import Memory

    async with session_factory() as session:
        orm_row = (
            await session.execute(
                select(Memory).where(
                    Memory.vip_id == vip_id,
                    Memory.category == "preferencias",
                )
            )
        ).scalar_one()
    d = memory_to_dict(orm_row)
    assert d["status"] == "auto"
    assert d["source_turn_id"] is None


@pytest.mark.db
@pytest.mark.asyncio
async def test_replace_vip_profile_regenerate_replaces_without_duplicates(
    session_factory,
):
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 502)

    rows = [
        MemoryInsert(
            category="identidad",
            text="Vive en Buenos Aires",
            embedding=_EMBEDDING_384,
            confidence=0.9,
            status="auto",
            approved_by="auto",
        ),
    ]
    perfil = {
        "vip_id": str(vip_id),
        "secciones": {"identidad": ["Vive en Buenos Aires"]},
        "generado_el": "2026-08-05T12:00:00+00:00",
        "actualizado_el": "2026-08-05T12:00:00+00:00",
        "fuente": "backfill",
        "version": 1,
    }
    first = await repo.replace_vip_profile(
        vip_id, rows=rows, perfil=perfil, perfil_embedding=_EMBEDDING_384
    )
    second = await repo.replace_vip_profile(
        vip_id, rows=rows, perfil=perfil, perfil_embedding=_EMBEDDING_384
    )
    assert first == 2
    assert second == 2
    assert await _count_memories(session_factory, vip_id) == 2  # no duplicates


@pytest.mark.db
@pytest.mark.asyncio
async def test_find_by_vip_and_similarity_filters_status(session_factory):
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 503)

    for category, status in [
        ("identidad", "auto"),
        ("preferencias", "approved"),
        ("comercial", "pending_owner"),
        ("limites", "discarded"),
    ]:
        await _insert_memory_row(session_factory, vip_id, category=category, status=status)

    found = await repo.find_by_vip_and_similarity(vip_id, _EMBEDDING_384)
    statuses = sorted(d["status"] for d in found)
    assert statuses == ["approved", "auto"]
    assert len(found) == 2


@pytest.mark.db
@pytest.mark.asyncio
async def test_find_by_vip_and_similarity_isolates_vips(session_factory):
    repo = MemoriesRepo(session_factory)
    vip_a = await _create_vip(session_factory, 504)
    vip_b = await _create_vip(session_factory, 505)

    # VIP B has rows with embeddings identical to the query vector.
    await _insert_memory_row(session_factory, vip_b, category="identidad", status="auto")
    await _insert_memory_row(session_factory, vip_b, category="preferencias", status="auto")

    # VIP A has no rows at all; a query for A must not see B's rows (BR-15).
    found = await repo.find_by_vip_and_similarity(vip_a, _EMBEDDING_384)
    assert found == []


@pytest.mark.db
@pytest.mark.asyncio
async def test_replace_vip_profile_unknown_vip_fails_fk(session_factory):
    """FK enforcement: writing memories for a non-existent VIP raises."""
    repo = MemoriesRepo(session_factory)
    rows = [
        MemoryInsert(
            category="identidad",
            text="x",
            embedding=_EMBEDDING_384,
            confidence=0.9,
            status="auto",
            approved_by="auto",
        )
    ]
    with pytest.raises(Exception):
        await repo.replace_vip_profile(
            uuid4(),
            rows=rows,
            perfil={"vip_id": str(uuid4()), "secciones": {}},
            perfil_embedding=_EMBEDDING_384,
        )
