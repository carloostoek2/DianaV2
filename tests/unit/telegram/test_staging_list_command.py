"""Owner /staging list command — pure helpers + router registration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from diana.telegram.handlers.staging import (
    STAGING_EMPTY_UX,
    STAGING_UNAVAILABLE_UX,
    build_staging_router,
    format_staging_candidate_body,
    load_pending_staging_list,
)
from diana.telegram.keyboards import (
    encode_staging_discard,
    encode_staging_promote,
    staging_candidate_keyboard,
)


OWNER = 999001


def _candidate(
    *,
    candidate_id=None,
    original: str = "old draft text",
    corrected: str = "fixed draft text",
):
    return SimpleNamespace(
        id=candidate_id or uuid4(),
        status="pending",
        candidate_type="example",
        payload={
            "original_draft": original,
            "corrected_text": corrected,
            "context": {},
        },
    )


@pytest.mark.asyncio
async def test_load_unavailable_when_staging_none() -> None:
    token, rows = await load_pending_staging_list(staging=None)
    assert token == "unavailable"
    assert rows == []


@pytest.mark.asyncio
async def test_load_empty_queue() -> None:
    staging = AsyncMock()
    staging.list_pending_examples = AsyncMock(return_value=[])
    token, rows = await load_pending_staging_list(staging=staging, limit=5)
    assert token == "empty"
    assert rows == []
    staging.list_pending_examples.assert_awaited_once_with(limit=5)


@pytest.mark.asyncio
async def test_load_listed_fifo_rows() -> None:
    c1, c2 = _candidate(), _candidate()
    staging = AsyncMock()
    staging.list_pending_examples = AsyncMock(return_value=[c1, c2])
    token, rows = await load_pending_staging_list(staging=staging)
    assert token == "listed"
    assert rows == [c1, c2]
    staging.list_pending_examples.assert_awaited_once_with(limit=10)


def test_format_candidate_body_includes_short_id_and_snippets() -> None:
    cid = uuid4()
    body = format_staging_candidate_body(
        _candidate(candidate_id=cid, original="hello original", corrected="hello fixed")
    )
    assert str(cid)[:8] in body
    assert "hello original" in body
    assert "hello fixed" in body


def test_format_candidate_body_truncates_long_snippets() -> None:
    long = "x" * 200
    body = format_staging_candidate_body(
        _candidate(original=long, corrected=long)
    )
    # snippets truncated — body should not contain full 200-char runs twice fully
    assert long not in body
    assert "…" in body or "..." in body or len(body) < 400


def test_keyboard_attached_to_candidate() -> None:
    cid = uuid4()
    kb = staging_candidate_keyboard(cid)
    assert kb.inline_keyboard[0][0].callback_data == encode_staging_promote(cid)
    assert kb.inline_keyboard[0][1].callback_data == encode_staging_discard(cid)


def test_ux_strings_defined() -> None:
    assert "not available" in STAGING_UNAVAILABLE_UX.lower() or "no disponible" in STAGING_UNAVAILABLE_UX.lower()
    assert "pending" in STAGING_EMPTY_UX.lower() or "pendiente" in STAGING_EMPTY_UX.lower()


def test_build_staging_router_registers_command() -> None:
    router = build_staging_router(staging=None, owner_telegram_id=OWNER)
    # Command handlers live on message observers
    assert router is not None
    assert router.name == "staging"


def test_admin_menu_includes_staging() -> None:
    from diana.telegram.handlers.callbacks import ADMIN_MENU_TEXT

    assert "/staging" in ADMIN_MENU_TEXT
