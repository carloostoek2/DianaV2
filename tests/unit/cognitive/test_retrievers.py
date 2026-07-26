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
