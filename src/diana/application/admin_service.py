"""AdminService — owner approval queue (domain API, no aiogram types)."""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
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
    TurnStore,
    VipStore,
)
from diana.application.draft_variants import ensure_versions, resolve_vip_display_name
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
    Decision,
    EvaluationProfile,
    IncomingTurn,
    TurnStatus,
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


def _eval_summary(decision: Decision) -> str:
    """Display-only summary string; never fed back into Decider."""
    e = decision.evaluation
    return (
        f"nat={e.naturalness:.2f} prec={e.precision:.2f} "
        f"doc={e.doctrine:.2f} con={e.consistency:.2f} "
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

    def set_director(self, director: Any) -> None:
        """Wire CognitiveDirector after composition builds it (draft regen / doctrine)."""
        self._director = director

    def set_gray_zone(self, gray_zone: GrayZoneServicePort | None) -> None:
        """Wire GrayZoneService for doctrine hold lookups on owner deliver."""
        self._gray_zone = gray_zone

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
    ) -> None:
        bc = (turn.business_connection_id or "").strip()
        if not bc:
            raise ValueError("business_connection_id is required for approval")
        draft = decision.draft_text or ""
        eval_dict = ensure_versions(
            decision.evaluation.model_dump(mode="json"),
            draft_text=draft,
            reason=decision.reason or "",
            vip_text=turn.text,
        )
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
                evaluation_summary=_eval_summary(decision),
                evaluation=decision.evaluation.model_dump(mode="json"),
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
                text=(getattr(query, "question", "") or "").strip() or "(no text)",
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
                await self.send_draft_for_approval(incoming, decision, turn_id)
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
                    evaluation_summary=_eval_summary(decision),
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
        severity: str = "moderate",
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
        severity: str = "moderate",
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
            delivery, candidate_id = await self._correct_core(
                turn_id, corrected_text, actor_id=actor_id
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
        return await self._behavior.deliver([stripped], ctx, turn_id)

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

        vip_text = (getattr(query, "question", "") or "").strip() or "(no text)"
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
