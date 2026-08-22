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
from diana.profile_content import is_hollow_content, normalize_content

logger = logging.getLogger("diana.application")

__all__ = ["ProfileAdminResult", "ProfileAdminService"]


def _is_integrity_error(exc: BaseException) -> bool:
    """True for SQLAlchemy/asyncpg IntegrityError without importing sqlalchemy."""
    for cls in type(exc).__mro__:
        if cls.__name__ == "IntegrityError":
            return True
    return False


@dataclass
class ProfileAdminResult:
    """Plain outcome of an owner profile admin operation."""

    status: str
    telegram_user_id: int | None = None
    display_name: str | None = None
    content: dict | None = None
    detail: str | None = None
    # F5 Pool 4 (F5-06): the semantic memory rows (list_by_vip) shown as an
    # extra section of the ficha. Default None keeps every existing
    # constructor/tests byte-identical (A7).
    memory: list[dict] | None = None
    # Evo-Agente Fase 5 (EA-06): per-category trust rows (list_for_ficha) shown
    # as the 🔐 Confianza section of the ficha. Default None keeps every
    # existing constructor/tests byte-identical (A7). Only wired with the flag
    # ON (flag OFF → None → no query, byte-identical).
    trust_budget: list[dict] | None = None
    # Evo-Agente Fase 5 (EA-06): vip_profile_history rows shown as the
    # 📚 Historial de versiones section of the ficha (newest-first, capped).
    # Default None keeps every existing constructor/tests byte-identical (A7).
    profile_history: list[dict] | None = None


