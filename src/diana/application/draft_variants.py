"""Owner draft versions: regenerate + prev/next navigation (v1 port).

Variants live inside ``approval.evaluation["_draft_versions"]`` so no migration
is required. ``draft_text`` always mirrors the selected variant for approve.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from diana.application.ports import (
    ApprovalRecord,
    MessageHistoryWriter,
    OwnerNotifierPort,
    PendingApprovalStore,
    TurnStore,
    VipStore,
)
from diana.cognitive.models import (
    Decision,
    IncomingTurn,
    TurnStatus,
    is_turn_status_terminal,
)

logger = logging.getLogger("diana.application")

VERSIONS_KEY = "_draft_versions"
MAX_DRAFT_VARIANTS = 10

# Fires when a regeneration run actually starts (after the soft-lock), so the
# owner sees live "Regenerando" feedback; the caller replaces it on success.
RegeneratingCallback = Callable[[], Awaitable[None]]


class DirectorPort(Protocol):
    async def handle_turn(self, turn_context: IncomingTurn) -> Decision: ...


@dataclass(frozen=True, slots=True)
class VariantNavResult:
    ok: bool
    token: str  # regen_ok|nav_ok|blocked_*|stale|error
    approval: ApprovalRecord | None = None
    toast: str = ""


def ensure_versions(
    evaluation: dict[str, Any] | None,
    *,
    draft_text: str,
    reason: str,
    vip_text: str,
) -> dict[str, Any]:
    """Return evaluation dict with versions block (idempotent if already present)."""
    base = dict(evaluation or {})
    existing = base.get(VERSIONS_KEY)
    if isinstance(existing, dict) and isinstance(existing.get("items"), list):
        items = existing["items"]
        if items:
            return base
    base[VERSIONS_KEY] = {
        "items": [{"text": draft_text, "reason": reason or ""}],
        "selected": 0,
        "regenerating": False,
        "vip_text": vip_text,
    }
    return base


def read_versions(evaluation: dict[str, Any] | None) -> dict[str, Any]:
    raw = (evaluation or {}).get(VERSIONS_KEY)
    if not isinstance(raw, dict):
        return {
            "items": [],
            "selected": 0,
            "regenerating": False,
            "vip_text": "",
        }
    items = raw.get("items") if isinstance(raw.get("items"), list) else []
    selected = int(raw.get("selected") or 0)
    if items:
        selected = max(0, min(selected, len(items) - 1))
    else:
        selected = 0
    return {
        "items": items,
        "selected": selected,
        "regenerating": bool(raw.get("regenerating")),
        "vip_text": str(raw.get("vip_text") or ""),
    }


def selected_text(evaluation: dict[str, Any] | None, fallback: str) -> str:
    v = read_versions(evaluation)
    items = v["items"]
    if not items:
        return fallback
    item = items[v["selected"]]
    if isinstance(item, dict):
        return str(item.get("text") or fallback)
    return fallback


def build_owner_draft_text(
    record: ApprovalRecord, vip_name: str | None = None
) -> str:
    """Reconstruct the owner draft DM body from an approval record.

    Mirrors the on-message body so void/audit paths show the same text the
    owner last saw. VIP name falls back to chat_id when the caller does not
    resolve a display name.
    """
    v = read_versions(record.evaluation)
    vip_text = v.get("vip_text") or ""
    items = v["items"] or [{"text": record.draft_text}]
    selected = v["selected"] if items else 0
    summary = ""
    if record.evaluation:
        e = record.evaluation
        try:
            summary = (
                f"nat={float(e.get('naturalness', 0)):.2f} "
                f"prec={float(e.get('precision', 0)):.2f} "
                f"saf={float(e.get('safety', 0)):.2f}"
            )
        except (TypeError, ValueError):
            summary = ""
    return format_draft_owner_text(
        vip_name=vip_name or str(record.chat_id),
        vip_text=vip_text,
        draft_text=record.draft_text,
        reason=record.cognitive_summary or "",
        evaluation_summary=summary,
        version_index=selected,
        version_count=len(items),
    )


async def resolve_vip_display_name(
    vips: VipStore | None,
    vip_id: UUID | None,
    chat_id: int,
) -> str | None:
    """Best-effort VIP display name; None when the store is missing or the VIP is unknown."""
    if vips is None:
        return None
    if vip_id is not None:
        rec = await vips.get_by_id(vip_id)
    else:
        rec = await vips.get_by_telegram_user_id(chat_id)
    if rec is not None and getattr(rec, "display_name", None):
        return str(rec.display_name)
    return None


def format_draft_owner_text(
    *,
    vip_name: str,
    vip_text: str,
    draft_text: str,
    reason: str,
    evaluation_summary: str,
    version_index: int,
    version_count: int,
) -> str:
    """Plain-ish HTML body for owner draft (matches notifier style)."""

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    header = (
        f"<b>Propuesta de respuesta para {esc(vip_name)}</b>"
        f" — borrador {version_index + 1}/{version_count}\n"
    )
    body = (
        f"{header}"
        f"[usuario]: {esc(vip_text)}\n"
        f"[propuesta]: {esc(draft_text)}"
    )
    if reason:
        body += f"\n\nMotivo: {esc(reason)}"
    if evaluation_summary:
        body += f"\nEvaluación: {esc(evaluation_summary)}"
    return body


class DraftVariantService:
    """Regenerate and navigate approval draft variants; edits owner message in place."""

    def __init__(
        self,
        *,
        approvals: PendingApprovalStore,
        turns: TurnStore,
        director: DirectorPort,
        notifier: OwnerNotifierPort,
        owner_telegram_id: int,
        history: MessageHistoryWriter | None = None,
        vips: VipStore | None = None,
        max_variants: int = MAX_DRAFT_VARIANTS,
    ) -> None:
        self._approvals = approvals
        self._turns = turns
        self._director = director
        self._notifier = notifier
        self._owner_telegram_id = owner_telegram_id
        self._history = history
        self._vips = vips
        self._max = max(1, int(max_variants))

    def _assert_owner(self, actor_id: int | None) -> None:
        if actor_id is None or actor_id != self._owner_telegram_id:
            from diana.application.admin_service import OwnerAuthError

            raise OwnerAuthError(
                f"actor_id {actor_id!r} is not the configured owner"
            )

    async def navigate(
        self, turn_id: UUID, *, actor_id: int | None, delta: int
    ) -> VariantNavResult:
        self._assert_owner(actor_id)
        approval = await self._approvals.get_by_turn(turn_id)
        if approval is None or approval.status != "waiting":
            return VariantNavResult(ok=False, token="stale", toast="Borrador no disponible")
        turn = await self._turns.get(turn_id)
        if turn is None or is_turn_status_terminal(turn.status):
            return VariantNavResult(ok=False, token="stale", toast="Borrador no disponible")
        versions = read_versions(approval.evaluation)
        if versions["regenerating"]:
            return VariantNavResult(
                ok=False, token="blocked_regenerating", toast="Espera a que termine la regeneración"
            )
        items = versions["items"]
        if not items:
            return VariantNavResult(ok=False, token="stale", toast="Sin versiones")
        new_sel = versions["selected"] + delta
        if new_sel < 0:
            return VariantNavResult(ok=False, token="blocked_first", toast="Primera versión")
        if new_sel >= len(items):
            return VariantNavResult(ok=False, token="blocked_last", toast="Última versión")
        updated = await self._apply_selection(approval, new_sel)
        if updated is None:
            return VariantNavResult(ok=False, token="stale", toast="Borrador no disponible")
        await self._refresh_owner_message(updated)
        return VariantNavResult(ok=True, token="nav_ok", approval=updated, toast="")

    async def regenerate(
        self,
        turn_id: UUID,
        *,
        actor_id: int | None,
        on_start: RegeneratingCallback | None = None,
    ) -> VariantNavResult:
        self._assert_owner(actor_id)
        approval = await self._approvals.get_by_turn(turn_id)
        if approval is None or approval.status != "waiting":
            return VariantNavResult(ok=False, token="stale", toast="Borrador no disponible")
        turn = await self._turns.get(turn_id)
        if turn is None:
            return VariantNavResult(ok=False, token="stale", toast="Turno no encontrado")
        if is_turn_status_terminal(turn.status):
            # Never re-run cognition or refresh buttons on a dead turn.
            return VariantNavResult(ok=False, token="stale", toast="Borrador no disponible")
        versions = read_versions(approval.evaluation)
        if versions["regenerating"]:
            return VariantNavResult(
                ok=False, token="blocked_regenerating", toast="Ya se está regenerando…"
            )
        if len(versions["items"]) >= self._max:
            return VariantNavResult(
                ok=False,
                token="blocked_max",
                toast=f"Máximo {self._max} versiones",
            )

        # Soft lock
        locked = await self._set_regenerating(approval, True)
        if locked is None:
            return VariantNavResult(ok=False, token="stale", toast="Borrador no disponible")

        try:
            # Re-check after lock: race may have terminalized the turn.
            turn = await self._turns.get(turn_id)
            if turn is None or is_turn_status_terminal(turn.status):
                await self._set_regenerating(locked, False)
                return VariantNavResult(
                    ok=False, token="stale", toast="Borrador no disponible"
                )

            await self._notify_regenerating(on_start)

            vip_text = versions.get("vip_text") or ""
            if not vip_text and self._history is not None:
                vip_text = await self._resolve_vip_text(
                    locked.chat_id, locked.trigger_message_id
                )
            if not vip_text:
                vip_text = "(mensaje original no disponible)"

            ctx = IncomingTurn(
                turn_id=turn_id,
                chat_id=locked.chat_id,
                vip_id=locked.vip_id,
                text=vip_text,
                telegram_message_id=locked.trigger_message_id,
                business_connection_id=locked.business_connection_id,
            )
            decision = await self._director.handle_turn(ctx)
            draft = (decision.draft_text or "").strip()
            if not draft:
                return VariantNavResult(
                    ok=False,
                    token="error",
                    toast="Regeneración falló: borrador vacío",
                    approval=await self._set_regenerating(locked, False),
                )

            # Post-LLM gates: never revive a cancelled/superseded draft UI.
            turn_after = await self._turns.get(turn_id)
            if turn_after is None or is_turn_status_terminal(turn_after.status):
                logger.info(
                    "draft_regen_aborted_terminal",
                    extra={
                        "turn_id": str(turn_id),
                        "status": None if turn_after is None else turn_after.status,
                    },
                )
                # Close orphan waiting approvals on a dead turn (no UI refresh).
                try:
                    orphan = await self._approvals.get_by_turn(turn_id)
                    if orphan is not None and orphan.status == "waiting":
                        await self._approvals.mark_status(turn_id, "cancelled")
                except Exception:
                    logger.exception(
                        "draft_regen_cancel_orphan_failed",
                        extra={"turn_id": str(turn_id)},
                    )
                return VariantNavResult(
                    ok=False, token="stale", toast="Borrador cancelado"
                )

            live = await self._approvals.get_by_turn(turn_id)
            if live is None or live.status != "waiting":
                return VariantNavResult(
                    ok=False, token="stale", toast="Borrador cancelado"
                )

            v = read_versions(live.evaluation)
            items = list(v["items"])
            items.append({"text": draft, "reason": decision.reason or ""})
            selected = len(items) - 1
            eval_dict = dict(live.evaluation or {})
            # Keep latest evaluation dims when present
            if decision.evaluation is not None:
                dims = decision.evaluation.model_dump(mode="json")
                eval_dict.update(dims)
            eval_dict[VERSIONS_KEY] = {
                "items": items,
                "selected": selected,
                "regenerating": False,
                "vip_text": v.get("vip_text") or vip_text,
            }
            # CAS: only while still waiting (lost race → None, no UI refresh).
            updated = await self._approvals.update_draft(
                turn_id,
                draft_text=draft,
                evaluation=eval_dict,
                cognitive_summary=decision.reason,
            )
            if updated is None:
                return VariantNavResult(
                    ok=False, token="stale", toast="Borrador cancelado"
                )

            # Restore approval queue status; refuse UI if terminal latch wins.
            try:
                restored = await self._turns.transition(
                    turn_id, TurnStatus.PENDING_APPROVAL.value
                )
            except Exception:
                logger.exception(
                    "draft_regen_restore_status_failed",
                    extra={"turn_id": str(turn_id)},
                )
                await self._set_regenerating(updated, False)
                return VariantNavResult(
                    ok=False,
                    token="error",
                    toast="Regeneración falló: no se pudo restaurar el borrador",
                )
            if (
                is_turn_status_terminal(restored.status)
                or restored.status != TurnStatus.PENDING_APPROVAL.value
            ):
                logger.info(
                    "draft_regen_restore_not_pending",
                    extra={
                        "turn_id": str(turn_id),
                        "status": restored.status,
                    },
                )
                # Avoid leaving a waiting approval on a dead turn.
                try:
                    live_appr = await self._approvals.get_by_turn(turn_id)
                    if live_appr is not None and live_appr.status == "waiting":
                        await self._approvals.mark_status(turn_id, "cancelled")
                except Exception:
                    logger.exception(
                        "draft_regen_cancel_orphan_failed",
                        extra={"turn_id": str(turn_id)},
                    )
                return VariantNavResult(
                    ok=False, token="stale", toast="Borrador cancelado"
                )

            await self._refresh_owner_message(updated)
            return VariantNavResult(
                ok=True, token="regen_ok", approval=updated, toast="Nueva versión lista"
            )
        except Exception:
            logger.exception(
                "draft_regen_failed",
                extra={"turn_id": str(turn_id)},
            )
            await self._set_regenerating(locked, False)
            return VariantNavResult(
                ok=False, token="error", toast="Regeneración falló: error inesperado"
            )

    async def _resolve_vip_text(
        self, chat_id: int, trigger_message_id: int | None
    ) -> str:
        if self._history is None:
            return ""
        recent = await self._history.get_recent(chat_id, limit=40)
        if trigger_message_id is not None:
            for row in reversed(recent):
                if (
                    row.get("role") == "vip"
                    and row.get("telegram_message_id") == trigger_message_id
                ):
                    return str(row.get("text") or "")
        for row in reversed(recent):
            if row.get("role") == "vip":
                return str(row.get("text") or "")
        return ""

    async def _notify_regenerating(
        self, on_start: RegeneratingCallback | None
    ) -> None:
        """Best-effort live 'Regenerando' signal; a fault never aborts the run."""
        if on_start is None:
            return
        try:
            await on_start()
        except Exception:
            logger.debug("draft_regen_start_callback_failed", exc_info=True)

    async def _set_regenerating(
        self, approval: ApprovalRecord, flag: bool
    ) -> ApprovalRecord | None:
        live = await self._approvals.get_by_turn(approval.turn_id)
        if live is None or live.status != "waiting":
            return None
        eval_dict = ensure_versions(
            live.evaluation,
            draft_text=live.draft_text,
            reason=live.cognitive_summary or "",
            vip_text=read_versions(live.evaluation).get("vip_text") or "",
        )
        v = read_versions(eval_dict)
        eval_dict[VERSIONS_KEY] = {
            **v,
            "regenerating": flag,
        }
        return await self._approvals.update_draft(
            live.turn_id,
            draft_text=live.draft_text,
            evaluation=eval_dict,
            cognitive_summary=live.cognitive_summary,
        )

    async def _apply_selection(
        self, approval: ApprovalRecord, selected: int
    ) -> ApprovalRecord | None:
        eval_dict = ensure_versions(
            approval.evaluation,
            draft_text=approval.draft_text,
            reason=approval.cognitive_summary or "",
            vip_text=read_versions(approval.evaluation).get("vip_text") or "",
        )
        v = read_versions(eval_dict)
        items = v["items"]
        selected = max(0, min(selected, len(items) - 1))
        item = items[selected]
        text = str(item.get("text") if isinstance(item, dict) else item)
        reason = (
            str(item.get("reason") or approval.cognitive_summary or "")
            if isinstance(item, dict)
            else (approval.cognitive_summary or "")
        )
        eval_dict[VERSIONS_KEY] = {
            **v,
            "selected": selected,
            "regenerating": False,
        }
        return await self._approvals.update_draft(
            approval.turn_id,
            draft_text=text,
            evaluation=eval_dict,
            cognitive_summary=reason,
        )

    async def _refresh_owner_message(self, approval: ApprovalRecord) -> None:
        edit = getattr(self._notifier, "edit_draft", None)
        if not callable(edit) or approval.owner_message_id is None:
            return
        vip_name = await resolve_vip_display_name(
            self._vips, approval.vip_id, approval.chat_id
        )
        text = build_owner_draft_text(approval, vip_name=vip_name)
        try:
            await edit(
                owner_message_id=approval.owner_message_id,
                text=text,
                turn_id=approval.turn_id,
                chat_id=approval.chat_id,
            )
        except Exception:
            logger.exception(
                "draft_variant_edit_failed",
                extra={"turn_id": str(approval.turn_id)},
            )


__all__ = [
    "MAX_DRAFT_VARIANTS",
    "VERSIONS_KEY",
    "DraftVariantService",
    "RegeneratingCallback",
    "VariantNavResult",
    "build_owner_draft_text",
    "ensure_versions",
    "format_draft_owner_text",
    "read_versions",
    "resolve_vip_display_name",
    "selected_text",
]
