"""Process-edge health probe — stdlib asyncio HTTP GET /health.

Binds with the Telegram process lifecycle (main start/stop). No aiohttp/FastAPI.
Does not expose tokens, DB URLs, or other secrets.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import text

logger = logging.getLogger("diana.telegram")

StatusCode = int
HealthBody = dict[str, Any]


def build_health_payload(
    *,
    db_ok: bool,
    db_latency_ms: int,
    bot_ok: bool | None,
    bot_username: str | None,
) -> HealthBody:
    """Assemble public health JSON (no secrets)."""
    if not db_ok:
        status = "fail"
    elif bot_ok is False:
        status = "degraded"
    else:
        status = "ok"

    checks: dict[str, Any] = {
        "db": {"ok": db_ok, "latency_ms": db_latency_ms},
    }
    if bot_ok is not None:
        checks["bot"] = {"ok": bot_ok, "username": bot_username}
    return {"status": status, "checks": checks}


class HealthServer:
    """Minimal asyncio TCP server answering GET /health."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        session_factory: Callable[[], Any],
        bot: Any | None = None,
        bot_check_timeout_s: float = 2.0,
        bot_cache_s: float = 30.0,
    ) -> None:
        self._host = host
        self._port = port
        self._session_factory = session_factory
        self._bot = bot
        self._bot_check_timeout_s = bot_check_timeout_s
        self._bot_cache_s = bot_cache_s
        self._server: asyncio.AbstractServer | None = None
        self._bot_cache: tuple[float, bool, str | None] | None = None

    async def check_db(self) -> tuple[bool, int]:
        started = time.monotonic()
        try:
            async with self._session_factory() as session:
                await session.execute(text("SELECT 1"))
            latency_ms = int((time.monotonic() - started) * 1000)
            return True, latency_ms
        except Exception:
            latency_ms = int((time.monotonic() - started) * 1000)
            logger.exception("health_check_db_error")
            return False, latency_ms

    async def check_bot(self) -> tuple[bool | None, str | None]:
        if self._bot is None:
            return None, None
        now = time.monotonic()
        if self._bot_cache is not None:
            cached_at, ok, username = self._bot_cache
            if now - cached_at <= self._bot_cache_s:
                return ok, username
        try:
            me = await asyncio.wait_for(
                self._bot.get_me(),
                timeout=self._bot_check_timeout_s,
            )
            username = getattr(me, "username", None)
            self._bot_cache = (now, True, username)
            return True, username
        except Exception:
            self._bot_cache = (now, False, None)
            return False, None

    async def health_response(self) -> tuple[StatusCode, HealthBody]:
        db_ok, db_latency_ms = await self.check_db()
        bot_ok, bot_username = await self.check_bot()
        body = build_health_payload(
            db_ok=db_ok,
            db_latency_ms=db_latency_ms,
            bot_ok=bot_ok,
            bot_username=bot_username,
        )
        code = 200 if db_ok else 503
        return code, body

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await asyncio.wait_for(reader.read(2048), timeout=5.0)
            request_line = raw.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
            parts = request_line.split()
            method = parts[0] if parts else ""
            path = parts[1] if len(parts) > 1 else ""
            if method == "GET" and path.split("?", 1)[0] == "/health":
                code, body = await self.health_response()
                payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
                reason = "OK" if code == 200 else "Service Unavailable"
            else:
                code = 404
                reason = "Not Found"
                payload = b'{"status":"not_found"}'
            header = (
                f"HTTP/1.1 {code} {reason}\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).encode("latin-1")
            writer.write(header + payload)
            await writer.drain()
        except Exception:
            logger.exception("health_request_error")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle,
            host=self._host,
            port=self._port,
        )
        sockets = self._server.sockets or []
        bound = None
        if sockets:
            bound = sockets[0].getsockname()
        logger.info(
            "health_server_started",
            extra={"host": self._host, "port": self._port, "bound": bound},
        )

    async def stop(self) -> None:
        server = self._server
        self._server = None
        if server is None:
            return
        server.close()
        await server.wait_closed()
        logger.info("health_server_stopped")


__all__ = ["HealthServer", "build_health_payload"]
