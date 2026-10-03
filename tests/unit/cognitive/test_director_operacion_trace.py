"""Director: traza ``operacion_match`` honesta en las salidas tempranas (ítem 2, B2).

Saludo puro, check-in y H4 (pregunta_repetida) salen antes de la recuperación:
nunca inyectan Operación, así que la traza dice ``injected: False`` e
``injected_ids == []``. Solo el camino con recuperación registra ids reales.
La traza es del proceso (InMemoryTraceStore); ``SqlTraceStore`` no la persiste.
"""

from __future__ import annotations

import random
from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest

from diana.cognitive.analyst import Analyst
from diana.cognitive.context_builder import ContextBuilder
from diana.cognitive.decider import Decider
from diana.cognitive.director import CognitiveDirector
from diana.cognitive.evaluator import Evaluator
from diana.cognitive.generator import Generator
from diana.cognitive.models import Comprehension, EvaluationProfile, IncomingTurn
from diana.cognitive.persona_catalog import get_persona_atencion_catalog, get_persona_catalog
from diana.cognitive.planner import Planner
from diana.cognitive.ports import InMemoryMessageHistory, InMemoryRecentIntents, InMemoryTraceStore
from diana.cognitive.registry import build_default_registry
from diana.cognitive.repetition_guard import RepetitionGuard
from diana.llm.fake import FakeLLM

LUCIEN = {"id": "lucien", "hecho": "Lucien es el bot administrador del canal VIP.",
          "alias": ["Lucien", "el mayordomo"]}
CHAT_ID = 7


def _catalogs() -> dict[str, dict]:
    vip = deepcopy(get_persona_catalog())
    vip["operacion"] = [deepcopy(LUCIEN)]
    return {"vip": vip, "atencion": deepcopy(get_persona_atencion_catalog())}


class _Provider:
    def __init__(self, by_channel: dict) -> None:
        self.by_channel = by_channel

    async def get_catalog(self, channel_type: str = "vip") -> Any:
        return self.by_channel.get(channel_type)


def _comp(intent: str = "otro") -> Comprehension:
    return Comprehension(
        intent=intent, topics=["canal"], emotion="neutral", urgency="baja", risk="bajo",
        needs_memory=False, needs_policy=False, needs_schedule=False,
        needs_examples=False, needs_history=False, needs_context=False,
    )


def _profile() -> EvaluationProfile:
    return EvaluationProfile(naturalness=0.9, precision=0.8, doctrine=0.85, consistency=0.9,
                             safety=0.95, coverage=0.7, empathy=0.8)


def _turn(text: str, channel: str = "vip") -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=CHAT_ID, text=text, channel_type=channel)  # type: ignore[arg-type]


def _director(*, enabled: bool = True, **early_exit: Any) -> tuple[CognitiveDirector, InMemoryTraceStore, FakeLLM]:
    provider = _Provider(_catalogs())
    llm = FakeLLM(structured_responses=[_comp(), _profile()], text_responses=["draft"])
    history = InMemoryMessageHistory()
    trace = InMemoryTraceStore()
    director = CognitiveDirector(
        analyst=Analyst(llm),
        planner=Planner(),
        registry=build_default_registry(history, persona_catalog_provider=provider),
        context_builder=ContextBuilder(),
        generator=Generator(llm),
        evaluator=Evaluator(llm),
        decider=Decider(),
        trace=trace,
        persona="P",
        history=history,
        persona_catalog_provider=provider,
        feature_persona_operacion_enabled=enabled,
        saludo_rng=random.Random(0),
        **early_exit,
    )
    return director, trace, llm


def _saludo() -> dict[str, Any]:
    return {"pure_greeting_cut": lambda text, comp: True, "saludo_response_pool": ["¡Hola! 😊"]}


def _checkin() -> dict[str, Any]:
    return {"checkin_cut": lambda text, comp: True}


def _h4() -> dict[str, Any]:
    intents = InMemoryRecentIntents()
    intents.seed(CHAT_ID, ["otro", "otro"])  # 2 previos + el actual = racha 3
    return {"recent_intents": intents, "repetition_guard": RepetitionGuard(threshold=3)}


NOT_INJECTED = {
    "channel_type": "vip",
    "matched": [{"id": "lucien", "alias": "Lucien"}],
    "injected_ids": [],
    "injected": False,
}


@pytest.mark.parametrize(
    ("early_exit", "reason"),
    [(_saludo, "plantilla_saludo"), (_checkin, "plantilla_checkin_"), (_h4, "pregunta_repetida")],
)
async def test_early_exits_trace_match_without_injection(early_exit: Any, reason: str) -> None:
    director, trace, llm = _director(**early_exit())
    turn = _turn("Hola Lucien, ¿cómo estás?")
    decision = await director.handle_turn(turn)

    assert decision.reason.startswith(reason)
    assert trace.get(turn.turn_id, "plan") is None  # salió antes de la recuperación
    assert trace.get(turn.turn_id, "retrieved") is None
    assert trace.get(turn.turn_id, "comprehension")["needs_operacion"] is True  # se necesitaba
    assert trace.get(turn.turn_id, "operacion_match") == NOT_INJECTED
    assert [name for name, _ in llm.calls] == ["generate_structured"]  # solo el Analyst


async def test_full_pipeline_traces_the_injected_ids() -> None:
    director, trace, _ = _director()
    turn = _turn("Hola Lucien, ¿cómo estás?")
    await director.handle_turn(turn)
    assert trace.get(turn.turn_id, "operacion_match") == {
        **NOT_INJECTED, "injected_ids": ["lucien"], "injected": True,
    }
    assert trace.get(turn.turn_id, "retrieved")["knowledge.operacion"] == [
        {"hecho": LUCIEN["hecho"]}
    ]


@pytest.mark.parametrize("early_exit", [_saludo, _checkin, _h4])
async def test_early_exit_without_match_or_flag_off_has_no_trace(early_exit: Any) -> None:
    director, trace, _ = _director(**early_exit())
    turn = _turn("Hola, ¿cómo estás?")  # sin alias
    await director.handle_turn(turn)
    assert trace.get(turn.turn_id, "operacion_match") is None

    off, off_trace, _ = _director(enabled=False, **early_exit())
    turn = _turn("Hola Lucien, ¿cómo estás?")
    await off.handle_turn(turn)
    assert off_trace.get(turn.turn_id, "operacion_match") is None
    assert off_trace.get(turn.turn_id, "comprehension")["needs_operacion"] is False


async def test_atencion_early_exit_never_traces_vip_operacion() -> None:
    director, trace, _ = _director(**_saludo())
    turn = _turn("Hola Lucien, ¿cómo estás?", channel="atencion")
    await director.handle_turn(turn)
    assert trace.get(turn.turn_id, "operacion_match") is None
