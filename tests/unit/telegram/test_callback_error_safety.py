"""Router-level standard owner callback — answer alert on dispatch fault."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiogram.types import CallbackQuery, User

from diana.telegram.handlers.callbacks import CorrectSessionStore, build_callback_router
from diana.telegram.keyboards import encode_callback

OWNER = 999001


def _owner_callback(data: str) -> CallbackQuery:
    cq = CallbackQuery(
        id="cq-err",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=data,
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))
    return cq


@pytest.mark.asyncio
async def test_standard_owner_callback_answers_alert_on_exception() -> None:
    """Approve path fault must clear spinner with alert and not re-raise."""
    admin = MagicMock()
    admin.handle_approve = AsyncMock(side_effect=RuntimeError("boom"))
    router = build_callback_router(
        admin=admin,
        correct_sessions=CorrectSessionStore(),
        owner_telegram_id=OWNER,
    )
    on_callback = router.callback_query.handlers[0].callback
    turn_id = uuid4()
    query = _owner_callback(encode_callback("approve", turn_id))

    await on_callback(query)

    query.answer.assert_awaited()
    args, kwargs = query.answer.await_args
    assert kwargs.get("show_alert") is True
    text = args[0] if args else kwargs.get("text", "")
    assert "Error processing action" in text
