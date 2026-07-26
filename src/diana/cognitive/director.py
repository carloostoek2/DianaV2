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
from uuid import UUID

from diana.cognitive.analyst import Analyst
from diana.cognitive.context_builder import ContextBuilder
from diana.cognitive.decider import Decider
from diana.cognitive.evaluator import Evaluator
from diana.cognitive.generator import Generator
from diana.cognitive.timing import TimingContext
from diana.cognitive.models import (
    AnalystInput,
    Decision,
    EvaluationProfile,
    EvaluatorInput,
    HistoryMessage,
    IncomingTurn,
    TurnStatus,
)
from diana.cognitive.repetition_guard import RepetitionGuard
from diana.cognitive.planner import Planner
from diana.cognitive.ports import (
    MessageHistoryPort,
    NoOpTurnStatusSink,
    RecentIntentsPort,
    TraceStore,
    TurnStatusSink,
    to_jsonable,
)
from diana.cognitive.registry import CapabilityRegistry
from diana.cognitive.thresholds import DEFAULT_SUPERVISED_THRESHOLDS

# Short Analyst window (contrato A.2 recommends 5–10). Registry retrieval stays at 20.
ANALYST_HISTORY_LIMIT = 8

# Port/DB role vocabulary → contract autor (bot and unknown roles are excluded).
_ROLE_TO_AUTOR: dict[str, str] = {
    "vip": "vip",
    "owner": "dueña",
}

