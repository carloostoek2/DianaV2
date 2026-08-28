"""Doctrine callback handlers — write rule + escalate (no Usar borrador / dx:)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
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
    SEVERITY_LABELS,
    doctrine_keyboard,
    encode_doctrine_callback,
    encode_doctrine_escalate_callback,
    encode_doctrine_proposal_callback,
    encode_doctrine_resolve_callback,
    encode_severity,
    parse_severity,
    severity_keyboard,
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
    proposed_rule: str | None = None
    proposed_reply: str | None = None
    proposal_source: str | None = None


class FakeAdmin:
    """Fake AdminService recording doctrine resolve + supervised-delivery calls."""

    def __init__(self) -> None:
        self.create_supervised_calls: list[tuple[UUID, object, str | None]] = []
        self.resolve_rule_calls: list[dict] = []
        self._denials: set[UUID] = set()

    def deny_on(self, turn_id: UUID) -> None:
        """Simulate a fail-soft False (e.g. legacy query without bc)."""
        self._denials.add(turn_id)

    async def create_supervised_delivery_from_gray_zone(
        self,
        turn_id: UUID,
        query: object,
        *,
        draft_override: str | None = None,
    ) -> bool:
        self.create_supervised_calls.append((turn_id, query, draft_override))
        return turn_id not in self._denials

    async def resolve_doctrine_rule_and_enqueue(self, **kwargs):
        self.resolve_rule_calls.append(kwargs)
        return "resolved"


@dataclass
class FakeCandidate:
    """Simulates a StagingCandidate row returned by resolve_with_doctrine."""
    id: UUID = field(default_factory=uuid4)


class FakeGrayZone:
    """Fake GrayZoneService for callback handler tests."""

    def __init__(self) -> None:
        self.queries: dict[UUID, FakeQuery] = {}
        self.candidates: list[FakeCandidate] = []
        self.resolve_calls: list[tuple[UUID, str, str, UUID | None]] = []
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

    def add_query_with_proposal(
        self,
        turn_id: UUID,
        *,
        rule: str = "Ofrecer 10% si piden 3 o más",
        reply: str = "Sí, con 3 o más te hago 10%",
    ) -> FakeQuery:
        q = FakeQuery(
            turn_id=turn_id,
            proposed_rule=rule,
            proposed_reply=reply,
            proposal_source="gray_zone_proposal",
        )
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

    async def get_hold_query_by_turn_id(self, turn_id: UUID) -> FakeQuery | None:
        return await self.get_open_query_by_turn_id(turn_id)

    async def get_awaiting_send_by_turn_id(self, turn_id: UUID) -> FakeQuery | None:
        q = self.queries.get(turn_id)
        if q is not None and getattr(q, "status", None) == "awaiting_send":
            return q
        return None

    async def resolve_with_doctrine(
        self,
        query_id: UUID,
        generalization: str,
        rule: str,
        *,
        vip_id: UUID | None = None,
    ) -> FakeCandidate:
        self.resolve_calls.append((query_id, generalization, rule, vip_id))
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
    """Fake TurnCoordinator that records transitions + exposes turn status."""

    def __init__(self) -> None:
        self.transitions: list[tuple[UUID, str]] = []
        self._failures: set[UUID] = set()
        self._status: dict[UUID, str] = {}
        self._missing: set[UUID] = set()

    def fail_on(self, turn_id: UUID) -> None:
        self._failures.add(turn_id)

    def set_status(self, turn_id: UUID, status: str) -> None:
        self._status[turn_id] = status

    def set_missing(self, turn_id: UUID) -> None:
        self._missing.add(turn_id)

    async def get_turn(self, turn_id: UUID) -> SimpleNamespace | None:
        if turn_id in self._missing:
            return None
        # Non-terminal by default so existing escalate tests keep their flow.
        return SimpleNamespace(status=self._status.get(turn_id, "gray_zone"))

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
async def test_resolve_with_draft_is_rejected() -> None:
    """Usar borrador path is inert — always rejected."""
    status = await handle_doctrine_resolve_with_draft(
        gray_zone=FakeGrayZone(),
        coordinator=FakeCoordinator(),
        turn_id=uuid4(),
    )
    assert status == "rejected"


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


@pytest.mark.asyncio
async def test_escalate_terminal_turn_returns_stale() -> None:
    """de: on a superseded turn -> 'stale' + residual hold discarded (no-op fix)."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    coordinator.set_status(turn_id, "superseded")
    query = gray_zone.add_query(turn_id)

    status = await handle_doctrine_escalate(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
    )
    assert status == "stale"
    assert gray_zone.discard_calls == [query.id]
    assert coordinator.transitions == []


