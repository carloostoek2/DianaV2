"""MemoryExtractionService unit tests — fakes only (no DB / no network).

Covers the ordered best-effort pipeline: flag gate → terminal gate → vip
gate → binding → message filter → prompt (no-repeat summary) → LLM fail-soft
→ consolidation → semantic dedup → fail-closed sensitivity → incremental
insert. Fakes mirror the Pool 1 backfill test doubles.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import zlib

from diana.application.memory_extraction_service import (
    MemoryExtractionService,
    PostTurnExtractionReport,
)
from diana.application.memory_backfill_service import (
    HechoExtracted,
    WindowExtraction,
)
from diana.application.ports import MemoryInsert, TurnRecord, VipRecord

CHAT_ID = 100
_TURN_START = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)


_UNSET = object()


def _turn(
    *,
    status: str = "delivered",
    vip_id: UUID | object = _UNSET,
    chat_id: int = CHAT_ID,
    created_at: datetime | None = _TURN_START,
) -> TurnRecord:
    resolved: UUID | None = uuid4() if vip_id is _UNSET else vip_id  # type: ignore[assignment]
    return TurnRecord(
        id=uuid4(),
        chat_id=chat_id,
        status=status,
        vip_id=resolved,
        created_at=created_at,
    )


def _vip(chat_id: int = CHAT_ID) -> VipRecord:
    return VipRecord(id=uuid4(), telegram_user_id=chat_id)


class FakeLLM:
    """Queue-driven structured LLM double (pattern Pool 1 backfill test)."""

    def __init__(
        self,
        responses: list[WindowExtraction] | None = None,
        *,
        fail_on_call: int | None = None,
    ) -> None:
        self._queue: deque[WindowExtraction] = deque(responses or [])
        self.fail_on_call = fail_on_call
        self.calls: list[list[dict]] = []

    def enqueue(self, value: WindowExtraction) -> None:
        self._queue.append(value)

    async def generate_structured(
        self, messages: list[dict], schema: type[Any], **kwargs: Any
    ) -> Any:
        self.calls.append(list(messages))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise RuntimeError("fake llm boom")
        if not self._queue:
            raise RuntimeError("FakeLLM structured response queue is empty")
        item = self._queue.popleft()
        if not isinstance(item, schema):
            raise TypeError(
                f"FakeLLM item {type(item).__name__} != schema {schema.__name__}"
            )
        return item


class FakeHistory:
    def __init__(self, messages: list[dict] | None = None) -> None:
        self.messages = list(messages or [])
        self.calls: list[tuple[int, int]] = []

    async def list_all(self, chat_id: int, *, page_size: int = 500) -> list[dict]:
        self.calls.append((chat_id, page_size))
        return list(self.messages)

    async def count(self, chat_id: int) -> int:
        return len(self.messages)


class FakeTurns:
    def __init__(self, turns: list[TurnRecord] | None = None) -> None:
        self._turns = {t.id: t for t in (turns or [])}

    def add(self, turn: TurnRecord) -> None:
        self._turns[turn.id] = turn

    async def get(self, turn_id: UUID) -> TurnRecord | None:
        rec = self._turns.get(turn_id)
        return rec.model_copy(deep=True) if rec else None

    # Rest of the TurnStore protocol — unused by the service, kept for
    # structural typing parity.
    async def create(self, turn: TurnRecord) -> TurnRecord:
        raise NotImplementedError

    async def list_non_terminal(self, chat_id: int) -> list[TurnRecord]:
        raise NotImplementedError

    async def list_all_non_terminal(self) -> list[TurnRecord]:
        raise NotImplementedError

    async def transition(
        self,
        turn_id: UUID,
        status: str,
        *,
        superseded_by: UUID | None = None,
        error: str | None = None,
    ) -> TurnRecord:
        raise NotImplementedError


class FakeVips:
    def __init__(self, vips: list[VipRecord] | None = None) -> None:
        self._vips = {v.id: v for v in (vips or [])}

    def add(self, vip: VipRecord) -> None:
        self._vips[vip.id] = vip

    async def get_by_id(self, vip_id: UUID) -> VipRecord | None:
        return self._vips.get(vip_id)


class FakeMemories:
    """MemoryFactsWriter double: known rows + configurable dedup hits."""

    def __init__(
        self,
        known: list[dict] | None = None,
        *,
        hits_by_category: dict[str, list[dict]] | None = None,
    ) -> None:
        self.known = [dict(m) for m in (known or [])]
        self._hits = {c: [dict(h) for h in hs] for c, hs in (hits_by_category or {}).items()}
        self.insert_calls: list[tuple[UUID, list[MemoryInsert]]] = []
        self.list_calls: list[tuple[UUID, tuple[str, ...] | None, int]] = []
        self.dedup_calls: list[tuple[UUID, float, str | None]] = []

    def add_hit(self, category: str, *, matched_text: str = "hit existente") -> None:
        self._hits[category] = [{"content": {"texto": matched_text}, "category": category}]

    async def list_by_vip(
        self,
        vip_id: UUID,
        *,
        statuses: tuple[str, ...] | None = None,
        limit: int = 200,
    ) -> list[dict]:
        self.list_calls.append((vip_id, statuses, limit))
        return [dict(m) for m in self.known]

    async def find_similar_facts(
        self,
        vip_id: UUID,
        embedding: list[float],
        *,
        threshold: float = 0.85,
        category: str | None = None,
    ) -> list[dict]:
        self.dedup_calls.append((vip_id, threshold, category))
        return [dict(h) for h in self._hits.get(category or "", [])]

    async def insert_facts(
        self, vip_id: UUID, *, rows: list[MemoryInsert]
    ) -> int:
        self.insert_calls.append((vip_id, list(rows)))
        return len(rows)


class FakeEmbedder:
    """Deterministic char-bigram pseudo-embedding (384d, Pool 1 pattern)."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        vec = [0.0] * self.dim
        norm = " ".join((text or "").casefold().split())
        for i in range(len(norm) - 1):
            h = zlib.crc32(norm[i : i + 2].encode("utf-8")) % self.dim
            vec[h] += 1.0
        return vec


