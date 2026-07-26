"""Analyst — single question: what is happening in this turn?"""

from __future__ import annotations

import json

from pydantic import ValidationError

from diana.cognitive.exceptions import AnalystSchemaInvalidError
from diana.cognitive.models import AnalystInput, Comprehension
from diana.cognitive.ports import LLMProvider

# A.1 pure classifier prompt: no tone/style/writing/business policy instructions.
_SYSTEM = (
    "You are the Analyst. Answer only one question: what is happening in this turn? "
    "Produce a structured comprehension object with English field names. "
    "emotion must be one of: neutral, positiva, ansiosa, molesta, triste, cariñosa, urgente. "
    "urgency must be one of: baja, media, alta. "
    "risk must be one of: bajo, medio, alto. "
    "Required fields: intent, topics, emotion, urgency, risk, "
    "needs_memory, needs_policy, needs_schedule, needs_examples, needs_history, needs_context. "
    "Also set needs_persona_facts and needs_voice_patterns (default false if unsure). "
    "intent is a free lowercase verb_object label. topics is a list of lowercase strings. "
    "Set each needs_* boolean only to indicate which knowledge would help later stages. "
    "needs_persona_facts=true when the turn asks about Diana biography/personal facts "
    "(familia, estudios, duelo, vivienda, rutina, canal). "
    "needs_voice_patterns=true when a characteristic voice/muletilla would help. "
    "needs_policy=true for limits, content promises, bio invention bounds, or photo/video requests."
)

_MAX_ATTEMPTS = 2  # initial try + exactly one retry (contrato A.6)

# Structured-output / schema-class failures (contrato A.6.1 + A.6.4).
# Includes DeepSeek JSON ValueError and transport timeouts without importing httpx.
_SCHEMA_FAIL_TYPES = (ValidationError, ValueError, TimeoutError)


def _is_schema_class_failure(exc: BaseException) -> bool:
    """Return True for failures that mean unusable structured comprehension."""
    if isinstance(exc, _SCHEMA_FAIL_TYPES):
        return True
    # httpx.TimeoutException and relatives without a cognitive→httpx import.
    name = type(exc).__name__
    if "Timeout" in name:
        return True
    return False


class Analyst:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def analyze(self, input: AnalystInput) -> Comprehension:
        messages = self._build_messages(input)
        last_error: Exception | None = None
        for _attempt in range(_MAX_ATTEMPTS):
            try:
                result = await self._llm.generate_structured(messages, Comprehension)
                if not isinstance(result, Comprehension):
                    result = Comprehension.model_validate(result.model_dump())
                if result.raw_llm_output is None:
                    raw = result.model_dump(mode="json", exclude={"raw_llm_output"})
                    result = result.model_copy(update={"raw_llm_output": raw})
                return result
            except Exception as exc:
                if not _is_schema_class_failure(exc):
                    raise
                last_error = exc
                continue
        raise AnalystSchemaInvalidError() from last_error

    def _build_messages(self, input: AnalystInput) -> list[dict[str, str]]:
        history_payload = [
            {
                "autor": msg.autor,
                "texto": msg.texto,
                "timestamp": (
                    msg.timestamp.isoformat()
                    if hasattr(msg.timestamp, "isoformat")
                    else str(msg.timestamp)
                ),
            }
            for msg in input.historial_reciente
        ]
        user_content = (
            f"turno_actual:\n{input.turno_actual}\n\n"
            f"historial_reciente:\n{json.dumps(history_payload, ensure_ascii=False)}"
        )
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_content},
        ]
