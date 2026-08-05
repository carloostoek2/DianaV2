"""Doctrine callback handlers — respond, resolve-with-draft, escalate."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from aiogram.types import CallbackQuery, User

from diana.application.memory import (
    InMemoryPendingApprovalStore,
    InMemoryTurnStore,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.telegram.handlers.doctrine import (
    build_doctrine_router,
    handle_doctrine_escalate,
    handle_doctrine_respond,
    handle_doctrine_resolve_with_draft,
)
from diana.application.turn_coordinator import ChatLockTimeoutError
from diana.telegram.keyboards import (
    encode_doctrine_callback,
    encode_doctrine_escalate_callback,
    encode_doctrine_resolve_callback,
)

OWNER = 999001
OTHER = 111222


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
    business_connection_id: str | None = "bc-test"


class FakeAdmin:
    """Fake AdminService recording supervised-delivery synthesis calls."""

    def __init__(self) -> None:
        self.create_supervised_calls: list[tuple[UUID, object]] = []
        self._denials: set[UUID] = set()

    def deny_on(self, turn_id: UUID) -> None:
        """Simulate a fail-soft False (e.g. legacy query without bc)."""
        self._denials.add(turn_id)

    async def create_supervised_delivery_from_gray_zone(
        self, turn_id: UUID, query: object
    ) -> bool:
        self.create_supervised_calls.append((turn_id, query))
        return turn_id not in self._denials


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
        self.reopen_calls: list[UUID] = []
        self.lookup_errors: set[UUID] = set()
        self.resolve_errors: set[UUID] = set()
        self.discard_errors: set[UUID] = set()

    async def reopen_query(self, query_id: UUID) -> bool:
        self.reopen_calls.append(query_id)
        return True

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
        if query_id in self._resolve_errors_by_qid():
            raise RuntimeError(f"simulated resolve error for {query_id}")
        candidate = FakeCandidate()
        self.candidates.append(candidate)
        return candidate

    async def confirm_and_apply(self, query_id: UUID, candidate_id: UUID) -> object:
        self.confirm_calls.append((query_id, candidate_id))
        return object()

    async def discard_and_close(self, query_id: UUID) -> object:
        self.discard_calls.append(query_id)
        if query_id in self._discard_errors_by_qid():
            raise RuntimeError(f"simulated discard error for {query_id}")
        return object()

    def _resolve_errors_by_qid(self) -> set[UUID]:
        return {q.id for t_id, q in self.queries.items() if t_id in self.resolve_errors}

    def _discard_errors_by_qid(self) -> set[UUID]:
        return {q.id for t_id, q in self.queries.items() if t_id in self.discard_errors}


class FakeCoordinator:
    """Fake TurnCoordinator that records transitions."""

    def __init__(self) -> None:
        self.transitions: list[tuple[UUID, str]] = []
        self._failures: set[UUID] = set()

    def fail_on(self, turn_id: UUID) -> None:
        self._failures.add(turn_id)

    async def transition(self, turn_id: UUID, status: str) -> None:
        self.transitions.append((turn_id, status))
        if turn_id in self._failures:
            msg = f"simulated transition error for {turn_id}"
            raise RuntimeError(msg)


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


# --- Error-on-resolve / error-on-discard tests (TEST-2) ---


@pytest.mark.asyncio
async def test_resolve_with_draft_resolve_error() -> None:
    """resolve_with_doctrine raises -> handler returns 'error'."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    query = gray_zone.add_query(turn_id)
    gray_zone.error_on_resolve(turn_id)  # => resolves to query.id

    status = await handle_doctrine_resolve_with_draft(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
    )
    assert status == "error"
    # The call was made but raised -- confirm_and_apply should NOT be called.
    assert len(gray_zone.resolve_calls) == 1
    assert len(gray_zone.confirm_calls) == 0


@pytest.mark.asyncio
async def test_resolve_with_draft_confirm_error() -> None:
    """confirm_and_apply raises -> handler returns 'error'."""
    gray_zone = _FakeGrayZoneWithConfirmError()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    gray_zone.add_query(turn_id)

    status = await handle_doctrine_resolve_with_draft(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
    )
    assert status == "error"
    assert len(gray_zone.resolve_calls) == 1
    assert len(gray_zone.confirm_calls) == 1


class _FakeGrayZoneWithConfirmError(FakeGrayZone):
    """FakeGrayZone variant that raises on confirm_and_apply."""

    async def confirm_and_apply(self, query_id: UUID, candidate_id: UUID) -> object:
        self.confirm_calls.append((query_id, candidate_id))
        msg = f"simulated confirm error for {query_id}"
        raise RuntimeError(msg)


