"""SQLAlchemy 2.0 ORM models for F1 + F2 knowledge + F3 proactivity tables."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for Diana ORM models."""


class Vip(Base):
    __tablename__ = "vips"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frozen_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_send: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class MessageHistory(Base):
    __tablename__ = "message_history"
    __table_args__ = (
        Index("ix_message_history_chat_id_timestamp", "chat_id", text("timestamp DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # vip | owner | bot
    text: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (
        Index("ix_turns_chat_id_status", "chat_id", "status"),
        Index("ix_turns_chat_id_created_at", "chat_id", text("created_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vip_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("vips.id"),
        nullable=True,
    )
    # F4 channel tag ("vip" | "atencion"); default 'vip' keeps pre-F4 rows/behavior.
    channel_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'vip'")
    )
    # Domain values live in diana.cognitive.models.TurnStatus (TEXT in DB per plan R7).
    status: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    superseded_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    # Failure reason (e.g. analista_schema_invalido). Nullable; set on mark_failed.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PipelineTrace(Base):
    __tablename__ = "pipeline_traces"
    __table_args__ = (
        Index("ix_pipeline_traces_turn_id", "turn_id"),
        Index("ix_pipeline_traces_vip_id_created_at", "vip_id", text("created_at DESC")),
        Index("ix_pipeline_traces_chat_id_created_at", "chat_id", text("created_at DESC")),
        Index("pipeline_traces_created_at_idx", text("created_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    turn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("turns.id"),
        nullable=False,
    )
    vip_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("vips.id"),
        nullable=True,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # F4 channel tag ("vip" | "atencion"); default 'vip' keeps pre-F4 rows/behavior.
    channel_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'vip'")
    )
    comprehension: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    retrieved: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    delivery_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    timings: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PendingDelivery(Base):
    __tablename__ = "pending_deliveries"
    __table_args__ = (Index("ix_pending_deliveries_status_scheduled_at", "status", "scheduled_at"),)

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vip_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("vips.id"),
        nullable=True,
    )
    business_connection_id: Mapped[str] = mapped_column(Text, nullable=False)
    texts: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    decision: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    # Referential integrity to turns (F1 foundation integrity).
    turn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("turns.id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PendingApproval(Base):
    __tablename__ = "pending_approvals"
    __table_args__ = (Index("ix_pending_approvals_status_created_at", "status", "created_at"),)

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    turn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("turns.id"),
        unique=True,
        nullable=False,
    )
    vip_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("vips.id"),
        nullable=True,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    business_connection_id: Mapped[str] = mapped_column(Text, nullable=False)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    cognitive_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'waiting'"))
    owner_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EscalationEvent(Base):
    __tablename__ = "escalation_events"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    turn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("turns.id"),
        nullable=False,
    )
    tipo: Mapped[str] = mapped_column(Text, nullable=False)
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    notificado: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class SystemConfig(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Profile(Base):
    """VIP profile vector store — one embedding row per VIP."""

    __tablename__ = "profiles"

    vip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vips.id"), primary_key=True,
    )
    embedding: Mapped[Any] = mapped_column(Vector(384), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    tipo: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class Memory(Base):
    """VIP-scoped episodic memory with embedding (BR-15: always filter by vip_id)."""

    __tablename__ = "memories"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"),
    )
    vip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vips.id"), nullable=False,
    )
    embedding: Mapped[Any] = mapped_column(Vector(384), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class Context(Base):
    """Chat-scoped context window (short-lived, expires)."""

    __tablename__ = "contexts"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"),
    )
    vip_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vips.id"), nullable=True,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(384), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class Policy(Base):
    """Vector-indexed business policy (active + scope-filtered at query time)."""

    __tablename__ = "policies"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"),
    )
    embedding: Mapped[Any] = mapped_column(Vector(384), nullable=False)
    trigger_description: Mapped[str] = mapped_column(Text, nullable=False)
    rule: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'all'"))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"),
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_query_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True,
        # Intentionally no FK: gray_zone_queries may be cleaned independently.
        # Loose coupling avoids circular deletion constraints during staging.
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class Example(Base):
    """Curated example pool (never populated from memory — staging bridge only)."""

    __tablename__ = "examples"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"),
    )
    embedding: Mapped[Any] = mapped_column(Vector(384), nullable=False)
    turn_text: Mapped[str] = mapped_column(Text, nullable=False)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_counter_example: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class StagingCandidate(Base):
    """Unverified learning artifact awaiting promotion (staging bridge)."""

    __tablename__ = "staging_candidates"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"),
    )
    candidate_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'"),
    )
    turn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("turns.id"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class GrayZoneQuery(Base):
    """Open doctrinal question awaiting owner resolution."""

    __tablename__ = "gray_zone_queries"
    __table_args__ = (
        Index("ix_gray_zone_queries_chat_id", "chat_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"),
    )
    vip_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vips.id"), nullable=True,
    )
    # F4: atencion chat freeze resolves by chat_id (vip_id is NULL there).
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # F4: source business connection for supervised-delivery reconstruction.
    business_connection_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    turn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("turns.id"), nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    draft: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'open'"),
    )
    freeze_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LearningMetric(Base):
    """Post-turn learning metrics (F3+). Schema completeness only."""

    __tablename__ = "learning_metrics"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"),
    )
    vip_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vips.id"), nullable=True,
    )
    metric_name: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class RecontactSchedule(Base):
    """Scheduled recontact for a VIP after inactivity (F3 proactivity)."""

    __tablename__ = "recontact_schedules"
    __table_args__ = (
        Index("ix_recontact_schedules_next_status", "next_contact_at", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"),
    )
    vip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("vips.id", ondelete="CASCADE"),
        nullable=False,
    )
    last_contact_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    next_contact_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class PromoTrigger(Base):
    """Exact-match promo trigger with multi-message sequence (F3 proactivity)."""

    __tablename__ = "promo_triggers"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"),
    )
    trigger_text: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    response_sequence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    repeat_first_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class PromoExecution(Base):
    """Record of a promo sequence delivery to a chat (F3 proactivity)."""

    __tablename__ = "promo_executions"
    __table_args__ = (
        Index(
            "ix_promo_executions_chat_trigger_sent",
            "chat_id",
            "trigger_id",
            text("sent_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"),
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    trigger_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("promo_triggers.id"), nullable=False,
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    sequence_sent: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'sent'"),
    )


class OwnerMark(Base):
    """Owner feedback on a turn (e.g. false_positive escalation mark)."""

    __tablename__ = "owner_marks"
    __table_args__ = (
        Index("ix_owner_marks_kind_created", "kind", "created_at"),
    )

    turn_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class PersonaVersion(Base):
    """Versioned persona catalog snapshot (owner admin, Item 1).

    Each row stores a complete validated persona catalog dict
    (voz_configurada, persona_facts, voice_patterns, policies, schedule).
    At most one row per channel is active (enforced by the partial unique
    index ``uq_persona_versions_active`` over ``(channel_type, is_active)``).
    ``channel_type`` is ``vip`` | ``atencion``; the version counter is a
    global sequence shared across channels.
    """

    __tablename__ = "persona_versions"
    __table_args__ = (
        Index("ix_persona_versions_created_at", text("created_at DESC")),
        Index(
            "uq_persona_versions_active",
            "channel_type",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("uq_persona_versions_version", "version", unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    channel_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'vip'")
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


class DailyMessageLimit(Base):
    """Per-chat daily client-message counter (F4-02, atencion channel).

    Keyed by ``(chat_id, fecha_local)`` so the count resets when the local day
    (``America/Mexico_City``) changes. The increment/enforce logic is Item 2;
    this item only creates the schema.
    """

    __tablename__ = "daily_message_limits"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fecha_local: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
