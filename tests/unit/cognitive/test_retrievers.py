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
    assert set(ctx.keys()) == {
        "waiting_for_reply_since",
        "is_first_message_of_day",
        "dia_semana",
        "hora_actual",
    }
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
    assert ctx["waiting_for_reply_since"] is None
    assert ctx["is_first_message_of_day"] is True
    assert "dia_semana" in ctx
    assert "hora_actual" in ctx


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
async def test_context_retriever_includes_dia_hora_mexico_city() -> None:
    """H9.5: additive dia_semana/hora_actual in America/Mexico_City."""
    port = InMemoryMessageHistory()
    # 2026-07-23 Thursday 23:00 UTC → 17:00 CDMX
    fixed = datetime(2026, 7, 23, 23, 0, 0, tzinfo=UTC)
    retriever = ContextRetriever(port, clock=lambda: fixed)
    ctx = await retriever.fetch(_turn(7), _comprehension())
    assert ctx["dia_semana"] == "jueves"
    assert ctx["hora_actual"] == "17:00"
    assert "waiting_for_reply_since" in ctx
    assert "is_first_message_of_day" in ctx


@pytest.mark.asyncio
async def test_context_first_message_cdmx_counts_same_local_day_across_utc_midnight() -> None:
    """Window A: two VIP same CDMX day straddling 00:00Z → not first of day."""
    # clock 2026-07-02T04:00Z → CDMX 2026-07-01 22:00
    # vip1 2026-07-01T16:00Z → CDMX Jul 1 10:00
    # vip2 2026-07-02T02:00Z → CDMX Jul 1 20:00
    port = InMemoryMessageHistory(
        {
            11: [
                {
                    "role": "vip",
                    "text": "morning",
                    "timestamp": "2026-07-01T16:00:00+00:00",
                },
                {
                    "role": "vip",
                    "text": "evening",
                    "timestamp": "2026-07-02T02:00:00+00:00",
                },
            ]
        }
    )
    fixed = datetime(2026, 7, 2, 4, 0, 0, tzinfo=UTC)
    retriever = ContextRetriever(port, clock=lambda: fixed)
    ctx = await retriever.fetch(_turn(11), _comprehension())
    assert ctx["is_first_message_of_day"] is False
    assert ctx["dia_semana"] == "miercoles"  # 2026-07-01 CDMX
    assert ctx["hora_actual"] == "22:00"


@pytest.mark.asyncio
async def test_context_first_message_cdmx_excludes_previous_local_evening_after_cdmx_midnight() -> None:
    """Window B: prev CDMX evening + one early CDMX morning → first of day True."""
    # clock 2026-07-02T07:00Z → CDMX 2026-07-02 01:00
    # vip_prev 2026-07-02T05:00Z → CDMX Jul 1 23:00 (yesterday)
    # vip_now  2026-07-02T06:30Z → CDMX Jul 2 00:30 (today)
    port = InMemoryMessageHistory(
        {
            12: [
                {
                    "role": "vip",
                    "text": "late evening",
                    "timestamp": "2026-07-02T05:00:00+00:00",
                },
                {
                    "role": "vip",
                    "text": "early morning",
                    "timestamp": "2026-07-02T06:30:00+00:00",
                },
            ]
        }
    )
    fixed = datetime(2026, 7, 2, 7, 0, 0, tzinfo=UTC)
    retriever = ContextRetriever(port, clock=lambda: fixed)
    ctx = await retriever.fetch(_turn(12), _comprehension())
    assert ctx["is_first_message_of_day"] is True
    assert ctx["dia_semana"] == "jueves"  # 2026-07-02 CDMX
    assert ctx["hora_actual"] == "01:00"


@pytest.mark.asyncio
async def test_context_first_message_naive_timestamp_treated_as_utc() -> None:
    """Naive timestamps are UTC, then converted to CDMX civil day."""
    # Same civil setup as Window A but with naive ISO (no offset).
    port = InMemoryMessageHistory(
        {
            13: [
                {"role": "vip", "text": "a", "timestamp": "2026-07-01T16:00:00"},
                {"role": "vip", "text": "b", "timestamp": "2026-07-02T02:00:00"},
            ]
        }
    )
    fixed = datetime(2026, 7, 2, 4, 0, 0, tzinfo=UTC)
    retriever = ContextRetriever(port, clock=lambda: fixed)
    ctx = await retriever.fetch(_turn(13), _comprehension())
    assert ctx["is_first_message_of_day"] is False


