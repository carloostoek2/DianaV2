"""Memory approval callbacks + owner /memoria list (mp:/md:).

Dedicated router included AFTER the staging router and BEFORE the
catch-all callback router so prefixes ``mp:`` / ``md:`` are not
swallowed (A1). Writes go through MemoryApprovalService only — the
telegram layer is pure I/O. Structural mirror of ``staging.py``:
same router shape, same UX tokens, same keyboard cleanup — but the
memory domain (approve/discard of pending_owner facts), never the
staging business logic.

Logs are metadata-only (fix S1): fact texts NEVER reach the logger.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from diana.application.memory_approval_service import MemoryApprovalService
from diana.telegram.keyboards import (
    memory_pending_keyboard,
    parse_memory_approval_callback,
)

logger = logging.getLogger("diana.telegram")

_SNIPPET_MAX = 80

MEMORY_UNAVAILABLE_UX = "Memoria no disponible"
MEMORY_EMPTY_UX = "No hay hechos pendientes de aprobación"

_MEMORY_TOKEN_UX: dict[str, tuple[str, bool]] = {
    "approved": ("Aprobado ✅", False),
    "discarded": ("Descartado 🗑", False),
    "forbidden": ("Not authorized", True),
    "unavailable": (MEMORY_UNAVAILABLE_UX, True),
    "invalid": ("Invalid callback", True),
    "stale": ("Already handled or not found", True),
}


def _truncate(text: str, max_len: int = _SNIPPET_MAX) -> str:
    text = text or ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def format_pending_fact_body(row: Any) -> str:
    """Owner-facing body for one pending memory fact."""
    vip_name = row.get("vip_name")
    if not vip_name:
        raw = row.get("vip_id") or "?"
        vip_name = str(raw)[:8]
    category = row.get("category") or "?"
    content = row.get("content") or {}
    texto = str(content.get("texto") or content.get("fact") or "")
    return f"VIP {vip_name} · [{category}]\n{_truncate(texto)}"


async def load_pending_memory_list(
    *,
    memory: MemoryApprovalService | None,
    actor_id: int | None = None,
    limit: int = 10,
) -> tuple[str, list[Any]]:
    """Load pending memory facts. Returns (token, rows).

    Tokens: unavailable | empty | listed. ``actor_id`` is forwarded to the
    service's owner gate — the /memoria handler already verified the caller
    is the owner (``_is_private_owner``), so it passes the real actor id.
    """
    if memory is None:
        return "unavailable", []
    rows = await memory.list_pending(actor_id, limit=limit)
    if not rows:
        return "empty", []
    return "listed", list(rows)


async def dispatch_memory_approval_callback(
    *,
    memory: MemoryApprovalService | None,
    callback_data: str,
    actor_id: int | None,
    owner_telegram_id: int,
) -> str:
    """Pure memory approval callback dispatch. Returns status token (no I/O)."""
    if actor_id is None or actor_id != owner_telegram_id:
        return "forbidden"
    if memory is None:
        return "unavailable"
    parsed = parse_memory_approval_callback(callback_data or "")
    if parsed is None:
        return "invalid"
    action, fact_id = parsed
    try:
        if action == "approve":
            token = await memory.approve(actor_id, fact_id)
            logger.info(
                "memory_approval_approved",
                extra={"fact_id": str(fact_id), "actor_id": actor_id},
            )
            return token
        if action == "discard":
            token = await memory.discard(actor_id, fact_id)
            logger.info(
                "memory_approval_discarded",
                extra={"fact_id": str(fact_id), "actor_id": actor_id},
            )
            return token
    except ValueError:
        logger.info(
            "memory_approval_stale",
            extra={"fact_id": str(fact_id), "actor_id": actor_id, "action": action},
        )
        return "stale"
    return "invalid"


def build_memory_approval_router(
    *,
    memory: MemoryApprovalService | None,
    owner_telegram_id: int,
) -> Router:
    """Build router for /memoria + mp:/md: callbacks. Include before catch-all."""
    router = Router(name="memory_approval")

    def _is_private_owner(message: Message) -> bool:
        if message.from_user is None or message.from_user.id != owner_telegram_id:
            return False
        chat = message.chat
        return chat is not None and chat.type == "private"

    @router.message(Command("memoria"))
    async def on_memory_list(message: Message, **_: Any) -> None:
        if not _is_private_owner(message):
            return
        actor_id = message.from_user.id if message.from_user else None
        token, rows = await load_pending_memory_list(
            memory=memory, actor_id=actor_id
        )
        if token == "unavailable":
            await message.answer(MEMORY_UNAVAILABLE_UX)
            return
        if token == "empty":
            await message.answer(MEMORY_EMPTY_UX)
            return
        await message.answer(f"Hechos por aprobar ({len(rows)}):")
        for row in rows:
            await message.answer(
                format_pending_fact_body(row),
                reply_markup=memory_pending_keyboard(UUID(str(row["id"]))),
            )

    @router.callback_query(
        lambda c: c.data is not None
        and (c.data.startswith("mp:") or c.data.startswith("md:"))
    )
    async def on_memory_action(callback: CallbackQuery, **_: Any) -> None:
        actor_id = callback.from_user.id if callback.from_user else None
        token = await dispatch_memory_approval_callback(
            memory=memory,
            callback_data=callback.data or "",
            actor_id=actor_id,
            owner_telegram_id=owner_telegram_id,
        )
        text, alert = _MEMORY_TOKEN_UX.get(token, ("Processed", False))
        await callback.answer(text, show_alert=alert)
        if token in {"approved", "discarded"} and callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                logger.debug(
                    "memory_approval_clear_keyboard_failed",
                    extra={"actor_id": actor_id},
                    exc_info=True,
                )

    return router


__all__ = [
    "MEMORY_EMPTY_UX",
    "MEMORY_UNAVAILABLE_UX",
    "build_memory_approval_router",
    "dispatch_memory_approval_callback",
    "format_pending_fact_body",
    "load_pending_memory_list",
]
