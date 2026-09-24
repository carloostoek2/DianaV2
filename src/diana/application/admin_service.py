"""AdminService — owner approval queue (domain API, no aiogram types)."""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from typing import Any, Literal
from uuid import UUID, uuid4

from diana.application.observability import log_swallowed
from diana.application.ports import (
    ApprovalRecord,
    BehaviorDeliverer,
    DeliveryContext,
    DeliveryMode,
    DeliveryResult,
    DeliveryResultWriter,
    DoctrineNotification,
    DraftNotification,
    EscalationNotification,
    EscalationStore,
    GrayZoneQueryView,
    GrayZoneServicePort,
    MessageHistoryWriter,
    OwnerNotifierPort,
    PendingApprovalStore,
    TraceReader,
    TurnRecord,
    TurnStore,
    VipStore,
)
from diana.application.draft_variants import (
    AUTONOMY_KEY,
    DOCTRINE_NA_LABEL,
    DOCTRINE_RELEVANT_KEY,
    ensure_versions,
    resolve_vip_display_name,
)
from diana.application.escalation_fp_resume import (
    FP_RESUME_REASON,
    RESUME_BLOCKED_SAFETY,
    RESUME_MARKED_ONLY,
    RESUME_OPENED_GRAY_ZONE,
    RESUME_RESUMED,
    SAFETY_ESCALATION_REASON,
    FpResumeOutcome,
    FpResumePlan,
    evaluation_from_trace,
    plan_fp_resume,
    plan_from_generated_decision,
)
from diana.application.escalation_labels import tipo_from_reason
from diana.behavior.ports import DeliveryProgressCallback
from diana.application.memory_extraction_service import (
    _POST_TURN_EXTRACTABLE_STATUSES,  # noqa: PLC2701 — extraction gate, single source (R3)
)
from diana.application.owner_history import append_owner_delivery_history
from diana.application.staging_service import AtencionPromoteBlocked, StagingService
from diana.application.turn_coordinator import TurnCoordinator
from diana.cognitive.exceptions import TurnSupersededError
from diana.cognitive.models import (
    Comprehension,
    Decision,
    EvaluationProfile,
    IncomingTurn,
    TurnStatus,
    is_doctrine_relevant,
    is_turn_status_terminal,
)

logger = logging.getLogger("diana.application")

# ROADMAP 5.7: durable audit trail of escalations as a plain-text rotating log.
# DB stores structured escalation rows (escalations table) and the owner
# receives a Telegram DM, but operators also want a grep-friendly file for
# post-incident review. The handler is attached lazily on first escalation
# so importing this module is side-effect-free in tests.
_ESCALATION_LOG_PATH = os.environ.get(
    "DIANA_ESCALATION_LOG_PATH", "/var/log/diana/escalations.log"
)
_ESCALATION_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
_ESCALATION_LOG_BACKUP_COUNT = 5
_escalation_file_handler_attached = False

# Owner-facing placeholder when the VIP's original text cannot be recovered
# (bounded history window / gray zone row without a question). Spanish neutral
# per AGENTS §0.6 — never show the owner an English token.
_NO_VIP_TEXT_PLACEHOLDER = "(texto no disponible)"


