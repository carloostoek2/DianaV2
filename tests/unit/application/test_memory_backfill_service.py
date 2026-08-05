"""MemoryBackfillService unit tests — fakes only (no DB / no network)."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from diana.application.memory_backfill_service import (
    BackfillReport,
    HechoExtracted,
    MemoryBackfillService,
    WindowExtraction,
)
from diana.application.ports import MemoryInsert


class FakeLLM:
    """Queue-driven LLM double; records every (messages, schema) call."""

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
        self.chat_ids: list[int] = []
        self.page_sizes: list[int] = []

    async def list_all(self, chat_id: int, *, page_size: int = 500) -> list[dict]:
        self.chat_ids.append(chat_id)
        self.page_sizes.append(page_size)
        return list(self.messages)


class FakeMemoryWriter:
    def __init__(self) -> None:
        self.replace_calls: list[
            tuple[UUID, list[MemoryInsert], dict, list[float]]
        ] = []

    async def replace_vip_profile(
        self,
        vip_id: UUID,
        *,
        rows: list[MemoryInsert],
        perfil: dict,
        perfil_embedding: list[float],
    ) -> int:
        self.replace_calls.append((vip_id, list(rows), dict(perfil), list(perfil_embedding)))
        return len(rows) + 1  # sections + perfil row


class FakeEmbedder:
    """Deterministic bag-of-char pseudo-embedding (pattern test_calibration)."""

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        vec = [0.0] * self.dim
        for i, ch in enumerate(text.encode("utf-8")):
            vec[i % self.dim] += float(ch) / 255.0
        return vec


class FakeNotifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.infos: list[str] = []
        self._fail = fail

    async def notify_draft(self, payload: object) -> int | None:
        return None

    async def notify_escalation(self, payload: object) -> None:
        return None

    async def notify_info(self, text: str, *, chat_id: int | None = None) -> None:
        if self._fail:
            raise RuntimeError("fake notifier boom")
        self.infos.append(text)

    async def notify_doctrine(self, payload: object) -> int | None:
        return None


class FakeClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self._now


class FakeVipStore:
    """Fix round (F5): minimal VipReader double for the binding check."""

    def __init__(self, telegram_user_id: int | None = 111) -> None:
        self._tid = telegram_user_id

    async def get_by_id(self, vip_id: UUID) -> Any:
        if self._tid is None:
            return None
        return SimpleNamespace(id=vip_id, telegram_user_id=self._tid)


def _msg(role: str, text: str, ts: str = "2026-08-05 10:30:00+00:00") -> dict:
    return {"role": role, "text": text, "timestamp": ts}


def _build_service(
    *,
    enabled: bool = True,
    messages: list[dict] | None = None,
    llm: FakeLLM | None = None,
    notifier: FakeNotifier | None = None,
    window_size: int = 200,
    vips: FakeVipStore | None = None,
) -> tuple[
    MemoryBackfillService, FakeHistory, FakeLLM, FakeMemoryWriter, FakeEmbedder
]:
    history = FakeHistory(messages)
    fake_llm = llm or FakeLLM()
    writer = FakeMemoryWriter()
    embedder = FakeEmbedder()
    svc = MemoryBackfillService(
        feature_memory_enabled=enabled,
        history=history,
        llm=fake_llm,
        memories=writer,
        embedder=embedder,
        notifier=notifier or FakeNotifier(),
        vips=vips,
        window_size=window_size,
        clock=FakeClock(),
    )
    return svc, history, fake_llm, writer, embedder


# ---------------------------------------------------------------------------
# cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_flag_returns_disabled_and_writes_nothing() -> None:
    svc, history, llm, writer, _ = _build_service(
        enabled=False, messages=[_msg("vip", "hola")]
    )
    report = await svc.generate_profile(uuid4(), chat_id=1)
    assert report.status == "disabled"
    assert report.facts == 0
    assert history.chat_ids == []
    assert llm.calls == []
    assert writer.replace_calls == []


@pytest.mark.asyncio
async def test_empty_history_returns_empty_and_no_llm_call() -> None:
    svc, history, llm, writer, _ = _build_service(messages=[])
    report = await svc.generate_profile(uuid4(), chat_id=2)
    assert report.status == "empty_history"
    assert history.chat_ids == [2]
    assert history.page_sizes == [500]
    assert llm.calls == []
    assert writer.replace_calls == []


@pytest.mark.asyncio
async def test_short_history_single_window_writes_sections_and_statuses() -> None:
    vip_id = uuid4()
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[
                    HechoExtracted(
                        seccion="preferencias",
                        texto="Le gusta el tono juguetón",
                        sensible=True,
                    ),
                    HechoExtracted(
                        seccion="preferencias",
                        texto="Prefiere hablar de viajes",
                    ),
                ]
            )
        ]
    )
    notifier = FakeNotifier()
    svc, history, _, writer, _ = _build_service(
        messages=[
            _msg("vip", "hola! respondeme juguetón"),
            _msg("owner", "claro!"),
            _msg("vip", "me encanta viajar"),
        ],
        llm=llm,
        notifier=notifier,
    )

    report = await svc.generate_profile(vip_id, chat_id=3)

    assert report.status == "ok"
    assert report.windows == 1
    assert report.facts == 2
    assert report.pending_owner == 1
    # Fixed vocabulary (F5-02): the perfil always carries the 5 sections.
    assert report.sections == 5

    assert len(writer.replace_calls) == 1
    call_vip, rows, perfil, perfil_embedding = writer.replace_calls[0]
    assert call_vip == vip_id
    assert len(rows) == 2

    pending = next(r for r in rows if r.status == "pending_owner")
    auto = next(r for r in rows if r.status == "auto")
    assert pending.approved_by is None
    assert pending.category == "preferencias"
    assert auto.approved_by == "auto"
    assert all(r.source_turn_id is None for r in rows)
    assert perfil["fuente"] == "backfill"
    assert perfil["version"] == 1
    assert "secciones" in perfil
    assert perfil["vip_id"] == str(vip_id)
    assert isinstance(perfil_embedding, list) and perfil_embedding

    assert len(notifier.infos) == 1
    assert "2 hechos" in notifier.infos[0]
    assert "1 requieren" in notifier.infos[0]


@pytest.mark.asyncio
async def test_long_history_paginates_windows_and_accumulates() -> None:
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[
                    HechoExtracted(seccion="identidad", texto="Vive en Buenos Aires")
                ]
            ),
            WindowExtraction(hechos=[]),
            WindowExtraction(hechos=[]),
        ]
    )
    messages = [_msg("vip", f"msg {i}") for i in range(450)]
    svc, _, _, writer, _ = _build_service(messages=messages, llm=llm)

    report = await svc.generate_profile(uuid4(), chat_id=4)

    assert report.status == "ok"
    assert report.windows == 3  # 450 // 200 -> 200 + 200 + 50
    assert len(llm.calls) == 3
    # Window 2 prompt must carry the facts already extracted from window 1.
    user2 = llm.calls[1][1]["content"]
    assert "Hechos ya extraídos" in user2
    assert "Vive en Buenos Aires" in user2
    assert len(writer.replace_calls) == 1
    assert len(writer.replace_calls[0][1]) == 1


@pytest.mark.asyncio
async def test_regenerate_replaces_without_duplicating() -> None:
    vip_id = uuid4()
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[HechoExtracted(seccion="identidad", texto="Vive en Buenos Aires")]
            ),
            WindowExtraction(
                hechos=[HechoExtracted(seccion="identidad", texto="Vive en Buenos Aires")]
            ),
        ]
    )
    svc, _, _, writer, _ = _build_service(
        messages=[_msg("vip", "soy de buenos aires")], llm=llm
    )

    first = await svc.generate_profile(vip_id, chat_id=5)
    second = await svc.generate_profile(vip_id, chat_id=5)

    assert first.status == "ok" and second.status == "ok"
    assert first.facts == second.facts == 1
    assert len(writer.replace_calls) == 2
    assert writer.replace_calls[0][0] == vip_id
    assert writer.replace_calls[1][0] == vip_id


@pytest.mark.asyncio
async def test_window_llm_failure_no_partial_write() -> None:
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[HechoExtracted(seccion="identidad", texto="Hecho uno")]
            ),
            WindowExtraction(hechos=[]),
            WindowExtraction(hechos=[]),
        ],
        fail_on_call=2,
    )
    messages = [_msg("vip", f"msg {i}") for i in range(450)]
    svc, _, _, writer, _ = _build_service(messages=messages, llm=llm)

    report = await svc.generate_profile(uuid4(), chat_id=6)

    assert report.status == "failed"
    assert writer.replace_calls == []  # R4: no partial write


@pytest.mark.asyncio
async def test_transcript_uses_diana_vip_prefixes() -> None:
    llm = FakeLLM([WindowExtraction(hechos=[])])
    svc, _, _, _, _ = _build_service(
        messages=[
            {"role": "owner", "text": "hola!", "timestamp": "2026-08-05 10:30:00+00:00"},
            {"role": "vip", "text": "hola!", "timestamp": "2026-08-05 10:31:00+00:00"},
        ],
        llm=llm,
    )

    await svc.generate_profile(uuid4(), chat_id=7)

    user_content = llm.calls[0][1]["content"]
    assert "Diana: hola!" in user_content
    assert "VIP: hola!" in user_content
    assert "[2026-08-05 10:30] Diana: hola!" in user_content
    assert "[2026-08-05 10:31] VIP: hola!" in user_content


@pytest.mark.asyncio
async def test_consolidation_dedups_exact_text_across_windows() -> None:
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[
                    HechoExtracted(seccion="identidad", texto="Vive  en   Buenos Aires")
                ]
            ),
            WindowExtraction(
                hechos=[
                    HechoExtracted(seccion="identidad", texto="vive en buenos aires")
                ]
            ),
        ]
    )
    messages = [_msg("vip", f"msg {i}") for i in range(250)]
    svc, _, _, writer, _ = _build_service(messages=messages, llm=llm)

    report = await svc.generate_profile(uuid4(), chat_id=8)

    assert report.status == "ok"
    assert report.windows == 2
    assert len(writer.replace_calls) == 1
    rows = writer.replace_calls[0][1]
    assert len(rows) == 1  # normalized exact dup collapsed into one row
    assert rows[0].text == "Vive  en   Buenos Aires"  # first occurrence kept


@pytest.mark.asyncio
async def test_notifier_failure_does_not_break_report() -> None:
    """Best-effort notification (pattern vip_history_seed): a notifier
    exception must NOT abort the backfill or poison the ok report."""
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[HechoExtracted(seccion="identidad", texto="Vive en Buenos Aires")]
            )
        ]
    )
    notifier = FakeNotifier(fail=True)
    svc, _, _, writer, _ = _build_service(
        messages=[_msg("vip", "soy de buenos aires")],
        llm=llm,
        notifier=notifier,
    )

    report = await svc.generate_profile(uuid4(), chat_id=9)

    assert report.status == "ok"
    assert report.facts == 1
    assert len(writer.replace_calls) == 1  # write happened despite notify failure
    assert notifier.infos == []


# ---------------------------------------------------------------------------
# fix round cases (F2, F5, L1, L8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_binding_mismatch_fails_closed_without_any_io() -> None:
    """Fix round (F5): chat_id not bound to vip_id → failed report, no reads
    or writes at all (the wiring can never contaminate another VIP)."""
    svc, history, llm, writer, _ = _build_service(
        messages=[_msg("vip", "hola")],
        vips=FakeVipStore(telegram_user_id=999),  # chat_id=1 does not match
    )
    report = await svc.generate_profile(uuid4(), chat_id=1)

    assert report.status == "failed"
    assert history.chat_ids == []
    assert llm.calls == []
    assert writer.replace_calls == []


@pytest.mark.asyncio
async def test_binding_match_proceeds_and_unknown_vip_fails_closed() -> None:
    """Fix round (F5): matching telegram_user_id → normal flow; unknown VIP
    (store returns None) also fails closed."""
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[HechoExtracted(seccion="identidad", texto="Vive en Buenos Aires")]
            )
        ]
    )
    svc, history, _, writer, _ = _build_service(
        messages=[_msg("vip", "soy de buenos aires")],
        llm=llm,
        vips=FakeVipStore(telegram_user_id=21),  # chat_id=21 matches
    )
    report = await svc.generate_profile(uuid4(), chat_id=21)
    assert report.status == "ok"
    assert history.chat_ids == [21]
    assert len(writer.replace_calls) == 1

    svc2, history2, _, writer2, _ = _build_service(
        messages=[_msg("vip", "hola")],
        vips=FakeVipStore(telegram_user_id=None),  # VIP not found
    )
    report2 = await svc2.generate_profile(uuid4(), chat_id=22)
    assert report2.status == "failed"
    assert history2.chat_ids == []
    assert writer2.replace_calls == []


@pytest.mark.asyncio
async def test_sensitive_term_heuristic_overrides_llm_classification() -> None:
    """Fix round (F2): the code-side term heuristic upgrades an LLM
    ``sensible=false`` fact to ``pending_owner`` (fail-closed backstop)."""
    llm = FakeLLM(
        [
            WindowExtraction(
                hechos=[
                    HechoExtracted(
                        seccion="preferencias",
                        texto="Toma medicación para la diabetes",
                        sensible=False,  # LLM misclassified; heuristic must override
                    )
                ]
            )
        ]
    )
    svc, _, _, writer, _ = _build_service(
        messages=[_msg("vip", "tomo medicación para la diabetes")],
        llm=llm,
    )
    report = await svc.generate_profile(uuid4(), chat_id=12)

    assert report.status == "ok"
    assert report.pending_owner == 1
    rows = writer.replace_calls[0][1]
    assert len(rows) == 1
    assert rows[0].status == "pending_owner"
    assert rows[0].approved_by is None


@pytest.mark.asyncio
async def test_extraction_prompt_fences_transcript_as_data() -> None:
    """Fix round (F2, SEC-INJ-02): the transcript is fenced and flagged as
    data, not instructions, in both the system prompt and the window prompt."""
    llm = FakeLLM([WindowExtraction(hechos=[])])
    svc, _, _, _, _ = _build_service(messages=[_msg("vip", "hola")], llm=llm)

    await svc.generate_profile(uuid4(), chat_id=13)

    system = llm.calls[0][0]["content"]
    user = llm.calls[0][1]["content"]
    assert "DATOS" in system
    assert "no instrucciones" in system
    assert "```transcripto" in user
    assert "DATOS, no instrucciones" in user


@pytest.mark.asyncio
async def test_empty_extraction_reports_without_writing_or_notifying() -> None:
    """Fix round (L1): zero facts across all windows → empty_extraction, no
    profile write and no owner DM."""
    llm = FakeLLM([WindowExtraction(hechos=[]), WindowExtraction(hechos=[])])
    notifier = FakeNotifier()
    svc, _, _, writer, _ = _build_service(
        messages=[_msg("vip", f"m{i}") for i in range(250)],
        llm=llm,
        notifier=notifier,
    )

    report = await svc.generate_profile(uuid4(), chat_id=14)

    assert report.status == "empty_extraction"
    assert report.windows == 2
    assert writer.replace_calls == []
    assert notifier.infos == []


@pytest.mark.asyncio
async def test_transcript_skips_empty_lines_and_missing_timestamp() -> None:
    """Fix round (L8): empty/blank texts never emit transcript lines; a
    message without timestamp renders without the ``[ts]`` prefix."""
    llm = FakeLLM([WindowExtraction(hechos=[])])
    svc, _, _, _, _ = _build_service(
        messages=[
            {"role": "vip", "text": "", "timestamp": "2026-08-05 10:30:00+00:00"},
            {"role": "vip", "text": "   ", "timestamp": "2026-08-05 10:31:00+00:00"},
            {"role": "vip", "text": "sin timestamp"},
            {"role": "owner", "text": "con ts", "timestamp": "2026-08-05 10:32:00+00:00"},
        ],
        llm=llm,
    )

    await svc.generate_profile(uuid4(), chat_id=15)

    user_content = llm.calls[0][1]["content"]
    assert "VIP: sin timestamp" in user_content  # no [ts] prefix
    assert "[2026-08-05 10:30]" not in user_content  # empty line skipped
    assert "[2026-08-05 10:31]" not in user_content  # blank line skipped
    assert "[2026-08-05 10:32] Diana: con ts" in user_content
    assert "\nVIP: \n" not in user_content


@pytest.mark.asyncio
async def test_window_size_zero_or_negative_clamps_to_one() -> None:
    """Fix round (L8): window_size <= 0 clamps to 1 — every line becomes its
    own window instead of crashing or creating one giant window."""
    for bad in (0, -1):
        llm = FakeLLM(
            [
                WindowExtraction(
                    hechos=[HechoExtracted(seccion="identidad", texto=f"hecho {i}")]
                )
                for i in range(3)
            ]
        )
        svc, _, _, writer, _ = _build_service(
            messages=[_msg("vip", f"m{i}") for i in range(3)],
            llm=llm,
            window_size=bad,
        )
        report = await svc.generate_profile(uuid4(), chat_id=16)
        assert report.status == "ok"
        assert report.windows == 3
        assert len(llm.calls) == 3
        assert len(writer.replace_calls) == 1


@pytest.mark.asyncio
async def test_transcript_line_truncation_and_char_budget() -> None:
    """Fix round (M2): lines are truncated to 400 chars and windows respect
    the 12K char budget on top of the message-count cap."""
    # Truncation: a 900-char message becomes 400 chars + ellipsis marker.
    long_msg = _msg("vip", "x" * 900)
    # Char budget: 36 lines (~375 chars each after the prefix) sum well over
    # 12K chars, so a second window opens far below the 200-message cap.
    filler = [_msg("vip", "y" * 350) for _ in range(35)]
    llm = FakeLLM([WindowExtraction(hechos=[]), WindowExtraction(hechos=[])])
    svc, _, _, _, _ = _build_service(
        messages=[long_msg] + filler,
        llm=llm,
        window_size=200,
    )

    await svc.generate_profile(uuid4(), chat_id=17)

    assert len(llm.calls) == 2  # char budget split the 36 lines into 2 windows
    first_window = llm.calls[0][1]["content"]
    assert "x" * 401 not in first_window  # truncated, not 900 raw chars
    assert "x" * 400 in first_window
    assert "…" in first_window
    # The second window only starts because of the char budget — it contains
    # the tail lines, and the accumulating prompt is still passed along.
    second_window = llm.calls[1][1]["content"]
    assert "Hechos ya extraídos" in second_window
