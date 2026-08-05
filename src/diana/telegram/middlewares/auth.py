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

from diana.application.ports import PromoTriggerRecord, TrainingModeStore, VipStore

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
        telegram_message_id: int | None = None,
    ) -> str: ...


class AuthMiddleware(BaseMiddleware):
    """Gate business VIP allowlist; optional promo for non-VIP business."""

    def __init__(
        self,
        *,
        vips: VipStore,
        promo: PromoMatcher | None = None,
        feature_promo_enabled: bool = False,
        feature_general_mode_enabled: bool = False,
        sandbox: Any | None = None,
        training_mode: TrainingModeStore | None = None,
    ) -> None:
        self._vips = vips
        self._promo = promo
        self._feature_promo_enabled = feature_promo_enabled
        self._feature_general_mode_enabled = feature_general_mode_enabled
        self._sandbox = sandbox
        self._training_mode = training_mode

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
            else:
                # S6: no VIP record → sandbox previews the atencion persona
                # instead of silently defaulting to the VIP channel.
                data["channel_type"] = "atencion"
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

        # Single VIP lookup: reuse the FreezeCheckMiddleware _vip_record cache
        # (MED-3) when present (allowed is derived from that same snapshot); a
        # stranger costs exactly one fetch (FIX-R2-8).
        rec: Any = data.get("_vip_record")
        rec, allowed = await self._vips.get_record_and_allowed(user.id, record=rec)
        if not allowed:
            # Distinguish "no VIP record at all" from "VIP record exists but
            # paused/inactive" (S4): only no-record users take the training /
            # general (atencion) gates. A paused/inactive VIP must NOT be
            # routed to atencion (it would lose VIP identity); it only reaches
            # promo/drop handling below.
            has_vip_record = rec is not None

            # Promo primero (REQ-ATN-09): the promo trigger is evaluated before
            # any gate. An exact match runs the promo and the message NEVER
            # enters the pipeline; a non-match falls through to the gates/drop.
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
                            telegram_message_id=event.message_id,
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
                    return None

            if not has_vip_record:
                # No VIP record at all → the non-VIP atencion gates apply.
                # Training mode gate: non-VIP + training ON → pass through to
                # the cognitive pipeline WITHOUT vip_id/vip_record.
                if self._training_mode is not None and await self._training_mode.is_enabled():
                    data["channel_type"] = "atencion"
                    logger.info(
                        "training_mode_bypass",
                        extra={
                            "telegram_user_id": user.id,
                            "chat_id": chat_id,
                        },
                    )
                    return await handler(event, data)

                # F4 general mode gate: non-VIP + flag ON → atencion channel,
                # same deterministic path as training mode but permanent. The
                # channel travels in data; no vip_id/vip_record is set.
                if self._feature_general_mode_enabled:
                    data["channel_type"] = "atencion"
                    # F4-02: ONLY the general-mode gate sets the limit-counted
                    # marker. Sandbox (auth.py sandbox gate) and training mode
                    # never set it, so their atencion messages are NOT counted.
                    data["atencion_limit_counted"] = True
                    logger.info(
                        "general_mode_bypass",
                        extra={
                            "telegram_user_id": user.id,
                            "chat_id": chat_id,
                        },
                    )
                    return await handler(event, data)

            logger.info(
                "auth_drop_not_allowed",
                extra={"telegram_user_id": user.id},
            )
            return None

        if rec is not None:
            data["vip_id"] = rec.id
            data["vip_record"] = rec
        return await handler(event, data)


__all__ = ["AuthMiddleware", "PromoMatcher"]
