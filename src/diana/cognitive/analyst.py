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
    "Also set needs_persona_facts, needs_voice_patterns, and needs_profile "
    "(default false if unsure). "
    "intent is a free lowercase verb_object label. topics is a list of lowercase strings. "
    "Set each needs_* boolean only to indicate which knowledge would help later stages. "
    "needs_persona_facts=true when the turn asks about Diana biography/personal facts. "
    "Prefer topics/intent from catalog temas: familia, duelo, estudios, trayectoria, "
    "vivienda, rutina, independencia, trabajo, contenido, canal, suscripcion, soporte, "
    "motivacion_personal, tema_pesado. "
    "needs_voice_patterns=true when a characteristic voice/muletilla would help. "
    "Useful tags: risa, humor, casual, saludo, apertura, cariño, cercania, enfasis, "
    "honestidad, tema_pesado, extrañar, reencuentro, conexion; emotion values "
    "positiva/cariñosa/triste/molesta/urgente also index patterns. "
    "needs_profile=true when stable VIP permanent profile notes would help "
    "(preferences/standing facts), not episodic memory. "
    "needs_policy=true for limits, content promises, bio invention bounds, or photo/video. "
    "Policy temas: contenido, expectativas, psicologia, limites_profesionales, biografia, "
    "limites, identidad, dinamica_novia_virtual; map foto/video requests to contenido. "
    "needs_schedule=true for direct questions about Diana's current activity/availability "
    "right now (qué haces, dónde andas, estás libre / \"ahora qué haces\"), "
    "not only future appointments. "
    "needs_history=true for almost every turn — a short follow-up like a bare "
    "date, a one-word answer, or a reply to a prior offer/question makes no "
    "sense without the last few messages. Set needs_history=false ONLY for a "
    "pure opening greeting or a fully self-contained message with no possible "
    "reference to anything said before. When in doubt, true. "
    "needs_examples=true when a similar past VIP exchange (same situation/register, e.g. "
    "flirty request, playful tease, mundane chat, emotional check-in) would help match "
    "how Diana actually replied before — not for purely factual/policy-governed turns "
    "(payment terms, schedule, biography) where those other fields already cover it."
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
