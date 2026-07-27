"""AuthMiddleware — VIP allowlist gate + drop non-owner private spam.

F3: non-allowlisted business messages may hit PromoService when
FEATURE_PROMO_ENABLED is on (exact match → execute → stop VIP pipeline).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from diana.application.ports import PromoTriggerRecord, VipStore

logger = logging.getLogger("diana.telegram")


class PromoMatcher(Protocol):
    """Minimal surface Auth needs from PromoService (no assembly logic)."""

    async def match_trigger(self, text: str) -> PromoTriggerRecord | None: ...

    async def execute_promo(
        self,
        chat_id: int,
        trigger: PromoTriggerRecord,
        *,
        business_connection_id: str,
    ) -> str: ...


class AuthMiddleware(BaseMiddleware):
    """Gate business VIP allowlist; optional promo for non-VIP business."""

    def __init__(
        self,
        *,
        vips: VipStore,
        promo: PromoMatcher | None = None,
        feature_promo_enabled: bool = False,
        sandbox: Any | None = None,
    ) -> None:
        self._vips = vips
        self._promo = promo
        self._feature_promo_enabled = feature_promo_enabled
        self._sandbox = sandbox

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            # Callbacks etc. — owner check happens in handlers via actor_id.
            return await handler(event, data)

        bc = data.get("business_connection_id") or event.business_connection_id

        # Private (non-business) messages: only owner admin path continues.
        if not bc:
            if data.get("is_owner"):
                return await handler(event, data)
            logger.info(
                "auth_drop_private_non_owner",
                extra={
                    "telegram_user_id": getattr(
                        getattr(event, "from_user", None), "id", None
                    )
                },
            )
            return None

        user = event.from_user
        if user is None:
            logger.info("auth_drop_no_user")
            return None

        chat_id = event.chat.id if event.chat is not None else user.id
        if self._sandbox is not None and self._sandbox.is_active(chat_id):
            rec: Any = data.get("_vip_record")
            if rec is None:
                rec = await self._vips.get_by_telegram_user_id(user.id)
            if rec is not None:
                data["vip_id"] = rec.id
                data["vip_record"] = rec
            data["sandbox_active"] = True
            logger.info(
                "sandbox_auth_bypass",
                extra={
                    "chat_id": chat_id,
                    "telegram_user_id": user.id,
                    "has_vip": rec is not None,
                },
            )
            return await handler(event, data)

        allowed = await self._vips.is_allowed(user.id)
        if not allowed:
            if (
                self._feature_promo_enabled
                and self._promo is not None
                and bc
            ):
                text = event.text or event.caption or ""
                trigger = await self._promo.match_trigger(text)
                if trigger is not None:
                    chat_id = event.chat.id if event.chat is not None else user.id
                    logger.info(
                        "promo_match",
                        extra={
                            "chat_id": chat_id,
                            "telegram_user_id": user.id,
                            "trigger_id": str(trigger.id),
                        },
                    )
                    try:
                        status = await self._promo.execute_promo(
                            chat_id,
                            trigger,
                            business_connection_id=str(bc),
                        )
                        logger.info(
                            "promo_executed",
                            extra={
                                "chat_id": chat_id,
                                "trigger_id": str(trigger.id),
                                "status": status,
                            },
                        )
                    except Exception:
                        logger.exception(
                            "promo_failed",
                            extra={
                                "chat_id": chat_id,
                                "trigger_id": str(trigger.id),
                            },
                        )
                # Always stop VIP pipeline for non-allowlisted (match or not).
                return None

            logger.info(
                "auth_drop_not_allowed",
                extra={"telegram_user_id": user.id},
            )
            return None

        # Use _vip_record cached by FreezeCheckMiddleware (MED-3) to avoid a
        # redundant DB lookup. This is safe because FreezeCheckMiddleware runs
        # before AuthMiddleware in the middleware order.
        rec: Any = data.get("_vip_record")
        if rec is None:
            rec = await self._vips.get_by_telegram_user_id(user.id)
        if rec is not None:
            data["vip_id"] = rec.id
            data["vip_record"] = rec
        return await handler(event, data)


__all__ = ["AuthMiddleware", "PromoMatcher"]
