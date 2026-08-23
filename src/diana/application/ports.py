"""I/O ports for the application shell (no aiogram types)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from diana.cognitive.models import SignalType, TurnCategory, SynthesisTrigger


class RuntimeTimerRecord(BaseModel):
    """runtime_timers row shape for crash-recovery persistence.

    ``kind``:
    - ``delivery`` — BehaviorEngine human delay (requires delivery_id)
    - ``pre_delay`` — VIP orchestrator wait before cognitive pipeline
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    chat_id: int
    turn_id: UUID
    delivery_id: UUID | None = None
    kind: str = "delivery"  # delivery | pre_delay
    scheduled_at: datetime
    initial_delay_seconds: float
    status: str  # "active" | "completed" | "recovered"
    created_at: datetime
    payload: dict[str, Any] | None = None


class TurnRecord(BaseModel):
    """Durable turn row shape used by application stores."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    chat_id: int
    status: str
    vip_id: UUID | None = None
    # F4 channel tag ("vip" | "atencion"); default keeps pre-F4 callers unchanged.
    channel_type: Literal["vip", "atencion"] = "vip"
    trigger_message_id: int | None = None
    superseded_by: UUID | None = None
    error: str | None = None
    # F5 Pool 3: turn creation time — the post-turn extractor filters
    # message_history to ``timestamp >= created_at`` (plan A3). Populated by
    # the SQL store from the ORM row; None for in-memory/legacy callers.
    created_at: datetime | None = None
    # Fix round (R2): per-turn terminal/finalize timestamp — the last
    # transition time (DELIVERED / escalated / failed). The post-turn
    # extractor uses it as THIS turn's own delivery/finalize UPPER bound so
    # it never scans owner rows globally. Populated by the SQL store from the
    # ORM row; None for in-memory/legacy callers (the extractor then falls
    # back to the owner-row scan — documented residual case).
    updated_at: datetime | None = None


class ApprovalRecord(BaseModel):
    """pending_approvals row shape.

    Status values used in F1:
    - waiting: owner has not acted
    - claimed: atomic claim before deliver (CAS winner)
    - approved / corrected: resolved after successful deliver
    - cancelled / expired: terminal non-deliver
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    turn_id: UUID
    chat_id: int
    business_connection_id: str
    draft_text: str
    status: str = "waiting"
    vip_id: UUID | None = None
    cognitive_summary: str | None = None
    evaluation: dict[str, Any] | None = None
    owner_message_id: int | None = None
    trigger_message_id: int | None = None


class DeliveryRecord(BaseModel):
    """pending_deliveries row shape."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    chat_id: int
    business_connection_id: str
    texts: list[str]
    decision: dict[str, Any]
    scheduled_at: datetime
    status: str = "pending"
    turn_id: UUID
    vip_id: UUID | None = None


class DraftNotification(BaseModel):
    """Owner DM payload for draft approval (plain data, no aiogram)."""

    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    chat_id: int
    vip_text: str
    draft_text: str
    reason: str
    vip_display_name: str | None = None
    evaluation_summary: str | None = None
    evaluation: dict[str, Any] | None = None
    business_connection_id: str
    reply_markup_spec: dict[str, Any] = Field(default_factory=dict)
    show_quality_feedback: bool = False


class LinkNotification(BaseModel):
    """Owner DM payload for a Lucien→Diana kick link (plain data, no aiogram)."""

    model_config = ConfigDict(extra="forbid")

    display_name: str
    username: str | None = None
    event_id: str


class EscalationNotification(BaseModel):
    """Owner DM payload for escalation."""

    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    chat_id: int
    reason: str
    vip_text: str | None = None
    tipo: str = "semantica"
    business_connection_id: str | None = None


class LinkEventRecord(BaseModel):
    """link_events row shape (ledger for Lucien→Diana kick events)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    event_id: str
    user_id: int
    username: str | None = None
    channel_id: int | None = None
    channel_name: str | None = None
    reason: str
    vip_id: UUID | None = None
    state: str = "pending"
    decision_at: datetime | None = None
    created_at: datetime | None = None


class DoctrineNotification(BaseModel):
    """Notification to the owner with a gray zone doctrine query."""

    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    chat_id: int
    vip_text: str
    draft_text: str | None = None
    evaluation_summary: str
    reason: str
    business_connection_id: str | None = None
    reply_markup_spec: dict | None = None


@runtime_checkable
class GrayZoneQueryView(Protocol):
    """Minimal query view used by AdminService.send_doctrine_query.

    Provides a stable interface over the ORM GrayZoneQuery row so the
    application layer does not depend on infrastructure model shapes.
    """

    id: UUID
    turn_id: UUID
    question: str
    draft: str
    # F4: source business connection used to reconstruct IncomingTurn for
    # supervised-delivery approval synthesis (nullable for legacy rows).
    business_connection_id: str | None = None


