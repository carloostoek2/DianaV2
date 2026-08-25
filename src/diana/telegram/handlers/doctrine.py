"""Doctrine callback handlers: write rule + escalate (no Usar borrador).

Flow (AGENTS §4.5):
- dr: (Escribir regla) opens a free-text session; owner writes a RULE.
- ds: Solo este VIP / A todos scopes the rule, then AdminService regenerates.
- de: (Escalar) discards the query and escalates the turn.
- dx: removed from the happy path (legacy callbacks answered as expired).
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
from diana.application.turn_coordinator import TurnCoordinator
from diana.cognitive.models import is_turn_status_terminal
from diana.telegram.keyboards import (
    doctrine_scope_keyboard,
    parse_doctrine_callback,
    parse_doctrine_scope,
)

logger = logging.getLogger("diana.telegram")

_RESULT_MESSAGES: dict[str, tuple[str, bool]] = {
    "resolved": ("Regla guardada — borrador regenerado para tu aprobación", False),
    "escalated": ("Escalado", False),
    "not_found": ("Consulta no encontrada — ya fue resuelta", True),
    "error": ("Error al procesar la solicitud", True),
    "regen_failed": (
        "No se pudo regenerar el borrador; la regla se desactivó. Reintenta.",
        True,
    ),
    "rejected": ("Acción no disponible", True),
    "stale": ("Este turno ya fue superado; la consulta quedó cerrada", True),
}

DOCTRINE_SCOPE_PROMPT = (
    "¿Esta regla aplica solo a este VIP o a todos?\n\n"
    "Es la norma que Diana usará para regenerar el borrador de este turno."
)

DOCTRINE_RULE_PROMPT = (
    "Escribe la REGLA / norma de negocio para este caso.\n"
    "No escribas el texto que recibirá el VIP: Diana regenerará el borrador "
    "con tu regla y te lo mandará a aprobar.\n"
    "Usa /cancelar para abortar."
)

DEFAULT_DOCTRINE_TTL = timedelta(minutes=15)
DoctrineClockFn = Callable[[], datetime]
DoctrineResolveState = Literal["live", "expired", "none"]
DoctrineMode = Literal["free_text", "draft"]
DoctrineScope = Literal["vip", "all"]


@dataclass
class DoctrinePending:
    """Pending RULE awaiting a scope choice (GAP-11).

    Only ``free_text`` mode is used on the happy path (``text`` = rule).
    ``draft`` mode is rejected by ``handle_doctrine_scope_choice``.
    """

    turn_id: UUID
    mode: DoctrineMode
    text: str | None = None


class DoctrineSessionStore:
    """Process-local FSM: owner_id → pending RULE for turn_id.

    Same pattern as ``CorrectSessionStore`` (callbacks.py) but for gray zone
    rule responses: after the owner writes a RULE (free text), the scope
    choice (Solo este VIP / A todos) is captured before resolve+regen.

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
    actor_id: int | None = None,
) -> str:
    """Deprecated staging resolve path — not used by doctrine happy path."""
    del gray_zone, coordinator, turn_id, generalization, rule, draft, admin, scope, actor_id
    return "rejected"


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
    actor_id: int | None = None,
) -> str:
    """Resolve a gray zone query with the owner's RULE (live persist + regen).

    ``text`` is the business rule only — never used as the VIP draft.
    ``scope`` sets whether the new rule applies to this VIP or to everyone.

    Returns status token: 'resolved', 'escalated', 'not_found', 'stale',
    'regen_failed', or 'error'.
    """
    if admin is None:
        return "error"
    rule = (text or "").strip()
    if not rule:
        return "error"
    try:
        turn = await coordinator.get_turn(turn_id)
    except Exception:
        logger.exception(
            "doctrine_free_text_turn_lookup_error",
            extra={"turn_id": str(turn_id)},
        )
        return "error"
    if turn is None:
        return "not_found"
    if is_turn_status_terminal(turn.status):
        # Superseded/finished turn: never persist a live policy for it; close
        # any residual hold so the VIP is not left frozen behind a dead turn.
        try:
            query = await gray_zone.get_open_query_by_turn_id(turn_id)
        except Exception:
            logger.exception(
                "doctrine_resolve_lookup_error", extra={"turn_id": str(turn_id)}
            )
            return "error"
        if query is not None:
            try:
                await gray_zone.discard_and_close(query.id)
            except Exception:
                logger.exception(
                    "doctrine_free_text_stale_discard_error",
                    extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                )
        logger.info(
            "doctrine_free_text_stale",
            extra={"turn_id": str(turn_id), "status": turn.status},
        )
        return "stale"
    try:
        query = await gray_zone.get_open_query_by_turn_id(turn_id)
    except Exception:
        logger.exception(
            "doctrine_resolve_lookup_error", extra={"turn_id": str(turn_id)}
        )
        return "error"
    if query is None:
        return "not_found"
    query_vip = getattr(query, "vip_id", None)
    scoped_vip = query_vip if scope == "vip" else None
    return await admin.resolve_doctrine_rule_and_enqueue(
        turn_id=turn_id,
        rule_text=rule,
        scope=scope,
        vip_id=scoped_vip,
        gray_zone=gray_zone,
        actor_id=actor_id,
    )


