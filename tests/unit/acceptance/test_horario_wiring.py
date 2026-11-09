"""F6 — el horario de atención queda cableado de punta a punta (AGENTS §4.27).

No prueba la lógica (ya cubierta en unitarios): prueba que el servicio llega
hasta donde tiene que llegar. Es la clase de fallo que dejó el botón muerto
(`NameError` por un servicio que no se reenviaba).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, Message, User

from diana.application.horario_atencion import HorarioAtencion, HorarioAtencionService
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryTurnStore,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.telegram.middlewares.horario import HorarioAtencionMiddleware
from diana.telegram.setup import build_dispatcher


def _mensaje(chat_id: int = 555) -> Message:
    return Message(
        message_id=9,
        date=0,
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=chat_id, is_bot=False, first_name="Vip"),
        text="hola",
        business_connection_id="bc-1",
    )


class _Store:
    def __init__(self, valor=None) -> None:
        self.valor = valor or {}

    async def get_horario_atencion(self):
        return dict(self.valor)

    async def set_horario_atencion(self, value):
        self.valor = dict(value)


def _wiring(*, horario=None, enabled=True, history=None):
    deliveries = InMemoryPendingDeliveryStore()
    behavior = BehaviorEngine(
        FakeTelegramActuator(),
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(
        InMemoryTurnStore(), InMemoryPendingApprovalStore(), behavior
    )
    return build_dispatcher(
        orchestrator=MagicMock(),
        admin=MagicMock(),
        coordinator=coordinator,
        escalations=InMemoryEscalationStore(),
        notifier=FakeOwnerNotifier(),
        behavior=behavior,
        vips=MagicMock(),
        owner_telegram_id=999001,
        forbidden_keywords=["x"],
        horario=horario,
        feature_business_hours_enabled=enabled,
        history=history,
    )


def _gate(wiring) -> HorarioAtencionMiddleware:
    return next(
        m for m in wiring.registered_middlewares
        if isinstance(m, HorarioAtencionMiddleware)
    )


def test_la_compuerta_recibe_el_servicio_y_respeta_la_bandera():
    servicio = HorarioAtencionService(_Store())
    wiring = _wiring(horario=servicio)
    gate = _gate(wiring)
    assert gate._horario is servicio
    assert gate._enabled is True


def test_bandera_apagada_deja_la_compuerta_inerte():
    wiring = _wiring(horario=HorarioAtencionService(_Store()), enabled=False)
    assert _gate(wiring)._enabled is False


def test_sin_servicio_la_compuerta_queda_inerte():
    """Nunca debe romper el arranque por no tener el servicio cableado."""
    assert _gate(_wiring(horario=None))._enabled is False


def test_la_compuerta_usa_el_historial_cableado():
    historial = MagicMock()
    wiring = _wiring(horario=HorarioAtencionService(_Store()), history=historial)
    assert _gate(wiring)._history is historial


@pytest.mark.asyncio
async def test_extremo_a_extremo_fuera_de_horario_no_llama_al_handler():
    """Servicio real + configuración cerrada → el mensaje no pasa."""
    store = _Store(
        {
            "activo": True,
            "zona_horaria": "America/Mexico_City",
            "apertura": "09:00",
            "cierre": "23:00",
        }
    )
    historial = MagicMock()
    historial.upsert_vip_message = AsyncMock()
    gate = _gate(_wiring(horario=HorarioAtencionService(store), history=historial))
    # 10:00 UTC = 04:00 en CDMX: cerrado.
    gate._clock = lambda: datetime(2026, 11, 9, 10, 0, tzinfo=UTC)

    handler = AsyncMock(return_value="paso")
    evento = _mensaje()
    data = {"vip_id": "v", "business_connection_id": "bc-1"}

    assert await gate(handler, evento, data) is None
    handler.assert_not_called()
    historial.upsert_vip_message.assert_awaited_once()

    # Dentro de la ventana (15:00 UTC = 09:00 local) sí pasa.
    gate._clock = lambda: datetime(2026, 11, 9, 15, 0, tzinfo=UTC)
    assert await gate(handler, evento, data) == "paso"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_el_panel_y_la_compuerta_comparten_el_mismo_ajuste():
    """Guardar desde el panel se refleja en la compuerta al instante."""
    store = _Store()
    servicio = HorarioAtencionService(store)
    gate = _gate(_wiring(horario=servicio))

    # El panel guarda la ventana y la enciende.
    await servicio.guardar({"activo": True, "apertura": "09:00", "cierre": "23:00"})

    assert (await servicio.estado()).activo is True
    gate._clock = lambda: datetime(2026, 11, 9, 10, 0, tzinfo=UTC)  # 04:00 local
    handler = AsyncMock(return_value="paso")
    evento = _mensaje()
    assert await gate(
        handler, evento, {"vip_id": "v", "business_connection_id": "b"}
    ) is None
    handler.assert_not_called()


def test_la_ventana_por_defecto_es_24_horas():
    """Recién instalado, el horario no cambia nada (decisión de producto)."""
    estado = HorarioAtencion.desde_config(_Store().valor)
    assert estado.activo is False
    assert estado.esta_abierto(datetime(2026, 11, 9, 10, 0, tzinfo=UTC)) is True
