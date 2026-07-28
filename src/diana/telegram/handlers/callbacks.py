"""Owner callback handlers: approve / correct / escalate."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Literal
from uuid import UUID

from aiogram import Router
from aiogram.types import BufferedInputFile, CallbackQuery

from diana.application.admin_metrics_service import AdminMetricsService
from diana.application.admin_service import AdminService, OwnerAuthError
from diana.application.admin_trace_service import AdminTraceService
from diana.telegram.keyboards import (
    parse_callback,
    parse_metrics_callback,
    parse_trace_callback,
    step_detail_keyboard,
    trace_detail_keyboard,
    trace_list_keyboard,
)

ADMIN_MENU_TEXT = (
    "Diana F1 admin\n"
    "/add_vip <telegram_user_id> [name]\n"
    "/remove_vip <telegram_user_id>\n"
    "/list_vips\n"
    "/rename_vip <telegram_user_id> <name>\n"
    "/vip_profile <telegram_user_id>\n"
    "/vip_fact <telegram_user_id> <key> <value>\n"
    "/vip_fact_del <telegram_user_id> <key>\n"
    "/vip_note <telegram_user_id> <text>\n"
    "/vip_note_del <telegram_user_id> <index>\n"
    "/sandbox — sandbox help\n"
    "/sandbox on|off|perfil|perfiles|estado|reset\n"
    "Draft buttons: Approve / Correct / Escalate\n"
    "/turnos — recent turns\n"
    "/traza <id> — trace detail\n"
    "/fp <turn_id> — mark escalation false positive\n"
    "/resumen — weekly learning metrics\n"
    "/metricas — alias of /resumen\n"
    "/staging — pending example candidates (promote/discard)"
)

SESSION_EXPIRED_UX = "Session expired — press Correct on the draft again"

logger = logging.getLogger("diana.telegram")

DEFAULT_CORRECT_TTL = timedelta(minutes=15)
ClockFn = Callable[[], datetime]
ResolveState = Literal["live", "expired", "none"]


class CorrectSessionStore:
    """Process-local FSM: owner_id → awaiting free-text correct for turn_id.

    In-memory only (single-instance). Restart clears all sessions; multi-replica
    would need a shared store (out of scope — see docs/OPS_SINGLE_INSTANCE.md).

    Supports TTL (default 15 min) and cancel-by-turn for supersede cleanup.
    """

    def __init__(
        self,
        *,
        ttl: timedelta = DEFAULT_CORRECT_TTL,
        clock: ClockFn | None = None,
    ) -> None:
        self._awaiting: dict[int, tuple[UUID, datetime]] = {}
        self._ttl = ttl
        self._clock: ClockFn = clock or (lambda: datetime.now(UTC))

    def start(self, owner_id: int, turn_id: UUID) -> None:
        self._awaiting[owner_id] = (turn_id, self._clock())
        logger.info(
            "correct_session_started",
            extra={
                "owner_id": owner_id,
                "turn_id": str(turn_id),
                "ttl_s": int(self._ttl.total_seconds()),
            },
        )

    def pop(self, owner_id: int) -> UUID | None:
        item = self._awaiting.pop(owner_id, None)
        if item is None:
            return None
        turn_id, started = item
        if self._clock() - started > self._ttl:
            return None
        return turn_id

    def get(self, owner_id: int) -> UUID | None:
        """Live UUID, or None when missing or expired (pop-on-TTL)."""
        state, turn_id = self.resolve(owner_id)
        if state == "live":
            return turn_id
        return None

    def resolve(
        self, owner_id: int
    ) -> tuple[ResolveState, UUID | None]:
        """Gate helper for free-text correct.

        - live: within TTL; UUID returned; entry KEPT (does not consume)
        - expired: TTL exceeded; entry POPPED; log correct_session_expired once
        - none: missing; no log
        """
        item = self._awaiting.get(owner_id)
        if item is None:
            return ("none", None)
        turn_id, started = item
        if self._clock() - started > self._ttl:
            self._awaiting.pop(owner_id, None)
            logger.info(
                "correct_session_expired",
                extra={
                    "owner_id": owner_id,
                    "turn_id": str(turn_id),
                },
            )
            return ("expired", turn_id)
        return ("live", turn_id)

    def cancel(self, owner_id: int) -> None:
        self._awaiting.pop(owner_id, None)

    def cancel_turn(self, turn_id: UUID) -> int:
        """Clear any correct sessions awaiting this turn (supersede / terminal)."""
        removed = 0
        for oid, (tid, _) in list(self._awaiting.items()):
            if tid == turn_id:
                self._awaiting.pop(oid, None)
                removed += 1
        return removed


def _map_delivery_status(result: Any, *, success_token: str) -> str:
    """Map Admin DeliveryResult | None to honest handler tokens."""
    if result is None:
        return "stale"
    success = getattr(result, "success", False)
    if success:
        return success_token
    if getattr(result, "cancelled", False):
        return "stale"
    return "deliver_failed"


async def dispatch_owner_callback(
    *,
    admin: AdminService,
    correct_sessions: CorrectSessionStore,
    callback_data: str,
    actor_id: int | None,
    admin_trace: AdminTraceService | None = None,
    admin_metrics: AdminMetricsService | None = None,
    owner_telegram_id: int | None = None,
) -> str:
    """Domain dispatch for unit tests. Returns honest status token."""

    # Metrics dashboard callbacks (mx:e / mx:b).
    metrics_action = parse_metrics_callback(callback_data)
    if metrics_action is not None:
        if owner_telegram_id is not None and actor_id != owner_telegram_id:
            return "forbidden"
        if metrics_action == "back":
            return "metrics_back"
        if admin_metrics is None:
            return "metrics_unavailable"
        if metrics_action == "export":
            return "metrics_export"
        return "ignored"

    # Check trace callbacks first (vt, td, tp, tj).
    trace_parsed = parse_trace_callback(callback_data)
    if trace_parsed is not None:
        action = trace_parsed.action
        if admin_trace is None:
            return "ignored"
        if action == "vt":
            turn_id = trace_parsed.turn_id
            if turn_id is not None:
                trace = await admin_trace.get_full_trace(turn_id)
                return "trace_view" if trace is not None else "trace_not_found"
            return "trace_invalid"
        if action == "td":
            turn_id = trace_parsed.turn_id
            step = trace_parsed.step
            if turn_id is not None and step:
                trace = await admin_trace.get_full_trace(turn_id)
                return "trace_detail_view" if trace is not None else "trace_not_found"
            return "trace_invalid"
        if action == "tp":
            return "trace_page"
        if action == "tj":
            turn_id = trace_parsed.turn_id
            if turn_id is not None:
                return "trace_export"
            return "trace_invalid"

    # Standard owner callbacks.
    parsed = parse_callback(callback_data)
    if parsed is None:
        return "ignored"
    action, turn_id = parsed
    try:
        if action == "approve":
            result = await admin.handle_approve(turn_id, actor_id=actor_id)
            status = _map_delivery_status(result, success_token="approved")
            if status != "approved":
                correct_sessions.cancel_turn(turn_id)
            return status
        if action == "correct":
            if actor_id is None:
                raise OwnerAuthError("missing actor")
            admin._assert_owner(actor_id)  # noqa: SLF001 — intentional thin gate
            if not await admin.is_pending_approval(turn_id):
                correct_sessions.cancel_turn(turn_id)
                return "stale"
            correct_sessions.start(actor_id, turn_id)
            return "awaiting_correct"
        if action == "escalate":
            applied = await admin.handle_owner_escalate(turn_id, actor_id=actor_id)
            correct_sessions.cancel_turn(turn_id)
            return "escalated" if applied else "stale"
    except OwnerAuthError:
        return "forbidden"
    return "ignored"


def build_callback_router(
    *,
    admin: AdminService,
    correct_sessions: CorrectSessionStore | None = None,
    admin_trace: AdminTraceService | None = None,
    admin_metrics: AdminMetricsService | None = None,
    owner_telegram_id: int | None = None,
) -> Router:
    router = Router(name="callbacks")
    sessions = correct_sessions or CorrectSessionStore()

    @router.callback_query()
    async def on_callback(query: CallbackQuery, **_: Any) -> None:
        actor_id = query.from_user.id if query.from_user else None
        data = query.data or ""

        # ---- Metrics dashboard callbacks (mx:e / mx:b) ----
        metrics_action = parse_metrics_callback(data)
        if metrics_action is not None:
            if owner_telegram_id is not None and actor_id != owner_telegram_id:
                await query.answer("Not authorized", show_alert=True)
                return
            if metrics_action == "back":
                if query.message:
                    await query.message.answer(ADMIN_MENU_TEXT)
                await query.answer()
                return
            if metrics_action == "export":
                if admin_metrics is None:
                    await query.answer("Métricas no disponibles", show_alert=True)
                    return
                try:
                    payload = await admin_metrics.export_week_json()
                except Exception:
                    logger.exception("Error exporting metrics JSON")
                    await query.answer("Error al exportar", show_alert=True)
                    return
                if query.message:
                    await query.message.answer(payload)
                await query.answer()
                return

        # ---- Trace callbacks (handled before standard dispatch) ----
        trace_parsed = parse_trace_callback(data)
        if trace_parsed is not None and admin_trace is not None:
            # Owner auth check for trace callbacks.
            if owner_telegram_id is not None and actor_id != owner_telegram_id:
                await query.answer("Not authorized", show_alert=True)
                return

            action = trace_parsed.action
            try:
                if action == "vt":
                    turn_id = trace_parsed.turn_id
                    if turn_id is None:
                        await query.answer("Invalid trace data")
                        return
                    view = await admin_trace.render_trace_summary(turn_id)
                    if view is None:
                        await query.answer("Turn not found", show_alert=True)
                        return
                    kb = trace_detail_keyboard(view.turn_id, timings=view.timings)
                    if query.message:
                        await query.message.answer(view.text, reply_markup=kb)
                    await query.answer()
                    return

                if action == "td":
                    turn_id = trace_parsed.turn_id
                    step = trace_parsed.step or ""
                    if turn_id is None or not step:
                        await query.answer("Invalid trace data")
                        return
                    view = await admin_trace.render_step_detail(turn_id, step)
                    if view is None:
                        await query.answer("Turn not found", show_alert=True)
                        return
                    kb = step_detail_keyboard(view.turn_id)
                    if query.message:
                        await query.message.answer(view.text, reply_markup=kb)
                    await query.answer()
                    return

                if action == "tp":
                    page = trace_parsed.page or 0
                    # Global pagination (no chat_id filter) — residual vs /turnos filter.
                    view = await admin_trace.render_turns_page(page)
                    if view.empty:
                        await query.answer("No turns on this page")
                        return
                    kb = trace_list_keyboard(
                        view.turns_data,
                        page=view.page,
                        total_pages=view.total_pages,
                    )
                    if query.message:
                        await query.message.edit_text(view.text, reply_markup=kb)
                    await query.answer()
                    return

                if action == "tj":
                    turn_id = trace_parsed.turn_id
                    if turn_id is None:
                        await query.answer("Invalid trace data")
                        return
                    json_str = await admin_trace.export_trace_json(turn_id)
                    if query.message:
                        buf = BufferedInputFile(json_str.encode("utf-8"), filename=f"trace_{turn_id}.json")
                        await query.message.answer_document(buf, caption=f"Trace {turn_id}")
                    await query.answer()
                    return
            except Exception:
                logger.exception("Error processing trace callback")
                await query.answer("System error: unable to query traces. Try again later.", show_alert=True)
                return

        # ---- Standard owner callbacks ----
        # Domain dispatch only — status→Telegram UX mapping stays outside so
        # post-success I/O faults are not labeled "Error processing action."
        try:
            status = await dispatch_owner_callback(
                admin=admin,
                correct_sessions=sessions,
                callback_data=data,
                actor_id=actor_id,
                admin_trace=admin_trace,
            )
        except Exception:
            logger.exception(
                "owner_callback_error",
                extra={"callback_data": data, "actor_id": actor_id},
            )
            try:
                await query.answer(
                    "Error processing action. Try again.",
                    show_alert=True,
                )
            except Exception:
                logger.exception("owner_callback_answer_failed")
            return

        try:
            if status == "forbidden":
                await query.answer("Not authorized", show_alert=True)
                return
            if status == "awaiting_correct":
                await query.answer()
                # Follow-up chat text is best-effort: never re-answer the callback.
                if query.message:
                    try:
                        await query.message.answer(
                            f"Send corrected text for turn {data.split(':', 1)[-1]}"
                        )
                    except Exception:
                        logger.exception(
                            "owner_callback_followup_failed",
                            extra={"callback_data": data, "actor_id": actor_id},
                        )
                return
            if status == "approved":
                await query.answer("Approved")
                return
            if status == "escalated":
                await query.answer("Escalated")
                return
            if status == "stale":
                await query.answer(
                    "Already handled or superseded — no action taken",
                    show_alert=True,
                )
                return
            if status == "deliver_failed":
                await query.answer("Delivery failed — try again", show_alert=True)
                return
            await query.answer()
        except Exception:
            logger.exception(
                "owner_callback_answer_failed",
                extra={
                    "callback_data": data,
                    "actor_id": actor_id,
                    "status": status,
                },
            )

    return router


__all__ = [
    "ADMIN_MENU_TEXT",
    "DEFAULT_CORRECT_TTL",
    "CorrectSessionStore",
    "build_callback_router",
    "dispatch_owner_callback",
]
