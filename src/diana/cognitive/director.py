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
from diana.cognitive.models import (
    AnalystInput,
    Decision,
    EvaluatorInput,
    HistoryMessage,
    IncomingTurn,
    TurnStatus,
)
from diana.cognitive.planner import Planner
from diana.cognitive.ports import (
    MessageHistoryPort,
    NoOpTurnStatusSink,
    TraceStore,
    TurnStatusSink,
    to_jsonable,
)
from diana.cognitive.registry import CapabilityRegistry

# Short Analyst window (contrato A.2 recommends 5–10). Registry retrieval stays at 20.
ANALYST_HISTORY_LIMIT = 8

# Port/DB role vocabulary → contract autor (bot and unknown roles are excluded).
_ROLE_TO_AUTOR: dict[str, str] = {
    "vip": "vip",
    "owner": "dueña",
}


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
        history: MessageHistoryPort,
        analyst_history_limit: int = ANALYST_HISTORY_LIMIT,
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
        self._history = history
        self._analyst_history_limit = analyst_history_limit
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
        the TraceStore for reconstructability. On Analyst schema failure no
        comprehension or plan is stored. On Evaluator schema failure no
        evaluation or decision is stored.
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
        analyst_input = await self._build_analyst_input(turn)
        # On AnalystSchemaInvalidError: do not store partial comprehension; re-raise.
        comprehension = await self._analyst.analyze(analyst_input)
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
        # On EvaluatorSchemaInvalidError: do not store synthetic evaluation/decision.
        blocks = self._context_builder.list_included_blocks(retrieved)
        evaluation = await self._evaluator.evaluate(
            EvaluatorInput(
                draft=draft,
                comprehension=comprehension,
                included_blocks=blocks,
                current_turn=turn.text,
            )
        )
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

    async def _build_analyst_input(self, turn: IncomingTurn) -> AnalystInput:
        """Fetch chat-scoped history and map to contract historial_reciente (R1).

        - Over-fetches raw rows so bot/unknown filtering still yields up to
          ``analyst_history_limit`` vip/dueña lines when available.
        - Excludes the current VIP trigger message (by telegram_message_id, or
          trailing identical vip text fallback) so it is not duplicated with
          ``turno_actual``.
        """
        limit = self._analyst_history_limit
        # Oversample raw rows; filter roles; then trim to limit human messages.
        # Bot-heavy tails need headroom beyond limit (A.2 short window is human lines).
        fetch_limit = max(limit * 8, 32) if limit > 0 else 0
        raw = await self._history.get_recent(turn.chat_id, limit=fetch_limit)
        raw = self._drop_current_turn_rows(raw, turn)
        mapped = self._map_history_messages(raw)
        if limit > 0 and len(mapped) > limit:
            mapped = mapped[-limit:]
        return AnalystInput(turno_actual=turn.text, historial_reciente=mapped)

    @staticmethod
    def _drop_current_turn_rows(raw: list[dict], turn: IncomingTurn) -> list[dict]:
        """Remove the triggering VIP message already appended by the application."""
        mid = turn.telegram_message_id
        if mid is not None:
            return [
                row
                for row in raw
                if not (
                    isinstance(row, dict)
                    and row.get("role") == "vip"
                    and row.get("telegram_message_id") == mid
                )
            ]
        # Fallback when message id is absent: drop trailing vip row with same text.
        if not raw:
            return raw
        last = raw[-1]
        if (
            isinstance(last, dict)
            and last.get("role") == "vip"
            and str(last.get("text", "")) == turn.text
        ):
            return list(raw[:-1])
        return list(raw)

    @staticmethod
    def _map_history_messages(raw: list[dict]) -> list[HistoryMessage]:
        """Map port rows to HistoryMessage; exclude bot and unknown roles."""
        out: list[HistoryMessage] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            autor = _ROLE_TO_AUTOR.get(str(role) if role is not None else "")
            if autor is None:
                continue
            texto = item.get("text")
            if texto is None:
                texto = ""
            ts = item.get("timestamp")
            if ts is None:
                ts = ""
            elif not isinstance(ts, str) and not hasattr(ts, "isoformat"):
                ts = str(ts)
            out.append(
                HistoryMessage(
                    autor=autor,  # type: ignore[arg-type]
                    texto=str(texto),
                    timestamp=ts,
                )
            )
        return out

    async def _store(self, turn_id: Any, key: str, value: Any) -> None:
        await self._trace.store(turn_id, key, to_jsonable(value))
