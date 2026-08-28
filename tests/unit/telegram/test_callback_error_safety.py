"""Router-level standard owner callback — answer alert on dispatch fault."""

from __future__ import annotations

from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from aiogram.types import BufferedInputFile, CallbackQuery, Chat, Message, User

from diana.application.draft_variants import VariantNavResult
from diana.behavior.ports import DeliveryProgress
from diana.telegram.handlers.callbacks import CorrectSessionStore, build_callback_router
from diana.telegram.handlers.menu import MenuSessionStore
from diana.telegram.keyboards import (
    MENU_ROOT_TEXT,
    encode_add_note,
    encode_callback,
    encode_metrics_back,
    encode_metrics_export,
    encode_trace_page,
    encode_trace_view,
)

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

    # Spinner cleared once; no second error-alert answer. The follow-up text
    # failure is logged (the SPEC-EA-07 severity-picker send is also best-effort
    # and logs its own event, so assert the follow-up event was emitted at all).
    assert query.answer.await_count == 1
    query.answer.assert_awaited_with()
    mock_logger.exception.assert_called()
    assert any(
        call.args[0] == "owner_callback_followup_failed"
        for call in mock_logger.exception.call_args_list
    )
    assert sessions.get(OWNER) == turn_id


@pytest.mark.asyncio
async def test_add_note_callback_starts_ttl_note_session() -> None:
    """A1: an:<chat_id> starts a TTL-bound 'note' MenuSession instead of a
    permanent dict, points the confirmation at the prompt (not the draft), and
    advertises /cancelar as the escape."""
    profile_admin = MagicMock()
    menu_sessions = MenuSessionStore()
    router = build_callback_router(
        admin=MagicMock(),
        correct_sessions=CorrectSessionStore(),
        owner_telegram_id=OWNER,
        menu_sessions=menu_sessions,
        profile_admin=profile_admin,
    )
    on_callback = router.callback_query.handlers[0].callback

    msg = Message(
        message_id=9,
        date=0,
        chat=Chat(id=OWNER, type="private"),
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        text="draft",
    )
    prompt = MagicMock()
    prompt.message_id = 100
    object.__setattr__(msg, "answer", AsyncMock(return_value=prompt))
    cq = CallbackQuery(
        id="cq-an",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=encode_add_note(777),
        message=msg,
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))

    await on_callback(cq)

    sess = menu_sessions.get(OWNER)
    assert sess is not None
    assert sess.kind == "note"
    assert sess.vip_user_id == 777
    assert sess.last_bot_message_id == 100
    assert sess.last_chat_id == OWNER
    prompt_text = msg.answer.await_args.args[0]
    assert "/cancelar" in prompt_text
    # Session is cancellable via /cancelar and expires via the store TTL.
    menu_sessions.cancel(OWNER)
    assert menu_sessions.get(OWNER) is None


@pytest.mark.asyncio
async def test_add_note_callback_unavailable_without_session_store() -> None:
    """an: without a wired MenuSessionStore degrades to an alert, not a leak."""
    router = build_callback_router(
        admin=MagicMock(),
        correct_sessions=CorrectSessionStore(),
        owner_telegram_id=OWNER,
        profile_admin=MagicMock(),
    )
    on_callback = router.callback_query.handlers[0].callback
    cq = CallbackQuery(
        id="cq-an2",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=encode_add_note(777),
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))

    await on_callback(cq)

    cq.answer.assert_awaited_once()
    args, kwargs = cq.answer.await_args
    assert kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_approve_answers_before_delivery() -> None:
    """A3: approve clears the spinner (empty answer) before the heavy delivery
    work and relies on the message edit for post-delivery feedback."""
    turn_id = uuid4()
    admin = MagicMock()
    admin.handle_approve = AsyncMock(return_value=MagicMock(success=True))
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
        text="draft",
    )
    object.__setattr__(msg, "edit_text", AsyncMock(return_value=True))
    cq = CallbackQuery(
        id="cq-app",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=encode_callback("approve", turn_id),
        message=msg,
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))

    await on_callback(cq)

    admin.handle_approve.assert_awaited_once_with(
        turn_id, actor_id=OWNER, on_progress=ANY
    )
    # Spinner cleared exactly once, before delivery — no trailing re-answer.
    cq.answer.assert_awaited_once_with()
    msg.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_approve_edits_draft_with_live_progress() -> None:
    """Approve reflects leído → escribiendo → Enviado on the draft message."""
    turn_id = uuid4()
    admin = MagicMock()

    async def fake_approve(
        turn_id: object,
        *,
        actor_id: object | None = None,
        on_progress: object | None = None,
    ) -> object:
        if on_progress is not None:
            await on_progress(DeliveryProgress(kind="reading"))
            await on_progress(DeliveryProgress(kind="typing"))
        return MagicMock(success=True)

    admin.handle_approve = AsyncMock(side_effect=fake_approve)
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
        text="<b>Propuesta</b> — borrador 1/1",
    )
    object.__setattr__(msg, "edit_text", AsyncMock(return_value=True))
    cq = CallbackQuery(
        id="cq-app-progress",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=encode_callback("approve", turn_id),
        message=msg,
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))

    await on_callback(cq)

    edits = [c.args[0] for c in msg.edit_text.await_args_list]
    assert edits[0].startswith("👀 Mensaje visto\n\n")
    assert edits[1].startswith("✍️ Escribiendo…\n\n")
    assert edits[2].startswith("✅ <b>Enviado</b>\n\n")
    # The original draft body is preserved across all live stages.
    assert "Propuesta" in edits[0] and "Propuesta" in edits[2]
    assert "borrador 1/1" in edits[2]


