"""Compact owner draft keyboards (callback_data ≤ 64 bytes)."""

from __future__ import annotations

from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# action:{uuid} — approve / correct / escalate / doctrine_respond
_ACTION_APPROVE = "a"
_ACTION_CORRECT = "c"
_ACTION_ESCALATE = "e"
_ACTION_DOCTRINE_RESPOND = "dr"


def encode_callback(action: str, turn_id: UUID) -> str:
    """Build callback_data: a|c|e : <uuid>."""
    code = {
        "approve": _ACTION_APPROVE,
        "correct": _ACTION_CORRECT,
        "escalate": _ACTION_ESCALATE,
    }.get(action, action)
    data = f"{code}:{turn_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def parse_callback(data: str) -> tuple[str, UUID] | None:
    """Parse callback_data into (action_name, turn_id) or None."""
    if not data or ":" not in data:
        return None
    code, raw_id = data.split(":", 1)

    # Try doctrine callback first (code "dr" — longer prefix wins).
    if code == _ACTION_DOCTRINE_RESPOND:
        try:
            return "respond_doctrine", UUID(raw_id)
        except ValueError:
            return None

    action = {
        _ACTION_APPROVE: "approve",
        _ACTION_CORRECT: "correct",
        _ACTION_ESCALATE: "escalate",
    }.get(code)
    if action is None:
        return None
    try:
        return action, UUID(raw_id)
    except ValueError:
        return None


def encode_doctrine_callback(turn_id: UUID) -> str:
    """Build callback_data for doctrine respond button: dr:<uuid>."""
    data = f"{_ACTION_DOCTRINE_RESPOND}:{turn_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def parse_doctrine_callback(data: str) -> UUID | None:
    """Parse doctrine callback_data into turn_id or None."""
    if not data or ":" not in data:
        return None
    code, raw_id = data.split(":", 1)
    if code != _ACTION_DOCTRINE_RESPOND:
        return None
    try:
        return UUID(raw_id)
    except ValueError:
        return None


def draft_keyboard(turn_id: UUID) -> InlineKeyboardMarkup:
    """Approve / Correct / Escalate inline keyboard for owner DM."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Approve",
                    callback_data=encode_callback("approve", turn_id),
                ),
                InlineKeyboardButton(
                    text="✏️ Correct",
                    callback_data=encode_callback("correct", turn_id),
                ),
                InlineKeyboardButton(
                    text="⚠️ Escalate",
                    callback_data=encode_callback("escalate", turn_id),
                ),
            ]
        ]
    )


def doctrine_keyboard(turn_id: UUID, query_id: UUID | None = None) -> InlineKeyboardMarkup:
    """Reply markup for gray zone doctrine queries.

    Uses compact callback encoding (dr:<uuid>) to stay under Telegram's
    64-byte callback_data limit. The query_id is stored server-side via
    the reply_markup_spec for the handler to look up.

    Full implementation in Item 4 (callback handlers).
    For now, returns a simple keyboard with the respond_doctrine action.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Respond to query",
                    callback_data=encode_doctrine_callback(turn_id),
                ),
            ]
        ]
    )


__all__ = [
    "doctrine_keyboard",
    "draft_keyboard",
    "encode_callback",
    "encode_doctrine_callback",
    "parse_callback",
    "parse_doctrine_callback",
]
