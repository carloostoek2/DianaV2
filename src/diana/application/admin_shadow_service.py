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
- ``render_drafts`` — the most recent turns where the fast-lane would have
  auto-sent, with the message it would have delivered.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from diana.application.mexico_tz import cdmx_local_date

logger = logging.getLogger("diana.application")

__all__ = [
    "AdminShadowService",
    "ShadowThresholds",
]

_DEFAULT_TRUST_MIN = 0.90
_DEFAULT_CLASSIFIER_CONFIDENCE_MIN = 0.70
_DRAFT_TEXT = "Holis 😁"
_SUMMARY_DAYS = 7
_DRAFTS_LIMIT = 10

_TRUST_OK = "✅ cumple"
_TRUST_BELOW = "⏳ en camino"


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

    async def daily_counts(self, days: int) -> list[dict]: ...


class TrustBudgetShadowReader(Protocol):
    """Reads per-(VIP, category) trust budgets (repo subset)."""

    async def list_all(self) -> list[Any]: ...


class VipNameReader(Protocol):
    """Provides VIP display names (repo subset)."""

    async def list_active(self) -> list[Any]: ...


class AdminShadowService:
    """Formats shadow-mode evidence for the owner menu (read-only)."""

    def __init__(
        self,
        *,
        turn_categories: TurnCategoryShadowReader,
        trust_budget: TrustBudgetShadowReader,
        vips: VipNameReader,
        thresholds: ShadowThresholds | None = None,
    ) -> None:
        self._turn_categories = turn_categories
        self._trust_budget = trust_budget
        self._vips = vips
        self._thresholds = thresholds or ShadowThresholds()

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

    async def render_drafts(self, limit: int = _DRAFTS_LIMIT) -> str:
        """The most recent turns where the fast-lane would have auto-sent."""
        try:
            rows = await self._turn_categories.list_would_autonomous(limit)
            vips = await self._vips.list_active()
        except Exception:
            logger.exception("shadow_drafts_read_failed")
            return _unavailable("mensajes que habría enviado")

        names = {v.id: (v.display_name or str(v.telegram_user_id)) for v in vips}
        lines = [
            "🤖 Modo sombra — Mensajes que habría enviado",
            "",
            "Últimos turnos donde Diana habría enviado sola "
            "(medición, nunca envío real):",
        ]
        if not rows:
            lines += ["", "Todavía no hay turnos donde habría enviado sola."]
            return "\n".join(lines)

        for i, row in enumerate(rows, 1):
            name = names.get(row.vip_id, str(row.vip_id)[:8]) if row.vip_id else "?"
            when = _fmt_day(row.created_at)
            conf = (
                f"{row.confidence:.2f}"
                if row.confidence is not None
                else "—"
            )
            lines += [
                "",
                f"{i}. {when} · {name} · {row.category} "
                f"(conf. {conf})",
                f'   Habría enviado: "{self._thresholds.draft_text}"',
            ]
        return "\n".join(lines)


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