@runtime_checkable
class GrayZoneServicePort(Protocol):
    """Application service for the gray zone query lifecycle.

    Exposes the methods consumed by telegram handlers so the telegram layer
    can depend on the protocol instead of ``Any``.
    """

    async def get_open_query_by_turn_id(self, turn_id: UUID) -> GrayZoneQueryView | None: ...

    async def get_open_query_by_vip_id(self, vip_id: UUID) -> GrayZoneQueryView | None: ...

    async def get_open_query_by_chat_id(self, chat_id: int) -> GrayZoneQueryView | None: ...

    async def resolve_with_doctrine(
        self,
        query_id: UUID,
        generalization: str,
        rule: str,
        *,
        vip_id: UUID | None = None,
    ) -> object: ...

    async def confirm_and_apply(
        self, query_id: UUID, candidate_id: UUID
    ) -> object: ...

    async def discard_and_close(self, query_id: UUID) -> object: ...

    async def expire_old_queries(
        self, timeout_hours: int | None = None
    ) -> list[object]: ...

    async def reopen_query(self, query_id: UUID) -> bool: ...


DeliveryMode = Literal["supervised", "autonomous", "fake_delivery"]


class DeliveryContext(BaseModel):
    """Context required to act a message toward a VIP chat."""

    model_config = ConfigDict(extra="forbid")

    chat_id: int
    business_connection_id: str
    vip_id: UUID | None = None
    mode: DeliveryMode = "supervised"
    telegram_message_id: int | None = None
    is_frozen: bool = False
    # When True the pre-send wait was already served before the pipeline,
    # so BehaviorEngine delivers without extra initial delay (typing still applies).
    skip_initial_delay: bool = False
    # Advanced behavior (H3.6) — fail-closed defaults; dual-gated in engine.
    allow_split: bool = False
    allow_human_quirks: bool = False
    split_chars: int = Field(default=4096, ge=1)
    # Telegram parse mode for the outgoing text (e.g. "HTML"). None = plain text.
    parse_mode: str | None = None


class DeliveryResult(BaseModel):
    """Outcome of a deliver attempt."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    message_ids: list[int] = Field(default_factory=list)
    texts: list[str] = Field(default_factory=list)  # final prepared segments
    actual_delay_seconds: float = 0.0
    typing_duration_seconds: float = 0.0
    error: str | None = None
    cancelled: bool = False

    def to_trace_dict(self) -> dict:
        return self.model_dump(mode="json")


class VipInboundMessage(BaseModel):
    """Application DTO for an inbound VIP business message."""

    model_config = ConfigDict(extra="forbid")

    chat_id: int
    text: str
    telegram_message_id: int | None = None
    business_connection_id: str | None = None
    vip_id: UUID | None = None
    # True for edited_business_message: replace history row, cancel prior turn.
    is_edit: bool = False
    # F4: channel type ("vip" | "atencion"). Set by AuthMiddleware for the
    # general-mode path; default keeps the VIP pipeline unchanged.
    channel_type: Literal["vip", "atencion"] = "vip"
    # F4-02: True ONLY when the general-mode atencion gate set it (auth.py).
    # Sandbox/training atencion and VIP never count; edits never count.
    counts_toward_limit: bool = False


class VipRecord(BaseModel):
    """VIP allowlist row shape."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    telegram_user_id: int
    display_name: str | None = None
    is_active: bool = True
    paused_until: datetime | None = None
    frozen_until: datetime | None = None
    auto_send: bool = False