@pytest.mark.asyncio
async def test_escalate_terminal_no_query_returns_stale() -> None:
    """de: on a superseded turn whose query was already closed -> 'stale'."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    coordinator.set_status(turn_id, "superseded")

    status = await handle_doctrine_escalate(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
    )
    assert status == "stale"
    assert gray_zone.discard_calls == []
    assert coordinator.transitions == []


@pytest.mark.asyncio
async def test_escalate_missing_turn_returns_not_found() -> None:
    """de: on an unknown turn -> 'not_found' (no transition, no discard)."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    coordinator.set_missing(turn_id)
    gray_zone.add_query(turn_id)

    status = await handle_doctrine_escalate(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
    )
    assert status == "not_found"
    assert gray_zone.discard_calls == []
    assert coordinator.transitions == []


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


def _callback_with_message(data: str, *, user_id: int) -> CallbackQuery:
    cq = _callback(data, user_id=user_id)
    msg = AsyncMock()
    msg.answer = AsyncMock(return_value=True)
    object.__setattr__(cq, "message", msg)
    return cq


def _handler_for_prefix(router, prefix: str):
    # Registration order: dx (inert), dp (proposal), dr, ds, de
    by_prefix = {
        "dx:": router.callback_query.handlers[0].callback,
        "dp:": router.callback_query.handlers[1].callback,
        "dr:": router.callback_query.handlers[2].callback,
        "ds:": router.callback_query.handlers[3].callback,
        "de:": router.callback_query.handlers[4].callback,
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
        ("de:", encode_doctrine_escalate_callback(turn_id)),
        ("ds:", __import__('diana.telegram.keyboards', fromlist=['encode_doctrine_scope']).encode_doctrine_scope(turn_id, 'vip')),
    ]
    for prefix, data in cases:
        handler = _handler_for_prefix(router, prefix)
        query = _callback(data, user_id=OTHER)
        await handler(query)
        query.answer.assert_awaited()
        args, kwargs = query.answer.await_args
        assert kwargs.get("show_alert") is True
        text = args[0] if args else kwargs.get("text", "")
        assert "No autorizado" in text

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
    handler = _handler_for_prefix(router, "de:")
    query = _callback(encode_doctrine_escalate_callback(turn_id), user_id=OWNER)
    await handler(query)
    args, kwargs = query.answer.await_args
    assert "No autorizado" in (args[0] if args else kwargs.get("text", ""))
    assert gray_zone.discard_calls == []


@pytest.mark.asyncio
async def test_doctrine_router_owner_escalate_allowed() -> None:
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    gray_zone.add_query(turn_id, draft="draft-ok")
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=coordinator,
        owner_telegram_id=OWNER,
    )
    handler = _handler_for_prefix(router, "de:")
    query = _callback_with_message(
        encode_doctrine_escalate_callback(turn_id), user_id=OWNER
    )
    await handler(query)
    assert len(gray_zone.discard_calls) == 1
    assert coordinator.transitions == [(turn_id, "escalated")]


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


# --- GAP-11: doctrine scope choice (ds:) ----------------------------------


from diana.telegram.handlers.doctrine import (  # noqa: E402
    DoctrineSessionStore,
)
from diana.telegram.keyboards import (  # noqa: E402
    doctrine_scope_keyboard,
    encode_doctrine_scope,
    parse_doctrine_scope,
)