async def handle_doctrine_resolve_with_draft(
    *,
    gray_zone: GrayZoneServicePort,
    coordinator: TurnCoordinator,
    turn_id: UUID,
    admin: AdminService | None = None,
    scope: DoctrineScope = "all",
    actor_id: int | None = None,
) -> str:
    """Deprecated: Usar borrador removed from doctrine happy path."""
    del gray_zone, coordinator, turn_id, admin, scope, actor_id
    return "rejected"


async def handle_doctrine_escalate(
    *,
    gray_zone: GrayZoneServicePort,
    coordinator: TurnCoordinator,
    turn_id: UUID,
    admin: AdminService | None = None,
    actor_id: int | None = None,
) -> str:
    """Discard query and escalate the turn.

    With ``admin`` injected, reuse ``handle_owner_escalate`` so Fila 4
    persists ``owner_outcome="escalated"``. Without admin, legacy
    ``coordinator.transition`` + discard. Order: mutate turn first
    (fails fast), then discard_and_close.

    Returns status token: 'escalated', 'not_found', 'stale', or 'error'.
    """
    try:
        turn = await coordinator.get_turn(turn_id)
    except Exception:
        logger.exception(
            "doctrine_escalate_turn_lookup_error", extra={"turn_id": str(turn_id)}
        )
        return "error"
    if turn is None:
        logger.info(
            "doctrine_escalate_missing_turn", extra={"turn_id": str(turn_id)}
        )
        return "not_found"

    try:
        if hasattr(gray_zone, "get_hold_query_by_turn_id"):
            query = await gray_zone.get_hold_query_by_turn_id(turn_id)
        else:
            query = await gray_zone.get_open_query_by_turn_id(turn_id)
    except Exception:
        logger.exception(
            "doctrine_escalate_lookup_error", extra={"turn_id": str(turn_id)}
        )
        return "error"

    if is_turn_status_terminal(turn.status):
        # Superseded/delivered/failed/escalated turn: discard any residual hold
        # (defense) and tell the owner the turn is gone instead of a silent no-op.
        if query is not None:
            try:
                await gray_zone.discard_and_close(query.id)
            except Exception:
                logger.exception(
                    "doctrine_escalate_stale_discard_error",
                    extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                )
        logger.info(
            "doctrine_escalate_stale",
            extra={"turn_id": str(turn_id), "status": turn.status},
        )
        return "stale"

    if query is None:
        logger.info("doctrine_escalate_no_query", extra={"turn_id": str(turn_id)})
        return "not_found"

    try:
        if admin is not None:
            applied = await admin.handle_owner_escalate(
                turn_id, actor_id=actor_id
            )
            if not applied:
                return "error"
            # handle_owner_escalate already releases awaiting_send holds.
            if getattr(query, "status", "open") == "open":
                try:
                    await gray_zone.discard_and_close(query.id)
                except ValueError:
                    pass
        else:
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
    actor_id: int | None = None,
) -> str:
    """Resolve a pending RULE with the chosen scope (GAP-11).

    Only ``free_text`` mode is supported. ``draft`` (Usar borrador) is rejected.
    """
    if pending is None or pending.mode != "free_text":
        return "rejected"
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
        actor_id=actor_id,
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

    Handlers: ``dr:`` (write rule), ``ds:`` (scope), ``de:`` (escalate).
    Legacy ``dx:`` is registered as inert (answers \"Ya no disponible\").
    """
    router = Router(name="doctrine")
    sessions = doctrine_sessions or DoctrineSessionStore()

    def _is_owner(callback: CallbackQuery) -> bool:
        if owner_telegram_id is None:
            return False
        actor = callback.from_user.id if callback.from_user else None
        return actor == owner_telegram_id

    @router.callback_query(lambda c: c.data and c.data.startswith("dx:"))
    async def on_doctrine_legacy_draft(callback: CallbackQuery, **_: Any) -> None:
        """Inert: Usar borrador removed from doctrine happy path."""
        if not _is_owner(callback):
            await callback.answer("No autorizado", show_alert=True)
            return
        await callback.answer(
            "Ya no disponible — usa Escribir regla",
            show_alert=True,
        )

    @router.callback_query(lambda c: c.data and c.data.startswith("dr:"))
    async def on_doctrine_respond(callback: CallbackQuery, **_: Any) -> None:
        # Answer immediately (<1s UX) before any further work.
        if not _is_owner(callback):
            await callback.answer("No autorizado", show_alert=True)
            return
        turn_id = parse_doctrine_callback(callback.data or "")
        if turn_id is None:
            await callback.answer("Dato de consulta inválido", show_alert=True)
            return

        await callback.answer("Escribe la regla…")
        status = await handle_doctrine_respond(turn_id=turn_id)
        if status == "prompted":
            actor_id = callback.from_user.id if callback.from_user else None
            if actor_id is not None:
                sessions.start(actor_id, turn_id)
            if callback.message:
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except Exception:
                    logger.exception(
                        "doctrine_respond_clear_keyboard_failed",
                        extra={"turn_id": str(turn_id)},
                    )
                await callback.message.answer(
                    f"{DOCTRINE_RULE_PROMPT}\n\nTurno: {turn_id}"
                )

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
                "La sesión de doctrina expiró — toca Escribir regla de nuevo",
                show_alert=True,
            )
            return

        # Immediate answer + disable buttons while regen may take >5s.
        await callback.answer("Regenerando borrador…")
        if callback.message:
            try:
                await callback.message.edit_text(
                    "⏳ Regenerando borrador con tu regla…",
                    reply_markup=None,
                )
            except Exception:
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except Exception:
                    logger.exception(
                        "doctrine_scope_progress_ux_failed",
                        extra={"turn_id": str(turn_id)},
                    )

        status = await handle_doctrine_scope_choice(
            gray_zone=gray_zone,
            coordinator=coordinator,
            turn_id=turn_id,
            scope=scope,  # type: ignore[arg-type]
            admin=admin,
            pending=pending,
            actor_id=actor_id,
        )
        text, _alert = _RESULT_MESSAGES.get(status, ("Procesado", False))
        if callback.message:
            try:
                await callback.message.edit_text(text)
            except Exception:
                logger.exception(
                    "doctrine_scope_result_edit_failed",
                    extra={"turn_id": str(turn_id), "status": status},
                )

    @router.callback_query(lambda c: c.data and c.data.startswith("de:"))
    async def on_doctrine_escalate(callback: CallbackQuery, **_: Any) -> None:
        if not _is_owner(callback):
            await callback.answer("No autorizado", show_alert=True)
            return
        turn_id = parse_doctrine_callback(callback.data or "")
        if turn_id is None:
            await callback.answer("Dato de consulta inválido", show_alert=True)
            return

        await callback.answer()
        actor_id = callback.from_user.id if callback.from_user else None
        status = await handle_doctrine_escalate(
            gray_zone=gray_zone,
            coordinator=coordinator,
            turn_id=turn_id,
            admin=admin,
            actor_id=actor_id,
        )
        text, alert = _RESULT_MESSAGES.get(status, ("Procesado", False))
        if alert:
            try:
                await callback.answer(text, show_alert=True)
            except Exception:
                pass
        elif callback.message:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            try:
                await callback.message.answer(text)
            except Exception:
                logger.exception(
                    "doctrine_escalate_result_notify_failed",
                    extra={"turn_id": str(turn_id)},
                )

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
