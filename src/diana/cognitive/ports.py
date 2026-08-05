"""I/O boundaries for the cognitive core (ports + test doubles).

Cognitive components depend only on these protocols. Concrete LLM clients and
SQL repositories live outside ``diana.cognitive`` and are injected at the
composition root (or in tests).
"""

from __future__ import annotations

from datetime import datetime
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
    "timings": "timings",
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
class PersonaCatalogProvider(Protocol):
    """Live persona catalog source for retrievers + Director (hot-reload).

    Concrete implementation lives in ``diana.application.persona_catalog_provider``
    (injected at the composition root). Returns the FULL validated catalog dict
    (voz_configurada, persona_facts, voice_patterns, policies, schedule) or
    ``None`` to signal "no live catalog — keep the static fallback".

    ``channel_type`` scopes the read: ``"vip"`` (default) resolves the VIP
    persona, ``"atencion"`` the non-VIP service persona.
    """

    async def get_catalog(
        self, channel_type: str = "vip"
    ) -> dict[str, Any] | None: ...


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
class ClockPort(Protocol):
    """Timezone-aware wall clock for cognitive retrievers (H9).

    Production injects composition ``SystemClock`` (duck-typed). Tests use fixed
    aware datetimes. Defined here so cognitive never imports ``diana.application``.
    """

    def now(self) -> datetime: ...


@runtime_checkable
class Retriever(Protocol):
    """Capability-scoped knowledge fetch (Anexo H.2).

    Runtime contract: ``fetch`` returns the bare **resultado** (or None when
    unavailable / stub). The Director stores that value directly in the
    knowledge map — there is no Spanish envelope DTO at runtime.

    Conceptual Anexo H.2 envelope (documentation only)::

        {capacidad, resultado, fuente}

    - ``resultado`` ↔ bare return value of ``fetch``
    - ``capacidad`` ↔ registry name used at ``resolve``
    - ``fuente`` ↔ optional class attribute on retrievers that expose provenance
      (e.g. ScheduleRetriever.fuente = \"agenda_semanal_fija\")

    ``IncomingTurn.chat_id`` supplies the chat scope for history/context ports.
    """

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> Any | None: ...


@runtime_checkable
class KnowledgeAugmenter(Protocol):
    """Optional post-retrieval inject (e.g. sandbox fixture profile).

    Application-layer implementations only. Cognitive must not import sandbox.
    """

    async def augment_retrieved(
        self,
        turn: IncomingTurn,
        retrieved: dict[str, Any | None],
    ) -> dict[str, Any | None]: ...


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
class RecentIntentsPort(Protocol):
    """Prior-turn intents for repetition detection (H4).

    Returns intent strings newest-first (DESC). Implementations MUST skip
    missing/empty intent rows. ``exclude_turn_id`` drops the current turn when
    comprehension was already stored.
    """

    async def get_recent_intents(
        self,
        chat_id: int,
        *,
        limit: int = 2,
        exclude_turn_id: UUID | None = None,
    ) -> list[str]: ...



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



class InMemoryRecentIntents:
    """Test double for RecentIntentsPort.

    Seeds store ``(turn_id|None, intent)`` newest-first per chat_id.
    """

    def __init__(self) -> None:
        self._by_chat: dict[int, list[tuple[UUID | None, str]]] = {}

    def seed(
        self,
        chat_id: int,
        intents: list[str] | list[tuple[UUID | None, str]],
    ) -> None:
        rows: list[tuple[UUID | None, str]] = []
        for item in intents:
            if isinstance(item, tuple):
                rows.append(item)
            else:
                rows.append((None, item))
        self._by_chat[chat_id] = rows

    async def get_recent_intents(
        self,
        chat_id: int,
        *,
        limit: int = 2,
        exclude_turn_id: UUID | None = None,
    ) -> list[str]:
        rows = self._by_chat.get(chat_id, [])
        out: list[str] = []
        for turn_id, intent in rows:
            if exclude_turn_id is not None and turn_id == exclude_turn_id:
                continue
            if not intent or not str(intent).strip():
                continue
            out.append(str(intent))
            if len(out) >= limit:
                break
        return out


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
    "ClockPort",
    "InMemoryMessageHistory",
    "InMemoryRecentIntents",
    "InMemoryTraceStore",
    "InMemoryTurnStatusSink",
    "KnowledgeAugmenter",
    "LLMProvider",
    "MessageHistoryPort",
    "NoOpTurnStatusSink",
    "PersonaCatalogProvider",
    "RecentIntentsPort",
    "Retriever",
    "TraceStore",
    "TurnContext",
    "TurnStatusSink",
    "to_jsonable",
]