class BackfillJobRecord(BaseModel):
    """Persistent backfill queue row shape (REQ-MEM-05, F5 Pool 2).

    One row per VIP backfill job. ``window_index`` is the next transcript
    window to extract and ``state`` carries the facts accumulated from
    previous windows (crash-safe resumption). ``outcome`` is set on ``done``
    (``ok`` | ``empty_history``); ``last_error`` traces the last failure.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    vip_id: UUID
    chat_id: int
    status: Literal["pending", "processing", "done", "failed"]
    window_index: int = 0
    state: dict[str, Any] = {}
    attempts: int = 0
    last_error: str | None = None
    outcome: str | None = None
    created_at: datetime
    updated_at: datetime


@runtime_checkable
class VipStore(Protocol):
    """VIP allowlist store used by Auth middleware and admin commands."""

    async def get_by_telegram_user_id(
        self, telegram_user_id: int
    ) -> VipRecord | None: ...

    async def is_allowed(
        self, telegram_user_id: int, *, now: datetime | None = None
    ) -> bool:
        """True iff VIP exists, is_active, and not paused (paused_until is None or < now)."""
        ...

    async def get_record_and_allowed(
        self,
        telegram_user_id: int,
        *,
        record: VipRecord | None = None,
    ) -> tuple[VipRecord | None, bool]:
        """Return ``(record, allowed)`` in one lookup.

        When ``record`` is given (e.g. FreezeCheckMiddleware's ``_vip_record``
        cache), it is reused and no DB lookup happens — ``allowed`` is derived
        from that same snapshot. Otherwise a single fetch returns both, so a
        stranger's message costs exactly one round-trip. ``record`` is None iff
        no VIP row exists (a paused/inactive VIP still returns its record with
        ``allowed=False``).
        """
        ...

    async def add(
        self, telegram_user_id: int, *, display_name: str | None = None
    ) -> VipRecord: ...

    async def deactivate(self, telegram_user_id: int) -> bool:
        """Soft-remove: set is_active=False. Returns False if unknown."""
        ...

    async def get_by_id(self, vip_id: UUID) -> VipRecord | None:
        """Lookup VIP by UUID primary key."""
        ...

    async def freeze_vip(self, vip_id: UUID, frozen_until: datetime) -> None:
        """Set frozen_until column. Raises ValueError if VIP not found."""
        ...

    async def unfreeze_vip(self, vip_id: UUID) -> None:
        """Clear frozen_until column (set to NULL). Raises ValueError if VIP not found."""
        ...

    async def pause_vip(self, vip_id: UUID, paused_until: datetime) -> None:
        """Set paused_until column. Raises ValueError if VIP not found."""
        ...

    async def unpause_vip(self, vip_id: UUID) -> None:
        """Clear paused_until column (set to NULL). Raises ValueError if VIP not found."""
        ...

    async def list_active(self) -> list[VipRecord]:
        """Active VIPs only (is_active True), ordered by telegram_user_id ASC."""
        ...

    async def rename(
        self, telegram_user_id: int, display_name: str
    ) -> VipRecord | None:
        """Set display_name for an active VIP. None if missing or inactive. Never reactivates."""
        ...

    async def set_auto_send(self, vip_id: UUID, enabled: bool) -> bool:
        """Fila 4 C6: toggle ``auto_send`` (L2 double gate). False if unknown."""
        ...


@runtime_checkable
class LinkEventStore(Protocol):
    """Persistence for the Lucien→Diana kick link ledger."""

    async def create(self, record: LinkEventRecord) -> tuple[LinkEventRecord, bool]: ...

    async def get_by_event_id(self, event_id: str) -> LinkEventRecord | None: ...

    async def set_state(
        self, event_id: str, state: str, *, decision_at: datetime | None = None
    ) -> None: ...


@runtime_checkable
class OwnerNotifierPort(Protocol):
    """Notify the owner via DM. Never accepts aiogram types."""

    async def notify_draft(self, payload: DraftNotification) -> int | None: ...

    async def notify_escalation(self, payload: EscalationNotification) -> None: ...

    async def notify_info(self, text: str, *, chat_id: int | None = None) -> None: ...

    async def notify_doctrine(
        self, payload: DoctrineNotification
    ) -> int | None: ...

    async def notify_link(self, payload: LinkNotification) -> int | None: ...


@runtime_checkable
class TurnStore(Protocol):
    async def create(self, turn: TurnRecord) -> TurnRecord: ...

    async def get(self, turn_id: UUID) -> TurnRecord | None: ...

    async def list_non_terminal(self, chat_id: int) -> list[TurnRecord]: ...

    async def list_all_non_terminal(self) -> list[TurnRecord]:
        """All non-terminal turns across all chats (for zombie turn detection)."""
        ...

    async def transition(
        self,
        turn_id: UUID,
        status: str,
        *,
        superseded_by: UUID | None = None,
        error: str | None = None,
    ) -> TurnRecord: ...


@runtime_checkable
class PendingApprovalStore(Protocol):
    async def create_waiting(self, record: ApprovalRecord) -> ApprovalRecord: ...

    async def get_by_turn(self, turn_id: UUID) -> ApprovalRecord | None: ...

    async def mark_status(self, turn_id: UUID, status: str) -> None: ...

    async def claim_waiting(self, turn_id: UUID) -> ApprovalRecord | None:
        """CAS: waiting → claimed. Returns claimed record or None if lost race."""
        ...

    async def set_owner_message_id(self, turn_id: UUID, message_id: int) -> None: ...

    async def cancel_waiting_for_chat(self, chat_id: int) -> int: ...

    async def list_waiting(self) -> list[ApprovalRecord]: ...

    async def list_open(self) -> list[ApprovalRecord]:
        """Approvals still in flight: status in {waiting, claimed}."""
        ...


@runtime_checkable
class PendingDeliveryStore(Protocol):
    async def insert_pending(self, record: DeliveryRecord) -> DeliveryRecord: ...

    async def update_status(
        self, delivery_id: UUID, status: str, **meta: Any
    ) -> bool:
        """Conditional status update. Returns False if transition is forbidden."""
        ...

    async def cancel_for_chat(self, chat_id: int) -> int: ...

    async def list_pending(self) -> list[DeliveryRecord]: ...

    async def list_active(self) -> list[DeliveryRecord]:
        """Rows in pending or delivering (for recovery)."""
        ...

    async def get(self, delivery_id: UUID) -> DeliveryRecord | None: ...


@runtime_checkable
class RuntimeTimerStore(Protocol):
    """Persistent runtime timer store for crash-recovery of in-flight delays."""

    async def create_active(self, record: RuntimeTimerRecord) -> RuntimeTimerRecord: ...

    async def mark_completed(self, timer_id: UUID) -> bool: ...

    async def list_active(self) -> list[RuntimeTimerRecord]: ...

    async def complete_for_turn(self, turn_id: UUID) -> int:
        """Mark all active timers for *turn_id* completed. Returns count."""
        ...


class PersonaVersionRecord(BaseModel):
    """persona_versions row shape for versioned persona catalog snapshots.

    ``payload`` is the complete validated catalog dict
    (voz_configurada, persona_facts, voice_patterns, policies, schedule).
    ``channel_type`` scopes the active row per channel (``vip`` | ``atencion``);
    the version counter stays a global sequence shared across channels.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    version: int
    channel_type: str = "vip"
    source: str  # "seed" | "db"
    payload: dict[str, Any]
    is_active: bool = False
    created_by: int | None = None
    created_at: datetime
    applied_at: datetime | None = None


