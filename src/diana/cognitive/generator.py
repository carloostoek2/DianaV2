"""Generator — single question: what draft text should we propose?"""

from __future__ import annotations

from diana.cognitive.ports import LLMProvider

_SYSTEM = (
    "You are the message Generator for a VIP chat assistant. "
    "Write a natural reply draft based only on the prompt. "
    "Do not classify, score, or choose system actions. Output the draft text only."
)


class Generator:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def generate(self, prompt: str) -> str:
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ]
        return await self._llm.generate(messages)
