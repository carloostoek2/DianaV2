"""RecontactService — silence-based recontact (no LLM / no Analyst / no Planner).

Flag-gated application service. Jobs call execute; eligibility lives here.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from diana.application.autonomous_mode_service import AutonomousModeService
from diana.application.ports import (
    BehaviorDeliverer,
    DeliveryMode,
    OwnerNotifierPort,
    PendingApprovalStore,
    RecontactScheduleRecord,
    RecontactScheduleStore,
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

    async def schedule_recontact(self, vip_id: UUID) -> RecontactScheduleRecord | None:
        if not self._enabled:
            return None
        days, _templates = await self._load_config()
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

        waiting = await self._approvals.list_waiting()
        if any(a.vip_id == vip_id for a in waiting):
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
        # Task 2 implements full path; skeleton keeps flag-off + blocked safe.
        if await self.is_blocked(vip_id):
            logger.info(
                "recontact_blocked",
                extra={"vip_id": str(vip_id), "status": "blocked"},
            )
            return "blocked"
        return "disabled"

    async def _load_config(self) -> tuple[int, list[str]]:
        try:
            raw: Mapping[str, object] = await self._config.get_recontact_config()
        except Exception:
            logger.exception("recontact_config_load_failed")
            return _DEFAULT_INACTIVITY_DAYS, list(_DEFAULT_TEMPLATES)

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
        return days, templates


def _as_aware(value: datetime, ref: datetime) -> datetime:
    if value.tzinfo is None and ref.tzinfo is not None:
        return value.replace(tzinfo=ref.tzinfo)
    return value


__all__ = [
    "ClockPort",
    "RecontactConfigReader",
    "RecontactService",
    "VipRouteResolver",
    "render_template",
]
