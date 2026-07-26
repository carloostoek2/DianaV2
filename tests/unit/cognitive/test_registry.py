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


def _comprehension() -> Comprehension:
    return Comprehension(
        intent="chat",
        topics=[],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=False,
        needs_schedule=False,
        needs_examples=False,
        needs_history=True,
        needs_context=True,
    )


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
async def test_schedule_is_unimplemented_seat() -> None:
    """H.3: schedule half-registered — resolve OK, fuente=no_implementado, fetch None."""
    assert "knowledge.schedule" in UNIMPLEMENTED_CAPABILITIES
    registry = build_default_registry(InMemoryMessageHistory())
    retriever = registry.resolve("knowledge.schedule")
    assert getattr(retriever, "fuente") == "no_implementado"
    result = await retriever.fetch(_turn(), _comprehension())
    assert result is None


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
    """Profile F2 seat remains registered STUB (not in H.3 table, not removed)."""
    registry = build_default_registry(InMemoryMessageHistory())
    retriever = registry.resolve("knowledge.profile")
    assert await retriever.fetch(_turn(), _comprehension()) is None


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



def test_planner_universe_has_eight_capabilities() -> None:
    """H2: 6 original + persona_facts + voice_patterns."""
    assert len(PLANNER_CAPABILITY_UNIVERSE) == 8
    assert "knowledge.persona_facts" in PLANNER_CAPABILITY_UNIVERSE
    assert "knowledge.voice_patterns" in PLANNER_CAPABILITY_UNIVERSE


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
    """Catalog kwargs wire persona_facts / voice_patterns / static_policies."""
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
    registry = build_default_registry(
        InMemoryMessageHistory(),
        persona_facts=facts,
        voice_patterns=patterns,
        static_policies=policies,
    )
    turn = _turn()
    c = _comprehension()
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
    """Cross-lock: planner map caps == universe; emission is supersequence of both."""
    from diana.cognitive.context_builder import _KNOWLEDGE_EMISSION_ORDER
    from diana.cognitive.planner import _NEED_TO_CAPABILITY
    from diana.cognitive.registry import PLANNER_CAPABILITY_UNIVERSE

    planner_caps = tuple(cap for _, cap in _NEED_TO_CAPABILITY)
    assert planner_caps == PLANNER_CAPABILITY_UNIVERSE

    # Emission order must include every planner cap (may also include profile, etc.).
    emission = list(_KNOWLEDGE_EMISSION_ORDER)
    for cap in planner_caps:
        assert cap in emission, f"{cap} missing from emission order"

    # Relative order among planner caps preserved in emission (supersequence).
    positions = [emission.index(cap) for cap in planner_caps]
    assert positions == sorted(positions)
