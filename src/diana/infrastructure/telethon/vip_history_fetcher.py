"""Telethon adapter: fetch recent DM history with a VIP (personal account)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from diana.application.vip_history_seed import HistoryLine, map_raw_messages_to_lines

logger = logging.getLogger("diana.infrastructure.telethon")

_FLOOD_WAIT_MAX_RETRIES = 5
_SESSION_LOCK = asyncio.Lock()

# Tope de peso para traer la media del historial: un archivo más grande no se
# descarga (describirlo no justifica la espera ni el costo).
_MAX_MEDIA_BYTES = 20 * 1024 * 1024


def _media_kind(msg: object) -> str | None:
    media = getattr(msg, "media", None)
    if not media:
        return None
    type_name = type(media).__name__
    if type_name == "MessageMediaPhoto":
        return "foto"
    if type_name == "MessageMediaDocument":
        doc = getattr(media, "document", None)
        if doc:
            for attr in getattr(doc, "attributes", ()) or ():
                attr_name = type(attr).__name__
                if attr_name == "DocumentAttributeVideo":
                    if getattr(attr, "round_message", False):
                        return "video circular"
                    return "video"
                if attr_name == "DocumentAttributeAudio":
                    if getattr(attr, "voice", False):
                        return "nota de voz"
                    return "audio"
                if attr_name == "DocumentAttributeSticker":
                    return "sticker"
                if attr_name == "DocumentAttributeAnimated":
                    return "gif"
        return "documento"
    return "multimedia"


async def _message_to_record(msg: object, diana_id: int) -> dict:
    text = (
        getattr(msg, "text", None)
        or getattr(msg, "message", None)
        or getattr(msg, "caption", None)
        or ""
    ).strip()
    media_kind = _media_kind(msg) if getattr(msg, "media", None) else None
    sender_id = getattr(msg, "sender_id", None)
    is_out = bool(getattr(msg, "out", False))
    return {
        "id": getattr(msg, "id", None),
        "date": (
            msg.date.isoformat()
            if getattr(msg, "date", None) is not None
            else None
        ),
        "sender_id": sender_id,
        "text": text,
        "is_diana": bool(is_out or (sender_id == diana_id)),
        "media_kind": media_kind,
    }


async def _resolve_entity(client: object, user_id: int, username: str | None) -> object:
    errors: list[str] = []
    for spec in (user_id, f"@{username}" if username else None):
        if spec is None:
            continue
        try:
            return await client.get_entity(spec)  # type: ignore[attr-defined]
        except Exception as exc:
            errors.append(f"{spec}: {type(exc).__name__}: {exc}")

    async for dialog in client.iter_dialogs():  # type: ignore[attr-defined]
        entity = dialog.entity
        if getattr(entity, "id", None) == user_id:
            return entity

    detail = "; ".join(errors) if errors else "sin intentos previos"
    raise ValueError(
        f"Could not resolve VIP entity user_id={user_id} "
        f"(username={username!r}). {detail}"
    )


async def _attach_media(client: object, msg: object, record: dict) -> bool:
    """Descarga la media del mensaje (en memoria) y la adjunta al registro.

    Devuelve True solo si se obtuvo contenido. La iteración va del mensaje más
    nuevo al más viejo, así que las primeras medias que aparecen son las
    últimas que mandó el VIP — que son las que interesan.
    """
    file_info = getattr(msg, "file", None)
    size = getattr(file_info, "size", None)
    if isinstance(size, int) and size > _MAX_MEDIA_BYTES:
        logger.info("telethon_media_skipped_too_large", extra={"size": size})
        return False
    try:
        data = await client.download_media(msg, file=bytes)  # type: ignore[attr-defined]
    except Exception as exc:
        logger.warning(
            "telethon_media_download_failed",
            extra={"error_type": type(exc).__name__},
        )
        return False
    if not data:
        return False
    record["media_bytes"] = bytes(data)
    record["media_mime"] = str(getattr(file_info, "mime_type", "") or "")
    return True


async def _fetch_raw_messages(
    client: object, entity: object, limit: int, media_limit: int = 0
) -> list[dict]:
    from telethon.errors import FloodWaitError

    me = await client.get_me()  # type: ignore[attr-defined]
    diana_id = me.id
    retries = 0
    while True:
        try:
            newest_first: list[dict] = []
            pending_media = max(0, int(media_limit))
            async for msg in client.iter_messages(entity, limit=limit):  # type: ignore[attr-defined]
                if msg is None:
                    continue
                record = await _message_to_record(msg, diana_id)
                if pending_media and record.get("media_kind"):
                    if await _attach_media(client, msg, record):
                        pending_media -= 1
                newest_first.append(record)
            newest_first.reverse()  # chronological oldest → newest
            return newest_first
        except FloodWaitError as exc:
            retries += 1
            if retries > _FLOOD_WAIT_MAX_RETRIES:
                raise
            logger.warning(
                "telethon_flood_wait",
                extra={"seconds": exc.seconds, "attempt": retries},
            )
            await asyncio.sleep(exc.seconds)


class TelethonVipHistoryFetcher:
    """Connect with user session → fetch → disconnect (serialized)."""

    def __init__(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_path: str | Path,
        media_limit: int = 0,
    ) -> None:
        self._media_limit = max(0, int(media_limit))
        self._api_id = int(api_id)
        self._api_hash = str(api_hash)
        path = Path(session_path)
        # TelegramClient session name is path without .session suffix.
        if path.suffix == ".session":
            path = path.with_suffix("")
        self._session = str(path)

    async def fetch_recent(
        self,
        user_id: int,
        *,
        limit: int,
        username: str | None = None,
    ) -> list[HistoryLine]:
        from telethon import TelegramClient

        # One Telethon session at a time (SQLite session file).
        async with _SESSION_LOCK:
            client = TelegramClient(self._session, self._api_id, self._api_hash)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    raise RuntimeError(
                        f"Telethon session not authorized: {self._session}.session"
                    )
                entity = await _resolve_entity(client, user_id, username)
                raw = await _fetch_raw_messages(
                    client, entity, limit, self._media_limit
                )
                return map_raw_messages_to_lines(raw)
            finally:
                await client.disconnect()


__all__ = ["TelethonVipHistoryFetcher"]
