"""Owner draft versions: regenerate + prev/next navigation (v1 port).

Variants live inside ``approval.evaluation["_draft_versions"]`` so no migration
is required. ``draft_text`` always mirrors the selected variant for approve.
"""

from __future__ import annotations

import logging
import math
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
from diana.cognitive.thresholds import DEFAULT_AUTONOMOUS_THRESHOLDS

logger = logging.getLogger("diana.application")

VERSIONS_KEY = "_draft_versions"
DOCTRINE_RELEVANT_KEY = "_doctrine_relevant"
DOCTRINE_NA_LABEL = "no aplica"
AUTONOMY_KEY = "_autonomy"
MAX_DRAFT_VARIANTS = 10

# Canonical order of the stored evaluation dimensions.
_DIM_KEYS: tuple[str, ...] = (
    "naturalness",
    "precision",
    "doctrine",
    "consistency",
    "safety",
    "coverage",
    "empathy",
)

# Owner-facing Spanish labels for the evaluation section (display only).
DIMENSION_LABELS_ES: tuple[tuple[str, str], ...] = (
    ("naturalness", "Naturalidad"),
    ("precision", "Precisión"),
    ("doctrine", "Doctrina"),
    ("consistency", "Consistencia"),
    ("safety", "Seguridad"),
    ("coverage", "Cobertura"),
    ("empathy", "Empatía"),
)

# Decision.reason tokens that can reach an approval draft → clear Spanish.
# Machine tokens stay stable for stores/parsers (escalation_labels pattern).
APPROVAL_REASON_LABELS: dict[str, str] = {
    "ok_for_human_review": (
        "El envío autónomo está apagado: el turno pasa por tu revisión."
    ),
    "autonomous_below_threshold": (
        "Diana no envió sola: el borrador no alcanzó los mínimos de autonomía."
    ),
    "autonomous_ok": "Diana habría enviado sola, pero este VIP aún no está activado.",
    "safety_below_threshold": (
        "Se frenó por seguridad: el contenido no se considera seguro para enviar."
    ),
    "risk_high": "Se frenó por riesgo alto en la conversación.",
    "frustracion_directa": "El VIP está molesto: conviene tu revisión.",
    "doctrine_not_found": "Faltaba una regla de negocio y se consultó la doctrina.",
    "gray_zone_resolved_by_doctrine": "Doctrina resuelta: borrador generado con la regla.",
    "startup_re_notify": "Recordatorio de un borrador pendiente de aprobación.",
}

# Turn categories (stored ASCII) → Spanish for the non-technical Autonomía text.
_TURN_CATEGORY_ES: dict[str, str] = {
    "fatico": "de cortesía",
    "informativo": "informativas",
    "emocional": "emocionales",
    "sensible": "sensibles",
}

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


