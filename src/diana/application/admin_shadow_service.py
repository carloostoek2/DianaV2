"""AdminShadowService — owner consult surface for shadow mode (read-only).

The evo-agente shadow layer measures every VIP turn (classifier, emotional
signal, mood, trust budget, profile synthesis) without changing any decision.
This service renders owner-facing views of that accumulated evidence so the
owner can check, on demand, how the system is evolving — no notifications,
no writes.

Views (all neutral Mexican Spanish):
- ``render_summary`` — global counts, last-7-day trend, current thresholds and
  the would-be autonomous message.
- ``render_by_vip`` — trust score vs. threshold per VIP and turn category,
  with the "autónomos" (would-have-sent) counter.
- ``render_decisions`` — recent turns with the generated draft (the same
  message the owner approves), the shadow verdict and WHY the fast-lane would
  or would not have sent alone, plus the trust gate when applicable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from diana.application.mexico_tz import cdmx_local_date
from diana.cognitive.models import Comprehension, EvaluationProfile

logger = logging.getLogger("diana.application")

__all__ = [
    "AdminShadowService",
    "ShadowThresholds",
]

_DEFAULT_TRUST_MIN = 0.90
_DEFAULT_CLASSIFIER_CONFIDENCE_MIN = 0.70
_DRAFT_TEXT = "Holis 😁"
_SUMMARY_DAYS = 7
_DECISIONS_LIMIT = 10

_TRUST_OK = "✅ cumple"
_TRUST_BELOW = "⏳ en camino"

# Decisor reasons → owner-facing labels (full-autonomy simulation).
_ESCALATE_LABELS = {
    "safety_below_threshold": "seguridad por debajo del mínimo",
    "risk_high": "riesgo alto en la conversación",
    "frustracion_directa": "el VIP está molesta",
}
_REAL_DECISION_LABELS = {
    "send": "enviar sola",
    "approve": "aprobar (revisión de la dueña)",
    "escalate": "escalar",
    "consult_doctrine": "consultar doctrina",
}


@dataclass(frozen=True)
class ShadowThresholds:
    """Thresholds shown next to the shadow evidence (measurement targets).

    Values mirror the runtime defaults: the trust budget double-gate
    (``DEFAULT_TRUST_BUDGET_THRESHOLD``) and the classifier confidence floor
    (``classifier_confidence_min``). They are displayed as reference, never
    used to decide anything here.
    """

    trust_min: float = _DEFAULT_TRUST_MIN
    classifier_confidence_min: float = _DEFAULT_CLASSIFIER_CONFIDENCE_MIN
    draft_text: str = _DRAFT_TEXT


class TurnCategoryShadowReader(Protocol):
    """Reads the shadow turn classifications (repo subset)."""

    async def list_would_autonomous(self, limit: int) -> list[Any]: ...

    async def list_recent_with_draft(self, limit: int) -> list[dict]: ...

    async def daily_counts(self, days: int) -> list[dict]: ...


class TrustBudgetShadowReader(Protocol):
    """Reads per-(VIP, category) trust budgets (repo subset)."""

    async def list_all(self) -> list[Any]: ...


class VipNameReader(Protocol):
    """Provides VIP display names (repo subset)."""

    async def list_active(self) -> list[Any]: ...


class AdminShadowService:
    """Formats shadow-mode evidence for the owner menu (read-only).

    ``decider`` is a cognitive Decider built with ``feature_autonomous_mode
    =True`` (the real decision matrix with the autonomy switch on): every
    stored turn is re-decided with it, so the view answers "what would Diana
    have done with full autonomy on this real message?" — the calibration
    surface the owner asked for.
    """

    def __init__(
        self,
        *,
        turn_categories: TurnCategoryShadowReader,
        trust_budget: TrustBudgetShadowReader,
        vips: VipNameReader,
        thresholds: ShadowThresholds | None = None,
        decider: Any | None = None,
    ) -> None:
        self._turn_categories = turn_categories
        self._trust_budget = trust_budget
        self._vips = vips
        self._thresholds = thresholds or ShadowThresholds()
        self._decider = decider

    async def render_summary(self) -> str:
        """Global view: totals, 7-day trend and thresholds."""
        try:
            counts = await self._turn_categories.daily_counts(_SUMMARY_DAYS)
            trust_rows = await self._trust_budget.list_all()
        except Exception:
            logger.exception("shadow_summary_read_failed")
            return _unavailable("resumen")

        total_turns = sum(int(row.get("total") or 0) for row in counts)
        total_would = sum(int(row.get("autonomous") or 0) for row in counts)
        total_corrections = sum(
            int(getattr(r, "correction_count", 0) or 0) for r in trust_rows
        )
        last_at = max((row.get("day") for row in counts), default=None)
        last_label = _fmt_day(last_at) if last_at else "—"

        lines = [
            "🤖 Modo sombra — Resumen",
            "",
            "Diana mide cada conversación sin cambiar sus decisiones. "
            "Todo lo que ves aquí es registro, no acción.",
        ]
        if counts:
            lines += ["", f"📈 Últimos {_SUMMARY_DAYS} días:"]
            for row in reversed(counts[-_SUMMARY_DAYS:]):
                day = row.get("day")
                total = int(row.get("total") or 0)
                would = int(row.get("autonomous") or 0)
                mark = f" · {would} habría enviado" if would else ""
                lines.append(f"  {_fmt_day(day)} — {total} turnos{mark}")
        lines += [
            "",
            f"Totales: {total_turns} turnos medidos · {total_would} habría "
            f"enviado sola · {total_corrections} correcciones de la dueña",
            "",
            "🎚 Umbrales actuales:",
            f"  Confianza para enviar sola: {self._thresholds.trust_min:.2f}",
            f"  Confianza del clasificador: "
            f"{self._thresholds.classifier_confidence_min:.2f}",
            f'  Mensaje que habría enviado: "{self._thresholds.draft_text}"',
            "",
            f"Última medición: {last_label}",
        ]
        return "\n".join(lines)

    async def render_by_vip(self) -> str:
        """Per-VIP trust vs. threshold with the 'autónomos' counter."""
        try:
            trust_rows = await self._trust_budget.list_all()
            vips = await self._vips.list_active()
        except Exception:
            logger.exception("shadow_by_vip_read_failed")
            return _unavailable("por VIP")

        names = {v.id: (v.display_name or str(v.telegram_user_id)) for v in vips}
        by_vip: dict[Any, list[Any]] = {}
        for row in trust_rows:
            by_vip.setdefault(row.vip_id, []).append(row)

        lines = [
            "🤖 Modo sombra — Por VIP",
            "",
            "Confianza por tipo de turno, comparada con el umbral para "
            f"enviar sola ({self._thresholds.trust_min:.2f}):",
        ]
        if not by_vip:
            lines += ["", "Todavía no hay confianza medida para ningún VIP."]
            return "\n".join(lines)

        for vip_id, rows in sorted(
            by_vip.items(), key=lambda item: _vip_sort_key(item[1], names)
        ):
            name = names.get(vip_id, str(vip_id)[:8])
            lines.append(f"\n👤 {name}")
            for row in sorted(rows, key=lambda r: r.turn_category):
                meets = (
                    _TRUST_OK
                    if float(row.trust_score) >= self._thresholds.trust_min
                    else _TRUST_BELOW
                )
                lines.append(
                    f"  • [{row.turn_category}] {row.trust_score:.2f} · "
                    f"autónomos {row.autonomous_count} · "
                    f"correcciones {row.correction_count} · {meets}"
                )
        return "\n".join(lines)

    async def render_decisions(self, limit: int = _DECISIONS_LIMIT) -> str:
        """Recent turns: draft + full-autonomy shadow verdict + reasons.

        Each entry re-runs the REAL Decisor (with the autonomy switch on)
        over the turn's stored evaluation/comprehension, so the owner sees
        what would have happened under full autonomy: sent alone (thresholds
        met), blocked by a threshold, escalated, or pending doctrine — plus
        the trust gate per (VIP, category) that "opens" autonomy as it is
        earned. The generated draft is the same message the owner approves.
        """
        try:
            rows = await self._turn_categories.list_recent_with_draft(limit)
            trust_rows = await self._trust_budget.list_all()
            vips = await self._vips.list_active()
        except Exception:
            logger.exception("shadow_decisions_read_failed")
            return _unavailable("borradores y decisiones")

        names = {v.id: (v.display_name or str(v.telegram_user_id)) for v in vips}
        trust_by_key = {
            (r.vip_id, r.turn_category): float(r.trust_score) for r in trust_rows
        }
        trust_min = self._thresholds.trust_min

        lines = [
            "🤖 Modo sombra — Borradores y decisiones",
            "",
            "Simulación con autonomía total: cada turno real se re-decide "
            "con el Decisor y el interruptor de autonomía ENCENDIDO. El "
            "borrador es el mismo que te llega para aprobar.",
        ]
        if not rows:
            lines += ["", "Todavía no hay turnos medidos."]
            return "\n".join(lines)

        for i, row in enumerate(rows, 1):
            name = names.get(row["vip_id"], str(row["vip_id"])[:8]) if row.get(
                "vip_id"
            ) else "?"
            when = _fmt_day(row["created_at"])
            category = row.get("category") or "?"
            confidence = row.get("confidence")
            conf_label = f"{confidence:.2f}" if confidence is not None else "—"
            draft = (row.get("draft") or "").strip()

            lines.append(
                f"\n{i}. {when} · {name} · {category} (conf. {conf_label})"
            )
            lines.extend(
                self._full_autonomy_lines(row, trust_by_key, trust_min)
            )
            if draft:
                lines.append(f'   Borrador generado: "{draft}"')
            else:
                lines.append("   (sin borrador guardado en este turno)")
        return "\n".join(lines)

    def _full_autonomy_lines(
        self, row: dict, trust_by_key: dict, trust_min: float
    ) -> list[str]:
        """Re-decide one stored turn with the real Decider (autonomy ON)."""
        if self._decider is None:
            return ["   (simulación no disponible)"]

        evaluation_dict = row.get("evaluation")
        comprehension_dict = row.get("comprehension")
        if not evaluation_dict or not comprehension_dict:
            return [
                "   — sin evaluación guardada en este turno "
                "(plantilla o pipeline cortado)"
            ]
        try:
            evaluation = EvaluationProfile.model_validate(evaluation_dict)
            comprehension = Comprehension.model_validate(comprehension_dict)
        except Exception:
            logger.warning(
                "shadow_evaluation_unparseable",
                extra={"turn_id": str(row.get("turn_id"))},
            )
            return ["   — evaluación no legible para simular el veredicto"]

        decision = self._decider.decide(
            evaluation,
            comprehension,
            retrieved=row.get("retrieved") or {},
        )

        # Real outcome reference (what the pipeline actually decided).
        real = row.get("decision") or {}
        real_label = _REAL_DECISION_LABELS.get(
            real.get("action"), str(real.get("action") or "?")
        )
        lines = [f"   Decisión real: {real_label}"]
        lines.append(
            f"   Seguridad {evaluation.safety:.2f} · doctrina "
            f"{evaluation.doctrine:.2f} · naturalidad "
            f"{evaluation.naturalness:.2f}"
        )

        if decision.action == "send":
            lines.append("   ✅ CON AUTONOMÍA TOTAL: habría enviado sola")
        elif decision.action == "escalate":
            reason = _ESCALATE_LABELS.get(decision.reason, decision.reason)
            lines.append(
                f"   ❌ Con autonomía: no habría enviado — {reason}"
            )
        elif decision.action == "consult_doctrine":
            lines.append(
                "   ❌ Con autonomía: no habría enviado — doctrina "
                "pendiente (zona gris)"
            )
        else:  # approve (autonomous_below_threshold)
            lines.append("   ❌ Con autonomía: no habría enviado — umbrales no alcanzados:")
            safety_min, doctrine_min, naturalness_min = self._decider.autonomous_mins()
            for label, value, minv in (
                ("Seguridad", evaluation.safety, safety_min),
                ("Doctrina", evaluation.doctrine, doctrine_min),
                ("Naturalidad", evaluation.naturalness, naturalness_min),
            ):
                mark = "✅" if value >= minv else "❌"
                lines.append(f"     {label} {value:.2f} vs {minv:.2f} {mark}")

        # The "earning" gate: per-(VIP, category) trust opens autonomy.
        trust = trust_by_key.get((row.get("vip_id"), row.get("category")))
        if trust is not None:
            mark = _TRUST_OK if trust >= trust_min else _TRUST_BELOW
            lines.append(
                f"   Confianza {trust:.2f} vs {trust_min:.2f}: {mark} "
                "(así se va abriendo la autonomía por VIP)"
            )
        lines.append(
            "   Nota: el interruptor maestro está apagado — nada se "
            "envía sola hoy, solo se mide."
        )
        return lines


def _fmt_day(value: date | datetime | None) -> str:
    if value is None:
        return "—"
    d = cdmx_local_date(value) if isinstance(value, datetime) else value
    return d.strftime("%d/%m")


def _vip_sort_key(rows: list[Any], names: dict[Any, str]) -> tuple[float, str]:
    """Sort VIPs by their best trust score desc, then by name."""
    best = max((float(r.trust_score) for r in rows), default=0.0)
    name = ""
    if rows:
        name = names.get(rows[0].vip_id, "")
    return (-best, name.lower())


def _unavailable(view: str) -> str:
    return (
        f"🤖 Modo sombra — {view}\n\n"
        "No se pudo leer la información en este momento. "
        "Intenta de nuevo en unos segundos."
    )