class ProfileAdminService:
    """Owner-gated VIP profile facts/notes admin API."""

    def __init__(
        self,
        *,
        profiles: Any,
        vips: VipStore,
        owner_telegram_id: int,
        clock: Callable[[], datetime] | None = None,
        memories: Any | None = None,
        trust_budget: Any | None = None,
        profile_history: Any | None = None,
    ) -> None:
        self._profiles = profiles
        self._vips = vips
        self._owner_telegram_id = owner_telegram_id
        self._clock = clock or (lambda: datetime.now(UTC))
        # F5 Pool 4 (F5-06): optional semantic memory reader (MemoriesRepo).
        # Wired only when feature_memory_enabled (flag OFF → None → no query,
        # byte-identical).
        self._memories = memories
        # Evo-Agente Fase 5 (EA-06): optional trust-budget service (flag-gated;
        # flag OFF → None → no query, byte-identical).
        self._trust_budget = trust_budget
        # Evo-Agente Fase 5 (EA-06): optional vip_profile_history reader
        # (flag-gated; flag OFF → None → no query, byte-identical).
        self._profile_history = profile_history

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

    async def _resolve_vip_any(
        self, telegram_user_id: int
    ) -> VipRecord | None:
        """Resolve VIP including inactive (for post-deactivate purge)."""
        return await self._vips.get_by_telegram_user_id(telegram_user_id)

    async def purge_profile_for_telegram_user(
        self, actor_id: int | None, telegram_user_id: int
    ) -> ProfileAdminResult:
        """Owner-gated delete of profiles row for VIP (active or inactive)."""
        self._assert_owner(actor_id)
        vip = await self._resolve_vip_any(telegram_user_id)
        if vip is None:
            return ProfileAdminResult(
                status="vip_not_found", telegram_user_id=telegram_user_id
            )
        deleted = await self._profiles.delete_by_vip_id(vip.id)
        return ProfileAdminResult(
            status="profile_purged" if deleted else "profile_absent",
            telegram_user_id=telegram_user_id,
            display_name=vip.display_name,
        )

    async def show_profile(
        self, actor_id: int | None, telegram_user_id: int
    ) -> ProfileAdminResult:
        self._assert_owner(actor_id)
        vip = await self._resolve_active_vip(telegram_user_id)
        if vip is None:
            return ProfileAdminResult(
                status="vip_not_found", telegram_user_id=telegram_user_id
            )
        # F5 Pool 4 (F5-06): semantic memory rows (only when wired — flag ON).
        memory_rows: list[dict] | None = None
        if self._memories is not None:
            memory_rows = await self._memories.list_by_vip(vip.id)
        # Evo-Agente Fase 5 (EA-06): per-category trust rows (only when wired —
        # flag ON). An empty list (VIP with no trust history) is normalized to
        # None so the ficha never renders an orphan header. Best-effort (review
        # round 1, S5): a DB error on the trust rows must never break the owner
        # ficha — consistent with the item's "never propagates" ethos.
        trust_rows: list[dict] | None = None
        if self._trust_budget is not None:
            try:
                rows = await self._trust_budget.list_for_ficha(vip.id)
            except Exception:
                logger.exception(
                    "profile_trust_rows_failed",
                    extra={"telegram_user_id": telegram_user_id},
                )
                rows = None
            trust_rows = rows or None
        # Evo-Agente Fase 5 (EA-06): profile version history (newest-first,
        # capped for display). Best-effort like the trust rows — a DB error
        # must never break the owner ficha.
        history_rows: list[dict] | None = None
        if self._profile_history is not None:
            try:
                rows = await self._profile_history.list_by_vip(vip.id)
                history_rows = [
                    {
                        "version": r.version,
                        "created_at": r.created_at,
                        "diff_summary": r.diff_summary,
                    }
                    for r in rows
                ]
                if not history_rows:
                    history_rows = None
            except Exception:
                logger.exception(
                    "profile_history_rows_failed",
                    extra={"telegram_user_id": telegram_user_id},
                )
                history_rows = None
        row = await self._profiles.get_by_vip_id(vip.id)
        content = None if row is None else row.get("content")
        if row is None or is_hollow_content(content):
            return ProfileAdminResult(
                status="profile_empty",
                telegram_user_id=telegram_user_id,
                display_name=vip.display_name,
                content={"facts": {}, "notes": []},
                memory=memory_rows,
                trust_budget=trust_rows,
                profile_history=history_rows,
            )
        # Prefer normalized schema for structured rows; keep legacy flat as-is.
        display: dict | None
        if isinstance(content, dict):
            other = {k: v for k, v in content.items() if k not in ("facts", "notes")}
            if other:
                display = content
            else:
                display = normalize_content(content)
        else:
            display = None
        return ProfileAdminResult(
            status="profile_ok",
            telegram_user_id=telegram_user_id,
            display_name=vip.display_name,
            content=display,
            memory=memory_rows,
            trust_budget=trust_rows,
            profile_history=history_rows,
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
        except ValueError as exc:
            return ProfileAdminResult(
                status="invalid",
                telegram_user_id=telegram_user_id,
                display_name=vip.display_name,
                detail=str(exc) or "empty key or value",
            )
        except Exception as exc:
            if _is_integrity_error(exc):
                logger.warning(
                    "profile_set_fact_integrity",
                    extra={"telegram_user_id": telegram_user_id},
                )
                return ProfileAdminResult(
                    status="vip_not_found",
                    telegram_user_id=telegram_user_id,
                    display_name=vip.display_name,
                    detail="integrity",
                )
            raise
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
        pre_content = pre.get("content") if isinstance(pre.get("content"), dict) else {}
        pre_facts = (pre_content or {}).get("facts") or {}
        key_present = isinstance(pre_facts, dict) and k in pre_facts
        try:
            row = await self._profiles.delete_fact(vip.id, k)
        except Exception as exc:
            if _is_integrity_error(exc):
                return ProfileAdminResult(
                    status="vip_not_found",
                    telegram_user_id=telegram_user_id,
                    display_name=vip.display_name,
                    detail="integrity",
                )
            raise
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
        except ValueError as exc:
            return ProfileAdminResult(
                status="invalid",
                telegram_user_id=telegram_user_id,
                display_name=vip.display_name,
                detail=str(exc) or "empty note text",
            )
        except Exception as exc:
            if _is_integrity_error(exc):
                logger.warning(
                    "profile_add_note_integrity",
                    extra={"telegram_user_id": telegram_user_id},
                )
                return ProfileAdminResult(
                    status="vip_not_found",
                    telegram_user_id=telegram_user_id,
                    display_name=vip.display_name,
                    detail="integrity",
                )
            raise
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
        try:
            row = await self._profiles.delete_note(vip.id, index0)
        except Exception as exc:
            if _is_integrity_error(exc):
                return ProfileAdminResult(
                    status="vip_not_found",
                    telegram_user_id=telegram_user_id,
                    display_name=vip.display_name,
                    detail="integrity",
                )
            raise
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
