"""Capability registry — name → Retriever resolution only (Anexo H.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from diana.cognitive.ports import ClockPort, MessageHistoryPort, PersonaCatalogProvider, Retriever
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
# Empty after H9 (schedule is real). Kept for future half-seats.
UNIMPLEMENTED_CAPABILITIES: frozenset[str] = frozenset()

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

_DEFAULT_SCHEDULE_TZ = "America/Mexico_City"
_DEFAULT_SCHEDULE_RESPONSE = "Pues aquí entre cosas jsjsjs y tú?"


class _UtcNowClock:
    """Minimal ClockPort when composition does not inject a clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


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
    schedule: dict | None = None,
    clock: ClockPort | None = None,
    persona_catalog_provider: PersonaCatalogProvider | None = None,
) -> CapabilityRegistry:
    """Register capabilities and fail-fast for the planner universe.

    Seats: history/context REAL; persona_facts/voice_patterns from static
    catalogs (empty → always None); memory/policy/examples REAL when their
    ``*_repo`` and ``embedding_service`` are provided, STUB otherwise (policy
    may still match static_policies); profile REAL when ``profile_repo`` is
    provided (PK VIP lookup), STUB otherwise; schedule REAL from fixed weekly
    agenda (empty bloques still yields respuesta_libre). Profile is always
    registered (stub or real).
    """
    resolved_clock: ClockPort = clock if clock is not None else _UtcNowClock()
    cfg = schedule or {}
    bloques = list(cfg.get("bloques") or [])
    defaults = list(cfg.get("default_responses") or [_DEFAULT_SCHEDULE_RESPONSE])
    tz_name = str(cfg.get("timezone") or _DEFAULT_SCHEDULE_TZ)

    registry = CapabilityRegistry()
    registry.register(
        "knowledge.history",
        HistoryRetriever(history_port, limit=history_limit),
    )
    registry.register(
        "knowledge.context",
        ContextRetriever(history_port, limit=history_limit, clock=resolved_clock.now),
    )
    registry.register(
        "knowledge.profile",
        ProfileRetriever(repo=profile_repo),
    )
    registry.register(
        "knowledge.persona_facts",
        PersonaFactsRetriever(
            persona_facts or [],
            persona_catalog_provider=persona_catalog_provider,
        ),
    )
    registry.register(
        "knowledge.voice_patterns",
        VoicePatternsRetriever(
            voice_patterns or [],
            persona_catalog_provider=persona_catalog_provider,
        ),
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
            persona_catalog_provider=persona_catalog_provider,
        ),
    )
    registry.register(
        "knowledge.examples",
        ExamplesRetriever(
            embedding_service=embedding_service,
            repo=examples_repo,
        ),
    )
    registry.register(
        "knowledge.schedule",
        ScheduleRetriever(
            bloques,
            defaults,
            tz_name,
            resolved_clock,
            persona_catalog_provider=persona_catalog_provider,
        ),
    )
    # Boot fail-fast: planner-requested names must resolve (H.1).
    for name in PLANNER_CAPABILITY_UNIVERSE:
        registry.resolve(name)
    return registry
