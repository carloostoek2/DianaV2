"""Single source of the sandbox exclusion predicates (migration 037).

``turns.is_sandbox`` is frozen by ``TurnCoordinator`` from
``SandboxService.is_active(chat_id)`` when the turn is minted. Every reader
that aggregates metrics or feeds learning/calibration must exclude sandbox
turns through these helpers (never an ad-hoc ``is_sandbox`` predicate), so a
future change of the rule lands in one place. Operational readers (turn
lifecycle, recovery, admin trace viewer) intentionally do NOT use them.

Limitation (no flag, documented in AGENTS.md / docs/OPS_SINGLE_INSTANCE.md):
the sandbox session is process-local; after a restart with the sandbox on,
subsequent turns are stored as ``is_sandbox = false`` until the owner
re-activates it.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ColumnElement, exists, false, true

from diana.infrastructure.db.models import PipelineTrace, Turn


def real_vip_turn() -> ColumnElement[bool]:
    """Predicate on ``Turn``: the turn is real traffic (not sandbox)."""
    return Turn.is_sandbox.is_(false())


def trace_is_sandbox() -> ColumnElement[bool]:
    """Correlated predicate on ``PipelineTrace``: its turn is a sandbox turn.

    ``EXISTS`` (not a JOIN) so a trace whose turn row is missing counts as
    real — same default as the column's ``server_default false``.
    """
    return (
        exists()
        .where(Turn.id == PipelineTrace.turn_id, Turn.is_sandbox.is_(true()))
        .correlate(PipelineTrace)
    )


def trace_not_sandbox() -> ColumnElement[bool]:
    """Correlated predicate on ``PipelineTrace``: its turn is NOT sandbox."""
    return ~trace_is_sandbox()


def trace_same_sandbox_mode_as(turn_id: UUID) -> ColumnElement[bool]:
    """Trace belongs to the same mode (sandbox / real) as ``turn_id``.

    Chat cognition (repetition guard, emotional baseline): a real turn never
    sees sandbox history and a sandbox turn only sees its own sandbox history
    (mirrors ``SandboxService.get_profile_history`` isolation).
    """
    current = (
        exists()
        .where(Turn.id == turn_id, Turn.is_sandbox.is_(true()))
        .correlate(None)
    )
    return trace_is_sandbox() == current


__all__ = [
    "real_vip_turn",
    "trace_is_sandbox",
    "trace_not_sandbox",
    "trace_same_sandbox_mode_as",
]
