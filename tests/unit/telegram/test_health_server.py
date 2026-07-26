"""HealthServer — stdlib GET /health with DB + optional bot checks."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from diana.telegram.health import HealthServer, build_health_payload


def _session_factory(*, execute_side_effect: Exception | None = None):
    session = MagicMock()
    if execute_side_effect is not None:
        session.execute = AsyncMock(side_effect=execute_side_effect)
    else:
        session.execute = AsyncMock(return_value=MagicMock())

    @asynccontextmanager
    async def factory():
        yield session

    return factory, session


def _bot(*, fail: bool = False) -> MagicMock:
    bot = MagicMock()
    if fail:
        bot.get_me = AsyncMock(side_effect=RuntimeError("bot down"))
    else:
        me = MagicMock()
        me.username = "diana_bot"
        bot.get_me = AsyncMock(return_value=me)
    return bot


@pytest.mark.asyncio
async def test_health_ok_when_db_and_bot_ok() -> None:
    factory, _ = _session_factory()
    server = HealthServer(
        host="127.0.0.1",
        port=0,
        session_factory=factory,
        bot=_bot(),
    )
    status_code, body = await server.health_response()
    assert status_code == 200
    assert body["status"] == "ok"
    assert body["checks"]["db"]["ok"] is True
    assert body["checks"]["bot"]["ok"] is True
    assert body["checks"]["bot"]["username"] == "diana_bot"


@pytest.mark.asyncio
async def test_health_fail_when_db_down() -> None:
    factory, _ = _session_factory(execute_side_effect=RuntimeError("db down"))
    server = HealthServer(
        host="127.0.0.1",
        port=0,
        session_factory=factory,
        bot=_bot(),
    )
    status_code, body = await server.health_response()
    assert status_code == 503
    assert body["status"] == "fail"
    assert body["checks"]["db"]["ok"] is False


@pytest.mark.asyncio
async def test_health_degraded_when_bot_fails() -> None:
    factory, _ = _session_factory()
    server = HealthServer(
        host="127.0.0.1",
        port=0,
        session_factory=factory,
        bot=_bot(fail=True),
        bot_check_timeout_s=0.1,
    )
    status_code, body = await server.health_response()
    assert status_code == 200
    assert body["status"] == "degraded"
    assert body["checks"]["db"]["ok"] is True
    assert body["checks"]["bot"]["ok"] is False


@pytest.mark.asyncio
async def test_health_json_has_no_secrets() -> None:
    factory, _ = _session_factory()
    server = HealthServer(
        host="127.0.0.1",
        port=0,
        session_factory=factory,
        bot=_bot(),
    )
    _, body = await server.health_response()
    blob = str(body).lower()
    assert "token" not in blob
    assert "database_url" not in blob
    assert "password" not in blob
    assert "secret" not in blob
    forbidden_keys = {"token", "database_url", "password", "secret", "api_key"}
    assert forbidden_keys.isdisjoint(set(body.keys()))
    assert "token" not in body.get("checks", {})


def test_build_health_payload_status_matrix() -> None:
    ok = build_health_payload(
        db_ok=True,
        db_latency_ms=1,
        bot_ok=True,
        bot_username="x",
    )
    assert ok["status"] == "ok"
    degraded = build_health_payload(
        db_ok=True,
        db_latency_ms=1,
        bot_ok=False,
        bot_username=None,
    )
    assert degraded["status"] == "degraded"
    fail = build_health_payload(
        db_ok=False,
        db_latency_ms=0,
        bot_ok=True,
        bot_username="x",
    )
    assert fail["status"] == "fail"
