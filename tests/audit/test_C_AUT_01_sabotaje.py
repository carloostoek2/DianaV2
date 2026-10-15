"""C-AUT-01 — comprobación de sabotaje (nivel E3) de las pruebas E2.

Prueba que cada escenario de ``tests/audit/test_C_AUT_01.py`` NO es decorativo:
se desconecta en tiempo de ejecución la pieza que sostiene la promesa
(``monkeypatch``, sin tocar código de producción) y se exige que la prueba real
FALLE. Si una prueba pasa igual con la pieza desconectada, no estaba midiendo
nada.

Se ejecuta la función de prueba real del módulo E2, con las mismas fixtures de
Postgres real, para que el sabotaje sea sobre el flujo real y no sobre una
copia. La última prueba es la inversa: si el hallazgo H-AUT1-2 se corrige
(rechequeo de ``paused_until`` en el camino autónomo), el ``xfail`` de S4b pasa
a verde.
"""

from __future__ import annotations

import pytest

import tests.audit.test_C_AUT_01 as caso
from diana.application.autonomous_mode_service import AutonomousModeService
from diana.application.turn_orchestrator import TurnOrchestrator
from diana.cognitive.decider import Decider
from diana.telegram.freeze_middleware import FreezeCheckMiddleware

VIP_SAB_1 = 999000981
VIP_SAB_2 = 999000982


async def _ams_siempre_abierto(self, vip_id=None):
    return True


async def _ams_siempre_cerrado(self, vip_id=None):
    return False


def _decider_siempre_envia(original):
    """Devuelve un `decide` que emite `send` aunque L1 esté apagado."""

    def _decide(self, evaluation, comprehension, **kwargs):
        decision = original(self, evaluation, comprehension, **kwargs)
        if decision.action != "send":
            return decision.model_copy(
                update={"action": "send", "reason": "autonomous_ok"}
            )
        return decision

    return _decide


async def _pass(self, handler, event, data):
    return await handler(event, data)


async def _nunca_congelado(self, vip_id):
    return False


@pytest.mark.db
@pytest.mark.asyncio
async def test_sabotaje_s1_corta_las_dos_guardas_de_l1_en_verdad(
    monkeypatch, engine, session_factory, alembic_applied
) -> None:
    """S1: L1 tiene DOS guardas (Decisor y AMS); hay que quitar las dos.

    Con una sola quitada la prueba sigue pasando — no porque sea decorativa,
    sino porque la otra guarda sostiene el fail-closed. Al quitar las dos, la
    prueba de L1 OFF debe reventar.
    """
    original = Decider.decide
    monkeypatch.setattr(Decider, "decide", _decider_siempre_envia(original))
    monkeypatch.setattr(AutonomousModeService, "is_autonomous_enabled", _ams_siempre_abierto)
    with pytest.raises(AssertionError):
        await caso.test_s1_l1_apagado_nada_sale_y_cae_en_la_cola(
            engine,
            session_factory,
            alembic_applied,
            global_mode="supervised",
            auto_send=True,
            chat_id=VIP_SAB_1,
        )


@pytest.mark.db
@pytest.mark.asyncio
async def test_sabotaje_s2_corta_ams_en_verdad(
    monkeypatch, engine, session_factory, alembic_applied
) -> None:
    """S2: con AMS siempre abierto, la prueba de L2 cerrado debe reventar."""
    monkeypatch.setattr(AutonomousModeService, "is_autonomous_enabled", _ams_siempre_abierto)
    with pytest.raises(AssertionError):
        await caso.test_s2_l2_cerrado_el_orquestador_demota_y_cae_en_la_cola(
            engine, session_factory, alembic_applied
        )


@pytest.mark.db
@pytest.mark.asyncio
async def test_sabotaje_s0_cierra_ams_en_verdad(
    monkeypatch, engine, session_factory, alembic_applied
) -> None:
    """S0: con AMS siempre cerrado, la prueba positiva debe reventar."""
    monkeypatch.setattr(AutonomousModeService, "is_autonomous_enabled", _ams_siempre_cerrado)
    with pytest.raises(AssertionError):
        await caso.test_s0_doble_puerta_abierta_entrega_sin_cola(
            engine,
            session_factory,
            alembic_applied,
            l2_por_vip=True,
            global_mode="supervised",
            chat_id=VIP_SAB_2,
        )


