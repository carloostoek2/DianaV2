"""Unit tests for knowledge retrievers (REAL + STUB)."""

from __future__ import annotations

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
    port = InMemoryMessageHistory(
        {
            100: [
                {"role": "vip", "text": "a"},
                {"role": "assistant", "text": "b"},
            ],
            200: [{"role": "vip", "text": "other-chat"}],
        }
    )
    retriever = HistoryRetriever(port, limit=20)
    result = await retriever.fetch(_turn(100), _comprehension())
    assert result == [
        {"role": "vip", "text": "a"},
        {"role": "assistant", "text": "b"},
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
    assert one == [{"role": "vip", "text": "only-one"}]
    assert two == [{"role": "vip", "text": "only-two"}]


@pytest.mark.asyncio
async def test_history_retriever_respects_limit() -> None:
    msgs = [{"role": "vip", "text": f"m{i}"} for i in range(10)]
    port = InMemoryMessageHistory({5: msgs})
    retriever = HistoryRetriever(port, limit=3)
    result = await retriever.fetch(_turn(5), _comprehension())
    assert len(result) == 3
    assert result[-1]["text"] == "m9"


@pytest.mark.asyncio
async def test_context_retriever_derives_partial_from_history() -> None:
    port = InMemoryMessageHistory(
        {
            7: [
                {"role": "vip", "text": "first"},
                {"role": "assistant", "text": "second message here"},
            ]
        }
    )
    retriever = ContextRetriever(port, limit=20)
    ctx = await retriever.fetch(_turn(7), _comprehension())
    assert ctx is not None
    assert ctx["message_count"] == 2
    assert ctx["last_role"] == "assistant"
    assert "second" in ctx["last_text_preview"]


@pytest.mark.asyncio
async def test_context_retriever_empty_history() -> None:
    port = InMemoryMessageHistory()
    retriever = ContextRetriever(port)
    ctx = await retriever.fetch(_turn(99), _comprehension())
    assert ctx is not None
    assert ctx["message_count"] == 0
    assert ctx["last_role"] is None
    assert ctx["last_text_preview"] == ""


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
