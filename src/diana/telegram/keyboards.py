"""Compact owner draft keyboards (callback_data ≤ 64 bytes)."""

from __future__ import annotations

from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# action:{uuid} — approve / correct / escalate
_ACTION_APPROVE = "a"
_ACTION_CORRECT = "c"
_ACTION_ESCALATE = "e"


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


__all__ = [
    "draft_keyboard",
    "encode_callback",
    "parse_callback",
]