@pytest.mark.db
@pytest.mark.asyncio
async def test_sabotaje_s3_quita_congelado_en_verdad(
    monkeypatch, engine, session_factory, alembic_applied
) -> None:
    """S3: sin la puerta de congelado (entrada y motor), la prueba debe reventar."""
    monkeypatch.setattr(FreezeCheckMiddleware, "__call__", _pass)
    monkeypatch.setattr(TurnOrchestrator, "_is_vip_frozen", _nunca_congelado)
    with pytest.raises(AssertionError):
        await caso.test_s3_vip_congelado_no_entra_al_motor_y_no_hay_envio(
            engine, session_factory, alembic_applied
        )


@pytest.mark.db
@pytest.mark.asyncio
async def test_sabotaje_s4_quita_la_pausa_en_verdad(
    monkeypatch, engine, session_factory, alembic_applied
) -> None:
    """S4: sin la puerta de pausa en la entrada, la prueba debe reventar."""
    from diana.infrastructure.db.repositories import vips as repo_vips

    monkeypatch.setattr(repo_vips, "vip_is_allowed", lambda rec, now=None: True)
    with pytest.raises(AssertionError):
        await caso.test_s4_vip_pausado_queda_fuera_en_la_entrada_y_al_reanudar_entrega(
            engine, session_factory, alembic_applied
        )


@pytest.mark.db
@pytest.mark.asyncio
async def test_sabotaje_s5_quita_el_guard_de_vip_id_en_verdad(
    monkeypatch, engine, session_factory, alembic_applied
) -> None:
    """S5: AMS que ignora vip_id=None → la prueba de Atención debe reventar."""
    monkeypatch.setattr(AutonomousModeService, "is_autonomous_enabled", _ams_siempre_abierto)
    with pytest.raises(AssertionError):
        await caso.test_s5_atencion_con_l1_y_modo_global_nunca_es_autonomo(
            engine, session_factory, alembic_applied
        )


@pytest.mark.db
@pytest.mark.asyncio
async def test_sabotaje_s6_con_el_motor_cableado_la_prueba_revienta(
    monkeypatch, engine, session_factory, alembic_applied
) -> None:
    """S6: si el motor SÍ está cableado, el turno no puede quedar FAILED.

    La prueba se rompe sola (`_behavior = None`); el sabotaje deshace esa rotura
    en el momento de preparar el envío, reponiendo el motor real capturado al
    construir el contenedor.
    """
    capturado: dict[str, object] = {}
    build_original = caso.build_app

    def _build_capturando(*args, **kwargs):
        app = build_original(*args, **kwargs)
        capturado["behavior"] = app.behavior
        return app

    monkeypatch.setattr(caso, "build_app", _build_capturando)

    prepare_original = TurnOrchestrator._prepare_autonomous_send

    async def _con_el_motor(self, **kwargs):
        if self._behavior is None and capturado.get("behavior") is not None:
            self._behavior = capturado["behavior"]
        return await prepare_original(self, **kwargs)

    monkeypatch.setattr(TurnOrchestrator, "_prepare_autonomous_send", _con_el_motor)
    with pytest.raises(AssertionError):
        await caso.test_s6_sin_behavior_el_turno_falla_y_el_borrador_no_va_a_la_cola(
            engine, session_factory, alembic_applied
        )


@pytest.mark.db
@pytest.mark.asyncio
async def test_sabotaje_s4b_la_correccion_hace_pasar_la_prueba(
    monkeypatch, engine, session_factory, alembic_applied
) -> None:
    """S4b (xfail): si el camino autónomo rechequea la pausa, la prueba pasa.

    Es la comprobación inversa: el xfail no es un adorno, detecta la corrección.
    """
    original = TurnOrchestrator._prepare_autonomous_send

    async def _con_pausa(self, **kwargs):
        incoming = kwargs.get("incoming")
        if incoming is not None and await self._is_vip_paused(incoming.vip_id):
            await self._coordinator.mark_failed(kwargs["turn_id"], error="vip_paused")
            return None
        return await original(self, **kwargs)

    monkeypatch.setattr(TurnOrchestrator, "_prepare_autonomous_send", _con_pausa)
    # Sin excepción: el escenario se cumple con la corrección aplicada.
    await caso.test_s4b_ventana_pausa_a_mitad_del_turno_no_detiene_el_envio(
        engine, session_factory, alembic_applied
    )
