"""SQLAlchemy 2.0 ORM models for Fase 1 tables only (8 tables)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    func,
    text,
)
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
    # Domain values live in diana.cognitive.models.TurnStatus (TEXT in DB per plan R7).
    status: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    superseded_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
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
    comprehension: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    retrieved: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    delivery_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
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
