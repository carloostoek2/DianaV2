"""Owner callback handlers: approve / correct / escalate."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import UUID

from aiogram import Router
from aiogram.types import BufferedInputFile, CallbackQuery

from diana.application.admin_service import AdminService, OwnerAuthError
from diana.application.admin_trace_service import AdminTraceService
from diana.telegram.keyboards import (
    parse_callback,
    parse_trace_callback,
    step_detail_keyboard,
    trace_detail_keyboard,
    trace_list_keyboard,
)

logger = logging.getLogger("diana.telegram")

DEFAULT_CORRECT_TTL = timedelta(minutes=15)
ClockFn = Callable[[], datetime]


class CorrectSessionStore:
    """In-process FSM: owner_id → awaiting free-text correct for turn_id.

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

    def pop(self, owner_id: int) -> UUID | None:
        item = self._awaiting.pop(owner_id, None)
        if item is None:
            return None
        turn_id, started = item
        if self._clock() - started > self._ttl:
            return None
        return turn_id

    def get(self, owner_id: int) -> UUID | None:
        item = self._awaiting.get(owner_id)
        if item is None:
            return None
        turn_id, started = item
        if self._clock() - started > self._ttl:
            self._awaiting.pop(owner_id, None)
            return None
        return turn_id

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
) -> str:
    """Domain dispatch for unit tests. Returns honest status token."""

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


def _format_step_input(step_name: str, trace: Any) -> str:
    """Format step input for display, truncated to ~1800 chars."""
    step_input_map = {
        "analyst": trace.comprehension,
        "planner": trace.plan,
        "memory_retriever": trace.retrieved,
        "policy_retriever": trace.retrieved,
        "examples_retriever": trace.retrieved,
        "context_builder": trace.prompt_text,
        "generator": trace.prompt_text,
        "evaluator": trace.evaluation,
        "decider": trace.decision,
    }
    result = json.dumps(step_input_map.get(step_name, {}), indent=2, default=str, ensure_ascii=False)
    if len(result) > 1800:
        result = result[:1800] + "\n... (truncated)"
    return result


def _format_step_output(step_name: str, trace: Any) -> str:
    """Format step output for display, truncated to ~1800 chars."""
    step_output_map = {
        "analyst": trace.comprehension,
        "planner": trace.plan,
        "memory_retriever": trace.retrieved,
        "policy_retriever": trace.retrieved,
        "examples_retriever": trace.retrieved,
        "context_builder": trace.prompt_text,
        "generator": trace.generated_text,
        "evaluator": trace.evaluation,
        "decider": trace.decision,
    }
    result = json.dumps(step_output_map.get(step_name, {}), indent=2, default=str, ensure_ascii=False)
    if len(result) > 1800:
        result = result[:1800] + "\n... (truncated)"
    return result


_STEP_TIMING_KEY: dict[str, str] = {
    "analyst": "analyst_ms",
    "planner": "planner_ms",
    "memory_retriever": "memory_retriever_ms",
    "policy_retriever": "policy_retriever_ms",
    "examples_retriever": "examples_retriever_ms",
    "context_builder": "context_builder_ms",
    "generator": "generator_ms",
    "evaluator": "evaluator_ms",
    "decider": "decider_ms",
}


def build_callback_router(
    *,
    admin: AdminService,
    correct_sessions: CorrectSessionStore | None = None,
    admin_trace: AdminTraceService | None = None,
    owner_telegram_id: int | None = None,
) -> Router:
    router = Router(name="callbacks")
    sessions = correct_sessions or CorrectSessionStore()

    @router.callback_query()
    async def on_callback(query: CallbackQuery, **_: Any) -> None:
        actor_id = query.from_user.id if query.from_user else None
        data = query.data or ""

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
                    trace = await admin_trace.get_full_trace(turn_id)
                    if trace is None:
                        await query.answer("Turn not found", show_alert=True)
                        return
                    sid = str(trace.turn_id)[:8]
                    ts = trace.created_at.strftime("%Y-%m-%d %H:%M:%S") if trace.created_at else ""
                    action_label = trace.decision.get("action", "N/A") if trace.decision else "N/A"
                    total_ms = 0
                    if trace.timings:
                        total_ms = int(sum(v for v in trace.timings.values() if isinstance(v, (int, float))))
                    original = (trace.prompt_text or "")[:200]
                    draft = (trace.generated_text or "")[:80]
                    lines = [
                        f"Trace {sid}",
                        f"Date: {ts}",
                        f"Original: \"{original}\"",
                        f"Draft: \"{draft}...\"",
                        f"Decision: {action_label}",
                        f"Total time: {total_ms}ms",
                    ]
                    kb = trace_detail_keyboard(turn_id, timings=trace.timings)
                    if query.message:
                        await query.message.answer("\n".join(lines), reply_markup=kb)
                    await query.answer()
                    return

                if action == "td":
                    turn_id = trace_parsed.turn_id
                    step = trace_parsed.step or ""
                    if turn_id is None or not step:
                        await query.answer("Invalid trace data")
                        return
                    trace = await admin_trace.get_full_trace(turn_id)
                    if trace is None:
                        await query.answer("Turn not found", show_alert=True)
                        return
                    timing_key = _STEP_TIMING_KEY.get(step, f"{step}_ms")
                    ms = (trace.timings or {}).get(timing_key, "N/A")
                    ms_label = f"{int(ms)}ms" if isinstance(ms, (int, float)) else "N/A"
                    step_display = step.replace("_", " ").title()
                    inp = _format_step_input(step, trace)
                    out = _format_step_output(step, trace)
                    msg = (
                        f"Step: {step_display}\n"
                        f"Duration: {ms_label}\n\n"
                        f"Input:\n{inp}\n\n"
                        f"Output:\n{out}"
                    )
                    kb = step_detail_keyboard(turn_id)
                    if query.message:
                        await query.message.answer(msg, reply_markup=kb)
                    await query.answer()
                    return

                if action == "tp":
                    page = trace_parsed.page or 0
                    turns = await admin_trace.get_recent_turns(limit=10, offset=page * 10)
                    total = await admin_trace.count_recent()
                    total_pages = max(1, (total + 9) // 10)
                    if not turns:
                        await query.answer("No turns on this page")
                        return
                    lines: list[str] = [f"Recent turns (page {page + 1}/{total_pages}):", ""]
                    for i, t in enumerate(turns, 1):
                        sid = str(t.turn_id)[:8]
                        name = t.vip_name or "Unknown"
                        ts = t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else ""
                        preview = t.message_preview
                        lines.append(f"{i}. [{sid}] {name} (chat {t.chat_id}): \"{preview}\" -> {t.decision} ({ts})")
                    turns_data = [(t.turn_id, str(t.turn_id)[:8]) for t in turns]
                    kb = trace_list_keyboard(turns_data, page=page, total_pages=total_pages)
                    if query.message:
                        await query.message.edit_text("\n".join(lines), reply_markup=kb)
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
        status = await dispatch_owner_callback(
            admin=admin,
            correct_sessions=sessions,
            callback_data=data,
            actor_id=actor_id,
            admin_trace=admin_trace,
        )
        if status == "forbidden":
            await query.answer("Not authorized", show_alert=True)
            return
        if status == "awaiting_correct":
            await query.answer()
            if query.message:
                await query.message.answer(
                    f"Send corrected text for turn {data.split(':', 1)[-1]}"
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

    return router


__all__ = [
    "DEFAULT_CORRECT_TTL",
    "CorrectSessionStore",
    "build_callback_router",
    "dispatch_owner_callback",
]
