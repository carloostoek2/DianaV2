"""Capability registry — name → Retriever resolution only (Anexo H.1)."""

from __future__ import annotations

from typing import Any

from diana.cognitive.ports import MessageHistoryPort, Retriever
from diana.cognitive.retrievers.context import ContextRetriever
from diana.cognitive.retrievers.examples import ExamplesRetriever
from diana.cognitive.retrievers.history import HistoryRetriever
from diana.cognitive.retrievers.memory import MemoryRetriever
from diana.cognitive.retrievers.policy import PolicyRetriever
from diana.cognitive.retrievers.profile import ProfileRetriever
from diana.cognitive.retrievers.schedule import ScheduleRetriever

DEFAULT_HISTORY_LIMIT = 20

# Half-registered seats: resolve OK, fetch → None, optional fuente attribute.
UNIMPLEMENTED_CAPABILITIES: frozenset[str] = frozenset({"knowledge.schedule"})

# Planner-requestable names in F1 (Anexo C + H). Must resolve after build.
PLANNER_CAPABILITY_UNIVERSE: tuple[str, ...] = (
    "knowledge.history",
    "knowledge.context",
    "knowledge.memory",
    "knowledge.policy",
    "knowledge.examples",
    "knowledge.schedule",
)


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
    memory_repo: Any = None,
    policy_repo: Any = None,
    examples_repo: Any = None,
    embedding_service: Any = None,
) -> CapabilityRegistry:
    """Register F1 capabilities and fail-fast for the planner universe.

    Seven seats: history/context REAL; memory/policy/examples REAL when
    their ``*_repo`` and ``embedding_service`` are provided, STUB otherwise;
    schedule half-registered (``fuente=no_implementado``, fetch always None).
    Profile is an F2 seat outside the planner universe but remains registered.
    """
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
    registry.register(
        "knowledge.memory",
        MemoryRetriever(
            embedding_service=embedding_service,
            repo=memory_repo,
        ),
    )
    registry.register(
        "knowledge.policy",
        PolicyRetriever(
            embedding_service=embedding_service,
            repo=policy_repo,
        ),
    )
    registry.register(
        "knowledge.examples",
        ExamplesRetriever(
            embedding_service=embedding_service,
            repo=examples_repo,
        ),
    )
    registry.register("knowledge.schedule", ScheduleRetriever())
    # Boot fail-fast: planner-requested names must resolve (H.1).
    for name in PLANNER_CAPABILITY_UNIVERSE:
        registry.resolve(name)
    return registry
