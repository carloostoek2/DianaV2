"""E2E: StagingCandidateRepo.list_corrections_by_vip_since (A8 / EA-04).

The staging row does not store vip_id — the JOIN to ``turns.vip_id`` is what
scopes owner corrections to a VIP. This suite verifies the JOIN, the
``since`` window, the oldest-first order and that the FULL payload
(original_draft / corrected_text / context.turn_text) reaches the caller so
the synthesis LLM can separate tone/personality from point feedback.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from diana.infrastructure.db.repositories.staging import StagingCandidateRepo


async def _create_vip_and_turn(session_factory, telegram_user_id: int):
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
        turn_id = (
            await session.execute(
                text(
                    "INSERT INTO turns (chat_id, status, vip_id) "
                    "VALUES (:c, 'received', :vip) RETURNING id"
                ),
                {"c": telegram_user_id, "vip": vip_id},
            )
        ).scalar_one()
        await session.commit()
        return vip_id, turn_id


async def _insert_candidate(session_factory, *, turn_id, payload, when=None):
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "INSERT INTO staging_candidates "
                    "(candidate_type, payload, status, turn_id) "
                    "VALUES ('example', CAST(:payload AS jsonb), 'pending', :tid) "
                    "RETURNING id"
                ),
                {"payload": json.dumps(payload), "tid": turn_id},
            )
        ).scalar_one()
        if when is not None:
            await session.execute(
                text(
                    "UPDATE staging_candidates SET created_at = :when "
                    "WHERE id = :cid"
                ),
                {"when": when, "cid": row},
            )
        await session.commit()
        return row


def _payload(texto: str) -> dict:
    return {
        "original_draft": f"draft: {texto}",
        "corrected_text": f"corrected: {texto}",
        "context": {"turn_text": f"context: {texto}"},
        "channel_type": "vip",
    }


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_corrections_joins_turns_and_filters_by_vip(session_factory):
    repo = StagingCandidateRepo(session_factory)
    vip_a, turn_a = await _create_vip_and_turn(session_factory, 8301)
    vip_b, turn_b = await _create_vip_and_turn(session_factory, 8302)

    await _insert_candidate(session_factory, turn_id=turn_a, payload=_payload("uno"))
    await _insert_candidate(session_factory, turn_id=turn_b, payload=_payload("otro vip"))
    # A non-example candidate of vip_a must be excluded (only 'example' counts).
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO staging_candidates "
                "(candidate_type, payload, status, turn_id) "
                "VALUES ('policy', CAST(:payload AS jsonb), 'pending', :tid)"
            ),
            {"payload": json.dumps(_payload("politica")), "tid": turn_a},
        )
        await session.commit()

    rows = await repo.list_corrections_by_vip_since(vip_a, since=None)
    assert len(rows) == 1  # only the example correction of vip_a (JOIN to turns)
    assert rows[0]["payload"]["corrected_text"] == "corrected: uno"
    assert rows[0]["payload"]["context"]["turn_text"] == "context: uno"


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_corrections_filters_since_and_orders_oldest_first(
    session_factory,
):
    repo = StagingCandidateRepo(session_factory)
    vip_a, turn_a = await _create_vip_and_turn(session_factory, 8303)
    now = datetime.now(UTC)

    await _insert_candidate(
        session_factory,
        turn_id=turn_a,
        payload=_payload("vieja"),
        when=now - timedelta(days=3),
    )
    await _insert_candidate(
        session_factory,
        turn_id=turn_a,
        payload=_payload("nueva"),
        when=now - timedelta(days=1),
    )

    all_rows = await repo.list_corrections_by_vip_since(vip_a, since=None)
    assert [r["payload"]["original_draft"] for r in all_rows] == [
        "draft: vieja",
        "draft: nueva",
    ]  # oldest first

    two_days = now - timedelta(days=2)
    recent = await repo.list_corrections_by_vip_since(vip_a, since=two_days)
    assert [r["payload"]["original_draft"] for r in recent] == ["draft: nueva"]

    assert await repo.list_corrections_by_vip_since(vip_a, since=now) == []


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_corrections_includes_pending_and_promoted(session_factory):
    """A8: both pending and promoted corrections are feedback (LLM filters)."""
    repo = StagingCandidateRepo(session_factory)
    vip_a, turn_a = await _create_vip_and_turn(session_factory, 8304)

    await _insert_candidate(session_factory, turn_id=turn_a, payload=_payload("pend"))
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE staging_candidates SET status = 'promoted' "
                "WHERE payload->>'original_draft' = 'draft: pend'"
            )
        )
        await session.commit()

    rows = await repo.list_corrections_by_vip_since(vip_a, since=None)
    assert len(rows) == 1
    assert rows[0]["status"] == "promoted"
    assert "payload" in rows[0]