def _service(
    *,
    enabled: bool = True,
    llm: FakeLLM | None = None,
    history: FakeHistory | None = None,
    turns: FakeTurns | None = None,
    memories: FakeMemories | None = None,
    vips: FakeVips | None = None,
    embedder: FakeEmbedder | None = None,
    dedup_threshold: float = 0.85,
) -> MemoryExtractionService:
    return MemoryExtractionService(
        feature_memory_enabled=enabled,
        llm=llm or FakeLLM(),
        embedder=embedder or FakeEmbedder(),
        history=history or FakeHistory(),
        turns=turns or FakeTurns(),
        memories=memories or FakeMemories(),
        vips=vips,
        dedup_threshold=dedup_threshold,
    )


def _turn_msgs(*texts: str, role: str = "vip", at: str = "2026-08-05T12:01:00+00:00") -> list[dict]:
    return [
        {"role": role, "text": text, "timestamp": at, "telegram_message_id": i}
        for i, text in enumerate(texts)
    ]


def _history_with_turn_msgs() -> FakeHistory:
    return FakeHistory(_turn_msgs("hola diana", role="vip"))


@pytest.mark.asyncio
async def test_disabled_when_flag_off() -> None:
    turn = _turn()
    llm = FakeLLM()
    memories = FakeMemories()
    svc = _service(enabled=False, llm=llm, memories=memories, turns=FakeTurns([turn]))
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "disabled"
    assert report.turn_id == turn.id
    assert llm.calls == []
    assert memories.insert_calls == []


@pytest.mark.asyncio
async def test_not_terminal_skips() -> None:
    turn = _turn(status="pending_approval")
    llm = FakeLLM()
    memories = FakeMemories()
    svc = _service(llm=llm, memories=memories, turns=FakeTurns([turn]))
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "not_terminal"
    assert llm.calls == []
    assert memories.insert_calls == []


@pytest.mark.asyncio
async def test_terminal_ok_extracts_and_classifies() -> None:
    turn = _turn()
    history = FakeHistory(
        _turn_msgs("hola diana", "me interesa el plan premium", role="vip")
        + _turn_msgs("perfecto, te lo dejo anotado", role="owner")
    )
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[
                    HechoExtracted(
                        seccion="preferencias",
                        texto="Le interesa el plan premium",
                        confianza=0.9,
                        sensible=False,
                    ),
                    HechoExtracted(
                        seccion="sensible",
                        texto="Mencionó problemas de salud",
                        confianza=0.8,
                        sensible=True,
                    ),
                ]
            )
        ]
    )
    memories = FakeMemories()
    svc = _service(llm=llm, history=history, memories=memories, turns=FakeTurns([turn]))
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "ok"
    assert report.inserted == 2
    assert report.pending_owner == 1
    assert report.vip_id == turn.vip_id
    assert len(memories.insert_calls) == 1
    (vip_id, rows) = memories.insert_calls[0]
    assert vip_id == turn.vip_id
    assert {r.status for r in rows} == {"auto", "pending_owner"}
    assert all(r.source_turn_id == turn.id for r in rows)
    by_status = {r.status: r for r in rows}
    assert by_status["auto"].approved_by == "auto"
    assert by_status["pending_owner"].approved_by is None


@pytest.mark.asyncio
async def test_sensitive_heuristic_upgrades_to_pending() -> None:
    turn = _turn()
    # LLM says preferencias + sensible=False, but the text hits _SENSITIVE_TERMS.
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[
                    HechoExtracted(
                        seccion="preferencias",
                        texto="le preocupa su salud",
                        confianza=0.9,
                        sensible=False,
                    )
                ]
            )
        ]
    )
    memories = FakeMemories()
    svc = _service(llm=llm, history=_history_with_turn_msgs(), memories=memories, turns=FakeTurns([turn]))
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "ok"
    assert report.pending_owner == 1
    rows = memories.insert_calls[0][1]
    assert rows[0].status == "pending_owner"
    assert rows[0].approved_by is None