def test_parse_doctrine_scope_valid() -> None:
    tid = uuid4()
    assert parse_doctrine_scope(f"ds:{tid}:vip") == (tid, "vip")
    assert parse_doctrine_scope(f"ds:{tid}:all") == (tid, "all")
    assert parse_doctrine_scope(f"ds:{tid}:cancel") == (tid, "cancel")


def test_parse_doctrine_scope_invalid() -> None:
    tid = uuid4()
    assert parse_doctrine_scope("") is None
    assert parse_doctrine_scope(f"ds:{tid}") is None
    assert parse_doctrine_scope(f"ds:{tid}:otro") is None
    assert parse_doctrine_scope("ds:not-a-uuid:vip") is None


def test_doctrine_scope_keyboard_under_64_bytes() -> None:
    tid = uuid4()
    kb = doctrine_scope_keyboard(tid)
    for row in kb.inline_keyboard:
        for btn in row:
            assert len(btn.callback_data.encode("utf-8")) <= 64


@pytest.mark.asyncio
async def test_dr_prompts_rule_for_owner() -> None:
    """dr: opens free-text session with rule-only prompt (no Usar borrador)."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    turn_id = uuid4()
    q = gray_zone.add_query(turn_id, draft="draft-vip")
    q.vip_id = uuid4()
    sessions = DoctrineSessionStore()
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=coordinator,
        owner_telegram_id=OWNER,
        doctrine_sessions=sessions,
    )
    handler = _handler_for_prefix(router, "dr:")
    query = _callback_with_message(
        encode_doctrine_callback(turn_id), user_id=OWNER
    )
    query.message.edit_reply_markup = AsyncMock(return_value=True)
    await handler(query)
    query.message.answer.assert_awaited()
    body = query.message.answer.await_args.args[0]
    assert "REGLA" in body or "regla" in body.lower()
    assert "texto que recibirá el VIP" not in body.lower() or "No escribas el texto" in body
    assert sessions.peek_turn_id(OWNER) == turn_id


@pytest.mark.asyncio
async def test_ds_scope_vip_resolves_with_vip_scope() -> None:
    """ds:<turn>:vip resolves a pending free-text RULE scoped to the VIP."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    admin = FakeAdmin()
    turn_id = uuid4()
    vip_id = uuid4()
    q = gray_zone.add_query(turn_id, draft="draft")
    q.vip_id = vip_id
    sessions = DoctrineSessionStore()
    sessions.start(OWNER, turn_id, mode="free_text", text="regla para este VIP")
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=coordinator,
        owner_telegram_id=OWNER,
        doctrine_sessions=sessions,
        admin=admin,
    )
    handler = _handler_for_prefix(router, "ds:")
    query = _callback_with_message(encode_doctrine_scope(turn_id, "vip"), user_id=OWNER)
    query.message.edit_text = AsyncMock(return_value=True)
    await handler(query)
    assert len(admin.resolve_rule_calls) == 1
    call = admin.resolve_rule_calls[0]
    assert call["rule_text"] == "regla para este VIP"
    assert call["vip_id"] == vip_id
    assert call["scope"] == "vip"
    assert sessions.resolve(OWNER) == ("none", None)