def _regen_query(turn_id: object, *, text: str = "borrador") -> tuple:
    """Build a Message + CallbackQuery pair for a regen button press."""
    msg = Message(
        message_id=9,
        date=0,
        chat=Chat(id=OWNER, type="private"),
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        text=text,
    )
    object.__setattr__(msg, "edit_text", AsyncMock(return_value=True))
    cq = CallbackQuery(
        id="cq-regen",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=encode_callback("regen", turn_id),
        message=msg,
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))
    return msg, cq


@pytest.mark.asyncio
async def test_regen_edits_draft_with_regenerating_legend() -> None:
    """Regen shows ♻️ Regenerando… while the run is in flight (success path)."""
    turn_id = uuid4()
    draft_variants = MagicMock()

    async def fake_regenerate(
        turn_id: object,
        *,
        actor_id: object | None = None,
        on_start: object | None = None,
    ) -> object:
        if on_start is not None:
            await on_start()
        return VariantNavResult(ok=True, token="regen_ok", toast="")

    draft_variants.regenerate = AsyncMock(side_effect=fake_regenerate)
    router = build_callback_router(
        admin=MagicMock(),
        correct_sessions=CorrectSessionStore(),
        owner_telegram_id=OWNER,
        draft_variants=draft_variants,
    )
    on_callback = router.callback_query.handlers[0].callback
    msg, cq = _regen_query(turn_id, text="<b>Propuesta</b> — borrador 1/1")

    await on_callback(cq)

    draft_variants.regenerate.assert_awaited_once_with(
        turn_id, actor_id=OWNER, on_start=ANY
    )
    edits = [c.args[0] for c in msg.edit_text.await_args_list]
    assert edits == ["♻️ Regenerando…\n\n<b>Propuesta</b> — borrador 1/1"]


@pytest.mark.asyncio
async def test_regen_failure_restores_draft_after_regenerating_legend() -> None:
    """Failed regen removes the ♻️ Regenerando… legend and restores the body."""
    turn_id = uuid4()
    draft_variants = MagicMock()

    async def fake_regenerate(
        turn_id: object,
        *,
        actor_id: object | None = None,
        on_start: object | None = None,
    ) -> object:
        if on_start is not None:
            await on_start()
        return VariantNavResult(ok=False, token="error", toast="falló")

    draft_variants.regenerate = AsyncMock(side_effect=fake_regenerate)
    router = build_callback_router(
        admin=MagicMock(),
        correct_sessions=CorrectSessionStore(),
        owner_telegram_id=OWNER,
        draft_variants=draft_variants,
    )
    on_callback = router.callback_query.handlers[0].callback
    msg, cq = _regen_query(turn_id, text="<b>Propuesta</b> — borrador 1/1")

    await on_callback(cq)

    edits = [c.args[0] for c in msg.edit_text.await_args_list]
    assert edits == [
        "♻️ Regenerando…\n\n<b>Propuesta</b> — borrador 1/1",
        "<b>Propuesta</b> — borrador 1/1",
    ]
    cq.answer.assert_awaited()