class VipProfileRecord(BaseModel):
    """vip_profile row shape — LLM-synthesized per-VIP profile (Fase 1 writer).

    DISTINTO de ``profiles`` (tabla vector, memories.py) y de ``/vip_profile``
    (comando legacy admin). Fase 0 = schema-only; no writer yet.
    """

    model_config = ConfigDict(extra="forbid")

    vip_id: UUID
    stable_traits: dict[str, Any]
    recent_trend: dict[str, Any]
    sensitivities: list[Any]
    version: int = 0
    last_synthesized_at: datetime | None = None
    synthesis_trigger: SynthesisTrigger | None = None


class VipProfileHistoryRecord(BaseModel):
    """vip_profile_history row shape (snapshot of a synthesized profile version).

    ``id`` / ``created_at`` are optional so the DB ``server_default``
    (``gen_random_uuid()`` / ``now()``) fills them when the caller omits them —
    mirroring ``EmotionalSignalLog``.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    vip_id: UUID
    version: int
    profile_snapshot: dict[str, Any]
    diff_summary: str | None = None
    created_at: datetime | None = None


class VipMoodStateRecord(BaseModel):
    """vip_mood_state row shape — 3-axis mood vector per VIP (Fase 3 writer).

    ``updated_at`` is optional because the repo ``upsert`` stamps ``func.now()``
    server-side (review round 1 nit) — the hook omits it; the DB fills it.
    """

    model_config = ConfigDict(extra="forbid")

    vip_id: UUID
    axis_playful_serious: float
    axis_warm_distant: float
    axis_energy: float
    updated_at: datetime | None = None


class VipTrustBudgetRecord(BaseModel):
    """vip_trust_budget row shape — trust score per (VIP, turn_category) (Fase 5)."""

    model_config = ConfigDict(extra="forbid")

    vip_id: UUID
    turn_category: TurnCategory
    # Spec documents trust_score as [0, 1]; enforce the range at the record
    # boundary (the Fase 5 writer is the only producer of these records).
    trust_score: float = Field(default=0.0, ge=0.0, le=1.0)
    correction_count: int = 0
    autonomous_count: int = 0
    last_correction_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProfileSynthesisQueueRecord(BaseModel):
    """profile_synthesis_queue row shape (Fila 4 C4 — durable synthesis queue)."""

    model_config = ConfigDict(extra="forbid")

    vip_id: UUID
    trigger: str  # volume | session_close | strong_signal | emotional_signal
    status: str = "pending"  # pending | processing
    attempts: int = 0
    enqueued_at: datetime | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None


@runtime_checkable
class ProfileSynthesisQueueStore(Protocol):
    """Durable synthesis-queue persistence (no trigger logic here)."""

    async def upsert_pending(self, vip_id: UUID, trigger: str) -> ProfileSynthesisQueueRecord: ...

    async def drain(self, limit: int = 100) -> list[ProfileSynthesisQueueRecord]:
        """Claim pending → processing atomically (CAS)."""
        ...

    async def complete(self, vip_id: UUID) -> bool:
        """Remove the row after synthesis."""
        ...

    async def recover_stale(self, *, max_age_seconds: int = 3600) -> int:
        """Reset abandoned processing rows back to pending."""
        ...

    async def list_pending(self, limit: int = 100) -> list[ProfileSynthesisQueueRecord]: ...


class TurnOutcomeLogRecord(BaseModel):
    """turn_outcome_log row shape (Fila 4, SPEC-AUTONOMIA-CALIBRACION §7).

    Written post-turn (shadow side) and updated when the owner resolves
    (owner_outcome/sent_score/quality_delta) and when the VIP reaction window
    closes (vip_signal). ``blocked_dims`` is the list of evaluation dimensions
    below the autonomous mins when ``shadow_verdict == "blocked"`` (panel
    "cuellos por dimensión"). Pure calibration metric — never feeds memories /
    examples / vip_profile (anti-contamination).
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    turn_id: UUID
    vip_id: UUID | None
    shadow_verdict: str | None = None  # send | blocked | escalate | doctrine
    shadow_reason: str | None = None
    owner_outcome: str | None = None  # approved_as_is | corrected | escalated
    draft_score: float | None = Field(default=None, ge=0.0, le=1.0)
    sent_score: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_delta: float | None = None
    blocked_dims: list[str] = Field(default_factory=list)
    vip_signal: str | None = None  # positive | neutral | negative | silence
    created_at: datetime | None = None
    updated_at: datetime | None = None


