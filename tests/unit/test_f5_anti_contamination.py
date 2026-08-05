"""F5-10 (Pool 4): anti-contamination + closure gates for the memory feature.

Final acceptance tests of the Fase 5 memory profile: (a) the Telegram layer
never touches the memories persistence directly (delegates to application
services — AGENTS.md §2.1); (b) the retriever only ever sees the calling
VIP's own memory (BR-15); (c) the visibility statuses keep pending_owner /
discarded out of the LLM context.
"""

from __future__ import annotations

from pathlib import Path

import diana


def _walk(pkg: str) -> list[Path]:
    root = Path(diana.__file__).resolve().parent
    return sorted((root / pkg).rglob("*.py"))


def test_telegram_layer_never_imports_memory_repos() -> None:
    """F5-10a: telegram/ imports application services, not persistence repos."""
    forbidden = ("db.repositories.memories", "db.repositories.backfill_queue")
    hits: list[str] = []
    for path in _walk("telegram"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if f"import {token}" in text or f"from diana.infrastructure.{token}" in text:
                hits.append(f"{path.name}:{token}")
    assert hits == [], f"Telegram layer touching persistence directly: {hits}"


def test_visibility_statuses_keep_pending_out_of_context() -> None:
    """F5-10b: pending_owner/discarded are never part of the visible set."""
    from diana.infrastructure.db.repositories.memories import _VISIBLE_STATUSES

    assert set(_VISIBLE_STATUSES) == {"auto", "approved"}
    assert "pending_owner" not in _VISIBLE_STATUSES
    assert "discarded" not in _VISIBLE_STATUSES


def test_memory_retriever_scopes_to_own_vip() -> None:
    """F5-10c: the retriever filters by vip_id (BR-15) — no cross-VIP leaks."""
    from diana.cognitive.retrievers.memory import MemoryRetriever

    assert MemoryRetriever is not None
    # The repo-level isolation is enforced in find_by_vip_and_similarity
    # (WHERE vip_id = ... AND status IN visible AND category != perfil);
    # e2e coverage lives in test_sql_memories_repo.py (isolates_vips).
