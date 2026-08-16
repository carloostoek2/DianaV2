"""Owner callback handlers: approve / correct / escalate."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Literal
from uuid import UUID

from aiogram import Router
from aiogram.types import BufferedInputFile, CallbackQuery

from diana.application.admin_metrics_service import AdminMetricsService
from diana.application.admin_service import AdminService, OwnerAuthError
from diana.behavior.ports import DeliveryProgressCallback, ProgressKind
from diana.application.admin_trace_service import AdminTraceService
from diana.application.draft_variants import (
    RegeneratingCallback,
    build_owner_draft_text,
)
from diana.application.profile_admin_service import ProfileAdminService
from diana.telegram.keyboards import (
    MENU_ROOT_TEXT,
    draft_keyboard,
    menu_root_keyboard,
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
    "/sandbox — ayuda sandbox\n"
    "/sandbox on|off|perfil|perfiles|estado|reset\n"
    "Botones del borrador: Aprobar / Corregir / Escalar\n"
    "/turnos — turnos recientes\n"
    "/traza <id> — detalle de traza\n"
    "/fp <turn_id> — marcar falsa alarma\n"
    "/resumen — métricas semanales\n"
    "/metricas — alias de /resumen\n"
    "/staging — ejemplos pendientes (promover/descartar)"
)

SESSION_EXPIRED_UX = "Sesión expirada — presiona Corregir de nuevo en el borrador"

logger = logging.getLogger("diana.telegram")

DEFAULT_CORRECT_TTL = timedelta(minutes=15)
ClockFn = Callable[[], datetime]
ResolveState = Literal["live", "expired", "expired_combo", "none"]


@dataclass
class CorrectSession:
    """In-process owner correct / reprimand wait state."""

    turn_id: UUID
    started_at: datetime
    mode: str = "correct"
    phase: str = "await_text"
    candidate_id: UUID | None = None
    corrected_text: str | None = None
    chat_id: int | None = None


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
        self._awaiting: dict[int, CorrectSession] = {}
        self._ttl = ttl
        self._clock: ClockFn = clock or (lambda: datetime.now(UTC))

    def start(
        self,
        owner_id: int,
        turn_id: UUID,
        *,
        mode: str = "correct",
        chat_id: int | None = None,
    ) -> None:
        self._awaiting[owner_id] = CorrectSession(
            turn_id=turn_id,
            started_at=self._clock(),
            mode=mode,
            phase="await_text",
            chat_id=chat_id,
        )
        logger.info(
            "correct_session_started",
            extra={
                "owner_id": owner_id,
                "turn_id": str(turn_id),
                "ttl_s": int(self._ttl.total_seconds()),
                "mode": mode,
            },
        )

    def pop(self, owner_id: int) -> UUID | None:
        item = self._awaiting.pop(owner_id, None)
        if item is None:
            return None
        if self._clock() - item.started_at > self._ttl:
            return None
        return item.turn_id

    def get(self, owner_id: int) -> UUID | None:
        """Live UUID, or None when missing or expired (pop-on-TTL)."""
        state, turn_id = self.resolve(owner_id)
        if state == "live":
            return turn_id
        return None

    def get_session(self, owner_id: int) -> CorrectSession | None:
        """Live session payload, or None when missing or expired."""
        state, _ = self.resolve(owner_id)
        if state != "live":
            return None
        return self._awaiting.get(owner_id)

    def resolve(
        self, owner_id: int
    ) -> tuple[ResolveState, UUID | None]:
        """Gate helper for free-text correct.

        - live: within TTL; UUID returned; entry KEPT (does not consume)
        - expired: TTL exceeded on await-text; entry POPPED; log once
        - expired_combo: TTL exceeded on reprimand_combo; entry POPPED
        - none: missing; no log
        """
        item = self._awaiting.get(owner_id)
        if item is None:
            return ("none", None)
        if self._clock() - item.started_at > self._ttl:
            self._awaiting.pop(owner_id, None)
            logger.info(
                "correct_session_expired",
                extra={
                    "owner_id": owner_id,
                    "turn_id": str(item.turn_id),
                    "mode": item.mode,
                    "phase": item.phase,
                },
            )
            if item.phase == "reprimand_combo":
                return ("expired_combo", item.turn_id)
            return ("expired", item.turn_id)
        return ("live", item.turn_id)

    def cancel(self, owner_id: int) -> None:
        self._awaiting.pop(owner_id, None)

    def cancel_turn(self, turn_id: UUID) -> int:
        """Clear any correct sessions awaiting this turn (supersede / terminal)."""
        removed = 0
        for oid, sess in list(self._awaiting.items()):
            if sess.turn_id == turn_id:
                self._awaiting.pop(oid, None)
                removed += 1
        return removed

    def refresh(self, owner_id: int) -> None:
        sess = self._awaiting.get(owner_id)
        if sess is not None:
            sess.started_at = self._clock()

    def capture_reprimand(
        self,
        owner_id: int,
        *,
        candidate_id: UUID,
        corrected_text: str,
    ) -> None:
        sess = self._awaiting.get(owner_id)
        if sess is None:
            return
        sess.phase = "reprimand_combo"
        sess.candidate_id = candidate_id
        sess.corrected_text = corrected_text
        sess.started_at = self._clock()

    def cancel_combo_for_chat(self, chat_id: int) -> None:
        """Drop live reprimand_combo sessions for this VIP chat only."""
        for oid, sess in list(self._awaiting.items()):
            if sess.phase == "reprimand_combo" and sess.chat_id == chat_id:
                self._awaiting.pop(oid, None)


def _map_delivery_status(result: Any, *, success_token: str) -> str:
    """Map Admin DeliveryResult | None to honest handler tokens."""
    if result is None:
        return "stale"
    success = getattr(result, "success", False)
    if success:
        return success_token
    if getattr(result, "cancelled", False):
        err = str(getattr(result, "error", "") or "")
        if err == "vip_frozen":
            return "vip_frozen"
        if "superseded" in err:
            return "stale_replaced"
        return "stale_cancelled"
    return "deliver_failed"


# Owner-facing alerts for approve/correct no-ops (product language).
_APPROVE_NOOP_ALERTS: dict[str, str] = {
    "stale": "Ya fue resuelto o reemplazado — no se realizó ninguna acción",
    "stale_replaced": (
        "Este borrador ya no aplica (mensaje nuevo o se reemplazó). No se envió."
    ),
    "stale_already_sent": "Este mensaje ya se había enviado — no se hizo nada.",
    "stale_resolved": "Este turno ya se resolvió — no se hizo nada.",
    "stale_cancelled": "El borrador ya no está disponible — no se envió.",
    "stale_gone": "No se encontró el turno — no se hizo nada.",
    "vip_frozen": "El VIP está en pausa/congelado — no se envió.",
}

# Live delivery stages shown on the draft message while the human-like
# simulation runs after approval (edited in place, buttons kept until the end).
_DRAFT_PROGRESS_LABELS: dict[ProgressKind, str] = {
    "reading": "👀 Mensaje visto",
    "typing": "✍️ Escribiendo…",
}

# Live state shown while a regeneration run is in flight; replaced when the
# new version lands (or the original body is restored on failure).
_REGENERATING_LABEL = "♻️ Regenerando…"


async def dispatch_owner_callback(
    *,
    admin: AdminService,
    correct_sessions: CorrectSessionStore,
    callback_data: str,
    actor_id: int | None,
    admin_trace: AdminTraceService | None = None,
    admin_metrics: AdminMetricsService | None = None,
    owner_telegram_id: int | None = None,
    draft_variants: Any | None = None,
    on_delivery_progress: DeliveryProgressCallback | None = None,
    on_regenerating: RegeneratingCallback | None = None,
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

    # Check trace callbacks first (vt, vtd, td, tdd, tp, tj, tb).
    trace_parsed = parse_trace_callback(callback_data)
    if trace_parsed is not None:
        action = trace_parsed.action
        if action == "tb":
            turn_id = trace_parsed.turn_id
            if turn_id is None:
                return "trace_invalid"
            if admin is not None:
                approval = await admin.get_approval(turn_id)
                if approval is None or approval.status != "waiting":
                    return "trace_back_stale"
            return "trace_back_to_draft"
        if admin_trace is None:
            return "ignored"
        if action in {"vt", "vtd"}:
            turn_id = trace_parsed.turn_id
            if turn_id is not None:
                trace = await admin_trace.get_full_trace(turn_id)
                return "trace_view" if trace is not None else "trace_not_found"
            return "trace_invalid"
        if action in {"td", "tdd"}:
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
            result = await admin.handle_approve(
                turn_id,
                actor_id=actor_id,
                on_progress=on_delivery_progress,
            )
            if result is None:
                correct_sessions.cancel_turn(turn_id)
                return await admin.classify_approve_noop(turn_id)
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
                return await admin.classify_approve_noop(turn_id)
            correct_sessions.start(actor_id, turn_id)
            return "awaiting_correct"
        if action == "escalate":
            applied = await admin.handle_owner_escalate(turn_id, actor_id=actor_id)
            correct_sessions.cancel_turn(turn_id)
            if applied:
                return "escalated"
            return await admin.classify_approve_noop(turn_id)
        if action in {"regen", "prev", "next"}:
            if draft_variants is None:
                return "ignored"
            if action == "regen":
                result = await draft_variants.regenerate(
                    turn_id, actor_id=actor_id, on_start=on_regenerating
                )
            else:
                delta = -1 if action == "prev" else 1
                result = await draft_variants.navigate(
                    turn_id, actor_id=actor_id, delta=delta
                )
            # Token used by Telegram handler for toast UX.
            return result.token
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
    menu_sessions: Any | None = None,
    profile_admin: ProfileAdminService | None = None,
    draft_variants: Any | None = None,
) -> Router:
    """Callback router for owner drafts/traces/metrics.

    ``menu_sessions`` is the shared MenuSessionStore (duck-typed here to avoid
    an import cycle through menu.py). The add-note-from-draft flow (``an:``)
    reuses its TTL-bound "note" session so the pending note expires and is
    cancellable with /cancelar (A1), instead of a permanent in-memory dict.
    """
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
                await query.answer("No autorizado", show_alert=True)
                return
            if metrics_action == "back":
                # A10: edit the same panel back to the root menu instead of
                # stacking a new floating message (fall back to a new one if
                # the message can't be edited, e.g. too old).
                if query.message:
                    try:
                        await query.message.edit_text(
                            MENU_ROOT_TEXT, reply_markup=menu_root_keyboard()
                        )
                    except Exception:
                        await query.message.answer(
                            MENU_ROOT_TEXT, reply_markup=menu_root_keyboard()
                        )
                await query.answer()
                return
            if metrics_action == "export":
                if admin_metrics is None:
                    await query.answer("Métricas no disponibles", show_alert=True)
                    return
                # A3: clear the spinner before the export work; A8: ship the full
                # JSON as a document so it is never capped at Telegram's 4096.
                try:
                    await query.answer()
                except Exception:
                    logger.debug("metrics_export_early_answer_failed", exc_info=True)
                try:
                    payload = await admin_metrics.export_week_json()
                except Exception:
                    logger.exception("Error exporting metrics JSON")
                    try:
                        await query.answer("Error al exportar", show_alert=True)
                    except Exception:
                        logger.exception("metrics_export_error_answer_failed")
                    return
                if query.message:
                    buf = BufferedInputFile(
                        payload.encode("utf-8"),
                        filename="metricas_semanales.json",
                    )
                    await query.message.answer_document(
                        buf, caption="Métricas semanales"
                    )
                return

        # ---- Add-note callback (an:<chat_id>) ----
        if data.startswith("an:"):
            if menu_sessions is None or profile_admin is None:
                await query.answer("Gestión de notas no disponible", show_alert=True)
                return
            if actor_id is None:
                await query.answer("No autorizado", show_alert=True)
                return
            raw = data[3:]
            try:
                chat_id_val = int(raw)
            except ValueError:
                await query.answer("Dato inválido")
                return
            if chat_id_val == 0:
                await query.answer("No se pudo identificar el chat", show_alert=True)
                return
            menu_sessions.start(
                actor_id,
                "note",
                vip_user_id=chat_id_val,
                last_chat_id=query.message.chat.id if query.message else None,
            )
            await query.answer()
            if query.message:
                prompt = await query.message.answer(
                    "📝 Envía el texto de la nota:\n\nUsa /cancelar para abortar."
                )
                # Point the note session at the prompt so the confirmation
                # edits it in place (draft message stays untouched).
                sess = menu_sessions.get(actor_id)
                if sess is not None:
                    sess.last_bot_message_id = prompt.message_id
            return

        # ---- Trace callbacks (handled before standard dispatch) ----
        trace_parsed = parse_trace_callback(data)
        if trace_parsed is not None and admin_trace is not None:
            # Owner auth check for trace callbacks.
            if owner_telegram_id is not None and actor_id != owner_telegram_id:
                await query.answer("No autorizado", show_alert=True)
                return

            action = trace_parsed.action
            try:
                if action in {"vt", "vtd"}:
                    turn_id = trace_parsed.turn_id
                    if turn_id is None:
                        await query.answer("Dato de traza inválido")
                        return
                    view = await admin_trace.render_trace_summary(turn_id)
                    if view is None:
                        await query.answer("Turno no encontrado", show_alert=True)
                        return
                    kb = trace_detail_keyboard(
                        view.turn_id,
                        timings=view.timings,
                        from_draft=action == "vtd",
                        page=trace_parsed.page or 0,
                    )
                    if query.message:
                        await query.message.edit_text(view.text, reply_markup=kb, parse_mode=None)
                    await query.answer()
                    return

                if action in {"td", "tdd"}:
                    turn_id = trace_parsed.turn_id
                    step = trace_parsed.step or ""
                    if turn_id is None or not step:
                        await query.answer("Dato de traza inválido")
                        return
                    view = await admin_trace.render_step_detail(turn_id, step)
                    if view is None:
                        await query.answer("Turno no encontrado", show_alert=True)
                        return
                    kb = step_detail_keyboard(view.turn_id, from_draft=action == "tdd")
                    if query.message:
                        await query.message.edit_text(view.text, reply_markup=kb, parse_mode=None)
                    await query.answer()
                    return

                if action == "tb":
                    turn_id = trace_parsed.turn_id
                    if turn_id is None:
                        await query.answer("Dato de traza inválido")
                        return
                    approval = await admin.get_approval(turn_id)
                    if approval is None or approval.status != "waiting":
                        await query.answer("Borrador no disponible", show_alert=True)
                        return
                    vip_name = await admin.resolve_vip_display_name(
                        approval.vip_id, approval.chat_id
                    )
                    text = build_owner_draft_text(approval, vip_name=vip_name)
                    kb = draft_keyboard(turn_id, chat_id=approval.chat_id)
                    if query.message:
                        await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
                    await query.answer()
                    return

                if action == "tp":
                    page = trace_parsed.page or 0
                    # Global pagination (no chat_id filter) — residual vs /turnos filter.
                    view = await admin_trace.render_turns_page(page)
                    if view.empty:
                        await query.answer("No hay turnos en esta página")
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
                        await query.answer("Dato de traza inválido")
                        return
                    json_str = await admin_trace.export_trace_json(turn_id)
                    if query.message:
                        buf = BufferedInputFile(json_str.encode("utf-8"), filename=f"trace_{turn_id}.json")
                        await query.message.answer_document(buf, caption=f"Trace {turn_id}")
                    await query.answer()
                    return
            except Exception:
                logger.exception("Error processing trace callback")
                await query.answer("Error del sistema al consultar la traza. Inténtalo más tarde.", show_alert=True)
                return

        # ---- Standard owner callbacks ----
        # A3: clear the button spinner immediately, before the heavy work
        # (approve/correct/escalate deliver to the VIP + write the DB).
        try:
            await query.answer()
        except Exception:
            logger.debug("owner_callback_early_answer_failed", exc_info=True)

        # Snapshot the draft body once, before any live-edit below, so the
        # progress stages and the final status all keep the original text.
        draft_text = (
            (query.message.text or query.message.caption or "")
            if query.message
            else ""
        )

        # Live delivery stages: while the human-like simulation runs, edit the
        # draft in place (leído → escribiendo) keeping the buttons until the
        # final status replaces them. Faults are best-effort (engine already
        # guards its own callback).
        async def _progress(kind: ProgressKind) -> None:
            if query.message is None or not draft_text:
                return
            label = _DRAFT_PROGRESS_LABELS.get(kind)
            if label is None:
                return
            try:
                await query.message.edit_text(
                    f"{label}\n\n{draft_text}",
                    reply_markup=query.message.reply_markup,
                    parse_mode="HTML",
                )
            except Exception:
                logger.debug("draft_progress_edit_failed", exc_info=True)

        # Live "Regenerando" state: fired only once a regeneration run actually
        # starts (after the draft_variants soft-lock), so blocked/stale early
        # returns never flash it. A failed run restores the original body below.
        regen_started = False

        async def _regenerating() -> None:
            nonlocal regen_started
            regen_started = True
            if query.message is None or not draft_text:
                return
            try:
                await query.message.edit_text(
                    f"{_REGENERATING_LABEL}\n\n{draft_text}",
                    reply_markup=query.message.reply_markup,
                    parse_mode="HTML",
                )
            except Exception:
                logger.debug("draft_regen_edit_failed", exc_info=True)

        # Domain dispatch only — status→Telegram UX mapping stays outside so
        # post-success I/O faults are not labeled "Error processing action."
        try:
            status = await dispatch_owner_callback(
                admin=admin,
                correct_sessions=sessions,
                callback_data=data,
                actor_id=actor_id,
                admin_trace=admin_trace,
                draft_variants=draft_variants,
                on_delivery_progress=_progress,
                on_regenerating=_regenerating,
            )
        except Exception:
            logger.exception(
                "owner_callback_error",
                extra={"callback_data": data, "actor_id": actor_id},
            )
            try:
                await query.answer(
                    "Error al procesar la acción. Inténtalo de nuevo.",
                    show_alert=True,
                )
            except Exception:
                logger.exception("owner_callback_answer_failed")
            return

        try:
            # Regeneration started but never produced a new version (error /
            # stale): restore the original draft body so the legend never sticks.
            if regen_started and status != "regen_ok" and query.message:
                try:
                    await query.message.edit_text(
                        draft_text,
                        reply_markup=query.message.reply_markup,
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.debug("draft_regen_restore_failed", exc_info=True)
            if status == "forbidden":
                await query.answer("No autorizado", show_alert=True)
                return
            if status == "awaiting_correct":
                # Follow-up chat text is best-effort: never re-answer the callback.
                if query.message:
                    try:
                        await query.message.answer(
                            f"Envía el texto corregido para el turno {data.split(':', 1)[-1]}"
                        )
                    except Exception:
                        logger.exception(
                            "owner_callback_followup_failed",
                            extra={"callback_data": data, "actor_id": actor_id},
                        )
                return
            if status == "approved":
                # The message edit is the primary feedback; the initial empty
                # answer already cleared the spinner (A3). ``draft_text`` keeps
                # the original body even after live progress edits.
                if query.message:
                    try:
                        await query.message.edit_text(
                            f"✅ <b>Enviado</b>\n\n{draft_text}",
                            reply_markup=None,
                            parse_mode="HTML",
                        )
                    except Exception:
                        logger.exception("Error al editar mensaje aprobado")
                return
            if status == "escalated":
                if query.message:
                    try:
                        await query.message.edit_text(
                            f"⚠️ <b>Escalado</b>\n\n{draft_text}",
                            reply_markup=None,
                            parse_mode="HTML",
                        )
                    except Exception:
                        logger.exception("Error al editar mensaje escalado")
                return
            if status in _APPROVE_NOOP_ALERTS:
                await query.answer(
                    _APPROVE_NOOP_ALERTS[status],
                    show_alert=True,
                )
                return
            if status == "deliver_failed":
                await query.answer("Error al enviar — inténtalo de nuevo", show_alert=True)
                return
            # Draft versioning (regen / prev / next)
            if status == "regen_ok":
                await query.answer("Nueva versión lista")
                return
            if status == "nav_ok":
                return
            if status == "blocked_regenerating":
                await query.answer("Espera a que termine la regeneración", show_alert=True)
                return
            if status == "blocked_max":
                await query.answer("Máximo de versiones alcanzado", show_alert=True)
                return
            if status == "blocked_first":
                await query.answer("Primera versión")
                return
            if status == "blocked_last":
                await query.answer("Última versión")
                return
            if status == "error":
                await query.answer("No se pudo regenerar — inténtalo", show_alert=True)
                return
            # Statuses without a toast (ignored, metrics_*, trace_*) rely on the
            # initial empty answer above.
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
