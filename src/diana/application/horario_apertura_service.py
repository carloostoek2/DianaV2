"""Barrido de apertura del horario de atención (AGENTS §4.27).

Cuando la ventana abre, Diana retoma lo que le escribieron mientras estaba en
silencio: arma **un** turno normal con la ráfaga pendiente, así que ese turno
se decide como cualquier otro (autónomo si corresponde, si no a la cola de la
dueña).

No inventa nada: los mensajes ya están en el historial del chat porque la
compuerta de entrada los guardó. Este servicio solo mira quién quedó con la
palabra y dispara el pipeline.

Reglas de seguridad:

- se salta VIP congelado, pausado, sin conexión de negocios vigente, o con un
  turno vivo (incluida una aprobación esperando);
- si la ráfaga trae una etiqueta de media sin descripción, marca
  ``media_unverified`` para que ese turno nunca se mande solo (§4.22);
- si la ráfaga coincide con una palabra prohibida, **no** se procesa aquí: ese
  camino lo atiende la escalación determinística cuando el VIP vuelve a
  escribir. Se prefiere dejarlo pendiente antes que contestarlo por el pipeline
  normal.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol, Sequence, runtime_checkable
from uuid import UUID

from diana.application.horario_atencion import HorarioAtencionService
from diana.application.ports import (
    BusinessConnectionRecord,
    VipInboundMessage,
    VipRecord,
)
from diana.application.turn_orchestrator import format_vip_burst_text

logger = logging.getLogger("diana.application")

#: Ventana de historial que se mira para encontrar los mensajes sin responder.
_LIMITE_HISTORIAL = 40
#: No se resucitan mensajes más viejos que esto (una madrugada, no una semana).
_MAX_ANTIGUEDAD = timedelta(hours=24)

#: Etiqueta de media SIN descripción: `[imagen]` / `[video]` (con o sin álbum).
#: Con visión activa el texto guardado es `[imagen: ...]`, que no coincide.
_MEDIA_SIN_DESCRIPCION = re.compile(r"\[(?:imagen|video)(?: parte de álbum)?\]")


@dataclass(frozen=True, slots=True)
class ResultadoBarrido:
    """Qué hizo el barrido (para el log y las pruebas)."""

    revisados: int = 0
    abiertos: int = 0
    saltados: int = 0
    cerrado: bool = False
    motivo: str | None = None


@runtime_checkable
class VipTurnRunner(Protocol):
    async def handle_vip_message(self, incoming: VipInboundMessage) -> UUID: ...


@runtime_checkable
class RecentHistoryReader(Protocol):
    async def get_recent(self, chat_id: int, *, limit: int = 20) -> list[dict]: ...


@runtime_checkable
class VipLister(Protocol):
    async def list_active(self) -> list[VipRecord]: ...


@runtime_checkable
class ConnectionLookup(Protocol):
    async def get_active(self) -> BusinessConnectionRecord | None: ...


@runtime_checkable
class NonTerminalTurnReader(Protocol):
    async def list_non_terminal(self, chat_id: int) -> list[object]: ...


def _asegurar_utc(valor: datetime) -> datetime:
    return valor.replace(tzinfo=UTC) if valor.tzinfo is None else valor


def _fecha_fila(row: dict) -> datetime | None:
    """Timestamp de una fila del historial (ISO string o datetime)."""
    crudo = row.get("timestamp")
    if isinstance(crudo, datetime):
        return _asegurar_utc(crudo)
    if isinstance(crudo, str):
        try:
            return _asegurar_utc(datetime.fromisoformat(crudo))
        except ValueError:
            return None
    return None


def rafaga_pendiente(rows: list[dict], *, ahora: datetime) -> list[dict]:
    """Mensajes del VIP al final del historial, sin respuesta posterior.

    Descarta los que superan ``_MAX_ANTIGUEDAD`` (no se resucita un chat de la
    semana pasada) y devuelve el resto en orden cronológico.
    """
    limite = _asegurar_utc(ahora) - _MAX_ANTIGUEDAD
    pendientes: list[dict] = []
    for row in reversed(rows):
        if not isinstance(row, dict) or row.get("role") != "vip":
            break
        if not str(row.get("text") or "").strip():
            continue
        fecha = _fecha_fila(row)
        if fecha is not None and fecha < limite:
            continue
        pendientes.append(row)
    pendientes.reverse()
    return pendientes


def trae_media_sin_ver(textos: Sequence[str]) -> bool:
    """True si alguna línea es una etiqueta de media sin descripción."""
    return any(_MEDIA_SIN_DESCRIPCION.search(t) for t in textos)


class HorarioAperturaService:
    """Retoma al abrir la ventana los mensajes que quedaron sin responder."""

    def __init__(
        self,
        *,
        horario: HorarioAtencionService,
        runner: VipTurnRunner,
        history: RecentHistoryReader,
        vips: VipLister,
        connections: ConnectionLookup,
        coordinator: NonTerminalTurnReader,
        matcher_prohibidas: Callable[[str], Sequence[str]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._horario = horario
        self._runner = runner
        self._history = history
        self._vips = vips
        self._connections = connections
        self._coordinator = coordinator
        self._matcher = matcher_prohibidas
        self._clock = clock or (lambda: datetime.now(UTC))

    async def barrer(self) -> ResultadoBarrido:
        """Una pasada del barrido. Nunca lanza: devuelve el conteo."""
        ahora = _asegurar_utc(self._clock())
        try:
            if not await self._horario.esta_abierto(ahora):
                return ResultadoBarrido(cerrado=True, motivo="fuera_de_horario")
        except Exception:
            # Fail-open, igual que la compuerta de entrada.
            logger.exception("horario_apertura_check_failed")

        try:
            vips = await self._vips.list_active()
        except Exception:
            logger.exception("horario_apertura_vips_failed")
            return ResultadoBarrido(motivo="vips_no_disponibles")

        revisados = abiertos = saltados = 0
        for vip in vips:
            revisados += 1
            try:
                motivo = await self._procesar(vip, ahora)
            except Exception:
                logger.exception(
                    "horario_apertura_vip_error", extra={"vip_id": str(vip.id)}
                )
                saltados += 1
                continue
            if motivo is None:
                abiertos += 1
            elif motivo != "nada_pendiente":
                saltados += 1

        if abiertos:
            logger.info(
                "horario_apertura_barrido",
                extra={"revisados": revisados, "abiertos": abiertos, "saltados": saltados},
            )
        return ResultadoBarrido(
            revisados=revisados, abiertos=abiertos, saltados=saltados
        )

    async def _procesar(self, vip: VipRecord, ahora: datetime) -> str | None:
        """Devuelve ``None`` si arrancó un turno; si no, el motivo del salto."""
        if getattr(vip, "frozen_until", None) is not None:
            return "congelado"
        pausado = getattr(vip, "paused_until", None)
        if pausado is not None and _asegurar_utc(pausado) > ahora:
            return "pausado"

        chat_id = int(vip.telegram_user_id)
        vivos = await self._coordinator.list_non_terminal(chat_id)
        if vivos:
            return "chat_ocupado"

        rows = await self._history.get_recent(chat_id, limit=_LIMITE_HISTORIAL)
        pendientes = rafaga_pendiente(rows, ahora=ahora)
        if not pendientes:
            return "nada_pendiente"

        textos = [str(r.get("text") or "") for r in pendientes]
        if self._matcher is not None:
            coincidencias = self._matcher("\n".join(textos))
            if coincidencias:
                logger.info(
                    "horario_apertura_pendiente_prohibido",
                    extra={"vip_id": str(vip.id), "coincidencias": list(coincidencias)},
                )
                return "palabra_prohibida"

        conexion = await self._connections.get_active()
        if conexion is None:
            return "sin_conexion"

        ultimo = pendientes[-1]
        incoming = VipInboundMessage(
            chat_id=chat_id,
            text=format_vip_burst_text(textos, fallback=textos[-1]),
            # El id real hace que el historial se ACTUALICE (upsert) en vez de
            # duplicarse al re-escribir el mensaje.
            telegram_message_id=ultimo.get("telegram_message_id"),
            business_connection_id=conexion.business_connection_id,
            vip_id=vip.id,
            channel_type="vip",
            media_unverified=trae_media_sin_ver(textos),
        )
        await self._runner.handle_vip_message(incoming)
        logger.info(
            "horario_apertura_retomado",
            extra={
                "chat_id": chat_id,
                "vip_id": str(vip.id),
                "mensajes": len(pendientes),
                "media_sin_ver": incoming.media_unverified,
            },
        )
        return None


__all__ = [
    "HorarioAperturaService",
    "ResultadoBarrido",
    "rafaga_pendiente",
    "trae_media_sin_ver",
]
