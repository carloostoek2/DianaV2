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

import logging
import random
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from diana.cognitive.album_collapse import collapse_album_runs
from diana.cognitive.analyst import Analyst
from diana.cognitive.context_builder import ContextBuilder
from diana.cognitive.decider import Decider
from diana.cognitive.evaluator import Evaluator
from diana.cognitive.generator import Generator
from diana.cognitive.timing import TimingContext
from diana.cognitive.models import (
    AnalystInput,
    Comprehension,
    Decision,
    EvaluationProfile,
    EvaluatorInput,
    HistoryMessage,
    IncomingTurn,
    TurnStatus,
)
from diana.profile_content import normalize_content
from diana.cognitive.exceptions import TurnSupersededError
from diana.cognitive.repetition_guard import RepetitionGuard
from diana.cognitive.tags import (
    catalog_fact_topics,
    catalog_pattern_tags,
    catalog_policy_topics,
)
from diana.cognitive.template_gate import (
    TemplateGate,
    TemplateRule,
    PhaticLightContext,
    checkin_reason_for,
    detect_phatic_subtype,
    pick_checkin_reply,
)
from diana.cognitive.persona_semantic import build_shadow_snapshot
from diana.cognitive.planner import Planner

from diana.cognitive.ports import (
    KnowledgeAugmenter,
    MessageHistoryPort,
    NoOpTurnStatusSink,
    PersonaCatalogProvider,
    CheckinCutPort,
    PhaticContextPort,
    PureGreetingCutPort,
    RecentIntentsPort,
    TraceStore,
    TurnStatusSink,
    to_jsonable,
)
from diana.cognitive.registry import CapabilityRegistry
from diana.cognitive.thresholds import DEFAULT_SUPERVISED_THRESHOLDS

# Short Analyst window (contrato A.2 recommends 5–10). Registry retrieval stays at 20.
ANALYST_HISTORY_LIMIT = 8

# Naturalness redraft reminder. Appended to ``prompt_final`` when the first
# draft scored below threshold. Phrased in Spanish to match the persona's chat
# register. The marker ``--- REDRAFT ---`` makes the LLM branch treat the second
# call as a deliberate remediation rather than a re-roll, and gives the
# Generator concrete knobs (length, muletillas, warmth) to re-aim at.
_REDRAFT_REMINDER = (
    "\n\n--- REDRAFT ---\n"
    "Tu respuesta anterior fue marcada como poco natural (naturalness baja). "
    "Reescríbela como mensaje real de chat: tono casual, 2-3 líneas como máximo, "
    "alguna muletilla natural de Diana si el tono lo permite (jsjs, o sea, pues, "
    "ayyy), calidez real sin sonar a asistente. Mantén el contenido semántico "
    "— solo cambia el cómo, no el qué."
)

# Port/DB role vocabulary → contract autor (bot and unknown roles are excluded).
_ROLE_TO_AUTOR: dict[str, str] = {
    "vip": "vip",
    "owner": "dueña",
}

# Channel-aware fallback for an atencion turn when the live catalog is
# unavailable (missing/corrupt static file AND no active DB row) or the
# ``voz_configurada`` slice is incomplete. The neutral service voice keeps the
# channel-isolation invariant on the failure path — an atencion customer must
# never resolve the boot VIP persona (FIX-R2-7).
_NEUTRAL_ATENCION_PERSONA = (
    "Eres la asistente de atención al cliente de este negocio. "
    "Responde con tono profesional, amable y servicial."
)
_NEUTRAL_ATENCION_STYLE_RULES: list[str] = []

logger = logging.getLogger("diana.cognitive")

_OPERACION_CAPABILITY = "knowledge.operacion"

_DECISION_EMOJI: dict[str, str] = {
    "approve": "✅",
    "escalate": "🚨",
    "send": "📤",
    "consult_doctrine": "📚",
}

_DECISION_VERB: dict[str, str] = {
    "approve": "aprobar",
    "escalate": "escalar",
    "send": "enviar",
    "consult_doctrine": "consultar doctrina",
}


