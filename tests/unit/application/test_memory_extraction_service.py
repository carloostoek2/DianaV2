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
    trigger_message_id: int | None = None,
) -> TurnRecord:
    resolved: UUID | None = uuid4() if vip_id is _UNSET else vip_id  # type: ignore[assignment]
    return TurnRecord(
        id=uuid4(),
        chat_id=chat_id,
        status=status,
        vip_id=resolved,
        created_at=created_at,
        trigger_message_id=trigger_message_id,
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
        fail_insert: bool = False,
    ) -> None:
        self.known = [dict(m) for m in (known or [])]
        self._hits = {c: [dict(h) for h in hs] for c, hs in (hits_by_category or {}).items()}
        self.insert_calls: list[tuple[UUID, list[MemoryInsert]]] = []
        self.list_calls: list[tuple[UUID, tuple[str, ...] | None, int]] = []
        self.dedup_calls: list[tuple[UUID, float, str | None]] = []
        self.fail_insert = fail_insert

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
        if self.fail_insert:
            raise RuntimeError("fake db boom")
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
    assert "Hechos ya conocidos (DATOS" in user_content
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
async def test_binding_match_proceeds_and_unknown_vip_fails_closed() -> None:
    """Binding gate (Pool 1 pattern F5, L8): a VIP bound to the SAME chat_id
    lets the extraction proceed; an unknown VIP (``get_by_id`` → None) fails
    closed with zero I/O. Both positive branches of the fail-closed check —
    the mismatch branch is covered by test_binding_mismatch_fails_closed
    (mirror of the backfill service test pair)."""
    turn = _turn()
    history = _history_with_turn_msgs()
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
    # Match: the VIP row carries the SAME telegram_user_id as the chat.
    match_vips = FakeVips(
        [VipRecord(id=turn.vip_id or uuid4(), telegram_user_id=CHAT_ID)]
    )
    memories = FakeMemories()
    svc = _service(
        llm=llm,
        history=history,
        memories=memories,
        turns=FakeTurns([turn]),
        vips=match_vips,
    )
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "ok"
    assert memories.insert_calls != []

    # Unknown VIP (get_by_id → None): fail-closed, no LLM, no insert.
    unknown_vips = FakeVips([])
    llm2 = FakeLLM()
    memories2 = FakeMemories()
    svc2 = _service(
        llm=llm2,
        history=history,
        memories=memories2,
        turns=FakeTurns([turn]),
        vips=unknown_vips,
    )
    report2 = await svc2.extract_post_turn(turn.id, CHAT_ID)
    assert report2.status == "failed"
    assert llm2.calls == []
    assert memories2.insert_calls == []


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


# ---------------------------------------------------------------------------
# Fix round (Pool 3): M1 / S-MED / L3 / L5 / L7 / L8 + SEC F2 / F4 coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_message_before_mint_is_extracted() -> None:
    """M1 regression: the message that DISPATCHED the turn is appended to
    message_history BEFORE the turn mint, so its timestamp < turn.created_at.
    The window must start at the trigger's OWN timestamp — otherwise a
    single-message turn extracts nothing (or only the owner draft)."""
    turn = _turn(
        created_at=datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC),
        trigger_message_id=777,
    )
    history = FakeHistory(
        [
            {
                "role": "vip",
                "text": "hola diana",
                "timestamp": "2026-08-05T11:59:59.900+00:00",  # pre-mint!
                "telegram_message_id": 777,
            },
            {
                "role": "vip",
                "text": "quiero el plan premium",
                "timestamp": "2026-08-05T12:01:00+00:00",
                "telegram_message_id": 778,
            },
        ]
    )
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[
                    HechoExtracted(
                        seccion="comercial",
                        texto="Le interesa el plan premium",
                        confianza=0.9,
                    )
                ]
            )
        ]
    )
    memories = FakeMemories()
    svc = _service(llm=llm, history=history, memories=memories, turns=FakeTurns([turn]))
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "ok"
    assert report.inserted == 1
    user_content = llm.calls[0][1]["content"]
    # The trigger message (pre-mint timestamp) IS part of the transcript.
    assert "hola diana" in user_content
    assert "quiero el plan premium" in user_content


