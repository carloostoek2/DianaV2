"""Evaluator — single question: how does this draft score on 7 dimensions?"""

from __future__ import annotations

from diana.cognitive.models import Comprehension, EvaluationProfile, IncomingTurn
from diana.cognitive.ports import LLMProvider

_SYSTEM = (
    "You are the Evaluator for a VIP chat assistant. "
    "Score the draft reply on exactly seven English dimensions as floats 0..1: "
    "naturalness, precision, doctrine, consistency, safety, coverage, empathy. "
    "Do not invent a single overall score. Do not choose the system action."
)


class Evaluator:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def evaluate(
        self,
        draft: str,
        comprehension: Comprehension,
        turn: IncomingTurn,
    ) -> EvaluationProfile:
        messages = [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": (
                    f"VIP message:\n{turn.text}\n\n"
                    f"Comprehension intent={comprehension.intent} "
                    f"risk={comprehension.risk} urgency={comprehension.urgency}\n\n"
                    f"Draft reply:\n{draft}"
                ),
            },
        ]
        result = await self._llm.generate_structured(messages, EvaluationProfile)
        if not isinstance(result, EvaluationProfile):
            result = EvaluationProfile.model_validate(result.model_dump())
        if result.raw_llm_output is None:
            raw = result.model_dump(mode="json", exclude={"raw_llm_output"})
            result = result.model_copy(update={"raw_llm_output": raw})
        return result