@pytest.mark.asyncio
async def test_regen_blocked_does_not_show_regenerating_legend() -> None:
    """Blocked early returns never flash the legend (no on_start fired)."""
    turn_id = uuid4()
    draft_variants = MagicMock()
    draft_variants.regenerate = AsyncMock(
        return_value=VariantNavResult(
            ok=False, token="blocked_regenerating", toast=""
        )
    )
    router = build_callback_router(
        admin=MagicMock(),
        correct_sessions=CorrectSessionStore(),
        owner_telegram_id=OWNER,
        draft_variants=draft_variants,
    )
    on_callback = router.callback_query.handlers[0].callback
    msg, cq = _regen_query(turn_id)

    await on_callback(cq)

    msg.edit_text.assert_not_awaited()
    draft_variants.regenerate.assert_awaited_once_with(
        turn_id, actor_id=OWNER, on_start=ANY
    )


@pytest.mark.asyncio
async def test_metrics_export_ships_full_json_document() -> None:
    """A8: metrics export answers early and sends the full JSON as a document."""
    admin_metrics = MagicMock()
    admin_metrics.export_week_json = AsyncMock(
        return_value='{"week_start": "2026-07-20", "metrics": {"total_turns": 5.0}}'
    )
    router = build_callback_router(
        admin=MagicMock(),
        correct_sessions=CorrectSessionStore(),
        admin_metrics=admin_metrics,
        owner_telegram_id=OWNER,
    )
    on_callback = router.callback_query.handlers[0].callback
    msg = Message(
        message_id=9,
        date=0,
        chat=Chat(id=OWNER, type="private"),
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        text="draft",
    )
    object.__setattr__(msg, "answer_document", AsyncMock(return_value=True))
    cq = CallbackQuery(
        id="cq-mx",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=encode_metrics_export(),
        message=msg,
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))

    await on_callback(cq)

    # A3: answered before the (potentially slow) export.
    cq.answer.assert_awaited_once_with()
    admin_metrics.export_week_json.assert_awaited_once()
    msg.answer_document.assert_awaited_once()
    args, kwargs = msg.answer_document.await_args
    document = args[0] if args else kwargs.get("document")
    assert isinstance(document, BufferedInputFile)
    assert b"week_start" in document.data
    assert document.filename == "metricas_semanales.json"
    assert kwargs.get("caption") == "Métricas semanales"


@pytest.mark.asyncio
async def test_metrics_back_edits_message_in_place() -> None:
    """A10: mx:b edits the current panel back to the root menu — no floating message."""
    router = build_callback_router(
        admin=MagicMock(),
        correct_sessions=CorrectSessionStore(),
        owner_telegram_id=OWNER,
    )
    on_callback = router.callback_query.handlers[0].callback
    msg = Message(
        message_id=9,
        date=0,
        chat=Chat(id=OWNER, type="private"),
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        text="resumen semanal",
    )
    object.__setattr__(msg, "edit_text", AsyncMock(return_value=True))
    object.__setattr__(msg, "answer", AsyncMock(return_value=True))
    cq = CallbackQuery(
        id="cq-mxb",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=encode_metrics_back(),
        message=msg,
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))

    await on_callback(cq)

    msg.edit_text.assert_awaited_once()
    args, kwargs = msg.edit_text.await_args
    text = args[0] if args else kwargs.get("text", "")
    assert text == MENU_ROOT_TEXT
    assert kwargs.get("reply_markup") is not None
    msg.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_trace_detail_back_uses_parsed_page() -> None:
    """A10: a vt:<id>:N callback renders 'Volver a turnos' targeting tp:N."""
    view = MagicMock()
    view.turn_id = uuid4()
    view.text = "detalle de traza"
    view.timings = {}
    admin_trace = MagicMock()
    admin_trace.render_trace_summary = AsyncMock(return_value=view)
    router = build_callback_router(
        admin=MagicMock(),
        correct_sessions=CorrectSessionStore(),
        admin_trace=admin_trace,
        owner_telegram_id=OWNER,
    )
    on_callback = router.callback_query.handlers[0].callback
    msg = Message(
        message_id=9,
        date=0,
        chat=Chat(id=OWNER, type="private"),
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        text="draft",
    )
    object.__setattr__(msg, "edit_text", AsyncMock(return_value=True))
    cq = CallbackQuery(
        id="cq-vt",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=encode_trace_view(view.turn_id, page=2),
        message=msg,
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))

    await on_callback(cq)

    msg.edit_text.assert_awaited_once()
    args, kwargs = msg.edit_text.await_args
    kb = kwargs.get("reply_markup")
    assert kb is not None
    back = next(
        b for row in kb.inline_keyboard for b in row
        if b.text == "🔙 Volver a turnos"
    )
    assert back.callback_data == encode_trace_page(2)
