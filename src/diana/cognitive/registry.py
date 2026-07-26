"""Capability registry — name → Retriever resolution only (Anexo H.1)."""

from __future__ import annotations

from typing import Any

from diana.cognitive.ports import MessageHistoryPort, Retriever
from diana.cognitive.retrievers.context import ContextRetriever
from diana.cognitive.retrievers.examples import ExamplesRetriever
from diana.cognitive.retrievers.history import HistoryRetriever
from diana.cognitive.retrievers.memory import MemoryRetriever
from diana.cognitive.retrievers.persona_facts import PersonaFactsRetriever
from diana.cognitive.retrievers.policy import PolicyRetriever
from diana.cognitive.retrievers.profile import ProfileRetriever
from diana.cognitive.retrievers.schedule import ScheduleRetriever
from diana.cognitive.retrievers.voice_patterns import VoicePatternsRetriever

DEFAULT_HISTORY_LIMIT = 20

# Half-registered seats: resolve OK, fetch → None, optional fuente attribute.
UNIMPLEMENTED_CAPABILITIES: frozenset[str] = frozenset({"knowledge.schedule"})

# Planner-requestable names (Anexo C + H + system prompt struct). Must resolve after build.
PLANNER_CAPABILITY_UNIVERSE: tuple[str, ...] = (
    "knowledge.history",
    "knowledge.context",
    "knowledge.persona_facts",
    "knowledge.voice_patterns",
    "knowledge.profile",
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
    profile_repo: Any = None,
    embedding_service: Any = None,
    persona_facts: list | None = None,
    voice_patterns: list | None = None,
    static_policies: list | None = None,
) -> CapabilityRegistry:
    """Register capabilities and fail-fast for the planner universe.

    Seats: history/context REAL; persona_facts/voice_patterns from static
    catalogs (empty → always None); memory/policy/examples REAL when their
    ``*_repo`` and ``embedding_service`` are provided, STUB otherwise (policy
    may still match static_policies); profile REAL when ``profile_repo`` is
    provided (PK VIP lookup), STUB otherwise; schedule half-registered
    (``fuente=no_implementado``, fetch always None). Profile is always
    registered (stub or real).
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
    registry.register(
        "knowledge.profile",
        ProfileRetriever(repo=profile_repo),
    )
    registry.register(
        "knowledge.persona_facts",
        PersonaFactsRetriever(persona_facts or []),
    )
    registry.register(
        "knowledge.voice_patterns",
        VoicePatternsRetriever(voice_patterns or []),
    )
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
            static_policies=static_policies,
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
