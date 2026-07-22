"""Assemble the minimum prompt string from turn, comprehension, and knowledge."""

from __future__ import annotations

import json
from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn


class ContextBuilder:
    """Build a text prompt; omit knowledge sections whose value is null-like.

    Null-like values: ``None``, empty ``list``, empty ``dict``, empty/whitespace
    ``str``. REAL retrievers that return empty collections therefore do not
    pollute the prompt with empty headings.
    """

    def build(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
        knowledge: dict[str, Any | None],
        persona: str,
    ) -> str:
        parts: list[str] = [
            "## Persona",
            persona.strip(),
            "",
            "## Current VIP message",
            turn.text,
            "",
            "## Comprehension",
            f"intent: {comprehension.intent}",
            f"topics: {', '.join(comprehension.topics)}",
            f"emotion: {comprehension.emotion}",
            f"urgency: {comprehension.urgency}",
            f"risk: {comprehension.risk}",
        ]
        for name, value in knowledge.items():
            if _is_null_like(value):
                continue
            parts.append("")
            parts.append(f"## Knowledge: {name}")
            parts.append(_format_value(value))
        return "\n".join(parts).strip() + "\n"


def _is_null_like(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict, tuple, set)) and len(value) == 0:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str, indent=2)
    except TypeError:
        return str(value)