def _merge_knowledge_overrides(
    retrieved: dict[str, Any | None],
    overrides: Mapping[str, Any],
) -> dict[str, Any | None]:
    """Merge application force-injects into retrieved knowledge.

    For ``knowledge.policy``: if existing value is a list, prepend override
    entry/entries; otherwise replace with the override list/dict.
    For ``knowledge.ephemeral``: shallow-merge dicts so a regen hint does not
    wipe active ephemeral events (and vice versa); ``eventos`` lists concat
    with override entries first.
    Other keys: replace when override is present and non-empty.
    """
    out: dict[str, Any | None] = dict(retrieved)
    for key, value in overrides.items():
        if value is None or value == [] or value == {}:
            continue
        if key == "knowledge.policy":
            existing = out.get(key)
            override_list = value if isinstance(value, list) else [value]
            if isinstance(existing, list):
                out[key] = list(override_list) + list(existing)
            else:
                out[key] = list(override_list)
        elif key == "knowledge.ephemeral":
            existing = out.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                merged = dict(existing)
                merged.update(value)
                ex_ev = existing.get("eventos")
                ov_ev = value.get("eventos")
                if isinstance(ex_ev, list) or isinstance(ov_ev, list):
                    left = list(ov_ev) if isinstance(ov_ev, list) else []
                    right = list(ex_ev) if isinstance(ex_ev, list) else []
                    merged["eventos"] = left + right
                out[key] = merged
            else:
                out[key] = value
        else:
            out[key] = value
    return out


