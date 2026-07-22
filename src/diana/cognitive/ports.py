"""I/O boundaries for the cognitive core (ports + test doubles).

Cognitive components depend only on these protocols. Concrete LLM clients and
SQL repositories live outside ``diana.cognitive`` and are injected at the
composition root (or in tests).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel

from diana.cognitive.models import Comprehension, IncomingTurn, TurnStatus

# Public alias: handle_turn argument is IncomingTurn (no ORM-shaped type).
TurnContext = IncomingTurn

# Keys align with pipeline_traces column names where applicable:
# prompt_text / generated_text match SQL columns; others are JSONB columns.
TRACE_KEYS = (
    "comprehension",
    "plan",
    "retrieved",
    "prompt_text",
    "generated_text",
    "evaluation",
    "decision",
)

# Map TRACE_KEYS → pipeline_traces ORM column names (identity except already aligned).
TRACE_KEY_TO_COLUMN: dict[str, str] = {
    "comprehension": "comprehension",
    "plan": "plan",
    "retrieved": "retrieved",
    "prompt_text": "prompt_text",
    "generated_text": "generated_text",
    "evaluation": "evaluation",
    "decision": "decision",
}


def to_jsonable(value: Any) -> Any:
    """Convert Pydantic models / nested structures to JSON-ready snapshots."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


@runtime_checkable
class LLMProvider(Protocol):
    """Swapable LLM I/O surface used by Analyst, Generator, Evaluator."""

    name: str

    async def generate(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str: ...

    async def generate_structured(
        self,
        messages: list[dict],
        schema: type[BaseModel],
        **kwargs: Any,
    ) -> BaseModel: ...


@runtime_checkable
class Retriever(Protocol):
    """Capability-scoped knowledge fetch. Returns None when unavailable."""

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> Any | None: ...


@runtime_checkable
class MessageHistoryPort(Protocol):
    """Chat-scoped message history. Implementations must filter by chat_id only."""

    async def get_recent(self, chat_id: int, *, limit: int = 20) -> list[dict]: ...


@runtime_checkable
class TraceStore(Protocol):
    """Records cognitive pipeline artifacts for a turn.

    Implementations SHOULD accept JSON-ready values. Director stores
    ``model_dump(mode=\"json\")`` snapshots (not live Pydantic instances).
    """

    async def store(self, turn_id: UUID, key: str, value: Any) -> None: ...


@runtime_checkable
class TurnStatusSink(Protocol):
    """Optional side-channel for turn status transitions (no-op in pure unit tests)."""

    async def transition(self, turn_id: UUID, status: str | TurnStatus) -> None: ...


class InMemoryTraceStore:
    """Dict-backed TraceStore for unit tests (stores JSON-ready values as given)."""

    def __init__(self) -> None:
        self.data: dict[UUID, dict[str, Any]] = {}

    async def store(self, turn_id: UUID, key: str, value: Any) -> None:
        bucket = self.data.setdefault(turn_id, {})
        # Defensive copy so later mutations do not alias into the bucket.
        bucket[key] = to_jsonable(value)

    def get(self, turn_id: UUID, key: str) -> Any | None:
        return self.data.get(turn_id, {}).get(key)

    def keys_for(self, turn_id: UUID) -> set[str]:
        return set(self.data.get(turn_id, {}).keys())


class InMemoryMessageHistory:
    """Map chat_id -> list[dict] implementing MessageHistoryPort."""

    def __init__(self, messages_by_chat: dict[int, list[dict]] | None = None) -> None:
        self._messages: dict[int, list[dict]] = {
            chat_id: list(msgs) for chat_id, msgs in (messages_by_chat or {}).items()
        }

    async def get_recent(self, chat_id: int, *, limit: int = 20) -> list[dict]:
        history = self._messages.get(chat_id, [])
        if limit <= 0:
            return []
        return list(history[-limit:])

    def seed(self, chat_id: int, messages: list[dict]) -> None:
        self._messages[chat_id] = list(messages)


class NoOpTurnStatusSink:
    """Discard status transitions."""

    async def transition(self, turn_id: UUID, status: str | TurnStatus) -> None:
        return None


class InMemoryTurnStatusSink:
    """Records status transitions for assertions."""

    def __init__(self) -> None:
        self.transitions: list[tuple[UUID, str]] = []

    async def transition(self, turn_id: UUID, status: str | TurnStatus) -> None:
        value = status.value if isinstance(status, TurnStatus) else str(status)
        self.transitions.append((turn_id, value))


__all__ = [
    "TRACE_KEYS",
    "TRACE_KEY_TO_COLUMN",
    "InMemoryMessageHistory",
    "InMemoryTraceStore",
    "InMemoryTurnStatusSink",
    "LLMProvider",
    "MessageHistoryPort",
    "NoOpTurnStatusSink",
    "Retriever",
    "TraceStore",
    "TurnContext",
    "TurnStatusSink",
    "to_jsonable",
]