@pytest.mark.asyncio
async def test_stubs_return_none() -> None:
    turn = _turn()
    c = _comprehension()
    # ScheduleRetriever is a real seat after H9 (see test_schedule_retriever.py).
    for cls in (
        ProfileRetriever,
        MemoryRetriever,
        PolicyRetriever,
        ExamplesRetriever,
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


def test_retrievers_have_no_cross_peer_imports_ast() -> None:
    """H.4: retriever modules must not import peer retrievers (no shared snapshot)."""
    import ast
    from pathlib import Path

    root = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "diana"
        / "cognitive"
        / "retrievers"
    )
    peer_names = (
        "history",
        "context",
        "memory",
        "policy",
        "examples",
        "profile",
        "schedule",
        "persona_facts",
        "voice_patterns",
    )
    for name in peer_names:
        path = root / f"{name}.py"
        assert path.is_file(), path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "diana.cognitive.retrievers" not in alias.name, (
                        f"{path.name} imports {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "diana.cognitive.retrievers" or module.startswith(
                    "diana.cognitive.retrievers."
                ):
                    raise AssertionError(f"{path.name} imports from {module}")
                # Relative peer import: from .history import ...
                if module.startswith(".") and not module.startswith(".."):
                    # . alone is package self; .history etc. are peers
                    if module != ".":
                        raise AssertionError(
                            f"{path.name} relative-imports peer {module}"
                        )


def test_retrievers_are_read_only_ast() -> None:
    """H.4 lightweight: no persistence mutators (commit/flush/delete/session.add)."""
    import ast
    from pathlib import Path

    root = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "diana"
        / "cognitive"
        / "retrievers"
    )
    # Local list.append is fine; persistence-shaped mutators are not.
    forbidden_attrs = frozenset({"commit", "flush", "delete", "rollback"})
    peer_files = (
        "history.py",
        "context.py",
        "memory.py",
        "policy.py",
        "examples.py",
        "profile.py",
        "schedule.py",
        "persona_facts.py",
        "voice_patterns.py",
    )
    for filename in peer_files:
        path = root / filename
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs:
                raise AssertionError(
                    f"{filename} uses mutating attribute .{node.attr} (read-only H.4)"
                )
            # session.add / db.add style
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add"
            ):
                raise AssertionError(
                    f"{filename} calls .add(...) (read-only H.4)"
                )
        for bad in ("sqlalchemy", "Session", ".commit(", ".delete("):
            assert bad not in source, f"{filename} must not contain {bad!r}"


# ── F2 real (non-stub) retriever path tests ────────────────────────────────


@pytest.mark.asyncio
async def test_memory_retriever_returns_none_when_vip_id_none() -> None:
    """BR-15: MemoryRetriever returns None for unidentified VIP even with deps."""
    from unittest.mock import AsyncMock, MagicMock

    embed = MagicMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()
    retriever = MemoryRetriever(embedding_service=embed, repo=repo)
    turn = IncomingTurn(turn_id=uuid4(), chat_id=100, text="hola", vip_id=None)
    result = await retriever.fetch(turn, _comprehension())
    assert result is None
    embed.embed.assert_not_called()
    repo.find_by_vip_and_similarity.assert_not_called()


@pytest.mark.asyncio
async def test_memory_retriever_returns_empty_on_no_results() -> None:
    """MemoryRetriever returns [] when repo returns no results."""
    from unittest.mock import AsyncMock, MagicMock

    embed = MagicMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()
    repo.find_by_vip_and_similarity = AsyncMock(return_value=[])
    retriever = MemoryRetriever(embedding_service=embed, repo=repo)
    turn = IncomingTurn(
        turn_id=uuid4(),
        chat_id=100,
        text="hola",
        vip_id=uuid4(),
    )
    result = await retriever.fetch(turn, _comprehension())
    assert result == []


