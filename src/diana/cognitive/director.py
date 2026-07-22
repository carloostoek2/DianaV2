"""CognitiveDirector — deterministic sequencer for the F1 decision path.

Control flow is fixed. The Director never asks a model which action to take.
"""

from __future__ import annotations

from typing import Any

from diana.cognitive.analyst import Analyst
from diana.cognitive.context_builder import ContextBuilder
from diana.cognitive.decider import Decider
from diana.cognitive.evaluator import Evaluator
from diana.cognitive.generator import Generator
from diana.cognitive.models import Decision, IncomingTurn, TurnStatus
from diana.cognitive.planner import Planner
from diana.cognitive.ports import NoOpTurnStatusSink, TraceStore, TurnStatusSink
from diana.cognitive.registry import CapabilityRegistry


class CognitiveDirector:
    """Ordered pipeline: Analyst → Planner → Registry → Context → Generator → Evaluator → Decider."""

    def __init__(
        self,
        *,
        analyst: Analyst,
        planner: Planner,
        registry: CapabilityRegistry,
        context_builder: ContextBuilder,
        generator: Generator,
        evaluator: Evaluator,
        decider: Decider,
        trace: TraceStore,
        persona: str,
        status_sink: TurnStatusSink | None = None,
    ) -> None:
        self._analyst = analyst
        self._planner = planner
        self._registry = registry
        self._context_builder = context_builder
        self._generator = generator
        self._evaluator = evaluator
        self._decider = decider
        self._trace = trace
        self._persona = persona
        self._status = status_sink or NoOpTurnStatusSink()

    async def handle_turn(self, turn_context: IncomingTurn) -> Decision:
        turn = turn_context
        turn_id = turn.turn_id

        await self._status.transition(turn_id, TurnStatus.ANALYZING)
        comprehension = await self._analyst.analyze(turn)
        await self._trace.store(turn_id, "comprehension", comprehension)

        await self._status.transition(turn_id, TurnStatus.PLANNING)
        plan = self._planner.plan(comprehension)
        await self._trace.store(turn_id, "plan", plan)

        await self._status.transition(turn_id, TurnStatus.RETRIEVING)
        retrieved: dict[str, Any | None] = {}
        for cap in plan.capabilities:
            retriever = self._registry.resolve(cap)
            retrieved[cap] = await retriever.fetch(turn, comprehension)
        await self._trace.store(turn_id, "retrieved", retrieved)

        await self._status.transition(turn_id, TurnStatus.BUILDING_CONTEXT)
        prompt = self._context_builder.build(
            turn,
            comprehension,
            knowledge=retrieved,
            persona=self._persona,
        )
        await self._trace.store(turn_id, "prompt", prompt)

        await self._status.transition(turn_id, TurnStatus.GENERATING)
        draft = await self._generator.generate(prompt)
        await self._trace.store(turn_id, "generated", draft)

        await self._status.transition(turn_id, TurnStatus.EVALUATING)
        evaluation = await self._evaluator.evaluate(draft, comprehension, turn)
        await self._trace.store(turn_id, "evaluation", evaluation)

        await self._status.transition(turn_id, TurnStatus.DECIDING)
        base = self._decider.decide(evaluation, comprehension, mode="supervised")
        decision = Decision(
            action=base.action,
            reason=base.reason,
            evaluation=base.evaluation,
            draft_text=draft,
        )
        await self._trace.store(turn_id, "decision", decision)
        return decision
