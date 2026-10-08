"""Seed VIP message_history from personal-account chat history (Telethon).

Product: when a VIP is added, import recent DM history so the cognitive
pipeline has context on the first live turn. Does not run inside Director.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, Protocol

from diana.application.image_vision_service import ImageVisionService
from diana.application.media_text import compose_media_text
from diana.application.ports import MessageHistoryWriter, OwnerNotifierPort
from diana.application.video_vision_service import VideoVisionService
from diana.application.vip_opening import OpeningOutcome, VipOpeningService
from diana.infrastructure.vision.ocr import detect_image_mime

logger = logging.getLogger("diana.application")

HistoryRole = Literal["vip", "owner"]
SeedKind = Literal["disabled", "ok", "failed"]


@dataclass(frozen=True, slots=True)
class HistoryLine:
    """One seeded history row (V2 role vocabulary).

    ``media_bytes`` trae el archivo que el VIP mandó antes de estar en la lista
    (solo para los últimos mensajes con media). Se usa para describirlo con la
    visión y se descarta: nunca se persiste.
    """

    role: HistoryRole
    text: str
    telegram_message_id: int | None = None
    timestamp: datetime | None = None
    caption: str = ""
    media_kind: str | None = None
    media_bytes: bytes | None = None
    media_mime: str = ""


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
        caption = (m.get("text") or "").strip()
        kind = m.get("media_kind")
        text = caption
        if not text:
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
                caption=caption,
                media_kind=kind,
                media_bytes=m.get("media_bytes"),
                media_mime=str(m.get("media_mime") or ""),
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
        disabled_reason: str | None = None,
        image_vision: ImageVisionService | None = None,
        video_vision: VideoVisionService | None = None,
        opening: VipOpeningService | None = None,
    ) -> None:
        self._history = history
        self._fetcher = fetcher
        self._limit = max(1, int(limit))
        self._notifier = notifier
        # Visión para la media importada: sin ella la foto o el video del
        # historial quedan como una etiqueta muda.
        self._image_vision = image_vision
        self._video_vision = video_vision
        # Arranque de conversación: se dispara después de importar el historial.
        self._opening = opening
        # Motivo por el que no hay importador (bandera apagada, configuración
        # ausente). Viaja a los logs para que el silencio nunca se lea como
        # "no había nada que importar".
        self._disabled_reason = disabled_reason
        # Tareas de importación vivas. Sin esta referencia una tarea en segundo
        # plano puede recolectarse a mitad de ejecución y desaparecer sin
        # importar ni avisar (mismo patrón que MemoryBackfillQueue).
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def enabled(self) -> bool:
        return self._fetcher is not None

    @property
    def disabled_reason(self) -> str:
        """Motivo por el que el importador no está disponible (nunca vacío)."""
        return self._disabled_reason or "no_fetcher"

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
                extra={"telegram_user_id": uid, "reason": self.disabled_reason},
            )
            return SeedOutcome(kind="disabled", count=0, telegram_user_id=uid)

        # chat_id for private DM with VIP is the Telegram user id.
        chat_id = uid
        lines = await self._fetcher.fetch_recent(
            chat_id, limit=self._limit, username=username
        )
        known = await self._known_message_ids(chat_id)
        lines = await self._describe_media(lines, known=known)
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

    async def _known_message_ids(self, chat_id: int) -> set[int]:
        """Ids que ya están en el historial del chat.

        Lo que ya está guardado no se vuelve a describir: la importación no
        reescribe esas filas, así que describirlas otra vez solo gasta cuota.
        """
        reader = getattr(self._history, "get_recent", None)
        if not callable(reader):
            return set()
        try:
            rows = await reader(chat_id, limit=self._limit)
        except Exception:
            logger.exception(
                "vip_history_seed_known_read_failed", extra={"chat_id": chat_id}
            )
            return set()
        return {
            int(row["telegram_message_id"])
            for row in rows
            if isinstance(row, dict) and row.get("telegram_message_id") is not None
        }

    async def _describe_media(
        self, lines: list[HistoryLine], *, known: set[int] | None = None
    ) -> list[HistoryLine]:
        """Cambia la etiqueta muda de la media importada por su descripción.

        Un fallo de la visión deja la etiqueta como estaba: el historial entra
        igual, solo que sin el contenido de esa foto o ese video.
        """
        if self._image_vision is None and self._video_vision is None:
            return lines
        already = known or set()
        return [await self._describe_line(line, known=already) for line in lines]

    async def _describe_line(
        self, line: HistoryLine, *, known: set[int] | None = None
    ) -> HistoryLine:
        data = line.media_bytes
        if not data or line.role != "vip":
            return line
        if line.telegram_message_id is not None and line.telegram_message_id in (known or set()):
            return replace(line, media_bytes=None)
        kind = (line.media_kind or "").lower()
        try:
            if kind.startswith("foto") and self._image_vision is not None:
                result = await self._image_vision.analyze(
                    data, mime_type=detect_image_mime(data)
                )
                tag = "imagen"
            elif kind.startswith("video") and self._video_vision is not None:
                result = await self._video_vision.analyze(
                    data, mime_type=line.media_mime or "video/mp4"
                )
                tag = "video"
            else:
                return line
        except Exception as exc:
            logger.warning(
                "vip_history_media_describe_failed",
                extra={
                    "telegram_message_id": line.telegram_message_id,
                    "error_type": type(exc).__name__,
                },
            )
            return line
        if not result.enabled:
            return line
        text = compose_media_text(result, tag=tag, caption=line.caption)
        return replace(line, text=text, media_bytes=None)

    def schedule_seed_for_new_vip(
        self,
        telegram_user_id: int,
        *,
        username: str | None = None,
    ) -> None:
        """Fire-and-forget seed after VIP allowlist add (never blocks owner UX)."""
        if self._fetcher is None:
            # El alta sigue su curso, pero el intento queda registrado con su
            # motivo: apagado a propósito no es lo mismo que no tener nada que
            # importar, y un registro ausente no debe parecer un éxito.
            logger.info(
                "vip_history_seed_skipped_disabled",
                extra={
                    "telegram_user_id": int(telegram_user_id),
                    "reason": self.disabled_reason,
                },
            )
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "vip_history_seed_no_loop",
                extra={"telegram_user_id": telegram_user_id},
            )
            return
        task = loop.create_task(
            self._seed_safe(telegram_user_id, username=username),
            name=f"vip-history-seed-{telegram_user_id}",
        )
        # La referencia se sostiene hasta que la tarea termina: si se suelta
        # antes, la tarea puede morir en silencio (conecta con Telegram y no
        # importa ni avisa, que es exactamente lo que se observó en producción).
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

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
        opening = await self._start_opening(uid, outcome)
        await self._notify_owner(outcome, opening=opening)

    async def _start_opening(
        self, uid: int, outcome: SeedOutcome
    ) -> OpeningOutcome | None:
        """Arranca la conversación con lo que quedó sin responder.

        Un fallo aquí no puede tumbar la importación: el historial ya entró.
        """
        if self._opening is None or outcome.kind != "ok":
            return None
        try:
            return await self._opening.start(uid)
        except Exception:
            logger.exception("vip_opening_failed", extra={"telegram_user_id": uid})
            return None

    async def _notify_owner(
        self, outcome: SeedOutcome, *, opening: OpeningOutcome | None = None
    ) -> None:
        if self._notifier is None:
            return
        text = outcome.owner_message()
        if opening is not None and opening.kind == "started":
            text = (
                f"{text} Además quedó un borrador en tu cola de aprobación con "
                "los mensajes que habían quedado sin responder."
            )
        try:
            await self._notifier.notify_info(text)
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
