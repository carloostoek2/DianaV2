"""F1 cognitive domain contracts (pure Pydantic).

Product vision (AGENTS.md) defines Decision actions as:
  send | approve | escalate | consult_doctrine | regenerate

Fase 1 runtime **restricts** Decision.action to approve | escalate only.
The full action set is reserved for F2+ and must not be exposed here.

EvaluationProfile is a 7-dimension vector. Never collapse it to a single
score (no confidence field, no overall_score, no mean() helper).
Each dimension is a finite float in ``[0.0, 1.0]``.
"""

from __future__ import annotations

import math
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


class IncomingTurn(BaseModel):
    """Inbound turn context consumed by later Analyst protocol."""

    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    chat_id: int
    vip_id: UUID | None = None
    text: str
    telegram_message_id: int | None = None
    business_connection_id: str | None = None


class Comprehension(BaseModel):
    """Analyst output: what is happening in this turn."""

    model_config = ConfigDict(extra="forbid")

    intent: str
    topics: list[str]
    emotion: str
    urgency: Literal["baja", "media", "alta"]
    risk: Literal["bajo", "medio", "alto"]
    needs_memory: bool = False
    needs_policy: bool = False
    needs_schedule: bool = False
    needs_examples: bool = False
    needs_history: bool = True
    needs_context: bool = True
    raw_llm_output: dict | None = None


class Plan(BaseModel):
    """Planner output: which knowledge capabilities to retrieve."""

    model_config = ConfigDict(extra="forbid")

    capabilities: list[str]


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


class Decision(BaseModel):
    """F1 runtime decision — approve | escalate only."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "escalate"]
    reason: str
    evaluation: EvaluationProfile
    draft_text: str | None = None


# Public alias: Director handle_turn argument (no ORM-shaped type).
TurnContext = IncomingTurn

__all__ = [
    "Comprehension",
    "Decision",
    "EvaluationProfile",
    "IncomingTurn",
    "Plan",
    "ScoreUnit",
    "TERMINAL_TURN_STATUSES",
    "TurnContext",
    "TurnStatus",
    "parse_turn_status",
]