@pytest.mark.asyncio
async def test_ds_scope_all_resolves_global() -> None:
    """ds:<turn>:all resolves with vip_id None (global rule)."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    admin = FakeAdmin()
    turn_id = uuid4()
    q = gray_zone.add_query(turn_id, draft="draft")
    q.vip_id = uuid4()
    sessions = DoctrineSessionStore()
    sessions.start(OWNER, turn_id, mode="free_text", text="regla global")
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=coordinator,
        owner_telegram_id=OWNER,
        doctrine_sessions=sessions,
        admin=admin,
    )
    handler = _handler_for_prefix(router, "ds:")
    query = _callback_with_message(encode_doctrine_scope(turn_id, "all"), user_id=OWNER)
    query.message.edit_text = AsyncMock(return_value=True)
    await handler(query)
    call = admin.resolve_rule_calls[0]
    assert call["vip_id"] is None
    assert call["scope"] == "all"


@pytest.mark.asyncio
async def test_ds_cancel_pops_pending() -> None:
    gray_zone = FakeGrayZone()
    turn_id = uuid4()
    sessions = DoctrineSessionStore()
    sessions.start(OWNER, turn_id, mode="free_text", text="x")
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=FakeCoordinator(),
        owner_telegram_id=OWNER,
        doctrine_sessions=sessions,
    )
    handler = _handler_for_prefix(router, "ds:")
    query = _callback(encode_doctrine_scope(turn_id, "cancel"), user_id=OWNER)
    await handler(query)
    assert "Cancelado" in query.answer.await_args.args[0]
    assert sessions.resolve(OWNER) == ("none", None)
    assert len(gray_zone.resolve_calls) == 0


@pytest.mark.asyncio
async def test_ds_without_pending_alerts_expired() -> None:
    gray_zone = FakeGrayZone()
    turn_id = uuid4()
    sessions = DoctrineSessionStore()
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=FakeCoordinator(),
        owner_telegram_id=OWNER,
        doctrine_sessions=sessions,
    )
    handler = _handler_for_prefix(router, "ds:")
    query = _callback(encode_doctrine_scope(turn_id, "vip"), user_id=OWNER)
    await handler(query)
    args, kwargs = query.answer.await_args
    assert kwargs.get("show_alert") is True
    assert "expiró" in (args[0] if args else "")


@pytest.mark.asyncio
async def test_ds_non_owner_forbidden() -> None:
    gray_zone = FakeGrayZone()
    turn_id = uuid4()
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=FakeCoordinator(),
        owner_telegram_id=OWNER,
    )
    handler = _handler_for_prefix(router, "ds:")
    query = _callback(encode_doctrine_scope(turn_id, "vip"), user_id=OTHER)
    await handler(query)
    args, kwargs = query.answer.await_args
    assert kwargs.get("show_alert") is True
    assert "No autorizado" in (args[0] if args else "")


# --- New contract: no Usar borrador / no dx: happy path --------------------


def test_doctrine_keyboard_rule_only_no_usar_borrador() -> None:
    markup = doctrine_keyboard(uuid4())
    labels = [btn.text or "" for row in markup.inline_keyboard for btn in row]
    callbacks = [btn.callback_data or "" for row in markup.inline_keyboard for btn in row]
    assert not any("Usar borrador" in label for label in labels)
    assert any("regla" in label.lower() for label in labels)
    assert any("Escalar" in label for label in labels)
    assert not any(cb.startswith("dx:") for cb in callbacks)
    assert any(cb.startswith("dr:") for cb in callbacks)
    assert any(cb.startswith("de:") for cb in callbacks)


@pytest.mark.asyncio
async def test_doctrine_router_dx_is_inert() -> None:
    """Legacy dx: answers unavailable; does not resolve-with-draft."""
    gray_zone = FakeGrayZone()
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=FakeCoordinator(),
        owner_telegram_id=OWNER,
    )
    assert len(router.callback_query.handlers) == 5
    turn_id = uuid4()
    gray_zone.add_query(turn_id)
    handler = _handler_for_prefix(router, "dx:")
    query = _callback(encode_doctrine_resolve_callback(turn_id), user_id=OWNER)
    await handler(query)
    args, kwargs = query.answer.await_args
    assert kwargs.get("show_alert") is True
    assert "Ya no disponible" in (args[0] if args else "")
    assert gray_zone.resolve_calls == []


# --- FEATURE_GRAY_ZONE_PROPOSAL_ENABLED: Usar regla propuesta (dp:) --------


def test_doctrine_keyboard_with_proposal_shows_use_proposal_button() -> None:
    """With a proposal, the keyboard adds '💡 Usar regla propuesta' (dp:)."""
    markup = doctrine_keyboard(uuid4(), has_proposal=True)
    labels = [btn.text or "" for row in markup.inline_keyboard for btn in row]
    callbacks = [btn.callback_data or "" for row in markup.inline_keyboard for btn in row]
    assert any("Usar regla propuesta" in label for label in labels)
    assert any("Escribir regla" in label for label in labels)
    assert any("Escalar" in label for label in labels)
    assert any(cb.startswith("dp:") for cb in callbacks)
    assert any(cb.startswith("dr:") for cb in callbacks)
    assert any(cb.startswith("de:") for cb in callbacks)
    assert not any(cb.startswith("dx:") for cb in callbacks)


def test_doctrine_keyboard_without_proposal_has_no_dp_button() -> None:
    """Flag OFF / no proposal ⇒ byte-identical keyboard (no dp:)."""
    markup = doctrine_keyboard(uuid4())
    callbacks = [btn.callback_data or "" for row in markup.inline_keyboard for btn in row]
    labels = [btn.text or "" for row in markup.inline_keyboard for btn in row]
    assert not any(cb.startswith("dp:") for cb in callbacks)
    assert not any("Usar regla propuesta" in label for label in labels)


@pytest.mark.asyncio
async def test_dp_use_proposal_starts_scope_session_with_proposed_rule() -> None:
    """dp: adopts the system RULE: starts the scope session with that rule."""
    gray_zone = FakeGrayZone()
    turn_id = uuid4()
    query = gray_zone.add_query_with_proposal(turn_id, rule="Ofrecer 10% si piden 3+")
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=FakeCoordinator(),
        owner_telegram_id=OWNER,
    )
    handler = _handler_for_prefix(router, "dp:")
    query_obj = _callback_with_message(
        encode_doctrine_proposal_callback(turn_id), user_id=OWNER
    )
    await handler(query_obj)

    # Scope prompt shown with the proposed rule (rule, not the VIP reply).
    edit_args = query_obj.message.edit_text.await_args.args[0]
    assert "Regla propuesta por el sistema" in edit_args
    assert "Ofrecer 10% si piden 3+" in edit_args
    assert query.proposed_rule == "Ofrecer 10% si piden 3+"


@pytest.mark.asyncio
async def test_dp_missing_proposal_alerts_rejected() -> None:
    """dp: on a query without a proposal ⇒ alert, no scope session."""
    gray_zone = FakeGrayZone()
    turn_id = uuid4()
    gray_zone.add_query(turn_id)  # no proposal
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=FakeCoordinator(),
        owner_telegram_id=OWNER,
    )
    handler = _handler_for_prefix(router, "dp:")
    query_obj = _callback(encode_doctrine_proposal_callback(turn_id), user_id=OWNER)
    await handler(query_obj)
    args, kwargs = query_obj.answer.await_args
    assert kwargs.get("show_alert") is True
    assert "no tiene propuesta" in (args[0] if args else "")


@pytest.mark.asyncio
async def test_dp_missing_query_alerts_not_found() -> None:
    """dp: with no open query ⇒ alert, no scope session."""
    gray_zone = FakeGrayZone()
    turn_id = uuid4()
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=FakeCoordinator(),
        owner_telegram_id=OWNER,
    )
    handler = _handler_for_prefix(router, "dp:")
    query_obj = _callback(encode_doctrine_proposal_callback(turn_id), user_id=OWNER)
    await handler(query_obj)
    args, kwargs = query_obj.answer.await_args
    assert kwargs.get("show_alert") is True
    assert "no encontrada" in (args[0] if args else "")


@pytest.mark.asyncio
async def test_dp_non_owner_forbidden() -> None:
    gray_zone = FakeGrayZone()
    turn_id = uuid4()
    gray_zone.add_query_with_proposal(turn_id)
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=FakeCoordinator(),
        owner_telegram_id=OWNER,
    )
    handler = _handler_for_prefix(router, "dp:")
    query_obj = _callback(encode_doctrine_proposal_callback(turn_id), user_id=OTHER)
    await handler(query_obj)
    args, kwargs = query_obj.answer.await_args
    assert kwargs.get("show_alert") is True
    assert "No autorizado" in (args[0] if args else "")


@pytest.mark.asyncio
async def test_dp_then_ds_scope_resolves_with_proposed_rule() -> None:
    """Full flow: 💡 Usar regla propuesta → scope → resolve with the RULE.

    The dp: button adopts the system-suggested RULE (not the reply); the
    scope choice resolves through the same rule→regen→approval path as a
    hand-written rule (AGENTS §4.5).
    """
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    admin = FakeAdmin()
    turn_id = uuid4()
    vip_id = uuid4()
    q = gray_zone.add_query_with_proposal(
        turn_id, rule="Ofrecer 10% si piden 3 o más", reply="Sí, te hago 10%"
    )
    q.vip_id = vip_id
    sessions = DoctrineSessionStore()
    router = build_doctrine_router(
        gray_zone=gray_zone,
        coordinator=coordinator,
        owner_telegram_id=OWNER,
        doctrine_sessions=sessions,
        admin=admin,
    )

    # Step 1: dp: (Usar regla propuesta) → scope prompt with the rule.
    dp_handler = _handler_for_prefix(router, "dp:")
    dp_query = _callback_with_message(
        encode_doctrine_proposal_callback(turn_id), user_id=OWNER
    )
    await dp_handler(dp_query)
    edit_args = dp_query.message.edit_text.await_args.args[0]
    assert "Ofrecer 10% si piden 3 o más" in edit_args
    assert sessions.peek_turn_id(OWNER) == turn_id

    # Step 2: ds: scope choice → resolve with the PROPOSED RULE (not the reply).
    ds_handler = _handler_for_prefix(router, "ds:")
    ds_query = _callback_with_message(encode_doctrine_scope(turn_id, "vip"), user_id=OWNER)
    ds_query.message.edit_text = AsyncMock(return_value=True)
    await ds_handler(ds_query)
    assert len(admin.resolve_rule_calls) == 1
    call = admin.resolve_rule_calls[0]
    assert call["rule_text"] == "Ofrecer 10% si piden 3 o más"  # RULE adopted
    assert call["rule_text"] != "Sí, te hago 10%"  # never the VIP reply
    assert call["vip_id"] == vip_id
    assert call["scope"] == "vip"


# --- SPEC-EA-07: severity picker encode/parse + keyboard ----------------------


class TestSeverityKeyboard:
    def test_encode_parse_round_trip(self) -> None:
        turn_id = uuid4()
        for severity in ("minor", "moderate", "major"):
            data = encode_severity(turn_id, severity)
            assert data.startswith("sv:")
            parsed = parse_severity(data)
            assert parsed is not None
            assert parsed[0] == turn_id
            assert parsed[1] == severity

    def test_encode_stays_within_64_bytes(self) -> None:
        data = encode_severity(uuid4(), "major")
        assert len(data.encode("utf-8")) <= 64

    def test_parse_malformed_returns_none(self) -> None:
        assert parse_severity("") is None
        assert parse_severity("sv:") is None
        assert parse_severity("sv:not-a-uuid:moderate") is None
        assert parse_severity("sv:uuid:critical") is None
        assert parse_severity("other:uuid") is None

    def test_keyboard_has_three_buttons_with_labels(self) -> None:
        kb = severity_keyboard(uuid4())
        buttons = kb.inline_keyboard[0]
        assert len(buttons) == 3
        labels = [b.text for b in buttons]
        assert labels == [
            SEVERITY_LABELS["minor"],
            SEVERITY_LABELS["moderate"],
            SEVERITY_LABELS["major"],
        ]
        # Neutral Mexican Spanish labels.
        assert "Tono" in labels[0]
        assert "Contenido" in labels[1]
        assert "Doctrina/Seguridad" in labels[2]
