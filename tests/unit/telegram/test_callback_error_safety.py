"""Router-level standard owner callback — answer alert on dispatch fault."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from diana.telegram.handlers.callbacks import CorrectSessionStore, build_callback_router
from diana.telegram.keyboards import encode_callback

OWNER = 999001


def _owner_callback(data: str, *, with_message: bool = False) -> CallbackQuery:
    msg = None
    if with_message:
        msg = Message(
            message_id=9,
            date=0,
            chat=Chat(id=OWNER, type="private"),
            from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
            text="draft",
        )
        object.__setattr__(msg, "answer", AsyncMock(return_value=True))
    cq = CallbackQuery(
        id="cq-err",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=data,
        message=msg,
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

    with patch("diana.telegram.handlers.callbacks.logger") as mock_logger:
        await on_callback(query)

    query.answer.assert_awaited()
    args, kwargs = query.answer.await_args
    assert kwargs.get("show_alert") is True
    text = args[0] if args else kwargs.get("text", "")
    assert "Error al procesar la acción" in text
    mock_logger.exception.assert_called()
    assert mock_logger.exception.call_args.args[0] == "owner_callback_error"
    extra = mock_logger.exception.call_args.kwargs.get("extra") or {}
    assert extra.get("actor_id") == OWNER
    assert "callback_data" in extra


@pytest.mark.asyncio
async def test_standard_owner_callback_answer_failure_swallowed() -> None:
    """Domain fault + answer failure must not re-raise (A7)."""
    admin = MagicMock()
    admin.handle_approve = AsyncMock(side_effect=RuntimeError("boom"))
    router = build_callback_router(
        admin=admin,
        correct_sessions=CorrectSessionStore(),
        owner_telegram_id=OWNER,
    )
    on_callback = router.callback_query.handlers[0].callback
    query = _owner_callback(encode_callback("approve", uuid4()))
    object.__setattr__(
        query, "answer", AsyncMock(side_effect=RuntimeError("answer failed"))
    )

    with patch("diana.telegram.handlers.callbacks.logger") as mock_logger:
        await on_callback(query)

    query.answer.assert_awaited()
    event_names = [c.args[0] for c in mock_logger.exception.call_args_list]
    assert "owner_callback_error" in event_names
    assert "owner_callback_answer_failed" in event_names


@pytest.mark.asyncio
async def test_escalate_callback_edits_draft_message() -> None:
    """Escalate mirrors approve: prepend legend and drop the draft buttons."""
    turn_id = uuid4()
    admin = MagicMock()
    admin.handle_owner_escalate = AsyncMock(return_value=True)
    router = build_callback_router(
        admin=admin,
        correct_sessions=CorrectSessionStore(),
        owner_telegram_id=OWNER,
    )
    on_callback = router.callback_query.handlers[0].callback
    msg = Message(
        message_id=9,
        date=0,
        chat=Chat(id=OWNER, type="private"),
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        text="<b>Propuesta de respuesta</b> — borrador 1/1",
    )
    object.__setattr__(msg, "edit_text", AsyncMock(return_value=True))
    cq = CallbackQuery(
        id="cq-esc",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=encode_callback("escalate", turn_id),
        message=msg,
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))

    await on_callback(cq)

    admin.handle_owner_escalate.assert_awaited_once_with(
        turn_id, actor_id=OWNER
    )
    msg.edit_text.assert_awaited_once()
    args, kwargs = msg.edit_text.await_args
    text = args[0] if args else kwargs.get("text", "")
    assert text.startswith("⚠️ <b>Escalado</b>\n\n")
    assert "Propuesta de respuesta" in text
    assert kwargs.get("reply_markup") is None
    assert kwargs.get("parse_mode") == "HTML"
    cq.answer.assert_awaited()


@pytest.mark.asyncio
async def test_awaiting_correct_followup_failure_does_not_reanswer() -> None:
    """Follow-up message.answer fault must not attempt a second query.answer."""
    turn_id = uuid4()
    admin = MagicMock()
    admin._assert_owner = MagicMock()
    admin.is_pending_approval = AsyncMock(return_value=True)
    sessions = CorrectSessionStore()
    router = build_callback_router(
        admin=admin,
        correct_sessions=sessions,
        owner_telegram_id=OWNER,
    )
    on_callback = router.callback_query.handlers[0].callback
    query = _owner_callback(
        encode_callback("correct", turn_id),
        with_message=True,
    )
    assert query.message is not None
    object.__setattr__(
        query.message,
        "answer",
        AsyncMock(side_effect=RuntimeError("chat send failed")),
    )

    with patch("diana.telegram.handlers.callbacks.logger") as mock_logger:
        await on_callback(query)

    # Spinner cleared once; no second error-alert answer.
    assert query.answer.await_count == 1
    query.answer.assert_awaited_with()
    mock_logger.exception.assert_called()
    assert mock_logger.exception.call_args.args[0] == "owner_callback_followup_failed"
    assert sessions.get(OWNER) == turn_id
