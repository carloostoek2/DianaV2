"""F5-10 (Pool 4): anti-contamination + closure gates for the memory feature.

Final acceptance tests of the Fase 5 memory profile: (a) the Telegram layer
never touches the memories persistence directly (delegates to application
services — AGENTS.md §2.1); (b) the retriever only ever sees the calling
VIP's own memory (BR-15); (c) the visibility statuses keep pending_owner /
discarded out of the LLM context.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import pytest

import diana
from diana.cognitive.models import Comprehension, IncomingTurn


def _walk(pkg: str) -> list[Path]:
    root = Path(diana.__file__).resolve().parent
    return sorted((root / pkg).rglob("*.py"))


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


def test_telegram_layer_never_imports_memory_repos() -> None:
    """F5-10a: telegram/ imports application services, not persistence repos.

    Review fix (M1 Pool 4): the forbidden tokens carry the full module path
    (``infrastructure.db.repositories.memories``) so a real
    ``from diana.infrastructure.db.repositories.memories import ...`` is
    always caught, and the memory services are included as tokens too.
    """
    forbidden = (
        "infrastructure.db.repositories.memories",
        "infrastructure.db.repositories.backfill_queue",
        "cognitive.retrievers.memory",
        "memory_backfill",
        "memory_extraction",
        "import MemoryRetriever",
    )
    hits: list[str] = []
    for path in _walk("telegram"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                hits.append(f"{path.name}:{token}")
    assert hits == [], f"Telegram layer touching persistence directly: {hits}"


def test_visibility_statuses_keep_pending_out_of_context() -> None:
    """F5-10b: pending_owner/discarded are never part of the visible set."""
    from diana.infrastructure.db.repositories.memories import _VISIBLE_STATUSES

    assert set(_VISIBLE_STATUSES) == {"auto", "approved"}
    assert "pending_owner" not in _VISIBLE_STATUSES
    assert "discarded" not in _VISIBLE_STATUSES


@pytest.mark.asyncio
async def test_memory_retriever_scopes_to_own_vip() -> None:
    """F5-10c: the retriever filters by vip_id (BR-15) — no cross-VIP leaks."""
    from diana.cognitive.retrievers.memory import MemoryRetriever

    vip_a = uuid4()
    embed = AsyncMock()
    embed.embed = AsyncMock(return_value=[0.1] * 384)
    repo = AsyncMock()
    repo.find_by_vip_and_similarity = AsyncMock(return_value=[])
    retriever = MemoryRetriever(embedding_service=embed, repo=repo)
    turn = IncomingTurn(
        turn_id=uuid4(),
        chat_id=100,
        text="hola",
        vip_id=vip_a,
    )
    await retriever.fetch(turn, _comprehension())
    # The retriever passes the turn's OWN vip_id to the repo — it never
    # broadens or substitutes the scope (BR-15). Repo-level isolation is
    # additionally covered in e2e (test_sql_memories_repo.py::isolates_vips).
    repo.find_by_vip_and_similarity.assert_awaited_once_with(
        vip_a, ANY, threshold=0.75, limit=5
    )


# ---------------------------------------------------------------------------
# EA-05 (SPEC-EVOLUCION-AGENTE): profile synthesis never contaminates examples
# ---------------------------------------------------------------------------


def test_profile_synthesis_never_feeds_examples_bank() -> None:
    """EA-05: the Fase 1 synthesis/profile modules never reach the examples bank
    or the examples retriever. The synthesized profile is shadow-only: only
    ``recent_trend`` (Fase 2) and mood (Fase 3) will ever feed generation.
    Structural scan (F5 style) — prevents drift when Fase 2 wires recent_trend
    into the context."""
    synthesis_files = (
        "application/profile_synthesis_service.py",
        "application/profile_synthesis_trigger_service.py",
        "application/strong_signal_heuristics.py",
        "infrastructure/db/repositories/vip_profile.py",
    )
    examples_tokens = (
        "retrievers.examples",
        "repositories.examples",
        "examples_bank",
        "ExamplesRepo",
        "from diana.cognitive.retrievers import examples",
    )
    hits: list[str] = []
    root = Path(diana.__file__).resolve().parent
    for rel in synthesis_files:
        text = (root / rel).read_text(encoding="utf-8")
        for token in examples_tokens:
            if token in text:
                hits.append(f"{Path(rel).name}:{token}")
    assert hits == [], f"Profile synthesis touching examples bank: {hits}"


def test_examples_never_reads_profile_fields() -> None:
    """EA-05 reverse: the examples bank / examples retriever never reference
    ``stable_traits`` or ``sensitivities`` (the profile is not generation
    context, so its fields must not leak into the example layer)."""
    forbidden = ("stable_traits", "sensitivities")
    hits: list[str] = []
    root = Path(diana.__file__).resolve().parent
    for pkg in ("learning", "cognitive/retrievers", "infrastructure/db/repositories"):
        for path in _walk(pkg):
            if "examples" not in path.name:
                continue
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    hits.append(f"{path.name}:{token}")
    assert hits == [], f"Examples layer reading profile fields: {hits}"
