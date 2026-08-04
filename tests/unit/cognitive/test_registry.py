"""Unit tests for CapabilityRegistry — Anexo H.1 / H.3 / H.4."""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.ports import InMemoryMessageHistory
from diana.cognitive.registry import (
    PLANNER_CAPABILITY_UNIVERSE,
    UNIMPLEMENTED_CAPABILITIES,
    CapabilityRegistry,
    build_default_registry,
)


ALL_CAPS = (
    "knowledge.history",
    "knowledge.context",
    "knowledge.profile",
    "knowledge.memory",
    "knowledge.policy",
    "knowledge.examples",
    "knowledge.schedule",
    "knowledge.persona_facts",
    "knowledge.voice_patterns",
)


def _turn(chat_id: int = 1) -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=chat_id, text="hola")


def _comprehension(**overrides: object) -> Comprehension:
    data: dict = {
        "intent": "chat",
        "topics": [],
        "emotion": "neutral",
        "urgency": "baja",
        "risk": "bajo",
        "needs_memory": False,
        "needs_policy": False,
        "needs_schedule": False,
        "needs_examples": False,
        "needs_history": True,
        "needs_context": True,
    }
    data.update(overrides)
    return Comprehension(**data)  # type: ignore[arg-type]


def test_default_registry_resolves_all_registered_capabilities() -> None:
    history = InMemoryMessageHistory()
    registry = build_default_registry(history)
    for name in ALL_CAPS:
        retriever = registry.resolve(name)
        assert retriever is not None
        assert hasattr(retriever, "fetch")


def test_unknown_capability_raises_key_error() -> None:
    registry = build_default_registry(InMemoryMessageHistory())
    with pytest.raises(KeyError, match="unknown"):
        registry.resolve("knowledge.unknown")


def test_register_and_resolve_custom() -> None:
    class _Dummy:
        async def fetch(self, turn, comprehension):
            return "x"

    registry = CapabilityRegistry()
    registry.register("knowledge.custom", _Dummy())
    assert registry.resolve("knowledge.custom") is not None


def test_capabilities_lists_registered_names() -> None:
    registry = build_default_registry(InMemoryMessageHistory())
    names = set(registry.capabilities())
    assert names == set(ALL_CAPS)


@pytest.mark.asyncio
async def test_schedule_is_real_seat() -> None:
    """H9: schedule real seat — not unimplemented; fuente agenda_semanal_fija; fetch dict."""
    from datetime import UTC, datetime

    assert "knowledge.schedule" not in UNIMPLEMENTED_CAPABILITIES
    assert UNIMPLEMENTED_CAPABILITIES == frozenset()

    class _FixedClock:
        def now(self) -> datetime:
            # jueves 17:00 CDMX
            return datetime(2026, 7, 23, 23, 0, tzinfo=UTC)

    schedule = {
        "timezone": "America/Mexico_City",
        "default_responses": ["Pues aquí entre cosas jsjsjs y tú?"],
        "bloques": [
            {
                "dias": ["jueves"],
                "inicio": "16:00",
                "fin": "21:00",
                "actividad": "en las prácticas profesionales, en una casa hogar",
            }
        ],
    }
    registry = build_default_registry(
        InMemoryMessageHistory(),
        schedule=schedule,
        clock=_FixedClock(),
    )
    retriever = registry.resolve("knowledge.schedule")
    assert getattr(retriever, "fuente") == "agenda_semanal_fija"
    result = await retriever.fetch(_turn(), _comprehension())
    assert result is not None
    assert result["tipo"] == "actividad"
    assert "prácticas" in result["actividad"]


@pytest.mark.asyncio
async def test_schedule_default_registry_never_unimplemented() -> None:
    """Without schedule kwargs, still real seat (empty bloques → respuesta_libre)."""
    registry = build_default_registry(InMemoryMessageHistory())
    retriever = registry.resolve("knowledge.schedule")
    assert getattr(retriever, "fuente") == "agenda_semanal_fija"
    result = await retriever.fetch(_turn(), _comprehension())
    assert isinstance(result, dict)
    assert result["tipo"] == "respuesta_libre"


def test_build_default_registry_resolves_planner_universe() -> None:
    """H.1: every planner-requestable name resolves after build (no mid-turn surprise)."""
    registry = build_default_registry(InMemoryMessageHistory())
    for name in PLANNER_CAPABILITY_UNIVERSE:
        assert registry.resolve(name) is not None


@pytest.mark.asyncio
async def test_memory_policy_examples_registered_stubs() -> None:
    """H.4: Memory/Policy/Examples registered stubs → always None."""
    registry = build_default_registry(InMemoryMessageHistory())
    turn = _turn()
    c = _comprehension()
    for name in ("knowledge.memory", "knowledge.policy", "knowledge.examples"):
        retriever = registry.resolve(name)
        assert await retriever.fetch(turn, c) is None