@pytest.mark.asyncio
async def test_superseded_turn_never_extracts() -> None:
    """S-MED: a superseded (cancelled) turn is terminal in the coordinator but
    must NOT trigger extraction — no LLM call, no inserts, no memory written
    with a wrong source_turn_id (REQ-MEM-07: only delivered/escalated/failed)."""
    turn = _turn(status="superseded")
    llm = FakeLLM()
    memories = FakeMemories()
    svc = _service(
        llm=llm,
        history=_history_with_turn_msgs(),
        memories=memories,
        turns=FakeTurns([turn]),
    )
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "not_terminal"
    assert llm.calls == []
    assert memories.insert_calls == []


@pytest.mark.asyncio
async def test_insert_facts_failure_returns_failed() -> None:
    """L8: the catch-all converts an insert failure into a ``failed`` report
    (best-effort R1) — the completed turn is never affected."""
    turn = _turn()
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[
                    HechoExtracted(
                        seccion="preferencias",
                        texto="Le gusta el café",
                        confianza=0.9,
                    )
                ]
            )
        ]
    )
    memories = FakeMemories(fail_insert=True)
    svc = _service(
        llm=llm,
        history=_history_with_turn_msgs(),
        memories=memories,
        turns=FakeTurns([turn]),
    )
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "failed"


@pytest.mark.asyncio
async def test_intra_run_semantic_duplicates_merged() -> None:
    """L5: two near-duplicate facts of the SAME turn (same section, similar
    text) are merged before the DB dedup — both would otherwise pass
    find_similar_facts (neither is persisted yet) and both be inserted."""
    turn = _turn()
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[
                    HechoExtracted(
                        seccion="preferencias",
                        texto="Le gusta el café",
                        confianza=0.9,
                    ),
                    HechoExtracted(
                        seccion="preferencias",
                        texto="le gusta el cafe",
                        confianza=0.7,
                    ),
                ]
            )
        ]
    )
    memories = FakeMemories()
    svc = _service(llm=llm, history=_history_with_turn_msgs(), memories=memories, turns=FakeTurns([turn]))
    report = await svc.extract_post_turn(turn.id, CHAT_ID)
    assert report.status == "ok"
    assert report.inserted == 1
    assert report.deduped == 1
    assert len(memories.insert_calls) == 1
    # The longer text survives and inherits the max confidence.
    row = memories.insert_calls[0][1][0]
    assert row.text == "Le gusta el café"
    assert row.confidence == 0.9


@pytest.mark.asyncio
async def test_prompt_no_repeat_uses_most_recent_facts() -> None:
    """L3: the 'do not repeat' summary shows the most RECENT facts
    (list_by_vip is oldest-first, so slice from the end) — the ones most
    likely to repeat in the current turn."""
    turn = _turn()
    history = FakeHistory(_turn_msgs("me gusta el trato cercano", role="vip"))
    llm = FakeLLM([WindowExtraction(hechos=[])])
    known = [
        {"category": "identidad", "content": {"texto": f"facto viejo {i}"}}
        for i in range(60)
    ]
    memories = FakeMemories(known=known)
    svc = _service(llm=llm, history=history, memories=memories, turns=FakeTurns([turn]))
    await svc.extract_post_turn(turn.id, CHAT_ID)
    user_content = llm.calls[0][1]["content"]
    assert "facto viejo 59" in user_content  # newest fact is shown
    assert "facto viejo 0" not in user_content  # oldest 10 dropped


@pytest.mark.asyncio
async def test_prompt_known_facts_fenced_and_data_disclaimer() -> None:
    """SEC-INJ-02 (F2): the known-facts section is fenced like the transcript
    and the system prompt declares ALL prompt texts as DATA, not instructions
    (a payload planted as a previous fact cannot degrade the classification)."""
    turn = _turn()
    history = FakeHistory(_turn_msgs("me gusta el trato cercano", role="vip"))
    llm = FakeLLM([WindowExtraction(hechos=[])])
    memories = FakeMemories(
        known=[{"category": "identidad", "content": {"texto": "Vive en Buenos Aires"}}]
    )
    svc = _service(llm=llm, history=history, memories=memories, turns=FakeTurns([turn]))
    await svc.extract_post_turn(turn.id, CHAT_ID)
    system_content = llm.calls[0][0]["content"]
    user_content = llm.calls[0][1]["content"]
    assert "```hechos_conocidos" in user_content
    assert "Vive en Buenos Aires" in user_content
    assert "Todos los textos de este prompt" in system_content
    assert "SEC-INJ-02" in system_content


