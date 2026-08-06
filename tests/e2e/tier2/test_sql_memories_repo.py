"""E2E: MemoriesRepo writer + visibility filter + VIP isolation (BR-15)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

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
    session_factory, vip_id, *, category: str, status: str, emb_sql: str | None = None
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
                "emb": emb_sql or _EMBEDDING_SQL,
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

    # memory_to_dict exposes the F5 columns. Fix round F1/M1: the perfil row
    # is excluded from retrieval, so only the two auto facts come back
    # (pending_owner sensible + category=perfil are both filtered out).
    found = await repo.find_by_vip_and_similarity(vip_id, _EMBEDDING_384)
    assert len(found) == 2  # perfil + sensible pending_owner filtered out
    assert all(d["category"] != "perfil" for d in found)
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
    # Fix round (L5): narrow the expectation to the actual failure class — a
    # broad `Exception` could mask an unrelated error (e.g. connection) as pass.
    with pytest.raises(IntegrityError):
        await repo.replace_vip_profile(
            uuid4(),
            rows=rows,
            perfil={"vip_id": str(uuid4()), "secciones": {}},
            perfil_embedding=_EMBEDDING_384,
        )


@pytest.mark.db
@pytest.mark.asyncio
async def test_replace_vip_profile_preserves_approved_and_discarded(
    session_factory,
):
    """Fix round (F4): regeneration must not destroy owner decisions.

    Rows the owner approved/discarded survive the next backfill; only the
    regenerable rows (auto/pending_owner) are replaced.
    """
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 506)

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
    first = await repo.replace_vip_profile(
        vip_id, rows=rows, perfil=perfil, perfil_embedding=_EMBEDDING_384
    )
    assert first == 3  # 2 facts + perfil
    assert await _count_memories(session_factory, vip_id) == 3

    # The owner decides on both facts (simulating the future DM approval flow).
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE memories SET status = 'approved' "
                "WHERE vip_id = :vip AND category = 'identidad'"
            ),
            {"vip": vip_id},
        )
        await session.execute(
            text(
                "UPDATE memories SET status = 'discarded' "
                "WHERE vip_id = :vip AND category = 'sensible'"
            ),
            {"vip": vip_id},
        )
        await session.commit()

    # Regenerate: approved/discarded rows must survive; the regenerable ones
    # (perfil auto + nothing else left in auto/pending_owner) are replaced.
    second = await repo.replace_vip_profile(
        vip_id, rows=rows, perfil=perfil, perfil_embedding=_EMBEDDING_384
    )
    assert second == 3  # 2 facts + perfil reinserted
    assert await _count_memories(session_factory, vip_id) == 5  # 3 new + 2 kept

    async with session_factory() as session:
        statuses = (
            await session.execute(
                text(
                    "SELECT status FROM memories WHERE vip_id = :vip ORDER BY category"
                ),
                {"vip": vip_id},
            )
        ).scalars().all()
    assert sorted(statuses) == [
        "approved",
        "auto",
        "auto",
        "discarded",
        "pending_owner",
    ]


@pytest.mark.db
@pytest.mark.asyncio
async def test_replace_vip_profile_rejects_invalid_status_and_dimension(
    session_factory,
):
    """Fix round (F6/L7): the DTO and the repo fail fast with a descriptive
    ValueError instead of a raw DB error."""
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 507)
    perfil = {"vip_id": str(vip_id), "secciones": {}}

    # DTO-level (F6): out-of-domain status is rejected at construction time.
    with pytest.raises(ValueError, match="invalid MemoryInsert.status"):
        MemoryInsert(
            category="identidad",
            text="x",
            embedding=_EMBEDDING_384,
            confidence=0.9,
            status="approved_by_typo",  # type: ignore[arg-type]  # intentional: F6 runtime validation
            approved_by="auto",
        )

    # Repo-level (L7): embedding dimension validated at the repo boundary.
    bad_dim = MemoryInsert(
        category="identidad",
        text="x",
        embedding=[0.1] * 8,  # not 384
        confidence=0.9,
        status="auto",
        approved_by="auto",
    )
    with pytest.raises(ValueError, match="embedding dimension"):
        await repo.replace_vip_profile(
            vip_id, rows=[bad_dim], perfil=perfil, perfil_embedding=_EMBEDDING_384
        )

    with pytest.raises(ValueError, match="perfil embedding dimension"):
        await repo.replace_vip_profile(
            vip_id, rows=[], perfil=perfil, perfil_embedding=[0.1] * 8
        )

    # Nothing was written by the rejected calls.
    assert await _count_memories(session_factory, vip_id) == 0


# ---------------------------------------------------------------------------
# F5 Pool 2: find_similar_surviving (pgvector dedup vs surviving rows) + has_profile
# ---------------------------------------------------------------------------

_EMBEDDING_B = [0.1] * 192 + [-0.1] * 192  # orthogonal to _EMBEDDING_384 (cos 0)


@pytest.mark.db
@pytest.mark.asyncio
async def test_find_similar_surviving_threshold_and_category(session_factory):
    """REQ-MEM-08: only surviving rows (approved/discarded) of the same VIP
    are returned; `auto` (regenerable) and other categories are filtered."""
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 508)

    def _insert(category: str, status: str, embedding: list[float]) -> MemoryInsert:
        return MemoryInsert(
            category=category,
            text=f"hecho {category} {status}",
            embedding=embedding,
            confidence=0.9,
            status=status,  # type: ignore[arg-type]
            approved_by="owner" if status in ("approved", "discarded") else "auto",
        )

    await repo.replace_vip_profile(
        vip_id,
        rows=[
            _insert("preferencias", "approved", _EMBEDDING_384),  # (a)
            _insert("identidad", "discarded", _EMBEDDING_384),  # (b)
            _insert("preferencias", "auto", _EMBEDDING_384),  # (c) not a survivor
            _insert("comercial", "approved", _EMBEDDING_B),  # (d) orthogonal
        ],
        perfil={"vip_id": str(vip_id), "secciones": {}},
        perfil_embedding=_EMBEDDING_384,
    )

    # Query with vector A → (a) approved and (b) discarded match; the `auto`
    # row (c) and the `perfil` row never appear.
    hits_a = await repo.find_similar_surviving(
        vip_id, _EMBEDDING_384, threshold=0.85
    )
    cats_a = {h["category"] for h in hits_a}
    assert cats_a == {"preferencias", "identidad"}
    assert all(h["status"] in ("approved", "discarded") for h in hits_a)

    # Same vector, category filter → only (a).
    hits_pref = await repo.find_similar_surviving(
        vip_id, _EMBEDDING_384, threshold=0.85, category="preferencias"
    )
    assert [h["category"] for h in hits_pref] == ["preferencias"]
    assert hits_pref[0]["status"] == "approved"

    # Query with the orthogonal vector B → only (d) matches.
    hits_b = await repo.find_similar_surviving(vip_id, _EMBEDDING_B, threshold=0.85)
    assert [h["category"] for h in hits_b] == ["comercial"]
    assert all(h["category"] != "preferencias" for h in hits_b)


@pytest.mark.db
@pytest.mark.asyncio
async def test_find_similar_surviving_excludes_perfil(session_factory):
    """The `perfil` card row never shows up as a dedup target (it is the
    panel card, not a fact — same rule as the retriever filter)."""
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 509)

    await repo.replace_vip_profile(
        vip_id,
        rows=[
            MemoryInsert(
                category="identidad",
                text="Vive en Buenos Aires",
                embedding=_EMBEDDING_384,
                confidence=0.9,
                status="approved",
                approved_by="owner",
            )
        ],
        perfil={"vip_id": str(vip_id), "secciones": {}},
        perfil_embedding=_EMBEDDING_384,
    )

    hits = await repo.find_similar_surviving(vip_id, _EMBEDDING_384, threshold=0.85)
    assert len(hits) == 1
    assert hits[0]["category"] == "identidad"
    assert all(h["category"] != "perfil" for h in hits)


@pytest.mark.db
@pytest.mark.asyncio
async def test_has_profile(session_factory):
    """has_profile is True after a profile write, False for a fresh VIP."""
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 510)
    assert await repo.has_profile(vip_id) is False

    await repo.replace_vip_profile(
        vip_id,
        rows=[
            MemoryInsert(
                category="identidad",
                text="Vive en Buenos Aires",
                embedding=_EMBEDDING_384,
                confidence=0.9,
                status="auto",
                approved_by="auto",
            )
        ],
        perfil={"vip_id": str(vip_id), "secciones": {}},
        perfil_embedding=_EMBEDDING_384,
    )
    assert await repo.has_profile(vip_id) is True


# ---------------------------------------------------------------------------
# F5 Pool 3: post-turn incremental extraction repo methods (F5-04 / REQ-MEM-07-08)
# ---------------------------------------------------------------------------

_EMBEDDING_B_SQL = "[" + ",".join(["0.1"] * 192 + ["-0.1"] * 192) + "]"


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_by_vip_orders_and_filters(session_factory):
    """list_by_vip returns every non-perfil fact (oldest first), never the
    `perfil` card row; the optional status filter narrows the result."""
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 511)

    await repo.replace_vip_profile(
        vip_id,
        rows=[
            MemoryInsert(
                category="preferencias",
                text="Le gusta el tono juguetón",
                embedding=_EMBEDDING_384,
                confidence=0.9,
                status="auto",
                approved_by="auto",
            ),
            MemoryInsert(
                category="identidad",
                text="Vive en Buenos Aires",
                embedding=_EMBEDDING_384,
                confidence=0.9,
                status="approved",
                approved_by="owner",
            ),
        ],
        perfil={"vip_id": str(vip_id), "secciones": {}},
        perfil_embedding=_EMBEDDING_384,
    )
    # Age the identidad row so the created_at ordering is deterministic.
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE memories SET created_at = now() - interval '1 day' "
                "WHERE vip_id = :vip AND category = 'identidad'"
            ),
            {"vip": vip_id},
        )
        await session.commit()

    all_rows = await repo.list_by_vip(vip_id)
    assert [r["category"] for r in all_rows] == ["identidad", "preferencias"]
    assert [r["status"] for r in all_rows] == ["approved", "auto"]
    assert all(r["category"] != "perfil" for r in all_rows)

    approved_only = await repo.list_by_vip(vip_id, statuses=("approved",))
    assert [r["category"] for r in approved_only] == ["identidad"]

    # The limit is honored.
    limited = await repo.list_by_vip(vip_id, limit=1)
    assert [r["category"] for r in limited] == ["identidad"]


@pytest.mark.db
@pytest.mark.asyncio
async def test_find_similar_facts_threshold_category_and_all_statuses(session_factory):
    """A5: post-turn dedup compares against every non-perfil row of the VIP
    that the owner has NOT discarded (auto/pending_owner/approved) — a
    discarded fact must never suppress a later correct fact. Unlike
    find_similar_surviving (Pool 2: only approved/discarded). Category filter
    and orthogonal vector behave like the Pool 2 contract."""
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 512)

    await repo.replace_vip_profile(
        vip_id,
        rows=[
            MemoryInsert(
                category="preferencias",
                text="hecho preferencias auto",
                embedding=_EMBEDDING_384,
                confidence=0.9,
                status="auto",
                approved_by="auto",
            ),
            MemoryInsert(
                category="identidad",
                text="hecho identidad approved",
                embedding=_EMBEDDING_384,
                confidence=0.9,
                status="approved",
                approved_by="owner",
            ),
            MemoryInsert(
                category="comercial",
                text="hecho comercial discarded",
                embedding=_EMBEDDING_384,
                confidence=0.9,
                status="discarded",
                approved_by="owner",
            ),
            MemoryInsert(
                category="limites",
                text="hecho limites pending",
                embedding=_EMBEDDING_384,
                confidence=0.9,
                status="pending_owner",
                approved_by=None,
            ),
        ],
        perfil={"vip_id": str(vip_id), "secciones": {}},
        perfil_embedding=_EMBEDDING_384,
    )
    # 5th row: orthogonal vector + other category, inserted directly (a second
    # replace_vip_profile would wipe the regenerable auto/pending_owner rows).
    await _insert_memory_row(
        session_factory,
        vip_id,
        category="comercial_b",
        status="approved",
        emb_sql=_EMBEDDING_B_SQL,
    )

    hits_a = await repo.find_similar_facts(vip_id, _EMBEDDING_384, threshold=0.85)
    assert len(hits_a) == 3
    assert {h["status"] for h in hits_a} == {
        "auto",
        "pending_owner",
        "approved",
    }
    assert all(h["category"] != "perfil" for h in hits_a)

    hits_pref = await repo.find_similar_facts(
        vip_id, _EMBEDDING_384, threshold=0.85, category="preferencias"
    )
    assert [h["category"] for h in hits_pref] == ["preferencias"]
    assert hits_pref[0]["status"] == "auto"

    # Orthogonal query vector B → only the B row matches.
    hits_b = await repo.find_similar_facts(vip_id, _EMBEDDING_B, threshold=0.85)
    assert [h["category"] for h in hits_b] == ["comercial_b"]
    assert all(h["category"] != "preferencias" for h in hits_b)


@pytest.mark.db
@pytest.mark.asyncio
async def test_insert_facts_appends_with_source_turn_and_preserves_existing(
    session_factory,
):
    """A6: insert_facts is a pure append (source_turn_id set) — pre-existing
    facts and the `perfil` card row stay untouched."""
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 513)

    # Pre-existing profile: 1 fact + perfil row.
    await repo.replace_vip_profile(
        vip_id,
        rows=[
            MemoryInsert(
                category="identidad",
                text="Vive en Buenos Aires",
                embedding=_EMBEDDING_384,
                confidence=0.9,
                status="auto",
                approved_by="auto",
            )
        ],
        perfil={"vip_id": str(vip_id), "secciones": {"identidad": ["Vive en Buenos Aires"]}},
        perfil_embedding=_EMBEDDING_384,
    )
    assert await _count_memories(session_factory, vip_id) == 2

    async with session_factory() as session:
        turn_id = (
            await session.execute(
                text("INSERT INTO turns (chat_id, status) VALUES (513, 'delivered') RETURNING id")
            )
        ).scalar_one()
        await session.commit()

    inserted = await repo.insert_facts(
        vip_id,
        rows=[
            MemoryInsert(
                category="preferencias",
                text="Le gusta el tono juguetón",
                embedding=_EMBEDDING_384,
                confidence=0.9,
                status="auto",
                source_turn_id=turn_id,
                approved_by="auto",
            ),
            MemoryInsert(
                category="sensible",
                text="Mencionó problemas de salud",
                embedding=_EMBEDDING_384,
                confidence=0.7,
                status="pending_owner",
                source_turn_id=turn_id,
                approved_by=None,
            ),
        ],
    )
    assert inserted == 2
    assert await _count_memories(session_factory, vip_id) == 4  # 2 old + 2 new

    all_rows = await repo.list_by_vip(vip_id)
    by_cat = {r["category"]: r for r in all_rows}
    assert by_cat["preferencias"]["status"] == "auto"
    assert by_cat["preferencias"]["source_turn_id"] == str(turn_id)
    assert by_cat["sensible"]["status"] == "pending_owner"
    assert by_cat["sensible"]["source_turn_id"] == str(turn_id)
    # Pre-existing fact untouched (source_turn_id still NULL).
    assert by_cat["identidad"]["source_turn_id"] is None

    # The `perfil` card row was not rewritten.
    async with session_factory() as session:
        perfil = (
            await session.execute(
                text(
                    "SELECT category, status FROM memories "
                    "WHERE vip_id = :vip AND category = 'perfil'"
                ),
                {"vip": vip_id},
            )
        ).one()
    assert perfil.category == "perfil"
    assert perfil.status == "auto"


@pytest.mark.db
@pytest.mark.asyncio
async def test_insert_facts_validates_status_and_dimension(session_factory):
    """Same boundary contract as replace_vip_profile: out-of-domain status and
    wrong embedding dimension fail fast with a descriptive ValueError."""
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 514)

    # DTO-level (F6): out-of-domain status is rejected at construction time.
    with pytest.raises(ValueError, match="invalid MemoryInsert.status"):
        MemoryInsert(
            category="identidad",
            text="x",
            embedding=_EMBEDDING_384,
            confidence=0.9,
            status="approved_by_typo",  # type: ignore[arg-type]  # intentional: F6 runtime validation
            approved_by="auto",
        )

    # Repo-level (L7): embedding dimension validated at the repo boundary.
    bad_dim = MemoryInsert(
        category="identidad",
        text="x",
        embedding=[0.1] * 8,  # not 384
        confidence=0.9,
        status="auto",
        approved_by="auto",
    )
    with pytest.raises(ValueError, match="embedding dimension"):
        await repo.insert_facts(vip_id, rows=[bad_dim])

    # Nothing was written by the rejected calls.
    assert await _count_memories(session_factory, vip_id) == 0


# ---------------------------------------------------------------------------
# F5 Pool 4: owner approval flow (F5-05 / REQ-MEM-10) — list/get/decide + visibility
# ---------------------------------------------------------------------------


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_pending_owner_returns_only_pending(session_factory):
    """list_pending_owner lists ONLY pending_owner fact rows, never perfil."""
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 521)

    for category, status in [
        ("identidad", "auto"),
        ("preferencias", "approved"),
        ("comercial", "pending_owner"),
        ("limites", "discarded"),
    ]:
        await _insert_memory_row(session_factory, vip_id, category=category, status=status)
    # The perfil card row is never part of the approval queue.
    await _insert_memory_row(session_factory, vip_id, category="perfil", status="auto")

    pending = await repo.list_pending_owner()
    assert all(r["status"] == "pending_owner" for r in pending)
    assert all(r["category"] != "perfil" for r in pending)
    # Our VIP's auto/approved/discarded rows are excluded; the single
    # pending_owner row IS listed (the queue is multi-VIP by design — A3).
    mine = [r for r in pending if r["vip_id"] == str(vip_id)]
    assert len(mine) == 1
    assert mine[0]["category"] == "comercial"

    limited = await repo.list_pending_owner(limit=0)
    assert limited == []


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_fact_returns_row_by_id_and_none_for_missing(session_factory):
    """get_fact resolves a row by id (identity) and None for unknown ids."""
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 522)
    await _insert_memory_row(
        session_factory, vip_id, category="sensible", status="pending_owner"
    )

    async with session_factory() as session:
        fact_id = (
            await session.execute(
                text(
                    "SELECT id FROM memories "
                    "WHERE vip_id = :vip AND category = 'sensible'"
                ),
                {"vip": vip_id},
            )
        ).scalar_one()

    row = await repo.get_fact(fact_id)
    assert row is not None
    assert row["id"] == str(fact_id)
    assert row["vip_id"] == str(vip_id)
    assert row["status"] == "pending_owner"
    assert row["category"] == "sensible"

    assert await repo.get_fact(uuid4()) is None


@pytest.mark.db
@pytest.mark.asyncio
async def test_set_fact_status_approve_discard_and_guards(session_factory):
    """set_fact_status transitions ONLY pending_owner scoped by (id, vip_id)."""
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 523)
    other_vip = await _create_vip(session_factory, 524)

    async def _insert(category: str, status: str):
        await _insert_memory_row(
            session_factory, vip_id, category=category, status=status
        )

    await _insert("sensible", "pending_owner")  # approve target
    await _insert("comercial", "pending_owner")  # discard target
    await _insert("identidad", "auto")  # already-auto guard

    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, category FROM memories WHERE vip_id = :vip "
                    "ORDER BY category"
                ),
                {"vip": vip_id},
            )
        ).all()
    by_cat = {cat: fid for fid, cat in rows}

    # Approve → True, row becomes approved with aprobado_por='owner'.
    approved = await repo.set_fact_status(
        by_cat["sensible"], vip_id=vip_id, new_status="approved"
    )
    assert approved is True
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, content->>'aprobado_por' AS aprobado_por "
                    "FROM memories WHERE id = :fid"
                ),
                {"fid": by_cat["sensible"]},
            )
        ).one()
    assert row.status == "approved"
    assert row.aprobado_por == "owner"

    # Discard → True, row becomes discarded.
    discarded = await repo.set_fact_status(
        by_cat["comercial"], vip_id=vip_id, new_status="discarded"
    )
    assert discarded is True
    async with session_factory() as session:
        status = (
            await session.execute(
                text("SELECT status FROM memories WHERE id = :fid"),
                {"fid": by_cat["comercial"]},
            )
        ).scalar_one()
    assert status == "discarded"

    # Already decided → stale (False); other VIP → not mine (False).
    assert (
        await repo.set_fact_status(
            by_cat["sensible"], vip_id=vip_id, new_status="approved"
        )
        is False
    )
    assert (
        await repo.set_fact_status(
            by_cat["sensible"], vip_id=other_vip, new_status="approved"
        )
        is False
    )
    # auto row is not pending_owner → False.
    assert (
        await repo.set_fact_status(
            by_cat["identidad"], vip_id=vip_id, new_status="approved"
        )
        is False
    )
    # Missing row → False.
    assert (
        await repo.set_fact_status(uuid4(), vip_id=vip_id, new_status="approved")
        is False
    )
    # Out-of-domain target status → ValueError, nothing written.
    with pytest.raises(ValueError, match="invalid target status"):
        await repo.set_fact_status(
            by_cat["sensible"], vip_id=vip_id, new_status="bogus"  # type: ignore[arg-type]
        )


@pytest.mark.db
@pytest.mark.asyncio
async def test_pending_owner_invisible_to_retriever_until_approved(session_factory):
    """(b)+(e): pending_owner is invisible to the retriever until the owner
    approves it — then the same query returns the row."""
    repo = MemoriesRepo(session_factory)
    vip_id = await _create_vip(session_factory, 525)
    await _insert_memory_row(
        session_factory, vip_id, category="sensible", status="pending_owner"
    )

    assert await repo.find_by_vip_and_similarity(
        vip_id, _EMBEDDING_384, threshold=0.75
    ) == []

    async with session_factory() as session:
        fact_id = (
            await session.execute(
                text("SELECT id FROM memories WHERE vip_id = :vip"),
                {"vip": vip_id},
            )
        ).scalar_one()
    assert (
        await repo.set_fact_status(fact_id, vip_id=vip_id, new_status="approved")
        is True
    )

    found = await repo.find_by_vip_and_similarity(
        vip_id, _EMBEDDING_384, threshold=0.75
    )
    assert len(found) == 1
    assert found[0]["id"] == str(fact_id)
    assert found[0]["status"] == "approved"