@pytest.mark.asyncio
async def test_dedup_descarta_duplicado_semantico() -> None:
    turn = _turn()
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[
                    HechoExtracted(
                        seccion="preferencias",
                        texto="Le gusta el tono juguetón",
                        confianza=0.9,
                    )
                ]
            )
        ]
    )
    memories = FakeMemories(hits_by_category={"preferencias": [{"content": {"texto": "hit"}}]})
    svc = _service(llm=llm, history=_history_with_turn_msgs(), memories=memories, turns=FakeTurns([turn]))
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "ok"
    assert report.deduped == 1
    assert report.inserted == 0
    assert memories.insert_calls == []


@pytest.mark.asyncio
async def test_prompt_incluye_resumen_no_repetir() -> None:
    turn = _turn()
    history = FakeHistory(_turn_msgs("me gusta el trato cercano", role="vip"))
    llm = FakeLLM([WindowExtraction(hechos=[])])
    memories = FakeMemories(
        known=[
            {"category": "identidad", "content": {"texto": "Vive en Buenos Aires"}},
        ]
    )
    svc = _service(llm=llm, history=history, memories=memories, turns=FakeTurns([turn]))
    await svc.extract_post_turn(turn.id, CHAT_ID)
    assert len(llm.calls) == 1
    system_content = llm.calls[0][0]["content"]
    user_content = llm.calls[0][1]["content"]
    assert "Hechos ya conocidos (NO repetir)" in user_content
    assert "Vive en Buenos Aires" in user_content
    assert "[identidad]" in user_content
    assert "me gusta el trato cercano" in user_content
    # The no-repeat rule is in the system prompt too.
    assert "NO los repitas" in system_content


@pytest.mark.asyncio
async def test_no_messages_skips() -> None:
    turn = _turn()
    llm = FakeLLM()
    memories = FakeMemories()
    svc = _service(
        llm=llm,
        history=FakeHistory(),
        memories=memories,
        turns=FakeTurns([turn]),
    )
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "no_messages"
    assert llm.calls == []
    assert memories.insert_calls == []


@pytest.mark.asyncio
async def test_messages_before_turn_start_skipped() -> None:
    turn = _turn()
    history = FakeHistory(
        [
            {
                "role": "vip",
                "text": "viejo mensaje",
                "timestamp": "2026-08-05T11:59:00+00:00",
                "telegram_message_id": 1,
            }
        ]
    )
    llm = FakeLLM()
    svc = _service(llm=llm, history=history, turns=FakeTurns([turn]))
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "no_messages"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_turn_without_vip_skips() -> None:
    turn = _turn(vip_id=None)
    llm = FakeLLM()
    memories = FakeMemories()
    svc = _service(llm=llm, memories=memories, turns=FakeTurns([turn]))
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "not_vip"
    assert llm.calls == []
    assert memories.insert_calls == []


@pytest.mark.asyncio
async def test_binding_mismatch_fails_closed() -> None:
    turn = _turn()
    vips = FakeVips([VipRecord(id=turn.vip_id or uuid4(), telegram_user_id=999)])
    llm = FakeLLM()
    memories = FakeMemories()
    svc = _service(llm=llm, memories=memories, turns=FakeTurns([turn]), vips=vips)
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "failed"
    assert memories.insert_calls == []
    assert llm.calls == []


@pytest.mark.asyncio
async def test_llm_failure_fail_soft() -> None:
    turn = _turn()
    llm = FakeLLM(fail_on_call=1)
    memories = FakeMemories()
    svc = _service(llm=llm, history=_history_with_turn_msgs(), memories=memories, turns=FakeTurns([turn]))
    report = await svc.extract_post_turn(turn.id, CHAT_ID)  # must not raise
    assert report.status == "failed"
    assert memories.insert_calls == []


@pytest.mark.asyncio
async def test_unknown_turn_failed() -> None:
    svc = _service()
    report = await svc.extract_post_turn(uuid4(), CHAT_ID)
    assert report.status == "failed"


@pytest.mark.asyncio
async def test_empty_extraction_ok_zero() -> None:
    turn = _turn()
    llm = FakeLLM([WindowExtraction(hechos=[])])
    memories = FakeMemories()
    svc = _service(llm=llm, history=_history_with_turn_msgs(), memories=memories, turns=FakeTurns([turn]))
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "ok"
    assert report.inserted == 0
    assert memories.insert_calls == []


@pytest.mark.asyncio
async def test_consolidate_exact_duplicates_dropped() -> None:
    turn = _turn()
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[
                    HechoExtracted(seccion="preferencias", texto="Le gusta el café"),
                    HechoExtracted(seccion="preferencias", texto="  le gusta el café "),
                ]
            )
        ]
    )
    memories = FakeMemories()
    svc = _service(llm=llm, history=_history_with_turn_msgs(), memories=memories, turns=FakeTurns([turn]))
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "ok"
    assert report.inserted == 1
    assert memories.insert_calls[0][1][0].text == "Le gusta el café"