def _clip(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _pct(score: float) -> str:
    return f"{score * 100:.0f}%"


def _build_redraft_prompt(prompt_final: str, naturalness_min: float) -> str:
    """Return a variant prompt for the 1× naturalness redraft.

    Keeps the original ``prompt_final`` (persona + knowledge + comprehension +
    current VIP message) and appends a concrete remediation hint so the second
    generation differs from the first. The threshold value is mentioned in the
    reminder so the LLM has a numeric anchor (currently a static phrase; we
    interpolate ``naturalness_min`` for future tunability).
    """
    return (
        prompt_final
        + _REDRAFT_REMINDER.replace(
            "naturalness baja", f"naturalness < {naturalness_min:.2f}"
        )
    )


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
        template_gate: TemplateGate | None = None,
        # Post-Analyst pure-greeting cut (injected; no cognitive→application import).
        pure_greeting_cut: PureGreetingCutPort | None = None,
        saludo_response_pool: Sequence[str] | None = None,
        saludo_rng: Any = random,
        # When True, pure-greeting / check-in cuts emit action=send; else approve.
        # Injected bool — never import Settings inside cognitive.
        phatic_auto_send: bool = False,
        # Post-Analyst check-in cut (bienestar/dia pools; optional light context).
        checkin_cut: CheckinCutPort | None = None,
        phatic_context_provider: PhaticContextPort | None = None,
        # Supervised naturalness redraft min; not autonomous send gate.
        naturalness_min: float | None = None,
        knowledge_augmenter: KnowledgeAugmenter | None = None,
        persona_catalog_provider: PersonaCatalogProvider | None = None,
        # Option A: OR needs_profile when VIP has non-empty owner notes.
        # Injected bool — never import Settings inside cognitive.
        force_profile_when_notes: bool = False,
        # Duck-typed ProfilesRepo (get_by_vip_id). None → force is a no-op.
        profiles_repo: Any | None = None,
        # FEATURE_PERSONA_OPERACION_ENABLED: deterministic alias match →
        # knowledge.operacion. Injected bool — never import Settings here.
        # False → pipeline (and prompt) byte-identical to the pre-feature path.
        feature_persona_operacion_enabled: bool = False,
        # FEATURE_PERSONA_SEMANTIC_SHADOW (SHADOW — only measures): duck-typed
        # PersonaSemanticShadow; gets a snapshot of strings after retrieval and
        # runs in background. None (default) → no hook at all.
        persona_semantic_shadow: Any | None = None,
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
        self._persona_catalog_provider = persona_catalog_provider
        self._history = history
        self._analyst_history_limit = analyst_history_limit
        self._status = status_sink or NoOpTurnStatusSink()
        self._recent_intents = recent_intents
        self._repetition_guard = repetition_guard
        self._template_gate = template_gate
        self._pure_greeting_cut = pure_greeting_cut
        self._saludo_response_pool = saludo_response_pool
        self._saludo_rng = saludo_rng
        self._phatic_auto_send = bool(phatic_auto_send)
        self._checkin_cut = checkin_cut
        self._phatic_context_provider = phatic_context_provider
        self._naturalness_min = (
            float(DEFAULT_SUPERVISED_THRESHOLDS["naturalness_min"])
            if naturalness_min is None
            else float(naturalness_min)
        )
        self._knowledge_augmenter = knowledge_augmenter
        self._force_profile_when_notes = bool(force_profile_when_notes)
        self._profiles_repo = profiles_repo
        self._feature_persona_operacion_enabled = bool(
            feature_persona_operacion_enabled
        )
        self._persona_semantic_shadow = persona_semantic_shadow

    async def _resolve_persona(
        self, channel_type: str = "vip"
    ) -> tuple[str, list[str] | None]:
        """Resolve persona + style rules for this turn (live catalog when available).

        The channel (``vip`` | ``atencion``) scopes which catalog the provider
        resolves, so the non-VIP service persona never leaks into the VIP flow
        (and vice versa). Falls back to the boot-time ``persona`` /
        ``style_rules`` when no provider is wired or the provider reports no
        live catalog — **except** on the atencion channel, which falls back to
        the neutral service voice instead (an atencion customer must never
        resolve the boot VIP persona, even on the failure path).

        Note: under a concurrent owner save the catalog snapshot may vary
        intra-turn (retrievers refresh before this resolves). That is
        inherent to hot-reload; the next turn is always consistent.
        """
        if self._persona_catalog_provider is None:
            if channel_type == "atencion":
                return _NEUTRAL_ATENCION_PERSONA, _NEUTRAL_ATENCION_STYLE_RULES
            return self._persona, self._style_rules
        catalog = await self._persona_catalog_provider.get_catalog(channel_type)
        if catalog is None:
            if channel_type == "atencion":
                logger.warning(
                    "persona_atencion_catalog_unavailable_fallback_neutral",
                    extra={"channel_type": channel_type},
                )
                return _NEUTRAL_ATENCION_PERSONA, _NEUTRAL_ATENCION_STYLE_RULES
            return self._persona, self._style_rules
        voz = catalog.get("voz_configurada") or {}
        if channel_type == "atencion":
            persona = str(voz.get("persona") or _NEUTRAL_ATENCION_PERSONA)
            rules = voz.get("reglas_estilo")
            style_rules = (
                list(rules)
                if isinstance(rules, list) and rules
                else _NEUTRAL_ATENCION_STYLE_RULES
            )
        else:
            persona = str(voz.get("persona") or self._persona)
            rules = voz.get("reglas_estilo")
            style_rules = list(rules) if isinstance(rules, list) and rules else self._style_rules
        return persona, style_rules

    async def handle_turn(
        self,
        turn_context: IncomingTurn,
        *,
        knowledge_overrides: Mapping[str, Any] | None = None,
        skip_repetition_guard: bool = False,
    ) -> Decision:
        """Run the F1 cognitive pipeline for one inbound turn.

        Args:
            turn_context: Fully formed ``IncomingTurn`` with ``turn_id`` already
                assigned by the application layer (item 3+).
            knowledge_overrides: Optional map merged into ``retrieved`` AFTER
                retrievers + KnowledgeAugmenter (application-owned force-inject,
                e.g. gray-zone live rule → ``knowledge.policy``). Decider still
                owns the action after inject.
            skip_repetition_guard: Sanctioned exception (owner false-positive
                resume, AGENTS §4.21): the H4 repetition short-circuit is
                bypassed so a turn the owner already triaged as a false
                positive gets a draft instead of escalating again on the same
                repeated intent. Default False keeps every other caller's
                behavior byte-identical.

        Returns:
            ``Decision`` with ``action`` in {approve, escalate} and non-empty
            ``draft_text`` from a successful Generator return (or a TemplateGate
            draft on H6 short-circuit).

        On unexpected errors the status sink receives ``TurnStatus.FAILED`` and
        the exception is re-raised. Partial artifacts already stored remain in
        the TraceStore for reconstructability. On Analyst schema failure no
        comprehension or plan is stored. On Evaluator schema failure no
        evaluation or decision is stored. On Generator empty fail no
        ``generated_text`` / evaluation / decision is stored.
        """
        turn = turn_context
        turn_id = turn.turn_id
        logger.info(
            '📥 Turno recibido — chat %s | "%s"',
            turn.chat_id,
            _clip(turn.text),
        )
        try:
            gate = self._template_gate
            if gate is not None:
                rule = gate.match(turn.text)
                if rule is not None:
                    return await self._handle_template(turn, rule, gate)
            return await self._run_pipeline(
                turn,
                knowledge_overrides=knowledge_overrides,
                skip_repetition_guard=skip_repetition_guard,
            )
        except TurnSupersededError:
            raise
        except Exception as exc:
            await self._status.transition(turn_id, TurnStatus.FAILED)
            logger.exception(
                "❌ Turno %s falló — chat %s: %s",
                str(turn_id)[:8],
                turn.chat_id,
                type(exc).__name__,
            )
            raise

    async def _handle_template(
        self,
        turn: IncomingTurn,
        rule: TemplateRule,
        gate: TemplateGate,
    ) -> Decision:
        """H6 pre-pipeline: synthetic approve Decision from fixed template (0 LLM)."""
        logger.info("⚡ Plantilla H6 — regla %s (%s)", rule.id, rule.reason)
        text = gate.render(rule)
        decision = Decision(
            action="approve",
            reason=rule.reason,
            evaluation=_early_exit_evaluation(),
            draft_text=text,
            mode_restriction_applied=None,
        )
        # Mirror pipeline: /traza Draft line reads generated_text.
        await self._store(turn.turn_id, "generated_text", text)
        await self._store(turn.turn_id, "decision", decision)
        return decision



    async def _run_pipeline(
        self,
        turn: IncomingTurn,
        *,
        knowledge_overrides: Mapping[str, Any] | None = None,
        skip_repetition_guard: bool = False,
    ) -> Decision:
        turn_id = turn.turn_id
        timings: dict[str, float] = {}

        await self._status.transition(turn_id, TurnStatus.ANALYZING)
        analyst_input = await self._build_analyst_input(turn)
        # On AnalystSchemaInvalidError: do not store partial comprehension; re-raise.
        with TimingContext("analyst") as tc:
            comprehension = await self._analyst.analyze(analyst_input)
        timings["analyst_ms"] = tc.elapsed_ms
        # Option A: hard-OR needs_profile when VIP has non-empty notes[]
        # (before store/plan so Planner 1:1 and traces stay honest).
        comprehension = await self._maybe_force_needs_profile(turn, comprehension)
        # Operación: deterministic alias n-gram match on the turn text (never
        # the Analyst). Same precedent as needs_profile_forced: OR the flag
        # before store/plan so the Planner stays 1:1 and the trace is honest.
        comprehension, operacion_hits = await self._maybe_force_operacion(
            turn, comprehension
        )
        await self._store(turn_id, "comprehension", comprehension)
        # operacion_match is traced right before EVERY exit below (early exits
        # never inject; see _store_operacion_match).
        logger.info(
            "🧠 Comprensión — intent: %s | emoción: %s | urgencia: %s | riesgo: %s",
            comprehension.intent,
            comprehension.emotion,
            comprehension.urgency,
            comprehension.risk,
        )

        # Post-Analyst pure-greeting cut: pool draft; send when phatic_auto_send.
        # Prefer before H4 so pure saludo never escalates as pregunta_repetida.
        if (
            self._pure_greeting_cut is not None
            and self._saludo_response_pool
        ):
            if self._pure_greeting_cut(turn.text, comprehension):
                # Whitespace-only entries do not count — fail open to full pipeline.
                pool = [t for t in self._saludo_response_pool if t and str(t).strip()]
                if pool:
                    draft = self._saludo_rng.choice(pool)
                    action = "send" if self._phatic_auto_send else "approve"
                    logger.info(
                        "⚡ Plantilla saludo post-Analyst — plantilla_saludo action=%s",
                        action,
                    )
                    decision = Decision(
                        action=action,
                        reason="plantilla_saludo",
                        evaluation=_early_exit_evaluation(),
                        draft_text=draft,
                        mode_restriction_applied=None,
                    )
                    await self._store(turn_id, "generated_text", draft)
                    await self._store(turn_id, "decision", decision)
                    await self._store_operacion_match(turn, operacion_hits, injected=False)
                    return decision

        # Post-Analyst check-in cut: pools + light context; send when phatic_auto_send.
        # Runs only when pure-greeting cut did not fire. Never Holis pool.
        if self._checkin_cut is not None:
            if self._checkin_cut(turn.text, comprehension):
                subtype = detect_phatic_subtype(turn.text) or "checkin_bienestar"
                if subtype.startswith("checkin_"):
                    ctx = PhaticLightContext()
                    provider = self._phatic_context_provider
                    if provider is not None:
                        try:
                            got = await provider.get(turn)
                            if isinstance(got, PhaticLightContext):
                                ctx = got
                        except Exception:
                            logger.exception(
                                "phatic_context_provider_failed — fail-soft empty context"
                            )
                            ctx = PhaticLightContext()
                    draft = pick_checkin_reply(
                        subtype,
                        context=ctx,
                        rng=self._saludo_rng,
                    )
                    if draft and str(draft).strip():
                        action = "send" if self._phatic_auto_send else "approve"
                        reason = checkin_reason_for(subtype)
                        logger.info(
                            "⚡ Plantilla check-in post-Analyst — %s subtype=%s action=%s",
                            reason,
                            subtype,
                            action,
                        )
                        decision = Decision(
                            action=action,
                            reason=reason,
                            evaluation=_early_exit_evaluation(),
                            draft_text=draft,
                            mode_restriction_applied=None,
                        )
                        await self._store(turn_id, "generated_text", draft)
                        await self._store(turn_id, "decision", decision)
                        await self._store_operacion_match(turn, operacion_hits, injected=False)
                        return decision

        # H4: 3+ consecutive same intent → Decision-only escalate (no Planner+).
        # Skipped only for the owner false-positive resume: she already triaged
        # this escalation as a false positive, so the repeated intent must not
        # escalate again (AGENTS §4.21).
        if skip_repetition_guard:
            logger.info(
                "repetition_guard_skipped_by_caller",
                extra={"turn_id": str(turn_id), "chat_id": turn.chat_id},
            )
        if (
            not skip_repetition_guard
            and self._recent_intents is not None
            and self._repetition_guard is not None
        ):
            recent = await self._recent_intents.get_recent_intents(
                turn.chat_id,
                limit=max(self._repetition_guard.threshold - 1, 0),
                exclude_turn_id=turn.turn_id,
            )
            if self._repetition_guard.is_repeated(comprehension.intent, recent):
                logger.info(
                    "🔁 Repetición — intent: %s → escalar (pregunta_repetida)",
                    comprehension.intent,
                )
                decision = Decision(
                    action="escalate",
                    reason="pregunta_repetida",
                    evaluation=_early_exit_evaluation(),
                    draft_text=None,
                    mode_restriction_applied=None,
                )
                await self._store(turn_id, "decision", decision)
                await self._store_operacion_match(turn, operacion_hits, injected=False)
                return decision

        await self._status.transition(turn_id, TurnStatus.PLANNING)
        with TimingContext("planner") as tc:
            plan = self._planner.plan(comprehension)
        timings["planner_ms"] = tc.elapsed_ms
        await self._store(turn_id, "plan", plan)
        logger.info("🗺️ Plan — capacidades: %s", ", ".join(plan.capabilities))
        # Retrieval injects the trigger's hits only when the plan asks for
        # knowledge.operacion (Planner 1:1 with needs_operacion): trace exactly that.
        await self._store_operacion_match(
            turn, operacion_hits, injected=_OPERACION_CAPABILITY in plan.capabilities
        )

        await self._status.transition(turn_id, TurnStatus.RETRIEVING)
        retrieved: dict[str, Any | None] = {}
        retriever_timings: dict[str, float] = {}
        try:
            for cap in plan.capabilities:
                if cap == _OPERACION_CAPABILITY:
                    # Inject exactly what the trigger matched (and traced) —
                    # no second catalog read that could diverge mid-turn.
                    retrieved[cap] = (
                        [{"hecho": hit.hecho} for hit in operacion_hits]
                        if operacion_hits
                        else None
                    )
                    continue
                retriever = self._registry.resolve(cap)
                with TimingContext(cap) as tc:
                    retrieved[cap] = await retriever.fetch(turn, comprehension)
                retriever_timings[cap] = tc.elapsed_ms
        finally:
            # Persist the retrieved map unconditionally — even an empty dict
            # signals "retrieval ran with no capabilities" vs "retrieval had
            # a pre-loop exception" (in which case the turn is failed anyway).
            await self._store(turn_id, "retrieved", retrieved)

        # SHADOW (E1): fire-and-forget; the turn never awaits nor reads it and
        # nothing it does can change the prompt, retrieved map or trace.
        if self._persona_semantic_shadow is not None:
            try:
                self._persona_semantic_shadow.schedule(
                    build_shadow_snapshot(turn, retrieved, operacion_hits)
                )
            except Exception:
                logger.warning("persona_semantic_shadow_schedule_failed", exc_info=True)

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

        if self._knowledge_augmenter is not None:
            retrieved = await self._knowledge_augmenter.augment_retrieved(
                turn, retrieved
            )
            await self._store(turn_id, "retrieved", retrieved)

        if knowledge_overrides:
            retrieved = _merge_knowledge_overrides(retrieved, knowledge_overrides)
            await self._store(turn_id, "retrieved", retrieved)

        hit_caps = [cap for cap, value in retrieved.items() if value]
        logger.info(
            "🔎 Retrieval — hits %d/%d (%s)",
            len(hit_caps),
            len(retrieved),
            ", ".join(hit_caps) if hit_caps else "ninguna",
        )

        await self._status.transition(turn_id, TurnStatus.BUILDING_CONTEXT)
        # Dual BuiltContext: single assembly pass for Generator + Evaluator (Anexo D).
        # On ContextExceedsLimitError: do not store partial prompt_text; re-raise.
        persona, style_rules = await self._resolve_persona(turn.channel_type)
        with TimingContext("context_builder") as tc:
            built = self._context_builder.build(
                turn,
                comprehension,
                knowledge=retrieved,
                persona=persona,
                style_rules=style_rules,
            )
        timings["context_builder_ms"] = tc.elapsed_ms
        await self._store(turn_id, "prompt_text", built.prompt_final)
        # Essential knowledge evidence (policy/memory/profile, fenced) for the
        # Evaluator. Rendered once from the same retrieved map that fed the
        # Generator; reused by the naturalness redraft re-evaluation.
        eval_knowledge = self._context_builder.render_knowledge_sections(retrieved)

        await self._status.transition(turn_id, TurnStatus.GENERATING)
        # On GeneratorEmptyOutputError: do not store generated_text/evaluation/decision.
        with TimingContext("generator") as tc:
            draft = await self._generator.generate(built.prompt_final)
        timings["generator_ms"] = tc.elapsed_ms
        await self._store(turn_id, "generated_text", draft)
        logger.info("✍️ Borrador — %d caracteres", len(draft))

        await self._status.transition(turn_id, TurnStatus.EVALUATING)
        # On EvaluatorSchemaInvalidError: do not store synthetic evaluation/decision.
        with TimingContext("evaluator") as tc:
            evaluation = await self._evaluator.evaluate(
                EvaluatorInput(
                    draft=draft,
                    comprehension=comprehension,
                    included_blocks=built.included_blocks,
                    current_turn=turn.text,
                    knowledge_content=eval_knowledge,
                )
            )
        timings["evaluator_ms"] = tc.elapsed_ms
        await self._store(turn_id, "evaluation", evaluation)
        logger.info(
            "📊 Evaluación — naturalness %s | safety %s | doctrine %s | coverage %s | empathy %s",
            _pct(evaluation.naturalness),
            _pct(evaluation.safety),
            _pct(evaluation.doctrine),
            _pct(evaluation.coverage),
            _pct(evaluation.empathy),
        )

        # Naturalness 1× redraft (Director pre-Decider).
        # Same persona + knowledge + comprehension as the first attempt, plus a
        # concrete remediation hint so the second generation is not byte-identical
        # to the first (which would just re-roll the same robotic output at
        # temperature=0.7). Exactly once — boolean gate, never a while/retry loop
        # or Decider action.
        if evaluation.naturalness < self._naturalness_min:
            old_naturalness = evaluation.naturalness
            await self._status.transition(turn_id, TurnStatus.GENERATING)
            redraft_prompt = _build_redraft_prompt(
                built.prompt_final, self._naturalness_min
            )
            with TimingContext("generator_redraft") as tc:
                draft = await self._generator.generate(redraft_prompt)
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
                        knowledge_content=eval_knowledge,
                    )
                )
            timings["evaluator_redraft_ms"] = tc.elapsed_ms
            await self._store(turn_id, "generated_text", draft)
            await self._store(turn_id, "evaluation", evaluation)
            timings["naturalness_redraft"] = 1.0
            logger.info(
                "🎨 Redraft — naturalness %s → %s",
                _pct(old_naturalness),
                _pct(evaluation.naturalness),
            )

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
        emoji = _DECISION_EMOJI.get(decision.action, "➡️")
        verb = _DECISION_VERB.get(decision.action, decision.action)
        logger.info(
            "%s Decisión para chat %s: %s (%s) | %sms",
            emoji,
            turn.chat_id,
            verb,
            decision.reason,
            round(timings.get("total_ms", 0)),
        )
        return decision

    async def _build_analyst_input(self, turn: IncomingTurn) -> AnalystInput:
        """Fetch chat-scoped history and map to contract historial_reciente (R1).

        - Over-fetches raw rows so bot/unknown filtering still yields up to
          ``analyst_history_limit`` vip/dueña lines when available.
        - Excludes the open trailing VIP burst (consecutive role=vip at the tail
          after the last owner/bot line). Orchestrator coalesces that burst into
          ``turno_actual`` so it must not also appear in historial.
        """
        limit = self._analyst_history_limit
        # Oversample raw rows; filter roles; then trim to limit human messages.
        # Bot-heavy tails need headroom beyond limit (A.2 short window is human lines).
        fetch_limit = max(limit * 8, 32) if limit > 0 else 0
        raw = await self._history.get_recent(turn.chat_id, limit=fetch_limit)
        # An album is N rows in the database but one line for the model: without
        # this, a 30-photo album would eat the whole short window.
        raw = collapse_album_runs(raw)
        raw = self._drop_open_vip_burst(raw)
        mapped = self._map_history_messages(raw)
        if limit > 0 and len(mapped) > limit:
            mapped = mapped[-limit:]
        fact_topics, policy_topics, voice_tags = await self._catalog_vocabulary(
            turn.channel_type
        )
        return AnalystInput(
            turno_actual=turn.text,
            historial_reciente=mapped,
            channel_type=turn.channel_type,
            catalog_topics=fact_topics,
            policy_topics=policy_topics,
            voice_tags=voice_tags,
        )

    async def _catalog_vocabulary(
        self, channel_type: str
    ) -> tuple[list[str], list[str], list[str]]:
        """Normalized Analyst vocabulary of the ACTIVE catalog for the channel.

        Returns ``(fact_topics, policy_topics, voice_tags)`` derived from ONE
        ``get_catalog(channel_type)`` read, so all three blocks always come
        from the same channel (VIP/atencion isolation). Fail-soft: no provider
        / read failure → three empty lists (Analyst keeps the fixed
        vocabulary, i.e. the pre-change behavior). The provider is cached
        (0 DB reads in steady state), so this adds no per-turn query.
        """
        if self._persona_catalog_provider is None:
            return [], [], []
        try:
            catalog = await self._persona_catalog_provider.get_catalog(channel_type)
        except Exception:
            logger.warning(
                "analyst_catalog_topics_unavailable",
                extra={"channel_type": channel_type},
                exc_info=True,
            )
            return [], [], []
        # Uncapped here: the 60-term prompt budget is split fairly per type
        # by the Analyst (tags.fair_share_limits), so the log sees real sizes.
        return (
            catalog_fact_topics(catalog, limit=None),
            catalog_policy_topics(catalog),
            catalog_pattern_tags(catalog),
        )

    @staticmethod
    def _drop_open_vip_burst(raw: list[dict]) -> list[dict]:
        """Remove trailing consecutive VIP rows (open burst already in turno_actual)."""
        if not raw:
            return raw
        i = len(raw) - 1
        while i >= 0:
            row = raw[i]
            if isinstance(row, dict) and row.get("role") == "vip":
                i -= 1
                continue
            break
        if i == len(raw) - 1:
            return list(raw)
        return list(raw[: i + 1])

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

    async def _maybe_force_needs_profile(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> Comprehension:
        """OR ``needs_profile=True`` when VIP has non-empty owner notes.

        Trigger is ONLY ``profiles.content.notes`` after ``normalize_content``
        (``len(notes) > 0``). Facts alone, síntesis alone, or hollow content
        do NOT force. Never clears an Analyst ``True``. ``vip_id is None`` →
        no lookup (BR-15). Feature flag / missing repo → no-op.
        """
        if not self._force_profile_when_notes:
            return comprehension
        if comprehension.needs_profile:
            # Natural Analyst hit — leave needs_profile_forced False so miss
            # rate of the classifier remains measurable.
            return comprehension
        if turn.vip_id is None or self._profiles_repo is None:
            return comprehension
        try:
            row = await self._profiles_repo.get_by_vip_id(turn.vip_id)
        except Exception:
            logger.exception(
                "force_profile_when_notes_lookup_failed",
                extra={"vip_id": str(turn.vip_id)},
            )
            return comprehension
        if not isinstance(row, dict):
            return comprehension
        notes = normalize_content(row.get("content")).get("notes") or []
        if len(notes) == 0:
            return comprehension
        logger.info(
            "📌 needs_profile forzado — VIP con notes[] no vacío (option A)",
        )
        return comprehension.model_copy(
            update={"needs_profile": True, "needs_profile_forced": True}
        )

    async def _maybe_force_operacion(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> tuple[Comprehension, list[Any]]:
        """Set ``needs_operacion`` from a deterministic alias match.

        Flag off → never requested (a stray ``True`` is cleared so the prompt
        stays byte-identical). Flag on → ``needs_operacion = bool(hits)``; the
        retriever reads ONLY the turn channel's live catalog (channel
        isolation is the provider's contract). Fail-soft: any error → no hits.
        """
        if not self._feature_persona_operacion_enabled:
            if comprehension.needs_operacion:
                comprehension = comprehension.model_copy(update={"needs_operacion": False})
            return comprehension, []
        hits: list[Any] = []
        try:
            retriever = self._registry.resolve(_OPERACION_CAPABILITY)
            match = getattr(retriever, "match", None)
            if match is not None:
                hits = list(await match(turn))
        except Exception:
            logger.warning(
                "operacion_match_failed",
                extra={"channel_type": turn.channel_type},
                exc_info=True,
            )
            hits = []
        if hits:
            logger.info(
                "⚙️ Operación — alias: %s",
                ", ".join(f"{h.id}<-{h.alias}" for h in hits),
            )
        if bool(hits) != comprehension.needs_operacion:
            comprehension = comprehension.model_copy(
                update={"needs_operacion": bool(hits)}
            )
        return comprehension, hits

    async def _store_operacion_match(
        self, turn: IncomingTurn, hits: list[Any], *, injected: bool
    ) -> None:
        """Trace ``operacion_match`` honestly; no-op without hits.

        Early exits (saludo / check-in / H4) call it with ``injected=False``
        (``injected_ids == []``); the retrieval path with the ids it really
        injects. In-process trace only: ``SqlTraceStore`` drops keys that are
        not in ``TRACE_KEY_TO_COLUMN``, so this never reaches the database.
        """
        if not hits:
            return
        await self._store(
            turn.turn_id,
            "operacion_match",
            {
                "channel_type": turn.channel_type,
                "matched": [{"id": hit.id, "alias": hit.alias} for hit in hits],
                "injected_ids": [hit.id for hit in hits] if injected else [],
                "injected": injected,
            },
        )

    async def _store(self, turn_id: UUID, key: str, value: Any) -> None:
        await self._trace.store(turn_id, key, to_jsonable(value))
