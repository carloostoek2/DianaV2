"""ProfileAdminService — owner-only write path for real VIP enrichable profiles.

Resolves telegram_user_id → active VIP UUID, then delegates to a duck-typed
profiles store (ProfilesRepo or test fake). No aiogram types.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from diana.application.admin_service import OwnerAuthError
from diana.application.ports import VipRecord, VipStore

logger = logging.getLogger("diana.application")

__all__ = ["ProfileAdminResult", "ProfileAdminService"]


@dataclass
class ProfileAdminResult:
    """Plain outcome of an owner profile admin operation."""

    status: str
    telegram_user_id: int | None = None
    display_name: str | None = None
    content: dict | None = None
    detail: str | None = None


class ProfileAdminService:
    """Owner-gated VIP profile facts/notes admin API."""

    def __init__(
        self,
        *,
        profiles: Any,
        vips: VipStore,
        owner_telegram_id: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._profiles = profiles
        self._vips = vips
        self._owner_telegram_id = owner_telegram_id
        self._clock = clock or (lambda: datetime.now(UTC))

    def _assert_owner(self, actor_id: int | None) -> None:
        if actor_id is None or actor_id != self._owner_telegram_id:
            raise OwnerAuthError(
                f"actor_id {actor_id!r} is not the configured owner"
            )

    async def _resolve_active_vip(
        self, telegram_user_id: int
    ) -> VipRecord | None:
        rec = await self._vips.get_by_telegram_user_id(telegram_user_id)
        if rec is None or not rec.is_active:
            return None
        return rec

    @staticmethod
    def _is_hollow(content: Any) -> bool:
        if content is None:
            return True
        if not isinstance(content, dict):
            return True
        facts = content.get("facts")
        notes = content.get("notes")
        facts_empty = facts is None or (isinstance(facts, dict) and len(facts) == 0)
        notes_empty = notes is None or (isinstance(notes, list) and len(notes) == 0)
        if not (facts_empty and notes_empty):
            return False
        other = {k: v for k, v in content.items() if k not in ("facts", "notes")}
        return not other

    async def show_profile(
        self, actor_id: int | None, telegram_user_id: int
    ) -> ProfileAdminResult:
        self._assert_owner(actor_id)
        vip = await self._resolve_active_vip(telegram_user_id)
        if vip is None:
            return ProfileAdminResult(
                status="vip_not_found", telegram_user_id=telegram_user_id
            )
        row = await self._profiles.get_by_vip_id(vip.id)
        content = None if row is None else row.get("content")
        if row is None or self._is_hollow(content):
            return ProfileAdminResult(
                status="profile_empty",
                telegram_user_id=telegram_user_id,
                display_name=vip.display_name,
                content={"facts": {}, "notes": []} if content is None else content,
            )
        return ProfileAdminResult(
            status="profile_ok",
            telegram_user_id=telegram_user_id,
            display_name=vip.display_name,
            content=content if isinstance(content, dict) else None,
        )

    async def set_fact(
        self,
        actor_id: int | None,
        telegram_user_id: int,
        key: str,
        value: str,
    ) -> ProfileAdminResult:
        self._assert_owner(actor_id)
        vip = await self._resolve_active_vip(telegram_user_id)
        if vip is None:
            return ProfileAdminResult(
                status="vip_not_found", telegram_user_id=telegram_user_id
            )
        try:
            row = await self._profiles.set_fact(vip.id, key, value)
        except ValueError:
            return ProfileAdminResult(
                status="invalid",
                telegram_user_id=telegram_user_id,
                display_name=vip.display_name,
                detail="empty key or value",
            )
        return ProfileAdminResult(
            status="fact_set",
            telegram_user_id=telegram_user_id,
            display_name=vip.display_name,
            content=row.get("content") if row else None,
            detail=(key or "").strip(),
        )

    async def delete_fact(
        self, actor_id: int | None, telegram_user_id: int, key: str
    ) -> ProfileAdminResult:
        self._assert_owner(actor_id)
        vip = await self._resolve_active_vip(telegram_user_id)
        if vip is None:
            return ProfileAdminResult(
                status="vip_not_found", telegram_user_id=telegram_user_id
            )
        k = (key or "").strip()
        if not k:
            return ProfileAdminResult(
                status="invalid",
                telegram_user_id=telegram_user_id,
                display_name=vip.display_name,
                detail="empty key",
            )
        pre = await self._profiles.get_by_vip_id(vip.id)
        if pre is None:
            return ProfileAdminResult(
                status="fact_missing",
                telegram_user_id=telegram_user_id,
                display_name=vip.display_name,
                detail=k,
            )
        pre_facts = (pre.get("content") or {}).get("facts") or {}
        key_present = isinstance(pre_facts, dict) and k in pre_facts
        row = await self._profiles.delete_fact(vip.id, k)
        if row is None:
            return ProfileAdminResult(
                status="fact_missing",
                telegram_user_id=telegram_user_id,
                display_name=vip.display_name,
                detail=k,
            )
        if not key_present:
            return ProfileAdminResult(
                status="fact_missing",
                telegram_user_id=telegram_user_id,
                display_name=vip.display_name,
                content=row.get("content"),
                detail=k,
            )
        return ProfileAdminResult(
            status="fact_deleted",
            telegram_user_id=telegram_user_id,
            display_name=vip.display_name,
            content=row.get("content"),
            detail=k,
        )

    async def add_note(
        self, actor_id: int | None, telegram_user_id: int, text: str
    ) -> ProfileAdminResult:
        self._assert_owner(actor_id)
        vip = await self._resolve_active_vip(telegram_user_id)
        if vip is None:
            return ProfileAdminResult(
                status="vip_not_found", telegram_user_id=telegram_user_id
            )
        note_date = self._clock().date().isoformat()
        try:
            row = await self._profiles.add_note(vip.id, text, date=note_date)
        except ValueError:
            return ProfileAdminResult(
                status="invalid",
                telegram_user_id=telegram_user_id,
                display_name=vip.display_name,
                detail="empty note text",
            )
        return ProfileAdminResult(
            status="note_added",
            telegram_user_id=telegram_user_id,
            display_name=vip.display_name,
            content=row.get("content") if row else None,
        )

    async def delete_note(
        self,
        actor_id: int | None,
        telegram_user_id: int,
        index_1based: int,
    ) -> ProfileAdminResult:
        self._assert_owner(actor_id)
        vip = await self._resolve_active_vip(telegram_user_id)
        if vip is None:
            return ProfileAdminResult(
                status="vip_not_found", telegram_user_id=telegram_user_id
            )
        if not isinstance(index_1based, int) or index_1based < 1:
            return ProfileAdminResult(
                status="note_missing",
                telegram_user_id=telegram_user_id,
                display_name=vip.display_name,
                detail=str(index_1based),
            )
        index0 = index_1based - 1
        row = await self._profiles.delete_note(vip.id, index0)
        if row is None:
            return ProfileAdminResult(
                status="note_missing",
                telegram_user_id=telegram_user_id,
                display_name=vip.display_name,
                detail=str(index_1based),
            )
        return ProfileAdminResult(
            status="note_deleted",
            telegram_user_id=telegram_user_id,
            display_name=vip.display_name,
            content=row.get("content"),
            detail=str(index_1based),
        )
