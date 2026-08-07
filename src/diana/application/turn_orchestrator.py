"""TurnOrchestrator — VIP message use-case wiring (supervised + autonomous send)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from diana.application.admin_service import AdminService
from diana.application.autonomous_mode_service import AutonomousModeService
from diana.application.gray_zone_service import GrayZoneService
from diana.application.memory_extraction_service import (
    _POST_TURN_EXTRACTABLE_STATUSES,  # noqa: PLC2701 — extraction gate, single source (R4)
)
from diana.application.mexico_tz import cdmx_local_date
from diana.application.observability import log_swallowed
from diana.application.mood_engine import MoodEngine, MoodState
from diana.application.owner_history import append_owner_delivery_history
from diana.application.ports import (
    AtencionCycleStore,
    BehaviorDeliverer,
    DeliveryContext,
    DeliveryMode,
    DeliveryResult,
    DeliveryResultWriter,
    EmotionalSignalRecord,
    MessageHistoryWriter,
    RuntimeTimerRecord,
    RuntimeTimerStore,
    TraceReader,
    TurnCategoryLogRecord,
    TurnRecord,
    TurnStore,
    VipInboundMessage,
    VipMoodStateRecord,
    VipStore,
)
from diana.behavior.ports import DelayPolicy
from diana.application.turn_coordinator import TurnCoordinator
from diana.cognitive.exceptions import (
    AnalystSchemaInvalidError,
    ContextExceedsLimitError,
    EvaluatorSchemaInvalidError,
    GeneratorEmptyOutputError,
    TurnSupersededError,
)
from diana.cognitive.models import (
    Decision,
    IncomingTurn,
    TurnStatus,
    is_turn_status_terminal,
)

logger = logging.getLogger("diana.application")

# Open VIP burst: trailing consecutive role=vip lines since last owner/bot reply.
_BURST_HISTORY_LIMIT = 40
_MULTI_VIP_BURST_HEADER = "(el VIP envió varios mensajes seguidos)"

# F4-02: fixed closing reply for the atencion channel when the daily
# client-message limit (20) is reached. Sent best-effort, direct to the
# client chat, never LLM / never supervised. Fixed constant (locked #7).
ATENCION_DAILY_LIMIT_CLOSE = (
    "¡Hola! Por hoy ya cubrimos todo, "
    "si necesitas algo más escríbeme mañana 😊"
)


# A7: exact informational DM text when an atencion turn shows payment intent.
ATENCION_PAYMENT_NOTICE = (
    "Cliente {chat_id} está en proceso de pago / confirmó pago — "
    "entrega manual pendiente"
)

# A2: topics that corroborate a confirmation-of-delivery payment intent.
_PAYMENT_TOPICS = frozenset({"pago", "suscripcion", "contenido"})

# F4: per-chat cooldown for the atencion payment DM (20 min), same TTL as
# the freeze middleware reminders. Bounded dict — pruned on each use.
_PAYMENT_NOTIFY_TTL = timedelta(minutes=20)

# Evo-Agente Fase 3: defensive hard cap for the per-VIP mood-engine cache. The
# cache is structurally bounded — one tiny ``MoodEngine`` fork per VIP and the
# VIP space is the allowlist (bounded cardinality) — so this ceiling is
# defense-in-depth only, mirroring ``_prune_payment_notify`` (review round 2).
_VIP_MOOD_ENGINE_CACHE_MAX = 1024


def _detect_payment_intent(trace: dict | None) -> bool:
    """Deterministic payment-intent detection from the committed pipeline trace.

    Primary signal: the activated knowledge policy contains
    ``Trigger: datos_pago``. The production shape of ``knowledge.policy`` is
    ``list[str]`` (PolicyRetriever.fetch persists a list); a bare ``str`` is
    accepted defensively. Secondary signal: comprehension intent is
    ``confirmar_entrega`` (the only confirmation intent in the closed
    catalog) AND its topics intersect the payment vocabulary. Pure function —
    never raises, never touches IO.
    """
    if not isinstance(trace, dict):
        return False
    retrieved = trace.get("retrieved") or {}
    if isinstance(retrieved, dict):
        raw = retrieved.get("knowledge.policy")
        policies = raw if isinstance(raw, list) else [raw]
        if any(
            isinstance(p, str) and "Trigger: datos_pago" in p for p in policies
        ):
            return True
    comp = trace.get("comprehension") or {}
    if not isinstance(comp, dict):
        return False
    intent = str(comp.get("intent") or "").strip().lower()
    if intent != "confirmar_entrega":
        return False
    topics_raw = comp.get("topics")
    topics = (
        {str(t).strip().lower() for t in topics_raw}
        if isinstance(topics_raw, list)
        else set()
    )
    return bool(topics & _PAYMENT_TOPICS)


def trailing_vip_texts(history_rows: list[dict]) -> list[str]:
    """Extract chronological texts of the open trailing VIP burst from history."""
    texts_rev: list[str] = []
    for row in reversed(history_rows):
        if not isinstance(row, dict):
            break
        if row.get("role") != "vip":
            break
        texts_rev.append(str(row.get("text") or ""))
    texts_rev.reverse()
    return [t for t in texts_rev if t.strip()]


def format_vip_burst_text(texts: list[str], *, fallback: str) -> str:
    """Build IncomingTurn.text for a single msg or multi-msg open burst.

    ROADMAP 3.3: when a VIP sends multiple messages before the pipeline runs,
    number each line so the Analyst can reason about distinct intents within
    the burst instead of collapsing N intents into a single ``intent``
    field. The Generator still produces one reply — the numbering is for the
    cognitive stage only — but the owner can see all N intents in ``/traza``
    and notice if one was ignored.
    """
    cleaned = [t.strip() for t in texts if isinstance(t, str) and t.strip()]
    if not cleaned:
        return fallback
    if len(cleaned) == 1:
        return cleaned[0]
    header = f"(el VIP envió {len(cleaned)} mensajes seguidos)"
    numbered = "\n".join(f"[{i + 1}/{len(cleaned)}] {t}" for i, t in enumerate(cleaned))
    return f"{header}\n{numbered}"


class DirectorPort(Protocol):
    async def handle_turn(self, turn_context: IncomingTurn) -> Decision: ...


class LearningPort(Protocol):
    async def run_post_turn(self, turn_id: UUID) -> object: ...


@dataclass(frozen=True, slots=True)
class _AutonomousDeliverJob:
    """Prepared autonomous deliver payload — executed outside chat_scope."""

    text: str
    ctx: DeliveryContext
    decision: Decision


class TurnOrchestrator:
    """Application entry for VIP business messages.

    Supervised approve never auto-delivers. Autonomous ``action=="send"``
    delivers via BehaviorEngine **outside** the per-chat lock so
    cancel_pending can interrupt mid-flight (Admin pattern).
    """

    def __init__(
        self,
        *,
        coordinator: TurnCoordinator,
        director: DirectorPort,
        admin: AdminService,
        learning: LearningPort,
        history: MessageHistoryWriter,
        gray_zone: GrayZoneService | None = None,
        feature_gray_zone_enabled: bool = False,
        feature_general_mode_enabled: bool = False,
        behavior: BehaviorDeliverer | None = None,
        autonomous_mode: AutonomousModeService | None = None,
        vip_store: VipStore | None = None,
        traces: DeliveryResultWriter | None = None,
        delivery_mode: DeliveryMode = "supervised",
        feature_advanced_behavior: bool = False,
        sandbox: object | None = None,
        delay_policy: DelayPolicy | None = None,
        runtime_timers: RuntimeTimerStore | None = None,
        clock: object | None = None,
        daily_message_limit_store: object | None = None,
        turns: TurnStore | None = None,
        persona_catalog_provider: object | None = None,
        trace_reader: TraceReader | None = None,
        atencion_cycles: AtencionCycleStore | None = None,
        memory_extraction: object | None = None,
        emotional_detector: object | None = None,
        emotional_signal_log: object | None = None,
        profile_synthesis_trigger: object | None = None,
        turn_classifier: object | None = None,
        turn_category_log: object | None = None,
        mood_engine: object | None = None,
        vip_mood_state: object | None = None,
        trust_budget: object | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._director = director
        self._admin = admin
        self._learning = learning
        self._history = history
        self._gray_zone = gray_zone
        self._feature_gray_zone_enabled = feature_gray_zone_enabled
        self._feature_general_mode_enabled = feature_general_mode_enabled
        self._behavior = behavior
        self._autonomous_mode = autonomous_mode
        self._vip_store = vip_store
        self._traces = traces
        self._delivery_mode = delivery_mode
        self._feature_advanced_behavior = bool(feature_advanced_behavior)
        self._sandbox = sandbox
        self._delay_policy = delay_policy
        self._runtime_timers = runtime_timers
        self._clock = clock
        self._daily_limit = daily_message_limit_store
        self._turns = turns
        self._catalog_provider = persona_catalog_provider
        self._trace_reader = trace_reader
        self._atencion_cycles = atencion_cycles
        self._memory_extraction = memory_extraction
        self._emotional_detector = emotional_detector
        self._emotional_signal_log = emotional_signal_log
        self._profile_synthesis_trigger = profile_synthesis_trigger
        # Evo-Agente Fase 2/3 shadow hooks: classifier + mood engine are
        # flag-gated (None when flag off → hooks no-op); the repos are always
        # wired (the hooks need them when the flag is on).
        self._turn_classifier = turn_classifier
        self._turn_category_log = turn_category_log
        self._mood_engine = mood_engine
        self._vip_mood_state = vip_mood_state
        # Evo-Agente Fase 5: trust-budget service (flag-gated; None when flag
        # off → ``_run_trust_budget`` is a no-op, byte-identical).
        self._trust_budget = trust_budget
        # Per-VIP mood engines forked from the injected prototype with a stable
        # seed per VIP (review round 1, S5) — deterministic bounded noise so the
        # same conversation reproduces the same mood trace across restarts.
        # Bounded, pruned (review round 2): one tiny engine per VIP and the VIP
        # space is the allowlist (bounded cardinality) — the cache cannot grow
        # beyond the allowlist size; ``_cap_mood_engines`` keeps a hard cap as
        # defense-in-depth, same convention as ``_prune_payment_notify``.
        self._vip_mood_engines: dict[UUID, MoodEngine] = {}
        # F4: per-chat cooldown for the atencion payment DM (bounded, pruned).
        self._last_payment_notify: dict[int, datetime] = {}

    def _sandbox_active(self, chat_id: int) -> bool:
        return self._sandbox is not None and self._sandbox.is_active(chat_id)  # type: ignore[union-attr]

    def _effective_delivery_mode(self, _chat_id: int) -> DeliveryMode:
        # Sandbox must not force fake_delivery; product isolation is should_persist.
        return self._delivery_mode

    async def _resolve_effective_mode(
        self, vip_id: UUID | None, channel_type: str = "vip",
    ) -> DeliveryMode:
        """Resolve the mode used for the pre-pipeline delay.

        Per-channel profile ``delivery_mode`` overrides the global mode when the
        catalog is available and the field is present (REQ-ATN-05). Autonomous
        mode must then pass both L1 (feature flag) and L2 (global mode or
        per-VIP auto_send) gates. Falls back to supervised otherwise. The AMS
        ``vip_id=None → supervised`` guard stays the final safety net.
        """
        mode = self._delivery_mode
        if self._catalog_provider is not None:
            try:
                catalog = await self._catalog_provider.get_catalog(channel_type)
            except Exception:
                catalog = None
            if catalog is not None:
                mode = catalog.get("delivery_mode", mode)
        if mode != "autonomous":
            return mode
        if self._autonomous_mode is None:
            return "supervised"
        enabled = await self._autonomous_mode.is_autonomous_enabled(vip_id)
        return "autonomous" if enabled else "supervised"

    def _should_enforce_daily_limit(self, incoming: VipInboundMessage) -> bool:
        # F4-02: general-mode atencion only; edits never count.
        return (
            bool(incoming.counts_toward_limit)
            and not incoming.is_edit
            and self._daily_limit is not None
        )

    async def _enforce_daily_limit(
        self, incoming: VipInboundMessage
    ) -> tuple[str, UUID | None]:
        """Return ``(outcome, close_turn_id)`` after the atomic increment.

        outcome is "proceed" | "closed" | "dropped"; ``close_turn_id`` is the
        real minted turn for "closed" (None when the close was skipped), None
        otherwise. Fails open on store error so a DB hiccup never drops a
        legitimate message.
        """
        now = (
            self._clock.now()  # type: ignore[union-attr]
            if self._clock is not None and hasattr(self._clock, "now")
            else datetime.now(UTC)
        )
        fecha_local = cdmx_local_date(now)
        try:
            count = await self._daily_limit.increment(  # type: ignore[union-attr]
                incoming.chat_id, fecha_local=fecha_local
            )
        except Exception:
            logger.exception(
                "atencion_limit_check_failed",
                extra={
                    "chat_id": incoming.chat_id,
                    "fecha_local": fecha_local.isoformat(),
                },
            )
            return "proceed", None
        if count <= 20:
            return "proceed", None
        if count == 21:
            close_id = await self._send_atencion_limit_close(incoming)
            return "closed", close_id
        logger.info(
            "atencion_limit_dropped",
            extra={
                "chat_id": incoming.chat_id,
                "fecha_local": fecha_local.isoformat(),
                "count": count,
            },
        )
        return "dropped", None

    async def _send_atencion_limit_close(
        self, incoming: VipInboundMessage
    ) -> UUID | None:
        """Best-effort direct-to-chat closing reply; never supervised/LLM.

        Mirrors ``PromoService.execute_promo``: mints a REAL turn with a
        non-terminal status (``promo_pending``) so the delivery path satisfies
        both the ``pending_deliveries.turn_id`` FK and the engine's
        TurnStatusReader liveness gate — a synthetic uuid4 aborts the send in
        production. Returns the close turn id (None when skipped).
        """
        bc = incoming.business_connection_id
        if self._behavior is None or not bc or not str(bc).strip():
            logger.info(
                "atencion_limit_close_skipped",
                extra={"chat_id": incoming.chat_id, "reason": "no_sender_or_bc"},
            )
            return None
        if self._turns is None:
            logger.info(
                "atencion_limit_close_skipped",
                extra={"chat_id": incoming.chat_id, "reason": "no_turn_store"},
            )
            return None
        try:
            turn = await self._turns.create(
                TurnRecord(
                    id=uuid4(),
                    chat_id=incoming.chat_id,
                    status=TurnStatus.PROMO_PENDING.value,
                    vip_id=None,
                    channel_type=incoming.channel_type,
                )
            )
        except Exception:
            logger.exception(
                "atencion_limit_close_skipped",
                extra={
                    "chat_id": incoming.chat_id,
                    "reason": "turn_create_failed",
                },
            )
            return None
        ctx = DeliveryContext(
            chat_id=incoming.chat_id,
            business_connection_id=str(bc),
            vip_id=None,
            mode=self._delivery_mode,
            is_frozen=False,
            telegram_message_id=incoming.telegram_message_id,
            skip_initial_delay=True,
        )
        try:
            result = await self._behavior.deliver(
                [ATENCION_DAILY_LIMIT_CLOSE],
                ctx,
                turn.id,
                decision=None,
            )
        except Exception:
            await self._try_transition(
                turn.id,
                TurnStatus.FAILED.value,
                error="atencion_limit_close_failed",
                chat_id=incoming.chat_id,
            )
            logger.exception(
                "atencion_limit_close_failed",
                extra={"chat_id": incoming.chat_id, "turn_id": str(turn.id)},
            )
            return turn.id
        status = (
            TurnStatus.DELIVERED.value
            if result.success
            else TurnStatus.FAILED.value
        )
        await self._try_transition(
            turn.id,
            status,
            error=None if result.success else result.error,
            chat_id=incoming.chat_id,
        )
        return turn.id

    async def _try_transition(
        self,
        turn_id: UUID,
        status: str,
        *,
        error: str | None = None,
        chat_id: int,
    ) -> None:
        """Fail-soft close-turn transition: never let a store error escape.

        The closing reply is best-effort; a turn-store failure on bookkeeping
        must not propagate out of ``_send_atencion_limit_close`` and drop the
        client's 21st message (same fail-open invariant as the increment).
        """
        try:
            await self._turns.transition(  # type: ignore[union-attr]
                turn_id,
                status,
                error=error,
            )
        except Exception:
            logger.exception(
                "atencion_limit_close_transition_failed",
                extra={
                    "turn_id": str(turn_id),
                    "status": status,
                    "chat_id": chat_id,
                },
            )

    async def _maybe_post_turn(self, turn_id: UUID, chat_id: int) -> None:
        if self._sandbox is not None and not self._sandbox.should_persist(chat_id):  # type: ignore[union-attr]
            logger.info(
                "post_turn_skipped_sandbox",
                extra={"turn_id": str(turn_id), "chat_id": chat_id},
            )
            return
        await self._learning.run_post_turn(turn_id)
        # F5 Pool 3 (F5-04 / REQ-MEM-07): post-turn incremental memory
        # extraction, composed AFTER LearningService (never modified). Best-
        # effort strict (R1): a failure here NEVER propagates to the already
        # completed turn. The service itself gates terminal turns, vip_id,
        # binding and the feature flag; when nothing is wired (flag OFF,
        # A8) this block is a no-op — byte-identical to pre-Pool 3.
        if self._memory_extraction is not None:
            extract = getattr(self._memory_extraction, "extract_post_turn", None)
            if callable(extract):
                try:
                    await extract(turn_id, chat_id)  # type: ignore[misc]  # object-typed dep (plan A8)
                except Exception:
                    log_swallowed(
                        logger,
                        "memory_extraction_error",
                        turn_id=str(turn_id),
                        chat_id=chat_id,
                    )

    async def _maybe_post_turn_guarded(
        self, turn_id: UUID, chat_id: int
    ) -> None:
        """Best-effort post-turn hook wrapper (never masks the caller).

        ``_maybe_post_turn`` swallows memory-extraction failures but leaves the
        LEARNING step unwrapped — a failure there inside a ``finally``/``except``
        would mask the original terminal-path exception. This wrapper guarantees
        the hook itself never propagates (R4, best-effort strict R1).
        """
        try:
            await self._maybe_post_turn(turn_id, chat_id)
        except Exception:
            log_swallowed(
                logger,
                "post_turn_hook_error",
                turn_id=str(turn_id),
                chat_id=chat_id,
            )

    async def _run_emotional_detector(
        self,
        turn_id: UUID,
        chat_id: int,
        decision: Decision | None,
        vip_epoch: int | None = None,
    ) -> EmotionalSignalRecord | None:
        """Shadow detector hook: never propagates, flag-gated, writes
        emotional_signal_log only. Best-effort (pattern _maybe_post_turn_guarded).

        Reads comprehension from the committed pipeline trace, builds the
        emotional baseline from prior turns of the chat, and — only when a
        signal is detected — inserts one emotional_signal_log row. No effect
        on the decision pipeline (shadow-only). Both deps are ``object | None``
        (flag OFF → detector is None → no-op).

        Returns the detected :class:`EmotionalSignalRecord` (or None) so the
        profile-synthesis trigger can reuse it without a re-read (A4/A12): the
        emotional signal is evaluated in the SAME turn (immediate, spec
        transversal §Puntos de integración 1). ``vip_epoch`` closes the
        deterministic stale-epoch gap: a turn whose VIP epoch advanced since
        it was minted (a newer message superseded it via ``supersede_chat``)
        is never logged, even when the read-back below is not yet terminal.
        """
        if self._emotional_detector is None or self._emotional_signal_log is None:
            return
        trace_reader = self._trace_reader
        if trace_reader is None:
            return
        try:
            trace = await trace_reader.get_full_trace(turn_id)
            if trace is None or not trace.get("comprehension"):
                return
            # Read-back gate (pattern ``_maybe_post_turn_terminal``): a turn
            # that is already terminal (superseded / failed / ...) never had
            # its decision applied — do not log a shadow signal for it. This
            # keeps the emotional_signal_log clean of stale-epoch superseded
            # and aborted turns (review round 1).
            turn = await self._coordinator.get_turn(turn_id)
            if turn is not None and is_turn_status_terminal(turn.status):
                return
            # Deterministic stale-epoch gate (review round 2): the read-back
            # above only covers turns ALREADY terminal at hook time. A turn
            # whose VIP epoch advanced since mint (superseded right after the
            # call-site by ``_apply_decision_after_director``'s
            # ``is_vip_epoch_current`` check) would still be logged here — skip
            # it too so a stale turn never gets a shadow signal.
            if vip_epoch is not None and not self._coordinator.is_vip_epoch_current(
                chat_id, vip_epoch
            ):
                return
            min_turns = getattr(
                self._emotional_detector, "min_baseline_turns", 5
            )
            baseline = await trace_reader.get_recent_comprehension(
                chat_id,
                limit=min_turns,
                exclude_turn_id=turn_id,
            )
            signal = self._emotional_detector.detect(
                trace["comprehension"],
                baseline,
                decision.action if decision is not None else None,
            )
            if signal.signal_detected:
                await self._emotional_signal_log.insert(
                    turn_id=turn_id,
                    vip_id=trace.get("vip_id"),
                    signal=signal,
                )
                logger.info(
                    "emotional_detector_signal",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": chat_id,
                        "signal_type": signal.signal_type,
                        "intensity": signal.intensity,
                    },
                )
            return signal if signal.signal_detected else None
        except Exception:
            log_swallowed(
                logger,
                "emotional_detector_error",
                turn_id=str(turn_id),
                chat_id=chat_id,
            )
            return None

    async def _run_profile_synthesis_trigger(
        self,
        turn_id: UUID,
        chat_id: int,
        incoming: VipInboundMessage,
        signal: EmotionalSignalRecord | None,
    ) -> None:
        """Profile-synthesis trigger hook: never propagates, flag-gated (A4).

        Runs at the SINGLE call-site right after ``_run_emotional_detector``
        (``_handle_vip_message_locked``), where ``incoming.text`` (needed for
        the strong-signal heuristic) and ``incoming.vip_id`` are available. The
        emotional signal is passed through for immediate evaluation; volume and
        strong-signal share the same hook; ``session_close`` (inactivity) is
        left to the periodic scan job. ``_maybe_post_turn`` has no message text
        — evaluating there would require an extra query per turn (A4).

        Flag OFF → trigger is None → no-op. Any error is swallowed (pattern
        ``_maybe_post_turn_guarded``): a synthesis trigger failure must never
        break the turn.
        """
        if self._profile_synthesis_trigger is None:
            return
        try:
            await self._profile_synthesis_trigger.evaluate_and_maybe_enqueue(
                incoming.vip_id,
                text=incoming.text,
                signal=signal,
            )
        except Exception:
            log_swallowed(
                logger,
                "profile_synthesis_trigger_error",
                turn_id=str(turn_id),
                chat_id=chat_id,
            )

    async def _run_turn_classifier(
        self,
        turn_id: UUID,
        chat_id: int,
        incoming: VipInboundMessage,
        signal: EmotionalSignalRecord | None,
        vip_epoch: int | None = None,
    ) -> TurnCategoryLogRecord | None:
        """Shadow classifier hook: never propagates, flag-gated, best-effort.

        Classifies the turn (pure heuristics over the analyst comprehension +
        ``incoming.text``), reclassifies with the SAME :class:`EmotionalSignalRecord`
        already computed by ``_run_emotional_detector`` (ONE evaluation per turn —
        never calls ``detector.detect()`` again and never writes
        ``emotional_signal_log``), computes ``would_autonomous`` (fast-lane
        shadow decision, independent of the ``feature_phatic_autonomy`` flag),
        and persists one ``turn_category_log`` row.

        EA-02(1) confident check + EA-02(2) satisfied by construction
        (``ForbiddenKeywordsMiddleware`` short-circuits before the orchestrator);
        EA-02(3) deferred to Fase 5 (no draft generation in shadow). EA-03:
        sensitive is never fast-lane. VIP turns only (``incoming.vip_id`` None
        → no-op — the atencion channel is out of the F2 measurement).

        Returns the inserted :class:`TurnCategoryLogRecord` (additive — the
        Fase 5 ``_run_trust_budget`` hook consumes it BY VALUE, never re-reading
        the DB), or ``None`` when the hook skipped / failed (best-effort).
        """
        if self._turn_classifier is None or self._turn_category_log is None:
            return
        if incoming.vip_id is None:
            return
        trace_reader = self._trace_reader
        if trace_reader is None:
            return
        try:
            trace = await trace_reader.get_full_trace(turn_id)
            if trace is None or not trace.get("comprehension"):
                return
            # Read-back gates (pattern ``_run_emotional_detector``): terminal /
            # stale-epoch turns are never logged.
            turn = await self._coordinator.get_turn(turn_id)
            if turn is not None and is_turn_status_terminal(turn.status):
                return
            if vip_epoch is not None and not self._coordinator.is_vip_epoch_current(
                chat_id, vip_epoch
            ):
                return
            classification = self._turn_classifier.classify(
                incoming.text, trace["comprehension"]
            )
            # Detector reclassification (spec transversal, Puntos de integración
            # 2): a signal above SYNTHESIS_THRESHOLD pulls the turn out of the
            # fast-lane (escalation-candidate → sensitive; otherwise emotional).
            # EA-03 priority is preserved (review round 1, B1): an already
            # classified ``sensible`` (hard rule) is NEVER degraded — the
            # signal only ADDS sensibility/escalation, it never downgrades it.
            final_category = classification.category
            if (
                signal is not None
                and signal.signal_detected
                and signal.should_trigger_synthesis
            ):
                if (
                    signal.should_escalate_to_owner
                    or classification.category == "sensible"
                ):
                    final_category = "sensible"
                else:
                    final_category = "emocional"
            # Fast-lane shadow decision (EA-02(1) + EA-03), independent of the
            # ``feature_phatic_autonomy`` flag — the flag only gates the hook.
            would_autonomous = (
                final_category == "fatico"
                and self._turn_classifier.is_confident(classification)
            )
            record = await self._turn_category_log.insert(
                TurnCategoryLogRecord(
                    turn_id=turn_id,
                    vip_id=incoming.vip_id,
                    chat_id=chat_id,
                    category=final_category,
                    # ``confidence`` is the classifier's confidence on its
                    # PRE-reclassification category (documented semantics,
                    # review round 1 nit). After a detector reclassification the
                    # persisted ``category`` is authoritative and
                    # ``would_autonomous`` is the fast-lane decision.
                    confidence=classification.confidence,
                    would_autonomous=would_autonomous,
                )
            )
            logger.info(
                "turn_classifier_classified",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "category": final_category,
                    "confidence": classification.confidence,
                    "would_autonomous": would_autonomous,
                },
            )
            return record
        except Exception:
            log_swallowed(
                logger, "turn_classifier_error", turn_id=str(turn_id), chat_id=chat_id
            )
            return None

    async def _run_mood_engine(
        self,
        turn_id: UUID,
        chat_id: int,
        incoming: VipInboundMessage,
        vip_epoch: int | None = None,
    ) -> None:
        """Shadow mood hook: never propagates, flag-gated, best-effort.

        Computes the per-turn mood signal from the analyst ``emotion`` (no LLM),
        updates the 3-axis ``vip_mood_state`` with the moving-average-with-
        return formula and upserts one row per VIP turn. 3.3 shadow: logs the
        mood→tone distance WITHOUT applying it (variant selection is Fase 5).
        VIP turns only (``incoming.vip_id`` None → no-op).

        Read-back gates mirror the classifier/detector (review round 1, B2):
        terminal AND stale-epoch turns are never upserted — a superseded turn's
        signal must not nudge the mood even though the upsert is idempotent per
        VIP (idempotency is not data quality). Noise is deterministic per VIP
        (S5): the injected prototype engine is forked with a stable seed derived
        from the VIP id.
        """
        if self._mood_engine is None or self._vip_mood_state is None:
            return
        if incoming.vip_id is None:
            return
        trace_reader = self._trace_reader
        if trace_reader is None:
            return
        try:
            trace = await trace_reader.get_full_trace(turn_id)
            if trace is None or not trace.get("comprehension"):
                return
            turn = await self._coordinator.get_turn(turn_id)
            if turn is not None and is_turn_status_terminal(turn.status):
                return
            if vip_epoch is not None and not self._coordinator.is_vip_epoch_current(
                chat_id, vip_epoch
            ):
                return
            engine = self._mood_engine
            if self._vip_mood_engines is not None:
                per_vip = self._vip_mood_engines.get(incoming.vip_id)
                if per_vip is None:
                    per_vip = engine.fork(seed=int(incoming.vip_id))
                    self._vip_mood_engines[incoming.vip_id] = per_vip
                    self._cap_mood_engines()
                engine = per_vip
            comprehension = trace["comprehension"]
            signal = engine.signal_from_comprehension(comprehension)
            current = await self._vip_mood_state.get_by_vip(incoming.vip_id)
            updated = engine.update(current, signal)
            # The repo stamps ``updated_at`` server-side (``func.now()``) — the
            # hook omits it (review round 1 nit).
            await self._vip_mood_state.upsert(
                VipMoodStateRecord(
                    vip_id=incoming.vip_id,
                    axis_playful_serious=updated.axis_playful_serious,
                    axis_warm_distant=updated.axis_warm_distant,
                    axis_energy=updated.axis_energy,
                )
            )
            # 3.3 shadow: distance between the PRE-update mood and the turn's
            # tone point (review round 1, S3) — measures tone deviation from
            # where the mood already was, not from where it just landed.
            emotion = (
                comprehension.get("emotion")
                if isinstance(comprehension, dict)
                else getattr(comprehension, "emotion", None)
            )
            tone_distance = engine.tone_distance(
                current or MoodState(0.0, 0.0, 0.0), emotion or "neutral"
            )
            logger.info(
                "mood_updated",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "vip_id": str(incoming.vip_id),
                    "axis_playful": updated.axis_playful_serious,
                    "axis_warm": updated.axis_warm_distant,
                    "axis_energy": updated.axis_energy,
                    "tone_distance": round(tone_distance, 4),
                },
            )
        except Exception:
            log_swallowed(
                logger, "mood_engine_error", turn_id=str(turn_id), chat_id=chat_id
            )

    async def _run_trust_budget(
        self,
        turn_id: UUID,
        chat_id: int,
        incoming: VipInboundMessage,
        category_log: TurnCategoryLogRecord | None,
        vip_epoch: int | None = None,
    ) -> None:
        """Shadow trust-budget hook: never propagates, flag-gated, best-effort.

        Increments the (VIP, category) trust budget when the just-classified
        turn would have been autonomous (``would_autonomous=True``). The
        increment is the "autonomous without correction" event (spec 5.1); the
        correction event arrives LATER via ``AdminService.handle_correct`` →
        ``TrustBudgetService.record_correction``. Read-back gates mirror
        ``_run_mood_engine``: terminal / stale-epoch turns never increment — a
        superseded turn's ``would_autonomous`` is not rewarded.

        ``category_log`` is the record JUST inserted by ``_run_turn_classifier``
        (passed BY VALUE — the hook never re-reads ``turn_category_log``); the
        terminal / stale-epoch read-back gates DO re-read the turn and epoch
        (``_coordinator.get_turn`` / ``is_vip_epoch_current``), mirroring
        ``_run_mood_engine`` (review round 1).

        Shadow semantics (review round 1, S3): in supervised mode each increment
        is a "would have sent" WITHOUT a real send — it is predictor
        (F2 ``would_autonomous``) calibration, not observed behavior. The trust
        budget is meant to be INTERPRETED / RESET when F2 leaves shadow, when
        the real auto-send becomes the source of truth (EA-01). Flag OFF →
        ``self._trust_budget`` None → no-op (byte-identical).
        """
        if self._trust_budget is None:
            return
        if incoming.vip_id is None:
            return
        if category_log is None or not category_log.would_autonomous:
            return
        try:
            turn = await self._coordinator.get_turn(turn_id)
            if turn is not None and is_turn_status_terminal(turn.status):
                return
            if vip_epoch is not None and not self._coordinator.is_vip_epoch_current(
                chat_id, vip_epoch
            ):
                return
            await self._trust_budget.record_autonomous(
                incoming.vip_id, category_log.category
            )
            logger.info(
                "trust_budget_autonomous",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "vip_id": str(incoming.vip_id),
                    "category": category_log.category,
                },
            )
        except Exception:
            log_swallowed(
                logger, "trust_budget_error", turn_id=str(turn_id), chat_id=chat_id
            )

    async def _maybe_post_turn_terminal(
        self, turn_id: UUID, chat_id: int
    ) -> None:
        """Best-effort post-turn hook gated on the persisted extractable status.

        Mirrors ``AdminService._trigger_post_turn_terminal`` (REQ-MEM-07): read-
        backs the turn's persisted status and fires the hook ONLY when it is
        still in the extractable set (delivered / escalated / failed). The read-
        back closes the persist-then-raise gap — a row persisted DELIVERED /
        FAILED / ESCALATED while the in-block flag was never assigned still runs,
        and a turn that ended non-extractable (e.g. superseded) never runs. The
        read itself is best-effort: on failure the hook still fires (the caller
        already confirmed it made the turn terminal), so the completed turn's
        learning + memory extraction are never stranded.
        """
        try:
            turn = await self._coordinator.get_turn(turn_id)
            if (
                turn is not None
                and turn.status not in _POST_TURN_EXTRACTABLE_STATUSES
            ):
                logger.info(
                    "post_turn_skipped_status",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": chat_id,
                        "status": turn.status,
                    },
                )
                return
        except Exception:
            log_swallowed(
                logger,
                "post_turn_status_readback_failed",
                turn_id=str(turn_id),
                chat_id=chat_id,
            )
        await self._maybe_post_turn_guarded(turn_id, chat_id)

    async def _safe_notify_info(
        self,
        message: str,
        *,
        chat_id: int,
        event: str,
        **extra: object,
    ) -> bool:
        """Owner notify fail-soft: never mask the primary failure path.

        Returns True when the DM was delivered, False when the send was
        swallowed. Callers that gate side effects on delivery (e.g. the
        payment-DM cooldown, O1) must act only on a True return.
        """
        try:
            await self._admin.notify_info(message, chat_id=chat_id)
        except Exception:
            log_swallowed(logger, event, chat_id=chat_id, **extra)
            return False
        return True

    def _prune_payment_notify(self, now: datetime) -> None:
        """Drop per-chat payment cooldown entries older than the TTL (F7)."""
        stale = now - _PAYMENT_NOTIFY_TTL
        for chat_id in [
            c for c, ts in self._last_payment_notify.items() if ts < stale
        ]:
            del self._last_payment_notify[chat_id]

    def _cap_mood_engines(self) -> None:
        """Keep the per-VIP mood-engine cache bounded (review round 2).

        The cache is structurally bounded already — one tiny ``MoodEngine`` fork
        per VIP and the VIP space is the allowlist (bounded cardinality) — so
        this is a defensive hard cap (FIFO eviction of the oldest-inserted
        entry), mirroring ``_prune_payment_notify``.
        """
        while len(self._vip_mood_engines) > _VIP_MOOD_ENGINE_CACHE_MAX:
            self._vip_mood_engines.pop(next(iter(self._vip_mood_engines)))

    async def _maybe_notify_payment_intent(
        self,
        *,
        turn_id: UUID,
        turn_ctx: IncomingTurn,
        incoming: VipInboundMessage,
        decision: Decision,
    ) -> None:
        """REQ-ATN-12: informational DM to the owner on payment intent.

        Runs only for the atencion channel, only in general mode (O2), and
        only when a ``trace_reader`` is injected. Reads the committed trace
        (already stored by the Director), detects the payment signal
        deterministically, and sends ONE fail-soft informational DM (A7).
        The turn flow is never altered.

        Anti-amplification (F4): edited messages never notify (edits also do
        not count toward the daily limit), per-chat 20-min cooldown, and
        ``consult_doctrine`` turns are skipped (the gray zone branch already
        sends a doctrine DM — a payment DM would double-notify). Sandboxed
        chats are skipped (F16).
        """
        if turn_ctx.channel_type != "atencion":
            return
        # O2: the payment DM only exists in general mode — training mode sets
        # channel_type=atencion without the general flag (byte-identical flag-OFF).
        if not self._feature_general_mode_enabled:
            return
        if incoming.is_edit:
            return
        if self._trace_reader is None:
            return
        if decision.action == "consult_doctrine":
            return
        if self._sandbox_active(turn_ctx.chat_id):
            return
        now = datetime.now(UTC)
        self._prune_payment_notify(now)
        last = self._last_payment_notify.get(turn_ctx.chat_id)
        if last is not None and now - last < _PAYMENT_NOTIFY_TTL:
            return
        try:
            trace = await self._trace_reader.get_full_trace(turn_id)
        except Exception:
            log_swallowed(
                logger,
                "atencion_payment_trace_read_failed",
                turn_id=str(turn_id),
                chat_id=turn_ctx.chat_id,
            )
            return
        if not _detect_payment_intent(trace):
            return
        # O1: stamp the 20-min cooldown ONLY after a successful DM. A swallowed
        # send must not consume the slot and hide the notice for 20 minutes.
        if await self._safe_notify_info(
            ATENCION_PAYMENT_NOTICE.format(chat_id=turn_ctx.chat_id),
            chat_id=turn_ctx.chat_id,
            event="atencion_payment_intent_notified",
            turn_id=str(turn_id),
        ):
            self._last_payment_notify[turn_ctx.chat_id] = now
            # F4: payment intent ends the chat's atencion cycle — the owner
            # delivers manually afterwards and the chat leaves the pipeline
            # (the auth gate only admits chats with an OPEN cycle). Fail-soft
            # and idempotent: a later turn re-detecting payment simply no-ops.
            if self._atencion_cycles is not None:
                try:
                    await self._atencion_cycles.close_payment(
                        turn_ctx.chat_id, now=now
                    )
                    logger.info(
                        "atencion_cycle_closed_payment",
                        extra={"chat_id": turn_ctx.chat_id},
                    )
                except Exception:
                    logger.exception(
                        "atencion_cycle_close_failed",
                        extra={"chat_id": turn_ctx.chat_id},
                    )

    async def _fail_director_typed(
        self,
        turn_id: UUID,
        chat_id: int,
        *,
        error: str,
        notify_event: str,
    ) -> None:
        """mark_failed then fail-soft owner notify (typed director errors).

        R4: the post-turn hook fires on the happy path from the caller
        (``pending_deliver is None`` in ``_run_after_pre_delay``). If
        ``mark_failed`` persists then raises, that normal-path hook is skipped
        by the propagating exception — so fire it here (best-effort, read-back
        gated) before re-raising, never double-firing on the happy path.
        """
        try:
            await self._coordinator.mark_failed(turn_id, error=error)
        except Exception:
            await self._maybe_post_turn_terminal(turn_id, chat_id)
            raise
        await self._safe_notify_info(
            f"Turn {turn_id} failed: {error}",
            chat_id=chat_id,
            event=notify_event,
            turn_id=str(turn_id),
        )

    async def handle_vip_message(self, incoming: VipInboundMessage) -> UUID:
        """Process one VIP message; return the minted turn_id."""
        chat_id = incoming.chat_id
        # F4-02: enforce the atencion daily limit BEFORE any pipeline work
        # (epoch bump, durable history, mint, LLM). Over-limit messages never
        # write history, never advance the epoch, never enter the cognitive
        # pipeline. "closed" returns the real close turn id (minted by the
        # closing-reply send); "dropped" returns a synthetic uuid4
        # (business.py only logs it).
        if self._should_enforce_daily_limit(incoming):
            outcome, close_id = await self._enforce_daily_limit(incoming)
            if outcome == "closed":
                return close_id or uuid4()
            if outcome == "dropped":
                return uuid4()
        # Capture before any await so owner marks during pre-mint are visible.
        before_inbound = time.monotonic()
        bc = incoming.business_connection_id
        if bc is None or not str(bc).strip():
            # Fail under lock without advancing VIP epoch / durable history.
            async with self._coordinator.chat_scope(chat_id):
                turn_id, _ = await self._handle_vip_message_locked(
                    incoming, vip_epoch=None
                )
            return turn_id

        # Newer VIP message invalidates older in-flight work for this chat.
        vip_epoch = self._coordinator.bump_vip_epoch(chat_id)
        await self._append_vip_history_if_persist(incoming)

        # Mint ASAP under lock (before mode resolve / delay) so owner cancel
        # has a durable target; sleep stays OUTSIDE chat_scope.
        async with self._coordinator.chat_scope(chat_id):
            if not self._coordinator.is_vip_epoch_current(chat_id, vip_epoch):
                winner_id = await self._resolve_skip_mint_turn_id(chat_id)
                logger.info(
                    "turn_mint_skipped_stale_epoch",
                    extra={
                        "chat_id": chat_id,
                        "vip_epoch": vip_epoch,
                        "current_epoch": self._coordinator.current_vip_epoch(
                            chat_id
                        ),
                        "winner_turn_id": str(winner_id),
                    },
                )
                return winner_id
            turn_id, aborted_owner = await self._mint_turn_for_inbound(
                incoming,
                vip_epoch,
                before_inbound=before_inbound,
            )
            if aborted_owner:
                return turn_id

        mode = await self._resolve_effective_mode(
            incoming.vip_id, incoming.channel_type
        )
        pre_delay = (
            self._delay_policy.initial_delay_seconds(mode)
            if self._delay_policy is not None
            else 0.0
        )

        logger.info(
            "turn_delay_started",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "pre_delay_s": pre_delay,
                "mode": mode,
            },
        )
        timer_id: UUID | None = None
        if pre_delay > 0:
            timer_id = await self._persist_pre_delay_timer(
                turn_id=turn_id,
                incoming=incoming,
                vip_epoch=vip_epoch,
                pre_delay=pre_delay,
                mode=mode,
            )
            try:
                await self._sleep_seconds(pre_delay)
            finally:
                if timer_id is not None and self._runtime_timers is not None:
                    try:
                        await self._runtime_timers.mark_completed(timer_id)
                    except Exception:
                        log_swallowed(
                            logger,
                            "pre_delay_timer_complete_failed",
                            turn_id=str(turn_id),
                            timer_id=str(timer_id),
                        )

        return await self._run_after_pre_delay(
            incoming,
            turn_id=turn_id,
            vip_epoch=vip_epoch,
            before_inbound=before_inbound,
        )

    async def resume_waiting_delay(
        self,
        *,
        turn_id: UUID,
        incoming: VipInboundMessage,
        vip_epoch: int,
        remaining_seconds: float,
    ) -> UUID:
        """Startup recovery: finish pre-pipeline wait then run cognitive path.

        Call **after** missed-update recovery so offline owner/VIP traffic can
        supersede the turn first.
        """
        chat_id = incoming.chat_id
        self._coordinator.restore_vip_epoch(chat_id, vip_epoch)
        self._coordinator.bind_turn_vip_epoch(turn_id, chat_id, vip_epoch)

        live = await self._coordinator.get_turn(turn_id)
        if live is None or live.status != TurnStatus.WAITING_DELAY.value:
            logger.info(
                "pre_delay_resume_skip",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "status": None if live is None else live.status,
                },
            )
            return turn_id

        if not self._coordinator.is_vip_epoch_current(chat_id, vip_epoch):
            async with self._coordinator.chat_scope(chat_id):
                still = await self._coordinator.get_turn(turn_id)
                if still is not None and not is_turn_status_terminal(still.status):
                    await self._coordinator.supersede_chat(
                        chat_id,
                        reason="new_message",
                        superseded_by=None,
                    )
            logger.info(
                "pre_delay_resume_stale_epoch",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "vip_epoch": vip_epoch,
                },
            )
            return turn_id

        logger.info(
            "pre_delay_resume_started",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "remaining_s": remaining_seconds,
            },
        )
        if remaining_seconds > 0:
            await self._sleep_seconds(remaining_seconds)

        return await self._run_after_pre_delay(
            incoming,
            turn_id=turn_id,
            vip_epoch=vip_epoch,
            before_inbound=None,
        )

    async def _sleep_seconds(self, seconds: float) -> None:
        if seconds <= 0:
            return
        sleep = getattr(self._clock, "sleep", None) if self._clock is not None else None
        if callable(sleep):
            await sleep(seconds)
            return
        await asyncio.sleep(seconds)

    async def _persist_pre_delay_timer(
        self,
        *,
        turn_id: UUID,
        incoming: VipInboundMessage,
        vip_epoch: int,
        pre_delay: float,
        mode: str,
    ) -> UUID | None:
        if self._runtime_timers is None or pre_delay <= 0:
            return None
        now = (
            self._clock.now()  # type: ignore[union-attr]
            if self._clock is not None and hasattr(self._clock, "now")
            else datetime.now(UTC)
        )
        timer_id = uuid4()
        payload = {
            "vip_epoch": vip_epoch,
            "mode": mode,
            "incoming": {
                "chat_id": incoming.chat_id,
                "text": incoming.text,
                "telegram_message_id": incoming.telegram_message_id,
                "business_connection_id": incoming.business_connection_id,
                "vip_id": str(incoming.vip_id) if incoming.vip_id else None,
                "is_edit": bool(incoming.is_edit),
                "channel_type": incoming.channel_type,
            },
        }
        try:
            await self._runtime_timers.create_active(
                RuntimeTimerRecord(
                    id=timer_id,
                    chat_id=incoming.chat_id,
                    turn_id=turn_id,
                    delivery_id=None,
                    kind="pre_delay",
                    scheduled_at=now,
                    initial_delay_seconds=float(pre_delay),
                    status="active",
                    created_at=now,
                    payload=payload,
                )
            )
            return timer_id
        except Exception:
            logger.exception(
                "pre_delay_timer_persist_failed",
                extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
            )
            return None

    async def _run_after_pre_delay(
        self,
        incoming: VipInboundMessage,
        *,
        turn_id: UUID,
        vip_epoch: int,
        before_inbound: float | None,
    ) -> UUID:
        """Post-wait gates + cognitive pipeline (shared by live path and recovery)."""
        chat_id = incoming.chat_id
        # Re-check after delay (no long lock): terminal / stale epoch / owner flag.
        live = await self._coordinator.get_turn(turn_id)
        owner_flag = self._coordinator.is_owner_intervened(
            chat_id, since=before_inbound
        )
        if live is None or is_turn_status_terminal(live.status):
            reason = self._abort_reason_after_delay(
                live, owner_intervened=owner_flag
            )
            logger.info(
                "turn_aborted_after_delay",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "reason": reason,
                    "status": None if live is None else live.status,
                },
            )
            return turn_id

        if not self._coordinator.is_vip_epoch_current(chat_id, vip_epoch):
            async with self._coordinator.chat_scope(chat_id):
                still = await self._coordinator.get_turn(turn_id)
                if still is not None and not is_turn_status_terminal(still.status):
                    await self._coordinator.supersede_chat(
                        chat_id,
                        reason="new_message",
                        superseded_by=None,
                    )
                still = await self._coordinator.get_turn(turn_id)
            logger.info(
                "turn_aborted_after_delay",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "reason": "new_message",
                    "status": None if still is None else still.status,
                },
            )
            return turn_id

        if owner_flag:
            # Defense-in-depth: flag set but coordinate(owner) not yet applied.
            async with self._coordinator.chat_scope(chat_id):
                still = await self._coordinator.get_turn(turn_id)
                if still is not None and not is_turn_status_terminal(still.status):
                    await self._coordinator.supersede_chat(
                        chat_id,
                        reason="owner_message",
                        superseded_by=None,
                    )
                self._coordinator.clear_owner_intervention(chat_id)
                still = await self._coordinator.get_turn(turn_id)
            logger.info(
                "turn_aborted_after_delay",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "reason": "owner_message",
                    "status": None if still is None else still.status,
                },
            )
            return turn_id

        logger.info(
            "turn_delay_completed",
            extra={"turn_id": str(turn_id), "chat_id": chat_id},
        )

        pending_deliver: _AutonomousDeliverJob | None
        async with self._coordinator.chat_scope(chat_id):
            still = await self._coordinator.get_turn(turn_id)
            if still is None or is_turn_status_terminal(still.status):
                reason = self._abort_reason_after_delay(
                    still,
                    owner_intervened=self._coordinator.is_owner_intervened(
                        chat_id, since=before_inbound
                    ),
                )
                logger.info(
                    "turn_aborted_after_delay",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": chat_id,
                        "reason": reason,
                        "status": None if still is None else still.status,
                    },
                )
                return turn_id
            if not self._coordinator.is_vip_epoch_current(chat_id, vip_epoch):
                if not is_turn_status_terminal(still.status):
                    await self._coordinator.supersede_chat(
                        chat_id,
                        reason="new_message",
                        superseded_by=None,
                    )
                still = await self._coordinator.get_turn(turn_id)
                logger.info(
                    "turn_aborted_after_delay",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": chat_id,
                        "reason": "new_message",
                        "status": None if still is None else still.status,
                    },
                )
                return turn_id
            # Defense-in-depth: owner flag under lock before Director.
            if self._coordinator.is_owner_intervened(chat_id, since=before_inbound):
                await self._coordinator.supersede_chat(
                    chat_id,
                    reason="owner_message",
                    superseded_by=None,
                )
                self._coordinator.clear_owner_intervention(chat_id)
                still = await self._coordinator.get_turn(turn_id)
                logger.info(
                    "turn_aborted_after_delay",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": chat_id,
                        "reason": "owner_message",
                        "status": None if still is None else still.status,
                    },
                )
                return turn_id
            turn_id, pending_deliver = await self._run_cognitive_after_delay(
                incoming, turn_id=turn_id, vip_epoch=vip_epoch
            )
            if pending_deliver is None:
                await self._maybe_post_turn(turn_id, chat_id)
                return turn_id

        # OUTSIDE lock — cancel_pending can interrupt delays (Admin pattern).
        # Re-check freeze after lock release (race: freeze applied mid-pipeline).
        vip_frozen = await self._is_vip_frozen(incoming.vip_id)
        if vip_frozen:
            async with self._coordinator.chat_scope(chat_id):
                live = await self._coordinator.get_turn(turn_id)
                if live is not None and not is_turn_status_terminal(live.status):
                    try:
                        await self._coordinator.mark_failed(
                            turn_id, error="vip_frozen"
                        )
                    except Exception:
                        # R4: persist-then-raise in mark_failed skips the
                        # normal-path hook below — fire it here (read-back gated)
                        # before re-raising, never double-firing on the happy path.
                        await self._maybe_post_turn_terminal(turn_id, chat_id)
                        raise
                    await self._safe_notify_info(
                        f"Turn {turn_id} failed: vip_frozen",
                        chat_id=chat_id,
                        event="owner_notify_failed_after_vip_frozen",
                        turn_id=str(turn_id),
                    )
            await self._maybe_post_turn(turn_id, chat_id)
            logger.info(
                "autonomous_vip_frozen_pre_deliver",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "vip_id": str(incoming.vip_id) if incoming.vip_id else None,
                },
            )
            return turn_id

        # Prepare already fails closed if behavior is None; re-check for
        # partial wiring / race without relying on assert (stripped under -O).
        if self._behavior is None:
            async with self._coordinator.chat_scope(chat_id):
                live = await self._coordinator.get_turn(turn_id)
                if live is not None and not is_turn_status_terminal(live.status):
                    try:
                        await self._coordinator.mark_failed(
                            turn_id, error="autonomous_behavior_not_wired"
                        )
                    except Exception:
                        # R4: persist-then-raise in mark_failed skips the
                        # normal-path hook below — fire it here (read-back gated)
                        # before re-raising, never double-firing on the happy path.
                        await self._maybe_post_turn_terminal(turn_id, chat_id)
                        raise
            await self._maybe_post_turn(turn_id, chat_id)
            logger.error(
                "autonomous_behavior_not_wired",
                extra={"turn_id": str(turn_id), "chat_id": chat_id},
            )
            return turn_id

        # SEC-F2: pass actual freeze snapshot from re-check (False after gate).
        # Mid-delay FreezePort re-query remains residual (engine uses ctx only).
        deliver_ctx = pending_deliver.ctx.model_copy(
            update={"is_frozen": vip_frozen}
        )
        logger.info(
            "autonomous_send_start",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "vip_id": str(incoming.vip_id) if incoming.vip_id else None,
            },
        )
        result = await self._behavior.deliver(
            [pending_deliver.text],
            deliver_ctx,
            turn_id,
            decision=pending_deliver.decision,
        )
        # R4: mutable holder — set BEFORE each terminal transition inside
        # ``_finalize_autonomous_delivery`` so a persisted-then-raised
        # transition still fires the post-turn hook from the ``finally`` below
        # (outside the chat lock); the read-back gate guards exactly-once.
        post_turn_state: list[bool] = [False]
        try:
            async with self._coordinator.chat_scope(chat_id):
                delivered = await self._finalize_autonomous_delivery(
                    turn_id,
                    chat_id,
                    result,
                    text=pending_deliver.text,
                    post_turn_state=post_turn_state,
                )
        finally:
            # REQ-MEM-07 parity with the supervised path: run post-turn learning
            # + memory extraction AFTER the turn is confirmed terminal in an
            # extractable status and OUTSIDE the chat lock. Best-effort strict
            # (R1) — a failure never propagates to the already-completed send.
            if post_turn_state[0]:
                await self._maybe_post_turn_terminal(turn_id, chat_id)

        # Near-threshold notify only when finalize confirmed DELIVERED
        # (not raw actuator success — mid-flight supersede must not notify).
        if (
            delivered
            and self._autonomous_mode is not None
        ):
            await self._autonomous_mode.notify_if_needed(
                turn_id,
                pending_deliver.decision,
                pending_deliver.decision.evaluation,
            )

        logger.info(
            "vip_message_handled",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "action": "send",
            },
        )
        return turn_id

    async def _append_vip_history_if_persist(self, incoming: VipInboundMessage) -> None:
        """Persist VIP inbound early so aborted rounds still join the open burst.

        Edits (same telegram_message_id) **replace** the prior row so the model
        never sees original + edited as two messages.
        """
        if (
            self._sandbox is not None
            and not self._sandbox.should_persist(incoming.chat_id)  # type: ignore[union-attr]
        ):
            logger.info(
                "vip_history_skipped_sandbox",
                extra={"chat_id": incoming.chat_id},
            )
            return
        upsert = getattr(self._history, "upsert_vip_message", None)
        if callable(upsert) and (
            incoming.is_edit or incoming.telegram_message_id is not None
        ):
            action = await upsert(
                incoming.chat_id,
                text=incoming.text,
                telegram_message_id=incoming.telegram_message_id,
            )
            if action == "updated" or incoming.is_edit:
                logger.info(
                    "vip_history_message_updated",
                    extra={
                        "chat_id": incoming.chat_id,
                        "telegram_message_id": incoming.telegram_message_id,
                        "is_edit": incoming.is_edit,
                    },
                )
            return
        await self._history.append(
            incoming.chat_id,
            role="vip",
            text=incoming.text,
            telegram_message_id=incoming.telegram_message_id,
        )

    async def _coalesce_open_vip_turn_text(
        self, chat_id: int, *, fallback: str
    ) -> str:
        """Join trailing unanswered VIP messages for the cognitive turn payload.

        History is the source of truth after append. When sandbox skips durable
        history, get_recent is empty and we keep ``fallback`` (current text only).
        """
        try:
            recent = await self._history.get_recent(
                chat_id, limit=_BURST_HISTORY_LIMIT
            )
        except Exception:
            logger.exception(
                "vip_burst_history_read_failed",
                extra={"chat_id": chat_id},
            )
            return fallback
        burst = trailing_vip_texts(recent)
        text = format_vip_burst_text(burst, fallback=fallback)
        if len(burst) > 1:
            logger.info(
                "vip_open_burst_coalesced",
                extra={
                    "chat_id": chat_id,
                    "burst_count": len(burst),
                    "text_chars": len(text),
                },
            )
        return text

    async def _resolve_skip_mint_turn_id(self, chat_id: int) -> UUID:
        """Prefer live winner, else last minted turn for chat; uuid4 last resort."""
        live_turns = await self._coordinator.list_non_terminal(chat_id)
        if live_turns:
            return live_turns[0].id
        last = self._coordinator.last_turn_id(chat_id)
        if last is not None:
            return last
        # Chat never minted a turn in this process — unavoidable synthetic.
        logger.info(
            "turn_mint_skipped_stale_epoch_no_prior_turn",
            extra={"chat_id": chat_id},
        )
        return uuid4()

    async def _mint_turn_for_inbound(
        self,
        incoming: VipInboundMessage,
        vip_epoch: int,
        *,
        before_inbound: float,
    ) -> tuple[UUID, bool]:
        """Create waiting_delay turn + bind epoch. Caller holds chat_scope.

        Returns ``(turn_id, aborted_for_owner)``. When owner intervened since
        *before_inbound*, cascade-supersedes the new turn and clears the flag.
        """
        chat_id = incoming.chat_id
        record = await self._coordinator.begin_turn_unlocked(
            chat_id=chat_id,
            trigger_message_id=incoming.telegram_message_id,
            vip_id=incoming.vip_id,
            channel_type=incoming.channel_type,
        )
        turn_id = record.id
        self._coordinator.bind_turn_vip_epoch(turn_id, chat_id, vip_epoch)
        logger.info(
            "turn_minted_waiting_delay",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "vip_epoch": vip_epoch,
            },
        )
        if self._coordinator.is_owner_intervened(chat_id, since=before_inbound):
            await self._coordinator.supersede_chat(
                chat_id,
                reason="owner_message",
                superseded_by=None,
            )
            self._coordinator.clear_owner_intervention(chat_id)
            logger.info(
                "turn_aborted_owner_at_mint",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "reason": "owner_message",
                },
            )
            return turn_id, True
        # Drop any older stuck flag so mid-pipeline checks stay clean.
        self._coordinator.clear_owner_intervention(chat_id)
        return turn_id, False

    @staticmethod
    def _abort_reason_after_delay(
        live: object | None,
        *,
        owner_intervened: bool = False,
    ) -> str:
        """Map post-delay abort for logs.

        - ``owner_message`` when owner flag/path fired
        - ``new_message`` when VIP replace (superseded_by set) or epoch stale
        - ``superseded`` neutral when terminal supersede without owner/VIP marker
          (e.g. sandbox reset)
        """
        if owner_intervened:
            return "owner_message"
        if live is None:
            return "new_message"
        status = getattr(live, "status", None)
        superseded_by = getattr(live, "superseded_by", None)
        if status in (TurnStatus.SUPERSEDED.value, "superseded"):
            if superseded_by is not None:
                return "new_message"
            return "superseded"
        return "new_message"

    async def _run_cognitive_after_delay(
        self,
        incoming: VipInboundMessage,
        *,
        turn_id: UUID,
        vip_epoch: int | None,
    ) -> tuple[UUID, _AutonomousDeliverJob | None]:
        """Director + routing for an already-minted turn. Caller holds chat_scope."""
        return await self._handle_vip_message_locked(
            incoming,
            vip_epoch=vip_epoch,
            turn_id=turn_id,
        )

    async def _handle_vip_message_locked(
        self,
        incoming: VipInboundMessage,
        *,
        vip_epoch: int | None,
        turn_id: UUID | None = None,
    ) -> tuple[UUID, _AutonomousDeliverJob | None]:
        bc = incoming.business_connection_id
        if bc is None or not str(bc).strip():
            if turn_id is None:
                record = await self._coordinator.begin_turn_unlocked(
                    chat_id=incoming.chat_id,
                    trigger_message_id=incoming.telegram_message_id,
                    vip_id=incoming.vip_id,
                    channel_type=incoming.channel_type,
                )
                turn_id = record.id
            try:
                await self._coordinator.mark_failed(
                    turn_id, error="business_connection_id is required"
                )
            finally:
                # R4: this path ALWAYS raises BEFORE the normal hook site, but
                # the turn is FAILED — a terminal, extractable outcome. Fire the
                # post-turn hook best-effort in the finally so a persisted-then-
                # raised mark_failed cannot strand extraction; the read-back gate
                # skips non-extractable statuses.
                await self._maybe_post_turn_terminal(
                    turn_id, incoming.chat_id
                )
            raise ValueError("business_connection_id is required")

        if turn_id is None:
            # Fail-closed / legacy entry: mint then cognitive in one lock section.
            record = await self._coordinator.begin_turn_unlocked(
                chat_id=incoming.chat_id,
                trigger_message_id=incoming.telegram_message_id,
                vip_id=incoming.vip_id,
                channel_type=incoming.channel_type,
            )
            turn_id = record.id
            if vip_epoch is not None:
                self._coordinator.bind_turn_vip_epoch(
                    turn_id, incoming.chat_id, vip_epoch
                )

        # History already appended at inbound (early) so cancelled rounds still
        # join the open burst. Sandbox skips are handled there too.

        # Coalesce open VIP burst into turn text so a superseding turn answers
        # all unanswered VIP lines in this round (not only the latest message).
        turn_text = await self._coalesce_open_vip_turn_text(
            incoming.chat_id, fallback=incoming.text
        )

        turn_ctx = IncomingTurn(
            turn_id=turn_id,
            chat_id=incoming.chat_id,
            vip_id=incoming.vip_id,
            text=turn_text,
            telegram_message_id=incoming.telegram_message_id,
            business_connection_id=str(bc).strip(),
            channel_type=incoming.channel_type,
        )

        try:
            decision = await self._director.handle_turn(turn_ctx)
        except TurnSupersededError:
            logger.info(
                "turn_cancelled_mid_pipeline",
                extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
            )
            return turn_id, None
        except Exception as exc:
            # Terminal latch: no-ops if already superseded while Director ran
            # (should not happen under full chat_scope; still safe).
            # Typed cognitive failures: mark failed + notify owner, do NOT re-raise
            # (avoids business_handler_error double-log; VIP gets no send).
            if isinstance(exc, AnalystSchemaInvalidError):
                await self._fail_director_typed(
                    turn_id,
                    incoming.chat_id,
                    error="analista_schema_invalido",
                    notify_event="owner_notify_failed_after_analyst_schema_invalid",
                )
                logger.warning(
                    "director_failed_typed",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": incoming.chat_id,
                        "error": "analista_schema_invalido",
                    },
                )
                return turn_id, None
            if isinstance(exc, EvaluatorSchemaInvalidError):
                await self._fail_director_typed(
                    turn_id,
                    incoming.chat_id,
                    error="evaluador_schema_invalido",
                    notify_event="owner_notify_failed_after_evaluator_schema_invalid",
                )
                logger.warning(
                    "director_failed_typed",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": incoming.chat_id,
                        "error": "evaluador_schema_invalido",
                    },
                )
                return turn_id, None
            if isinstance(exc, ContextExceedsLimitError):
                await self._fail_director_typed(
                    turn_id,
                    incoming.chat_id,
                    error="contexto_excede_limite",
                    notify_event="owner_notify_failed_after_context_exceeds_limit",
                )
                logger.warning(
                    "director_failed_typed",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": incoming.chat_id,
                        "error": "contexto_excede_limite",
                    },
                )
                return turn_id, None
            if isinstance(exc, GeneratorEmptyOutputError):
                await self._fail_director_typed(
                    turn_id,
                    incoming.chat_id,
                    error="generador_salida_vacia",
                    notify_event="owner_notify_failed_after_generator_empty_output",
                )
                logger.warning(
                    "director_failed_typed",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": incoming.chat_id,
                        "error": "generador_salida_vacia",
                    },
                )
                return turn_id, None
            try:
                await self._coordinator.mark_failed(turn_id, error=str(exc))
            finally:
                # R4: persist-then-raise in mark_failed (or the raise below) —
                # the turn is FAILED, a terminal extractable outcome, but this
                # path raises before the normal hook site. Fire best-effort here
                # so extraction is never stranded; the read-back gate skips
                # non-extractable statuses.
                await self._maybe_post_turn_terminal(
                    turn_id, incoming.chat_id
                )
            logger.exception(
                "director_failed",
                extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
            )
            raise

        # Evo-Agente: shadow emotional detector AFTER the Director produced a
        # decision (needs decision.action for pipeline_would_have_escalated).
        # Flag OFF → detector None → no-op. ``_run_emotional_detector`` is
        # fully guarded (its inner try/except never propagates), so no external
        # guard is needed here — and the hook never transitions the turn, so
        # TurnSupersededError cannot originate from it. ``vip_epoch`` is passed
        # so the hook can skip turns that are about to be superseded by the
        # ``_apply_decision_after_director`` epoch check below (round 2).
        #
        # Evo-Agente Fase 1 (A4): the profile-synthesis trigger runs at this
        # SINGLE call-site, right after the detector — the only place where
        # incoming.text (strong-signal) and incoming.vip_id are both available
        # for every VIP turn (supervised AND autonomous both pass here; the
        # autonomous send / supervised approval happen downstream). The
        # detector's signal is passed through so ``should_trigger_synthesis``
        # is evaluated in the same turn (immediate). ``_maybe_post_turn`` has
        # no message text → it is NOT the call-site. All hooks are guarded.
        #
        # Evo-Agente Fase 2/3 (A2): the classifier and mood-engine shadow hooks
        # run here too. ANTI-DOUBLE-COUNT: the emotional signal is evaluated ONE
        # time per turn, in ``_run_emotional_detector`` (which also writes the
        # single ``emotional_signal_log`` row, UNIQUE ``turn_id``). That same
        # record is REUSED by ``_run_turn_classifier`` to reclassify — the new
        # hooks never re-run ``detector.detect()`` nor write ``emotional_signal_log``.
        #
        # Evo-Agente Fase 5 (A3): the trust-budget hook runs right after the
        # mood hook, consuming the ``TurnCategoryLogRecord`` just returned by
        # ``_run_turn_classifier`` BY VALUE (no DB re-read). Shadow + flag-gated
        # (``feature_trust_budget``); it increments only VIP turns classified
        # ``would_autonomous=True`` and never propagates. The matching decrement
        # arrives later via ``AdminService.handle_correct`` → ``record_correction``.
        signal = await self._run_emotional_detector(
            turn_id, incoming.chat_id, decision, vip_epoch
        )
        category_log = await self._run_turn_classifier(
            turn_id, incoming.chat_id, incoming, signal, vip_epoch
        )
        await self._run_mood_engine(
            turn_id, incoming.chat_id, incoming, vip_epoch
        )
        await self._run_trust_budget(
            turn_id, incoming.chat_id, incoming, category_log, vip_epoch
        )
        await self._run_profile_synthesis_trigger(
            turn_id, incoming.chat_id, incoming, signal
        )

        # Route decision + transitions: owner/VIP cancel may raise on status_sink
        # when the Director stub never polled mid-pipeline (A2 clean abort).
        try:
            return await self._apply_decision_after_director(
                decision,
                turn_id=turn_id,
                turn_ctx=turn_ctx,
                incoming=incoming,
                vip_epoch=vip_epoch,
            )
        except TurnSupersededError:
            logger.info(
                "turn_cancelled_post_director",
                extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
            )
            return turn_id, None

    async def _apply_decision_after_director(
        self,
        decision: Decision,
        *,
        turn_id: UUID,
        turn_ctx: IncomingTurn,
        incoming: VipInboundMessage,
        vip_epoch: int | None,
    ) -> tuple[UUID, _AutonomousDeliverJob | None]:
        """Apply Director decision; may raise TurnSupersededError via status_sink."""
        # Total cancel: newer VIP message while this turn was running (even if
        # the Director port is a stub that never hits status_sink transitions).
        if vip_epoch is not None and not self._coordinator.is_vip_epoch_current(
            incoming.chat_id, vip_epoch
        ):
            await self._coordinator.supersede_chat(
                incoming.chat_id,
                reason="new_message",
                superseded_by=None,
            )
            logger.info(
                "turn_cancelled_stale_epoch_post_director",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": incoming.chat_id,
                    "vip_epoch": vip_epoch,
                    "current_epoch": self._coordinator.current_vip_epoch(
                        incoming.chat_id
                    ),
                },
            )
            return turn_id, None

        # Post-Director liveness check (defense in depth vs zombie pipeline).
        live = await self._coordinator.get_turn(turn_id)
        if live is None or is_turn_status_terminal(live.status):
            logger.info(
                "orchestrator_aborted_terminal",
                extra={
                    "turn_id": str(turn_id),
                    "status": None if live is None else live.status,
                },
            )
            return turn_id, None

        # REQ-ATN-12: informational payment notice for atencion (fail-soft,
        # never alters the supervised flow).
        await self._maybe_notify_payment_intent(
            turn_id=turn_id,
            turn_ctx=turn_ctx,
            incoming=incoming,
            decision=decision,
        )

        if decision.action == "approve":
            await self._coordinator.transition(
                turn_id, TurnStatus.PENDING_APPROVAL
            )
            await self._admin.send_draft_for_approval(
                turn_ctx, decision, turn_id
            )
            # CRITICAL: never call behavior.deliver here (L2 / R1)
        elif decision.action == "consult_doctrine":
            if (
                turn_ctx.vip_id is None
                and self._sandbox_active(incoming.chat_id)
            ):
                demoted = decision.model_copy(
                    update={
                        "action": "approve",
                        "reason": "sandbox_no_vip_doctrine",
                    }
                )
                await self._coordinator.transition(
                    turn_id, TurnStatus.PENDING_APPROVAL
                )
                await self._admin.send_draft_for_approval(
                    turn_ctx, demoted, turn_id
                )
                logger.info(
                    "sandbox_consult_doctrine_demoted",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": incoming.chat_id,
                    },
                )
            elif turn_ctx.channel_type == "atencion" and turn_ctx.vip_id is None:
                # atencion channel (non-VIP) turn without vip_id: real gray
                # zone consult (create query with vip_id=None + chat_id) when
                # ALL gates are on — general mode AND gray zone AND an injected
                # service (F10: training mode sets channel_type=atencion without
                # the general flag → demote, no query, no orphan freeze).
                # Otherwise demote to approve (byte-identical pre-Item-4
                # behavior). A vip-less turn on the VIP channel must NOT take
                # this path — it falls through to the RuntimeError guard below.
                if (
                    self._feature_general_mode_enabled
                    and self._feature_gray_zone_enabled
                    and self._gray_zone is not None
                ):
                    # F20: re-check the atencion freeze before minting a second
                    # query (race TOCTOU): if a newer message already opened a
                    # query with a future freeze_until, drop this turn instead
                    # of creating a second query + second DM.
                    # O3: the F20 re-check is fail-soft too — a transient DB
                    # error must not escape to business.py and leave the turn
                    # non-terminal. Fail open: proceed as if no open query.
                    try:
                        already = await self._gray_zone.get_open_query_by_chat_id(
                            turn_ctx.chat_id
                        )
                    except Exception:
                        log_swallowed(
                            logger,
                            "atencion_gray_zone_recheck_failed",
                            turn_id=str(turn_id),
                            chat_id=incoming.chat_id,
                        )
                        already = None
                    if already is not None:
                        existing_freeze = getattr(already, "freeze_until", None)
                        if existing_freeze is not None:
                            if existing_freeze.tzinfo is None:
                                existing_freeze = existing_freeze.replace(
                                    tzinfo=UTC
                                )
                            if existing_freeze > datetime.now(UTC):
                                await self._coordinator.transition(
                                    turn_id, TurnStatus.SUPERSEDED
                                )
                                logger.info(
                                    "atencion_gray_zone_already_open",
                                    extra={
                                        "turn_id": str(turn_id),
                                        "chat_id": incoming.chat_id,
                                        "query_id": str(getattr(already, "id", None)),
                                    },
                                )
                                return turn_id, None
                    query = await self._gray_zone.create_query(
                        vip_id=None,
                        chat_id=turn_ctx.chat_id,
                        turn_id=turn_id,
                        question=turn_ctx.text,
                        draft=decision.draft_text or "",
                        business_connection_id=turn_ctx.business_connection_id,
                    )
                    try:
                        await self._admin.send_doctrine_query(
                            turn_ctx, decision, turn_id, query
                        )
                    except Exception:
                        # F6: a notify failure must not orphan the query and
                        # freeze the chat without a DM. Close + demote approve.
                        try:
                            await self._gray_zone.discard_and_close(query.id)
                        except Exception:
                            log_swallowed(
                                logger,
                                "atencion_doctrine_discard_failed",
                                turn_id=str(turn_id),
                                chat_id=incoming.chat_id,
                                query_id=str(query.id)
                                if hasattr(query, "id")
                                else None,
                            )
                        demoted = decision.model_copy(
                            update={
                                "action": "approve",
                                "reason": "atencion_doctrine_notify_failed",
                            }
                        )
                        await self._coordinator.transition(
                            turn_id, TurnStatus.PENDING_APPROVAL
                        )
                        await self._admin.send_draft_for_approval(
                            turn_ctx, demoted, turn_id
                        )
                        logger.warning(
                            "atencion_doctrine_notify_failed",
                            extra={
                                "turn_id": str(turn_id),
                                "chat_id": incoming.chat_id,
                                "query_id": str(query.id)
                                if hasattr(query, "id")
                                else None,
                            },
                        )
                    else:
                        await self._coordinator.transition(
                            turn_id, TurnStatus.GRAY_ZONE
                        )
                        logger.info(
                            "atencion_consult_doctrine_gray_zone",
                            extra={
                                "turn_id": str(turn_id),
                                "chat_id": incoming.chat_id,
                                "query_id": str(query.id)
                                if hasattr(query, "id")
                                else None,
                            },
                        )
                else:
                    demoted = decision.model_copy(
                        update={
                            "action": "approve",
                            "reason": "atencion_no_vip_doctrine",
                        }
                    )
                    await self._coordinator.transition(
                        turn_id, TurnStatus.PENDING_APPROVAL
                    )
                    await self._admin.send_draft_for_approval(
                        turn_ctx, demoted, turn_id
                    )
                    logger.info(
                        "atencion_consult_doctrine_demoted",
                        extra={
                            "turn_id": str(turn_id),
                            "chat_id": incoming.chat_id,
                        },
                    )
            elif not self._feature_gray_zone_enabled:
                raise RuntimeError(
                    "consult_doctrine action returned but gray zone feature is disabled"
                )
            elif self._gray_zone is None:
                raise RuntimeError(
                    "consult_doctrine action returned but GrayZoneService is not injected"
                )
            elif turn_ctx.vip_id is None:
                raise RuntimeError(
                    "consult_doctrine requires vip_id but turn has None"
                )
            else:
                # Create query + notify BEFORE transitioning to GRAY_ZONE so
                # a failure does not leave the turn stuck in gray_zone (BUG-3).
                query = await self._gray_zone.create_query(
                    vip_id=turn_ctx.vip_id,
                    turn_id=turn_id,
                    question=turn_ctx.text,
                    draft=decision.draft_text or "",
                    chat_id=turn_ctx.chat_id,
                    business_connection_id=turn_ctx.business_connection_id,
                )
                await self._admin.send_doctrine_query(
                    turn_ctx, decision, turn_id, query
                )
                await self._coordinator.transition(
                    turn_id, TurnStatus.GRAY_ZONE
                )
                logger.info(
                    "consult_doctrine_completed",
                    extra={
                        "turn_id": str(turn_id),
                        "vip_id": str(turn_ctx.vip_id),
                        "query_id": str(query.id)
                        if hasattr(query, "id")
                        else None,
                    },
                )
                # CRITICAL: never call behavior.deliver — VIP is frozen
        elif decision.action == "escalate":
            try:
                await self._coordinator.transition(
                    turn_id, TurnStatus.ESCALATED
                )
                await self._admin.notify_escalation(
                    turn_ctx, decision, turn_id
                )
            except Exception:
                # R4: an ESCALATED transition that persists-then-raises (or a
                # notify failure after it) must still fire the post-turn hook —
                # the normal-path hook (pending_deliver is None) only runs when
                # no exception propagates. The read-back gate decides
                # extractability and guards exactly-once.
                await self._maybe_post_turn_terminal(
                    turn_id, incoming.chat_id
                )
                raise
        elif decision.action == "send":
            job = await self._prepare_autonomous_send(
                turn_id=turn_id,
                turn_ctx=turn_ctx,
                decision=decision,
                incoming=incoming,
            )
            if job is not None:
                return turn_id, job
        else:
            logger.error(
                "unexpected_f2_action",
                extra={
                    "turn_id": str(turn_id),
                    "action": decision.action,
                    "chat_id": incoming.chat_id,
                },
            )
            try:
                await self._coordinator.mark_failed(
                    turn_id, error=f"unexpected F2 action: {decision.action!r}"
                )
            finally:
                # R4: persist-then-raise in mark_failed (or the raise below) —
                # the turn is FAILED, a terminal extractable outcome, but this
                # path raises before the normal hook site. Fire best-effort here.
                await self._maybe_post_turn_terminal(
                    turn_id, incoming.chat_id
                )
            raise ValueError(f"unexpected F2 action: {decision.action!r}")

        logger.info(
            "vip_message_handled",
            extra={
                "turn_id": str(turn_id),
                "chat_id": incoming.chat_id,
                "action": decision.action,
            },
        )
        return turn_id, None

    async def _prepare_autonomous_send(
        self,
        *,
        turn_id: UUID,
        turn_ctx: IncomingTurn,
        decision: Decision,
        incoming: VipInboundMessage,
    ) -> _AutonomousDeliverJob | None:
        """Gate AMS + frozen/empty; return deliver job or complete under lock."""
        if self._autonomous_mode is None:
            logger.error(
                "autonomous_not_wired",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": incoming.chat_id,
                },
            )
            try:
                await self._coordinator.mark_failed(
                    turn_id, error="autonomous_not_wired"
                )
            except Exception:
                # R4: persist-then-raise in mark_failed skips the normal-path
                # hook (pending_deliver is None) — fire it here (read-back
                # gated) before re-raising; the happy path fires exactly once.
                await self._maybe_post_turn_terminal(
                    turn_id, incoming.chat_id
                )
                raise
            return None

        enabled = await self._autonomous_mode.is_autonomous_enabled(
            incoming.vip_id
        )
        if not enabled:
            logger.info(
                "autonomous_disabled_for_vip",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": incoming.chat_id,
                    "vip_id": str(incoming.vip_id) if incoming.vip_id else None,
                },
            )
            # Demote send → approve with explicit reason (not autonomous_ok).
            demoted = decision.model_copy(
                update={
                    "action": "approve",
                    "reason": "autonomous_mode_disabled",
                }
            )
            await self._coordinator.transition(
                turn_id, TurnStatus.PENDING_APPROVAL
            )
            await self._admin.send_draft_for_approval(
                turn_ctx, demoted, turn_id
            )
            return None

        if await self._is_vip_frozen(incoming.vip_id):
            logger.info(
                "autonomous_vip_frozen",
                extra={
                    "turn_id": str(turn_id),
                    "vip_id": str(incoming.vip_id) if incoming.vip_id else None,
                },
            )
            try:
                await self._coordinator.mark_failed(turn_id, error="vip_frozen")
            except Exception:
                # R4: persist-then-raise in mark_failed skips the normal-path
                # hook (pending_deliver is None) — fire it here (read-back
                # gated) before re-raising; the happy path fires exactly once.
                await self._maybe_post_turn_terminal(
                    turn_id, incoming.chat_id
                )
                raise
            await self._safe_notify_info(
                f"Turn {turn_id} failed: vip_frozen",
                chat_id=incoming.chat_id,
                event="owner_notify_failed_after_vip_frozen",
                turn_id=str(turn_id),
            )
            return None

        draft = (decision.draft_text or "").strip()
        if not draft:
            logger.info(
                "autonomous_empty_draft",
                extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
            )
            try:
                await self._coordinator.mark_failed(turn_id, error="empty_draft")
            except Exception:
                # R4: persist-then-raise in mark_failed skips the normal-path
                # hook (pending_deliver is None) — fire it here (read-back
                # gated) before re-raising; the happy path fires exactly once.
                await self._maybe_post_turn_terminal(
                    turn_id, incoming.chat_id
                )
                raise
            await self._safe_notify_info(
                f"Turn {turn_id} failed: empty_draft",
                chat_id=incoming.chat_id,
                event="owner_notify_failed_after_empty_draft",
                turn_id=str(turn_id),
            )
            return None

        if self._behavior is None:
            logger.error(
                "autonomous_behavior_not_wired",
                extra={"turn_id": str(turn_id)},
            )
            try:
                await self._coordinator.mark_failed(
                    turn_id, error="autonomous_behavior_not_wired"
                )
            except Exception:
                # R4: persist-then-raise in mark_failed skips the normal-path
                # hook (pending_deliver is None) — fire it here (read-back
                # gated) before re-raising; the happy path fires exactly once.
                await self._maybe_post_turn_terminal(
                    turn_id, incoming.chat_id
                )
                raise
            return None

        # is_frozen=False: prepare only builds a job when VIP is not frozen.
        # Engine hard-check of is_frozen is defense-in-depth; orch re-checks
        # after lock release before deliver.
        advanced = self._feature_advanced_behavior
        mode = self._effective_delivery_mode(incoming.chat_id)
        if mode == "fake_delivery":
            logger.info(
                "delivery_mode_fake",
                extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
            )
        ctx = DeliveryContext(
            chat_id=incoming.chat_id,
            business_connection_id=str(turn_ctx.business_connection_id).strip(),
            vip_id=incoming.vip_id,
            telegram_message_id=incoming.telegram_message_id,
            mode=mode,
            is_frozen=False,
            skip_initial_delay=True,
            allow_split=advanced,
            allow_human_quirks=advanced,
            split_chars=4096,
        )
        return _AutonomousDeliverJob(text=draft, ctx=ctx, decision=decision)

    async def _is_vip_frozen(self, vip_id: UUID | None) -> bool:
        """True if vip_store says frozen_until > now(UTC). Missing store/id → False."""
        if self._vip_store is None or vip_id is None:
            return False
        vip = await self._vip_store.get_by_id(vip_id)
        if vip is None or vip.frozen_until is None:
            return False
        now = datetime.now(UTC)
        frozen = vip.frozen_until
        if frozen.tzinfo is None:
            frozen = frozen.replace(tzinfo=UTC)
        return frozen > now

    async def _finalize_autonomous_delivery(
        self,
        turn_id: UUID,
        chat_id: int,
        result: DeliveryResult,
        text: str,
        post_turn_state: list[bool] | None = None,
    ) -> bool:
        """Post-deliver terminal check under chat lock (Admin I.5 parity, no approval).

        Returns True only when the turn was transitioned to DELIVERED.
        Not a SQL CAS / claim token — single-process lock + terminal latch.

        R4: ``post_turn_state`` (mutable holder from the caller's ``finally``)
        is set to True BEFORE each terminal transition so a persisted-then-raised
        transition still fires the post-turn hook (best-effort, read-back gated).
        """
        turn_after = await self._coordinator.get_turn(turn_id)
        if turn_after is None or is_turn_status_terminal(turn_after.status):
            logger.info(
                "autonomous_aborted_terminal_after_deliver",
                extra={
                    "turn_id": str(turn_id),
                    "status": None if turn_after is None else turn_after.status,
                    "deliver_success": result.success,
                },
            )
            return False

        if result.success:
            # R4: eligibility BEFORE the transition — a DELIVERED transition
            # that persists-then-raises must still fire the post-turn hook (the
            # read-back gate decides whether the turn is actually extractable).
            if post_turn_state is not None:
                post_turn_state[0] = True
            await self._coordinator.transition(turn_id, TurnStatus.DELIVERED)
            if self._traces is not None:
                await self._traces.set_delivery_result(
                    turn_id, result.to_trace_dict()
                )
            # H7.2: owner history for Diana outbound (role maps to autor=dueña).
            # Skip durable history when sandbox is active (should_persist false).
            # Multi-segment: one owner row per message_id when texts align.
            if (
                self._sandbox is not None
                and not self._sandbox.should_persist(chat_id)  # type: ignore[union-attr]
            ):
                logger.info(
                    "owner_history_skipped_sandbox",
                    extra={"turn_id": str(turn_id), "chat_id": chat_id},
                )
            else:
                await append_owner_delivery_history(
                    self._history,
                    chat_id,
                    result=result,
                    fallback_text=text,
                    turn_id=turn_id,
                )
            logger.info(
                "autonomous_delivered",
                extra={"turn_id": str(turn_id), "chat_id": chat_id},
            )
            return True

        if result.cancelled:
            # R4: eligibility BEFORE the transition — a FAILED transition that
            # persists-then-raises must still fire the post-turn hook.
            if post_turn_state is not None:
                post_turn_state[0] = True
            await self._coordinator.mark_failed(
                turn_id, error=result.error or "delivery_cancelled"
            )
            if self._traces is not None:
                await self._traces.set_delivery_result(
                    turn_id, result.to_trace_dict()
                )
            logger.info(
                "autonomous_deliver_cancelled",
                extra={
                    "turn_id": str(turn_id),
                    "error": result.error,
                },
            )
            return False

        # Permanent deliver failure (I.5).
        # R4: eligibility BEFORE the transition — a FAILED transition that
        # persists-then-raises must still fire the post-turn hook.
        if post_turn_state is not None:
            post_turn_state[0] = True
        await self._coordinator.mark_failed(
            turn_id, error=result.error or "delivery_failed"
        )
        await self._safe_notify_info(
            f"Turn {turn_id} failed: delivery_failed ({result.error})",
            chat_id=chat_id,
            event="owner_notify_failed_after_autonomous_deliver_fail",
            turn_id=str(turn_id),
        )
        if self._traces is not None:
            await self._traces.set_delivery_result(
                turn_id, result.to_trace_dict()
            )
        logger.info(
            "autonomous_deliver_failed",
            extra={"turn_id": str(turn_id), "error": result.error},
        )
        return False
