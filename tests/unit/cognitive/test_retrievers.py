"""Unit tests for knowledge retrievers (REAL + STUB) — Anexo H.3 shapes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.ports import InMemoryMessageHistory
from diana.cognitive.retrievers.context import ContextRetriever
from diana.cognitive.retrievers.examples import ExamplesRetriever
from diana.cognitive.retrievers.history import HistoryRetriever
from diana.cognitive.retrievers.memory import MemoryRetriever
from diana.cognitive.retrievers.policy import PolicyRetriever
from diana.cognitive.retrievers.profile import ProfileRetriever
from diana.cognitive.retrievers.schedule import ScheduleRetriever


def _turn(chat_id: int = 100) -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=chat_id, text="hola")


def _comprehension() -> Comprehension:
    return Comprehension(
        intent="chat",
        topics=[],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=False,
        needs_schedule=False,
        needs_examples=False,
        needs_history=True,
        needs_context=True,
    )


@pytest.mark.asyncio
async def test_history_retriever_returns_chat_scoped_messages() -> None:
    """Bare list of {autor,texto,timestamp}; assistant dropped; chat-scoped."""
    port = InMemoryMessageHistory(
        {
            100: [
                {"role": "vip", "text": "a", "timestamp": "2026-01-01T10:00:00+00:00"},
                {"role": "assistant", "text": "b"},
            ],
            200: [{"role": "vip", "text": "other-chat"}],
        }
    )
    retriever = HistoryRetriever(port, limit=20)
    result = await retriever.fetch(_turn(100), _comprehension())
    assert result == [
        {
            "autor": "vip",
            "texto": "a",
            "timestamp": "2026-01-01T10:00:00+00:00",
        },
    ]


@pytest.mark.asyncio
async def test_history_retriever_isolates_chat_ids() -> None:
    port = InMemoryMessageHistory(
        {
            1: [{"role": "vip", "text": "only-one"}],
            2: [{"role": "vip", "text": "only-two"}],
        }
    )
    retriever = HistoryRetriever(port)
    one = await retriever.fetch(_turn(1), _comprehension())
    two = await retriever.fetch(_turn(2), _comprehension())
    assert one == [{"autor": "vip", "texto": "only-one", "timestamp": ""}]
    assert two == [{"autor": "vip", "texto": "only-two", "timestamp": ""}]


@pytest.mark.asyncio
async def test_history_retriever_respects_limit() -> None:
    msgs = [{"role": "vip", "text": f"m{i}"} for i in range(10)]
    port = InMemoryMessageHistory({5: msgs})
    retriever = HistoryRetriever(port, limit=3)
    result = await retriever.fetch(_turn(5), _comprehension())
    assert result is not None
    assert len(result) == 3
    assert result[-1]["texto"] == "m9"


@pytest.mark.asyncio
async def test_history_retriever_empty_chat_returns_empty_list_not_none() -> None:
    port = InMemoryMessageHistory()
    retriever = HistoryRetriever(port)
    result = await retriever.fetch(_turn(99), _comprehension())
    assert result == []
    assert result is not None


@pytest.mark.asyncio
async def test_history_retriever_maps_owner_to_duena() -> None:
    port = InMemoryMessageHistory(
        {
            10: [
                {"role": "owner", "text": "hola VIP", "timestamp": "t1"},
            ]
        }
    )
    retriever = HistoryRetriever(port)
    result = await retriever.fetch(_turn(10), _comprehension())
    assert result == [{"autor": "dueña", "texto": "hola VIP", "timestamp": "t1"}]


@pytest.mark.asyncio
async def test_context_retriever_derives_partial_from_history() -> None:
    """H.3 English keys only; no preview/message_count fields."""
    port = InMemoryMessageHistory(
        {
            7: [
                {"role": "vip", "text": "first", "timestamp": "2026-07-01T09:00:00+00:00"},
                {"role": "assistant", "text": "second message here"},
            ]
        }
    )
    fixed = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    retriever = ContextRetriever(port, limit=20, clock=lambda: fixed)
    ctx = await retriever.fetch(_turn(7), _comprehension())
    assert ctx is not None
    assert set(ctx.keys()) == {"waiting_for_reply_since", "is_first_message_of_day"}
    assert "message_count" not in ctx
    assert "last_role" not in ctx
    assert "last_text_preview" not in ctx
    # Last mappable is vip (assistant dropped) → waiting = that ts; one vip today → True
    assert ctx["waiting_for_reply_since"] == "2026-07-01T09:00:00+00:00"
    assert ctx["is_first_message_of_day"] is True


@pytest.mark.asyncio
async def test_context_retriever_empty_history() -> None:
    port = InMemoryMessageHistory()
    retriever = ContextRetriever(port)
    ctx = await retriever.fetch(_turn(99), _comprehension())
    assert ctx is not None
    assert ctx == {
        "waiting_for_reply_since": None,
        "is_first_message_of_day": True,
    }


@pytest.mark.asyncio
async def test_context_waiting_when_last_is_vip() -> None:
    port = InMemoryMessageHistory(
        {
            3: [
                {"role": "owner", "text": "ok", "timestamp": "2026-07-01T08:00:00+00:00"},
                {"role": "vip", "text": "pregunta", "timestamp": "2026-07-01T09:30:00+00:00"},
            ]
        }
    )
    fixed = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    retriever = ContextRetriever(port, clock=lambda: fixed)
    ctx = await retriever.fetch(_turn(3), _comprehension())
    assert ctx["waiting_for_reply_since"] == "2026-07-01T09:30:00+00:00"
    assert ctx["is_first_message_of_day"] is True


@pytest.mark.asyncio
async def test_context_not_waiting_when_last_is_owner() -> None:
    port = InMemoryMessageHistory(
        {
            4: [
                {"role": "vip", "text": "hola", "timestamp": "2026-07-01T09:00:00+00:00"},
                {"role": "owner", "text": "respuesta", "timestamp": "2026-07-01T09:05:00+00:00"},
            ]
        }
    )
    fixed = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    retriever = ContextRetriever(port, clock=lambda: fixed)
    ctx = await retriever.fetch(_turn(4), _comprehension())
    assert ctx["waiting_for_reply_since"] is None
    assert ctx["is_first_message_of_day"] is True


@pytest.mark.asyncio
async def test_context_is_first_message_of_day_false_with_two_vip_today() -> None:
    port = InMemoryMessageHistory(
        {
            5: [
                {"role": "vip", "text": "a", "timestamp": "2026-07-01T08:00:00+00:00"},
                {"role": "vip", "text": "b", "timestamp": "2026-07-01T09:00:00+00:00"},
            ]
        }
    )
    fixed = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    retriever = ContextRetriever(port, clock=lambda: fixed)
    ctx = await retriever.fetch(_turn(5), _comprehension())
    assert ctx["is_first_message_of_day"] is False
    assert ctx["waiting_for_reply_since"] == "2026-07-01T09:00:00+00:00"


@pytest.mark.asyncio
async def test_stubs_return_none() -> None:
    turn = _turn()
    c = _comprehension()
    for cls in (
        ProfileRetriever,
        MemoryRetriever,
        PolicyRetriever,
        ExamplesRetriever,
        ScheduleRetriever,
    ):
        result = await cls().fetch(turn, c)
        assert result is None


def test_examples_stub_has_no_memory_imports_ast() -> None:
    """AST gate: examples retriever must not import memory modules or tables."""
    import ast
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "diana"
        / "cognitive"
        / "retrievers"
        / "examples.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden_substrings = ("memory", "memories", "Memory")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for bad in forbidden_substrings:
                    assert bad not in alias.name, alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for bad in forbidden_substrings:
                assert bad not in module, module
            for alias in node.names:
                for bad in forbidden_substrings:
                    assert bad not in alias.name, alias.name
