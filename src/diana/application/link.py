"""LinkCoordinator — dedup, verify-VIP, persist and apply Lucien→Diana kick decisions.

No aiogram and no cognitive-core imports: this is pure application-service
orchestration over the VipStore + LinkEventStore + OwnerNotifierPort ports.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Callable

from diana.application.ports import (
    LinkEventRecord,
    LinkEventStore,
    LinkNotification,
    OwnerNotifierPort,
    VipStore,
)

logger = logging.getLogger("diana.application.link")

_DEFAULT_DISABLE_FROZEN_UNTIL = datetime(2099, 12, 31, tzinfo=UTC)


class LinkCoordinator:
    """Orchestrates the kick-link ledger without any telegram wiring.

    ``enabled=False`` makes both entry points no-ops (feature flag OFF), so the
    system behaves exactly as before the feature existed.
    """

    def __init__(
        self,
        *,
        vips: VipStore,
        links: LinkEventStore,
        notifier: OwnerNotifierPort,
        owner_telegram_id: int,
        clock: Callable[[], datetime] | None = None,
        disable_frozen_until: datetime,
        enabled: bool,
    ) -> None:
        self._vips = vips
        self._links = links
        self._notifier = notifier
        self._owner_telegram_id = owner_telegram_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._disable_frozen_until = disable_frozen_until
        self._enabled = enabled

    async def handle_kick_event(
        self,
        *,
        event_id: str,
        user_id: int,
        username: str | None,
        reason: str,
        channel_id: int | None,
        channel_name: str | None,
    ) -> None:
        if not self._enabled:
            return
        if await self._links.get_by_event_id(event_id) is not None:
            logger.info("link_dedup", extra={"event_id": event_id})
            return

        rec = await self._vips.get_by_telegram_user_id(user_id)
        is_vip = rec is not None and rec.is_active
        vip_id = rec.id if is_vip else None

        await self._links.create(
            LinkEventRecord(
                event_id=event_id,
                user_id=user_id,
                username=username,
                channel_id=channel_id,
                channel_name=channel_name,
                reason=reason,
                vip_id=vip_id,
                state="pending",
            )
        )
        logger.info(
            "link_received",
            extra={
                "event_id": event_id,
                "user_id": user_id,
                "vip_id": str(vip_id) if vip_id else None,
            },
        )

        if not is_vip:
            await self._links.set_state(event_id, "ignored_not_vip")
            logger.info(
                "link_ignored_not_vip",
                extra={"event_id": event_id, "user_id": user_id},
            )
            return

        await self._notifier.notify_link(
            LinkNotification(
                display_name=rec.display_name or str(user_id),
                username=username,
                event_id=event_id,
            )
        )
        await self._links.set_state(event_id, "notified")
        logger.info(
            "link_notified",
            extra={"event_id": event_id, "user_id": user_id, "vip_id": str(vip_id)},
        )

    async def handle_decision(self, event_id: str, action: str) -> str:
        if not self._enabled:
            return "ya no aplica"
        event = await self._links.get_by_event_id(event_id)
        if event is None:
            logger.info(
                "link_noop",
                extra={"reason": "not_found", "event_id": event_id, "action": action},
            )
            return "ya no aplica"

        if event.state not in ("notified", "pending"):
            logger.info(
                "link_noop",
                extra={"event_id": event_id, "state": event.state, "action": action},
            )
            return "ya no aplica"

        if event.vip_id is None:
            await self._links.set_state(event_id, "noop")
            logger.info(
                "link_noop",
                extra={"event_id": event_id, "state": event.state, "action": action},
            )
            return "ya no aplica"

        if action == "expel":
            deactivated = await self._vips.deactivate(event.user_id)
            if not deactivated:
                logger.info(
                    "link_noop",
                    extra={"reason": "deactivate_failed", "event_id": event_id, "action": action},
                )
                return "ya no aplica"
            new_state = "decided_expel"
        elif action == "disable":
            frozen_until = (
                self._disable_frozen_until
                if self._disable_frozen_until > self._clock()
                else _DEFAULT_DISABLE_FROZEN_UNTIL
            )
            try:
                await self._vips.freeze_vip(event.vip_id, frozen_until=frozen_until)
            except ValueError:
                logger.info(
                    "link_noop",
                    extra={"reason": "vip_missing", "event_id": event_id, "action": action},
                )
                return "ya no aplica"
            new_state = "decided_disable"
        elif action == "keep":
            new_state = "decided_keep"
        else:
            logger.info(
                "link_noop",
                extra={"reason": "unknown_action", "event_id": event_id, "action": action},
            )
            return "ya no aplica"

        await self._links.set_state(event_id, new_state, decision_at=self._clock())
        logger.info(
            f"link_decided_{action}",
            extra={"event_id": event_id, "vip_id": str(event.vip_id)},
        )

        if action == "expel":
            return "Suscriptor expulsado."
        if action == "disable":
            return "VIP inhabilitado."
        return "Sin cambios."


__all__ = ["LinkCoordinator"]