@runtime_checkable
class TurnOutcomeLogStore(Protocol):
    """turn_outcome_log persistence (Fila 4 — the learning circle ledger)."""

    async def insert(self, record: TurnOutcomeLogRecord) -> TurnOutcomeLogRecord: ...

    async def get_by_turn_id(self, turn_id: UUID) -> TurnOutcomeLogRecord | None: ...

    async def update_outcome(
        self,
        turn_id: UUID,
        *,
        owner_outcome: str,
        sent_score: float | None,
        quality_delta: float | None,
    ) -> TurnOutcomeLogRecord | None: ...

    async def update_signal(
        self, turn_id: UUID, *, vip_signal: str
    ) -> TurnOutcomeLogRecord | None: ...

    async def list_by_vip_since(
        self, vip_id: UUID, *, since: datetime, limit: int = 200
    ) -> list[TurnOutcomeLogRecord]: ...

    async def list_recent(
        self, *, since: datetime, limit: int = 500
    ) -> list[TurnOutcomeLogRecord]: ...

    async def count_safety_escalations_since(self, *, since: datetime) -> int: ...

    async def find_pending_signal_for_chat(
        self, chat_id: int, *, since: datetime
    ) -> TurnOutcomeLogRecord | None:
        """C3: most recent row for a chat still missing its VIP reaction."""
        ...

    async def list_signal_pending(
        self, *, window_hours: int, limit: int = 200
    ) -> list[dict]:
        """C3 job: rows without a reaction whose window already closed."""
        ...


@runtime_checkable
class OutcomeSourceReader(Protocol):
    """Fase A on-the-fly source: finished VIP turns with decision context."""

    async def list_finished_source_turns(
        self, *, window_days: int, limit: int = 200
    ) -> list[dict]: ...


@runtime_checkable
class VipTrustBudgetStore(Protocol):
    """(VIP, turn_category) budget persistence — atomic deltas, no trust math.

    The repository applies the SQL delta (increment/decrement) atomically so
    concurrent correction/autonomous events never race; the application service
    decides the deltas and clamps. ``initial`` seeds the INSERT branch.
    """

    async def get_by_vip_and_category(
        self, vip_id: UUID, turn_category: TurnCategory
    ) -> VipTrustBudgetRecord | None: ...

    async def increment_autonomous(
        self,
        vip_id: UUID,
        turn_category: TurnCategory,
        *,
        delta: float,
        initial: float,
    ) -> VipTrustBudgetRecord: ...

    async def decrement_correction(
        self,
        vip_id: UUID,
        turn_category: TurnCategory,
        *,
        delta: float,
        initial: float,
        correction_time: datetime,
    ) -> VipTrustBudgetRecord: ...

    async def list_by_vip(self, vip_id: UUID) -> list[VipTrustBudgetRecord]: ...


@runtime_checkable
class TurnCategoryLogReader(Protocol):
    """Read-only view of the turn classification log (by turn_id)."""

    async def get_by_turn_id(
        self, turn_id: UUID
    ) -> TurnCategoryLogRecord | None: ...