def _early_exit_evaluation() -> EvaluationProfile:
    """Fresh zero profile for Decision-only early exits (reason is source of truth)."""
    return EvaluationProfile(
        naturalness=0.0,
        precision=0.0,
        doctrine=0.0,
        consistency=0.0,
        safety=0.0,
        coverage=0.0,
        empathy=0.0,
    )


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
        style_rules: list[str] | None = None,
        recent_intents: RecentIntentsPort | None = None,
        repetition_guard: RepetitionGuard | None = None,
        # Supervised naturalness redraft min; not autonomous send gate.
        naturalness_min: float | None = None,
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
        self._style_rules = style_rules
        self._history = history
        self._analyst_history_limit = analyst_history_limit
        self._status = status_sink or NoOpTurnStatusSink()
        self._recent_intents = recent_intents
        self._repetition_guard = repetition_guard
        self._naturalness_min = (
            float(DEFAULT_SUPERVISED_THRESHOLDS["naturalness_min"])
            if naturalness_min is None
            else float(naturalness_min)
        )

    async def handle_turn(self, turn_context: IncomingTurn) -> Decision:
        """Run the F1 cognitive pipeline for one inbound turn.

        Args:
            turn_context: Fully formed ``IncomingTurn`` with ``turn_id`` already
                assigned by the application layer (item 3+).

        Returns:
            ``Decision`` with ``action`` in {approve, escalate} and non-empty
            ``draft_text`` from a successful Generator return.

        On unexpected errors the status sink receives ``TurnStatus.FAILED`` and
        the exception is re-raised. Partial artifacts already stored remain in
        the TraceStore for reconstructability. On Analyst schema failure no
        comprehension or plan is stored. On Evaluator schema failure no
        evaluation or decision is stored. On Generator empty fail no
        ``generated_text`` / evaluation / decision is stored.
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
        timings: dict[str, float] = {}

        await self._status.transition(turn_id, TurnStatus.ANALYZING)
        analyst_input = await self._build_analyst_input(turn)
        # On AnalystSchemaInvalidError: do not store partial comprehension; re-raise.
        with TimingContext("analyst") as tc:
            comprehension = await self._analyst.analyze(analyst_input)
        timings["analyst_ms"] = tc.elapsed_ms
        await self._store(turn_id, "comprehension", comprehension)

        # H4: 3+ consecutive same intent → Decision-only escalate (no Planner+).
        if self._recent_intents is not None and self._repetition_guard is not None:
            recent = await self._recent_intents.get_recent_intents(
                turn.chat_id,
                limit=max(self._repetition_guard.threshold - 1, 0),
                exclude_turn_id=turn.turn_id,
            )
            if self._repetition_guard.is_repeated(comprehension.intent, recent):
                decision = Decision(
                    action="escalate",
                    reason="pregunta_repetida",
                    evaluation=_early_exit_evaluation(),
                    draft_text=None,
                    mode_restriction_applied=None,
                )
                await self._store(turn_id, "decision", decision)
                return decision

        await self._status.transition(turn_id, TurnStatus.PLANNING)
        with TimingContext("planner") as tc:
            plan = self._planner.plan(comprehension)
        timings["planner_ms"] = tc.elapsed_ms
        await self._store(turn_id, "plan", plan)

        await self._status.transition(turn_id, TurnStatus.RETRIEVING)
        retrieved: dict[str, Any | None] = {}
        retriever_timings: dict[str, float] = {}
        try:
            for cap in plan.capabilities:
                retriever = self._registry.resolve(cap)
                with TimingContext(cap) as tc:
                    retrieved[cap] = await retriever.fetch(turn, comprehension)
                retriever_timings[cap] = tc.elapsed_ms
        finally:
            # Persist the retrieved map unconditionally — even an empty dict
            # signals "retrieval ran with no capabilities" vs "retrieval had
            # a pre-loop exception" (in which case the turn is failed anyway).
            await self._store(turn_id, "retrieved", retrieved)

        # Aggregate retriever timings by type (only when no exception occurred).
        if retriever_timings:
            memory_ms = 0.0
            policy_ms = 0.0
            examples_ms = 0.0
            persona_facts_ms = 0.0
            voice_patterns_ms = 0.0
            for cap, elapsed in retriever_timings.items():
                if "memory" in cap:
                    memory_ms += elapsed
                elif "policy" in cap:
                    policy_ms += elapsed
                elif "examples" in cap:
                    examples_ms += elapsed
                elif "persona_facts" in cap:
                    persona_facts_ms += elapsed
                elif "voice_patterns" in cap:
                    voice_patterns_ms += elapsed
            timings["memory_retriever_ms"] = memory_ms
            timings["policy_retriever_ms"] = policy_ms
            timings["examples_retriever_ms"] = examples_ms
            timings["persona_facts_ms"] = persona_facts_ms
            timings["voice_patterns_ms"] = voice_patterns_ms

        await self._status.transition(turn_id, TurnStatus.BUILDING_CONTEXT)
        # Dual BuiltContext: single assembly pass for Generator + Evaluator (Anexo D).
        # On ContextExceedsLimitError: do not store partial prompt_text; re-raise.
        with TimingContext("context_builder") as tc:
            built = self._context_builder.build(
                turn,
                comprehension,
                knowledge=retrieved,
                persona=self._persona,
                style_rules=self._style_rules,
            )
        timings["context_builder_ms"] = tc.elapsed_ms
        await self._store(turn_id, "prompt_text", built.prompt_final)

        await self._status.transition(turn_id, TurnStatus.GENERATING)
        # On GeneratorEmptyOutputError: do not store generated_text/evaluation/decision.
        with TimingContext("generator") as tc:
            draft = await self._generator.generate(built.prompt_final)
        timings["generator_ms"] = tc.elapsed_ms
        await self._store(turn_id, "generated_text", draft)

        await self._status.transition(turn_id, TurnStatus.EVALUATING)
        # On EvaluatorSchemaInvalidError: do not store synthetic evaluation/decision.
        with TimingContext("evaluator") as tc:
            evaluation = await self._evaluator.evaluate(
                EvaluatorInput(
                    draft=draft,
                    comprehension=comprehension,
                    included_blocks=built.included_blocks,
                    current_turn=turn.text,
                )
            )
        timings["evaluator_ms"] = tc.elapsed_ms
        await self._store(turn_id, "evaluation", evaluation)

        # Naturalness 1× redraft (Director pre-Decider): same prompt_final only.
        # Exactly once — boolean gate, never a while/retry loop or Decider action.
        if evaluation.naturalness < self._naturalness_min:
            await self._status.transition(turn_id, TurnStatus.GENERATING)
            with TimingContext("generator_redraft") as tc:
                draft = await self._generator.generate(built.prompt_final)
            timings["generator_redraft_ms"] = tc.elapsed_ms
            # Store second draft only after second eval succeeds (paired artifacts).

            await self._status.transition(turn_id, TurnStatus.EVALUATING)
            with TimingContext("evaluator_redraft") as tc:
                evaluation = await self._evaluator.evaluate(
                    EvaluatorInput(
                        draft=draft,
                        comprehension=comprehension,
                        included_blocks=built.included_blocks,
                        current_turn=turn.text,
                    )
                )
            timings["evaluator_redraft_ms"] = tc.elapsed_ms
            await self._store(turn_id, "generated_text", draft)
            await self._store(turn_id, "evaluation", evaluation)
            timings["naturalness_redraft"] = 1.0

        await self._status.transition(turn_id, TurnStatus.DECIDING)
        # Generator guarantees non-empty draft on success; Decider owns action choice.
        with TimingContext("decider") as tc:
            base = self._decider.decide(
                evaluation,
                comprehension,
                retrieved=retrieved,
                mode="supervised",
            )
            decision = Decision(
                action=base.action,
                reason=base.reason,
                evaluation=base.evaluation,
                draft_text=draft,
                mode_restriction_applied=base.mode_restriction_applied,
            )
        timings["decider_ms"] = tc.elapsed_ms
        await self._store(turn_id, "decision", decision)

        # Sum only duration keys (*_ms); exclude audit flags like naturalness_redraft.
        timings["total_ms"] = sum(
            v for k, v in timings.items() if k.endswith("_ms")
        )
        await self._store(turn_id, "timings", timings)
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

    async def _store(self, turn_id: UUID, key: str, value: Any) -> None:
        await self._trace.store(turn_id, key, to_jsonable(value))
