"""Temporary per-turn regen hint: tn: encode/parse, keyboard, callback session."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from diana.telegram.handlers.callbacks import CorrectSessionStore, build_callback_router
from diana.telegram.handlers.menu import MenuSessionStore
from diana.telegram.keyboards import (
    draft_keyboard,
    encode_add_note,
    encode_regen_hint,
    parse_regen_hint,
)

OWNER = 42


def test_encode_parse_regen_hint_roundtrip() -> None:
    tid = uuid4()
    data = encode_regen_hint(tid)
    assert data.startswith("tn:")
    assert len(data.encode("utf-8")) <= 64
    assert parse_regen_hint(data) == tid
    assert parse_regen_hint("tn:not-a-uuid") is None
    assert parse_regen_hint("an:123") is None
    assert parse_regen_hint("") is None


def test_draft_keyboard_has_regen_hint_and_keeps_note() -> None:
    tid = uuid4()
    kb = draft_keyboard(tid, chat_id=777)
    labels = [
        btn.text
        for row in kb.inline_keyboard
        for btn in row
    ]
    assert "💡 Contexto para regen" in labels
    assert "📝 Agregar nota" in labels
    # Permanent note still uses an:<chat_id>
    note_cbs = [
        btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
        if btn.text == "📝 Agregar nota"
    ]
    assert note_cbs == [encode_add_note(777)]
    hint_cbs = [
        btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
        if btn.text == "💡 Contexto para regen"
    ]
    assert hint_cbs == [encode_regen_hint(tid)]


@pytest.mark.asyncio
async def test_tn_callback_starts_regen_hint_session() -> None:
    turn_id = uuid4()
    menu_sessions = MenuSessionStore()
    draft_variants = MagicMock()
    router = build_callback_router(
        admin=MagicMock(),
        correct_sessions=CorrectSessionStore(),
        owner_telegram_id=OWNER,
        menu_sessions=menu_sessions,
        draft_variants=draft_variants,
        profile_admin=MagicMock(),
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
        id="cq-tn",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=encode_regen_hint(turn_id),
        message=msg,
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))

    await on_callback(cq)

    sess = menu_sessions.get(OWNER)
    assert sess is not None
    assert sess.kind == "regen_hint"
    assert sess.turn_id == turn_id
    assert sess.draft_message_id == 9
    assert sess.last_bot_message_id == 100
    prompt_text = msg.answer.await_args.args[0]
    assert "/cancelar" in prompt_text
    assert "nota permanente" in prompt_text.lower() or "no se guarda" in prompt_text.lower()


@pytest.mark.asyncio
async def test_an_note_path_unchanged_regression() -> None:
    """Permanent an: note session must stay independent of tn: regen hint."""
    profile_admin = MagicMock()
    menu_sessions = MenuSessionStore()
    router = build_callback_router(
        admin=MagicMock(),
        correct_sessions=CorrectSessionStore(),
        owner_telegram_id=OWNER,
        menu_sessions=menu_sessions,
        profile_admin=profile_admin,
        draft_variants=MagicMock(),
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
        id="cq-an-reg",
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
    assert sess.turn_id is None


def test_ephemeral_injection_renders_one_shot_label() -> None:
    from diana.application.draft_variants import build_regen_hint_knowledge
    from diana.cognitive.context_builder import ContextBuilder
    from diana.cognitive.models import Comprehension, IncomingTurn
    from uuid import uuid4

    built = ContextBuilder().build(
        IncomingTurn(
            turn_id=uuid4(),
            chat_id=1,
            vip_id=None,
            text="hola",
        ),
        Comprehension(
            intent="greeting",
            topics=[],
            emotion="neutral",
            urgency="baja",
            risk="bajo",
            needs_memory=False,
            needs_policy=False,
            needs_schedule=False,
            needs_examples=False,
            needs_history=False,
            needs_context=False,
            needs_profile=False,
        ),
        knowledge={"knowledge.ephemeral": build_regen_hint_knowledge("sé breve")},
        persona="Diana",
    )
    assert "knowledge.ephemeral" in built.prompt_final
    assert "ONE-SHOT OWNER REGEN CONTEXT" in built.prompt_final
    assert "sé breve" in built.prompt_final
    assert "KNOWLEDGE_EPHEMERAL_DATA" in built.prompt_final
    # Independent of needs_profile
    assert "never echo to VIP" in built.prompt_final.lower() or "never echo" in built.prompt_final.lower() or "Do not echo" in built.prompt_final or "never echo" in built.prompt_final.lower() or "VIP" in built.prompt_final