class TurnCategoryLogRecord(BaseModel):
    """turn_category_log row shape — per-turn classification (Fase 2 writer).

    ``id`` / ``created_at`` are optional so the DB ``server_default``
    (``gen_random_uuid()`` / ``now()``) fills them when the caller omits them —
    mirroring ``EmotionalSignalLog``.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    turn_id: UUID
    category: TurnCategory
    chat_id: int
    vip_id: UUID | None = None
    # Fase 2 shadow measurement (migración 026). ``would_autonomous`` is a
    # SHADOW proxy — "the fast-lane WOULD have auto-sent in shadow" (F2
    # measurement), NOT a promise of real auto-send; it ignores vip_trust_budget
    # (EA-01) and the EA-02(3) draft-safety check, both Fase 5. It is also the
    # CALIBRATION SIGNAL for the F2 predictor: the trust budget increments ONLY
    # on ``would_autonomous == True``, and the increment runs BEFORE the real
    # delivery outcome (shadow semantics — a "would have sent" without a send).
    # The accumulated trust is meant to be INTERPRETED / RESET when F2 leaves
    # shadow, when the real auto-send becomes the source of truth (review round
    # 1, S3). ``confidence`` is the classifier's confidence on its
    # PRE-reclassification category (modo "no estoy seguro" = below
    # classifier_confidence_min). NULL = pre-Fase-2 rows.
    would_autonomous: bool | None = None
    confidence: float | None = None
    created_at: datetime | None = None


class EmotionalSignalRecord(BaseModel):
    """emotional_signal_log row shape + detector output (componente transversal).

    ``signal_detected`` is the detector's no-match sentinel; the persisted row
    columns map 1:1 from the other fields. ``pipeline_would_have_escalated`` is
    NULL for fast-lane turns that skipped the Decider (Fase 2).
    """

    model_config = ConfigDict(extra="forbid")

    signal_detected: bool
    signal_type: SignalType | None = None
    intensity: float = 0.0
    should_trigger_synthesis: bool = False
    should_escalate_to_owner: bool = False
    pipeline_would_have_escalated: bool | None = None


@runtime_checkable
class PersonaAdminStore(Protocol):
    """Versioned persona catalog persistence (owner admin, channel-scoped)."""

    async def insert_version(
        self,
        *,
        version: int,
        source: str,
        payload: dict[str, Any],
        created_by: int | None = None,
        channel_type: str = "vip",
    ) -> PersonaVersionRecord: ...

    async def list_versions(
        self, *, channel_type: str | None = None
    ) -> list[PersonaVersionRecord]: ...

    async def get_by_id(self, persona_version_id: UUID) -> PersonaVersionRecord | None: ...

    async def get_active(
        self, *, channel_type: str = "vip"
    ) -> PersonaVersionRecord | None: ...

    async def activate_version(
        self,
        persona_version_id: UUID,
        *,
        now: datetime,
        channel_type: str = "vip",
    ) -> PersonaVersionRecord | None: ...


class EphemeralEventRecord(BaseModel):
    """ephemeral_events row shape — owner-injected time-bounded context.

    Active window is ``[start_at, end_at)`` (half-open): an event past its
    ``end_at`` is simply not found by the augmenter. ``is_paused`` is a
    reversible hold; "terminar antes" sets ``end_at = now`` (terminal).
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    body: str
    start_at: datetime
    end_at: datetime
    is_paused: bool = False
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


@runtime_checkable
class EphemeralEventStore(Protocol):
    """Ephemeral events persistence consumed by service + knowledge augmenter.

    The SQL repo satisfies this structurally (hexagonal: application never
    imports infrastructure).
    """

    async def create(
        self,
        *,
        body: str,
        start_at: datetime,
        end_at: datetime,
        created_by: int | None = None,
    ) -> EphemeralEventRecord: ...

    async def get(self, event_id: UUID) -> EphemeralEventRecord | None: ...

    async def list_all(self) -> list[EphemeralEventRecord]: ...

    async def update(
        self, event_id: UUID, *, body: str, start_at: datetime, end_at: datetime
    ) -> EphemeralEventRecord | None: ...

    async def set_paused(
        self, event_id: UUID, paused: bool
    ) -> EphemeralEventRecord | None: ...

    async def terminate_now(
        self, event_id: UUID, now: datetime
    ) -> EphemeralEventRecord | None: ...

    async def delete(self, event_id: UUID) -> bool: ...

    async def find_active_at(self, now: datetime) -> list[EphemeralEventRecord]: ...

    async def list_open(self, now: datetime) -> list[EphemeralEventRecord]: ...


class BusinessConnectionRecord(BaseModel):
    """business_connections row shape for BC lifecycle persistence."""

    model_config = ConfigDict(extra="forbid")

    business_connection_id: str
    user_id: int
    user_chat_id: int
    date: datetime
    can_reply: bool
    is_enabled: bool


@runtime_checkable
class BusinessConnectionStore(Protocol):
    """Upsert business connection state by business_connection_id."""

    async def upsert(self, record: BusinessConnectionRecord) -> BusinessConnectionRecord: ...


@runtime_checkable
class EscalationStore(Protocol):
    async def create(
        self, turn_id: UUID, *, tipo: str, motivo: str | None
    ) -> None: ...

    async def mark_notified(self, turn_id: UUID) -> None: ...


@runtime_checkable
class MessageHistoryWriter(Protocol):
    """Append-capable history writer (application side)."""

    async def append(
        self,
        chat_id: int,
        *,
        role: str,
        text: str,
        telegram_message_id: int | None = None,
        timestamp: datetime | None = None,
    ) -> None: ...

    async def get_recent(self, chat_id: int, *, limit: int = 20) -> list[dict]: ...

    async def upsert_vip_message(
        self,
        chat_id: int,
        *,
        text: str,
        telegram_message_id: int | None,
        timestamp: datetime | None = None,
    ) -> str:
        """Insert VIP row, or update text if ``telegram_message_id`` already exists.

        Returns ``\"inserted\"`` or ``\"updated\"``. Used for VIP edits so the
        model only sees the latest version of a message, never both.
        """
        ...


