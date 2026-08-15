"""Link kick keyboard — 3 buttons + parse_link_callback round-trip."""

from __future__ import annotations

from diana.telegram.keyboards import link_kick_keyboard, parse_link_callback


def test_link_kick_keyboard_three_buttons() -> None:
    markup = link_kick_keyboard("evt-1")
    flat = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert len(flat) == 3
    assert flat == ["link:expel:evt-1", "link:disable:evt-1", "link:keep:evt-1"]


def test_link_kick_keyboard_callbacks_under_64_bytes() -> None:
    event_id = "12345678-1234-1234-1234-123456789abc"  # 36-char UUID string
    markup = link_kick_keyboard(event_id)
    flat = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert all(len(d.encode("utf-8")) <= 64 for d in flat)


def test_parse_link_callback_roundtrip() -> None:
    for action in ("expel", "disable", "keep"):
        assert parse_link_callback(f"link:{action}:evt-1") == (action, "evt-1")


def test_parse_link_callback_malformed_returns_none() -> None:
    for data in ("", "link:expel", "link:unknown:evt-1", "nope"):
        assert parse_link_callback(data) is None