@pytest.mark.asyncio
async def test_profile_f2_seat_still_registered() -> None:
    """Profile remains registered; without profile_repo still stubs to None."""
    registry = build_default_registry(InMemoryMessageHistory())
    retriever = registry.resolve("knowledge.profile")
    assert await retriever.fetch(_turn(), _comprehension()) is None


@pytest.mark.asyncio
async def test_profile_real_when_profile_repo_injected() -> None:
    """When profile_repo is injected, profile fetch returns tipo/content on hit."""
    from unittest.mock import AsyncMock

    vip_id = uuid4()
    repo = AsyncMock()
    repo.get_by_vip_id = AsyncMock(
        return_value={
            "vip_id": str(vip_id),
            "tipo": "summary",
            "content": {"pref": "morning"},
        }
    )
    registry = build_default_registry(
        InMemoryMessageHistory(),
        profile_repo=repo,
    )
    turn = IncomingTurn(turn_id=uuid4(), chat_id=1, text="hola", vip_id=vip_id)
    result = await registry.resolve("knowledge.profile").fetch(turn, _comprehension())
    assert result == {"tipo": "summary", "content": {"pref": "morning"}}
    repo.get_by_vip_id.assert_awaited_once_with(vip_id)


@pytest.mark.asyncio
async def test_build_default_registry_accepts_repo_and_embedding_kwargs() -> None:
    """F2 Item 1: registry accepts memory_repo, policy_repo, examples_repo, embedding_service."""
    from unittest.mock import MagicMock

    history = InMemoryMessageHistory()
    fake_repo = MagicMock()
    fake_embed = MagicMock()
    registry = build_default_registry(
        history,
        memory_repo=fake_repo,
        policy_repo=fake_repo,
        examples_repo=fake_repo,
        embedding_service=fake_embed,
    )
    # All 6 planner-requestable caps still resolve.
    for name in PLANNER_CAPABILITY_UNIVERSE:
        retriever = registry.resolve(name)
        assert retriever is not None
        assert hasattr(retriever, "fetch")


@pytest.mark.asyncio
async def test_build_default_registry_without_repos_still_stubs() -> None:
    """F2 Item 1: registry without repo kwargs keeps Memory/Policy/Examples as stubs."""
    history = InMemoryMessageHistory()
    registry = build_default_registry(history)
    turn = _turn()
    c = _comprehension()
    for name in ("knowledge.memory", "knowledge.policy", "knowledge.examples"):
        retriever = registry.resolve(name)
        assert await retriever.fetch(turn, c) is None



def test_planner_universe_has_nine_capabilities() -> None:
    """H2: 6 original + persona_facts + voice_patterns + profile."""
    assert len(PLANNER_CAPABILITY_UNIVERSE) == 9
    assert "knowledge.persona_facts" in PLANNER_CAPABILITY_UNIVERSE
    assert "knowledge.voice_patterns" in PLANNER_CAPABILITY_UNIVERSE
    assert "knowledge.profile" in PLANNER_CAPABILITY_UNIVERSE
    # Profile sits after voice_patterns, before memory (planner map order).
    idx = list(PLANNER_CAPABILITY_UNIVERSE).index
    assert idx("knowledge.voice_patterns") < idx("knowledge.profile") < idx(
        "knowledge.memory"
    )


@pytest.mark.asyncio
async def test_persona_voice_capabilities_resolve_and_empty_fetch() -> None:
    """Empty default catalogs still resolve; fetch returns None."""
    registry = build_default_registry(InMemoryMessageHistory())
    turn = _turn()
    c = _comprehension()
    for name in ("knowledge.persona_facts", "knowledge.voice_patterns"):
        retriever = registry.resolve(name)
        assert await retriever.fetch(turn, c) is None


