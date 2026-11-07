"""Horario de atención — la ventana en la que Diana responde (AGENTS §4.27).

Fuera de la ventana configurada Diana no contesta a los VIP ni dispara
recontactos; los mensajes se guardan y se retoman al abrir. Esos mensajes **no
crean turno**, así que no tocan métricas ni confianza.

Este módulo es puro a propósito: parseo, validación y evaluación de la ventana,
sin base de datos, sin aiogram y sin reloj global (``ahora`` siempre se recibe).
La lectura del ajuste y su caché viven en :class:`HorarioAtencionService`, que
solo depende de un puerto.

Regla de seguridad: si el ajuste no se puede leer o viene roto, el sistema se
comporta como **abierto** (fail-open). Un hipo de base de datos no puede dejar a
todos los VIP sin respuesta.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from time import monotonic
from typing import Any, Mapping, Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger("diana.application")

#: Clave del bloque en ``system_config``.
CLAVE_HORARIO = "horario_atencion"

ZONA_POR_DEFECTO = "America/Mexico_City"
APERTURA_POR_DEFECTO = "09:00"
CIERRE_POR_DEFECTO = "23:00"

_HORA_VALIDA = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

#: TTL de la caché del ajuste, en segundos. Corto: el panel invalida al guardar,
#: así que este valor solo cubre cambios hechos fuera del panel.
_TTL_POR_DEFECTO = 30.0


def parsear_hora(texto: object) -> time | None:
    """``"HH:MM"`` → ``time``; ``None`` si no tiene ese formato."""
    if not isinstance(texto, str):
        return None
    limpio = texto.strip()
    if not _HORA_VALIDA.match(limpio):
        return None
    hora, minuto = limpio.split(":")
    return time(int(hora), int(minuto))


def formatear_hora(valor: time) -> str:
    """``time`` → ``"HH:MM"`` (formato del panel y de ``system_config``)."""
    return f"{valor.hour:02d}:{valor.minute:02d}"


def _asegurar_utc(valor: datetime) -> datetime:
    return valor.replace(tzinfo=UTC) if valor.tzinfo is None else valor


@dataclass(frozen=True, slots=True)
class HorarioAtencion:
    """Ventana de atención ya validada.

    - ``activo = False`` → 24 horas (comportamiento previo, byte a byte).
    - ``apertura < cierre`` → ventana normal del mismo día.
    - ``apertura > cierre`` → ventana que cruza la medianoche (21:00 → 03:00).
    - ``apertura == cierre`` → sin restricción efectiva (se trata como abierto).
    """

    activo: bool = False
    zona_horaria: str = ZONA_POR_DEFECTO
    apertura: time = time(9, 0)
    cierre: time = time(23, 0)
    pausa_manual_hasta: datetime | None = None

    # -- construcción -----------------------------------------------------

    @classmethod
    def desde_config(cls, raw: Mapping[str, Any] | None) -> HorarioAtencion:
        """Construye desde el blob de ``system_config``; tolerante a basura.

        Cualquier campo inválido cae a su valor por defecto y el horario queda
        como está configurado el resto. Un blob ausente o que no sea un objeto
        produce el horario **desactivado** (24 horas).
        """
        if not isinstance(raw, Mapping):
            return cls()
        apertura = parsear_hora(raw.get("apertura")) or time(9, 0)
        cierre = parsear_hora(raw.get("cierre")) or time(23, 0)
        zona = raw.get("zona_horaria")
        if not isinstance(zona, str) or not _zona_valida(zona):
            zona = ZONA_POR_DEFECTO
        pausa = raw.get("pausa_manual_hasta")
        pausa_dt: datetime | None = None
        if isinstance(pausa, datetime):
            pausa_dt = _asegurar_utc(pausa)
        elif isinstance(pausa, str):
            try:
                pausa_dt = _asegurar_utc(datetime.fromisoformat(pausa))
            except ValueError:
                pausa_dt = None
        return cls(
            activo=bool(raw.get("activo", False)),
            zona_horaria=zona,
            apertura=apertura,
            cierre=cierre,
            pausa_manual_hasta=pausa_dt,
        )

    def a_config(self) -> dict[str, Any]:
        """Serializa al formato JSONB que guarda ``system_config``."""
        return {
            "activo": self.activo,
            "zona_horaria": self.zona_horaria,
            "apertura": formatear_hora(self.apertura),
            "cierre": formatear_hora(self.cierre),
            "pausa_manual_hasta": (
                self.pausa_manual_hasta.isoformat()
                if self.pausa_manual_hasta is not None
                else None
            ),
        }

    # -- evaluación -------------------------------------------------------

    @property
    def zona(self) -> ZoneInfo:
        """Zona horaria resuelta (cae a la de por defecto si no existe)."""
        try:
            return ZoneInfo(self.zona_horaria)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo(ZONA_POR_DEFECTO)

    def en_pausa_manual(self, ahora: datetime) -> bool:
        """True si la dueña canceló el descanso por un rato."""
        if self.pausa_manual_hasta is None:
            return False
        return _asegurar_utc(ahora) < self.pausa_manual_hasta

    def esta_abierto(self, ahora: datetime) -> bool:
        """¿Corresponde responder en este instante?"""
        if not self.activo:
            return True
        if self.en_pausa_manual(ahora):
            return True
        if self.apertura == self.cierre:
            return True
        hora_local = _asegurar_utc(ahora).astimezone(self.zona).time()
        if self.apertura < self.cierre:
            return self.apertura <= hora_local < self.cierre
        # Cruza la medianoche: 21:00 → 03:00 significa >= 21:00 o < 03:00.
        return hora_local >= self.apertura or hora_local < self.cierre

    def proxima_apertura(self, ahora: datetime) -> datetime | None:
        """Instante (UTC) de la próxima apertura, o ``None`` si ya está abierto."""
        ahora_utc = _asegurar_utc(ahora)
        if self.esta_abierto(ahora_utc):
            return None
        local = ahora_utc.astimezone(self.zona)
        for adelanto in (0, 1, 2):
            dia = local.date() + timedelta(days=adelanto)
            candidato = datetime.combine(dia, self.apertura, tzinfo=self.zona)
            if candidato > local:
                return candidato.astimezone(UTC)
        return None  # inalcanzable con una ventana válida


def _zona_valida(nombre: str) -> bool:
    try:
        ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def validar_horario(raw: Mapping[str, Any] | None) -> str | None:
    """Valida el blob que llega del panel. Devuelve el error o ``None``.

    Los mensajes son de negocio (los lee la dueña), no técnicos.
    """
    if raw is None or not isinstance(raw, Mapping):
        return "No se recibió un horario."
    for campo, etiqueta in (("apertura", "la hora de apertura"), ("cierre", "la hora de cierre")):
        valor = raw.get(campo)
        if valor in (None, ""):
            continue
        if parsear_hora(valor) is None:
            return f"La {etiqueta} debe escribirse como HH:MM (por ejemplo 09:00)."
    zona = raw.get("zona_horaria")
    if zona not in (None, "") and not isinstance(zona, str):
        return "La zona horaria debe ser un texto."
    if isinstance(zona, str) and zona and not _zona_valida(zona):
        return "Esa zona horaria no existe. Usa una como America/Mexico_City."
    return None


@runtime_checkable
class HorarioConfigStore(Protocol):
    """Puerto de lectura/escritura del ajuste (lo implementa system_config)."""

    async def get_horario_atencion(self) -> dict[str, Any]: ...

    async def set_horario_atencion(self, value: dict[str, Any]) -> None: ...


class HorarioAtencionService:
    """Lee el ajuste con caché corta y responde ``está abierto``/``no``.

    Fail-open: cualquier fallo de lectura devuelve un horario **desactivado**,
    es decir, se responde como antes. Nunca deja a los VIP sin respuesta por un
    problema de base de datos.
    """

    def __init__(
        self,
        store: HorarioConfigStore,
        *,
        enabled: bool = True,
        ttl_s: float = _TTL_POR_DEFECTO,
    ) -> None:
        self._store = store
        self._enabled = enabled
        self._ttl = ttl_s
        self._cache: HorarioAtencion | None = None
        self._cache_en: float | None = None

    @property
    def habilitado(self) -> bool:
        return self._enabled

    def invalidate(self) -> None:
        """Olvida el valor cacheado (se llama al guardar desde el panel)."""
        self._cache = None
        self._cache_en = None

    async def estado(self) -> HorarioAtencion:
        """Horario vigente (cacheado ``ttl_s`` segundos)."""
        if not self._enabled:
            return HorarioAtencion()
        ahora = monotonic()
        if self._cache is not None and self._cache_en is not None:
            if ahora - self._cache_en < self._ttl:
                return self._cache
        try:
            raw = await self._store.get_horario_atencion()
        except Exception:
            logger.exception("horario_atencion_read_failed")
            return HorarioAtencion()
        horario = HorarioAtencion.desde_config(raw)
        self._cache = horario
        self._cache_en = ahora
        return horario

    async def esta_abierto(self, ahora: datetime) -> bool:
        """Atajo: evalúa la ventana contra ``ahora``."""
        return (await self.estado()).esta_abierto(ahora)

    async def guardar(self, raw: Mapping[str, Any]) -> HorarioAtencion:
        """Valida y persiste lo que falte, conservando el resto del ajuste."""
        error = validar_horario(raw)
        if error is not None:
            raise ValueError(error)
        previo = await self._store.get_horario_atencion()
        horario = HorarioAtencion.desde_config({**previo, **dict(raw)})
        await self._store.set_horario_atencion(horario.a_config())
        self.invalidate()
        return horario


__all__ = [
    "APERTURA_POR_DEFECTO",
    "CIERRE_POR_DEFECTO",
    "CLAVE_HORARIO",
    "HorarioAtencion",
    "HorarioAtencionService",
    "HorarioConfigStore",
    "ZONA_POR_DEFECTO",
    "formatear_hora",
    "parsear_hora",
    "validar_horario",
]
