"""Analyst — single question: what is happening in this turn?"""

from __future__ import annotations

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.ports import LLMProvider

_SYSTEM = (
    "You are the Analyst for a VIP chat assistant. "
    "Given the VIP message, produce a structured comprehension object. "
    "Use English field names. urgency is one of: baja, media, alta. "
    "risk is one of: bajo, medio, alto. "
    "Set needs_* flags for knowledge that would help reply."
)


class Analyst:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def analyze(self, turn: IncomingTurn) -> Comprehension:
        messages = [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": f"VIP message:\n{turn.text}",
            },
        ]
        result = await self._llm.generate_structured(messages, Comprehension)
        if not isinstance(result, Comprehension):
            result = Comprehension.model_validate(result.model_dump())
        if result.raw_llm_output is None:
            raw = result.model_dump(mode="json", exclude={"raw_llm_output"})
            result = result.model_copy(update={"raw_llm_output": raw})
        return result
