
"""Director check-in fast-lane tests (pools + fail-soft context)."""

from __future__ import annotations

import random
from typing import Any

import pytest

from diana.application.turn_classifier import TurnClassifier, make_checkin_cut
from diana.cognitive.template_gate import (
    CHECKIN_BIENESTAR_POOL,
    CHECKIN_DIA_POOL,
    PhaticLightContext,
)
from diana.llm.fake import FakeLLM
from tests.unit.cognitive.test_director import (
    SALUDO_POOL,
    _h6_template_gate,
    _pure_greeting_cut_using_tc,
    _profile,
    _saludo_comprehension,
    _turn,
    _wire_stage_spies,
    make_director,
)


def _checkin_cut_using_tc(classifier: TurnClassifier | None = None):
    return make_checkin_cut(classifier or TurnClassifier())


class _EmptyContext:
    async def get(self, turn: Any) -> PhaticLightContext:
        return PhaticLightContext()


class _BoomContext:
    async def get(self, turn: Any) -> PhaticLightContext:
        raise RuntimeError("context unavailable")


@pytest.mark.asyncio
async def test_checkin_como_estas_uses_bienestar_pool_not_holis() -> None:
    llm = FakeLLM(
        structured_responses=[_saludo_comprehension()],
        text_responses=["should-not-generate"],
    )
    director, trace, _ = make_director(
        llm,
        template_gate=_h6_template_gate(),
        pure_greeting_cut=_pure_greeting_cut_using_tc(),
        saludo_response_pool=list(SALUDO_POOL),
        saludo_rng=random.Random(0),
        phatic_auto_send=True,
        checkin_cut=_checkin_cut_using_tc(),
        phatic_context_provider=_EmptyContext(),
    )
    _wire_stage_spies(director)
    turn = _turn(text="cómo estás")
    decision = await director.handle_turn(turn)
    assert decision.reason == "plantilla_checkin_bienestar"
    assert decision.action == "send"
    assert decision.draft_text in CHECKIN_BIENESTAR_POOL
    assert decision.draft_text not in SALUDO_POOL
    assert trace.get(turn.turn_id, "plan") is None
    director._planner.plan.assert_not_called()  # type: ignore[attr-defined]
    director._generator.generate.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_checkin_que_tal_tu_dia_uses_dia_pool() -> None:
    llm = FakeLLM(
        structured_responses=[_saludo_comprehension()],
        text_responses=["should-not-generate"],
    )
    director, _, _ = make_director(
        llm,
        template_gate=_h6_template_gate(),
        pure_greeting_cut=_pure_greeting_cut_using_tc(),
        saludo_response_pool=list(SALUDO_POOL),
        saludo_rng=random.Random(2),
        phatic_auto_send=True,
        checkin_cut=_checkin_cut_using_tc(),
        phatic_context_provider=_EmptyContext(),
    )
    decision = await director.handle_turn(_turn(text="qué tal tu día"))
    assert decision.reason == "plantilla_checkin_dia"
    assert decision.draft_text in CHECKIN_DIA_POOL
    assert decision.draft_text not in SALUDO_POOL


@pytest.mark.asyncio
async def test_pure_hola_still_saludo_puro_when_checkin_wired() -> None:
    llm = FakeLLM(
        structured_responses=[_saludo_comprehension()],
        text_responses=["should-not-generate"],
    )
    director, _, _ = make_director(
        llm,
        template_gate=_h6_template_gate(),
        pure_greeting_cut=_pure_greeting_cut_using_tc(),
        saludo_response_pool=list(SALUDO_POOL),
        saludo_rng=random.Random(0),
        checkin_cut=_checkin_cut_using_tc(),
        phatic_context_provider=_EmptyContext(),
    )
    decision = await director.handle_turn(_turn(text="Hola"))
    assert decision.reason == "plantilla_saludo"
    assert decision.draft_text in SALUDO_POOL


@pytest.mark.asyncio
async def test_sales_message_not_checkin_template() -> None:
    llm = FakeLLM(
        structured_responses=[_saludo_comprehension(), _profile(safety=0.5)],
        text_responses=["Sales path draft"],
    )
    director, trace, _ = make_director(
        llm,
        template_gate=_h6_template_gate(),
        pure_greeting_cut=_pure_greeting_cut_using_tc(),
        saludo_response_pool=list(SALUDO_POOL),
        checkin_cut=_checkin_cut_using_tc(),
        phatic_context_provider=_EmptyContext(),
        phatic_auto_send=True,
    )
    turn = _turn(text="cómo estás, quiero comprar el pack")
    decision = await director.handle_turn(turn)
    assert not str(decision.reason).startswith("plantilla_checkin")
    assert decision.reason != "plantilla_saludo"
    assert decision.draft_text == "Sales path draft"
    assert trace.get(turn.turn_id, "plan") is not None


@pytest.mark.asyncio
async def test_checkin_context_missing_still_pool_line() -> None:
    llm = FakeLLM(
        structured_responses=[_saludo_comprehension()],
        text_responses=["should-not-generate"],
    )
    director, _, _ = make_director(
        llm,
        template_gate=_h6_template_gate(),
        pure_greeting_cut=_pure_greeting_cut_using_tc(),
        saludo_response_pool=list(SALUDO_POOL),
        saludo_rng=random.Random(3),
        checkin_cut=_checkin_cut_using_tc(),
        phatic_context_provider=_BoomContext(),
        phatic_auto_send=False,
    )
    decision = await director.handle_turn(_turn(text="como estas"))
    assert decision.reason == "plantilla_checkin_bienestar"
    assert decision.action == "approve"
    assert decision.draft_text in CHECKIN_BIENESTAR_POOL


@pytest.mark.asyncio
async def test_long_non_greeting_not_checkin() -> None:
    llm = FakeLLM(
        structured_responses=[_saludo_comprehension(), _profile(safety=0.5)],
        text_responses=["Long path draft"],
    )
    director, _, _ = make_director(
        llm,
        template_gate=_h6_template_gate(),
        pure_greeting_cut=_pure_greeting_cut_using_tc(),
        saludo_response_pool=list(SALUDO_POOL),
        checkin_cut=_checkin_cut_using_tc(),
        phatic_context_provider=_EmptyContext(),
    )
    decision = await director.handle_turn(
        _turn(text="Hola, tengo una pregunta sobre el contenido")
    )
    assert decision.reason != "plantilla_saludo"
    assert not str(decision.reason).startswith("plantilla_checkin")
    assert decision.draft_text == "Long path draft"
