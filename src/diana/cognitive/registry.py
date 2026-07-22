"""Capability registry — name → Retriever resolution only."""

from __future__ import annotations

from diana.cognitive.ports import MessageHistoryPort, Retriever
from diana.cognitive.retrievers.context import ContextRetriever
from diana.cognitive.retrievers.examples import ExamplesRetriever
from diana.cognitive.retrievers.history import HistoryRetriever
from diana.cognitive.retrievers.memory import MemoryRetriever
from diana.cognitive.retrievers.policy import PolicyRetriever
from diana.cognitive.retrievers.profile import ProfileRetriever
from diana.cognitive.retrievers.schedule import ScheduleRetriever

DEFAULT_HISTORY_LIMIT = 20


class CapabilityRegistry:
    """Map capability strings to Retriever instances."""

    def __init__(self) -> None:
        self._by_name: dict[str, Retriever] = {}

    def register(self, name: str, retriever: Retriever) -> None:
        self._by_name[name] = retriever

    def resolve(self, name: str) -> Retriever:
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise KeyError(f"unknown capability: {name!r}") from exc

    def capabilities(self) -> list[str]:
        return sorted(self._by_name.keys())


def build_default_registry(
    history_port: MessageHistoryPort,
    *,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
) -> CapabilityRegistry:
    """Register all 7 F1 capabilities (history/context REAL; others STUB)."""
    registry = CapabilityRegistry()
    registry.register(
        "knowledge.history",
        HistoryRetriever(history_port, limit=history_limit),
    )
    registry.register(
        "knowledge.context",
        ContextRetriever(history_port, limit=history_limit),
    )
    registry.register("knowledge.profile", ProfileRetriever())
    registry.register("knowledge.memory", MemoryRetriever())
    registry.register("knowledge.policy", PolicyRetriever())
    registry.register("knowledge.examples", ExamplesRetriever())
    registry.register("knowledge.schedule", ScheduleRetriever())
    return registry
