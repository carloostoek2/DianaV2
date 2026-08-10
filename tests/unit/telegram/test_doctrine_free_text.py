"""Doctrine free-text flow — DoctrineSessionStore + handle_doctrine_free_text.

Covers the dr: (Responder consulta) path from SPEC-FASE2 6.2: the owner
presses the button, a session opens, and the next free-text DM is captured
as doctrine (generalization + rule) and resolved into a supervised delivery.
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


def _query_row(*, status: str = "open") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        turn_id=uuid4(),
        question="¿Cuándo me toca renovar?",
        draft="borrador del bot",
        chat_id=6502396879,
        business_connection_id="bc-vip",
    )


def _candidate() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4())


@pytest.fixture
def gray_zone() -> AsyncMock:
    gz = AsyncMock()
    gz.get_open_query_by_turn_id.return_value = _query_row()
    gz.resolve_with_doctrine.return_value = _candidate()
    gz.confirm_and_apply.return_value = None
    return gz


@pytest.fixture
def coordinator() -> AsyncMock:
    c = AsyncMock()
    c.transition.return_value = None
    return c


@pytest.fixture
def admin() -> AsyncMock:
    a = AsyncMock()
    a.create_supervised_delivery_from_gray_zone.return_value = True
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
    """Owner text becomes generalization+rule and the delivered draft."""
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
    gray_zone.get_open_query_by_turn_id.assert_awaited_once_with(turn_id)
    # The owner text is used as generalization AND rule.
    args = gray_zone.resolve_with_doctrine.await_args.args
    assert args[1] == text
    assert args[2] == text
    gray_zone.confirm_and_apply.assert_awaited_once()
    # Supervised delivery uses the owner text as the draft to approve/send.
    _, kwargs = admin.create_supervised_delivery_from_gray_zone.await_args
    assert kwargs["draft_override"] == text
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
    gray_zone.resolve_with_doctrine.assert_not_awaited()
    admin.create_supervised_delivery_from_gray_zone.assert_not_awaited()


@pytest.mark.asyncio
async def test_free_text_delivery_failure_escalates_turn(
    gray_zone: AsyncMock,
    coordinator: AsyncMock,
    admin: AsyncMock,
) -> None:
    admin.create_supervised_delivery_from_gray_zone.return_value = False
    status = await handle_doctrine_free_text(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=uuid4(),
        text="regla",
        admin=admin,
    )
    assert status == "escalated"
    coordinator.transition.assert_awaited_once_with(
        ANY, "escalated"
    )


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
