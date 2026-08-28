"""Seed VIP message_history from personal-account chat history (Telethon).

Product: when a VIP is added, import recent DM history so the cognitive
pipeline has context on the first live turn. Does not run inside Director.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from diana.application.ports import MessageHistoryWriter, OwnerNotifierPort

logger = logging.getLogger("diana.application")

HistoryRole = Literal["vip", "owner"]
SeedKind = Literal["disabled", "ok", "failed"]


@dataclass(frozen=True, slots=True)
class HistoryLine:
    """One seeded history row (V2 role vocabulary)."""

    role: HistoryRole
    text: str
    telegram_message_id: int | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class SeedOutcome:
    """Result of one VIP history import attempt (for owner notify + logs)."""

    kind: SeedKind
    count: int = 0
    telegram_user_id: int = 0

    def owner_message(self) -> str:
        """Short product-facing notice for the owner DM."""
        uid = self.telegram_user_id
        if self.kind == "failed":
            return (
                f"Historial del VIP {uid}: no se pudo importar. "
                "El VIP quedó registrado igual; el bot arrancará sin contexto previo."
            )
        if self.kind == "disabled":
            return (
                f"Historial del VIP {uid}: importación no disponible "
                "(Telethon no configurado)."
            )
        if self.count == 0:
            # Fetch succeeded but nothing was missing: either the personal
            # chat is empty or every available message was already stored.
            return f"Historial del VIP {uid}: no había historial previo que importar."
        return (
            f"Historial del VIP {uid}: importación correcta "
            f"({self.count} mensaje{'s' if self.count != 1 else ''})."
        )


class VipHistoryFetcher(Protocol):
    """Fetch recent personal-account messages with a VIP user."""

    async def fetch_recent(
        self,
        user_id: int,
        *,
        limit: int,
        username: str | None = None,
    ) -> list[HistoryLine]: ...


def map_raw_messages_to_lines(raw: list[dict]) -> list[HistoryLine]:
    """Map Telethon-style records → V2 HistoryLine list (chronological).

    Raw shape (v1 telethon_import): text, is_diana, id, date, media_kind.
    Empty text uses ``[media_kind]`` placeholder when media_kind is set.
    """
    out: list[HistoryLine] = []
    for m in raw:
        text = (m.get("text") or "").strip()
        if not text:
            kind = m.get("media_kind")
            if kind:
                text = f"[{kind}]"
            else:
                continue
        role: HistoryRole = "owner" if m.get("is_diana") else "vip"
        mid = m.get("id")
        ts_raw = m.get("date")
        ts: datetime | None = None
        if isinstance(ts_raw, datetime):
            ts = ts_raw
        elif isinstance(ts_raw, str) and ts_raw.strip():
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                ts = None
        out.append(
            HistoryLine(
                role=role,
                text=text,
                telegram_message_id=int(mid) if mid is not None else None,
                timestamp=ts,
            )
        )
    return out


class VipHistorySeedService:
    """Import recent VIP DM history into durable message_history once."""

    def __init__(
        self,
        *,
        history: MessageHistoryWriter,
        fetcher: VipHistoryFetcher | None,
        limit: int = 20,
        notifier: OwnerNotifierPort | None = None,
    ) -> None:
        self._history = history
        self._fetcher = fetcher
        self._limit = max(1, int(limit))
        self._notifier = notifier

    @property
    def enabled(self) -> bool:
        return self._fetcher is not None

    async def seed_for_new_vip(
        self,
        telegram_user_id: int,
        *,
        username: str | None = None,
    ) -> SeedOutcome:
        """Fetch recent personal-chat history and append what is missing.

        Import is always attempted and idempotent: rows whose
        ``telegram_message_id`` is already in ``message_history`` are skipped,
        so a chat that already holds system messages (atencion channel turns,
        bot/owner replies from the same day) still receives the missing
        pre-existing history instead of being skipped as "already imported".
        Returns a structured outcome.
        """
        uid = int(telegram_user_id)
        if self._fetcher is None:
            logger.info(
                "vip_history_seed_disabled",
                extra={"telegram_user_id": uid},
            )
            return SeedOutcome(kind="disabled", count=0, telegram_user_id=uid)

        # chat_id for private DM with VIP is the Telegram user id.
        chat_id = uid
        lines = await self._fetcher.fetch_recent(
            chat_id, limit=self._limit, username=username
        )
        if not lines:
            logger.info(
                "vip_history_seed_empty",
                extra={"chat_id": chat_id, "telegram_user_id": uid},
            )
            return SeedOutcome(kind="ok", count=0, telegram_user_id=uid)

        rows = [
            (line.role, line.text, line.telegram_message_id, line.timestamp)
            for line in lines
        ]
        append_missing = getattr(self._history, "append_missing", None)
        if callable(append_missing):
            added = await append_missing(chat_id, rows=rows)
        else:
            # Fallback for minimal writers without dedup support: plain append
            # (pre-dedup behavior) — production always uses append_missing.
            for line in lines:
                await self._history.append(
                    chat_id,
                    role=line.role,
                    text=line.text,
                    telegram_message_id=line.telegram_message_id,
                    timestamp=line.timestamp,
                )
            added = len(lines)
        logger.info(
            "vip_history_seeded",
            extra={
                "chat_id": chat_id,
                "telegram_user_id": uid,
                "count": len(lines),
                "added": added,
            },
        )
        return SeedOutcome(kind="ok", count=added, telegram_user_id=uid)

    def schedule_seed_for_new_vip(
        self,
        telegram_user_id: int,
        *,
        username: str | None = None,
    ) -> None:
        """Fire-and-forget seed after VIP allowlist add (never blocks owner UX)."""
        if self._fetcher is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "vip_history_seed_no_loop",
                extra={"telegram_user_id": telegram_user_id},
            )
            return
        loop.create_task(
            self._seed_safe(telegram_user_id, username=username),
            name=f"vip-history-seed-{telegram_user_id}",
        )

    async def _seed_safe(
        self,
        telegram_user_id: int,
        *,
        username: str | None,
    ) -> None:
        uid = int(telegram_user_id)
        try:
            outcome = await self.seed_for_new_vip(uid, username=username)
        except Exception:
            logger.exception(
                "vip_history_seed_failed",
                extra={"telegram_user_id": uid},
            )
            outcome = SeedOutcome(kind="failed", count=0, telegram_user_id=uid)
        await self._notify_owner(outcome)

    async def _notify_owner(self, outcome: SeedOutcome) -> None:
        if self._notifier is None:
            return
        try:
            await self._notifier.notify_info(outcome.owner_message())
        except Exception:
            logger.exception(
                "vip_history_seed_notify_failed",
                extra={"telegram_user_id": outcome.telegram_user_id},
            )


__all__ = [
    "HistoryLine",
    "SeedOutcome",
    "VipHistoryFetcher",
    "VipHistorySeedService",
    "map_raw_messages_to_lines",
]