@pytest.mark.asyncio
async def test_memory_retriever_formats_results() -> None:
    """MemoryRetriever formats repo rows into [category] fact strings."""
    from unittest.mock import AsyncMock, MagicMock

    embed = MagicMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()
    repo.find_by_vip_and_similarity = AsyncMock(
        return_value=[
            {"category": "preference", "content": {"fact": "likes coffee"}},
            {"category": "fact", "content": {"fact": "born in 1990"}},
            {"category": "general", "content": {"note": "no fact key"}},
        ]
    )
    retriever = MemoryRetriever(embedding_service=embed, repo=repo)
    turn = IncomingTurn(
        turn_id=uuid4(),
        chat_id=100,
        text="hola",
        vip_id=uuid4(),
    )
    result = await retriever.fetch(turn, _comprehension())
    assert result == [
        "[preference] likes coffee",
        "[fact] born in 1990",
        "[general] {'note': 'no fact key'}",
    ]


@pytest.mark.asyncio
async def test_policy_retriever_returns_empty_on_no_results() -> None:
    """PolicyRetriever returns [] when repo returns no results."""
    from unittest.mock import AsyncMock, MagicMock

    embed = MagicMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()
    repo.find_active_by_similarity = AsyncMock(return_value=[])
    retriever = PolicyRetriever(embedding_service=embed, repo=repo)
    result = await retriever.fetch(_turn(), _comprehension())
    assert result == []


@pytest.mark.asyncio
async def test_policy_retriever_formats_results() -> None:
    """PolicyRetriever formats repo rows into trigger/rule strings."""
    from unittest.mock import AsyncMock, MagicMock

    embed = MagicMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()
    repo.find_active_by_similarity = AsyncMock(
        return_value=[
            {"trigger_description": "user says bye", "rule": "say bye back"},
            {"trigger_description": "user asks help", "rule": "offer assistance"},
        ]
    )
    retriever = PolicyRetriever(embedding_service=embed, repo=repo)
    result = await retriever.fetch(_turn(), _comprehension())
    assert result == [
        "Trigger: user says bye | Rule: say bye back",
        "Trigger: user asks help | Rule: offer assistance",
    ]


@pytest.mark.asyncio
async def test_examples_retriever_returns_empty_on_no_results() -> None:
    """ExamplesRetriever returns [] when repo returns no results."""
    from unittest.mock import AsyncMock, MagicMock

    embed = MagicMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()
    repo.find_by_similarity = AsyncMock(return_value=[])
    retriever = ExamplesRetriever(embedding_service=embed, repo=repo)
    result = await retriever.fetch(_turn(), _comprehension())
    assert result == []


@pytest.mark.asyncio
async def test_examples_retriever_formats_results() -> None:
    """ExamplesRetriever formats repo rows into turn/draft/corrected strings."""
    from unittest.mock import AsyncMock, MagicMock

    embed = MagicMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()
    repo.find_by_similarity = AsyncMock(
        return_value=[
            {"turn_text": "hello", "draft_text": "hi", "corrected_text": "hello there"},
        ]
    )
    retriever = ExamplesRetriever(embedding_service=embed, repo=repo, counter_example_chance=0.0)
    result = await retriever.fetch(_turn(), _comprehension())
    assert result == [
        "Turn: hello | Draft: hi | Corrected: hello there",
    ]


@pytest.mark.asyncio
async def test_examples_retriever_counter_example() -> None:
    """ExamplesRetriever includes [COUNTER-EXAMPLE] prefix when counter_example_chance=1.0."""
    from unittest.mock import AsyncMock, MagicMock

    embed = MagicMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()

    async def find_by_similarity(
        embedding: list[float],
        threshold: float,
        limit: int,
        counter_example: bool = False,
    ) -> list[dict[str, str]]:
        if counter_example:
            return [
                {
                    "turn_text": "bad example",
                    "draft_text": "wrong",
                    "corrected_text": "right",
                }
            ]
        return [
            {"turn_text": "hello", "draft_text": "hi", "corrected_text": "hello there"},
        ]

    repo.find_by_similarity = find_by_similarity
    retriever = ExamplesRetriever(
        embedding_service=embed, repo=repo, counter_example_chance=1.0,
    )
    result = await retriever.fetch(_turn(), _comprehension())
    assert result is not None
    assert len(result) == 2
    assert result[0] == "Turn: hello | Draft: hi | Corrected: hello there"
    assert "[COUNTER-EXAMPLE]" in result[1]
    assert "bad example" in result[1]



