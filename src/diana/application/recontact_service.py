"""RecontactService — silence-based recontact (no LLM / no Analyst / no Planner).

Flag-gated application service. Jobs call execute; eligibility lives here.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from diana.application.autonomous_mode_service import AutonomousModeService
from diana.application.owner_history import append_owner_delivery_history
from diana.application.ports import (
    BehaviorDeliverer,
    DeliveryContext,
    DeliveryMode,
    MessageHistoryWriter,
    OwnerNotifierPort,
    PendingApprovalStore,
    PendingDeliveryStore,
    RecontactScheduleRecord,
    RecontactScheduleStore,
    TurnRecord,
    TurnStore,
    VipStore,
)

logger = logging.getLogger("diana.application")

_DEFAULT_INACTIVITY_DAYS = 7
_DEFAULT_TEMPLATES: list[str] = ["Hola {nombre}"]


class RecontactConfigReader(Protocol):
    async def get_recontact_config(self) -> dict: ...


class VipRouteResolver(Protocol):
    async def resolve(self, vip_id: UUID) -> tuple[int, str] | None:
        """Return (chat_id, business_connection_id) or None if unknown."""
        ...


class ClockPort(Protocol):
    def now(self) -> datetime: ...


def render_template(template: str, *, nombre: str, producto: str = "") -> str:
    """Substitute ``{nombre}`` / ``{producto}`` placeholders (no format-string eval)."""
    return (
        template.replace("{nombre}", nombre).replace("{producto}", producto)
    )


class RecontactService:
    """Schedule lifecycle + eligibility + AMS-gated template recontact."""

    def __init__(
        self,
        *,
        feature_recontact_enabled: bool,
        schedules: RecontactScheduleStore,
        vips: VipStore,
        config: RecontactConfigReader,
        approvals: PendingApprovalStore,
        ams: AutonomousModeService,
        behavior: BehaviorDeliverer,
        turns: TurnStore,
        route_resolver: VipRouteResolver,
        notifier: OwnerNotifierPort,
        clock: ClockPort,
        delivery_mode: DeliveryMode = "supervised",
        has_open_gray_zone: Callable[[UUID], Awaitable[bool]] | None = None,
        is_sandbox_vip: Callable[[UUID], Awaitable[bool]] | None = None,
        history: MessageHistoryWriter | None = None,
        sandbox: object | None = None,
        personalizer: object | None = None,
    ) -> None:
        self._enabled = feature_recontact_enabled
        self._schedules = schedules
        self._vips = vips
        self._config = config
        self._approvals = approvals
        self._ams = ams
        self._behavior = behavior
        self._turns = turns
        self._route_resolver = route_resolver
        self._notifier = notifier
        self._clock = clock
        self._delivery_mode = delivery_mode
        self._has_open_gray_zone = has_open_gray_zone
        self._is_sandbox_vip = is_sandbox_vip
        self._history = history
        self._sandbox = sandbox
        # Reduced-pipeline personalization (REE-02/COG-15): optional
        # RecontactPersonalizer. When wired, ``personalize: true`` in the
        # recontact config turns it on; any failure falls back to templates.
        self._personalizer = personalizer

    async def schedule_recontact(self, vip_id: UUID) -> RecontactScheduleRecord | None:
        if not self._enabled:
            return None
        days, _templates, _personalize = await self._load_config()
        now = self._clock.now()
        next_at = now + timedelta(days=days)
        rec = await self._schedules.upsert_pending(
            vip_id, last_contact_at=now, next_contact_at=next_at
        )
        logger.info(
            "recontact_scheduled",
            extra={"vip_id": str(vip_id), "next_contact_at": next_at.isoformat()},
        )
        return rec

    async def cancel_recontact(self, vip_id: UUID) -> bool:
        if not self._enabled:
            return False
        ok = await self._schedules.cancel_pending(vip_id)
        if ok:
            logger.info("recontact_cancelled", extra={"vip_id": str(vip_id)})
        return ok

    async def is_blocked(self, vip_id: UUID) -> bool:
        if not self._enabled:
            return False

        vip = await self._vips.get_by_id(vip_id)
        if vip is None or not vip.is_active:
            return True

        now = self._clock.now()
        if vip.paused_until is not None and _as_aware(vip.paused_until, now) > now:
            return True
        if vip.frozen_until is not None and _as_aware(vip.frozen_until, now) > now:
            return True

        open_approvals = await self._approvals.list_open()
        if any(a.vip_id == vip_id for a in open_approvals):
            return True

        if self._has_open_gray_zone is not None:
            try:
                if await self._has_open_gray_zone(vip_id):
                    return True
            except Exception:
                logger.exception(
                    "recontact_gray_zone_check_failed",
                    extra={"vip_id": str(vip_id)},
                )
                return True

        if self._is_sandbox_vip is not None:
            try:
                if await self._is_sandbox_vip(vip_id):
                    return True
            except Exception:
                logger.exception(
                    "recontact_sandbox_check_failed",
                    extra={"vip_id": str(vip_id)},
                )
                return True

        return False

    async def get_due_vips(self) -> list[UUID]:
        if not self._enabled:
            return []
        now = self._clock.now()
        due = await self._schedules.list_due(now)
        seen: set[UUID] = set()
        out: list[UUID] = []
        for row in due:
            if row.vip_id in seen:
                continue
            seen.add(row.vip_id)
            if await self.is_blocked(row.vip_id):
                continue
            out.append(row.vip_id)
        return out

    async def execute_recontact(self, vip_id: UUID) -> str:
        """Return status: disabled|blocked|no_route|supervised_skipped|delivered|failed."""
        if not self._enabled:
            return "disabled"

        if await self.is_blocked(vip_id):
            logger.info(
                "recontact_blocked",
                extra={"vip_id": str(vip_id), "status": "blocked"},
            )
            return "blocked"

        days, templates, _personalize = await self._load_config()
        now = self._clock.now()

        route = await self._route_resolver.resolve(vip_id)
        if route is None:
            next_at = now + timedelta(days=days)
            await self._schedules.upsert_pending(
                vip_id, last_contact_at=now, next_contact_at=next_at
            )
            logger.info(
                "recontact_no_route",
                extra={"vip_id": str(vip_id), "status": "no_route"},
            )
            return "no_route"

        chat_id, business_connection_id = route
        text = await self._render_for_vip(vip_id, templates)

        if not await self._ams.is_autonomous_enabled(vip_id):
            vip = await self._vips.get_by_id(vip_id)
            nombre = vip.display_name if vip and vip.display_name else "vos"
            try:
                await self._notifier.notify_info(
                    "Recontacto supervisado (sin auto-envío): "
                    f"VIP {nombre} — borrador: {text}"
                )
            except Exception:
                logger.exception(
                    "recontact_supervised_notify_failed",
                    extra={"vip_id": str(vip_id)},
                )
            await self._complete_and_reschedule(vip_id, now=now, days=days)
            logger.info(
                "recontact_supervised_skipped",
                extra={"vip_id": str(vip_id), "status": "supervised_skipped"},
            )
            return "supervised_skipped"

        turn = await self._turns.create(
            TurnRecord(
                id=uuid4(),
                chat_id=chat_id,
                status="received",
                vip_id=vip_id,
            )
        )
        ctx = DeliveryContext(
            chat_id=chat_id,
            business_connection_id=business_connection_id,
            vip_id=vip_id,
            mode=self._delivery_mode,
            is_frozen=False,
        )
        try:
            result = await self._behavior.deliver([text], ctx, turn.id)
        except Exception as exc:
            logger.exception(
                "recontact_deliver_error",
                extra={"vip_id": str(vip_id), "turn_id": str(turn.id)},
            )
            await self._turns.transition(
                turn.id, "failed", error=str(exc)[:500]
            )
            return "failed"

        if getattr(result, "success", False):
            await self._turns.transition(turn.id, "delivered")
            # Owner history after successful recontact deliver (parity admin/orch).
            if self._history is not None:
                if (
                    self._sandbox is not None
                    and not self._sandbox.should_persist(chat_id)  # type: ignore[union-attr]
                ):
                    logger.info(
                        "owner_history_skipped_sandbox",
                        extra={"turn_id": str(turn.id), "chat_id": chat_id},
                    )
                else:
                    await append_owner_delivery_history(
                        self._history,
                        chat_id,
                        result=result,
                        fallback_text=text,
                        turn_id=turn.id,
                    )
            await self._complete_and_reschedule(vip_id, now=now, days=days)
            logger.info(
                "recontact_delivered",
                extra={
                    "vip_id": str(vip_id),
                    "turn_id": str(turn.id),
                    "status": "delivered",
                },
            )
            return "delivered"

        err = getattr(result, "error", None) or "deliver_failed"
        await self._turns.transition(turn.id, "failed", error=str(err)[:500])
        logger.info(
            "recontact_failed",
            extra={
                "vip_id": str(vip_id),
                "turn_id": str(turn.id),
                "status": "failed",
            },
        )
        return "failed"

    async def _render_for_vip(self, vip_id: UUID, templates: list[str]) -> str:
        vip = await self._vips.get_by_id(vip_id)
        nombre = "vos"
        if vip is not None and vip.display_name:
            nombre = vip.display_name
        idx = vip_id.int % len(templates)
        template = render_template(templates[idx], nombre=nombre, producto="")
        if self._personalizer is None or not self._personalize_enabled:
            return template
        try:
            personalized = await self._personalizer.personalize(
                vip_id=vip_id, template=template, nombre=nombre
            )
        except Exception:
            logger.exception(
                "recontact_personalize_failed",
                extra={"vip_id": str(vip_id)},
            )
            return template
        return personalized or template

    @property
    def _personalize_enabled(self) -> bool:
        """Config key ``personalize``; defaults to ON when a personalizer is wired."""
        flag = getattr(self, "_personalize_flag", None)
        if flag is None:
            return self._personalizer is not None
        return bool(flag)

    async def _complete_and_reschedule(
        self, vip_id: UUID, *, now: datetime, days: int
    ) -> None:
        pending = await self._schedules.get_pending_by_vip(vip_id)
        if pending is not None:
            await self._schedules.mark_done(pending.id)
        next_at = now + timedelta(days=days)
        await self._schedules.upsert_pending(
            vip_id, last_contact_at=now, next_contact_at=next_at
        )

    async def _load_config(self) -> tuple[int, list[str], bool]:
        try:
            raw: Mapping[str, object] = await self._config.get_recontact_config()
        except Exception:
            logger.exception("recontact_config_load_failed")
            return (
                _DEFAULT_INACTIVITY_DAYS,
                list(_DEFAULT_TEMPLATES),
                self._personalizer is not None,
            )

        days_raw = raw.get("inactivity_days", _DEFAULT_INACTIVITY_DAYS)
        try:
            days = int(days_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            days = _DEFAULT_INACTIVITY_DAYS
        if days < 1:
            days = _DEFAULT_INACTIVITY_DAYS

        templates_raw = raw.get("templates")
        templates: list[str] = []
        if isinstance(templates_raw, list):
            templates = [str(t) for t in templates_raw if str(t).strip()]
        if not templates:
            templates = list(_DEFAULT_TEMPLATES)

        personalize_raw = raw.get("personalize")
        if isinstance(personalize_raw, bool):
            personalize = personalize_raw
        else:
            personalize = self._personalizer is not None
        self._personalize_flag = personalize
        return days, templates, personalize


def _as_aware(value: datetime, ref: datetime) -> datetime:
    if value.tzinfo is None and ref.tzinfo is not None:
        return value.replace(tzinfo=ref.tzinfo)
    return value


class ApprovalsDeliveriesRouteResolver:
    """Resolve VIP routing from waiting approvals, then active deliveries."""

    def __init__(
        self,
        approvals: PendingApprovalStore,
        deliveries: PendingDeliveryStore,
    ) -> None:
        self._approvals = approvals
        self._deliveries = deliveries

    async def resolve(self, vip_id: UUID) -> tuple[int, str] | None:
        open_rows = await self._approvals.list_open()
        for row in open_rows:
            if row.vip_id == vip_id:
                bc = (row.business_connection_id or "").strip()
                if bc:
                    return row.chat_id, bc
        try:
            active = await self._deliveries.list_active()
        except Exception:
            logger.exception(
                "recontact_route_list_active_failed",
                extra={"vip_id": str(vip_id)},
            )
            return None
        for row in active:
            if row.vip_id == vip_id:
                bc = (row.business_connection_id or "").strip()
                if bc:
                    return row.chat_id, bc
        return None


__all__ = [
    "ApprovalsDeliveriesRouteResolver",
    "ClockPort",
    "RecontactConfigReader",
    "RecontactService",
    "VipRouteResolver",
    "render_template",
]
