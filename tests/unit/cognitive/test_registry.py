"""Unit tests for CapabilityRegistry."""

from __future__ import annotations

import pytest

from diana.cognitive.ports import InMemoryMessageHistory
from diana.cognitive.registry import CapabilityRegistry, build_default_registry


ALL_CAPS = (
    "knowledge.history",
    "knowledge.context",
    "knowledge.profile",
    "knowledge.memory",
    "knowledge.policy",
    "knowledge.examples",
    "knowledge.schedule",
)


def test_default_registry_resolves_all_seven_capabilities() -> None:
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
