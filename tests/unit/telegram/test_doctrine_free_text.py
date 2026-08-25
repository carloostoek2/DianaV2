"""Doctrine free-text flow — DoctrineSessionStore + handle_doctrine_free_text.

Owner writes a RULE (not the VIP reply). Happy path calls
AdminService.resolve_doctrine_rule_and_enqueue; approval draft is the
regenerated text (≠ raw rule).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import UUID, uuid4

import pytest

from diana.telegram.handlers.doctrine import (
    DoctrineSessionStore,
    handle_doctrine_free_text,
)

OWNER = 999001


def _query_row(*, status: str = "open", vip_id: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        turn_id=uuid4(),
        question="¿Cuándo me toca renovar?",
        draft="borrador del bot",
        chat_id=6502396879,
        business_connection_id="bc-vip",
        vip_id=vip_id,
    )


@pytest.fixture
def gray_zone() -> AsyncMock:
    gz = AsyncMock()
    gz.get_open_query_by_turn_id.return_value = _query_row()
    return gz


@pytest.fixture
def coordinator() -> AsyncMock:
    c = AsyncMock()
    c.transition.return_value = None
    return c


@pytest.fixture
def admin() -> AsyncMock:
    a = AsyncMock()
    a.resolve_doctrine_rule_and_enqueue.return_value = "resolved"
    return a


# --- DoctrineSessionStore -------------------------------------------------


def test_session_start_live() -> None:
    store = DoctrineSessionStore()
    turn_id = uuid4()
    store.start(OWNER, turn_id)
    assert store.resolve(OWNER) == ("live", turn_id)
    # pop consumes and returns the turn id.
    assert store.pop(OWNER) == turn_id
    assert store.resolve(OWNER) == ("none", None)


def test_session_ttl_expires() -> None:
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    store = DoctrineSessionStore(
        ttl=timedelta(minutes=15),
        clock=lambda: now,
    )
    turn_id = uuid4()
    store.start(OWNER, turn_id)
    now = now + timedelta(minutes=16)
    assert store.resolve(OWNER) == ("expired", turn_id)
    # Entry was popped on expiry.
    assert store.resolve(OWNER) == ("none", None)


def test_session_cancel() -> None:
    store = DoctrineSessionStore()
    turn_id = uuid4()
    store.start(OWNER, turn_id)
    store.cancel(OWNER)
    assert store.resolve(OWNER) == ("none", None)


def test_session_cancel_turn() -> None:
    store = DoctrineSessionStore()
    turn_id = uuid4()
    store.start(OWNER, turn_id)
    assert store.cancel_turn(turn_id) == 1
    assert store.resolve(OWNER) == ("none", None)


# --- handle_doctrine_free_text -------------------------------------------


@pytest.mark.asyncio
async def test_free_text_resolves_and_delivers(
    gray_zone: AsyncMock,
    coordinator: AsyncMock,
    admin: AsyncMock,
) -> None:
    """Owner text is a RULE; orchestration goes through Admin resolve API."""
    text = "Siempre ofrecer 10% de descuento si piden 3 o más unidades"
    turn_id = uuid4()

    status = await handle_doctrine_free_text(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
        text=text,
        admin=admin,
    )

    assert status == "resolved"
    admin.resolve_doctrine_rule_and_enqueue.assert_awaited_once()
    kwargs = admin.resolve_doctrine_rule_and_enqueue.await_args.kwargs
    assert kwargs.get("rule_text") == text or (
        admin.resolve_doctrine_rule_and_enqueue.await_args.args
        and text in admin.resolve_doctrine_rule_and_enqueue.await_args.args
    )
    # Happy path must NOT write staging / confirm_and_apply from the handler.
    gray_zone.resolve_with_doctrine.assert_not_awaited()
    gray_zone.confirm_and_apply.assert_not_awaited()
    # Approval draft is owned by Admin regen — never the raw rule as draft_override here.
    admin.create_supervised_delivery_from_gray_zone.assert_not_awaited()
    coordinator.transition.assert_not_awaited()


@pytest.mark.asyncio
async def test_free_text_no_open_query_returns_not_found(
    gray_zone: AsyncMock,
    coordinator: AsyncMock,
    admin: AsyncMock,
) -> None:
    gray_zone.get_open_query_by_turn_id.return_value = None
    status = await handle_doctrine_free_text(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=uuid4(),
        text="regla",
        admin=admin,
    )
    assert status == "not_found"
    admin.resolve_doctrine_rule_and_enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_free_text_delivery_failure_escalates_turn(
    gray_zone: AsyncMock,
    coordinator: AsyncMock,
    admin: AsyncMock,
) -> None:
    admin.resolve_doctrine_rule_and_enqueue.return_value = "escalated"
    status = await handle_doctrine_free_text(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=uuid4(),
        text="regla",
        admin=admin,
    )
    assert status == "escalated"
    admin.resolve_doctrine_rule_and_enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_free_text_lookup_error_returns_error(
    gray_zone: AsyncMock,
    coordinator: AsyncMock,
    admin: AsyncMock,
) -> None:
    gray_zone.get_open_query_by_turn_id.side_effect = RuntimeError("db down")
    status = await handle_doctrine_free_text(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=uuid4(),
        text="regla",
        admin=admin,
    )
    assert status == "error"


# --- GAP-11: scope question before resolution ------------------------------


from diana.telegram.handlers.admin import handle_admin_text  # noqa: E402
from diana.telegram.handlers.doctrine import (  # noqa: E402
    DoctrinePending,
    handle_doctrine_scope_choice,
)


def test_session_attach_text_and_pop_pending() -> None:
    store = DoctrineSessionStore()
    turn_id = uuid4()
    store.start(OWNER, turn_id, mode="free_text")
    assert store.attach_text(OWNER, "regla nueva") is True
    pending = store.pop_pending(OWNER)
    assert pending is not None
    assert pending.turn_id == turn_id
    assert pending.mode == "free_text"
    assert pending.text == "regla nueva"
    # attach on a missing session never creates one
    assert store.attach_text(OWNER, "x") is False


@pytest.mark.asyncio
async def test_admin_text_vip_query_prompts_scope() -> None:
    """VIP doctrine text is kept and the scope question is asked (no resolve)."""
    gz = AsyncMock()
    gz.get_open_query_by_turn_id.return_value = _query_row(vip_id=uuid4())
    sessions = DoctrineSessionStore()
    turn_id = uuid4()
    sessions.start(OWNER, turn_id, mode="free_text")

    status = await handle_admin_text(
        text="regla nueva",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=AsyncMock(),
        admin=AsyncMock(),
        correct_sessions=object(),  # type: ignore[arg-type]  # doctrine branch returns first
        doctrine_sessions=sessions,
        gray_zone=gz,
        coordinator=AsyncMock(),
    )
    assert status == "doctrine_scope_prompted"
    gz.resolve_with_doctrine.assert_not_awaited()
    # The text is stored and the pending turn is still live for the ds: callback.
    assert sessions.peek_turn_id(OWNER) == turn_id
    pending = sessions.pop_pending(OWNER)
    assert pending is not None and pending.text == "regla nueva"


@pytest.mark.asyncio
async def test_admin_text_atencion_resolves_global_directly() -> None:
    """Atencion queries (no VIP) have nothing to scope — resolve global now."""
    gz = AsyncMock()
    gz.get_open_query_by_turn_id.return_value = _query_row(vip_id=None)
    sessions = DoctrineSessionStore()
    turn_id = uuid4()
    sessions.start(OWNER, turn_id, mode="free_text")
    admin = AsyncMock()
    admin.resolve_doctrine_rule_and_enqueue.return_value = "resolved"

    status = await handle_admin_text(
        text="regla de atencion",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=AsyncMock(),
        admin=admin,
        correct_sessions=object(),  # type: ignore[arg-type]
        doctrine_sessions=sessions,
        gray_zone=gz,
        coordinator=AsyncMock(),
    )
    assert status == "resolved"
    admin.resolve_doctrine_rule_and_enqueue.assert_awaited_once()
    call_kwargs = admin.resolve_doctrine_rule_and_enqueue.await_args.kwargs
    assert call_kwargs.get("rule_text") == "regla de atencion"
    assert call_kwargs.get("vip_id") is None
    gz.resolve_with_doctrine.assert_not_awaited()
    assert sessions.resolve(OWNER) == ("none", None)


@pytest.mark.asyncio
async def test_scope_choice_free_text_scopes_to_vip() -> None:
    vip_id = uuid4()
    gz = AsyncMock()
    gz.get_open_query_by_turn_id.return_value = _query_row(vip_id=vip_id)
    turn_id = uuid4()
    admin = AsyncMock()
    admin.resolve_doctrine_rule_and_enqueue.return_value = "resolved"

    status = await handle_doctrine_scope_choice(
        gray_zone=gz,
        coordinator=AsyncMock(),
        turn_id=turn_id,
        scope="vip",
        pending=DoctrinePending(
            turn_id=turn_id, mode="free_text", text="regla para este VIP"
        ),
        admin=admin,
    )
    assert status == "resolved"
    admin.resolve_doctrine_rule_and_enqueue.assert_awaited_once()
    call_kwargs = admin.resolve_doctrine_rule_and_enqueue.await_args.kwargs
    assert call_kwargs.get("rule_text") == "regla para este VIP"
    assert call_kwargs.get("vip_id") == vip_id
    assert call_kwargs.get("scope") == "vip"
    gz.resolve_with_doctrine.assert_not_awaited()


@pytest.mark.asyncio
async def test_scope_choice_rejects_draft_mode() -> None:
    """mode=draft (Usar borrador) is removed from the doctrine happy path."""
    vip_id = uuid4()
    gz = AsyncMock()
    gz.get_open_query_by_turn_id.return_value = _query_row(vip_id=vip_id)
    turn_id = uuid4()
    admin = AsyncMock()

    status = await handle_doctrine_scope_choice(
        gray_zone=gz,
        coordinator=AsyncMock(),
        turn_id=turn_id,
        scope="all",
        pending=DoctrinePending(turn_id=turn_id, mode="draft"),
        admin=admin,
    )
    assert status in {"error", "not_found", "rejected"}
    admin.resolve_doctrine_rule_and_enqueue.assert_not_awaited()
    gz.resolve_with_doctrine.assert_not_awaited()


@pytest.mark.asyncio
async def test_free_text_terminal_turn_returns_stale() -> None:
    """Free-text on a superseded turn -> 'stale' + residual hold discarded."""
    gz = AsyncMock()
    query = _query_row()
    gz.get_open_query_by_turn_id.return_value = query
    gz.discard_and_close = AsyncMock()

    coordinator = AsyncMock()
    coordinator.get_turn.return_value = SimpleNamespace(status="superseded")

    admin = AsyncMock()
    admin.resolve_doctrine_rule_and_enqueue.return_value = "resolved"

    status = await handle_doctrine_free_text(
        gray_zone=gz,
        coordinator=coordinator,
        turn_id=query.turn_id,
        text="regla",
        admin=admin,
        scope="all",
    )
    assert status == "stale"
    admin.resolve_doctrine_rule_and_enqueue.assert_not_awaited()
    gz.discard_and_close.assert_awaited_once()
