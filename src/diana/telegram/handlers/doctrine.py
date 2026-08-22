"""Doctrine callback handlers: respond, resolve-with-draft, escalate.

Flow (SPEC-FASE2 6.2):
- dr: (Responder consulta) opens a free-text doctrine session; the owner's
  next DM text is captured as doctrine (generalization + rule) and resolved.
- dx: (Usar borrador) resolves with the persisted draft as doctrine.
- de: (Escalar) discards the query and escalates the turn.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Literal
from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from diana.application.admin_service import AdminService
from diana.application.ports import GrayZoneServicePort
from diana.application.turn_coordinator import (
    ChatLockTimeoutError,
    TurnCoordinator,
)
from diana.telegram.keyboards import (
    doctrine_scope_keyboard,
    parse_doctrine_callback,
    parse_doctrine_scope,
)

logger = logging.getLogger("diana.telegram")

_RESULT_MESSAGES: dict[str, tuple[str, bool]] = {
    "resolved": ("Resuelto y aplicado", False),
    "escalated": ("Escalado", False),
    "not_found": ("Consulta no encontrada — ya fue resuelta", True),
    "error": ("Error al procesar la solicitud", True),
}

DOCTRINE_SCOPE_PROMPT = (
    "¿Esta regla aplica solo a este VIP o a todos?\n\n"
    "Es la lección que Diana guardará para casos futuros."
)

DEFAULT_DOCTRINE_TTL = timedelta(minutes=15)
DoctrineClockFn = Callable[[], datetime]
DoctrineResolveState = Literal["live", "expired", "none"]
DoctrineMode = Literal["free_text", "draft"]
DoctrineScope = Literal["vip", "all"]


@dataclass
class DoctrinePending:
    """Pending doctrine response awaiting a scope choice (GAP-11).

    ``mode`` tells the scope callback how to resolve:
    - "free_text": the owner typed the doctrine (``text`` is the rule/draft).
    - "draft": the owner chose "Usar borrador" (the query draft is the rule).
    """

    turn_id: UUID
    mode: DoctrineMode
    text: str | None = None


class DoctrineSessionStore:
    """Process-local FSM: owner_id → pending doctrine response for turn_id.

    Same pattern as ``CorrectSessionStore`` (callbacks.py) but for gray zone
    doctrine responses: after the owner provides doctrine (free text or
    "usar borrador"), the scope choice is captured before resolution.

    In-memory only (single-instance). Restart clears all sessions; multi-replica
    would need a shared store (out of scope — see docs/OPS_SINGLE_INSTANCE.md).
    Supports TTL (default 15 min) and cancel-by-turn for supersede cleanup.
    """

    def __init__(
        self,
        *,
        ttl: timedelta = DEFAULT_DOCTRINE_TTL,
        clock: DoctrineClockFn | None = None,
    ) -> None:
        self._awaiting: dict[int, tuple[DoctrinePending, datetime]] = {}
        self._ttl = ttl
        self._clock: DoctrineClockFn = clock or (lambda: datetime.now(UTC))

    def start(
        self,
        owner_id: int,
        turn_id: UUID,
        *,
        mode: DoctrineMode = "free_text",
        text: str | None = None,
    ) -> None:
        self._awaiting[owner_id] = (
            DoctrinePending(turn_id=turn_id, mode=mode, text=text),
            self._clock(),
        )
        logger.info(
            "doctrine_session_started",
            extra={
                "owner_id": owner_id,
                "turn_id": str(turn_id),
                "mode": mode,
                "ttl_s": int(self._ttl.total_seconds()),
            },
        )

    def attach_text(self, owner_id: int, text: str) -> bool:
        """Attach the owner's free-text doctrine to a live session.

        Returns False when there is no live session (never silently creates
        one). The entry is kept so the scope callback can consume it.
        """
        item = self._awaiting.get(owner_id)
        if item is None:
            return False
        pending, started = item
        if self._clock() - started > self._ttl:
            self._awaiting.pop(owner_id, None)
            return False
        self._awaiting[owner_id] = (
            DoctrinePending(
                turn_id=pending.turn_id, mode=pending.mode, text=text
            ),
            started,
        )
        return True

    def pop_pending(self, owner_id: int) -> DoctrinePending | None:
        """Pop the pending doctrine response (TTL-checked)."""
        item = self._awaiting.pop(owner_id, None)
        if item is None:
            return None
        pending, started = item
        if self._clock() - started > self._ttl:
            return None
        return pending

    def peek_turn_id(self, owner_id: int) -> UUID | None:
        """Turn id of a live pending response (no consume), for scope prompt."""
        item = self._awaiting.get(owner_id)
        if item is None:
            return None
        pending, started = item
        if self._clock() - started > self._ttl:
            return None
        return pending.turn_id

    def pop(self, owner_id: int) -> UUID | None:
        """Legacy alias: pop the pending turn id (TTL-checked)."""
        pending = self.pop_pending(owner_id)
        return pending.turn_id if pending is not None else None

    def resolve(
        self, owner_id: int
    ) -> tuple[DoctrineResolveState, UUID | None]:
        """Gate helper for free-text doctrine.

        - live: within TTL; UUID returned; entry KEPT (does not consume)
        - expired: TTL exceeded; entry POPPED; log doctrine_session_expired once
        - none: missing; no log
        """
        item = self._awaiting.get(owner_id)
        if item is None:
            return ("none", None)
        pending, started = item
        if self._clock() - started > self._ttl:
            self._awaiting.pop(owner_id, None)
            logger.info(
                "doctrine_session_expired",
                extra={
                    "owner_id": owner_id,
                    "turn_id": str(pending.turn_id),
                },
            )
            return ("expired", pending.turn_id)
        return ("live", pending.turn_id)

    def cancel(self, owner_id: int) -> None:
        self._awaiting.pop(owner_id, None)

    def cancel_turn(self, turn_id: UUID) -> int:
        """Clear any doctrine sessions awaiting this turn (supersede / terminal)."""
        removed = 0
        for oid, (pending, _) in list(self._awaiting.items()):
            if pending.turn_id == turn_id:
                self._awaiting.pop(oid, None)
                removed += 1
        return removed


async def _resolve_query_with_doctrine(
    *,
    gray_zone: GrayZoneServicePort,
    coordinator: TurnCoordinator,
    turn_id: UUID,
    generalization: str,
    rule: str,
    draft: str,
    admin: AdminService | None = None,
    scope: DoctrineScope = "all",
) -> str:
    """Shared resolution core: doctrine text → candidate → confirm → deliver.

    Used by both the draft path (generalization=rule=draft=query.draft) and
    the free-text path (all three = the owner's text). ``scope`` decides
    whether the new rule applies to this VIP only (``vip``) or to everyone
    (``all``); the candidate payload carries the chosen ``vip_id`` so the
    eventual promotion honors it (GAP-11). Returns status token:
    'resolved', 'escalated', 'not_found', or 'error'.
    """
    try:
        query = await gray_zone.get_open_query_by_turn_id(turn_id)
    except Exception:
        logger.exception(
            "doctrine_resolve_lookup_error", extra={"turn_id": str(turn_id)}
        )
        return "error"

    if query is None:
        logger.info("doctrine_resolve_no_query", extra={"turn_id": str(turn_id)})
        return "not_found"

    try:
        vip_id = getattr(query, "vip_id", None)
        scoped_vip_id = vip_id if scope == "vip" else None
        candidate = await gray_zone.resolve_with_doctrine(
            query.id,
            generalization,
            rule,
            vip_id=scoped_vip_id,
        )
        # If confirm_and_apply fails below, resolve_with_doctrine already
        # created an orphan staging candidate. The query stays open so it
        # can be retried or expired later — safe but should be monitored.
        await gray_zone.confirm_and_apply(query.id, candidate.id)
        if admin is not None:
            try:
                created = await admin.create_supervised_delivery_from_gray_zone(
                    turn_id, query, draft_override=draft
                )
            except ChatLockTimeoutError:
                # Lock contention with the expiry job or an owner callback:
                # the other holder may be creating the approval for this very
                # turn. Escalating would terminalize it mid-flight — report a
                # retryable error. The query is already closed by
                # confirm_and_apply, so reopen it: otherwise the turn would be
                # stranded in gray_zone with a query nothing ever revisits.
                try:
                    await gray_zone.reopen_query(query.id)
                except Exception:
                    logger.exception(
                        "doctrine_resolve_lock_timeout_reopen_error",
                        extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                    )
                logger.warning(
                    "doctrine_resolve_delivery_lock_timeout",
                    extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                )
                return "error"
            except Exception:
                logger.exception(
                    "doctrine_resolve_delivery_error",
                    extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                )
                created = False
            if not created:
                # Supervised delivery unavailable (e.g. legacy query without
                # business_connection_id). The query is already closed, so
                # escalate the turn — never leave it stuck in gray_zone.
                try:
                    await coordinator.transition(turn_id, "escalated")
                except Exception:
                    logger.exception(
                        "doctrine_resolve_fallback_escalate_error",
                        extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                    )
                    # Double failure: reopen the query so a later run (expiry)
                    # retries instead of stranding the turn in gray_zone.
                    try:
                        await gray_zone.reopen_query(query.id)
                    except Exception:
                        logger.exception(
                            "doctrine_resolve_reopen_error",
                            extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                        )
                    return "error"
                logger.warning(
                    "doctrine_resolve_delivery_fallback_escalated",
                    extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                )
                return "escalated"
        logger.info(
            "doctrine_resolved_with_text",
            extra={
                "turn_id": str(turn_id),
                "query_id": str(query.id),
                "candidate_id": str(candidate.id),
                "supervised": admin is not None,
                "source": "draft" if generalization == draft else "free_text",
            },
        )
        return "resolved"
    except Exception:
        logger.exception(
            "doctrine_resolve_error",
            extra={"turn_id": str(turn_id), "query_id": str(query.id)},
        )
        return "error"


async def handle_doctrine_respond(
    *,
    turn_id: UUID,
) -> str:
    """Handle respond callback: acknowledge and return 'prompted' status."""
    logger.info(
        "doctrine_respond",
        extra={
            "turn_id": str(turn_id),
        },
    )
    return "prompted"


async def handle_doctrine_free_text(
    *,
    gray_zone: GrayZoneServicePort,
    coordinator: TurnCoordinator,
    turn_id: UUID,
    text: str,
    admin: AdminService | None = None,
    scope: DoctrineScope = "all",
) -> str:
    """Resolve a gray zone query with the owner's free-text doctrine.

    The owner's text plays both roles (SPEC-FASE2 6.2): it is the answer
    delivered to the VIP (via supervised approval) and the generalization
    stored as doctrine. ``text`` must be non-empty (callers gate this).
    ``scope`` sets whether the new rule applies to this VIP or to everyone
    (GAP-11).

    Returns status token: 'resolved', 'escalated', 'not_found', or 'error'.
    """
    return await _resolve_query_with_doctrine(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
        generalization=text,
        rule=text,
        draft=text,
        admin=admin,
        scope=scope,
    )


async def handle_doctrine_resolve_with_draft(
    *,
    gray_zone: GrayZoneServicePort,
    coordinator: TurnCoordinator,
    turn_id: UUID,
    admin: AdminService | None = None,
    scope: DoctrineScope = "all",
) -> str:
    """Resolve using the existing query draft as doctrine, then confirm.

    After ``confirm_and_apply`` closes the query (and unfreezes the VIP),
    ``admin.create_supervised_delivery_from_gray_zone`` creates a supervised
    PendingApproval with the query draft and transitions the turn to
    ``PENDING_APPROVAL``. With ``admin=None`` the behavior is legacy:
    only ``confirm_and_apply`` (no approval creation, no transition). If the
    supervised delivery cannot be created, the turn is escalated as a
    fallback so it never stays stuck in ``gray_zone``.

    Returns status token: 'resolved', 'escalated', 'not_found', or 'error'.
    """
    try:
        query = await gray_zone.get_open_query_by_turn_id(turn_id)
    except Exception:
        logger.exception(
            "doctrine_resolve_lookup_error", extra={"turn_id": str(turn_id)}
        )
        return "error"

    if query is None:
        logger.info("doctrine_resolve_no_query", extra={"turn_id": str(turn_id)})
        return "not_found"

    return await _resolve_query_with_doctrine(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
        generalization=query.draft,
        rule=query.draft,
        draft=query.draft,
        admin=admin,
        scope=scope,
    )


async def handle_doctrine_escalate(
    *,
    gray_zone: GrayZoneServicePort,
    coordinator: TurnCoordinator,
    turn_id: UUID,
) -> str:
    """Discard query and escalate the turn.

    Order: coordinator.transition first (fails fast, reversible),
    then discard_and_close (non-reversible side effect).

    Returns status token: 'escalated', 'not_found', or 'error'.
    """
    try:
        query = await gray_zone.get_open_query_by_turn_id(turn_id)
    except Exception:
        logger.exception(
            "doctrine_escalate_lookup_error", extra={"turn_id": str(turn_id)}
        )
        return "error"

    if query is None:
        logger.info("doctrine_escalate_no_query", extra={"turn_id": str(turn_id)})
        return "not_found"

    try:
        # Transition first (fails fast, reversible) — then close the query.
        await coordinator.transition(turn_id, "escalated")
        await gray_zone.discard_and_close(query.id)
        logger.info(
            "doctrine_escalated",
            extra={
                "turn_id": str(turn_id),
                "query_id": str(query.id),
            },
        )
        return "escalated"
    except Exception:
        logger.exception(
            "doctrine_escalate_error",
            extra={"turn_id": str(turn_id), "query_id": str(query.id)},
        )
        return "error"


async def handle_doctrine_scope_choice(
    *,
    gray_zone: GrayZoneServicePort,
    coordinator: TurnCoordinator,
    turn_id: UUID,
    scope: DoctrineScope,
    admin: AdminService | None = None,
    pending: DoctrinePending | None = None,
) -> str:
    """Resolve a pending doctrine response with the chosen scope (GAP-11).

    ``pending`` carries the owner's free-text doctrine when it came from the
    "Responder consulta" flow (mode ``free_text``); for the "Usar borrador"
    flow (mode ``draft``) the query draft is used. Returns the usual status
    token.
    """
    if pending is not None and pending.mode == "free_text":
        text = (pending.text or "").strip()
        if not text:
            return "error"
        return await handle_doctrine_free_text(
            gray_zone=gray_zone,
            coordinator=coordinator,
            turn_id=turn_id,
            text=text,
            admin=admin,
            scope=scope,
        )
    return await handle_doctrine_resolve_with_draft(
        gray_zone=gray_zone,
        coordinator=coordinator,
        turn_id=turn_id,
        admin=admin,
        scope=scope,
    )


def build_doctrine_router(
    *,
    gray_zone: GrayZoneServicePort,
    coordinator: TurnCoordinator,
    owner_telegram_id: int | None = None,
    admin: AdminService | None = None,
    doctrine_sessions: DoctrineSessionStore | None = None,
) -> Router:
    """Build a Router with doctrine callback handlers.

    The router is included BEFORE the catch-all callback router so that
    doctrine-specific callbacks (dr:*, dx:*, de:*) are handled first.
    Owner auth mirrors metrics/trace: non-owner answers ``Not authorized``.
    """
    router = Router(name="doctrine")
    sessions = doctrine_sessions or DoctrineSessionStore()

    def _is_owner(callback: CallbackQuery) -> bool:
        if owner_telegram_id is None:
            return False
        actor = callback.from_user.id if callback.from_user else None
        return actor == owner_telegram_id

    @router.callback_query(lambda c: c.data and c.data.startswith("dr:"))
    async def on_doctrine_respond(callback: CallbackQuery, **_: Any) -> None:
        if not _is_owner(callback):
            await callback.answer("No autorizado", show_alert=True)
            return
        turn_id = parse_doctrine_callback(callback.data or "")
        if turn_id is None:
            await callback.answer("Dato de consulta inválido", show_alert=True)
            return

        status = await handle_doctrine_respond(turn_id=turn_id)
        await callback.answer("Abriendo respuesta de doctrina...")
        if status == "prompted":
            # Open a free-text session so the owner's next DM is captured.
            actor_id = callback.from_user.id if callback.from_user else None
            if actor_id is not None:
                sessions.start(actor_id, turn_id)
            if callback.message:
                await callback.message.answer(
                    f"Envía tu respuesta de doctrina para el turno {turn_id}.\n"
                    "Escribe el texto que quieres que el VIP reciba; quedará "
                    "también como regla para casos futuros."
                )

    @router.callback_query(lambda c: c.data and c.data.startswith("dx:"))
    async def on_doctrine_resolve_with_draft(
        callback: CallbackQuery, **_: Any
    ) -> None:
        if not _is_owner(callback):
            await callback.answer("No autorizado", show_alert=True)
            return
        turn_id = parse_doctrine_callback(callback.data or "")
        if turn_id is None:
            await callback.answer("Dato de consulta inválido", show_alert=True)
            return
        actor_id = callback.from_user.id if callback.from_user else None

        # GAP-11: ask the scope before resolving. Atencion queries have no VIP
        # (vip_id None) — nothing to choose, resolve global immediately.
        try:
            query = await gray_zone.get_open_query_by_turn_id(turn_id)
        except Exception:
            logger.exception(
                "doctrine_scope_lookup_error", extra={"turn_id": str(turn_id)}
            )
            await callback.answer(
                _RESULT_MESSAGES["error"][0], show_alert=True
            )
            return
        if query is None:
            await callback.answer(
                _RESULT_MESSAGES["not_found"][0], show_alert=True
            )
            return
        if getattr(query, "vip_id", None) is None:
            status = await handle_doctrine_resolve_with_draft(
                gray_zone=gray_zone,
                coordinator=coordinator,
                turn_id=turn_id,
                admin=admin,
                scope="all",
            )
            text, alert = _RESULT_MESSAGES.get(status, ("Procesado", False))
            await callback.answer(text, show_alert=alert)
            return

        if actor_id is not None:
            sessions.start(actor_id, turn_id, mode="draft")
        if callback.message:
            try:
                await callback.message.answer(
                    DOCTRINE_SCOPE_PROMPT,
                    reply_markup=doctrine_scope_keyboard(turn_id),
                )
            except Exception:
                logger.exception(
                    "doctrine_scope_prompt_failed",
                    extra={"turn_id": str(turn_id)},
                )
        await callback.answer()

    @router.callback_query(lambda c: c.data and c.data.startswith("ds:"))
    async def on_doctrine_scope(callback: CallbackQuery, **_: Any) -> None:
        if not _is_owner(callback):
            await callback.answer("No autorizado", show_alert=True)
            return
        parsed = parse_doctrine_scope(callback.data or "")
        if parsed is None:
            await callback.answer("Dato de consulta inválido", show_alert=True)
            return
        turn_id, scope = parsed
        actor_id = callback.from_user.id if callback.from_user else None

        if scope == "cancel":
            if actor_id is not None:
                sessions.pop_pending(actor_id)
            await callback.answer("Cancelado")
            return

        pending = sessions.pop_pending(actor_id) if actor_id is not None else None
        if pending is None or pending.turn_id != turn_id:
            await callback.answer(
                "La respuesta de doctrina expiró — presiona Responder consulta "
                "de nuevo",
                show_alert=True,
            )
            return

        status = await handle_doctrine_scope_choice(
            gray_zone=gray_zone,
            coordinator=coordinator,
            turn_id=turn_id,
            scope=scope,  # type: ignore[arg-type]
            admin=admin,
            pending=pending,
        )
        text, alert = _RESULT_MESSAGES.get(status, ("Procesado", False))
        await callback.answer(text, show_alert=alert)

    @router.callback_query(lambda c: c.data and c.data.startswith("de:"))
    async def on_doctrine_escalate(callback: CallbackQuery, **_: Any) -> None:
        if not _is_owner(callback):
            await callback.answer("No autorizado", show_alert=True)
            return
        turn_id = parse_doctrine_callback(callback.data or "")
        if turn_id is None:
            await callback.answer("Dato de consulta inválido", show_alert=True)
            return

        status = await handle_doctrine_escalate(
            gray_zone=gray_zone,
            coordinator=coordinator,
            turn_id=turn_id,
        )
        text, alert = _RESULT_MESSAGES.get(status, ("Procesado", False))
        await callback.answer(text, show_alert=alert)

    return router


__all__ = [
    "DoctrinePending",
    "DoctrineScope",
    "DoctrineSessionStore",
    "build_doctrine_router",
    "handle_doctrine_escalate",
    "handle_doctrine_free_text",
    "handle_doctrine_respond",
    "handle_doctrine_resolve_with_draft",
    "handle_doctrine_scope_choice",
]
