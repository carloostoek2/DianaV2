"""Doctrine callback handlers — respond, resolve-with-draft, escalate."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from diana.application.memory import (
    InMemoryPendingApprovalStore,
    InMemoryTurnStore,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.telegram.handlers.doctrine import (
    handle_doctrine_escalate,
    handle_doctrine_respond,
    handle_doctrine_resolve_with_draft,
)


@dataclass
class FakeQuery:
    """Simulates a GrayZoneQuery ORM row for testing."""
    id: UUID = field(default_factory=uuid4)
    turn_id: UUID = field(default_factory=uuid4)
    vip_id: UUID | None = None
    status: str = "open"
    question: str = "test question"
    draft: str = "test draft"
    frozen_until: object = None


@dataclass
class FakeCandidate:
    """Simulates a StagingCandidate row returned by resolve_with_doctrine."""
    id: UUID = field(default_factory=uuid4)


class FakeGrayZone:
    """Fake GrayZoneService for callback handler tests."""

    def __init__(self) -> None:
        self.queries: dict[UUID, FakeQuery] = {}
        self.candidates: list[FakeCandidate] = []
        self.resolve_calls: list[tuple[UUID, str, str]] = []
        self.confirm_calls: list[tuple[UUID, UUID]] = []
        self.discard_calls: list[UUID] = []
        self.lookup_errors: set[UUID] = set()
        self.resolve_errors: set[UUID] = set()
        self.discard_errors: set[UUID] = set()

    def add_query(self, turn_id: UUID, *, draft: str = "test draft") -> FakeQuery:
        q = FakeQuery(turn_id=turn_id, draft=draft)
        self.queries[turn_id] = q
        return q

    def error_on_lookup(self, turn_id: UUID) -> None:
        self.lookup_errors.add(turn_id)

    def error_on_resolve(self, turn_id: UUID) -> None:
        self.resolve_errors.add(turn_id)

    def error_on_discard(self, turn_id: UUID) -> None:
        self.discard_errors.add(turn_id)

    async def get_open_query_by_turn_id(self, turn_id: UUID) -> FakeQuery | None:
        if turn_id in self.lookup_errors:
            msg = "simulated lookup error"
            raise RuntimeError(msg)
        return self.queries.get(turn_id)

    async def resolve_with_doctrine(
        self, query_id: UUID, generalization: str, rule: str,
    ) -> FakeCandidate:
        self.resolve_calls.append((query_id, generalization, rule))
        candidate = FakeCandidate()
        self.candidates.append(candidate)
        return candidate

    async def confirm_and_apply(self, query_id: UUID, candidate_id: UUID) -> object:
        self.confirm_calls.append((query_id, candidate_id))
        return object()

    async def discard_and_close(self, query_id: UUID) -> object:
        self.discard_calls.append(query_id)
        return object()


class FakeCoordinator:
    """Fake TurnCoordinator that records transitions."""

    def __init__(self) -> None:
        self.transitions: list[tuple[UUID, str]] = []

    async def transition(self, turn_id: UUID, status: str) -> None:
        self.transitions.append((turn_id, status))


@pytest.mark.asyncio
async def test_respond_returns_prompted() -> None:
    turn_id = uuid4()

    status = await handle_doctrine_respond(turn_id=turn_id)
    assert status == "prompted"


@pytest.mark.asyncio
async def test_resolve_with_draft_resolves_query() -> None:
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    query = gray_zone.add_query(turn_id, draft="use-this-draft")

    status = await handle_doctrine_resolve_with_draft(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
    )
    assert status == "resolved"

    # Verify resolve_with_doctrine was called with the draft
    assert len(gray_zone.resolve_calls) == 1
    qid, gen, rule = gray_zone.resolve_calls[0]
    assert qid == query.id
    assert gen == "use-this-draft"
    assert rule == "use-this-draft"

    # Verify confirm_and_apply was called
    assert len(gray_zone.confirm_calls) == 1
    confirm_qid, confirm_cid = gray_zone.confirm_calls[0]
    assert confirm_qid == query.id
    assert confirm_cid == gray_zone.candidates[0].id


@pytest.mark.asyncio
async def test_resolve_with_draft_no_query() -> None:
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()  # No query added

    status = await handle_doctrine_resolve_with_draft(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
    )
    assert status == "not_found"
    assert len(gray_zone.resolve_calls) == 0
    assert len(gray_zone.confirm_calls) == 0


@pytest.mark.asyncio
async def test_resolve_with_draft_lookup_error() -> None:
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    gray_zone.error_on_lookup(turn_id)

    status = await handle_doctrine_resolve_with_draft(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
    )
    assert status == "error"


@pytest.mark.asyncio
async def test_escalate_discards_and_transitions() -> None:
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    query = gray_zone.add_query(turn_id)

    status = await handle_doctrine_escalate(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
    )
    assert status == "escalated"

    assert len(gray_zone.discard_calls) == 1
    assert gray_zone.discard_calls[0] == query.id

    assert len(coordinator.transitions) == 1
    assert coordinator.transitions[0] == (turn_id, "escalated")


@pytest.mark.asyncio
async def test_escalate_no_query() -> None:
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()

    status = await handle_doctrine_escalate(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
    )
    assert status == "not_found"
    assert len(gray_zone.discard_calls) == 0
    assert len(coordinator.transitions) == 0


@pytest.mark.asyncio
async def test_escalate_lookup_error() -> None:
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    gray_zone.error_on_lookup(turn_id)

    status = await handle_doctrine_escalate(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
    )
    assert status == "error"
    assert len(gray_zone.discard_calls) == 0
    assert len(coordinator.transitions) == 0
