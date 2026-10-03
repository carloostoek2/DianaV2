"""Policy embedding retry + zero-marker repair (hardener/persona-reglas ítem 3, D2)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

from diana.application.policy_embedding import (
    PolicyEmbeddingRepairService,
    embed_policy_text,
    policy_embedding_text,
)


class _Emb:
    def __init__(self, outcomes):
        self.outcomes, self.calls, self.warmups = list(outcomes), [], 0

    async def warmup(self):
        self.warmups += 1

    async def embed(self, text):
        self.calls.append(text)
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o


async def test_first_try_success_no_warmup():
    e = _Emb([[0.1] * 384])
    assert await embed_policy_text(e, "t\nr") == [0.1] * 384
    assert e.warmups == 0 and e.calls == ["t\nr"]


async def test_retry_after_failure_warms_up_then_succeeds():
    e = _Emb([RuntimeError("x"), [0.2] * 384])
    assert await embed_policy_text(e, "t\nr") == [0.2] * 384
    assert e.warmups == 1


async def test_persistent_failure_returns_none():
    assert await embed_policy_text(_Emb([RuntimeError(), RuntimeError()]), "t") is None


async def test_no_embedder_returns_none():
    assert await embed_policy_text(None, "t") is None


async def test_repair_reembeds_zero_rows_with_insert_text():
    repo = AsyncMock()
    repo.list_active_zero_embedding.return_value = [
        SimpleNamespace(id=1, trigger_description="T", rule="R")
    ]
    e = _Emb([[0.3] * 384])
    out = await PolicyEmbeddingRepairService(repo, e).repair_once(limit=10)
    assert out == {"found": 1, "repaired": 1, "failed": 0}
    assert e.calls == [policy_embedding_text("T", "R")] == ["T\nR"]
    repo.set_embedding.assert_awaited_once_with(1, [0.3] * 384)


async def test_repair_keeps_marker_when_embed_still_fails(caplog):
    repo = AsyncMock()
    repo.list_active_zero_embedding.return_value = [
        SimpleNamespace(id=1, trigger_description="T", rule="R")
    ]
    e = _Emb([RuntimeError(), RuntimeError()])
    with caplog.at_level(logging.INFO, logger="diana.application"):
        out = await PolicyEmbeddingRepairService(repo, e).repair_once()
    assert out == {"found": 1, "repaired": 0, "failed": 1}
    repo.set_embedding.assert_not_awaited()
    recs = [r for r in caplog.records if r.getMessage() == "policy_embedding_repair"]
    assert recs and recs[-1].levelno == logging.WARNING
    assert recs[-1].failed == 1


async def test_repair_never_writes_a_zero_vector():
    repo = AsyncMock()
    repo.list_active_zero_embedding.return_value = [
        SimpleNamespace(id=1, trigger_description="T", rule="R")
    ]
    out = await PolicyEmbeddingRepairService(repo, _Emb([[0.0] * 384])).repair_once()
    assert out == {"found": 1, "repaired": 0, "failed": 1}
    repo.set_embedding.assert_not_awaited()


async def test_repair_noop_when_no_rows(caplog):
    repo = AsyncMock()
    repo.list_active_zero_embedding.return_value = []
    with caplog.at_level(logging.INFO, logger="diana.application"):
        out = await PolicyEmbeddingRepairService(repo, _Emb([])).repair_once()
    assert out == {"found": 0, "repaired": 0, "failed": 0}
    recs = [r for r in caplog.records if r.getMessage() == "policy_embedding_repair"]
    assert recs and recs[-1].levelno == logging.INFO