@runtime_checkable
class DeliveryResultWriter(Protocol):
    async def set_delivery_result(self, turn_id: UUID, result: dict) -> None: ...


@runtime_checkable
class TraceReader(Protocol):
    async def get_trace_keys(self, turn_id: UUID) -> set[str]: ...

    async def get_full_trace(self, turn_id: UUID) -> dict | None:
        """Full pipeline_trace row as dict, including generated_text."""
        ...

    async def get_recent_comprehension(
        self,
        chat_id: int,
        *,
        limit: int = 5,
        exclude_turn_id: UUID | None = None,
    ) -> list[dict]:
        """Prior-turn comprehension dicts for chat (newest first).

        Emotional baseline source: ``pipeline_traces.comprehension.emotion``.
        Skips rows with missing/empty comprehension.
        """
        ...


@runtime_checkable
class BehaviorCanceller(Protocol):
    """Minimal cancel surface for TurnCoordinator (avoids circular import)."""

    async def cancel_pending(self, chat_id: int, reason: str = "new_message") -> None: ...


@runtime_checkable
class BehaviorDeliverer(Protocol):
    """Deliver gate used by Admin (decoupled from concrete BehaviorEngine)."""

    async def deliver(
        self,
        texts: list[str],
        ctx: Any,
        turn_id: UUID,
        decision: Any | None = None,
        *,
        on_progress: Any | None = None,
    ) -> Any: ...


@runtime_checkable
class TraceabilityReader(Protocol):
    """Read-only trace access for the AdminTraceService.

    Implementations retrieve pipeline trace data from the underlying store
    without modifying it. Returns plain dicts to avoid coupling the protocol
    to ORM or DTO types.
    """

    async def get_recent_turns(self, limit: int = 10, offset: int = 0, chat_id: int | None = None) -> list[dict]: ...
    async def get_full_trace(self, turn_id: UUID) -> dict | None: ...
    async def count_recent(self, chat_id: int | None = None) -> int: ...


@runtime_checkable
class TrainingModeStore(Protocol):
    """Training mode flag for AuthMiddleware gate and config toggle.

    When True, non-VIP business messages pass through the cognitive pipeline
    without VIP attribution (no vip_id/vip_record set in data).
    """

    async def is_enabled(self) -> bool: ...
    async def set_enabled(self, enabled: bool) -> None: ...


@runtime_checkable
class DailyMessageLimitStore(Protocol):
    """Atomic per-chat daily client-message counter (F4-02, atencion).

    Date-keyed: a distinct ``fecha_local`` is a fresh row (count starts at 1).
    The increment is a single ``INSERT ... ON CONFLICT ... DO UPDATE ...
    RETURNING count`` so two concurrent messages never drift.
    """

    async def increment(self, chat_id: int, *, fecha_local: date) -> int: ...


@runtime_checkable
class AtencionCycleStore(Protocol):
    """Chat-level atencion lifecycle (F4): first promo opens a 30-day window.

    ``start_if_absent`` is idempotent: a re-trigger of the promo never resets
    ``started_at`` (linear window, never extended). ``is_active`` requires the
    window open (``started_at >= since``) AND no payment closure. ``close_payment``
    ends the cycle early (owner delivers manually afterwards); it is idempotent
    per chat (only closes an open cycle).
    """

    async def start_if_absent(self, chat_id: int, *, now: datetime) -> None: ...

    async def is_active(
        self, chat_id: int, *, since: datetime, now: datetime
    ) -> bool: ...

    async def close_payment(self, chat_id: int, *, now: datetime) -> None: ...


# --- F3 proactivity (recontact + promo) ports ---------------------------------


class RecontactScheduleRecord(BaseModel):
    """recontact_schedules row shape.

    Status domain: pending | done | cancelled.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    vip_id: UUID
    last_contact_at: datetime
    next_contact_at: datetime | None = None
    status: str


class PromoTriggerRecord(BaseModel):
    """promo_triggers row shape (exact-match text + sequence + re-intro)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    trigger_text: str
    response_sequence: list[str]
    repeat_first_message: str | None = None
    is_active: bool = True


