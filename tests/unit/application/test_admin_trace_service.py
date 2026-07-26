"""Unit tests for AdminTraceService (mocks TraceabilityReader protocol)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from diana.application.admin_trace_service import (
    AdminTraceService,
    FullTrace,
    StepDetailView,
    TraceSummaryView,
    TurnsPageView,
    TurnSummary,
    format_relative_time,
)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now


class FakeTraceabilityReader:
    """In-memory fake implementing TraceabilityReader protocol for tests."""

    def __init__(self) -> None:
        self._turns: list[dict] = []
        self._traces: dict[str, dict] = {}

    def seed_turns(self, rows: list[dict]) -> None:
        self._turns = list(rows)

    def seed_trace(self, turn_id: str, data: dict) -> None:
        self._traces[str(turn_id)] = dict(data)

    async def get_recent_turns(self, limit: int = 10, offset: int = 0, chat_id: int | None = None) -> list[dict]:
        if chat_id is not None:
            filtered = [r for r in self._turns if r.get("chat_id") == chat_id]
            return list(filtered[offset:offset + limit])
        return list(self._turns[offset:offset + limit])

    async def get_full_trace(self, turn_id) -> dict | None:
        return self._traces.get(str(turn_id))

    async def count_recent(self, chat_id: int | None = None) -> int:
        if chat_id is not None:
            return sum(1 for r in self._turns if r.get("chat_id") == chat_id)
        return len(self._turns)


FROZEN_NOW = datetime(2026, 7, 26, 15, 0, 0, tzinfo=UTC)


@pytest.fixture
def reader() -> FakeTraceabilityReader:
    return FakeTraceabilityReader()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(FROZEN_NOW)


@pytest.fixture
def svc(reader: FakeTraceabilityReader, clock: FakeClock) -> AdminTraceService:
    return AdminTraceService(traces=reader, trace_ttl_days=30, clock=clock)


class TestGetRecentTurns:
    async def test_get_recent_turns_returns_summaries(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        turn_id = uuid4()
        reader.seed_turns([
            {
                "turn_id": turn_id,
                "chat_id": 123,
                "display_name": "Ana",
                "message_text": "Hola, quiero saber el precio del paquete premium",
                "decision": "approve",
                "status": "delivered",
                "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
                "correction_applied": False,
            }
        ])
        results = await svc.get_recent_turns(limit=10, offset=0)
        assert len(results) == 1
        t = results[0]
        assert isinstance(t, TurnSummary)
        assert t.turn_id == turn_id
        assert t.chat_id == 123
        assert t.vip_name == "Ana"
        assert t.message_preview == "Hola, quiero saber el precio del paquete premium"
        assert t.decision == "approve"
        assert t.status == "delivered"
        assert t.created_at is not None
        assert t.correction_applied is False

    async def test_get_recent_turns_empty(
        self, svc: AdminTraceService, _unused_reader: object = None
    ) -> None:
        results = await svc.get_recent_turns(limit=10, offset=0)
        assert results == []

    async def test_message_preview_truncated(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        long_text = "X" * 100
        reader.seed_turns([
            {
                "turn_id": uuid4(),
                "chat_id": 1,
                "display_name": "Test",
                "message_text": long_text,
                "decision": "approve",
                "status": "delivered",
                "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
                "correction_applied": False,
            }
        ])
        results = await svc.get_recent_turns()
        assert len(results) == 1
        assert results[0].message_preview == "X" * 50 + "..."
        assert len(results[0].message_preview) == 53

    async def test_get_recent_turns_filters_by_chat_id(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        """Verify chat_id filter returns only matching turns."""
        reader.seed_turns([
            {
                "turn_id": uuid4(), "chat_id": 1, "display_name": "A",
                "message_text": "hi", "decision": "a", "status": "d",
                "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
                "correction_applied": False,
            },
            {
                "turn_id": uuid4(), "chat_id": 2, "display_name": "B",
                "message_text": "hey", "decision": "a", "status": "d",
                "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
                "correction_applied": False,
            },
        ])
        results = await svc.get_recent_turns(limit=10, offset=0, chat_id=1)
        assert len(results) == 1
        assert results[0].chat_id == 1

    async def test_get_recent_turns_filter_by_chat_id_returns_empty_when_no_match(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        """Verify chat_id filter returns empty list when no turns match."""
        reader.seed_turns([
            {
                "turn_id": uuid4(), "chat_id": 1, "display_name": "A",
                "message_text": "hi", "decision": "a", "status": "d",
                "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
                "correction_applied": False,
            },
        ])
        results = await svc.get_recent_turns(limit=10, offset=0, chat_id=99)
        assert results == []


class TestGetFullTrace:
    async def test_get_full_trace_found(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        turn_id = uuid4()
        reader.seed_trace(str(turn_id), {
            "turn_id": turn_id,
            "chat_id": 123,
            "vip_id": uuid4(),
            "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
            "comprehension": {"intent": "chat"},
            "plan": {"capabilities": []},
            "retrieved": {},
            "prompt_text": "Hello",
            "generated_text": "Hi there",
            "evaluation": {"naturalness": 0.9},
            "decision": {"action": "approve"},
            "delivery_result": {"success": True},
            "timings": {"analyst_ms": 100.0},
            "status": "delivered",
            "error": None,
        })
        trace = await svc.get_full_trace(turn_id)
        assert trace is not None
        assert isinstance(trace, FullTrace)
        assert trace.turn_id == turn_id
        assert trace.comprehension == {"intent": "chat"}
        assert trace.generated_text == "Hi there"
        assert trace.timings == {"analyst_ms": 100.0}
        assert trace.status == "delivered"

    async def test_get_full_trace_not_found(
        self, svc: AdminTraceService, _unused_reader: object = None
    ) -> None:
        trace = await svc.get_full_trace(uuid4())
        assert trace is None


class TestCountRecent:
    async def test_count_recent(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        reader.seed_turns([
            {
                "turn_id": uuid4(), "chat_id": 1, "display_name": "A",
                "message_text": "hi", "decision": "a", "status": "d",
                "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
                "correction_applied": False,
            },
            {
                "turn_id": uuid4(), "chat_id": 2, "display_name": "B",
                "message_text": "hey", "decision": "a", "status": "d",
                "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
                "correction_applied": False,
            },
        ])
        count = await svc.count_recent()
        assert count == 2

    async def test_count_recent_zero(
        self, svc: AdminTraceService, _unused_reader: object = None
    ) -> None:
        count = await svc.count_recent()
        assert count == 0

    async def test_count_recent_filters_by_chat_id(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        """Verify count_recent with chat_id returns only matching rows."""
        reader.seed_turns([
            {
                "turn_id": uuid4(), "chat_id": 1, "display_name": "A",
                "message_text": "hi", "decision": "a", "status": "d",
                "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
                "correction_applied": False,
            },
            {
                "turn_id": uuid4(), "chat_id": 1, "display_name": "B",
                "message_text": "hey", "decision": "a", "status": "d",
                "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
                "correction_applied": False,
            },
            {
                "turn_id": uuid4(), "chat_id": 2, "display_name": "C",
                "message_text": "hello", "decision": "a", "status": "d",
                "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
                "correction_applied": False,
            },
        ])
        count = await svc.count_recent(chat_id=1)
        assert count == 2
        count = await svc.count_recent(chat_id=2)
        assert count == 1
        count = await svc.count_recent(chat_id=99)
        assert count == 0


class TestExportTraceJson:
    async def test_export_trace_json_found(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        turn_id = uuid4()
        reader.seed_trace(str(turn_id), {
            "turn_id": turn_id,
            "chat_id": 123,
            "vip_id": uuid4(),
            "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
            "comprehension": {"intent": "chat"},
            "plan": {"capabilities": []},
            "retrieved": {},
            "prompt_text": "Hello",
            "generated_text": "Hi there",
            "evaluation": {"naturalness": 0.9},
            "decision": {"action": "approve"},
            "delivery_result": None,
            "timings": {"analyst_ms": 100.0},
            "status": "delivered",
            "error": None,
        })
        json_str = await svc.export_trace_json(turn_id)
        import json
        data = json.loads(json_str)
        assert data["turn_id"] == str(turn_id)
        assert data["comprehension"]["intent"] == "chat"
        assert data["timings"]["analyst_ms"] == 100.0

    async def test_export_trace_json_not_found(
        self, svc: AdminTraceService, _unused_reader: object = None
    ) -> None:
        json_str = await svc.export_trace_json(uuid4())
        import json
        data = json.loads(json_str)
        assert "error" in data


class TestFormatRelativeTime:
    def test_five_minutes_ago_with_injected_now(self) -> None:
        now = datetime(2026, 7, 26, 15, 0, 0, tzinfo=UTC)
        dt = now - timedelta(minutes=5)
        assert format_relative_time(dt, now=now) == "hace 5 minutos"

    def test_none_returns_empty(self) -> None:
        assert format_relative_time(None) == ""


class TestTurnsKeyboardRows:
    def test_short_ids_are_first_8_chars(self, svc: AdminTraceService) -> None:
        turn_id = UUID("abcdef12-3456-7890-abcd-ef1234567890")
        turns = [
            TurnSummary(
                turn_id=turn_id,
                chat_id=1,
                vip_name="Ana",
                message_preview="hi",
                decision="approve",
                status="delivered",
                created_at=FROZEN_NOW - timedelta(minutes=5),
            )
        ]
        rows = svc.turns_keyboard_rows(turns)
        assert rows == [(turn_id, "abcdef12")]
        assert len(rows[0][1]) == 8


class TestTruncatePreview:
    async def test_list_preview_collapses_newlines(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        turn_id = uuid4()
        reader.seed_turns(
            [
                {
                    "turn_id": turn_id,
                    "chat_id": 1,
                    "display_name": "Ana",
                    "message_text": "hola\nmundo\tprecio",
                    "decision": "approve",
                    "status": "delivered",
                    "created_at": FROZEN_NOW - timedelta(minutes=5),
                    "correction_applied": False,
                }
            ]
        )
        results = await svc.get_recent_turns()
        assert results[0].message_preview == "hola mundo precio"
        assert "\n" not in results[0].message_preview
        text = svc.format_turns_list_text(results, page=0, total_pages=1)
        assert "hola mundo precio" in text
        assert "hola\nmundo" not in text


class TestFormatTurnsListText:
    def test_list_template_and_header(
        self, svc: AdminTraceService
    ) -> None:
        turn_id = UUID("abcdef12-3456-7890-abcd-ef1234567890")
        created = FROZEN_NOW - timedelta(minutes=5)
        turns = [
            TurnSummary(
                turn_id=turn_id,
                chat_id=123,
                vip_name="Ana",
                message_preview="hola precio",
                decision="approve",
                status="delivered",
                created_at=created,
            )
        ]
        text = svc.format_turns_list_text(turns, page=0, total_pages=2)
        assert text.startswith("Recent turns (page 1/2):")
        assert (
            '1. [abcdef12] Ana (chat 123): "hola precio" -> approve (hace 5 minutos)'
            in text
        )

    def test_unknown_vip_name(self, svc: AdminTraceService) -> None:
        turns = [
            TurnSummary(
                turn_id=UUID("11111111-2222-3333-4444-555555555555"),
                chat_id=9,
                vip_name=None,
                message_preview="x",
                decision="escalate",
                created_at=FROZEN_NOW - timedelta(minutes=1),
            )
        ]
        text = svc.format_turns_list_text(turns, page=0, total_pages=1)
        assert "Unknown" in text


class TestRenderTurnsPage:
    async def test_render_page_with_rows(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        turn_id = UUID("abcdef12-3456-7890-abcd-ef1234567890")
        reader.seed_turns(
            [
                {
                    "turn_id": turn_id,
                    "chat_id": 123,
                    "display_name": "Ana",
                    "message_text": "hola precio",
                    "decision": "approve",
                    "status": "delivered",
                    "created_at": FROZEN_NOW - timedelta(minutes=5),
                    "correction_applied": False,
                }
            ]
        )
        view = await svc.render_turns_page(0, limit=10)
        assert isinstance(view, TurnsPageView)
        assert view.empty is False
        assert view.page == 0
        assert view.total_pages == 1
        assert view.turns_data == [(turn_id, "abcdef12")]
        assert view.text.startswith("Recent turns (page 1/1):")
        assert "Ana" in view.text

    async def test_render_empty_page(
        self, svc: AdminTraceService
    ) -> None:
        view = await svc.render_turns_page(0)
        assert view.empty is True
        assert view.text == ""
        assert view.turns_data == []
        assert view.total_pages == 1

    async def test_render_respects_chat_id_filter(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        reader.seed_turns(
            [
                {
                    "turn_id": uuid4(),
                    "chat_id": 1,
                    "display_name": "A",
                    "message_text": "hi",
                    "decision": "approve",
                    "status": "d",
                    "created_at": FROZEN_NOW - timedelta(minutes=2),
                    "correction_applied": False,
                },
                {
                    "turn_id": uuid4(),
                    "chat_id": 2,
                    "display_name": "B",
                    "message_text": "hey",
                    "decision": "approve",
                    "status": "d",
                    "created_at": FROZEN_NOW - timedelta(minutes=1),
                    "correction_applied": False,
                },
            ]
        )
        view = await svc.render_turns_page(0, chat_id=1)
        assert view.empty is False
        assert "(chat 1)" in view.text
        assert "(chat 2)" not in view.text


class TestFormatTraceSummaryText:
    def test_canonical_template_has_status_and_original_intent(
        self, svc: AdminTraceService
    ) -> None:
        turn_id = UUID("abcdef12-3456-7890-abcd-ef1234567890")
        trace = FullTrace(
            turn_id=turn_id,
            chat_id=123,
            created_at=FROZEN_NOW - timedelta(minutes=5),
            prompt_text="Hello world intent",
            generated_text="Hi draft reply",
            decision={"action": "approve"},
            timings={"analyst_ms": 100.0, "generator_ms": 50.5},
            status="delivered",
        )
        text = svc.format_trace_summary_text(trace)
        lines = text.splitlines()
        assert lines[0] == "Trace abcdef12"
        assert lines[1] == "Date: hace 5 minutos"
        assert lines[2] == "Status: delivered"
        assert lines[3] == "Original intent: Hello world intent"
        assert lines[4] == 'Draft: "Hi draft reply..."'
        assert lines[5] == "Decision: approve"
        assert lines[6] == "Total time: 150ms"
        assert "Original:" not in text or "Original intent:" in text
        # Bare Original: label must not appear (canonical uses Original intent:)
        assert not any(line.startswith('Original: "') for line in lines)

    def test_missing_fields_use_na(self, svc: AdminTraceService) -> None:
        turn_id = uuid4()
        text = svc.format_trace_summary_text(
            FullTrace(turn_id=turn_id, chat_id=1, created_at=None)
        )
        assert "Status: N/A" in text
        assert "Decision: N/A" in text
        assert "Total time: 0ms" in text

    def test_prefers_director_total_ms_not_double_sum(
        self, svc: AdminTraceService
    ) -> None:
        """Production timings include step *_ms AND total_ms — use total_ms."""
        turn_id = UUID("abcdef12-3456-7890-abcd-ef1234567890")
        text = svc.format_trace_summary_text(
            FullTrace(
                turn_id=turn_id,
                chat_id=1,
                created_at=FROZEN_NOW - timedelta(minutes=1),
                prompt_text="x",
                generated_text="y",
                decision={"action": "approve"},
                timings={
                    "analyst_ms": 100.0,
                    "generator_ms": 50.0,
                    "total_ms": 150.0,
                },
                status="delivered",
            )
        )
        assert "Total time: 150ms" in text
        assert "Total time: 300ms" not in text

    def test_total_ms_fallback_sums_steps_without_total_key(
        self, svc: AdminTraceService
    ) -> None:
        turn_id = uuid4()
        text = svc.format_trace_summary_text(
            FullTrace(
                turn_id=turn_id,
                chat_id=1,
                created_at=FROZEN_NOW,
                timings={"analyst_ms": 100.0, "generator_ms": 50.5},
            )
        )
        assert "Total time: 150ms" in text

    def test_summary_collapses_newlines_in_slices(
        self, svc: AdminTraceService
    ) -> None:
        text = svc.format_trace_summary_text(
            FullTrace(
                turn_id=uuid4(),
                chat_id=1,
                created_at=FROZEN_NOW,
                prompt_text="line1\nline2\tline3",
                generated_text="draft\nwith\nbreaks",
                decision={"action": "approve"},
                status="delivered",
            )
        )
        assert "Original intent: line1 line2 line3" in text
        assert "\nline2" not in text.split("Original intent:", 1)[1].split("\n")[0]
        assert "draft with breaks" in text

    def test_original_intent_truncated_at_200(self, svc: AdminTraceService) -> None:
        """PLAN A8/M3: original intent cap is 200 chars (no ellipsis on intent)."""
        long_intent = "I" * 250
        text = svc.format_trace_summary_text(
            FullTrace(
                turn_id=uuid4(),
                chat_id=1,
                created_at=FROZEN_NOW,
                prompt_text=long_intent,
                generated_text="short",
                decision={"action": "approve"},
                status="delivered",
            )
        )
        intent_line = next(
            line for line in text.splitlines() if line.startswith("Original intent:")
        )
        value = intent_line.removeprefix("Original intent: ")
        assert len(value) == 200
        assert value == "I" * 200
        assert "I" * 201 not in text

    def test_draft_truncated_at_80(self, svc: AdminTraceService) -> None:
        """PLAN A8/M3: draft cap is 80 chars + quoted trailing ..."""
        long_draft = "D" * 120
        text = svc.format_trace_summary_text(
            FullTrace(
                turn_id=uuid4(),
                chat_id=1,
                created_at=FROZEN_NOW,
                prompt_text="intent",
                generated_text=long_draft,
                decision={"action": "approve"},
                status="delivered",
            )
        )
        draft_line = next(line for line in text.splitlines() if line.startswith("Draft:"))
        assert draft_line == f'Draft: "{"D" * 80}..."'
        assert "D" * 81 not in draft_line


class TestRenderTraceSummary:
    async def test_render_found(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        turn_id = UUID("abcdef12-3456-7890-abcd-ef1234567890")
        reader.seed_trace(
            str(turn_id),
            {
                "turn_id": turn_id,
                "chat_id": 123,
                "vip_id": None,
                "created_at": FROZEN_NOW - timedelta(minutes=5),
                "comprehension": None,
                "plan": None,
                "retrieved": None,
                "prompt_text": "intent",
                "generated_text": "draft",
                "evaluation": None,
                "decision": {"action": "approve"},
                "delivery_result": None,
                "timings": {"analyst_ms": 10},
                "status": "delivered",
                "error": None,
            },
        )
        view = await svc.render_trace_summary(turn_id)
        assert isinstance(view, TraceSummaryView)
        assert view.turn_id == turn_id
        assert view.timings == {"analyst_ms": 10}
        assert "Status: delivered" in view.text
        assert "Original intent: intent" in view.text

    async def test_render_not_found(self, svc: AdminTraceService) -> None:
        assert await svc.render_trace_summary(uuid4()) is None


class TestFormatStepDetailText:
    def test_known_step_input_output_json(self, svc: AdminTraceService) -> None:
        turn_id = uuid4()
        trace = FullTrace(
            turn_id=turn_id,
            chat_id=1,
            comprehension={"intent": "chat"},
            timings={"analyst_ms": 42},
        )
        text = svc.format_step_detail_text(trace, "analyst")
        assert text.startswith("Step: Analyst")
        assert "Duration: 42ms" in text
        assert "Input:" in text
        assert "Output:" in text
        assert '"intent": "chat"' in text

    def test_oversized_payload_truncated(self, svc: AdminTraceService) -> None:
        huge = {"blob": "X" * 3000}
        trace = FullTrace(
            turn_id=uuid4(),
            chat_id=1,
            comprehension=huge,
            timings={"analyst_ms": 1},
        )
        text = svc.format_step_detail_text(trace, "analyst")
        assert text.endswith("... (truncated)") or "\n... (truncated)" in text
        # Content before suffix must respect 1800 cap for each JSON block
        suffix = "\n... (truncated)"
        assert suffix in text
        # At least one truncated block
        parts = text.split("Input:\n", 1)[1]
        inp_block = parts.split("\n\nOutput:\n", 1)[0]
        if suffix in inp_block:
            body = inp_block[: -len(suffix)]
            assert len(body) <= 1800

    def test_missing_timing_shows_na(self, svc: AdminTraceService) -> None:
        text = svc.format_step_detail_text(
            FullTrace(turn_id=uuid4(), chat_id=1, timings=None),
            "generator",
        )
        assert "Duration: N/A" in text


class TestRenderStepDetail:
    async def test_render_found(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        turn_id = uuid4()
        reader.seed_trace(
            str(turn_id),
            {
                "turn_id": turn_id,
                "chat_id": 1,
                "vip_id": None,
                "created_at": FROZEN_NOW,
                "comprehension": {"intent": "chat"},
                "plan": None,
                "retrieved": None,
                "prompt_text": None,
                "generated_text": None,
                "evaluation": None,
                "decision": None,
                "delivery_result": None,
                "timings": {"analyst_ms": 5},
                "status": "delivered",
                "error": None,
            },
        )
        view = await svc.render_step_detail(turn_id, "analyst")
        assert isinstance(view, StepDetailView)
        assert view.turn_id == turn_id
        assert "Step: Analyst" in view.text

    async def test_render_not_found(self, svc: AdminTraceService) -> None:
        assert await svc.render_step_detail(uuid4(), "analyst") is None