@pytest.mark.asyncio
async def test_policy_static_tema_match_without_embeddings() -> None:
    """J.5: static policies match by tema without repo/embed deps."""
    policies = [
        {
            "id": "no_promesas_contenido",
            "tema": ["contenido", "expectativas"],
            "regla": "No prometo fechas concretas.",
        },
        {
            "id": "no_consultas",
            "tema": ["psicologia"],
            "regla": "No doy consultas clínicas.",
        },
    ]
    retriever = PolicyRetriever(static_policies=policies)
    c = Comprehension(
        intent="chat",
        topics=["contenido"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=True,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
    )
    result = await retriever.fetch(_turn(), c)
    assert result == [
        "Trigger: no_promesas_contenido | Rule: No prometo fechas concretas."
    ]


@pytest.mark.asyncio
async def test_policy_static_no_match_returns_empty_list() -> None:
    """Static catalog present but no tema match → [] (not None)."""
    policies = [
        {"id": "x", "tema": ["contenido"], "regla": "rule x"},
    ]
    retriever = PolicyRetriever(static_policies=policies)
    c = _comprehension()  # topics empty, intent chat
    result = await retriever.fetch(_turn(), c)
    assert result == []


@pytest.mark.asyncio
async def test_policy_static_plus_db_merge_dedupes_by_rule() -> None:
    """Static hits first; DB appends; de-dupe by rule text after '| Rule: '."""
    from unittest.mock import AsyncMock, MagicMock

    policies = [
        {"id": "static1", "tema": ["limites"], "regla": "same rule text"},
    ]
    embed = MagicMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()
    repo.find_active_by_similarity = AsyncMock(
        return_value=[
            {"trigger_description": "db trig", "rule": "same rule text"},
            {"trigger_description": "other", "rule": "unique db rule"},
        ]
    )
    retriever = PolicyRetriever(
        embedding_service=embed,
        repo=repo,
        static_policies=policies,
    )
    c = Comprehension(
        intent="limites",
        topics=["limites"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=True,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
    )
    result = await retriever.fetch(_turn(), c)
    assert result[0] == "Trigger: static1 | Rule: same rule text"
    assert "Trigger: other | Rule: unique db rule" in result
    # de-duped: only one with same rule text
    rules = [r.split("| Rule: ", 1)[1] for r in result]
    assert rules.count("same rule text") == 1



@pytest.mark.asyncio
async def test_policy_static_empty_list_is_stub_none() -> None:
    """static_policies=[] with no deps behaves like stub (None)."""
    retriever = PolicyRetriever(static_policies=[])
    assert await retriever.fetch(_turn(), _comprehension()) is None


@pytest.mark.asyncio
async def test_policy_both_sources_static_only_match() -> None:
    """Both deps + static: only static tema hits when DB empty."""
    from unittest.mock import AsyncMock, MagicMock

    policies = [{"id": "s1", "tema": ["contenido"], "regla": "static rule"}]
    embed = MagicMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()
    repo.find_active_by_similarity = AsyncMock(return_value=[])
    retriever = PolicyRetriever(
        embedding_service=embed, repo=repo, static_policies=policies
    )
    c = Comprehension(
        intent="chat",
        topics=["contenido"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=True,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
    )
    result = await retriever.fetch(_turn(), c)
    assert result == ["Trigger: s1 | Rule: static rule"]


@pytest.mark.asyncio
async def test_policy_both_sources_db_only_match() -> None:
    """Both deps + static: only DB hits when static temas miss."""
    from unittest.mock import AsyncMock, MagicMock

    policies = [{"id": "s1", "tema": ["psicologia"], "regla": "static only"}]
    embed = MagicMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()
    repo.find_active_by_similarity = AsyncMock(
        return_value=[{"trigger_description": "db", "rule": "db rule"}]
    )
    retriever = PolicyRetriever(
        embedding_service=embed, repo=repo, static_policies=policies
    )
    c = Comprehension(
        intent="chat",
        topics=["otro"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=True,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
    )
    result = await retriever.fetch(_turn(), c)
    assert result == ["Trigger: db | Rule: db rule"]


@pytest.mark.asyncio
async def test_policy_both_sources_no_hits_returns_empty() -> None:
    """Both configured, no static match and no DB rows → []."""
    from unittest.mock import AsyncMock, MagicMock

    policies = [{"id": "s1", "tema": ["psicologia"], "regla": "x"}]
    embed = MagicMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()
    repo.find_active_by_similarity = AsyncMock(return_value=[])
    retriever = PolicyRetriever(
        embedding_service=embed, repo=repo, static_policies=policies
    )
    c = Comprehension(
        intent="chat",
        topics=["otro"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=True,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
    )
    assert await retriever.fetch(_turn(), c) == []


@pytest.mark.asyncio
async def test_policy_db_exception_preserves_static_hits() -> None:
    """Issue 3: embed/DB failure after static match still returns static lines."""
    from unittest.mock import AsyncMock, MagicMock

    policies = [{"id": "s1", "tema": ["contenido"], "regla": "keep me"}]
    embed = MagicMock()
    embed.embed = AsyncMock(side_effect=RuntimeError("embed down"))
    repo = AsyncMock()
    retriever = PolicyRetriever(
        embedding_service=embed, repo=repo, static_policies=policies
    )
    c = Comprehension(
        intent="chat",
        topics=["contenido"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=True,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
    )
    result = await retriever.fetch(_turn(), c)
    assert result == ["Trigger: s1 | Rule: keep me"]



@pytest.mark.asyncio
async def test_production_catalog_policy_contenido_gold() -> None:
    """Issue 8: production soft policy gold — contenido tema matches."""
    from diana.cognitive.persona_catalog import load_persona_catalog

    catalog = load_persona_catalog()
    retriever = PolicyRetriever(static_policies=catalog["policies"])
    c = Comprehension(
        intent="chat",
        topics=["contenido"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=True,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
    )
    result = await retriever.fetch(_turn(), c)
    assert isinstance(result, list) and result
    assert any("no_promesas_contenido" in line or "peticion_fotos_video" in line for line in result)



@pytest.mark.asyncio
async def test_policy_malformed_db_rows_preserve_static() -> None:
    """Malformed DB rows must not drop already-matched static hits."""
    from unittest.mock import AsyncMock, MagicMock

    policies = [{"id": "s1", "tema": ["contenido"], "regla": "static keep"}]
    embed = MagicMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()
    repo.find_active_by_similarity = AsyncMock(return_value=[{}])
    retriever = PolicyRetriever(
        embedding_service=embed, repo=repo, static_policies=policies
    )
    c = Comprehension(
        intent="chat",
        topics=["contenido"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=True,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
    )
    result = await retriever.fetch(_turn(), c)
    assert result == ["Trigger: s1 | Rule: static keep"]


# ── Profile REAL mínimo (residuals-polish item4) ─────────────────────────────


@pytest.mark.asyncio
async def test_profile_retriever_returns_none_without_repo() -> None:
    """Stub compat: no-arg / no-repo ProfileRetriever always returns None."""
    result = await ProfileRetriever().fetch(_turn(), _comprehension())
    assert result is None


@pytest.mark.asyncio
async def test_profile_retriever_returns_none_when_vip_id_none() -> None:
    """BR-15: unidentified VIP → None and repo not called."""
    from unittest.mock import AsyncMock

    repo = AsyncMock()
    retriever = ProfileRetriever(repo=repo)
    turn = IncomingTurn(turn_id=uuid4(), chat_id=100, text="hola", vip_id=None)
    result = await retriever.fetch(turn, _comprehension())
    assert result is None
    repo.get_by_vip_id.assert_not_called()


@pytest.mark.asyncio
async def test_profile_retriever_returns_none_on_miss() -> None:
    """Miss: repo returns None → fetch None."""
    from unittest.mock import AsyncMock

    repo = AsyncMock()
    repo.get_by_vip_id = AsyncMock(return_value=None)
    vip_id = uuid4()
    retriever = ProfileRetriever(repo=repo)
    turn = IncomingTurn(turn_id=uuid4(), chat_id=100, text="hola", vip_id=vip_id)
    result = await retriever.fetch(turn, _comprehension())
    assert result is None
    repo.get_by_vip_id.assert_awaited_once_with(vip_id)


@pytest.mark.asyncio
async def test_profile_retriever_returns_tipo_content_on_hit() -> None:
    """Hit: repo row → {"tipo", "content"} only (no embedding)."""
    from unittest.mock import AsyncMock

    vip_id = uuid4()
    row = {
        "vip_id": str(vip_id),
        "tipo": "summary",
        "content": {"fact": "prefers morning"},
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    repo = AsyncMock()
    repo.get_by_vip_id = AsyncMock(return_value=row)
    retriever = ProfileRetriever(repo=repo)
    turn = IncomingTurn(turn_id=uuid4(), chat_id=100, text="hola", vip_id=vip_id)
    result = await retriever.fetch(turn, _comprehension())
    assert result == {"tipo": "summary", "content": {"fact": "prefers morning"}}
    repo.get_by_vip_id.assert_awaited_once_with(vip_id)


@pytest.mark.asyncio
async def test_profile_retriever_returns_none_on_empty_content() -> None:
    """Null-like content (PLAN A4 / D.5) → None so ContextBuilder omits block.

    Covers None, {}, whitespace/empty str, and empty list (ContextBuilder parity).
    """
    from unittest.mock import AsyncMock

    vip_id = uuid4()
    retriever = ProfileRetriever(repo=AsyncMock())
    turn = IncomingTurn(turn_id=uuid4(), chat_id=100, text="hola", vip_id=vip_id)

    for empty_content in (None, {}, "", "   ", [], ()):
        retriever._repo.get_by_vip_id = AsyncMock(
            return_value={
                "tipo": "summary",
                "content": empty_content,
                "vip_id": str(vip_id),
            }
        )
        assert await retriever.fetch(turn, _comprehension()) is None, empty_content


@pytest.mark.asyncio
async def test_profile_retriever_hollow_schema_envelope_is_none() -> None:
    """Option A: empty facts+notes shell (or partial shell, no other keys) → None."""
    from unittest.mock import AsyncMock

    vip_id = uuid4()
    retriever = ProfileRetriever(repo=AsyncMock())
    turn = IncomingTurn(turn_id=uuid4(), chat_id=100, text="hola", vip_id=vip_id)

    hollow_payloads = (
        {"facts": {}, "notes": []},
        {"facts": {}},
        {"notes": []},
    )
    for content in hollow_payloads:
        retriever._repo.get_by_vip_id = AsyncMock(
            return_value={
                "tipo": "summary",
                "content": content,
                "vip_id": str(vip_id),
            }
        )
        assert await retriever.fetch(turn, _comprehension()) is None, content


@pytest.mark.asyncio
async def test_profile_retriever_legacy_flat_content_still_hits() -> None:
    """Legacy flat ``{"fact": ...}`` must remain a hit (not hollow)."""
    from unittest.mock import AsyncMock

    vip_id = uuid4()
    row = {
        "vip_id": str(vip_id),
        "tipo": "summary",
        "content": {"fact": "prefers morning"},
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    repo = AsyncMock()
    repo.get_by_vip_id = AsyncMock(return_value=row)
    retriever = ProfileRetriever(repo=repo)
    turn = IncomingTurn(turn_id=uuid4(), chat_id=100, text="hola", vip_id=vip_id)
    result = await retriever.fetch(turn, _comprehension())
    assert result == {"tipo": "summary", "content": {"fact": "prefers morning"}}


@pytest.mark.asyncio
async def test_profile_retriever_whitespace_only_facts_is_none() -> None:
    """H2: whitespace-only structured facts are hollow → None (shared helper)."""
    from unittest.mock import AsyncMock

    vip_id = uuid4()
    retriever = ProfileRetriever(repo=AsyncMock())
    turn = IncomingTurn(turn_id=uuid4(), chat_id=100, text="hola", vip_id=vip_id)
    retriever._repo.get_by_vip_id = AsyncMock(
        return_value={
            "tipo": "summary",
            "content": {"facts": {"city": "   "}, "notes": []},
            "vip_id": str(vip_id),
        }
    )
    assert await retriever.fetch(turn, _comprehension()) is None


class _FakeProvider:
    """Minimal PersonaCatalogProvider double with a mutable catalog."""

    def __init__(self, catalog) -> None:
        self.catalog = catalog

    async def get_catalog(self, channel_type: str = "vip"):
        return self.catalog


@pytest.mark.asyncio
async def test_policy_hot_swap_via_provider() -> None:
    """PolicyRetriever picks up a new policies slice when the catalog changes."""
    from diana.cognitive.retrievers.policy import PolicyRetriever

    v1 = {"policies": [{"id": "s1", "tema": ["contenido"], "regla": "rule v1"}]}
    v2 = {"policies": [{"id": "s2", "tema": ["contenido"], "regla": "rule v2"}]}
    provider = _FakeProvider(dict(v1))
    retriever = PolicyRetriever(persona_catalog_provider=provider)  # type: ignore[arg-type]
    c = Comprehension(
        intent="chat",
        topics=["contenido"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=True,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
    )

    result = await retriever.fetch(_turn(), c)
    assert result == ["Trigger: s1 | Rule: rule v1"]

    provider.catalog = dict(v2)
    result = await retriever.fetch(_turn(), c)
    assert result == ["Trigger: s2 | Rule: rule v2"]


@pytest.mark.asyncio
async def test_policy_provider_none_falls_back_to_static() -> None:
    from diana.cognitive.retrievers.policy import PolicyRetriever

    policies = [{"id": "s1", "tema": ["contenido"], "regla": "static rule"}]
    provider = _FakeProvider(None)
    retriever = PolicyRetriever(
        static_policies=policies,
        persona_catalog_provider=provider,  # type: ignore[arg-type]
    )
    c = Comprehension(
        intent="chat",
        topics=["contenido"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=True,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
    )
    result = await retriever.fetch(_turn(), c)
    assert result == ["Trigger: s1 | Rule: static rule"]


@pytest.mark.asyncio
async def test_schedule_fallback_is_channel_neutral_for_atencion() -> None:
    """FIX-R2-3: the unpopulated-channel fallback must not carry VIP slang.

    A provider returning None (stub/misconfigured wiring) leaves the atencion
    channel with the defensive ``_DEFAULT_SCHEDULE_RESPONSES`` fallback, which
    must be neutral — never the coqueta "jsjsjs" style B3 removed from
    ``persona_atencion.json``.
    """
    from diana.cognitive.retrievers.schedule import ScheduleRetriever

    class _FixedClock:
        def now(self) -> datetime:
            return datetime(2026, 7, 22, 23, 0, tzinfo=UTC)  # Wednesday

    class _FixedRng:
        def choice(self, seq: list[str]) -> str:
            return seq[0]

    provider = _FakeProvider(None)
    retriever = ScheduleRetriever(
        [],
        [],
        "America/Mexico_City",
        _FixedClock(),
        rng=_FixedRng(),
        persona_catalog_provider=provider,  # type: ignore[arg-type]
    )
    atencion_turn = _turn()
    atencion_turn.channel_type = "atencion"
    result = await retriever.fetch(atencion_turn, _comprehension())
    assert result is not None and result["tipo"] == "respuesta_libre"
    assert "jsjsjs" not in result["respuesta_sugerida"]
    assert "jsjs" not in result["respuesta_sugerida"]


@pytest.mark.asyncio
async def test_policy_db_path_channel_scopes_atencion_to_all() -> None:
    """FIX-R2-4: the PolicyRetriever DB path is channel-scoped.

    An atencion turn must request ``scope="all"`` (never load a VIP-scoped
    policy row); a VIP turn keeps the unfiltered lookup (``scope=None``).
    """
    from unittest.mock import AsyncMock, MagicMock

    def _side_effect(*args, **kwargs):
        # Simulate the SQL filter: scope="all" → only scope='all' rows;
        # scope=None → unfiltered (returns the VIP-scoped row).
        scope = kwargs.get("scope")
        row = {"trigger_description": "vip only", "rule": "VIP-scoped rule"}
        return [] if scope == "all" else [row]

    embed = MagicMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()
    repo.find_active_by_similarity = AsyncMock(side_effect=_side_effect)
    retriever = PolicyRetriever(embedding_service=embed, repo=repo)

    atencion_turn = _turn()
    atencion_turn.channel_type = "atencion"
    result = await retriever.fetch(atencion_turn, _comprehension())
    assert result == []
    assert repo.find_active_by_similarity.await_args.kwargs.get("scope") == "all"

    result = await retriever.fetch(_turn(), _comprehension())
    assert result == ["Trigger: vip only | Rule: VIP-scoped rule"]
    assert repo.find_active_by_similarity.await_args.kwargs.get("scope") is None
