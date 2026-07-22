"""Deterministic capability Planner — pure function, no model calls."""

from __future__ import annotations

from diana.cognitive.models import Comprehension, Plan

# Stable capability order (MVP §5.6).
_NEED_TO_CAPABILITY: tuple[tuple[str, str], ...] = (
    ("needs_history", "knowledge.history"),
    ("needs_context", "knowledge.context"),
    ("needs_memory", "knowledge.memory"),
    ("needs_policy", "knowledge.policy"),
    ("needs_examples", "knowledge.examples"),
    ("needs_schedule", "knowledge.schedule"),
)

_HISTORY_CAP = "knowledge.history"


class Planner:
    """Map Comprehension.needs_* flags to ordered capability names."""

    def plan(self, comprehension: Comprehension) -> Plan:
        capabilities: list[str] = []
        for attr, cap in _NEED_TO_CAPABILITY:
            if getattr(comprehension, attr, False):
                capabilities.append(cap)
        if _HISTORY_CAP not in capabilities:
            capabilities.insert(0, _HISTORY_CAP)
        return Plan(capabilities=capabilities)
