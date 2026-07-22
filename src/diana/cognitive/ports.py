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

TRACE_KEYS = (
    "comprehension",
    "plan",
    "retrieved",
    "prompt",
    "generated",
    "evaluation",
    "decision",
)


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
    """Records cognitive pipeline artifacts for a turn."""

    async def store(self, turn_id: UUID, key: str, value: Any) -> None: ...


@runtime_checkable
class TurnStatusSink(Protocol):
    """Optional side-channel for turn status transitions (no-op in pure unit tests)."""

    async def transition(self, turn_id: UUID, status: str | TurnStatus) -> None: ...


class InMemoryTraceStore:
    """Dict-backed TraceStore for unit tests."""

    def __init__(self) -> None:
        self.data: dict[UUID, dict[str, Any]] = {}

    async def store(self, turn_id: UUID, key: str, value: Any) -> None:
        bucket = self.data.setdefault(turn_id, {})
        bucket[key] = value

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
]