def test_filter_turn_messages_window_and_fail_closed() -> None:
    """SEC F4 + window (A3/M1): only vip/owner messages with a valid
    timestamp >= since stay; untimestamped or unparseable rows are OUT of the
    window (fail-closed), and other roles never enter the transcript."""
    f = MemoryExtractionService._filter_turn_messages
    # Window lower bound = the trigger's own timestamp (M1).
    since = datetime(2026, 8, 5, 11, 59, 59, 900000, tzinfo=UTC)
    msgs = [
        {"role": "vip", "text": "viejo", "timestamp": "2026-08-05T11:59:00+00:00", "telegram_message_id": 1},
        {"role": "vip", "text": "trigger", "timestamp": "2026-08-05T11:59:59.900+00:00", "telegram_message_id": 2},
        {"role": "owner", "text": "draft", "timestamp": "2026-08-05T12:05:00+00:00", "telegram_message_id": 3},
        {"role": "vip", "text": "sin ts", "timestamp": None, "telegram_message_id": 4},
        {"role": "system", "text": "fuera", "timestamp": "2026-08-05T13:00:00+00:00", "telegram_message_id": 5},
        {"role": "vip", "text": "ts invalido", "timestamp": "no-es-fecha", "telegram_message_id": 6},
    ]
    out = f(msgs, since)
    assert [m["text"] for m in out] == ["trigger", "draft"]


def test_filter_turn_messages_naive_and_aware_mixed() -> None:
    """L7: naive timestamps never raise TypeError against an aware ``since``
    (both sides normalize to UTC-aware)."""
    f = MemoryExtractionService._filter_turn_messages
    since = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
    msgs = [
        {"role": "vip", "text": "naive dentro", "timestamp": "2026-08-05T12:01:00", "telegram_message_id": 1},
        {"role": "vip", "text": "naive afuera", "timestamp": "2026-08-05T11:00:00", "telegram_message_id": 2},
    ]
    out = f(msgs, since)
    assert [m["text"] for m in out] == ["naive dentro"]


def test_filter_turn_messages_since_none_and_cap() -> None:
    """L8 + S-MED cap: since=None keeps every valid-timestamped role message;
    max_messages keeps only the NEWEST messages of the window."""
    f = MemoryExtractionService._filter_turn_messages
    msgs = [
        {
            "role": "vip",
            "text": f"m{i}",
            "timestamp": f"2026-08-05T12:{i:02d}:00+00:00",
            "telegram_message_id": i,
        }
        for i in range(10)
    ]
    assert len(f(msgs, None)) == 10
    out = f(msgs, None, max_messages=3)
    assert [m["text"] for m in out] == ["m7", "m8", "m9"]


def test_window_since_uses_trigger_timestamp() -> None:
    """M1: the window lower bound is the TRIGGER message's own timestamp."""
    turn = _turn(trigger_message_id=777)
    msgs = [
        {"role": "vip", "text": "x", "timestamp": "2026-08-05T11:59:59.900+00:00", "telegram_message_id": 777},
        {"role": "vip", "text": "y", "timestamp": "2026-08-05T11:50:00+00:00", "telegram_message_id": 999},
    ]
    since = MemoryExtractionService._window_since(turn, msgs)
    assert since == datetime(2026, 8, 5, 11, 59, 59, 900000, tzinfo=UTC)


def test_window_since_falls_back_to_created_at() -> None:
    """M1 fallback: no trigger id (or trigger absent from history) → the
    previous behavior (turn.created_at) is preserved for recovery turns."""
    assert MemoryExtractionService._window_since(_turn(trigger_message_id=None), []) == _TURN_START
    turn_with_unknown_trigger = _turn(trigger_message_id=424242)
    assert MemoryExtractionService._window_since(turn_with_unknown_trigger, []) == _TURN_START


def test_cap_transcript_drops_oldest_lines() -> None:
    """L8: _cap_transcript keeps the NEWEST lines within the char budget."""
    lines = [f"linea-{i}-" + "x" * 100 for i in range(150)]
    capped = MemoryExtractionService._cap_transcript(lines)
    assert capped
    assert sum(len(line) for line in capped) <= 12_000
    assert capped[-1] == lines[-1]  # newest kept
    assert lines[0] not in capped  # oldest dropped
