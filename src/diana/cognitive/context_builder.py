"""Assemble the minimum prompt from turn, comprehension, and knowledge (Anexo D)."""

from __future__ import annotations

import json
from typing import Any

from diana.cognitive.exceptions import ContextExceedsLimitError
from diana.cognitive.models import BuiltContext, Comprehension, IncomingTurn

# D.4 fixed knowledge emission order (independent of dict insertion).
_KNOWLEDGE_EMISSION_ORDER: tuple[str, ...] = (
    "knowledge.history",
    "knowledge.context",
    "knowledge.memory",
    "knowledge.policy",
    "knowledge.examples",
    "knowledge.schedule",
    "knowledge.profile",
)

DEFAULT_MAX_PROMPT_CHARS = 100_000


class ContextBuilder:
    """Build minimal Generator context; omit knowledge sections whose value is null-like.

    Answers only: what is the minimal context for the Generator? (Anexo D.1).
    No LLM, no draft, no scoring. Dict ``knowledge`` is the Registry shape
    (capability name → retrieved value; Spanish contract: conocimiento_recuperado).

    Null-like values: ``None``, empty ``list``/``dict``/``tuple``/``set``,
    empty/whitespace ``str``. REAL retrievers that return empty collections
    therefore do not pollute the prompt with empty headings.
    """

    def __init__(
        self,
        *,
        max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
    ) -> None:
        self._max_prompt_chars = max_prompt_chars

    def build(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
        knowledge: dict[str, Any | None],
        persona: str,
        style_rules: list[str] | None = None,
    ) -> BuiltContext:
        parts: list[str] = [
            "## Persona",
            persona.strip(),
        ]
        rules = style_rules or []
        for rule in rules:
            if isinstance(rule, str) and rule.strip():
                parts.append(rule.strip())

        included_blocks: list[str] = []
        for name in _KNOWLEDGE_EMISSION_ORDER:
            if name not in knowledge:
                continue
            value = knowledge[name]
            if _is_null_like(value):
                continue
            parts.append("")
            parts.append(f"## Knowledge: {name}")
            parts.append(_format_value(value))
            included_blocks.append(name)

        parts.extend(
            [
                "",
                "## Comprehension",
                f"intent: {comprehension.intent}",
                f"topics: {', '.join(comprehension.topics)}",
                f"emotion: {comprehension.emotion}",
                f"urgency: {comprehension.urgency}",
                f"risk: {comprehension.risk}",
                "",
                "## Current VIP message",
                turn.text,
            ]
        )
        prompt = "\n".join(parts).strip() + "\n"
        if len(prompt) > self._max_prompt_chars:
            raise ContextExceedsLimitError()
        return BuiltContext(prompt_final=prompt, included_blocks=included_blocks)

    def list_included_blocks(self, knowledge: dict[str, Any | None]) -> list[str]:
        """Capability names that appear as ## Knowledge sections in build() (D.4 order)."""
        return [
            name
            for name in _KNOWLEDGE_EMISSION_ORDER
            if name in knowledge and not _is_null_like(knowledge[name])
        ]


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
