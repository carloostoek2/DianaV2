"""F1 cognitive domain contracts (pure Pydantic).

Product vision (AGENTS.md) defines Decision actions as:
  send | approve | escalate | consult_doctrine | regenerate

Fase 1 runtime **restricts** Decision.action to approve | escalate only.
The full action set is reserved for F2+ and must not be exposed here.

EvaluationProfile is a 7-dimension vector. Never collapse it to a single
score (no confidence field, no overall_score, no mean() helper).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
    """7-dimension evaluation vector. Never reduce to a single score."""

    model_config = ConfigDict(extra="forbid")

    naturalness: float
    precision: float
    doctrine: float
    consistency: float
    safety: float
    coverage: float
    empathy: float
    raw_llm_output: dict | None = None


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
    "TERMINAL_TURN_STATUSES",
    "TurnContext",
    "TurnStatus",
    "parse_turn_status",
]
