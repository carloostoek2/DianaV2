"""Compact owner draft keyboards (callback_data ≤ 64 bytes)."""

from __future__ import annotations

from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# action:{uuid} — approve / correct / escalate / doctrine_respond
_ACTION_APPROVE = "a"
_ACTION_CORRECT = "c"
_ACTION_ESCALATE = "e"
_ACTION_DOCTRINE_RESPOND = "dr"
_ACTION_DOCTRINE_RESOLVE = "dx"
_ACTION_DOCTRINE_ESCALATE = "de"


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

    # Try doctrine callbacks first.
    if code == _ACTION_DOCTRINE_RESOLVE:
        try:
            return "resolve_with_draft", UUID(raw_id)
        except ValueError:
            return None
    if code == _ACTION_DOCTRINE_ESCALATE:
        try:
            return "escalate_doctrine", UUID(raw_id)
        except ValueError:
            return None
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


def parse_doctrine_callback(data: str, prefix: str | None = None) -> UUID | None:
    """Extract UUID from doctrine callback data (dr:|dx:|de:<uuid>).

    Args:
        data: The callback data string.
        prefix: If provided, only match this prefix (e.g. ``"dr"``).
                When ``None`` (default), any prefix is accepted.
    """
    if not data or ":" not in data:
        return None
    code, raw_id = data.split(":", 1)
    if prefix is not None and code != prefix:
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


def encode_doctrine_resolve_callback(turn_id: UUID) -> str:
    """Build callback_data for doctrine resolve-with-draft button: dx:<uuid>."""
    data = f"{_ACTION_DOCTRINE_RESOLVE}:{turn_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_doctrine_escalate_callback(turn_id: UUID) -> str:
    """Build callback_data for doctrine escalate button: de:<uuid>."""
    data = f"{_ACTION_DOCTRINE_ESCALATE}:{turn_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def doctrine_keyboard(turn_id: UUID) -> InlineKeyboardMarkup:
    """Reply markup for gray zone doctrine queries (three actions).

    - Respond: owner writes free-text doctrine
    - Use draft: auto-resolve with the existing draft
    - Escalate: discard query, escalate turn
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Respond to query",
                    callback_data=encode_doctrine_callback(turn_id),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Use draft as-is",
                    callback_data=encode_doctrine_resolve_callback(turn_id),
                ),
                InlineKeyboardButton(
                    text="Escalate",
                    callback_data=encode_doctrine_escalate_callback(turn_id),
                ),
            ],
        ]
    )


__all__ = [
    "doctrine_keyboard",
    "draft_keyboard",
    "encode_callback",
    "encode_doctrine_callback",
    "encode_doctrine_resolve_callback",
    "encode_doctrine_escalate_callback",
    "parse_callback",
    "parse_doctrine_callback",
]