@pytest.mark.asyncio
async def test_resolve_with_draft_with_admin_creates_supervised_delivery() -> None:
    """dx: with admin injected → confirm_and_apply + exactly ONE supervised call."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    admin = FakeAdmin()
    turn_id = uuid4()
    query = gray_zone.add_query(turn_id, draft="use-this-draft")

    status = await handle_doctrine_resolve_with_draft(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
        admin=admin,
    )
    assert status == "resolved"

    assert len(gray_zone.confirm_calls) == 1
    assert len(admin.create_supervised_calls) == 1
    called_turn_id, called_query = admin.create_supervised_calls[0]
    assert called_turn_id == turn_id
    assert called_query is query


@pytest.mark.asyncio
async def test_resolve_with_draft_no_admin_skips_supervised() -> None:
    """dx: without admin → legacy behavior (confirm_and_apply, no supervised call)."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    admin = FakeAdmin()
    turn_id = uuid4()
    gray_zone.add_query(turn_id, draft="use-this-draft")

    status = await handle_doctrine_resolve_with_draft(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
        admin=None,
    )
    assert status == "resolved"
    assert len(gray_zone.confirm_calls) == 1
    assert len(admin.create_supervised_calls) == 0


@pytest.mark.asyncio
async def test_resolve_with_draft_confirm_before_supervised_delivery() -> None:
    """dx: ordering — confirm_and_apply (closes query + unfreezes) runs first.

    The VIP must be unfrozen before the owner approves; the supervised
    delivery synthesis must never run before the query is confirmed.
    """
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    admin = FakeAdmin()
    turn_id = uuid4()
    gray_zone.add_query(turn_id, draft="use-this-draft")

    events: list[str] = []

    async def _confirm_and_apply(query_id: UUID, candidate_id: UUID) -> object:
        events.append("confirm")
        return object()

    async def _create_supervised(
        turn_id_: UUID, query: object
    ) -> bool:
        events.append("supervised")
        return True

    gray_zone.confirm_and_apply = _confirm_and_apply  # type: ignore[method-assign]
    admin.create_supervised_delivery_from_gray_zone = _create_supervised  # type: ignore[method-assign]

    status = await handle_doctrine_resolve_with_draft(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
        admin=admin,
    )
    assert status == "resolved"
    assert events == ["confirm", "supervised"]


@pytest.mark.asyncio
async def test_resolve_with_draft_delivery_denied_falls_back_to_escalate() -> None:
    """dx: supervised delivery unavailable → turn escalated, never stuck.

    Legacy query without business_connection_id: the query is already closed
    by confirm_and_apply, so the handler escalates the turn and reports
    'escalated' instead of claiming a resolution that never scheduled a draft.
    """
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    admin = FakeAdmin()
    turn_id = uuid4()
    gray_zone.add_query(turn_id, draft="use-this-draft")
    admin.deny_on(turn_id)

    status = await handle_doctrine_resolve_with_draft(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
        admin=admin,
    )
    assert status == "escalated"
    assert len(gray_zone.confirm_calls) == 1
    assert len(admin.create_supervised_calls) == 1
    assert coordinator.transitions == [(turn_id, "escalated")]


@pytest.mark.asyncio
async def test_resolve_with_draft_delivery_error_falls_back_to_escalate() -> None:
    """dx: supervised delivery raises → turn escalated, still no zombie."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    admin = FakeAdmin()
    turn_id = uuid4()
    gray_zone.add_query(turn_id, draft="use-this-draft")

    async def _boom(turn_id_: UUID, query: object) -> bool:
        msg = "simulated delivery failure"
        raise RuntimeError(msg)

    admin.create_supervised_delivery_from_gray_zone = _boom  # type: ignore[method-assign]

    status = await handle_doctrine_resolve_with_draft(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
        admin=admin,
    )
    assert status == "escalated"
    assert coordinator.transitions == [(turn_id, "escalated")]


@pytest.mark.asyncio
async def test_resolve_with_draft_lock_timeout_is_error_not_escalated() -> None:
    """dx: ChatLockTimeoutError → 'error' (retryable), no escalate, no reopen.

    The lock holder (expiry job / owner callback) may be creating the
    approval for this very turn; escalating would terminalize it mid-flight.
    """
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    admin = FakeAdmin()
    turn_id = uuid4()
    gray_zone.add_query(turn_id, draft="use-this-draft")

    async def _lock_timeout(turn_id_: UUID, query: object) -> bool:
        msg = "simulated lock contention"
        raise ChatLockTimeoutError(msg)

    admin.create_supervised_delivery_from_gray_zone = _lock_timeout  # type: ignore[method-assign]

    status = await handle_doctrine_resolve_with_draft(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
        admin=admin,
    )
    assert status == "error"
    assert coordinator.transitions == []
    assert gray_zone.reopen_calls == []


@pytest.mark.asyncio
async def test_resolve_with_draft_double_failure_reopens_query() -> None:
    """dx: delivery denied AND fallback escalate fails → query reopened, 'error'.

    The turn stays gray_zone and the query is reopened so the expiry job
    retries later — never silently stranded with a closed query.
    """
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    admin = FakeAdmin()
    turn_id = uuid4()
    query = gray_zone.add_query(turn_id, draft="use-this-draft")
    admin.deny_on(turn_id)
    coordinator.fail_on(turn_id)

    status = await handle_doctrine_resolve_with_draft(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
        admin=admin,
    )
    assert status == "error"
    assert coordinator.transitions == [(turn_id, "escalated")]  # attempted
    assert gray_zone.reopen_calls == [query.id]


@pytest.mark.asyncio
async def test_escalate_never_creates_supervised_delivery() -> None:
    """de: stays byte-identical — no supervised approval is ever created."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    admin = FakeAdmin()
    turn_id = uuid4()
    gray_zone.add_query(turn_id, draft="must-not-deliver")

    status = await handle_doctrine_escalate(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
    )
    assert status == "escalated"
    assert coordinator.transitions == [(turn_id, "escalated")]
    assert len(gray_zone.discard_calls) == 1
    assert len(admin.create_supervised_calls) == 0