class PromoExecutionRecord(BaseModel):
    """promo_executions row shape.

    Status domain: sent | failed.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    chat_id: int
    trigger_id: UUID
    sent_at: datetime
    sequence_sent: list[str] | dict | None = None
    status: str


@runtime_checkable
class RecontactScheduleStore(Protocol):
    """CRUD/query surface for VIP recontact schedules (no eligibility logic)."""

    async def upsert_pending(
        self,
        vip_id: UUID,
        last_contact_at: datetime,
        next_contact_at: datetime | None,
    ) -> RecontactScheduleRecord: ...

    async def get_pending_by_vip(
        self, vip_id: UUID
    ) -> RecontactScheduleRecord | None: ...

    async def list_due(self, now: datetime) -> list[RecontactScheduleRecord]:
        """Pending rows with next_contact_at <= now."""
        ...

    async def cancel_pending(self, vip_id: UUID) -> bool:
        """pending → cancelled for vip. False if none pending."""
        ...

    async def mark_done(self, schedule_id: UUID) -> bool:
        """Mark schedule done by id. False if not found."""
        ...


@runtime_checkable
class PromoTriggerStore(Protocol):
    """Active promo trigger lookup.

    Match is exact and case-insensitive (strip + lower) against trigger_text.
    """

    async def get_active_by_trigger_text(
        self, text: str
    ) -> PromoTriggerRecord | None: ...

    async def list_active(self) -> list[PromoTriggerRecord]: ...


@runtime_checkable
class PromoExecutionStore(Protocol):
    """Promo delivery history (thin insert/query only)."""

    async def insert(
        self,
        chat_id: int,
        trigger_id: UUID,
        sequence_sent: list[str] | None,
        status: str = "sent",
    ) -> PromoExecutionRecord: ...

    async def latest_for_chat_trigger(
        self, chat_id: int, trigger_id: UUID
    ) -> PromoExecutionRecord | None: ...

    async def was_sent_since(
        self, chat_id: int, trigger_id: UUID, since: datetime
    ) -> bool:
        """True if a status=sent execution exists with sent_at >= since."""
        ...


# --- F5 VIP memory profile (backfill writer DTO) -----------------------------

# Fix round (F6/L3): the visibility gate depends on `status` — the domain is
# enforced at the DTO (Literal + runtime check), at the repo boundary (L7)
# and at the schema level (CheckConstraint `ck_memories_status`, migration 022).
_MEMORY_STATUSES = ("auto", "pending_owner", "approved", "discarded")
MemoryStatus = Literal["auto", "pending_owner", "approved", "discarded"]


@dataclass(frozen=True, slots=True)
class MemoryInsert:
    """One fact row to persist via ``MemoryProfileWriter.replace_vip_profile``.

    Application-side DTO (no ORM/session): the infrastructure repo maps it to
    a ``memories`` row with the canonical ``content`` shape (``texto`` +
    ``fact`` mirror). ``status`` is ``auto`` | ``pending_owner`` | ``approved``
    | ``discarded``; ``source_turn_id`` stays NULL for backfill rows.
    """

    category: str
    text: str
    embedding: list[float]
    confidence: float
    status: MemoryStatus
    source_turn_id: UUID | None = None
    approved_by: str | None = None

    def __post_init__(self) -> None:
        # Fix round (F6): fail fast on out-of-domain status — a typo must not
        # silently turn a sensitive fact visible (or vice versa).
        if self.status not in _MEMORY_STATUSES:
            raise ValueError(
                f"invalid MemoryInsert.status {self.status!r}; "
                f"expected one of {_MEMORY_STATUSES}"
            )


__all__ = [
    "ApprovalRecord",
    "BackfillJobRecord",
    "BehaviorCanceller",
    "BehaviorDeliverer",
    "BusinessConnectionRecord",
    "BusinessConnectionStore",
    "DailyMessageLimitStore",
    "DeliveryContext",
    "DeliveryMode",
    "DeliveryRecord",
    "DeliveryResult",
    "DeliveryResultWriter",
    "DoctrineNotification",
    "DraftNotification",
    "EmotionalSignalRecord",
    "EscalationNotification",
    "EscalationStore",
    "GrayZoneQueryView",
    "GrayZoneServicePort",
    "LinkEventRecord",
    "LinkEventStore",
    "LinkNotification",
    "MemoryInsert",
    "MessageHistoryWriter",
    "OwnerNotifierPort",
    "OutcomeSourceReader",
    "PendingApprovalStore",
    "PendingDeliveryStore",
    "PersonaAdminStore",
    "PersonaVersionRecord",
    "ProfileSynthesisQueueRecord",
    "ProfileSynthesisQueueStore",
    "PromoExecutionRecord",
    "PromoExecutionStore",
    "PromoTriggerRecord",
    "PromoTriggerStore",
    "RecontactScheduleRecord",
    "RecontactScheduleStore",
    "RuntimeTimerRecord",
    "RuntimeTimerStore",
    "TraceabilityReader",
    "TraceReader",
    "TrainingModeStore",
    "TurnCategoryLogRecord",
    "TurnOutcomeLogRecord",
    "TurnOutcomeLogStore",
    "TurnRecord",
    "TurnStore",
    "VipInboundMessage",
    "VipMoodStateRecord",
    "VipProfileHistoryRecord",
    "VipProfileRecord",
    "VipRecord",
    "VipStore",
    "VipTrustBudgetRecord",
]