@pytest.mark.asyncio
async def test_build_default_registry_accepts_catalog_kwargs() -> None:
    """Catalog kwargs wire persona_facts / voice_patterns / static_policies / schedule."""
    from datetime import UTC, datetime

    class _FixedClock:
        def now(self) -> datetime:
            return datetime(2026, 7, 23, 23, 0, tzinfo=UTC)

    facts = [{"id": "f1", "tema": ["familia"], "hecho": "Hermana Laura"}]
    patterns = [
        {
            "id": "p1",
            "tags": ["saludo"],
            "patron": "Holis",
            "uso": "apertura",
        }
    ]
    policies = [
        {
            "id": "no_promesas",
            "tema": ["contenido"],
            "regla": "No prometo fechas",
        }
    ]
    schedule = {
        "timezone": "America/Mexico_City",
        "default_responses": ["gap line"],
        "bloques": [
            {
                "dias": ["jueves"],
                "inicio": "16:00",
                "fin": "21:00",
                "actividad": "en las prácticas profesionales, en una casa hogar",
            }
        ],
    }
    registry = build_default_registry(
        InMemoryMessageHistory(),
        persona_facts=facts,
        voice_patterns=patterns,
        static_policies=policies,
        schedule=schedule,
        clock=_FixedClock(),
    )
    turn = _turn()
    sched = await registry.resolve("knowledge.schedule").fetch(turn, _comprehension())
    assert sched is not None
    assert sched["tipo"] == "actividad"

    # override comprehension for match
    c_facts = Comprehension(
        intent="chat",
        topics=["familia"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=False,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
        needs_persona_facts=True,
    )
    fact = await registry.resolve("knowledge.persona_facts").fetch(turn, c_facts)
    assert fact is not None
    assert "Laura" in fact["hecho"]

    c_voice = Comprehension(
        intent="saludo",
        topics=[],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=False,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
        needs_voice_patterns=True,
    )
    voice = await registry.resolve("knowledge.voice_patterns").fetch(turn, c_voice)
    assert voice is not None
    assert voice["patron"] == "Holis"

    c_pol = Comprehension(
        intent="contenido",
        topics=["contenido"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=True,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
    )
    pol = await registry.resolve("knowledge.policy").fetch(turn, c_pol)
    assert pol == ["Trigger: no_promesas | Rule: No prometo fechas"]



def test_planner_universe_matches_planner_and_emission_supersequence() -> None:
    """Cross-lock: planner map caps == universe; emission includes every planner cap.

    Profile emission position is intentionally last (ContextBuilder D.4) while
    Planner map places profile after voice_patterns / before memory — relative
    order check therefore excludes knowledge.profile only.
    """
    from diana.cognitive.context_builder import _KNOWLEDGE_EMISSION_ORDER
    from diana.cognitive.planner import _NEED_TO_CAPABILITY
    from diana.cognitive.registry import PLANNER_CAPABILITY_UNIVERSE

    planner_caps = tuple(cap for _, cap in _NEED_TO_CAPABILITY)
    assert planner_caps == PLANNER_CAPABILITY_UNIVERSE

    emission = list(_KNOWLEDGE_EMISSION_ORDER)
    for cap in planner_caps:
        assert cap in emission, f"{cap} missing from emission order"

    # Relative order among planner caps preserved in emission, except profile
    # which is emitted last by design (independent of planner request order).
    order_caps = [c for c in planner_caps if c != "knowledge.profile"]
    positions = [emission.index(cap) for cap in order_caps]
    assert positions == sorted(positions)
    assert emission.index("knowledge.profile") == len(emission) - 1


class _FakeProvider:
    """Minimal PersonaCatalogProvider double."""

    def __init__(self, catalog) -> None:
        self.catalog = catalog

    async def get_catalog(self):
        return self.catalog


async def test_registry_propagates_persona_catalog_provider() -> None:
    """build_default_registry wires the provider into the 4 catalog retrievers."""
    provider = _FakeProvider(
        {
            "persona_facts": [{"id": "a", "tema": ["familia"], "hecho": "live fact"}],
            "voice_patterns": [{"id": "p", "tags": ["positiva"], "patron": "holis", "uso": "x"}],
            "policies": [{"id": "pol", "tema": ["contenido"], "regla": "live policy"}],
            "schedule": {
                "timezone": "America/Mexico_City",
                "default_responses": ["live response"],
                "bloques": [],
            },
        }
    )
    registry = build_default_registry(
        InMemoryMessageHistory(),
        persona_catalog_provider=provider,  # type: ignore[arg-type]
    )

    facts = await registry.resolve("knowledge.persona_facts").fetch(
        _turn(), _comprehension(topics=["familia"])
    )
    assert facts is not None and facts["hecho"] == "live fact"

    patterns = await registry.resolve("knowledge.voice_patterns").fetch(
        _turn(), _comprehension(emotion="positiva", intent="saludo", topics=["apertura"])
    )
    assert patterns is not None and patterns["patron"] == "holis"

    policies = await registry.resolve("knowledge.policy").fetch(
        _turn(), _comprehension(topics=["contenido"])
    )
    assert policies == ["Trigger: pol | Rule: live policy"]

    schedule = await registry.resolve("knowledge.schedule").fetch(
        _turn(), _comprehension()
    )
    assert schedule is not None and schedule["tipo"] == "respuesta_libre"
    assert schedule["respuesta_sugerida"] == "live response"



async def test_registry_static_slices_plus_provider_combination() -> None:
    """Static slices remain the fallback when the provider reports None."""
    static_facts = [{"id": "s", "tema": ["familia"], "hecho": "static fact"}]
    provider = _FakeProvider(None)
    registry = build_default_registry(
        InMemoryMessageHistory(),
        persona_facts=static_facts,
        persona_catalog_provider=provider,  # type: ignore[arg-type]
    )
    result = await registry.resolve("knowledge.persona_facts").fetch(
        _turn(), _comprehension(topics=["familia"])
    )
    assert result is not None and result["hecho"] == "static fact"
