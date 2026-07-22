"""CognitiveDirector — deterministic sequencer for the F1 decision path.

Control flow is fixed. The Director never asks a model which action to take.

ITEM 3 contract
---------------
``handle_turn`` takes a **single** argument: ``IncomingTurn`` (alias
``TurnContext``). Callers must mint ``turn_id`` (and usually persist a turns
row) **before** invocation. The two-argument MVP sketch
``handle_turn(turn, incoming)`` is **not** implemented — map Telegram fields
into ``IncomingTurn`` at the application layer.
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
from diana.cognitive.ports import (
    NoOpTurnStatusSink,
    TraceStore,
    TurnStatusSink,
    to_jsonable,
)
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
        """Run the F1 cognitive pipeline for one inbound turn.

        Args:
            turn_context: Fully formed ``IncomingTurn`` with ``turn_id`` already
                assigned by the application layer (item 3+).

        Returns:
            ``Decision`` with ``action`` in {approve, escalate} and ``draft_text``
            set from the Generator (or empty string when escalate-for-empty-draft).

        On unexpected errors the status sink receives ``TurnStatus.FAILED`` and
        the exception is re-raised. Partial artifacts already stored remain in
        the TraceStore for reconstructability.
        """
        turn = turn_context
        turn_id = turn.turn_id
        try:
            return await self._run_pipeline(turn)
        except Exception:
            await self._status.transition(turn_id, TurnStatus.FAILED)
            raise

    async def _run_pipeline(self, turn: IncomingTurn) -> Decision:
        turn_id = turn.turn_id

        await self._status.transition(turn_id, TurnStatus.ANALYZING)
        comprehension = await self._analyst.analyze(turn)
        await self._store(turn_id, "comprehension", comprehension)

        await self._status.transition(turn_id, TurnStatus.PLANNING)
        plan = self._planner.plan(comprehension)
        await self._store(turn_id, "plan", plan)

        await self._status.transition(turn_id, TurnStatus.RETRIEVING)
        retrieved: dict[str, Any | None] = {}
        try:
            for cap in plan.capabilities:
                retriever = self._registry.resolve(cap)
                retrieved[cap] = await retriever.fetch(turn, comprehension)
        finally:
            # Persist partial retrieved map even when a fetch fails mid-loop.
            if retrieved:
                await self._store(turn_id, "retrieved", retrieved)
        await self._store(turn_id, "retrieved", retrieved)

        await self._status.transition(turn_id, TurnStatus.BUILDING_CONTEXT)
        prompt = self._context_builder.build(
            turn,
            comprehension,
            knowledge=retrieved,
            persona=self._persona,
        )
        await self._store(turn_id, "prompt_text", prompt)

        await self._status.transition(turn_id, TurnStatus.GENERATING)
        draft = await self._generator.generate(prompt)
        await self._store(turn_id, "generated_text", draft)

        await self._status.transition(turn_id, TurnStatus.EVALUATING)
        evaluation = await self._evaluator.evaluate(draft, comprehension, turn)
        await self._store(turn_id, "evaluation", evaluation)

        await self._status.transition(turn_id, TurnStatus.DECIDING)
        # Empty / whitespace-only draft must never approve (product safety).
        if not (draft or "").strip():
            decision = Decision(
                action="escalate",
                reason="empty_draft",
                evaluation=evaluation,
                draft_text=draft if draft is not None else "",
            )
        else:
            base = self._decider.decide(evaluation, comprehension, mode="supervised")
            decision = Decision(
                action=base.action,
                reason=base.reason,
                evaluation=base.evaluation,
                draft_text=draft,
            )
        await self._store(turn_id, "decision", decision)
        return decision

    async def _store(self, turn_id: Any, key: str, value: Any) -> None:
        await self._trace.store(turn_id, key, to_jsonable(value))
