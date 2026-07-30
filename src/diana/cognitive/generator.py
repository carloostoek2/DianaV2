"""Generator — single question: how would the owner reply?"""

from __future__ import annotations

from diana.cognitive.exceptions import GeneratorEmptyOutputError
from diana.cognitive.ports import LLMProvider

# E.1: sole text producer; answer only the owner-reply question (REQ-COG-07).
# Communication standard (always-on): warm/close/cheerful; zero Mexican slang
# and zero profanity/vulgarity. Variable tone nuances come from the user prompt
# (persona + style rules + comprehension.emotion), never by inventing slang.
_SYSTEM = (
    "You are the message Generator for a VIP chat assistant. "
    "Answer only one question: how would the owner reply? "
    "Write a natural reply draft based only on the prompt. "
    "Default voice: warm, close, cheerful — never cold or robotic. "
    "HARD BAN (always): no Mexican slang (e.g. güey/wey, no mames, chido, "
    "qué pedo, órale as filler) and no swear words, profanity, or vulgarities. "
    "Follow any emotion-based style rules in the prompt (e.g. compassionate "
    "accompaniment when emotion is triste/ansiosa) without breaking the ban. "
    "Do not classify, search knowledge, score, or choose system actions. "
    "Output the draft text only."
)

_MAX_ATTEMPTS = 2  # initial + exactly one retry (Anexo E.4)


class Generator:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def generate(self, prompt: str) -> str:
        """Produce a plain-text draft from ``prompt_final``.

        Empty/whitespace output is retried once with the same messages.
        Permanent empty raises ``GeneratorEmptyOutputError``. Transport errors
        from the LLM provider are not treated as empty and propagate.
        """
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ]
        for _attempt in range(_MAX_ATTEMPTS):
            text = await self._llm.generate(messages)
            if (text or "").strip():
                return text
        raise GeneratorEmptyOutputError()
