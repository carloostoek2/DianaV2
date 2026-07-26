"""AdminMetricsService — owner DM weekly learning summary (SPEC §7.3).

Read-only over LearningMetricsStore. Formats Spanish operational text with
week-over-week deltas. No aggregation logic (Item 2 owns that).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from diana.application.metrics_service import (
    LearningMetricsStore,
    previous_complete_week_start,
)

logger = logging.getLogger("diana.application")

__all__ = [
    "AdminMetricsService",
    "MetricsSummary",
    "format_count_delta",
    "format_rate_delta",
    "format_week_range_label",
]

_TELEGRAM_MSG_CAP = 4096
_DRIFT_NORMAL_MAX = 0.1  # score < 0.1 → normal; else alto


@dataclass
class MetricsSummary:
    """Week metrics snapshot for owner dashboard formatting."""

    week_start: date
    week_end: date  # inclusive display end (Monday + 6 days)
    values: dict[str, float]
    previous: dict[str, float]
    status: str  # ok | empty


def format_week_range_label(week_start: date, week_end: date) -> tuple[str, str]:
    """Return (dd/mm, dd/mm) for the week range header."""
    return week_start.strftime("%d/%m"), week_end.strftime("%d/%m")


def format_rate_delta(new: float, old: float | None) -> str:
    """Absolute percentage-point delta for rates stored as 0–1 fractions."""
    if old is None:
        return ""
    delta_pp = round((float(new) - float(old)) * 100)
    if delta_pp == 0:
        return ""
    arrow = "↑" if delta_pp > 0 else "↓"
    return f" ({arrow} {abs(delta_pp)}% vs semana anterior)"


def format_count_delta(new: float, old: float | None) -> str:
    """Relative percent delta for counts; omit when previous missing or zero."""
    if old is None or float(old) <= 0:
        return ""
    rel = round(((float(new) - float(old)) / float(old)) * 100)
    if rel == 0:
        return ""
    arrow = "↑" if rel > 0 else "↓"
    return f" ({arrow} {abs(rel)}%)"


def _drift_label(score: float) -> str:
    if float(score) < _DRIFT_NORMAL_MAX:
        return "normal"
    return "alto — revisá las últimas conversaciones"


def _as_int(value: float | int | None, default: int = 0) -> int:
    if value is None:
        return default
    return int(round(float(value)))


def _prev_value(previous: dict[str, float], key: str) -> float | None:
    if not previous or key not in previous:
        return None
    return float(previous[key])


def _false_positive_count(values: dict[str, float]) -> int:
    """Prefer explicit count; rate 0.0 → 0; else rate-only residual shows 0."""
    if "false_positive_escalation_count" in values:
        return _as_int(values["false_positive_escalation_count"])
    rate = float(values.get("false_positive_escalation_rate", 0.0))
    if rate == 0.0:
        return 0
    # No escalations denominator in store (Item 2 residual) — honest zero-ish
    # display only when count metric absent and rate non-zero is rare.
    return 0


class AdminMetricsService:
    """Format weekly learning metrics for the owner DM dashboard."""

    def __init__(
        self,
        store: LearningMetricsStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    def previous_complete_week_start(self, now: datetime | None = None) -> date:
        return previous_complete_week_start(
            now if now is not None else self._clock()
        )

    async def get_week_summary(
        self, week_start: date | None = None
    ) -> MetricsSummary:
        if week_start is None:
            week_start = self.previous_complete_week_start()
        week_end = week_start + timedelta(days=6)
        values = await self._store.get_week(week_start)
        previous = await self._store.get_previous_week(week_start)
        status = "empty" if not values else "ok"
        return MetricsSummary(
            week_start=week_start,
            week_end=week_end,
            values=dict(values),
            previous=dict(previous or {}),
            status=status,
        )

    def format_summary_text(self, summary: MetricsSummary) -> str:
        start_lbl, end_lbl = format_week_range_label(
            summary.week_start, summary.week_end
        )
        if summary.status == "empty" or not summary.values:
            return (
                f"Sin métricas para la semana del {start_lbl} al {end_lbl} "
                f"(aún no hay agregación)."
            )

        v = summary.values
        prev = summary.previous

        total = _as_int(v.get("total_turns", 0))
        approval_rate = float(v.get("approval_without_correction_rate", 0.0))
        approval_pct = int(round(approval_rate * 100))
        approval_delta = format_rate_delta(
            approval_rate, _prev_value(prev, "approval_without_correction_rate")
        )

        gray = _as_int(v.get("gray_zone_repetition_count", 0))

        fp_count = _false_positive_count(v)
        fp_delta = ""
        if "false_positive_escalation_count" in prev or (
            "false_positive_escalation_count" in v and prev
        ):
            old_fp = (
                _as_int(prev["false_positive_escalation_count"])
                if "false_positive_escalation_count" in prev
                else None
            )
            fp_delta = format_count_delta(float(fp_count), float(old_fp) if old_fp is not None else None)
        elif prev and "false_positive_escalation_rate" in prev:
            # Rate-only residual: relative on rate if both non-zero; else omit
            old_rate = float(prev.get("false_positive_escalation_rate", 0.0))
            new_rate = float(v.get("false_positive_escalation_rate", 0.0))
            if old_rate > 0:
                fp_delta = format_count_delta(new_rate, old_rate)

        drift = float(v.get("style_drift_score", 0.0))
        drift_lbl = _drift_label(drift)

        auto_rate = float(v.get("autonomous_send_rate", 0.0))
        if "autonomous_send_count" in v:
            auto_count = _as_int(v["autonomous_send_count"])
        else:
            auto_count = int(round(auto_rate * total)) if total else 0
        auto_pct = int(round(auto_rate * 100))

        promo_sent = _as_int(v.get("promo_sent_count", 0))
        promo_unique = _as_int(v.get("promo_unique_chats", 0))
        promo_repeat = _as_int(v.get("promo_repeat_count", 0))

        lines = [
            f"📊 Resumen de aprendizaje (semana del {start_lbl} al {end_lbl}):",
            f"- Turnos totales: {total}",
            f"- Aprobación sin corrección: {approval_pct}%{approval_delta}",
            f"- Repetición de zona gris: {gray}",
            f"- Falsos positivos de escalación: {fp_count}{fp_delta}",
            f"- Drift de estilo: {drift:.2f} ({drift_lbl})",
            f"- Envíos autónomos: {auto_count} ({auto_pct}% del total)",
            f"- Promos enviadas: {promo_sent} (únicos: {promo_unique}, "
            f"repetidos: {promo_repeat})",
        ]
        return "\n".join(lines)

    async def export_week_json(self, week_start: date | None = None) -> str:
        summary = await self.get_week_summary(week_start)
        payload: dict[str, Any] = {
            "week_start": summary.week_start.isoformat(),
            "week_end": summary.week_end.isoformat(),
            "status": summary.status,
            "metrics": summary.values,
            "previous": summary.previous,
        }
        raw = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        if len(raw) <= _TELEGRAM_MSG_CAP:
            return raw
        note = "\n\n… [truncated — export exceeds Telegram 4096 cap]"
        budget = _TELEGRAM_MSG_CAP - len(note)
        return raw[: max(0, budget)] + note
