"""Cognitive domain contracts (pure Pydantic).

Product vision (AGENTS.md) defines Decision actions as:
  send | approve | escalate | consult_doctrine | regenerate

F3 **type surface** exposes: approve | escalate | consult_doctrine | send
(``Decision.action`` is constructible with ``send``). Runtime emission of
``send`` is deferred to Decider (item 2) and orchestrator delivery (item 3);
until then producers stay on the F2 action set and unknown paths fail closed.
regenerate remains reserved / out of scope (still rejected by the Literal).

EvaluationProfile is a 7-dimension vector. Never collapse it to a single
score (no confidence field, no overall_score, no mean() helper).
Each dimension is a finite float in ``[0.0, 1.0]``.
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Unit-interval score for EvaluationProfile dimensions.
ScoreUnit = Annotated[float, Field(ge=0.0, le=1.0)]

_EVAL_DIMS = (
    "naturalness",
    "precision",
    "doctrine",
    "consistency",
    "safety",
    "coverage",
    "empathy",
)


class TurnStatus(StrEnum):
    """Turn state machine values for Fase 1."""

    RECEIVED = "received"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    RETRIEVING = "retrieving"
    BUILDING_CONTEXT = "building_context"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    DECIDING = "deciding"
    PENDING_APPROVAL = "pending_approval"
    GRAY_ZONE = "gray_zone"
    ESCALATED = "escalated"
    SUPERSEDED = "superseded"
    DELIVERED = "delivered"
    FAILED = "failed"


TERMINAL_TURN_STATUSES: frozenset[TurnStatus] = frozenset(
    {
        TurnStatus.SUPERSEDED,
        TurnStatus.DELIVERED,
        TurnStatus.FAILED,
        TurnStatus.ESCALATED,
    }
)


def parse_turn_status(value: str) -> TurnStatus:
    """Parse a free-text turn status into the domain enum (raises ValueError)."""
    try:
        return TurnStatus(value)
    except ValueError as exc:
        raise ValueError(f"invalid turn status: {value!r}") from exc


def is_turn_status_terminal(status: str) -> bool:
    """Check whether a free-text turn status is terminal.

    Safe for any string (returns False for unknown status values).
    """
    try:
        return parse_turn_status(status) in TERMINAL_TURN_STATUSES
    except ValueError:
        return False


class IncomingTurn(BaseModel):
    """Inbound turn context consumed by later Analyst protocol."""

    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    chat_id: int
    vip_id: UUID | None = None
    text: str
    telegram_message_id: int | None = None
    business_connection_id: str | None = None


# Closed emotion enum (contrato_analista.md A.3). Free strings are forbidden.
Emotion = Literal[
    "neutral",
    "positiva",
    "ansiosa",
    "molesta",
    "triste",
    "cariñosa",
    "urgente",
]


class HistoryMessage(BaseModel):
    """One short-window history line for Analyst input (contrato A.2)."""

    model_config = ConfigDict(extra="forbid")

    autor: Literal["vip", "dueña"]
    texto: str
    timestamp: datetime | str


class AnalystInput(BaseModel):
    """Analyst input: current turn text + short chat-scoped history only."""

    model_config = ConfigDict(extra="forbid")

    turno_actual: str
    historial_reciente: list[HistoryMessage]


class Comprehension(BaseModel):
    """Analyst output: what is happening in this turn (contrato A.3).

    All six needs_* flags are required — no partial comprehension.
    Optional internal raw capture field is excluded from LLM required set.
    """

    model_config = ConfigDict(extra="forbid")

    intent: str
    topics: list[str]
    emotion: Emotion
    urgency: Literal["baja", "media", "alta"]
    risk: Literal["bajo", "medio", "alto"]
    needs_memory: bool
    needs_policy: bool
    needs_schedule: bool
    needs_examples: bool
    needs_history: bool
    needs_context: bool
    raw_llm_output: dict | None = None


class Plan(BaseModel):
    """Planner output (Anexo C.2): which knowledge capabilities to retrieve.

    English field ``capabilities`` maps to Spanish contract name
    ``capacidades_solicitadas``. Empty list is legal when all needs_* are false.
    """

    model_config = ConfigDict(extra="forbid")

    capabilities: list[str]




class BuiltContext(BaseModel):
    """ContextBuilder output (Anexo D.3).

    English fields map to Spanish contract names:
    prompt_final←prompt_final, included_blocks←bloques_incluidos.
    """

    model_config = ConfigDict(extra="forbid")

    prompt_final: str
    included_blocks: list[str]


class EvaluatorInput(BaseModel):
    """Evaluator input (Anexo B.2).

    English fields map to Spanish contract names:
    draft←borrador, comprehension←comprension,
    included_blocks←bloques_incluidos, current_turn←turno_actual.
    """

    model_config = ConfigDict(extra="forbid")

    draft: str
    comprehension: Comprehension
    included_blocks: list[str]
    current_turn: str


class EvaluationProfile(BaseModel):
    """7-dimension evaluation vector. Never reduce to a single score.

    Each dimension must be a finite float in [0.0, 1.0] so the Decider
    safety gate cannot be bypassed by NaN or out-of-range LLM values.
    """

    model_config = ConfigDict(extra="forbid")

    naturalness: ScoreUnit
    precision: ScoreUnit
    doctrine: ScoreUnit
    consistency: ScoreUnit
    safety: ScoreUnit
    coverage: ScoreUnit
    empathy: ScoreUnit
    raw_llm_output: dict | None = None

    @field_validator(*_EVAL_DIMS, mode="after")
    @classmethod
    def dims_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("evaluation dimension must be a finite float in [0, 1]")
        return value


class Policy(BaseModel):
    """Pure domain model for a distilled business policy (non-ORM).

    Used by PolicyDistiller (cognitive/) and StagingService (application/)
    as a shared data contract. NOT the same as db/models.Policy (ORM).
    """

    model_config = ConfigDict(extra="forbid")

    trigger_description: str
    rule: str
    scope: str = "all"
    is_active: bool = True
    source_query_id: UUID | None = None
    created_at: datetime | None = None
    id: UUID | None = None


class Decision(BaseModel):
    """F3 decision type surface — approve | escalate | consult_doctrine | send.

    F1 actions: approve, escalate.
    F2 extension: consult_doctrine (gray zone doctrine query).
    F3 extension: send is constructible and **emitted** by Decider when
    ``feature_autonomous_mode`` is injected and evaluation dims meet
    autonomous mins (item2). Orchestrator deliver branch remains item3
    (fail-closed on send until then).

    Maps Anexo F DecisorOutput: action←accion, reason←razon,
    mode_restriction_applied←restriccion_de_modo_aplicada.
    regenerate remains residual / out of scope.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "escalate", "consult_doctrine", "send"]
    reason: str
    evaluation: EvaluationProfile
    draft_text: str | None = None
    mode_restriction_applied: str | None = None


# Public alias: Director handle_turn argument (no ORM-shaped type).
TurnContext = IncomingTurn

__all__ = [
    "AnalystInput",
    "BuiltContext",
    "Comprehension",
    "Decision",
    "Emotion",
    "EvaluationProfile",
    "EvaluatorInput",
    "Policy",
    "HistoryMessage",
    "IncomingTurn",
    "Plan",
    "ScoreUnit",
    "TERMINAL_TURN_STATUSES",
    "TurnContext",
    "TurnStatus",
    "is_turn_status_terminal",
    "parse_turn_status",
]
