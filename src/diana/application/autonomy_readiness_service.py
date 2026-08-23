"""AutonomyReadinessService — Fila 4 panel (C5) + recommendation gate (C6).

SPEC-AUTONOMIA-CALIBRACION.md §5 C5/C6. Renders the owner's single view of
"Camino a la autonomía" (global preparation, comparativas, per-VIP readiness)
and evaluates the §8 recommendation gate:

1. confianza del VIP ≥ 0.90 (por categoría; el botón es por VIP → se usa el
   mejor trust_score del VIP),
2. coincidencia global ≥ 95 % en la ventana,
3. cero escalaciones por seguridad en la ventana.

The activation button writes ``vips.auto_send`` (L2 of the existing double
gate) — the master kill-switch ``FEATURE_AUTONOMOUS_MODE`` keeps governing the
real send. Read-only for everything else (C5); never sends, never decides.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from diana.application.outcome_log_service import OutcomeLogService
from diana.application.ports import VipStore

logger = logging.getLogger("diana.application")

__all__ = ["AutonomyReadinessService", "VipReadiness"]

# Telegram message cap: keep each rendered view bounded.
_MAX_VIPS_PER_VIEW = 10


class TrustBudgetReader(Protocol):
    """Per-(VIP, category) trust rows for the readiness view (repo subset)."""

    async def list_all(self) -> list[Any]: ...


class VipReadiness:
    """Per-VIP readiness summary (C5 "por VIP" + C6 recommendation input)."""

    __slots__ = (
        "vip_id",
        "display_name",
        "best_trust",
        "trust_rows",
        "auto_send",
        "meets_confidence",
        "global_rate",
        "global_safety_escalations",
        "ready",
    )

    def __init__(
        self,
        *,
        vip_id: UUID,
        display_name: str,
        auto_send: bool,
        best_trust: float,
        trust_rows: list[dict],
        global_rate: float | None,
        global_safety_escalations: int,
        confidence_min: float,
        match_rate_min: float,
    ) -> None:
        self.vip_id = vip_id
        self.display_name = display_name
        self.auto_send = auto_send
        self.best_trust = best_trust
        self.trust_rows = trust_rows
        self.global_rate = global_rate
        self.global_safety_escalations = global_safety_escalations
        self.meets_confidence = best_trust >= confidence_min
        self.ready = bool(
            self.meets_confidence
            and global_rate is not None
            and global_rate >= match_rate_min
            and global_safety_escalations == 0
        )


class AutonomyReadinessService:
    """Fila 4 C5/C6: evidence panel + per-VIP activation recommendation.

    ``outcome`` is the shared :class:`OutcomeLogService` (source comparativas +
    the persistent log when Fase B is on). ``trust`` is the per-(VIP, category)
    budget reader (repo subset). ``vips`` must expose ``set_auto_send``.
    """

    def __init__(
        self,
        *,
        outcome: OutcomeLogService,
        trust: TrustBudgetReader,
        vips: VipStore,
        window_days: int = 14,
        confidence_min: float = 0.9,
        match_rate_min: float = 0.95,
        recommendation_enabled: bool = False,
        clock: Any | None = None,
    ) -> None:
        self._outcome = outcome
        self._trust = trust
        self._vips = vips
        self._window_days = max(1, int(window_days))
        self._confidence_min = float(confidence_min)
        self._match_rate_min = float(match_rate_min)
        self._recommendation_enabled = bool(recommendation_enabled)
        self._clock = clock or (lambda: datetime.now(UTC))

    # ------------------------------------------------------------------
    # evidence
    # ------------------------------------------------------------------

    async def _summary(self) -> dict[str, Any]:
        summary = await self._outcome.coincidence_summary(
            window_days=self._window_days
        )
        rows = await self._outcome.list_comparativas(
            window_days=self._window_days, limit=500
        )
        # Safety escalations come from the re-decided comparativas (works in
        # Fase A on-the-fly AND Fase B) — a turn re-decided as escalate with
        # reason safety_below_threshold.
        safety = sum(
            1 for r in rows if r.shadow_reason == "safety_below_threshold"
        )
        bottlenecks: Counter[str] = Counter()
        for row in rows:
            for dim in row.extra.get("blocked_dims") or []:
                bottlenecks[str(dim)] += 1
        return {
            "summary": summary,
            "safety_escalations": safety,
            "bottlenecks": dict(bottlenecks.most_common()),
            "window_days": self._window_days,
            "match_rate_min": self._match_rate_min,
            "confidence_min": self._confidence_min,
        }

    async def _by_vip(self) -> list[VipReadiness]:
        trust_rows = await self._trust.list_all()
        vips = await self._vips.list_active()
        summary = await self._outcome.coincidence_summary(
            window_days=self._window_days
        )
        comparativas = await self._outcome.list_comparativas(
            window_days=self._window_days, limit=500
        )
        safety = sum(
            1 for r in comparativas if r.shadow_reason == "safety_below_threshold"
        )
        rate = summary.get("rate")

        names = {v.id: (v.display_name or str(v.telegram_user_id)) for v in vips}
        auto_send = {v.id: bool(v.auto_send) for v in vips}
        by_vip: dict[UUID, list[Any]] = {}
        for row in trust_rows:
            by_vip.setdefault(row.vip_id, []).append(row)

        out: list[VipReadiness] = []
        for vip in vips:
            rows = by_vip.get(vip.id, [])
            trust_view = [
                {
                    "category": r.turn_category,
                    "trust_score": float(r.trust_score),
                    "autonomous_count": int(r.autonomous_count or 0),
                    "correction_count": int(r.correction_count or 0),
                }
                for r in rows
            ]
            best = max((float(r.trust_score) for r in rows), default=0.0)
            out.append(
                VipReadiness(
                    vip_id=vip.id,
                    display_name=names.get(vip.id, str(vip.id)[:8]),
                    auto_send=auto_send.get(vip.id, False),
                    best_trust=best,
                    trust_rows=trust_view,
                    global_rate=rate,
                    global_safety_escalations=safety,
                    confidence_min=self._confidence_min,
                    match_rate_min=self._match_rate_min,
                )
            )
        out.sort(key=lambda item: (not item.ready, -item.best_trust, item.display_name))
        return out

    # ------------------------------------------------------------------
    # C6 — recommendation + activation
    # ------------------------------------------------------------------

    async def list_readiness(self) -> list[VipReadiness]:
        """Per-VIP readiness (C5 "por VIP"); the panel renders it."""
        return await self._by_vip()

    async def recommendation(self, vip_id: UUID) -> VipReadiness | None:
        """Evaluate the §8 gate for one VIP (all three conditions at once)."""
        for readiness in await self._by_vip():
            if readiness.vip_id == vip_id:
                return readiness
        return None

    async def activate(self, vip_id: UUID) -> tuple[bool, str]:
        """Enable ``vips.auto_send`` ONLY when the §8 gate is met.

        The double gate stays: L1 ``FEATURE_AUTONOMOUS_MODE`` (master
        kill-switch) + L2 ``auto_send`` still govern the real send.
        """
        if not self._recommendation_enabled:
            return False, (
                "La recomendación de autonomía está desactivada "
                "(feature_autonomy_recommendation_enabled)."
            )
        readiness = await self.recommendation(vip_id)
        if readiness is None:
            return False, "No se encontró el VIP."
        if not readiness.ready:
            return False, self._not_ready_reason(readiness)
        await self._vips.set_auto_send(vip_id, True)
        logger.info(
            "autonomy_activated",
            extra={"vip_id": str(vip_id), "best_trust": readiness.best_trust},
        )
        return True, f"Activado el envío autónomo para {readiness.display_name}."

    async def deactivate(self, vip_id: UUID) -> tuple[bool, str]:
        """Rollback: turn ``auto_send`` off for the VIP (no redeploy needed)."""
        await self._vips.set_auto_send(vip_id, False)
        logger.info("autonomy_deactivated", extra={"vip_id": str(vip_id)})
        return True, "Apagado el envío autónomo para el VIP."

    def _not_ready_reason(self, readiness: VipReadiness) -> str:
        reasons: list[str] = []
        if not readiness.meets_confidence:
            reasons.append(
                f"confianza {readiness.best_trust:.2f} < {self._confidence_min:.2f}"
            )
        if readiness.global_rate is None or readiness.global_rate < self._match_rate_min:
            rate = (
                "sin datos"
                if readiness.global_rate is None
                else f"{readiness.global_rate:.0%}"
            )
            reasons.append(f"coincidencia global {rate} < {self._match_rate_min:.0%}")
        if readiness.global_safety_escalations > 0:
            reasons.append(
                f"{readiness.global_safety_escalations} escalación(es) de seguridad"
            )
        return "Faltan: " + " · ".join(reasons) + "."

    # ------------------------------------------------------------------
    # C5 — owner panel rendering (Telegram-safe, neutral Spanish)
    # ------------------------------------------------------------------

    async def render_global(self) -> str:
        data = await self._summary()
        summary = data["summary"]
        rate = summary.get("rate")
        rate_label = "sin datos" if rate is None else f"{rate:.0%}"
        match_ok = rate is not None and rate >= self._match_rate_min
        lines = [
            "🧭 Camino a la autonomía — Preparación global",
            "",
            "Diana mide si puede enviar sola por VIP. Esto es evidencia, "
            "no una decisión: nada cambia hasta que tú lo actives.",
            "",
            f"📈 Coincidencia (ventana {data['window_days']} días): "
            f"{rate_label} · meta {self._match_rate_min:.0%} "
            f"{'✅' if match_ok else '⏳'}",
            (
                f"   ({summary['aciertos']} aciertos · "
                f"{summary['desacuerdos']} desacuerdos · "
                f"{summary['conservadora']} conservadoras)"
            ),
            f"🔒 Escalaciones por seguridad: {data['safety_escalations']} "
            f"{'✅' if data['safety_escalations'] == 0 else '⛔'}",
        ]
        if data["bottlenecks"]:
            lines.append("🚧 Cuellos por dimensión (turnos bloqueados):")
            for dim, count in list(data["bottlenecks"].items())[:5]:
                lines.append(f"   • {dim}: {count}")
        lines += [
            "",
            "💬 Comparativas y ⚖️ Por VIP: usa los botones de abajo.",
            "",
            "La activación solo es posible cuando se cumplen las tres "
            "condiciones (confianza ≥ 0.90 · coincidencia ≥ 95 % · "
            "cero escalaciones de seguridad).",
        ]
        return "\n".join(lines)

    async def render_comparativas(self) -> str:
        summary = await self._outcome.coincidence_summary(
            window_days=self._window_days
        )
        rate = summary.get("rate")
        rate_label = "sin datos" if rate is None else f"{rate:.0%}"
        casos = summary["aciertos"] + summary["desacuerdos"]
        lines = [
            "🧭 Camino a la autonomía — Comparativas",
            "",
            f"Coincidencia: {rate_label} "
            f"({summary['aciertos']} aciertos / {casos or 1} casos de envío)",
        ]
        disagreements = summary["desacuerdos_list"][:_MAX_VIPS_PER_VIEW]
        if not disagreements:
            lines += ["", "Sin desacuerdos recientes. ✨"]
        else:
            lines += ["", "Los desacuerdos son los casos de oro (la simulación "
                           "habría enviado y la dueña corrigió):"]
            for row in disagreements:
                when = (
                    row.created_at.strftime("%d/%m")
                    if row.created_at is not None
                    else "?"
                )
                draft = (row.draft or "")[:120]
                corrected = (row.corrected_text or "")[:120]
                lines.append(f"\n• {when}:")
                if draft:
                    lines.append(f"   Borrador: \"{draft}\"")
                if corrected:
                    lines.append(f"   Corrección: \"{corrected}\"")
        lines.append(
            "\nLa tendencia del delta de calidad (cuando está activa la "
            "medición de calidad) se revisa en la vista global."
        )
        return "\n".join(lines)

    async def render_by_vip(self) -> str:
        readiness_list = await self._by_vip()
        lines = [
            "🧭 Camino a la autonomía — Por VIP",
            "",
            "Quién está listo (✅) y a quién le falta cuánto (⏳). El botón "
            "activa el envío autónomo solo si se cumplen las 3 condiciones.",
        ]
        if not readiness_list:
            lines += ["", "Todavía no hay VIPs medidos."]
            return "\n".join(lines)
        shown = readiness_list[:_MAX_VIPS_PER_VIEW]
        for item in shown:
            state = "✅ LISTO" if item.ready else "⏳ en camino"
            send = " · envío autónomo ON" if item.auto_send else ""
            lines.append(f"\n👤 {item.display_name} — {state}{send}")
            if item.trust_rows:
                for t in sorted(item.trust_rows, key=lambda d: d["category"]):
                    lines.append(
                        f"   • [{t['category']}] {t['trust_score']:.2f} "
                        f"(autónomos {t['autonomous_count']} · "
                        f"correcciones {t['correction_count']})"
                    )
            else:
                lines.append("   (sin confianza medida todavía)")
            if not item.ready:
                lines.append(f"   {self._not_ready_reason(item)}")
        hidden = len(readiness_list) - len(shown)
        if hidden > 0:
            lines.append(f"\n… y {hidden} VIPs más.")
        lines.append(
            "\nActiva o apaga con los botones de abajo (solo si están "
            "disponibles)."
        )
        return "\n".join(lines)
