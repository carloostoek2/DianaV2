"""MemoryApprovalService — owner-gated approval of pending_owner facts (F5-05).

The owner lists the facts that need her decision via ``/memoria`` and
approves/discards them one by one (``mp:``/``md:`` callbacks) — the
structural mirror of the staging example approval, but for the memory
domain. All writes go through ``MemoryDecisionWriter`` (implemented by
``MemoriesRepo``) which scopes every transition by (id, vip_id) (BR-15):
the service resolves the row's ``vip_id`` via ``get_fact`` and never
accepts a vip id from the callback payload.

Purity: stdlib + application imports only — no aiogram, no infrastructure
sessions (structural typing via the local protocol).
"""

from __future__ import annotations

import logging
from typing import Literal, Protocol
from uuid import UUID

from diana.application.admin_service import OwnerAuthError
from diana.application.memory_backfill_service import VipReader

logger = logging.getLogger("diana.application")

__all__ = ["MemoryApprovalService", "MemoryDecisionWriter"]


class MemoryDecisionWriter(Protocol):
    """Repo surface the approval flow needs (implemented by MemoriesRepo)."""

    async def list_pending_owner(self, limit: int = 50) -> list[dict]: ...

    async def get_fact(self, fact_id: UUID) -> dict | None: ...

    async def set_fact_status(
        self,
        fact_id: UUID,
        *,
        vip_id: UUID,
        new_status: Literal["approved", "discarded"],
    ) -> bool: ...


class MemoryApprovalService:
    """Owner-only approval queue for sensitive memory facts (REQ-MEM-10)."""

    def __init__(
        self,
        *,
        memories: MemoryDecisionWriter,
        owner_telegram_id: int,
        vips: VipReader | None = None,
    ) -> None:
        self._memories = memories
        self._owner_telegram_id = owner_telegram_id
        # Optional VIP store: enriches the DM list with display_name (UX).
        self._vips = vips

    def _assert_owner(self, actor_id: int | None) -> None:
        if actor_id is None or actor_id != self._owner_telegram_id:
            raise OwnerAuthError(
                f"actor_id {actor_id!r} is not the configured owner"
            )

    async def _vip_name(self, row: dict) -> str:
        """Best-effort display_name for a fact row (fallback short uuid)."""
        raw = row.get("vip_id")
        if not raw:
            return "?"
        vip_id = UUID(str(raw))
        if self._vips is not None:
            try:
                vip = await self._vips.get_by_id(vip_id)
                if vip is not None and getattr(vip, "display_name", None):
                    return str(vip.display_name)
            except Exception:
                logger.debug(
                    "memory_approval_name_resolve_failed",
                    extra={"vip_id": str(vip_id)},
                )
        return str(raw)[:8]

    async def list_pending(
        self, actor_id: int | None, *, limit: int = 50
    ) -> list[dict]:
        """Owner-admin list of pending_owner facts across VIPs (A3)."""
        self._assert_owner(actor_id)
        rows = await self._memories.list_pending_owner(limit=limit)
        out: list[dict] = []
        for row in rows:
            enriched = dict(row)
            enriched["vip_name"] = await self._vip_name(row)
            out.append(enriched)
        return out

    async def approve(self, actor_id: int | None, fact_id: UUID) -> str:
        """Approve one pending fact. Tokens: approved | stale."""
        return await self._decide(actor_id, fact_id, "approved")

    async def discard(self, actor_id: int | None, fact_id: UUID) -> str:
        """Discard one pending fact. Tokens: discarded | stale."""
        return await self._decide(actor_id, fact_id, "discarded")

    async def _decide(
        self,
        actor_id: int | None,
        fact_id: UUID,
        new_status: Literal["approved", "discarded"],
    ) -> str:
        self._assert_owner(actor_id)
        row = await self._memories.get_fact(fact_id)
        if row is None or row.get("status") != "pending_owner":
            return "stale"
        ok = await self._memories.set_fact_status(
            fact_id,
            vip_id=UUID(str(row["vip_id"])),
            new_status=new_status,
        )
        if not ok:
            return "stale"
        logger.info(
            "memory_approval_decided",
            extra={
                "fact_id": str(fact_id),
                "new_status": new_status,
                "actor_id": actor_id,
            },
        )
        return new_status