def _dims_subset(mapping: dict[str, Any] | None) -> dict[str, float]:
    """Floats of the 7 evaluation dims present in a stored dict (JSON-safe)."""
    out: dict[str, float] = {}
    for key in _DIM_KEYS:
        try:
            value = float(mapping.get(key))  # type: ignore[union-attr]
        except (TypeError, ValueError, AttributeError):
            continue
        if math.isfinite(value):
            out[key] = value
    return out


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
    first = {"text": draft_text, "reason": reason or ""}
    per_version = _dims_subset(base)
    if per_version:
        first["evaluation"] = per_version
    base[VERSIONS_KEY] = {
        "items": [first],
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

    Single source of truth is ``record.evaluation`` (dims, doctrine relevance,
    ``_draft_versions`` and — when the readiness feature was on at creation —
    the ``_autonomy`` snapshot), so void/audit paths show the same body the
    owner last saw. VIP name falls back to chat_id when the caller does not
    resolve a display name.
    """
    v = read_versions(record.evaluation)
    vip_text = v.get("vip_text") or ""
    items = v["items"] or [{"text": record.draft_text}]
    selected = v["selected"] if items else 0
    return format_draft_owner_text(
        vip_name=vip_name or str(record.chat_id),
        vip_text=vip_text,
        draft_text=record.draft_text,
        reason=record.cognitive_summary or "",
        evaluation=record.evaluation,
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


def localize_reason(raw: str) -> str:
    """Decision.reason token → clear Spanish owner-facing text.

    Preserves a ``SANDBOX — profile: x | <token>`` prefix (display-only) and
    localizes the trailing token. Unknown tokens fall back to the raw value.
    """
    if not raw:
        return ""
    text = raw.strip()
    if " | " in text:
        prefix, _, tail = text.rpartition(" | ")
        localized = APPROVAL_REASON_LABELS.get(tail.strip(), tail.strip())
        return f"{prefix} | {localized}"
    return APPROVAL_REASON_LABELS.get(text, text)


def _selected_dimensions(
    evaluation: dict[str, Any] | None,
) -> tuple[dict[str, float], bool | None]:
    """Dims of the SELECTED draft version plus the turn's doctrine relevance.

    A per-version item may carry its own ``evaluation`` floats (new drafts);
    legacy items fall back to the top-level dims. Doctrine relevance is a turn
    constant (same across regens) and lives at the top level.
    """
    dims = _dims_subset(evaluation)
    relevant = evaluation.get(DOCTRINE_RELEVANT_KEY) if evaluation else None
    v = read_versions(evaluation)
    items = v["items"]
    if items and isinstance(items[v["selected"]], dict):
        item_eval = items[v["selected"]].get("evaluation")
        if isinstance(item_eval, dict):
            dims = {**dims, **_dims_subset(item_eval)}
    return dims, relevant


def _render_evaluation_rows(evaluation: dict[str, Any] | None) -> list[str]:
    """One HTML row per evaluation dimension shown (bold label, value 0..1)."""
    dims, relevant = _selected_dimensions(evaluation)
    rows: list[str] = []
    for key, label in DIMENSION_LABELS_ES:
        if key == "doctrine":
            if relevant is False:
                rows.append(f"• <b>{label}:</b> {DOCTRINE_NA_LABEL}")
            elif key in dims:
                rows.append(f"• <b>{label}:</b> {dims[key]:.2f}")
            # Missing value + unknown/absent relevance → no row (fail-open shows
            # the number only when a value exists; "no aplica" only when known).
            continue
        if key in dims:
            rows.append(f"• <b>{label}:</b> {dims[key]:.2f}")
    return rows


def _mins(autonomy: dict[str, Any]) -> dict[str, float]:
    raw = autonomy.get("mins")
    if isinstance(raw, dict):
        fallback = dict(DEFAULT_AUTONOMOUS_THRESHOLDS)
        fallback.update(
            {k: float(v) for k, v in raw.items() if isinstance(v, (int, float))}
        )
        return fallback
    return dict(DEFAULT_AUTONOMOUS_THRESHOLDS)


def _draft_mins_text(
    evaluation: dict[str, Any] | None, autonomy: dict[str, Any]
) -> str:
    """Part (a): does THIS draft meet the autonomous-send minimums? Non-technical."""
    dims, relevant = _selected_dimensions(evaluation)
    if "safety" not in dims and "naturalness" not in dims:
        return ""
    mins = _mins(autonomy)
    missing: list[str] = []
    for dim_key, min_key, label in (
        ("safety", "safety_min", "seguridad"),
        ("naturalness", "naturalness_min", "naturalidad"),
    ):
        if dim_key in dims and dims[dim_key] < mins[min_key]:
            missing.append(f"{label} ({dims[dim_key]:.2f}; se pide {mins[min_key]:.2f})")
    if relevant is not False and "doctrine" in dims:
        if dims["doctrine"] < mins["doctrine_min"]:
            missing.append(
                f"doctrina ({dims['doctrine']:.2f}; se pide {mins['doctrine_min']:.2f})"
            )
    if missing:
        return "Este borrador no habría ido solo: le falta " + ", ".join(missing) + "."
    return "Este borrador sí cumpliría los mínimos para el envío autónomo."


def _category_es(category: Any) -> str:
    return _TURN_CATEGORY_ES.get(str(category), f"«{category}»")


def _join_es(items: list[str]) -> str:
    """Join Spanish words with the last separated by 'y'/'e' (2+ items)."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    *head, tail = items
    if tail.startswith(("i", "hi")):
        return ", ".join(head) + " e " + tail
    return ", ".join(head) + " y " + tail


def _vip_history_text(autonomy: dict[str, Any]) -> str:
    """Part (b): how far THIS VIP is from autonomy, in plain Spanish."""
    if not autonomy.get("has_history"):
        return "Para este VIP: aún sin historial para evaluar autonomía con este contacto."
    conf_min = float(autonomy.get("confidence_min") or 0.9)
    bullets: list[str] = []
    if not autonomy.get("meets_confidence"):
        low = [
            r
            for r in autonomy.get("trust_rows") or []
            if isinstance(r, dict)
            and _eval_float(r.get("trust_score")) is not None
            and float(r["trust_score"]) < conf_min
        ]
        cats = (
            "conversaciones "
            + _join_es(sorted({_category_es(r.get("category")) for r in low}))
            if low
            else "este tipo de conversaciones"
        )
        best = autonomy.get("best_trust")
        if best is not None and _eval_float(best) is not None:
            anchor = f" (la mejor confianza es {float(best):.2f} de {conf_min:.2f})"
        else:
            anchor = f" (se pide {conf_min:.2f})"
        bullets.append(
            f"• A Diana todavía no le alcanza la confianza en {cats} para responder "
            f"sola sin que la revises{anchor}; le faltan turnos bien resueltos sin corrección."
        )
    rate = autonomy.get("global_rate")
    match_min = float(autonomy.get("match_rate_min") or 0.95)
    if rate is None or _eval_float(rate) is None or float(rate) < match_min:
        label = (
            "todavía no hay suficientes casos"
            if _eval_float(rate) is None
            else f"está en {round(float(rate) * 100)} %"
        )
        bullets.append(
            f"• La coincidencia de Diana con tus aprobaciones {label} "
            f"(se pide {round(match_min * 100)} %)."
        )
    safety = int(autonomy.get("global_safety_escalations") or 0)
    if safety > 0:
        bullets.append(
            f"• Hay {safety} turno(s) reciente(s) que se frenaron por seguridad."
        )
    if bullets:
        return "Para este VIP: todavía no está listo para que Diana responda sola.\n" + "\n".join(
            bullets
        )
    if autonomy.get("auto_send"):
        return (
            "Para este VIP: cumple las condiciones y el envío autónomo está "
            "activado — puede enviar sola."
        )
    return (
        "Para este VIP: ya cumple las condiciones para el envío autónomo; "
        "solo falta activarlo."
    )


def _render_autonomy(evaluation: dict[str, Any] | None) -> str:
    """Autonomía section body ("" when the readiness feature was off / absent)."""
    if not isinstance(evaluation, dict):
        return ""
    autonomy = evaluation.get(AUTONOMY_KEY)
    if not isinstance(autonomy, dict):
        return ""
    blocks: list[str] = []
    draft_part = _draft_mins_text(evaluation, autonomy)
    if draft_part:
        blocks.append(draft_part)
    vip_part = _vip_history_text(autonomy)
    if vip_part:
        blocks.append(vip_part)
    return "\n".join(blocks)


def _eval_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_draft_owner_text(
    *,
    vip_name: str,
    vip_text: str,
    draft_text: str,
    reason: str,
    evaluation: dict[str, Any] | None,
    version_index: int,
    version_count: int,
) -> str:
    """HTML body for the owner draft DM (parse_mode="HTML").

    Reads everything renderable from ``evaluation`` (dims, doctrine relevance,
    per-version items, ``_autonomy`` snapshot) so the first notify and the
    regen/nav/void re-renders are byte-identical for the same record. Legacy
    records with ``evaluation=None`` degrade to header + blocks only.
    """

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    effective_reason = reason or _selected_reason(evaluation)
    localized = localize_reason(effective_reason)

    header = (
        f"<b>Propuesta de respuesta para {esc(vip_name)}</b>"
        f" — <i>borrador {version_index + 1}/{version_count}</i>"
    )
    lines = [
        header,
        "",
        "<b>[usuario]</b>",
        esc(vip_text) or "",
        "",
        "<b>[propuesta]</b>",
        esc(draft_text) or "",
    ]
    if localized:
        lines += ["", f"<b>Motivo:</b> {esc(localized)}"]
    eval_rows = _render_evaluation_rows(evaluation)
    if eval_rows:
        lines += ["", "<b>Evaluación</b>", *eval_rows]
    autonomy_block = _render_autonomy(evaluation)
    if autonomy_block:
        lines += ["", "<b>Autonomía</b>", autonomy_block]
    return "\n".join(lines)


def _selected_reason(evaluation: dict[str, Any] | None) -> str:
    """Fallback reason from the selected draft version ("" when unavailable)."""
    v = read_versions(evaluation)
    items = v["items"]
    if not items or not isinstance(items[v["selected"]], dict):
        return ""
    return str(items[v["selected"]].get("reason") or "")


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
        feature_quality_feedback_enabled: bool = False,
    ) -> None:
        self._approvals = approvals
        self._turns = turns
        self._director = director
        self._notifier = notifier
        self._owner_telegram_id = owner_telegram_id
        self._history = history
        self._vips = vips
        self._max = max(1, int(max_variants))
        self._feature_quality_feedback_enabled = bool(
            feature_quality_feedback_enabled
        )

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
            new_item: dict[str, Any] = {
                "text": draft,
                "reason": decision.reason or "",
            }
            if decision.evaluation is not None:
                per_version = _dims_subset(decision.evaluation.model_dump(mode="json"))
                if per_version:
                    new_item["evaluation"] = per_version
            items.append(new_item)
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
                show_quality_feedback=(
                    self._feature_quality_feedback_enabled
                    and approval.vip_id is not None
                ),
            )
        except Exception:
            logger.exception(
                "draft_variant_edit_failed",
                extra={"turn_id": str(approval.turn_id)},
            )


__all__ = [
    "APPROVAL_REASON_LABELS",
    "AUTONOMY_KEY",
    "DOCTRINE_NA_LABEL",
    "DOCTRINE_RELEVANT_KEY",
    "DIMENSION_LABELS_ES",
    "MAX_DRAFT_VARIANTS",
    "VERSIONS_KEY",
    "DraftVariantService",
    "RegeneratingCallback",
    "VariantNavResult",
    "build_owner_draft_text",
    "ensure_versions",
    "format_draft_owner_text",
    "localize_reason",
    "read_versions",
    "resolve_vip_display_name",
    "selected_text",
]