@pytest.mark.asyncio
async def test_escalate_discard_error() -> None:
    """discard_and_close raises -> handler returns 'error'."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    query = gray_zone.add_query(turn_id)
    gray_zone.error_on_discard(turn_id)  # => resolves to query.id

    status = await handle_doctrine_escalate(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
    )
    assert status == "error"
    assert len(gray_zone.discard_calls) == 1
    # Transition was called first (MED-6 order), so it should be recorded.
    assert len(coordinator.transitions) == 1


# --- Router owner auth (SEC-AUTH-01) ---


def _callback(data: str, *, user_id: int) -> CallbackQuery:
    cq = CallbackQuery(
        id="cq-doc",
        from_user=User(id=user_id, is_bot=False, first_name="U"),
        chat_instance="inst",
        data=data,
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))
    return cq


def _handler_for_prefix(router, prefix: str):
    # Registration order in build_doctrine_router: dr, dx, de
    by_prefix = {
        "dr:": router.callback_query.handlers[0].callback,
        "dx:": router.callback_query.handlers[1].callback,
        "de:": router.callback_query.handlers[2].callback,
    }
    return by_prefix[prefix]


@pytest.mark.asyncio
async def test_doctrine_router_non_owner_forbidden_all_actions() -> None:
    """Non-owner must not mutate gray-zone / escalate via doctrine callbacks."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    gray_zone.add_query(turn_id)
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=coordinator,
        owner_telegram_id=OWNER,
    )
    cases = [
        ("dr:", encode_doctrine_callback(turn_id)),
        ("dx:", encode_doctrine_resolve_callback(turn_id)),
        ("de:", encode_doctrine_escalate_callback(turn_id)),
    ]
    for prefix, data in cases:
        handler = _handler_for_prefix(router, prefix)
        query = _callback(data, user_id=OTHER)
        await handler(query)
        query.answer.assert_awaited()
        args, kwargs = query.answer.await_args
        assert kwargs.get("show_alert") is True
        text = args[0] if args else kwargs.get("text", "")
        assert "Not authorized" in text

    assert gray_zone.resolve_calls == []
    assert gray_zone.discard_calls == []
    assert coordinator.transitions == []


@pytest.mark.asyncio
async def test_doctrine_router_missing_owner_id_fail_closed() -> None:
    """Without owner_telegram_id, all doctrine callbacks are forbidden."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    gray_zone.add_query(turn_id)
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=coordinator,
        owner_telegram_id=None,
    )
    handler = _handler_for_prefix(router, "dx:")
    query = _callback(encode_doctrine_resolve_callback(turn_id), user_id=OWNER)
    await handler(query)
    args, kwargs = query.answer.await_args
    assert "Not authorized" in (args[0] if args else kwargs.get("text", ""))
    assert gray_zone.resolve_calls == []


@pytest.mark.asyncio
async def test_doctrine_router_owner_resolve_allowed() -> None:
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    gray_zone.add_query(turn_id, draft="draft-ok")
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=coordinator,
        owner_telegram_id=OWNER,
    )
    handler = _handler_for_prefix(router, "dx:")
    query = _callback(encode_doctrine_resolve_callback(turn_id), user_id=OWNER)
    await handler(query)
    assert len(gray_zone.resolve_calls) == 1
    args, kwargs = query.answer.await_args
    text = args[0] if args else kwargs.get("text", "")
    assert "Resolved" in text


# --- parse_doctrine_callback tests (TEST-1) ---


from diana.telegram.keyboards import parse_doctrine_callback  # noqa: E402


def test_parse_doctrine_callback_valid() -> None:
    tid = uuid4()
    assert parse_doctrine_callback(f"dr:{tid}") == tid
    assert parse_doctrine_callback(f"dx:{tid}") == tid
    assert parse_doctrine_callback(f"de:{tid}") == tid


def test_parse_doctrine_callback_with_prefix() -> None:
    tid = uuid4()
    assert parse_doctrine_callback(f"dr:{tid}", prefix="dr") == tid
    assert parse_doctrine_callback(f"dx:{tid}", prefix="dx") == tid
    assert parse_doctrine_callback(f"de:{tid}", prefix="de") == tid


def test_parse_doctrine_callback_prefix_mismatch() -> None:
    assert parse_doctrine_callback("dx:abc123", prefix="dr") is None


def test_parse_doctrine_callback_invalid() -> None:
    assert parse_doctrine_callback("") is None
    assert parse_doctrine_callback("invalid") is None
    assert parse_doctrine_callback(":") is None
    assert parse_doctrine_callback("dr:not-a-uuid") is None
