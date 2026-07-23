"""Deterministic capability Planner — pure function, no model calls.

Answers a single question (Anexo C.1): what knowledge to recover?
Maps ``Comprehension.needs_*`` → ordered ``Plan.capabilities`` (C.2–C.3).
Never requests a capability when its ``needs_*`` flag is false (minimum knowledge).
Empty ``[]`` is legal when all needs are false.

Note: ``knowledge.profile`` is registered in the default registry as an F2 hook
but is not requested by Planner (no ``needs_profile`` on Comprehension in F1).
"""

from __future__ import annotations

from diana.cognitive.models import Comprehension, Plan

# Stable capability order (Anexo C.2 / L5). Profile intentionally absent in F1.
_NEED_TO_CAPABILITY: tuple[tuple[str, str], ...] = (
    ("needs_history", "knowledge.history"),
    ("needs_context", "knowledge.context"),
    ("needs_memory", "knowledge.memory"),
    ("needs_policy", "knowledge.policy"),
    ("needs_examples", "knowledge.examples"),
    ("needs_schedule", "knowledge.schedule"),
)


class Planner:
    """Map Comprehension.needs_* flags to ordered capability names (Anexo C)."""

    def plan(self, comprehension: Comprehension) -> Plan:
        capabilities: list[str] = []
        for attr, cap in _NEED_TO_CAPABILITY:
            if getattr(comprehension, attr, False):
                capabilities.append(cap)
        return Plan(capabilities=capabilities)
