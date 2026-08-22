"""Staging promote/discard callbacks + owner /staging list (sp:/sd:).

Dedicated router included BEFORE the catch-all callback router so prefixes
``sp:`` / ``sd:`` are not swallowed. Writes go through StagingService only.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from diana.application.staging_service import (
    AtencionPromoteBlocked,
    StagingService,
)
from diana.telegram.keyboards import (
    parse_staging_callback,
    staging_candidate_keyboard,
    staging_discard_confirm_keyboard,
)

logger = logging.getLogger("diana.telegram")

_SNIPPET_MAX = 80

STAGING_UNAVAILABLE_UX = "Cola de revisión no disponible"
STAGING_EMPTY_UX = "No hay nada pendiente de revisión"

_TOKEN_UX: dict[str, tuple[str, bool]] = {
    "promoted": ("Aplicado", False),
    "discarded": ("Descartado", False),
    "forbidden": ("No autorizado", True),
    "unavailable": (STAGING_UNAVAILABLE_UX, True),
    "invalid": ("Dato inválido", True),
    "stale": ("Ya fue revisado o no existe", True),
    "atencion_blocked": (
        "Las correcciones de Atención no pueden convertirse en ejemplos VIP",
        True,
    ),
}


def _truncate(text: str, max_len: int = _SNIPPET_MAX) -> str:
    text = text or ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def format_staging_candidate_body(candidate: Any) -> str:
    """Owner-facing body for one pending staging candidate.

    Policy candidates (gray-zone doctrine rules) render the rule, the draft
    and the chosen scope; example candidates keep the original/corrected
    pair. New text is neutral Mexican Spanish (AGENTS.md §0.6).
    """
    cid = str(getattr(candidate, "id", ""))
    short = cid[:8] if cid else "?"
    payload = getattr(candidate, "payload", None) or {}
    if getattr(candidate, "candidate_type", "example") == "policy":
        rule = _truncate(str(payload.get("generalization") or payload.get("rule") or ""))
        draft = _truncate(str(payload.get("draft") or ""))
        scope = (
            "🔒 Solo este VIP"
            if payload.get("scope") == "vip"
            else "🌍 A todos"
        )
        return (
            f"Regla {short}\n"
            f"Regla: {rule}\n"
            f"Borrador: {draft}\n"
            f"Alcance: {scope}"
        )
    original = _truncate(str(payload.get("original_draft", "")))
    corrected = _truncate(str(payload.get("corrected_text", "")))
    return (
        f"Candidate {short}\n"
        f"Original: {original}\n"
        f"Corrected: {corrected}"
    )


async def load_pending_staging_list(
    *,
    staging: StagingService | None,
    limit: int = 10,
) -> tuple[str, list[Any]]:
    """Load the pending review queue: example candidates + gray-zone rules.

    Returns (token, rows). Tokens: unavailable | empty | listed.
    """
    if staging is None:
        return "unavailable", []
    rows = await staging.list_pending_examples(limit=limit)
    rows = [*rows, *await staging.list_pending_policies(limit=limit)]
    if not rows:
        return "empty", []
    return "listed", list(rows)


async def dispatch_staging_callback(
    *,
    staging: StagingService | None,
    callback_data: str,
    actor_id: int | None,
    owner_telegram_id: int,
) -> str:
    """Pure staging callback dispatch. Returns status token (no Telegram I/O)."""
    if actor_id is None or actor_id != owner_telegram_id:
        return "forbidden"
    if staging is None:
        return "unavailable"
    parsed = parse_staging_callback(callback_data or "")
    if parsed is None:
        return "invalid"
    action, candidate_id = parsed
    try:
        if action == "promote":
            # Route by candidate type: gray-zone doctrine rules promote to a
            # live policy (with the scope chosen by the owner, GAP-11);
            # corrections promote to the example bank.
            candidate = await staging.get_candidate(candidate_id)
            if candidate is not None and getattr(
                candidate, "candidate_type", "example"
            ) == "policy":
                payload = getattr(candidate, "payload", None) or {}
                vip_raw = payload.get("vip_id")
                vip_id = UUID(vip_raw) if vip_raw else None
                trigger = str(
                    payload.get("question")
                    or payload.get("generalization")
                    or "regla de zona gris"
                )[:80]
                rule = str(
                    payload.get("generalization") or payload.get("rule") or ""
                ).strip()
                await staging.promote_to_policy(
                    candidate_id,
                    trigger=trigger,
                    rule=rule,
                    scope=str(payload.get("scope") or "all"),
                    vip_id=vip_id,
                )
                logger.info(
                    "staging_policy_promoted",
                    extra={
                        "candidate_id": str(candidate_id),
                        "actor_id": actor_id,
                        "scope": payload.get("scope"),
                    },
                )
                return "promoted"
            await staging.promote_to_example(candidate_id)
            logger.info(
                "staging_promoted",
                extra={
                    "candidate_id": str(candidate_id),
                    "actor_id": actor_id,
                },
            )
            return "promoted"
        if action == "discard":
            # A4: the first tap only arms the two-step confirm — nothing is
            # deleted until the owner confirms with sd:<id>:confirm.
            return "discard_confirm_prompt"
        if action == "discard_confirm":
            await staging.discard(candidate_id)
            logger.info(
                "staging_discarded",
                extra={
                    "candidate_id": str(candidate_id),
                    "actor_id": actor_id,
                },
            )
            return "discarded"
        if action == "discard_cancel":
            return "discard_cancelled"
    except AtencionPromoteBlocked:
        logger.info(
            "staging_atencion_promote_blocked",
            extra={
                "candidate_id": str(candidate_id),
                "actor_id": actor_id,
                "action": action,
            },
        )
        return "atencion_blocked"
    except ValueError:
        logger.info(
            "staging_stale",
            extra={
                "candidate_id": str(candidate_id),
                "actor_id": actor_id,
                "action": action,
            },
        )
        return "stale"
    return "invalid"


def build_staging_router(
    *,
    staging: StagingService | None,
    owner_telegram_id: int,
) -> Router:
    """Build router for /staging + sp:/sd: callbacks. Include before catch-all."""
    router = Router(name="staging")

    def _is_private_owner(message: Message) -> bool:
        if message.from_user is None or message.from_user.id != owner_telegram_id:
            return False
        chat = message.chat
        return chat is not None and chat.type == "private"

    @router.message(Command("staging"))
    async def on_staging_list(message: Message, **_: Any) -> None:
        if not _is_private_owner(message):
            return
        token, rows = await load_pending_staging_list(staging=staging)
        if token == "unavailable":
            await message.answer(STAGING_UNAVAILABLE_UX)
            return
        if token == "empty":
            await message.answer(STAGING_EMPTY_UX)
            return
        await message.answer(f"Cola de revisión ({len(rows)}):")
        for row in rows:
            await message.answer(
                format_staging_candidate_body(row),
                reply_markup=staging_candidate_keyboard(row.id),
            )

    @router.callback_query(
        lambda c: c.data is not None
        and (c.data.startswith("sp:") or c.data.startswith("sd:"))
    )
    async def on_staging_action(callback: CallbackQuery, **_: Any) -> None:
        actor_id = callback.from_user.id if callback.from_user else None
        token = await dispatch_staging_callback(
            staging=staging,
            callback_data=callback.data or "",
            actor_id=actor_id,
            owner_telegram_id=owner_telegram_id,
        )
        parsed = parse_staging_callback(callback.data or "")
        candidate_id = parsed[1] if parsed is not None else None

        if token == "discard_confirm_prompt":
            # A4: first discard tap swaps in the confirm keyboard; the body
            # text stays put, so "No, mantener" can simply swap it back.
            await callback.answer()
            if candidate_id is not None and callback.message is not None:
                try:
                    await callback.message.edit_reply_markup(
                        reply_markup=staging_discard_confirm_keyboard(candidate_id)
                    )
                except Exception:
                    logger.debug(
                        "staging_show_confirm_failed",
                        extra={"actor_id": actor_id},
                        exc_info=True,
                    )
            return
        if token == "discard_cancelled":
            await callback.answer()
            if candidate_id is not None and callback.message is not None:
                try:
                    await callback.message.edit_reply_markup(
                        reply_markup=staging_candidate_keyboard(candidate_id)
                    )
                except Exception:
                    logger.debug(
                        "staging_restore_keyboard_failed",
                        extra={"actor_id": actor_id},
                        exc_info=True,
                    )
            return

        text, alert = _TOKEN_UX.get(token, ("Processed", False))
        await callback.answer(text, show_alert=alert)
        if token in {"promoted", "discarded"} and callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                logger.debug(
                    "staging_clear_keyboard_failed",
                    extra={"actor_id": actor_id},
                    exc_info=True,
                )

    return router


__all__ = [
    "STAGING_EMPTY_UX",
    "STAGING_UNAVAILABLE_UX",
    "build_staging_router",
    "dispatch_staging_callback",
    "format_staging_candidate_body",
    "load_pending_staging_list",
]