def _ensure_escalation_file_handler() -> None:
    """Attach a RotatingFileHandler to the escalation logger (once per process)."""
    global _escalation_file_handler_attached
    if _escalation_file_handler_attached:
        return
    escalation_logger = logging.getLogger("diana.escalations")
    # Skip if the root config or a prior attach already provided one.
    if any(isinstance(h, RotatingFileHandler) for h in escalation_logger.handlers):
        _escalation_file_handler_attached = True
        return
    try:
        # Ensure the parent directory exists; if it can't (e.g. sandbox),
        # the handler is silently skipped — DB and Telegram paths still work.
        os.makedirs(os.path.dirname(_ESCALATION_LOG_PATH), exist_ok=True)
        handler = RotatingFileHandler(
            _ESCALATION_LOG_PATH,
            maxBytes=_ESCALATION_LOG_MAX_BYTES,
            backupCount=_ESCALATION_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        escalation_logger.addHandler(handler)
        escalation_logger.setLevel(logging.INFO)
        _escalation_file_handler_attached = True
    except OSError:
        # Filesystem not writable (e.g. tests, container without /var/log).
        # Fail-soft: the in-process logger and DB/DM paths remain functional.
        pass


class OwnerAuthError(PermissionError):
    """Raised when a non-owner actor attempts an owner-only admin action."""


class QualityFeedbackDisabled(ValueError):
    """FEATURE_QUALITY_FEEDBACK_ENABLED is off."""


def _resolve_doctrine_relevant(
    decision: Decision,
    *,
    comprehension: Comprehension | Mapping[str, Any] | None = None,
    retrieved: Mapping[str, Any] | None = None,
    doctrine_relevant: bool | None = None,
) -> bool:
    """Whether owner UI should treat doctrine as a measured score.

    Never infer N/A from ``evaluation.doctrine == 0.5`` (real compliance and
    gray-zone dummy profiles can share that number). Missing inputs show the
    number (fail-open), not "no aplica".
    """
    if doctrine_relevant is not None:
        return bool(doctrine_relevant)
    if comprehension is not None or retrieved is not None:
        return is_doctrine_relevant(comprehension, retrieved)
    if decision.action == "consult_doctrine":
        return True
    if decision.reason == "gray_zone_resolved_by_doctrine":
        return True
    return True


def _eval_summary(decision: Decision, *, doctrine_relevant: bool) -> str:
    """Display-only summary string; never fed back into Decider."""
    e = decision.evaluation
    doc_slot = (
        f"doc={DOCTRINE_NA_LABEL}"
        if not doctrine_relevant
        else f"doc={e.doctrine:.2f}"
    )
    return (
        f"nat={e.naturalness:.2f} prec={e.precision:.2f} "
        f"{doc_slot} con={e.consistency:.2f} "
        f"saf={e.safety:.2f} cov={e.coverage:.2f} emp={e.empathy:.2f}"
    )


class AdminService:
    """Owner-facing draft queue and owner resolve path that may call Behavior.deliver.

    Autonomous TurnOrchestrator send path may also call Behavior.deliver when
    AMS L1/L2 enablement allows it (feature flag + global/VIP gate).
    """

    def __init__(
        self,
        *,
        notifier: OwnerNotifierPort,
        approvals: PendingApprovalStore,
        escalations: EscalationStore,
        coordinator: TurnCoordinator,
        behavior: BehaviorDeliverer,
        traces: DeliveryResultWriter,
        turns: TurnStore,
        owner_telegram_id: int,
        delivery_mode: DeliveryMode = "supervised",
        feature_advanced_behavior: bool = False,
        vip_store: VipStore | None = None,
        fp_marks: Any | None = None,
        sandbox: Any | None = None,
        staging: StagingService | None = None,
        history: MessageHistoryWriter | None = None,
        post_turn: Callable[[UUID, int], Awaitable[None]] | None = None,
        trust_budget: object | None = None,
        feature_quality_feedback_enabled: bool = False,
        # Fila 4 (SPEC-AUTONOMIA-CALIBRACION): outcome-log service (flag-gated)
        # + readiness kill for record_correction (readiness ON → the desacuerdo
        # event from record_outcome is the single trust decrement).
        outcome: object | None = None,
        feature_autonomy_readiness_enabled: bool = False,
        director: Any | None = None,
        gray_zone: GrayZoneServicePort | None = None,
        # Fila 4 draft DM: readiness snapshot provider for the "Autonomía"
        # section (None → section omitted, byte-compatible with flag OFF).
        autonomy_readiness: Any | None = None,
        # False-positive resume (AGENTS §4.21): when ON, marking an escalation
        # as a false positive continues the supervised flow with a draft DM.
        # OFF ⇒ byte-identical pre-flag behavior (mark only).
        feature_escalation_fp_draft_enabled: bool = False,
    ) -> None:
        self._notifier = notifier
        self._approvals = approvals
        self._escalations = escalations
        self._coordinator = coordinator
        self._behavior = behavior
        self._traces = traces
        self._turns = turns
        self._owner_telegram_id = owner_telegram_id
        self._delivery_mode = delivery_mode
        self._feature_advanced_behavior = bool(feature_advanced_behavior)
        self._vip_store = vip_store
        self._fp_marks = fp_marks
        self._sandbox = sandbox
        self._staging = staging
        self._history = history
        self._post_turn = post_turn
        # Evo-Agente Fase 5: trust-budget service (flag-gated; None when flag
        # off → the correction event is a no-op, byte-identical).
        self._trust_budget = trust_budget
        self._feature_quality_feedback_enabled = bool(feature_quality_feedback_enabled)
        # Fila 4: outcome-log service + readiness kill-switch for
        # record_correction (readiness ON → outcome-driven trust only).
        self._outcome = outcome
        self._autonomy_readiness = bool(feature_autonomy_readiness_enabled)
        # Doctrine rule→regen: Director + GrayZone (wired post-construct when needed).
        self._director = director
        self._gray_zone = gray_zone
        # Gray-zone RULE proposal for FP→consult (mirrors TurnOrchestrator; optional).
        self._gray_zone_proposal: Any | None = None
        self._feature_gray_zone_proposal_enabled = False
        self._autonomy_readiness_svc = autonomy_readiness
        self._feature_escalation_fp_draft_enabled = bool(
            feature_escalation_fp_draft_enabled
        )
        # In-flight false-positive resumes, keyed by turn: aiogram runs each
        # callback update as its own task, so a double tap would otherwise run
        # two pipelines for the same turn (the loser's status transitions land
        # after the winner reopened it, and the terminal latch no longer holds).
        # Process-local on purpose: single-instance deployment (OPS_SINGLE_INSTANCE).
        self._fp_resume_inflight: set[UUID] = set()

    def set_director(self, director: Any) -> None:
        """Wire CognitiveDirector after composition builds it (draft regen / doctrine)."""
        self._director = director

    def set_gray_zone(self, gray_zone: GrayZoneServicePort | None) -> None:
        """Wire GrayZoneService for doctrine hold lookups on owner deliver."""
        self._gray_zone = gray_zone

    def set_gray_zone_proposal(
        self,
        proposal: Any | None,
        *,
        enabled: bool = False,
    ) -> None:
        """Wire optional gray-zone RULE proposal (FEATURE_GRAY_ZONE_PROPOSAL_ENABLED)."""
        self._gray_zone_proposal = proposal
        self._feature_gray_zone_proposal_enabled = bool(enabled)

    @property
    def quality_feedback_enabled(self) -> bool:
        return self._feature_quality_feedback_enabled

    def set_post_turn_hook(
        self,
        hook: Callable[[UUID, int], Awaitable[None]] | None,
    ) -> None:
        """Wire the post-turn learning + memory extraction hook (REQ-MEM-07).

        AdminService is built BEFORE TurnOrchestrator in composition.py, so the
        orchestrator's ``_maybe_post_turn`` is injected after the fact via this
        setter. None disables the hook (tests / flag off).
        """
        self._post_turn = hook

    def _assert_owner(self, actor_id: int | None) -> None:
        if actor_id is None or actor_id != self._owner_telegram_id:
            raise OwnerAuthError(
                f"actor_id {actor_id!r} is not the configured owner"
            )

    def _require_quality_feedback(self) -> None:
        if not self._feature_quality_feedback_enabled:
            raise QualityFeedbackDisabled("FEATURE_QUALITY_FEEDBACK_ENABLED is off")

    def _scope_vip_id(
        self, turn: Any, scope: Literal["global", "vip"]
    ) -> UUID | None:
        if scope == "global":
            return None
        if turn.vip_id is None:
            raise ValueError("scope='vip' requires turn.vip_id")
        return turn.vip_id

    def _sandbox_prefix(self, chat_id: int) -> str:
        if self._sandbox is None or not self._sandbox.is_active(chat_id):
            return ""
        key = self._sandbox.get_profile(chat_id) or "?"
        return f"SANDBOX — profile: {key}"

    def _sandbox_reason(self, chat_id: int, reason: str) -> str:
        prefix = self._sandbox_prefix(chat_id)
        if not prefix:
            return reason
        return f"{prefix} | {reason}"

    def _effective_delivery_mode(self, _chat_id: int) -> DeliveryMode:
        # Sandbox must not force fake_delivery; product isolation is should_persist.
        return self._delivery_mode

    async def send_draft_for_approval(
        self,
        turn: IncomingTurn,
        decision: Decision,
        turn_id: UUID,
        *,
        comprehension: Comprehension | Mapping[str, Any] | None = None,
        retrieved: Mapping[str, Any] | None = None,
        doctrine_relevant: bool | None = None,
    ) -> None:
        bc = (turn.business_connection_id or "").strip()
        if not bc:
            raise ValueError("business_connection_id is required for approval")
        draft = decision.draft_text or ""
        relevant = _resolve_doctrine_relevant(
            decision,
            comprehension=comprehension,
            retrieved=retrieved,
            doctrine_relevant=doctrine_relevant,
        )
        eval_dict = decision.evaluation.model_dump(mode="json")
        eval_dict[DOCTRINE_RELEVANT_KEY] = relevant
        eval_dict = ensure_versions(
            eval_dict,
            draft_text=draft,
            reason=decision.reason or "",
            vip_text=turn.text,
        )
        await self._store_autonomy_snapshot(turn, eval_dict)
        record = ApprovalRecord(
            id=uuid4(),
            turn_id=turn_id,
            chat_id=turn.chat_id,
            business_connection_id=bc,
            draft_text=draft,
            status="waiting",
            vip_id=turn.vip_id,
            cognitive_summary=decision.reason,
            evaluation=eval_dict,
            trigger_message_id=turn.telegram_message_id,
            photo_file_id=turn.photo_file_id,
        )
        await self._approvals.create_waiting(record)
        reason = self._sandbox_reason(turn.chat_id, decision.reason)

        # Look up the VIP display name for the draft header.
        vip_name: str | None = None
        if self._vip_store is not None:
            if turn.vip_id is not None:
                vip_rec = await self._vip_store.get_by_id(turn.vip_id)
            else:
                vip_rec = await self._vip_store.get_by_telegram_user_id(turn.chat_id)
            if vip_rec is not None:
                vip_name = vip_rec.display_name

        owner_mid = await self._notifier.notify_draft(
            DraftNotification(
                turn_id=turn_id,
                chat_id=turn.chat_id,
                vip_text=turn.text,
                draft_text=draft,
                reason=reason,
                vip_display_name=vip_name,
                evaluation_summary=_eval_summary(
                    decision, doctrine_relevant=relevant
                ),
                evaluation=eval_dict,
                business_connection_id=bc,
                reply_markup_spec={
                    "actions": ["approve", "correct", "escalate"],
                    "turn_id": str(turn_id),
                },
                show_quality_feedback=(
                    self._feature_quality_feedback_enabled
                    and turn.vip_id is not None
                ),
                photo_file_id=turn.photo_file_id,
            )
        )
        if owner_mid is not None:
            await self._approvals.set_owner_message_id(turn_id, owner_mid)
        logger.info(
            "draft_for_approval",
            extra={"turn_id": str(turn_id), "chat_id": turn.chat_id},
        )

    async def _store_autonomy_snapshot(
        self, turn: IncomingTurn, eval_dict: dict[str, Any]
    ) -> None:
        """Embed the Autonomía snapshot into the approval evaluation (best-effort).

        Only runs when a readiness provider is wired (recommendation feature
        on). A fault never breaks the approval flow; without a provider or with
        a failure the section is simply absent/fallback on the draft.
        """
        svc = self._autonomy_readiness_svc
        if svc is None:
            return
        try:
            snapshot = await svc.readiness_snapshot(turn.vip_id)
        except Exception:
            logger.exception(
                "autonomy_snapshot_store_failed",
                extra={"turn_id": str(turn.turn_id if hasattr(turn, "turn_id") else None)},
            )
            return
        if isinstance(snapshot, dict):
            eval_dict[AUTONOMY_KEY] = snapshot

    async def create_supervised_delivery_from_gray_zone(
        self,
        turn_id: UUID,
        query: GrayZoneQueryView,
        *,
        draft_override: str | None = None,
    ) -> bool:
        """Create a supervised PendingApproval from a resolved/expired gray zone draft.

        ``draft_override`` is the **regenerated** draft after doctrine
        rule→regen (force-inject). Never pass the raw owner rule as the VIP
        draft. When omitted, the persisted query draft is used (expiration /
        legacy timeout path).

        Synthesizes an ``IncomingTurn`` + minimal ``Decision`` from the turn
        record and the persisted gray zone query, reuses
        ``send_draft_for_approval`` to create the approval record and notify
        the owner, then transitions the turn ``GRAY_ZONE`` → ``PENDING_APPROVAL``.
        The approval creation + transition run under the per-chat lock
        (``coordinator.chat_scope``) so they serialize with doctrine resolve,
        the expiry job and owner callbacks.

        Fail-soft: returns False (with a log) when the turn is missing, the
        query does not belong to the turn, the query lacks a non-empty
        ``business_connection_id``, the draft is empty, or the turn is already
        terminal. Returns True when a supervised approval is in place — created
        now, or already ``waiting`` (idempotent, no second approval/DM). A
        ``cancelled`` leftover is deleted so retry can recreate (unique
        ``turn_id``). If ``send_draft_for_approval`` fails after persisting,
        the just-created approval is cancelled before the exception re-raises.
        If the transition fails (``TurnSupersededError`` or any other error),
        the approval just created is cancelled (only while still ``waiting``).
        """
        turn = await self._turns.get(turn_id)
        if turn is None:
            logger.info("gray_zone_delivery_missing_turn", extra={"turn_id": str(turn_id)})
            return False

        q_turn_id = getattr(query, "turn_id", None)
        if q_turn_id is not None and str(q_turn_id) != str(turn_id):
            logger.warning(
                "gray_zone_delivery_turn_mismatch",
                extra={
                    "turn_id": str(turn_id),
                    "query_turn_id": str(q_turn_id),
                },
            )
            return False

        bc = getattr(query, "business_connection_id", None) or ""
        if not bc.strip():
            logger.warning(
                "gray_zone_delivery_missing_bc",
                extra={"turn_id": str(turn_id), "query_id": str(getattr(query, "id", None))},
            )
            return False

        draft = (
            draft_override
            if draft_override is not None
            else (getattr(query, "draft", "") or "")
        )
        if not draft.strip():
            logger.info("gray_zone_delivery_empty_draft", extra={"turn_id": str(turn_id)})
            return False

        async with self._coordinator.chat_scope(turn.chat_id):
            fresh = await self._turns.get(turn_id)
            if fresh is None:
                logger.info(
                    "gray_zone_delivery_missing_turn",
                    extra={"turn_id": str(turn_id)},
                )
                return False
            if is_turn_status_terminal(fresh.status):
                logger.info(
                    "gray_zone_delivery_terminal_skip",
                    extra={"turn_id": str(turn_id), "status": fresh.status},
                )
                return False
            existing = await self._approvals.get_by_turn(turn_id)
            if existing is not None:
                if existing.status == "waiting":
                    logger.info(
                        "gray_zone_delivery_already_pending",
                        extra={
                            "turn_id": str(turn_id),
                            "approval_status": existing.status,
                        },
                    )
                    return True
                if existing.status == "cancelled":
                    # Clear unique(turn_id) so doctrine mark-fail compensate
                    # can re-enqueue on owner retry.
                    deleted = False
                    if hasattr(self._approvals, "delete_for_turn"):
                        try:
                            deleted = await self._approvals.delete_for_turn(turn_id)
                        except Exception:
                            logger.exception(
                                "gray_zone_delivery_delete_cancelled_error",
                                extra={"turn_id": str(turn_id)},
                            )
                            return False
                    if not deleted:
                        logger.warning(
                            "gray_zone_delivery_cancelled_not_deleted",
                            extra={"turn_id": str(turn_id)},
                        )
                        return False
                else:
                    # Non-waiting leftover (approved/corrected/…) on a live turn:
                    # do not re-create over it (unique turn_id).
                    logger.warning(
                        "gray_zone_delivery_existing_non_waiting",
                        extra={
                            "turn_id": str(turn_id),
                            "approval_status": existing.status,
                        },
                    )
                    return False

            incoming = IncomingTurn(
                turn_id=turn_id,
                chat_id=fresh.chat_id,
                vip_id=fresh.vip_id,
                text=(getattr(query, "question", "") or "").strip()
                or _NO_VIP_TEXT_PLACEHOLDER,
                telegram_message_id=fresh.trigger_message_id,
                business_connection_id=bc,
                channel_type=fresh.channel_type,
            )
            decision = Decision(
                action="approve",
                reason="gray_zone_resolved_by_doctrine",
                evaluation=EvaluationProfile(
                    naturalness=0.5, precision=0.5, doctrine=0.5,
                    consistency=0.5, safety=0.5, coverage=0.5, empathy=0.5,
                ),
                draft_text=draft,
            )
            try:
                await self.send_draft_for_approval(
                    incoming, decision, turn_id, doctrine_relevant=True
                )
            except Exception:
                # send_draft_for_approval persists the approval (waiting)
                # BEFORE the owner DM; if the DM (or anything after persist)
                # fails, cancel the just-created approval so callers never
                # leave a waiting orphan behind.
                await self._cancel_waiting_approval(turn_id)
                raise
            try:
                await self._coordinator.transition(
                    turn_id, TurnStatus.PENDING_APPROVAL
                )
            except TurnSupersededError:
                await self._cancel_waiting_approval(turn_id)
                logger.info(
                    "gray_zone_delivery_superseded",
                    extra={"turn_id": str(turn_id)},
                )
                return False
            except Exception:
                # Any other transition failure (e.g. transient DB error) must
                # not leave a live waiting approval — cancel and re-raise.
                await self._cancel_waiting_approval(turn_id)
                raise
        logger.info(
            "gray_zone_supervised_delivery_created",
            extra={"turn_id": str(turn_id)},
        )
        return True

    async def _cancel_waiting_approval(self, turn_id: UUID) -> None:
        """Best-effort cancel of a waiting approval (no-op when none/live)."""
        try:
            approval = await self._approvals.get_by_turn(turn_id)
        except Exception:
            logger.exception(
                "gray_zone_delivery_cancel_lookup_error",
                extra={"turn_id": str(turn_id)},
            )
            return
        if approval is not None and approval.status == "waiting":
            try:
                await self._approvals.mark_status(turn_id, "cancelled")
            except Exception:
                logger.exception(
                    "gray_zone_delivery_cancel_error",
                    extra={"turn_id": str(turn_id)},
                )

    async def _discard_doctrine_hold_if_any(self, turn_id: UUID) -> None:
        """Best-effort close of a residual gray-zone hold for a terminal turn.

        Used on no-op paths (turn already superseded/delivered/...) so a dead
        turn never leaves the VIP frozen behind an open doctrine query. Never
        raises; a cleanup failure only logs.
        """
        if self._gray_zone is None:
            return
        try:
            query = await self._gray_zone.get_hold_query_by_turn_id(turn_id)
        except Exception:
            log_swallowed(
                logger,
                "doctrine_hold_lookup_failed",
                turn_id=str(turn_id),
            )
            return
        if query is None:
            return
        try:
            await self._gray_zone.discard_and_close(query.id)
        except Exception:
            log_swallowed(
                logger,
                "doctrine_hold_discard_failed",
                turn_id=str(turn_id),
                query_id=str(query.id),
            )

    async def notify_info(self, text: str, *, chat_id: int | None = None) -> None:
        """Thin wrapper for operator/info notifications (e.g. Analyst schema fail)."""
        await self._notifier.notify_info(text, chat_id=chat_id)

    async def notify_escalation(
        self,
        turn: IncomingTurn,
        decision: Decision,
        turn_id: UUID,
    ) -> None:
        tipo = tipo_from_reason(decision.reason)
        reason = self._sandbox_reason(turn.chat_id, decision.reason)
        await self._escalations.create(
            turn_id,
            tipo=tipo,
            motivo=reason,
            business_connection_id=turn.business_connection_id,
        )
        await self._notifier.notify_escalation(
            EscalationNotification(
                turn_id=turn_id,
                chat_id=turn.chat_id,
                reason=reason,
                vip_text=turn.text,
                tipo=tipo,
                business_connection_id=turn.business_connection_id,
            )
        )
        await self._escalations.mark_notified(turn_id)
        # ROADMAP 5.7: append a one-line plain-text record to the audit log.
        _ensure_escalation_file_handler()
        logging.getLogger("diana.escalations").info(
            "turn=%s chat=%s vip_text=%r tipo=%s reason=%s",
            str(turn_id),
            turn.chat_id,
            (turn.text or "")[:200],
            tipo,
            reason,
        )
        logger.info(
            "escalation_notified",
            extra={"turn_id": str(turn_id), "chat_id": turn.chat_id},
        )

    async def send_doctrine_query(
        self,
        turn: IncomingTurn,
        decision: Decision,
        turn_id: UUID,
        query: GrayZoneQueryView,
        *,
        proposed_rule: str | None = None,
        proposed_reply: str | None = None,
        proposal_source: str | None = None,
        comprehension: Comprehension | Mapping[str, Any] | None = None,
        retrieved: Mapping[str, Any] | None = None,
        doctrine_relevant: bool | None = None,
    ) -> None:
        """Notify owner of a gray zone doctrine query (VIP frozen).

        Sends DM with the VIP's question, the draft, and reply markup
        for the owner to respond with doctrine guidance.
        Does NOT deliver to the VIP (VIP is frozen).

        FEATURE_GRAY_ZONE_PROPOSAL_ENABLED: optional system RULE proposal
        included in the DM (suggestion only). ``proposal_source`` records the
        origin (e.g. "gray_zone_proposal") for audit.

        Note: owner_mid is NOT persisted in F2 because the
        GrayZoneQuery model lacks an owner_message_id column. For F3/Item 4
        callback handlers, the handler looks up the open query by turn_id.
        """
        bc = (turn.business_connection_id or "").strip()
        if not bc:
            raise ValueError("business_connection_id is required for doctrine query")

        draft = decision.draft_text or ""
        query_id = query.id
        reason = self._sandbox_reason(turn.chat_id, decision.reason)

        reply_spec: dict = {
            "actions": ["respond_doctrine", "escalate_doctrine"],
            "turn_id": str(turn_id),
        }
        if query_id is not None:
            reply_spec["query_id"] = str(query_id)
        if proposed_rule:
            reply_spec["actions"] = [
                "use_proposal_doctrine",
                "respond_doctrine",
                "escalate_doctrine",
            ]

        try:
            owner_mid = await self._notifier.notify_doctrine(
                DoctrineNotification(
                    turn_id=turn_id,
                    chat_id=turn.chat_id,
                    vip_text=turn.text,
                    draft_text=draft,
                    reason=reason,
                    evaluation_summary=_eval_summary(
                        decision,
                        doctrine_relevant=_resolve_doctrine_relevant(
                            decision,
                            comprehension=comprehension,
                            retrieved=retrieved,
                            doctrine_relevant=doctrine_relevant,
                        ),
                    ),
                    business_connection_id=bc,
                    reply_markup_spec=reply_spec,
                    proposed_rule=proposed_rule,
                    proposed_reply=proposed_reply,
                    proposal_source=proposal_source,
                )
            )
        except Exception:
            logger.exception(
                "doctrine_notification_failed",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": turn.chat_id,
                    "query_id": str(query_id) if query_id else None,
                },
            )
            raise

        logger.info(
            "doctrine_query_notified",
            extra={
                "turn_id": str(turn_id),
                "chat_id": turn.chat_id,
                "query_id": str(query_id) if query_id else None,
                "owner_message_id": owner_mid,
            },
        )

    async def handle_approve(
        self,
        turn_id: UUID,
        *,
        actor_id: int | None = None,
        on_progress: DeliveryProgressCallback | None = None,
    ) -> DeliveryResult | None:
        self._assert_owner(actor_id)
        return await self._resolve_and_deliver(
            turn_id, corrected_text=None, on_progress=on_progress
        )

    async def classify_approve_noop(self, turn_id: UUID) -> str:
        """Map a no-op approve (``handle_approve`` → None) to an honest UX token.

        Tokens are consumed by owner callbacks for distinct alerts instead of a
        single generic "already resolved" toast.
        """
        turn = await self._turns.get(turn_id)
        if turn is None:
            return "stale_gone"
        status = turn.status
        if is_turn_status_terminal(status):
            if status in {
                TurnStatus.SUPERSEDED.value,
                "superseded",
            }:
                return "stale_replaced"
            if status in {
                TurnStatus.DELIVERED.value,
                "delivered",
            }:
                return "stale_already_sent"
            if status in {
                TurnStatus.ESCALATED.value,
                "escalated",
            }:
                return "stale_resolved"
            return "stale_resolved"
        approval = await self._approvals.get_by_turn(turn_id)
        if approval is None or approval.status not in {"waiting", "claimed"}:
            return "stale_cancelled"
        # Live turn + open approval but claim lost (concurrent owner action).
        return "stale"

    async def _correct_core(
        self,
        turn_id: UUID,
        corrected_text: str,
        *,
        actor_id: int | None = None,
        severity: str | None = "moderate",
    ) -> tuple[DeliveryResult | None, UUID | None]:
        self._assert_owner(actor_id)
        if not (corrected_text or "").strip():
            raise ValueError("corrected_text must be non-empty")
        stripped = corrected_text.strip()
        # H7.1 timing A: capture correction before claim/deliver (orphan pending OK).
        correction_persisted = False
        candidate_id: UUID | None = None
        if self._staging is not None:
            turn = await self._turns.get(turn_id)
            approval = await self._approvals.get_by_turn(turn_id)
            if turn is not None and approval is not None:
                turn_text = await self._resolve_trigger_text(
                    turn.chat_id, turn.trigger_message_id
                )
                try:
                    saved = await self._staging.save_correction(
                        turn_id,
                        original_draft=approval.draft_text,
                        corrected_text=stripped,
                        context={
                            "chat_id": turn.chat_id,
                            "turn_text": turn_text,
                        },
                        chat_id=turn.chat_id,
                        channel_type=turn.channel_type,
                    )
                    # Sandbox skips persistence (returns None without insert);
                    # only a genuinely persisted correction counts (S6).
                    correction_persisted = saved is not None
                    if saved is not None:
                        candidate_id = saved.id
                except Exception:
                    logger.exception(
                        "staging_save_correction_failed",
                        extra={"turn_id": str(turn_id)},
                    )
        # Evo-Agente Fase 5: owner correction → trust-budget decrement (event
        # source, A2). Best-effort: a trust failure must not break the delivery
        # path. ``record_correction`` resolves (vip_id, category) by turn_id and
        # no-ops for unclassified / non-VIP / non-autonomous turns. The decrement
        # fires ONLY when the correction actually persisted — a swallowed
        # ``save_correction`` failure must not penalize trust for a correction
        # that never landed (review round 1, S6). Flag OFF → trust_budget None
        # → no-op (byte-identical).
        if self._trust_budget is not None and correction_persisted:
            # Fila 4 readiness ON → the desacuerdo event from record_outcome
            # is the single trust decrement (record_correction would double-
            # count against it). Byte-identical pre-Fila-4 behavior otherwise.
            # KNOWN STATE (SPEC-EA-07, not a new bug): with quality ON + readiness
            # OFF both paths run — path A here AND path B in _resolve_and_deliver —
            # each applying the SAME severity, so the pre-existing double count is
            # identical to today. The gate below is intentionally untouched.
            if not self._autonomy_readiness:
                try:
                    await self._trust_budget.record_correction(
                        turn_id, severity=severity
                    )
                except Exception:
                    logger.exception(
                        "trust_budget_correction_failed",
                        extra={"turn_id": str(turn_id)},
                    )
        delivery = await self._resolve_and_deliver(
            turn_id, corrected_text=stripped, severity=severity
        )
        return delivery, candidate_id

    async def handle_correct(
        self,
        turn_id: UUID,
        corrected_text: str,
        *,
        actor_id: int | None = None,
        severity: str = "moderate",
    ) -> DeliveryResult | None:
        delivery, _ = await self._correct_core(
            turn_id, corrected_text, actor_id=actor_id, severity=severity
        )
        return delivery

    async def handle_correct_with_candidate(
        self,
        turn_id: UUID,
        corrected_text: str,
        *,
        actor_id: int | None = None,
        severity: str | None = "moderate",
    ) -> tuple[DeliveryResult | None, UUID | None]:
        return await self._correct_core(
            turn_id, corrected_text, actor_id=actor_id, severity=severity
        )

    async def handle_mark_gold(
        self,
        turn_id: UUID,
        *,
        scope: Literal["global", "vip"],
        actor_id: int,
        on_progress: DeliveryProgressCallback | None = None,
    ) -> DeliveryResult | None:
        self._assert_owner(actor_id)
        self._require_quality_feedback()
        turn = await self._turns.get(turn_id)
        if turn is None:
            return None
        if turn.channel_type == "atencion":
            raise AtencionPromoteBlocked(
                "atencion candidates cannot be promoted to the VIP example bank"
            )
        approval = await self._approvals.get_by_turn(turn_id)
        draft = approval.draft_text if approval is not None else ""
        turn_text = await self._resolve_trigger_text(turn.chat_id, turn.trigger_message_id)
        delivery = await self.handle_approve(
            turn_id, actor_id=actor_id, on_progress=on_progress
        )
        if delivery is None or delivery.cancelled:
            return delivery
        if self._staging is None:
            return delivery
        await self._staging.insert_gold_example(
            turn_text=turn_text,
            draft_text=draft,
            corrected_text=draft,
            context={"chat_id": turn.chat_id, "turn_text": turn_text},
            vip_id=self._scope_vip_id(turn, scope),
            channel_type=turn.channel_type,
            chat_id=turn.chat_id,
        )
        logger.info(
            "gold_example_marked",
            extra={
                "turn_id": str(turn_id),
                "scope": scope,
            },
        )
        return delivery

    async def handle_reprimand(
        self,
        turn_id: UUID,
        corrected_text: str,
        *,
        mode: Literal["policy", "counter_example"],
        scope: Literal["global", "vip"],
        actor_id: int,
        candidate_id: UUID | None = None,
    ) -> DeliveryResult | None:
        self._assert_owner(actor_id)
        self._require_quality_feedback()
        if mode not in {"policy", "counter_example"} or scope not in {"global", "vip"}:
            raise ValueError("invalid mode/scope")
        turn = await self._turns.get(turn_id)
        if turn is None:
            return None
        if turn.channel_type == "atencion":
            raise AtencionPromoteBlocked(
                "atencion candidates cannot be promoted to the VIP example bank"
            )
        delivery: DeliveryResult | None
        if candidate_id is None:
            # SPEC-EA-07 (review round 1): the reprimand flow never shows the
            # sv: picker, so it must NOT fabricate a "moderate" tag. Threading
            # severity=None keeps the shadow distribution honest: the ledger
            # correction_severity stays None and the trust path uses the
            # fallback decrement (flag OFF/ON byte-identical math).
            delivery, candidate_id = await self._correct_core(
                turn_id, corrected_text, actor_id=actor_id, severity=None
            )
            if delivery is None or delivery.cancelled:
                return delivery
        else:
            delivery = None  # promote-only; item 4 already delivered
        if candidate_id is None or self._staging is None:
            return delivery
        vip_id = self._scope_vip_id(turn, scope)
        if mode == "counter_example":
            await self._staging.promote_to_counter_example(candidate_id, vip_id=vip_id)
        else:
            turn_text = await self._resolve_trigger_text(
                turn.chat_id, turn.trigger_message_id
            )
            trigger = " ".join((turn_text or "").split())
            trigger = trigger[:80] if trigger else "reprimenda"
            await self._staging.promote_to_policy(
                candidate_id,
                trigger=trigger,
                rule=(corrected_text or "").strip(),
                scope="all",
                vip_id=vip_id,
            )
        logger.info(
            "reprimand_promoted",
            extra={
                "turn_id": str(turn_id),
                "candidate_id": str(candidate_id),
                "mode": mode,
                "scope": scope,
            },
        )
        return delivery

    async def _resolve_trigger_text(
        self,
        chat_id: int,
        trigger_message_id: int | None,
    ) -> str:
        """Resolve VIP trigger text from history by telegram_message_id (H7)."""
        if self._history is None or trigger_message_id is None:
            return ""
        try:
            recent = await self._history.get_recent(chat_id, limit=20)
        except Exception:
            logger.exception(
                "owner_history_trigger_lookup_failed",
                extra={"chat_id": chat_id, "trigger_message_id": trigger_message_id},
            )
            return ""
        matches: list[dict[str, Any]] = []
        for row in recent:
            if not isinstance(row, dict):
                continue
            if row.get("telegram_message_id") == trigger_message_id:
                matches.append(row)
        if not matches:
            return ""
        for row in matches:
            if row.get("role") == "vip":
                return str(row.get("text") or "")
        return str(matches[0].get("text") or "")

    async def is_pending_approval(self, turn_id: UUID) -> bool:
        """True when turn is non-terminal and has a waiting approval."""
        turn = await self._turns.get(turn_id)
        if turn is None or is_turn_status_terminal(turn.status):
            return False
        approval = await self._approvals.get_by_turn(turn_id)
        return approval is not None and approval.status == "waiting"

    async def get_approval(self, turn_id: UUID) -> ApprovalRecord | None:
        """Return the approval record for a turn, or None when missing."""
        return await self._approvals.get_by_turn(turn_id)

    async def resolve_vip_display_name(
        self, vip_id: UUID | None, chat_id: int
    ) -> str | None:
        """Best-effort VIP display name for the owner draft body."""
        return await resolve_vip_display_name(self._vip_store, vip_id, chat_id)

    async def mark_false_positive(
        self,
        turn_id: UUID,
        *,
        actor_id: int | None = None,
    ) -> bool:
        """Record owner mark that an escalation was a false positive (metrics).

        Thin entry point — no Telegram UI required. Returns False when the
        mark store is not wired. Sandbox test window: the mark is NOT
        persisted (isolation) — test feedback must not pollute real metrics.
        """
        self._assert_owner(actor_id)
        if self._fp_marks is None:
            logger.info(
                "mark_false_positive_no_store",
                extra={"turn_id": str(turn_id)},
            )
            return False
        turn = await self._turns.get(turn_id)
        if (
            turn is not None
            and self._sandbox is not None
            and self._sandbox.is_active(turn.chat_id)  # type: ignore[union-attr]
        ):
            logger.info(
                "false_positive_skipped_sandbox",
                extra={"turn_id": str(turn_id), "chat_id": turn.chat_id},
            )
            return True
        await self._fp_marks.mark(turn_id)
        logger.info(
            "false_positive_marked",
            extra={"turn_id": str(turn_id)},
        )
        return True

    async def mark_false_positive_and_resume(
        self,
        turn_id: UUID,
        *,
        actor_id: int | None = None,
    ) -> FpResumeOutcome:
        """Owner triage: mark the escalation as false positive and continue.

        AGENTS §4.21 / REQ-ESC-04. The metric mark is always recorded first, so
        a resume fault never loses the owner's triage. When the feature flag is
        ON and the turn is still ``escalated``, the normal supervised flow
        continues: the draft the pipeline already generated is reused
        (zero LLM cost, the common semantic case) and, when there is none (H4
        ``pregunta_repetida``, deterministic escalations), the pipeline runs
        again for the same turn.

        Fail-closed cases never produce a draft DM: an escalation by
        ``safety_below_threshold`` (an unsafe draft is never enqueued — same
        rule as the doctrine regen), a chat whose newer VIP message already owns
        the flow, a second tap while this turn's resume is still running, a
        missing business connection or missing VIP text. When the regenerated
        decision asks for doctrine, the resume opens the gray zone (query +
        doctrine DM) instead of fail-closing like §4.5 doctrine regen.

        Fail-soft: resume faults return an honest status and are logged, never
        raised. The mark store failing keeps ``mark_false_positive``'s contract
        (``marked=False``) so the caller can report a real triage error.
        """
        self._assert_owner(actor_id)
        marked = await self.mark_false_positive(turn_id, actor_id=actor_id)
        if not marked:
            return FpResumeOutcome(
                marked=False, status=RESUME_MARKED_ONLY, detail="mark_unavailable"
            )
        if not self._feature_escalation_fp_draft_enabled:
            return FpResumeOutcome(
                marked=True, status=RESUME_MARKED_ONLY, detail="flag_off"
            )

        try:
            turn = await self._turns.get(turn_id)
            if turn is None:
                return self._fp_not_resumed("missing_turn", turn_id=turn_id)
            if turn.status != TurnStatus.ESCALATED.value:
                # ``delivered`` is the durable close after a successful manual
                # reply (or an approve): same owner-facing key as the
                # process-local intervention flag so a restart still says she
                # already answered. Other non-escalated statuses stay stale.
                detail = (
                    "owner_intervened"
                    if turn.status == TurnStatus.DELIVERED.value
                    else "not_escalated"
                )
                return self._fp_not_resumed(
                    detail, turn_id=turn_id, chat_id=turn.chat_id
                )
            if self._coordinator.is_owner_intervened(turn.chat_id):
                # She already wrote in that VIP chat after this escalation: the
                # case is hers, so a draft would only duplicate her reply.
                return self._fp_not_resumed(
                    "owner_intervened", turn_id=turn_id, chat_id=turn.chat_id
                )
            if turn_id in self._fp_resume_inflight:
                return self._fp_not_resumed(
                    "already_running", turn_id=turn_id, chat_id=turn.chat_id
                )
            self._fp_resume_inflight.add(turn_id)
            try:
                return await self._resume_escalation(turn)
            finally:
                self._fp_resume_inflight.discard(turn_id)
        except Exception:
            logger.exception(
                "escalation_fp_resume_failed",
                extra={"turn_id": str(turn_id)},
            )
            return FpResumeOutcome(
                marked=True, status=RESUME_MARKED_ONLY, detail="error"
            )

    def _fp_not_resumed(
        self,
        detail: str,
        *,
        turn_id: UUID,
        chat_id: int | None = None,
        status: str = RESUME_MARKED_ONLY,
        extra: Mapping[str, Any] | None = None,
    ) -> FpResumeOutcome:
        """Fail-closed outcome + log: a mark the owner made never ends silently.

        Returns ``marked=True`` for every reason except a mark-store fault
        (built by the caller) — the triage mark is already recorded.
        ``extra`` carries the underlying machine reason when the owner-facing
        detail is a normalized token.
        """
        log_extra: dict[str, Any] = {
            "turn_id": str(turn_id),
            "chat_id": chat_id,
            "reason": detail,
            "status": status,
        }
        if extra:
            log_extra.update(extra)
        logger.info("escalation_fp_not_resumed", extra=log_extra)
        return FpResumeOutcome(marked=True, status=status, detail=detail)

    async def _read_resume_trace(self, turn_id: UUID) -> dict[str, Any] | None:
        """Best-effort trace read for the resume (never raises).

        The injected trace store is the delivery writer (``SqlTraceStore``
        implements TraceReader too), so no extra dependency is needed.
        """
        if not isinstance(self._traces, TraceReader):
            return None
        try:
            return await self._traces.get_full_trace(turn_id)
        except Exception:
            log_swallowed(
                logger, "escalation_fp_resume_trace_failed", turn_id=str(turn_id)
            )
            return None

    async def _resume_business_connection(
        self, turn_id: UUID, approval: Any | None = None
    ) -> str | None:
        """BC for the resumed draft: escalation ledger, then approval row.

        The escalation that notified the owner persists the BC (migration 032);
        an owner-escalated draft never writes an escalation event, but its
        approval row carries the BC the draft was created with.
        """
        try:
            bc = await self._escalations.get_business_connection_id(turn_id)
        except Exception:
            log_swallowed(
                logger, "escalation_fp_resume_bc_failed", turn_id=str(turn_id)
            )
            bc = None
        if isinstance(bc, str) and bc.strip():
            return bc.strip()
        if approval is None:
            approval = await self._resume_approval_row(turn_id)
        fallback = getattr(approval, "business_connection_id", None)
        if isinstance(fallback, str) and fallback.strip():
            return fallback.strip()
        return None

    async def _resume_approval_row(self, turn_id: UUID) -> Any | None:
        """Approval row of the turn, when there is one (best-effort)."""
        try:
            return await self._approvals.get_by_turn(turn_id)
        except Exception:
            log_swallowed(
                logger, "escalation_fp_resume_approval_failed", turn_id=str(turn_id)
            )
            return None

    async def _resume_escalation_motivo(self, turn_id: UUID) -> str | None:
        """Persisted escalation motivo (durable safety fallback, best-effort)."""
        try:
            motivo = await self._escalations.get_motivo(turn_id)
        except Exception:
            log_swallowed(
                logger, "escalation_fp_resume_motivo_failed", turn_id=str(turn_id)
            )
            return None
        return motivo.strip() if isinstance(motivo, str) else None

    async def _resume_escalation(self, turn: TurnRecord) -> FpResumeOutcome:
        """Resolve the resumed draft and enqueue it (never called unguarded)."""
        turn_id = turn.id
        chat_id = turn.chat_id
        approval = await self._resume_approval_row(turn_id)
        bc = await self._resume_business_connection(turn_id, approval)
        if bc is None:
            return self._fp_not_resumed(
                "no_business_connection", turn_id=turn_id, chat_id=chat_id
            )

        trace = await self._read_resume_trace(turn_id)
        plan = plan_fp_resume(
            trace=trace,
            escalation_motivo=await self._resume_escalation_motivo(turn_id),
        )
        if plan.action == "blocked_safety":
            return self._fp_not_resumed(
                plan.reason or "safety_below_threshold",
                turn_id=turn_id,
                chat_id=chat_id,
                status=RESUME_BLOCKED_SAFETY,
            )

        vip_text = await self._resolve_trigger_text(chat_id, turn.trigger_message_id)
        incoming = IncomingTurn(
            turn_id=turn_id,
            chat_id=chat_id,
            vip_id=turn.vip_id,
            text=(vip_text or "").strip() or _NO_VIP_TEXT_PLACEHOLDER,
            telegram_message_id=turn.trigger_message_id,
            business_connection_id=bc,
            channel_type=(
                "atencion" if turn.channel_type == "atencion" else "vip"
            ),
            # The turn does not persist the image; an owner-escalated draft left
            # it in its approval row, so the resumed DM can still attach it.
            photo_file_id=getattr(approval, "photo_file_id", None),
        )
        if plan.action == "reuse_trace_draft":
            return await self._enqueue_resumed_draft(
                turn=turn,
                incoming=incoming,
                decision=self._reuse_trace_decision(plan=plan, trace=trace),
                comprehension=plan.comprehension,
                retrieved=plan.retrieved,
            )
        generated = await self._generate_resume_decision(
            incoming, plan=plan, vip_text=vip_text, trace=trace
        )
        if isinstance(generated, FpResumeOutcome):
            return generated
        decision, comprehension, retrieved, open_gray_zone = generated
        if open_gray_zone:
            return await self._open_gray_zone_from_fp_resume(
                turn=turn,
                incoming=incoming,
                decision=decision,
                comprehension=comprehension,
                retrieved=retrieved,
            )
        return await self._enqueue_resumed_draft(
            turn=turn,
            incoming=incoming,
            decision=decision,
            comprehension=comprehension,
            retrieved=retrieved,
        )

    def _reuse_trace_decision(
        self, *, plan: FpResumePlan, trace: Mapping[str, Any] | None
    ) -> Decision:
        """Supervised decision from the draft the pipeline already generated."""
        return Decision(
            action="approve",
            reason=FP_RESUME_REASON,
            evaluation=plan.evaluation or evaluation_from_trace(trace),
            draft_text=plan.draft_text,
        )

    async def _generate_resume_decision(
        self,
        incoming: IncomingTurn,
        *,
        plan: FpResumePlan,
        vip_text: str,
        trace: Mapping[str, Any] | None,
    ) -> (
        tuple[Decision, Mapping[str, Any] | None, Mapping[str, Any] | None, bool]
        | FpResumeOutcome
    ):
        """Run the pipeline for this turn, or a fail-closed outcome.

        Generation happens OUTSIDE the chat lock (same as the doctrine regen) so
        a slow model call never blocks the VIP's next message from minting.
        The trailing bool is True when the regenerated decision must open the
        gray zone (``consult_doctrine``) instead of the approval queue.
        """
        if plan.action != "generate":
            # Defensive: the caller only routes "generate" here. Any other plan
            # means this turn has no draft to show, never a fabricated one.
            return self._fp_not_resumed(
                "no_draft_generated",
                turn_id=incoming.turn_id,
                chat_id=incoming.chat_id,
            )
        if not (vip_text or "").strip():
            # Generation uses the VIP message as pipeline input; without it we
            # fail closed rather than fabricate one (bounded history window).
            return self._fp_not_resumed(
                "no_vip_text", turn_id=incoming.turn_id, chat_id=incoming.chat_id
            )
        if self._director is None:
            return self._fp_not_resumed(
                "no_director", turn_id=incoming.turn_id, chat_id=incoming.chat_id
            )
        if trace is not None:
            # The regeneration overwrites this turn's persisted decision, so the
            # escalation's own reason is recorded first (audit trail).
            logger.info(
                "escalation_fp_resume_regenerating",
                extra={
                    "turn_id": str(incoming.turn_id),
                    "chat_id": incoming.chat_id,
                    "escalation_reason": plan.reason,
                },
            )
        try:
            generated = await self._director.handle_turn(
                incoming, skip_repetition_guard=True
            )
        except TurnSupersededError:
            return self._fp_not_resumed(
                "superseded", turn_id=incoming.turn_id, chat_id=incoming.chat_id
            )
        generated_plan = plan_from_generated_decision(
            action=str(getattr(generated, "action", "") or ""),
            reason=str(getattr(generated, "reason", "") or ""),
            draft_text=str(getattr(generated, "draft_text", "") or ""),
        )
        evaluation = getattr(generated, "evaluation", None)
        fresh_trace = await self._read_resume_trace(incoming.turn_id)
        comprehension = (fresh_trace or {}).get("comprehension") or plan.comprehension
        retrieved = (fresh_trace or {}).get("retrieved") or plan.retrieved
        eval_profile = (
            evaluation
            if isinstance(evaluation, EvaluationProfile)
            else evaluation_from_trace(fresh_trace or trace)
        )
        if generated_plan.action == "open_gray_zone":
            # Keep consult_doctrine on the Decision so the doctrine DM shows the
            # real reason; do not rewrite to the FP-resume display token.
            return (
                Decision(
                    action="consult_doctrine",
                    reason=generated_plan.reason or "doctrine_not_found",
                    evaluation=eval_profile,
                    draft_text=generated_plan.draft_text,
                ),
                comprehension,
                retrieved,
                True,
            )
        if generated_plan.action != "reuse_trace_draft":
            # Empty draft / safety: honest token; raw reason stays in the log.
            # Safety status comes from the reason (empty draft blocks action first).
            status = (
                RESUME_BLOCKED_SAFETY
                if generated_plan.reason == SAFETY_ESCALATION_REASON
                else RESUME_MARKED_ONLY
            )
            return self._fp_not_resumed(
                "no_draft_generated",
                turn_id=incoming.turn_id,
                chat_id=incoming.chat_id,
                status=status,
                extra={
                    "decision_action": generated_plan.action,
                    "decision_reason": generated_plan.reason,
                },
            )
        return (
            Decision(
                action="approve",
                reason=FP_RESUME_REASON,
                evaluation=eval_profile,
                draft_text=generated_plan.draft_text,
            ),
            comprehension,
            retrieved,
            False,
        )

    async def _fp_resume_chat_ready(
        self, turn_id: UUID, chat_id: int
    ) -> FpResumeOutcome | None:
        """Busy/stale guards shared by draft enqueue and gray-zone open.

        Must run under ``chat_scope``. Returns a fail-closed outcome when the
        chat is not ready to resume this escalation; ``None`` means proceed.
        """
        fresh = await self._turns.get(turn_id)
        if fresh is None or fresh.status != TurnStatus.ESCALATED.value:
            return self._fp_not_resumed(
                "stale", turn_id=turn_id, chat_id=chat_id
            )
        live = await self._turns.list_non_terminal(chat_id)
        if live:
            # One live turn per chat is non-negotiable: a newer VIP message
            # owns the chat, so this escalation stays closed.
            return self._fp_not_resumed(
                "chat_busy", turn_id=turn_id, chat_id=chat_id
            )
        latest = await self._turns.latest_turn_id(chat_id)
        if latest is not None and latest != turn_id:
            # A newer message of this chat was already attended and maybe
            # delivered — delivered turns are invisible to
            # ``list_non_terminal``, so this is the only place that stops an
            # old escalation from answering *after* the newer one.
            return self._fp_not_resumed(
                "stale", turn_id=turn_id, chat_id=chat_id
            )
        return None

    async def _maybe_fp_gray_zone_proposal(
        self,
        *,
        question: str,
        draft: str,
        channel_type: str,
    ) -> tuple[str | None, str | None, str | None]:
        """Optional RULE proposal for FP→gray-zone (fail-open; mirrors orch)."""
        if (
            not self._feature_gray_zone_proposal_enabled
            or self._gray_zone_proposal is None
        ):
            return (None, None, None)
        try:
            proposal = await self._gray_zone_proposal.generate(  # type: ignore[union-attr]
                question=question,
                draft=draft,
                channel_type=channel_type,
            )
        except Exception:
            logger.exception(
                "fp_gray_zone_proposal_generate_error",
                extra={"channel_type": channel_type},
            )
            return (None, None, None)
        if proposal is None:
            return (None, None, None)
        rule = (getattr(proposal, "proposed_rule", "") or "").strip()
        if not rule:
            return (None, None, None)
        return (
            rule,
            (getattr(proposal, "proposed_reply", "") or "").strip() or None,
            "gray_zone_proposal",
        )

    async def _open_gray_zone_from_fp_resume(
        self,
        *,
        turn: TurnRecord,
        incoming: IncomingTurn,
        decision: Decision,
        comprehension: Mapping[str, Any] | None,
        retrieved: Mapping[str, Any] | None,
    ) -> FpResumeOutcome:
        """Open a gray-zone consult after FP regen returned ``consult_doctrine``.

        BUG-3 order: create_query + notify doctrine BEFORE CAS to ``gray_zone``.
        Never uses ``coordinator.transition`` from ``escalated`` (terminal latch).
        On notify failure: discard the query and leave the turn escalated.
        """
        turn_id = turn.id
        chat_id = turn.chat_id
        gz = self._gray_zone
        if gz is None:
            return self._fp_not_resumed(
                "gray_zone_unavailable",
                turn_id=turn_id,
                chat_id=chat_id,
            )
        # Sandbox without vip_id: orchestrator demotes consult; FP must not open
        # a VIP-less query in sandbox either (mark isolation already handled).
        sandbox_active = (
            self._sandbox is not None
            and bool(getattr(self._sandbox, "is_active", lambda _c: False)(chat_id))
        )
        if sandbox_active and incoming.vip_id is None:
            return self._fp_not_resumed(
                "gray_zone_unavailable",
                turn_id=turn_id,
                chat_id=chat_id,
                extra={"reason": "sandbox_no_vip_doctrine"},
            )

        prop_rule, prop_reply, prop_source = await self._maybe_fp_gray_zone_proposal(
            question=incoming.text or "",
            draft=decision.draft_text or "",
            channel_type=incoming.channel_type or "vip",
        )

        async with self._coordinator.chat_scope(chat_id):
            blocked = await self._fp_resume_chat_ready(turn_id, chat_id)
            if blocked is not None:
                return blocked
            # F20-ish: do not mint a second open query for the same chat.
            try:
                already = await gz.get_open_query_by_chat_id(chat_id)
            except Exception:
                log_swallowed(
                    logger,
                    "fp_gray_zone_recheck_failed",
                    turn_id=str(turn_id),
                    chat_id=chat_id,
                )
                already = None
            if already is not None:
                return self._fp_not_resumed(
                    "chat_busy", turn_id=turn_id, chat_id=chat_id
                )

            query = await gz.create_query(
                vip_id=incoming.vip_id,
                turn_id=turn_id,
                question=incoming.text or "",
                draft=decision.draft_text or "",
                chat_id=chat_id,
                business_connection_id=incoming.business_connection_id,
                proposed_rule=prop_rule,
                proposed_reply=prop_reply,
                proposal_source=prop_source,
            )
            try:
                await self.send_doctrine_query(
                    incoming,
                    decision,
                    turn_id,
                    query,  # type: ignore[arg-type]
                    proposed_rule=prop_rule,
                    proposed_reply=prop_reply,
                    proposal_source=prop_source,
                    comprehension=comprehension,
                    retrieved=retrieved,
                )
            except Exception:
                try:
                    await gz.discard_and_close(query.id)  # type: ignore[union-attr]
                except Exception:
                    log_swallowed(
                        logger,
                        "fp_doctrine_discard_failed",
                        turn_id=str(turn_id),
                        chat_id=chat_id,
                        query_id=str(getattr(query, "id", None)),
                    )
                return self._fp_not_resumed(
                    "doctrine_notify_failed",
                    turn_id=turn_id,
                    chat_id=chat_id,
                )
            try:
                reopened = await self._turns.reopen_from_escalated(
                    turn_id, status=TurnStatus.GRAY_ZONE.value
                )
            except Exception:
                try:
                    await gz.discard_and_close(query.id)  # type: ignore[union-attr]
                except Exception:
                    log_swallowed(
                        logger,
                        "fp_gray_zone_reopen_discard_failed",
                        turn_id=str(turn_id),
                        chat_id=chat_id,
                        query_id=str(getattr(query, "id", None)),
                    )
                raise
            if reopened is None:
                try:
                    await gz.discard_and_close(query.id)  # type: ignore[union-attr]
                except Exception:
                    log_swallowed(
                        logger,
                        "fp_gray_zone_reopen_lost_discard_failed",
                        turn_id=str(turn_id),
                        chat_id=chat_id,
                        query_id=str(getattr(query, "id", None)),
                    )
                return self._fp_not_resumed(
                    "reopen_lost", turn_id=turn_id, chat_id=chat_id
                )
        logger.info(
            "escalation_fp_opened_gray_zone",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "query_id": str(getattr(query, "id", None)),
            },
        )
        return FpResumeOutcome(
            marked=True, status=RESUME_OPENED_GRAY_ZONE, detail="opened_gray_zone"
        )

    async def _enqueue_resumed_draft(
        self,
        *,
        turn: TurnRecord,
        incoming: IncomingTurn,
        decision: Decision,
        comprehension: Mapping[str, Any] | None,
        retrieved: Mapping[str, Any] | None,
    ) -> FpResumeOutcome:
        """Create the waiting approval and reopen the escalated turn (locked).

        Mirrors ``create_supervised_delivery_from_gray_zone``: approval creation
        and the status change run under the per-chat lock, and a failure after
        persisting cancels the just-created approval so no orphan stays behind.
        """
        turn_id = turn.id
        chat_id = turn.chat_id
        async with self._coordinator.chat_scope(chat_id):
            blocked = await self._fp_resume_chat_ready(turn_id, chat_id)
            if blocked is not None:
                return blocked
            existing = await self._approvals.get_by_turn(turn_id)
            if existing is not None and existing.status != "waiting":
                if existing.status != "cancelled":
                    return self._fp_not_resumed(
                        "approval_exists", turn_id=turn_id, chat_id=chat_id
                    )
                # Clear unique(turn_id) so a retry can recreate the approval.
                deleted = False
                delete_for_turn = getattr(self._approvals, "delete_for_turn", None)
                if callable(delete_for_turn):
                    try:
                        deleted = await delete_for_turn(turn_id)
                    except Exception:
                        logger.exception(
                            "escalation_fp_resume_delete_cancelled_error",
                            extra={"turn_id": str(turn_id)},
                        )
                if not deleted:
                    return self._fp_not_resumed(
                        "cancelled_not_deleted", turn_id=turn_id, chat_id=chat_id
                    )
            if existing is None or existing.status != "waiting":
                try:
                    await self.send_draft_for_approval(
                        incoming,
                        decision,
                        turn_id,
                        comprehension=comprehension,
                        retrieved=retrieved,
                    )
                except Exception:
                    await self._cancel_waiting_approval(turn_id)
                    raise
            try:
                reopened = await self._turns.reopen_from_escalated(turn_id)
            except Exception:
                # A fault moving the status must not leave a waiting approval
                # that no live turn backs (mirror the gray-zone compensation).
                await self._cancel_waiting_approval(turn_id)
                raise
            if reopened is None:
                await self._cancel_waiting_approval(turn_id)
                return self._fp_not_resumed(
                    "reopen_lost", turn_id=turn_id, chat_id=chat_id
                )
        logger.info(
            "escalation_fp_resumed",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "draft_chars": len(decision.draft_text or ""),
            },
        )
        return FpResumeOutcome(marked=True, status=RESUME_RESUMED)

    async def handle_escalation_reply(
        self,
        turn_id: UUID,
        text: str,
        *,
        actor_id: int | None = None,
    ) -> DeliveryResult | None:
        """Deliver a free-text owner reply to the escalated chat.

        The escalation means Diana did NOT answer; the owner takes over by
        writing the response and this method delivers it to the VIP chat
        through the BehaviorEngine (same delivery path as an approved draft).
        A successful delivery is the owner's answer for this turn: it marks her
        intervention and cancels a draft still waiting here, so a later
        false-positive tap or an approval never reaches the VIP twice.
        Returns None when the turn is missing.
        """
        self._assert_owner(actor_id)
        stripped = (text or "").strip()
        if not stripped:
            raise ValueError("reply text must be non-empty")
        turn = await self._turns.get(turn_id)
        if turn is None:
            logger.info(
                "escalation_reply_missing_turn",
                extra={"turn_id": str(turn_id)},
            )
            return None
        if self._behavior is None:
            logger.error(
                "escalation_reply_behavior_not_wired",
                extra={"turn_id": str(turn_id)},
            )
            return None
        # The turn/approval rows do not carry the business connection; the
        # escalation record stores it at notify time (migration 032).
        bc = ""
        if self._escalations is not None:
            try:
                stored = await self._escalations.get_business_connection_id(turn_id)
                bc = stored or ""
            except Exception:
                log_swallowed(
                    logger,
                    "escalation_reply_bc_lookup_failed",
                    turn_id=str(turn_id),
                )
        bc = bc.strip()
        if not bc:
            logger.info(
                "escalation_reply_missing_bc",
                extra={"turn_id": str(turn_id), "chat_id": turn.chat_id},
            )
            return None
        advanced = self._feature_advanced_behavior
        mode = self._effective_delivery_mode(turn.chat_id)
        ctx = DeliveryContext(
            chat_id=turn.chat_id,
            business_connection_id=bc,
            vip_id=turn.vip_id,
            mode=mode,
            is_frozen=False,
            skip_initial_delay=True,
            allow_split=advanced,
            allow_human_quirks=advanced,
            split_chars=4096,
        )
        logger.info(
            "escalation_reply_send",
            extra={
                "turn_id": str(turn_id),
                "chat_id": turn.chat_id,
                "vip_id": str(turn.vip_id) if turn.vip_id else None,
            },
        )
        result = await self._behavior.deliver([stripped], ctx, turn_id)
        if getattr(result, "success", False):
            # The manual reply is the owner's answer for this turn: a later
            # false-positive tap must see it (the in-memory flag is cleared on
            # the next ``begin_turn``, the semantics the rest of the system
            # uses) and a draft she left waiting must not be delivered on top
            # of it. Persist ``delivered`` so a process restart cannot reopen
            # the case via FP resume (``mark_owner_intervened`` alone dies with
            # the process; ``reopen_from_escalated`` refuses delivered).
            self._coordinator.mark_owner_intervened(turn.chat_id)
            await self._cancel_waiting_approval(turn_id)
            try:
                async with self._coordinator.chat_scope(turn.chat_id):
                    turn_after = await self._turns.get(turn_id)
                    if turn_after is None:
                        pass
                    elif turn_after.status == TurnStatus.ESCALATED.value:
                        # CAS escalated → delivered (sanctioned latch exception).
                        await self._turns.reopen_from_escalated(
                            turn_id, status=TurnStatus.DELIVERED.value
                        )
                    elif not is_turn_status_terminal(turn_after.status):
                        # e.g. pending_approval after an earlier FP resume.
                        await self._coordinator.transition(
                            turn_id, TurnStatus.DELIVERED
                        )
            except Exception:
                log_swallowed(
                    logger,
                    "escalation_reply_delivered_transition_failed",
                    turn_id=str(turn_id),
                    chat_id=turn.chat_id,
                )
        return result

    async def handle_owner_escalate(
        self,
        turn_id: UUID,
        *,
        actor_id: int | None = None,
    ) -> bool:
        """Owner discard/escalate: cancel waiting approval; never deliver.

        Returns True when the turn was transitioned to escalated; False on no-op.
        """
        self._assert_owner(actor_id)
        turn = await self._turns.get(turn_id)
        if turn is None:
            logger.info(
                "owner_escalate_missing_turn", extra={"turn_id": str(turn_id)}
            )
            return False
        chat_id = turn.chat_id

        escalated_here = False
        try:
            async with self._coordinator.chat_scope(chat_id):
                turn = await self._turns.get(turn_id)
                if turn is None or is_turn_status_terminal(turn.status):
                    if turn is not None:
                        # Terminal turn with a residual doctrine hold (e.g. a
                        # superseded GRAY_ZONE): close it so the VIP is not left
                        # frozen behind a dead turn. Best-effort, never raises.
                        await self._discard_doctrine_hold_if_any(turn_id)
                    logger.info(
                        "owner_escalate_terminal_noop",
                        extra={
                            "turn_id": str(turn_id),
                            "status": None if turn is None else turn.status,
                        },
                    )
                    return False

                approval = await self._approvals.get_by_turn(turn_id)
                if approval is not None and approval.status in {"waiting", "claimed"}:
                    await self._approvals.mark_status(turn_id, "cancelled")

                # R4: eligibility BEFORE the transition — an ESCALATED
                # transition that persists-then-raises must still fire the
                # post-turn hook (the read-back gate below decides whether the
                # turn is actually extractable).
                escalated_here = True
                await self._coordinator.transition(turn_id, TurnStatus.ESCALATED)
                # Doctrine hold: release freeze + close awaiting_send; keep live policy.
                await self._release_doctrine_hold_on_escalate(turn_id)
                # Fila 4 (C1): owner escalated → outcome row owner_outcome =
                # escalated (no sent text → no scores). Best-effort.
                if self._outcome is not None:
                    try:
                        await self._outcome.record_owner_outcome(
                            turn_id,
                            owner_outcome="escalated",
                            sent_text=None,
                            vip_id=turn.vip_id,
                        )
                    except Exception:
                        log_swallowed(
                            logger,
                            "outcome_owner_escalate_failed",
                            turn_id=str(turn_id),
                            chat_id=chat_id,
                        )
        finally:
            # REQ-MEM-07 parity with the autonomous path: an owner-escalated turn
            # is ESCALATED — a terminal, extractable outcome. Fire the post-turn
            # hook best-effort OUTSIDE the chat lock (the ``with`` exited) —
            # never blocks the callback; a failure is swallowed and logged. R4:
            # fired from the ``finally`` so a soft persistence error in the
            # transition cannot strand extraction of the now-ESCALATED turn. The
            # terminal no-op paths return before ``escalated_here`` is set, so
            # the hook runs only when THIS call made the turn escalated
            # (exactly once); ``_trigger_post_turn_terminal`` read-backs the
            # persisted status (exactly-once guard).
            if escalated_here and self._post_turn is not None:
                await self._trigger_post_turn_terminal(turn_id, chat_id)

        try:
            await self._notifier.notify_info(
                f"Turn {turn_id} escalated/discarded by owner",
                chat_id=chat_id,
            )
        except Exception:
            log_swallowed(
                logger,
                "owner_escalate_notify_failed",
                turn_id=str(turn_id),
                chat_id=chat_id,
            )
        logger.info(
            "owner_escalate",
            extra={"turn_id": str(turn_id), "chat_id": chat_id},
        )
        return True

    async def _resolve_and_deliver(
        self,
        turn_id: UUID,
        *,
        corrected_text: str | None,
        on_progress: DeliveryProgressCallback | None = None,
        severity: str | None = None,
    ) -> DeliveryResult | None:
        turn = await self._turns.get(turn_id)
        if turn is None:
            logger.info("admin_resolve_missing_turn", extra={"turn_id": str(turn_id)})
            return None
        chat_id = turn.chat_id

        claimed: ApprovalRecord | None = None
        text: str = ""
        decision_dump: dict[str, Any] | None = None
        trigger_message_id: int | None = None

        # Claim under chat lock so only one owner resolve wins (BUG-003).
        async with self._coordinator.chat_scope(chat_id):
            turn = await self._turns.get(turn_id)
            if turn is None or is_turn_status_terminal(turn.status):
                logger.info(
                    "admin_resolve_terminal_noop",
                    extra={
                        "turn_id": str(turn_id),
                        "status": None if turn is None else turn.status,
                    },
                )
                return None

            claimed = await self._approvals.claim_waiting(turn_id)
            if claimed is None:
                logger.info(
                    "admin_resolve_claim_lost",
                    extra={"turn_id": str(turn_id)},
                )
                return None

            text = (
                corrected_text
                if corrected_text is not None
                else claimed.draft_text
            )
            decision_dump = claimed.evaluation
            trigger_message_id = (
                claimed.trigger_message_id or turn.trigger_message_id
            )

        # SEC-F1: freeze gate before VIP write (mirror orch autonomous re-check).
        # Fail closed: no deliver when frozen — EXCEPT doctrine awaiting_send hold
        # (VIP stays frozen until successful send on this path).
        is_frozen = await self._is_vip_frozen(claimed.vip_id)
        doctrine_hold = await self._has_doctrine_awaiting_send(turn_id)
        if is_frozen and not doctrine_hold:
            failed_here = False
            try:
                async with self._coordinator.chat_scope(chat_id):
                    turn_after = await self._turns.get(turn_id)
                    if turn_after is not None and not is_turn_status_terminal(
                        turn_after.status
                    ):
                        await self._approvals.mark_status(turn_id, "cancelled")
                        # R4: eligibility BEFORE the transition — a FAILED
                        # transition that persists-then-raises must still fire
                        # the post-turn hook (the read-back gate below decides
                        # whether the turn is actually extractable).
                        failed_here = True
                        await self._coordinator.mark_failed(
                            turn_id, error="vip_frozen"
                        )
                        try:
                            await self._notifier.notify_info(
                                f"Turn {turn_id} failed: vip_frozen",
                                chat_id=chat_id,
                            )
                        except Exception:
                            logger.exception(
                                "owner_notify_failed_after_vip_frozen",
                                extra={"turn_id": str(turn_id)},
                            )
            finally:
                # Fix round (R3): vip_frozen marks the turn FAILED — a terminal,
                # extractable outcome (REQ-MEM-07), so the post-turn hook fires
                # best-effort OUTSIDE the chat lock, mirroring the autonomous
                # path. R4: fired from the ``finally`` so a soft persistence
                # error in ``mark_failed`` cannot strand extraction of the
                # now-FAILED turn. Gated on ``failed_here``: when the turn was
                # already terminal at re-read (a concurrent branch owns the
                # hook), do NOT double-run; ``_trigger_post_turn_terminal``
                # read-backs the persisted status (exactly-once guard).
                if failed_here and self._post_turn is not None:
                    await self._trigger_post_turn_terminal(turn_id, chat_id)
            logger.info(
                "admin_deliver_vip_frozen",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "vip_id": str(claimed.vip_id) if claimed.vip_id else None,
                },
            )
            return DeliveryResult(
                success=False,
                cancelled=True,
                error="vip_frozen",
            )

        advanced = self._feature_advanced_behavior
        mode = self._effective_delivery_mode(claimed.chat_id)
        if mode == "fake_delivery":
            logger.info(
                "delivery_mode_fake",
                extra={"turn_id": str(turn_id), "chat_id": claimed.chat_id},
            )
        # SEC-F2: is_frozen reflects gate result (False here; True never reaches deliver).
        ctx = DeliveryContext(
            chat_id=claimed.chat_id,
            business_connection_id=claimed.business_connection_id,
            vip_id=claimed.vip_id,
            telegram_message_id=trigger_message_id,
            mode=mode,
            is_frozen=False,
            skip_initial_delay=True,
            allow_split=advanced,
            allow_human_quirks=advanced,
            split_chars=4096,
        )
        # Deliver outside the chat lock so cancel_pending can interrupt mid-flight.
        result = await self._behavior.deliver(
            [text],
            ctx,
            turn_id,
            decision=decision_dump,
            on_progress=on_progress,
        )

        # Fix round (R2/R3): the post-turn hook fires from a ``finally`` keyed
        # on ``post_turn_eligible`` — whether THIS block made the turn terminal
        # in an extractable status (delivered / failed, REQ-MEM-07). The flag
        # is set BEFORE the transition, so a transition that persists then
        # raises still fires; the ``finally`` read-backs the persisted status
        # via ``_trigger_post_turn_terminal``, which skips non-extractable
        # statuses and never double-runs when another branch (e.g. a concurrent
        # owner escalate on the terminal-abort path) already fired for the turn.
        post_turn_eligible = False
        try:
            async with self._coordinator.chat_scope(chat_id):
                turn_after = await self._turns.get(turn_id)
                if turn_after is None or is_turn_status_terminal(turn_after.status):
                    # Superseded or otherwise terminal mid-flight — do not revive.
                    await self._approvals.mark_status(turn_id, "cancelled")
                    logger.info(
                        "admin_resolve_aborted_terminal_after_deliver",
                        extra={
                            "turn_id": str(turn_id),
                            "status": None if turn_after is None else turn_after.status,
                            "deliver_success": result.success,
                        },
                    )
                    return None if not result.cancelled else result

                if result.success:
                    approval_status = (
                        "corrected" if corrected_text is not None else "approved"
                    )
                    await self._approvals.mark_status(turn_id, approval_status)
                    # R3: mark eligible BEFORE the transition (see above).
                    post_turn_eligible = True
                    await self._coordinator.transition(turn_id, TurnStatus.DELIVERED)
                    # Doctrine hold: close awaiting_send + unfreeze after real send.
                    await self._close_doctrine_hold_after_send(turn_id)
                    # Fila 4 (C1/C2): owner-resolution half of the outcome log —
                    # approved_as_is / corrected + the sent score + quality
                    # delta + the trust label event. Best-effort (a failure must
                    # never fail the already-completed delivery).
                    if self._outcome is not None:
                        try:
                            await self._outcome.record_owner_outcome(
                                turn_id,
                                owner_outcome=(
                                    "corrected"
                                    if corrected_text is not None
                                    else "approved_as_is"
                                ),
                                sent_text=(
                                    corrected_text
                                    if corrected_text is not None
                                    else claimed.draft_text
                                ),
                                vip_id=claimed.vip_id,
                                severity=severity,
                            )
                        except Exception:
                            log_swallowed(
                                logger,
                                "outcome_owner_resolution_failed",
                                turn_id=str(turn_id),
                                chat_id=chat_id,
                            )
                    # Fix round (R2): bookkeeping AFTER the confirmed transition
                    # is best-effort — a failure here must never fail the
                    # already-completed delivery nor strand the post-turn hook.
                    try:
                        await self._traces.set_delivery_result(
                            turn_id, result.to_trace_dict()
                        )
                        # H7.2: append delivered outbound text for HistoryRetriever (owner→dueña).
                        # Skip durable history when sandbox is active (should_persist false).
                        # Multi-segment: one owner row per message_id when texts align.
                        if self._history is not None:
                            if (
                                self._sandbox is not None
                                and not self._sandbox.should_persist(chat_id)  # type: ignore[union-attr]
                            ):
                                logger.info(
                                    "owner_history_skipped_sandbox",
                                    extra={
                                        "turn_id": str(turn_id),
                                        "chat_id": chat_id,
                                    },
                                )
                            else:
                                await append_owner_delivery_history(
                                    self._history,
                                    chat_id,
                                    result=result,
                                    fallback_text=text,
                                    turn_id=turn_id,
                                )
                    except Exception:
                        log_swallowed(
                            logger,
                            "admin_delivery_bookkeeping_failed",
                            turn_id=str(turn_id),
                            chat_id=chat_id,
                        )
                    logger.info(
                        "admin_delivered",
                        extra={
                            "turn_id": str(turn_id),
                            "chat_id": claimed.chat_id,
                            "mode": approval_status,
                        },
                    )
                elif result.cancelled:
                    # Live turn + cancel (rare) — reopen waiting for owner retry.
                    await self._approvals.mark_status(turn_id, "waiting")
                    logger.info(
                        "admin_deliver_cancelled_reopened",
                        extra={
                            "turn_id": str(turn_id),
                            "error": result.error,
                        },
                    )
                else:
                    # I.5 permanent deliver failure after retries — do not silent-wait.
                    await self._approvals.mark_status(turn_id, "cancelled")
                    # R3: a permanent failure is FAILED — an extractable terminal
                    # outcome (REQ-MEM-07); mark eligible BEFORE mark_failed so a
                    # persisted-then-raised transition still fires the hook.
                    post_turn_eligible = True
                    await self._coordinator.mark_failed(
                        turn_id, error=result.error or "delivery_failed"
                    )
                    await self._notifier.notify_info(
                        f"Turn {turn_id} failed: delivery_failed ({result.error})",
                        chat_id=claimed.chat_id,
                    )
                    await self._traces.set_delivery_result(
                        turn_id, result.to_trace_dict()
                    )
                    logger.info(
                        "admin_deliver_failed",
                        extra={
                            "turn_id": str(turn_id),
                            "error": result.error,
                        },
                    )
        finally:
            # REQ-MEM-07 parity with the autonomous path: run post-turn
            # learning + memory extraction AFTER the turn is confirmed terminal
            # in an extractable status and OUTSIDE the chat lock. Best-effort
            # strict (R1) — a failure never propagates to the already-completed
            # supervised delivery. ``_trigger_post_turn_terminal`` read-backs
            # the persisted status (closing the commit-then-refresh gap) and
            # skips when it is no longer extractable (exactly-once guard).
            if post_turn_eligible and self._post_turn is not None:
                await self._trigger_post_turn_terminal(turn_id, chat_id)
        return result

    async def _trigger_post_turn(self, turn_id: UUID, chat_id: int) -> None:
        """Best-effort post-turn hook after a confirmed supervised delivery.

        Mirrors the orchestrator's ``_maybe_post_turn`` (which the hook points
        to): sandbox skip, learning and flag-gated memory extraction are all
        handled inside. This wrapper only guarantees the completed delivery is
        never affected by a hook failure.
        """
        try:
            await self._post_turn(turn_id, chat_id)
        except Exception:
            log_swallowed(
                logger,
                "post_turn_hook_error",
                turn_id=str(turn_id),
                chat_id=chat_id,
            )

    async def _trigger_post_turn_terminal(
        self, turn_id: UUID, chat_id: int
    ) -> None:
        """Best-effort post-turn hook after a supervised terminal outcome.

        Like ``_trigger_post_turn`` but read-backs the turn's persisted status
        and fires ONLY when it is still in the extractable set (delivered /
        escalated / failed, REQ-MEM-07). The read-back closes the
        commit-then-refresh gap (a row persisted DELIVERED/FAILED while the
        in-block flag was never assigned) and guards the exactly-once invariant
        — a turn that ended non-extractable (e.g. superseded) never runs, and a
        concurrent branch that already fired for the same terminal turn is not
        re-fired. The read itself is best-effort: on failure the hook still
        fires (the caller already confirmed it made the turn terminal), so the
        completed turn's learning + memory extraction are never stranded.
        """
        try:
            turn = await self._turns.get(turn_id)
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
        await self._trigger_post_turn(turn_id, chat_id)

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

    async def _has_doctrine_awaiting_send(self, turn_id: UUID) -> bool:
        """True when a doctrine hold (open|awaiting_send) exists for this turn.

        Name kept for call sites; lookup uses hold (open|awaiting_send) so a
        mark_awaiting_send race cannot strand approve behind vip_frozen.
        """
        gz = self._gray_zone
        if gz is None:
            return False
        try:
            if hasattr(gz, "get_hold_query_by_turn_id"):
                row = await gz.get_hold_query_by_turn_id(turn_id)
            else:
                row = await gz.get_awaiting_send_by_turn_id(turn_id)
        except Exception:
            logger.exception(
                "doctrine_awaiting_send_lookup_error",
                extra={"turn_id": str(turn_id)},
            )
            return False
        return row is not None

    async def _close_doctrine_hold_after_send(self, turn_id: UUID) -> None:
        """Best-effort: close open|awaiting_send hold + unfreeze after successful deliver."""
        gz = self._gray_zone
        if gz is None:
            return
        try:
            if hasattr(gz, "get_hold_query_by_turn_id"):
                row = await gz.get_hold_query_by_turn_id(turn_id)
            else:
                row = await gz.get_awaiting_send_by_turn_id(turn_id)
            if row is None:
                return
            await gz.close_awaiting_send(row.id, unfreeze=True)
        except Exception:
            logger.exception(
                "doctrine_hold_close_after_send_failed",
                extra={"turn_id": str(turn_id)},
            )

    async def _release_doctrine_hold_on_escalate(self, turn_id: UUID) -> None:
        """Best-effort: close awaiting_send/open hold + unfreeze; keep live policy."""
        gz = self._gray_zone
        if gz is None:
            return
        try:
            row = None
            if hasattr(gz, "get_hold_query_by_turn_id"):
                row = await gz.get_hold_query_by_turn_id(turn_id)
            if row is None:
                row = await gz.get_awaiting_send_by_turn_id(turn_id)
            if row is None:
                return
            status = getattr(row, "status", None)
            if status == "awaiting_send":
                await gz.close_awaiting_send(row.id, unfreeze=True)
            elif status == "open":
                await gz.discard_and_close(row.id)
        except Exception:
            logger.exception(
                "doctrine_hold_release_on_escalate_failed",
                extra={"turn_id": str(turn_id)},
            )

    async def resolve_doctrine_rule_and_enqueue(
        self,
        *,
        turn_id: UUID,
        rule_text: str,
        scope: str = "all",
        vip_id: UUID | None = None,
        gray_zone: GrayZoneServicePort | None = None,
        actor_id: int | None = None,
    ) -> str:
        """Persist live RULE → force-regen → supervised approval; freeze until send.

        Returns status token: ``resolved``, ``regen_failed``, ``error``,
        or ``not_found``. Approval-create / lock / mark failures return
        ``error`` (freeze held, policy live, retryable) — never auto-escalate.
        """
        del actor_id  # reserved for auth/audit; resolve no longer auto-escalates
        gz = gray_zone if gray_zone is not None else self._gray_zone
        if gz is None:
            logger.error(
                "doctrine_resolve_missing_gray_zone",
                extra={"turn_id": str(turn_id)},
            )
            return "error"
        if self._director is None:
            logger.error(
                "doctrine_resolve_missing_director",
                extra={"turn_id": str(turn_id)},
            )
            return "error"

        rule = (rule_text or "").strip()
        if not rule:
            return "error"

        try:
            query = await gz.get_open_query_by_turn_id(turn_id)
        except Exception:
            logger.exception(
                "doctrine_resolve_lookup_error",
                extra={"turn_id": str(turn_id)},
            )
            return "error"
        if query is None:
            return "not_found"

        # Terminal turn guard: never persist a live policy or regen for a
        # superseded/finished turn; close any residual hold so the VIP is not
        # left frozen behind a dead turn. Defense in depth — the supersede path
        # already closes the hold, so this is the no-op/race backstop.
        turn = await self._turns.get(turn_id)
        if turn is None:
            try:
                await gz.discard_and_close(query.id)
            except Exception:
                log_swallowed(
                    logger,
                    "doctrine_resolve_missing_turn_discard_failed",
                    turn_id=str(turn_id),
                    query_id=str(query.id),
                )
            return "not_found"
        if is_turn_status_terminal(turn.status):
            try:
                await gz.discard_and_close(query.id)
            except Exception:
                log_swallowed(
                    logger,
                    "doctrine_resolve_stale_discard_failed",
                    turn_id=str(turn_id),
                    query_id=str(query.id),
                )
            logger.info(
                "doctrine_resolve_stale_turn",
                extra={"turn_id": str(turn_id), "status": turn.status},
            )
            return "stale"

        policy = None
        try:
            policy = await gz.persist_live_policy(
                query.id,
                rule,
                vip_id=vip_id,
                scope=scope if scope in {"vip", "all"} else ("vip" if vip_id else "all"),
            )
        except Exception:
            logger.exception(
                "doctrine_live_policy_persist_failed",
                extra={"turn_id": str(turn_id), "query_id": str(query.id)},
            )
            return "error"

        vip_text = (
            (getattr(query, "question", "") or "").strip()
            or _NO_VIP_TEXT_PLACEHOLDER
        )
        incoming = IncomingTurn(
            turn_id=turn_id,
            chat_id=turn.chat_id,
            vip_id=turn.vip_id,
            text=vip_text,
            telegram_message_id=turn.trigger_message_id,
            business_connection_id=(
                getattr(query, "business_connection_id", None)
                or ""
            ),
            channel_type=turn.channel_type,
        )
        override_entry = (
            gz.policy_override_payload(policy)
            if hasattr(gz, "policy_override_payload")
            else {
                "trigger_description": getattr(policy, "trigger_description", ""),
                "rule": getattr(policy, "rule", rule),
                "scope": getattr(policy, "scope", scope),
                "is_active": True,
            }
        )
        knowledge_overrides = {"knowledge.policy": [override_entry]}

        try:
            decision = await self._director.handle_turn(
                incoming,
                knowledge_overrides=knowledge_overrides,
            )
        except Exception:
            logger.exception(
                "doctrine_regen_failed",
                extra={"turn_id": str(turn_id), "query_id": str(query.id)},
            )
            await gz.deactivate_policy(policy.id)
            try:
                await self._notifier.notify_info(
                    "No pude regenerar el borrador con la regla. "
                    "La regla se desactivó; el chat sigue congelado. Reintenta.",
                    chat_id=turn.chat_id,
                )
            except Exception:
                logger.exception(
                    "doctrine_regen_fail_notify_error",
                    extra={"turn_id": str(turn_id)},
                )
            return "regen_failed"

        draft = (getattr(decision, "draft_text", None) or "").strip()
        action = getattr(decision, "action", None)
        reason = getattr(decision, "reason", "") or ""
        # Fail-closed ONLY when the rule was NOT applied or the regenerated
        # draft is itself unsafe:
        # - consult_doctrine again (the injected rule did not satisfy the Decider)
        # - empty draft (regeneration produced nothing usable)
        # - escalate by SAFETY (the regenerated draft itself is unsafe — never
        #   enqueue a draft that failed the safety gate)
        #
        # Decision.action=escalate by risk/frustration of the ORIGINAL message
        # (reason risk_high / frustracion_directa) WITH a valid draft is NOT a
        # regen failure: the rule WAS applied and the regenerated draft goes to
        # the owner approval queue, where the owner decides approve/correct/
        # escalate (AGENTS §4.5 — "regen ok (borrador no vacío, acción ≠
        # consult_doctrine)").
        if (
            action == "consult_doctrine"
            or not draft
            or (action == "escalate" and reason == "safety_below_threshold")
        ):
            await gz.deactivate_policy(policy.id)
            try:
                await self._notifier.notify_info(
                    "La regeneración no produjo un borrador usable "
                    "(el sistema volvió a pedir doctrina, no generó texto, "
                    "o el borrador no pasó el control de seguridad). "
                    "La regla se desactivó; el chat sigue congelado. "
                    "Reintenta con otra regla.",
                    chat_id=turn.chat_id,
                )
            except Exception:
                logger.exception(
                    "doctrine_regen_reject_notify_error",
                    extra={"turn_id": str(turn_id)},
                )
            return "regen_failed"

        if action == "escalate":
            logger.info(
                "doctrine_regen_escalate_queued",
                extra={
                    "turn_id": str(turn_id),
                    "query_id": str(query.id),
                    "reason": reason,
                    "draft_chars": len(draft),
                },
            )

        from diana.application.turn_coordinator import ChatLockTimeoutError

        try:
            created = await self.create_supervised_delivery_from_gray_zone(
                turn_id, query, draft_override=draft
            )
        except ChatLockTimeoutError:
            try:
                await gz.reopen_query(query.id)
            except Exception:
                logger.exception(
                    "doctrine_resolve_lock_timeout_reopen_error",
                    extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                )
            logger.warning(
                "doctrine_resolve_delivery_lock_timeout",
                extra={"turn_id": str(turn_id), "query_id": str(query.id)},
            )
            try:
                await self._notifier.notify_info(
                    "No pude encolar el borrador regenerado (el chat está ocupado). "
                    "El chat sigue congelado; la regla quedó activa. Reintenta.",
                    chat_id=turn.chat_id,
                )
            except Exception:
                logger.exception(
                    "doctrine_resolve_lock_timeout_notify_error",
                    extra={"turn_id": str(turn_id)},
                )
            return "error"
        except Exception:
            logger.exception(
                "doctrine_resolve_delivery_error",
                extra={"turn_id": str(turn_id), "query_id": str(query.id)},
            )
            created = False

        if not created:
            # Approval-create fail: keep freeze, keep live policy, reopen if
            # needed, notify — never auto-escalate / unfreeze (AGENTS §4.5).
            try:
                await gz.reopen_query(query.id)
            except Exception:
                logger.exception(
                    "doctrine_resolve_reopen_error",
                    extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                )
            try:
                await self._notifier.notify_info(
                    "No pude encolar el borrador regenerado. "
                    "El chat sigue congelado; la regla quedó activa. Reintenta.",
                    chat_id=turn.chat_id,
                )
            except Exception:
                logger.exception(
                    "doctrine_resolve_create_fail_notify_error",
                    extra={"turn_id": str(turn_id)},
                )
            return "error"

        try:
            await gz.mark_awaiting_send(query.id)
        except Exception:
            logger.exception(
                "doctrine_mark_awaiting_send_failed",
                extra={"turn_id": str(turn_id), "query_id": str(query.id)},
            )
            # Full compensate: cancel+delete approval, restore GRAY_ZONE, reopen
            # query (freeze held, policy live) so owner "Reintenta" can re-enqueue.
            try:
                async with self._coordinator.chat_scope(turn.chat_id):
                    try:
                        await self._cancel_waiting_approval(turn_id)
                    except Exception:
                        logger.exception(
                            "doctrine_mark_fail_cancel_approval_error",
                            extra={"turn_id": str(turn_id)},
                        )
                    if hasattr(self._approvals, "delete_for_turn"):
                        try:
                            await self._approvals.delete_for_turn(turn_id)
                        except Exception:
                            logger.exception(
                                "doctrine_mark_fail_delete_approval_error",
                                extra={"turn_id": str(turn_id)},
                            )
                    try:
                        await self._coordinator.transition(
                            turn_id, TurnStatus.GRAY_ZONE
                        )
                    except Exception:
                        logger.exception(
                            "doctrine_mark_fail_restore_gray_zone_error",
                            extra={"turn_id": str(turn_id)},
                        )
            except Exception:
                logger.exception(
                    "doctrine_mark_fail_compensate_scope_error",
                    extra={"turn_id": str(turn_id)},
                )
            try:
                await gz.reopen_query(query.id)
            except Exception:
                logger.exception(
                    "doctrine_mark_fail_reopen_error",
                    extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                )
            try:
                await self._notifier.notify_info(
                    "Encolé el borrador pero no pude retener el congelamiento. "
                    "Cancelé la aprobación; el chat sigue congelado y la regla "
                    "sigue activa. Reintenta.",
                    chat_id=turn.chat_id,
                )
            except Exception:
                logger.exception(
                    "doctrine_mark_fail_notify_error",
                    extra={"turn_id": str(turn_id)},
                )
            return "error"

        logger.info(
            "doctrine_rule_resolved_enqueued",
            extra={
                "turn_id": str(turn_id),
                "query_id": str(query.id),
                "policy_id": str(policy.id),
            },
        )
        return "resolved"
