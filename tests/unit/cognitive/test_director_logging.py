"""CognitiveDirector pipeline logging tests — caplog on the diana.cognitive logger.

Reuses the director builder and LLM fakes from ``test_director``.
"""

from __future__ import annotations

import logging

import pytest

from diana.cognitive.repetition_guard import RepetitionGuard
from diana.cognitive.ports import InMemoryRecentIntents
from diana.llm.fake import FakeLLM

import test_director as td


@pytest.mark.asyncio
async def test_full_pipeline_logs_each_stage(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="diana.cognitive")
    llm = FakeLLM(
        structured_responses=[td._comprehension(), td._profile()],
        text_responses=["Draft reply for VIP"],
    )
    director, _, _ = td.make_director(llm)

    await director.handle_turn(td._turn(text="hola amor, cómo vas?"))

    messages = " ".join(caplog.messages)
    assert "Turno recibido" in messages
    assert "Comprensión" in messages
    assert "Plan" in messages
    assert "Retrieval" in messages
    assert "Borrador" in messages
    assert "Evaluación" in messages
    assert "Decisión para chat" in messages


@pytest.mark.asyncio
async def test_template_h6_logs_rule(caplog: pytest.LogCaptureFixture) -> None:
    """Pure saludo logs post-Analyst cut (not pre-gate saludo_constante)."""
    caplog.set_level(logging.INFO, logger="diana.cognitive")
    llm = FakeLLM(
        structured_responses=[td._saludo_comprehension()],
        text_responses=[],
    )
    director, _, _ = td.make_director(
        llm,
        template_gate=td._h6_template_gate(),
        pure_greeting_cut=td._pure_greeting_cut_using_tc(),
        saludo_response_pool=list(td.SALUDO_POOL),
        saludo_rng=__import__("random").Random(0),
    )

    decision = await director.handle_turn(td._turn(text="hola"))

    assert decision.action == "approve"
    assert decision.reason == "plantilla_saludo"
    messages = " ".join(caplog.messages)
    assert "Comprensión" in messages
    assert "plantilla_saludo" in messages
    assert "saludo_constante" not in messages
    assert "Plantilla H6" not in messages


@pytest.mark.asyncio
async def test_template_h6_ia_logs_pre_pipeline(caplog: pytest.LogCaptureFixture) -> None:
    """IA probe still logs Plantilla H6 pre-pipeline path."""
    caplog.set_level(logging.INFO, logger="diana.cognitive")
    llm = FakeLLM(structured_responses=[], text_responses=[])
    director, _, _ = td.make_director(llm, template_gate=td._h6_template_gate())

    decision = await director.handle_turn(td._turn(text="eres una ia?"))

    assert decision.reason == "plantilla_deteccion_ia"
    messages = " ".join(caplog.messages)
    assert "Plantilla H6" in messages
    assert "deteccion_ia" in messages


@pytest.mark.asyncio
async def test_repetition_logs_escalation(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="diana.cognitive")
    intents = InMemoryRecentIntents()
    intents.seed(42, ["precio", "precio"])  # current makes streak 3
    llm = FakeLLM(
        structured_responses=[
            td._comprehension(intent="precio", risk="bajo"),
            td._profile(safety=0.9),
        ],
        text_responses=["should-not-generate"],
    )
    director, _, _ = td.make_director(
        llm,
        recent_intents=intents,
        repetition_guard=RepetitionGuard(threshold=3),
    )

    decision = await director.handle_turn(td._turn(chat_id=42, text="otra vez el precio"))

    assert decision.reason == "pregunta_repetida"
    messages = " ".join(caplog.messages)
    assert "Repetición" in messages
    assert "pregunta_repetida" in messages
