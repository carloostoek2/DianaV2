"""Unit tests for trace keyboard factories and callback encoding."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from diana.telegram.keyboards import (
    TraceCallbackData,
    draft_keyboard,
    encode_callback,
    encode_trace_detail,
    encode_trace_json,
    encode_trace_page,
    encode_trace_view,
    parse_trace_callback,
    step_detail_keyboard,
    trace_detail_keyboard,
    trace_list_keyboard,
)


@pytest.fixture
def turn_id() -> UUID:
    return uuid4()


class TestCallbackEncoding:
    def test_trace_view_callback_under_64_bytes(self, turn_id: UUID) -> None:
        data = encode_trace_view(turn_id)
        assert len(data.encode("utf-8")) <= 64

    def test_trace_detail_callback_under_64_bytes(self, turn_id: UUID) -> None:
        data = encode_trace_detail(turn_id, "analyst")
        assert len(data.encode("utf-8")) <= 64

    def test_trace_page_callback_under_64_bytes(self) -> None:
        data = encode_trace_page(0)
        assert len(data.encode("utf-8")) <= 64
        data = encode_trace_page(99)
        assert len(data.encode("utf-8")) <= 64

    def test_trace_json_callback_under_64_bytes(self, turn_id: UUID) -> None:
        data = encode_trace_json(turn_id)
        assert len(data.encode("utf-8")) <= 64


class TestParseTraceCallback:
    def test_parse_trace_view_callback(self, turn_id: UUID) -> None:
        data = encode_trace_view(turn_id)
        parsed = parse_trace_callback(data)
        assert parsed is not None
        assert isinstance(parsed, TraceCallbackData)
        assert parsed.action == "vt"
        assert parsed.turn_id == turn_id

    def test_parse_trace_detail_callback(self, turn_id: UUID) -> None:
        data = encode_trace_detail(turn_id, "analyst")
        parsed = parse_trace_callback(data)
        assert parsed is not None
        assert isinstance(parsed, TraceCallbackData)
        assert parsed.action == "td"
        assert parsed.turn_id == turn_id
        assert parsed.step == "analyst"

    def test_parse_trace_page_callback(self) -> None:
        data = encode_trace_page(2)
        parsed = parse_trace_callback(data)
        assert parsed is not None
        assert isinstance(parsed, TraceCallbackData)
        assert parsed.action == "tp"
        assert parsed.page == 2

    def test_parse_trace_json_callback(self, turn_id: UUID) -> None:
        data = encode_trace_json(turn_id)
        parsed = parse_trace_callback(data)
        assert parsed is not None
        assert isinstance(parsed, TraceCallbackData)
        assert parsed.action == "tj"
        assert parsed.turn_id == turn_id

    def test_parse_non_trace_callback_returns_none(self) -> None:
        parsed = parse_trace_callback("a:some-uuid")
        assert parsed is None
        parsed = parse_trace_callback("c:some-uuid")
        assert parsed is None

    def test_parse_empty_string_returns_none(self) -> None:
        assert parse_trace_callback("") is None
        assert parse_trace_callback("no-colon") is None


class TestTraceListKeyboard:
    def test_basic_structure(self) -> None:
        turn_id = uuid4()
        kb = trace_list_keyboard(
            [(turn_id, "abc123")],
            page=0,
            total_pages=1,
        )
        assert len(kb.inline_keyboard) == 1  # 1 turn row + no nav (1 page total)
        assert "abc123" in kb.inline_keyboard[0][0].text

    def test_pagination_previous_hidden_on_page_0(self) -> None:
        turn_id = uuid4()
        kb = trace_list_keyboard(
            [(turn_id, "abc123")],
            page=0,
            total_pages=3,
        )
        buttons = [b.text for row in kb.inline_keyboard for b in row]
        assert "Previous" not in buttons
        assert "Next" in buttons

    def test_pagination_next_hidden_on_last_page(self) -> None:
        turn_id = uuid4()
        kb = trace_list_keyboard(
            [(turn_id, "abc123")],
            page=2,
            total_pages=3,
        )
        buttons = [b.text for row in kb.inline_keyboard for b in row]
        assert "Previous" in buttons
        assert "Next" not in buttons


class TestTraceDetailKeyboard:
    def test_contains_all_steps(self, turn_id: UUID) -> None:
        kb = trace_detail_keyboard(turn_id, timings={"analyst_ms": 100.0})
        all_text = " ".join(b.text for row in kb.inline_keyboard for b in row)
        assert "Analyst" in all_text
        assert "Planner" in all_text
        assert "Generator" in all_text
        assert "Evaluator" in all_text
        assert "Decider" in all_text
        assert "Export JSON" in all_text
        assert "Back to turns" in all_text

    def test_shows_timings_when_present(self, turn_id: UUID) -> None:
        kb = trace_detail_keyboard(turn_id, timings={"analyst_ms": 100.0, "decider_ms": 0.5})
        texts = [b.text for row in kb.inline_keyboard for b in row]
        analyst_text = next(t for t in texts if "Analyst" in t)
        assert "100" in analyst_text


class TestStepDetailKeyboard:
    def test_has_back_button(self, turn_id: UUID) -> None:
        kb = step_detail_keyboard(turn_id)
        assert len(kb.inline_keyboard) == 1
        assert kb.inline_keyboard[0][0].text == "Back to trace"
        assert "vt" in kb.inline_keyboard[0][0].callback_data


class TestValueErrorOnLargeCallback:
    def test_encode_trace_detail_raises_on_long_step_name(self, turn_id: UUID) -> None:
        with pytest.raises(ValueError, match="callback_data exceeds"):
            encode_trace_detail(turn_id, "a" * 30)

    def test_encode_callback_fallback_raises_on_long_action(self) -> None:
        with pytest.raises(ValueError, match="callback_data exceeds"):
            encode_callback("a-very-long-action-name-that-overflows", uuid4())


class TestDraftKeyboard:
    def test_draft_keyboard_includes_trace_button(self) -> None:
        turn_id = uuid4()
        kb = draft_keyboard(turn_id)
        all_text = [b.text for row in kb.inline_keyboard for b in row]
        assert "Trace" in all_text
        assert len(kb.inline_keyboard) >= 2  # original row + trace row
