"""Vigilante de contratos — pruebas E2 por vigilante, contra Postgres real.

Cada vigilante se prueba **con el estado malo sembrado en la base** y con el estado que debe
quedar en silencio. No se asertó "se llamó a tal funcion": se ejecuta el servicio real contra
filas reales y se lee el aviso que saldria.

Por que cada negativo importa igual que su positivo: un vigilante que grita por datos viejos o
por rutas que son por diseno se termina ignorando, y eso es peor que no tener ninguno. Los
negativos de este archivo son justamente esas condiciones (la ventana de 2 dias, el filtro de
sesiones de prueba, y las tres exclusiones de V3), y cada uno tiene su sabotaje en el informe:
quitando esa condicion, la prueba cae.

Nota de aislamiento: el contenedor es de sesion y no se limpia por prueba, asi que **ningun
aserto es global** ("no hay alertas de nadie"): cada prueba siembra lo suyo y pregunta por lo
suyo (una tabla para V1, un id de turno para V2/V3/V7).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from diana.application.contract_watchdog_service import (
    ContractWatchdogService,
    WatchdogReport,
    leer_vigilantes,
)

pytestmark = pytest.mark.db

#: Ceros que se usan como "estado malo" del chequeo de huellas.
CERO_384 = "array_fill(0::real, ARRAY[384])::vector"


class _SandboxFake:
    """Doble del clasificador de sesiones de prueba (el real lee el journal del bot)."""

    def __init__(self, turnos: set[str] | None = None) -> None:
        self.turnos = turnos or set()
        self.llamado = False

    async def __call__(self, hours: int = 48) -> set[str]:
        self.llamado = True
        return set(self.turnos)


def _service(session_factory, sandbox: _SandboxFake | None = None, sql_path: Path | None = None):
    return ContractWatchdogService(
        session_factory,
        sandbox_turns=sandbox or _SandboxFake(),
        sql_path=sql_path,
    )


async def _correr(session_factory, sandbox: _SandboxFake | None = None, sql_path=None) -> WatchdogReport:
    return await _service(session_factory, sandbox, sql_path).revisar()


def _filas(report: WatchdogReport, vigilante_id: str) -> list[dict[str, Any]]:
    for alerta in report.alerts:
        if alerta.vigilante_id == vigilante_id:
            return [dict(fila) for fila in alerta.rows]
    return []


def _turnos(report: WatchdogReport, vigilante_id: str) -> set[str]:
    return {str(fila.get("turno")) for fila in _filas(report, vigilante_id)}


# ---------------------------------------------------------------------------
# Semillas
# ---------------------------------------------------------------------------


async def _seed_vip(session_factory, *, etiqueta: str) -> str:
    """Un VIP nuevo con id de Telegram unico (los tests no se limpian entre si)."""
    telegram_user_id = 990000000 + (uuid.uuid4().int % 9_000_000)
    async with session_factory() as session:
        fila = await session.execute(
            text(
                "insert into vips (telegram_user_id, display_name) "
                "values (:uid, :nombre) returning id"
            ),
            {"uid": telegram_user_id, "nombre": f"Prueba vigilante {etiqueta}"},
        )
        vip_id = str(fila.scalar_one())
        await session.commit()
    return vip_id


async def _seed_turn(
    session_factory,
    *,
    vip_id: str | None,
    chat_id: int,
    status: str,
    horas_atras: float = 3.0,
) -> str:
    creado = datetime.now(UTC) - timedelta(hours=horas_atras)
    async with session_factory() as session:
        fila = await session.execute(
            text(
                "insert into turns (chat_id, vip_id, status, created_at, updated_at) "
                "values (:chat, cast(:vip as uuid), :status, :creado, :creado) returning id"
            ),
            {"chat": chat_id, "vip": vip_id, "status": status, "creado": creado},
        )
        turn_id = str(fila.scalar_one())
        await session.commit()
    return turn_id


async def _seed_trace(
    session_factory,
    *,
    turn_id: str,
    chat_id: int,
    vip_id: str | None,
    decision: dict[str, Any],
    con_evaluacion: bool = True,
) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                "insert into pipeline_traces (turn_id, chat_id, vip_id, decision, evaluation) "
                "values (cast(:turno as uuid), :chat, cast(:vip as uuid), cast(:decision as jsonb), "
                "cast(:eval as jsonb))"
            ),
            {
                "turno": turn_id,
                "chat": chat_id,
                "vip": vip_id,
                "decision": _json(decision),
                "eval": _json({"naturalidad": 0.9}) if con_evaluacion else None,
            },
        )
        await session.commit()


async def _seed_outcome(
    session_factory,
    *,
    turn_id: str,
    vip_id: str,
    verdict: str = "send",
    draft_score: float | None = None,
    owner_outcome: str | None = None,
) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                "insert into turn_outcome_log (turn_id, vip_id, shadow_verdict, shadow_reason, "
                "owner_outcome, draft_score) values (cast(:turno as uuid), cast(:vip as uuid), "
                ":verdict, 'prueba', :owner, :nota)"
            ),
            {
                "turno": turn_id,
                "vip": vip_id,
                "verdict": verdict,
                "owner": owner_outcome,
                "nota": draft_score,
            },
        )
        await session.commit()


async def _seed_huella(session_factory, *, tabla: str, dias_atras: float) -> None:
    """Un registro con la huella en ceros. ``dias_atras`` decide si entra en la ventana."""
    creado = datetime.now(UTC) - timedelta(days=dias_atras)
    async with session_factory() as session:
        if tabla == "memories":
            vip_id = await _seed_vip(session_factory, etiqueta="huella")
            await session.execute(
                text(
                    "insert into memories (vip_id, embedding, content, category, confidence, "
                    "status, created_at) values (cast(:vip as uuid), "
                    f"{CERO_384}, cast(:cont as jsonb), 'identidad', 0.9, 'auto', :creado)"
                ),
                {
                    "vip": vip_id,
                    "cont": _json({"hecho": "prueba de huella en ceros"}),
                    "creado": creado,
                },
            )
        elif tabla == "contexts":
            await session.execute(
                text(
                    "insert into contexts (chat_id, embedding, content, expires_at, created_at) "
                    f"values (:chat, {CERO_384}, cast(:cont as jsonb), :vence, :creado)"
                ),
                {
                    "chat": 990000000 + (uuid.uuid4().int % 9_000_000),
                    "cont": _json({"tipo": "interpretado"}),
                    "vence": creado + timedelta(days=1),
                    "creado": creado,
                },
            )
        else:  # pragma: no cover - guard against typos in the tests
            raise AssertionError(f"tabla sin semilla: {tabla}")
        await session.commit()


def _json(valor: Any) -> str:
    import json

    return json.dumps(valor)


# ---------------------------------------------------------------------------
# V1 — huellas nuevas en ceros
# ---------------------------------------------------------------------------


async def test_v1_avisa_por_un_cero_nuevo(session_factory) -> None:
    await _seed_huella(session_factory, tabla="memories", dias_atras=0)

    report = await _correr(session_factory)

    filas = {fila["tabla"]: fila for fila in _filas(report, "V1")}
    assert "memories" in filas, f"V1 no aviso de un cero recien escrito: {report.as_dict()}"
    assert int(filas["memories"]["alerta"]) >= 1


async def test_v1_no_avisa_por_un_cero_viejo(session_factory) -> None:
    """La ventana de 2 dias es lo que evita que el aviso se repita todos los dias para siempre."""
    await _seed_huella(session_factory, tabla="contexts", dias_atras=30)

    report = await _correr(session_factory)

    tablas = {fila["tabla"] for fila in _filas(report, "V1")}
    assert "contexts" not in tablas, (
        "V1 conto un cero de hace 30 dias: el aviso volveria a sonar todos los dias"
    )


# ---------------------------------------------------------------------------
# V2 — turnos sin registro de lo que Diana habria decidido sola
# ---------------------------------------------------------------------------


async def test_v2_avisa_por_un_turno_sin_registro(session_factory) -> None:
    vip_id = await _seed_vip(session_factory, etiqueta="v2")
    chat_id = 991000000 + (uuid.uuid4().int % 9_000_000)
    turn_id = await _seed_turn(session_factory, vip_id=vip_id, chat_id=chat_id, status="delivered")
    await _seed_trace(session_factory, turn_id=turn_id, chat_id=chat_id, vip_id=vip_id, decision={})

    report = await _correr(session_factory)

    assert turn_id in _turnos(report, "V2"), f"V2 no aviso del turno sin registro: {report.as_dict()}"


async def test_v2_no_avisa_por_un_turno_de_sesion_de_prueba(session_factory) -> None:
    """El sandbox no persiste a proposito: si no se filtrara, cada prueba dispararia una alarma."""
    vip_id = await _seed_vip(session_factory, etiqueta="v2-sandbox")
    chat_id = 991100000 + (uuid.uuid4().int % 9_000_000)
    turn_id = await _seed_turn(session_factory, vip_id=vip_id, chat_id=chat_id, status="delivered")
    await _seed_trace(session_factory, turn_id=turn_id, chat_id=chat_id, vip_id=vip_id, decision={})

    sandbox = _SandboxFake({turn_id})
    report = await _correr(session_factory, sandbox)

    assert sandbox.llamado, "el vigilante no consulto las sesiones de prueba"
    assert turn_id not in _turnos(report, "V2"), "V2 conto como falla un turno de una prueba"
    assert report.skipped_sandbox >= 1


async def test_v2_sin_clasificador_de_sandbox_es_falla_y_no_silencio(session_factory) -> None:
    """Sin poder clasificar, el vigilante dice "no pude revisar" en vez de dar todo por bueno."""
    service = ContractWatchdogService(session_factory, sandbox_turns=None)

    report = await service.revisar()

    fallas = {falla.vigilante_id for falla in report.failures}
    assert "V2" in fallas, "V2 se cayo en silencio cuando no pudo clasificar las pruebas"
    mensaje = service.componer_mensaje(report)
    assert mensaje is not None and "No pude revisar" in mensaje


# ---------------------------------------------------------------------------
# V3 — escalaciones que nadie resolvio
# ---------------------------------------------------------------------------


async def _seed_v3(
    session_factory,
    *,
    accion: str = "approve",
    razon: str = "naturalidad",
    status: str = "escalated",
    respuesta_duena: bool = False,
) -> str:
    vip_id = await _seed_vip(session_factory, etiqueta="v3")
    chat_id = 992000000 + (uuid.uuid4().int % 9_000_000)
    turn_id = await _seed_turn(session_factory, vip_id=vip_id, chat_id=chat_id, status=status)
    await _seed_trace(
        session_factory,
        turn_id=turn_id,
        chat_id=chat_id,
        vip_id=vip_id,
        decision={"action": accion, "reason": razon},
    )
    await _seed_outcome(session_factory, turn_id=turn_id, vip_id=vip_id)
    if respuesta_duena:
        async with session_factory() as session:
            await session.execute(
                text(
                    "insert into message_history (chat_id, role, text, timestamp) "
                    "values (:chat, 'owner', 'respuesta de prueba', :cuando)"
                ),
                {"chat": chat_id, "cuando": datetime.now(UTC)},
            )
            await session.commit()
    return turn_id


async def test_v3_avisa_por_una_escalacion_que_nadie_resolvio(session_factory) -> None:
    turn_id = await _seed_v3(session_factory)

    report = await _correr(session_factory)

    assert turn_id in _turnos(report, "V3"), f"V3 no aviso de una escalacion sin resolver: {report.as_dict()}"


async def test_v3_no_avisa_por_un_saludo_de_plantilla(session_factory) -> None:
    turn_id = await _seed_v3(session_factory, razon="plantilla_saludo", status="delivered")

    report = await _correr(session_factory)

    assert turn_id not in _turnos(report, "V3"), "V3 conto un saludo de plantilla, que no pasa por la cola"


async def test_v3_no_avisa_por_un_envio_automatico(session_factory) -> None:
    turn_id = await _seed_v3(session_factory, accion="send", status="delivered")

    report = await _correr(session_factory)

    assert turn_id not in _turnos(report, "V3"), "V3 conto un envio automatico, que no lo decide la duena"


async def test_v3_no_avisa_cuando_la_duena_ya_respondio_en_el_chat(session_factory) -> None:
    """Decision de producto: responder en el chat deja el turno sin resolucion registrada."""
    turn_id = await _seed_v3(session_factory, respuesta_duena=True)

    report = await _correr(session_factory)

    assert turn_id not in _turnos(report, "V3"), (
        "V3 conto una escalacion que la duena ya habia respondido escribiendo en el chat"
    )


# ---------------------------------------------------------------------------
# V7 — la duena aprobo y su decision no quedo
# ---------------------------------------------------------------------------


async def test_v7_avisa_por_una_decision_no_guardada(session_factory) -> None:
    vip_id = await _seed_vip(session_factory, etiqueta="v7")
    chat_id = 993000000 + (uuid.uuid4().int % 9_000_000)
    turn_id = await _seed_turn(session_factory, vip_id=vip_id, chat_id=chat_id, status="delivered")
    await _seed_outcome(session_factory, turn_id=turn_id, vip_id=vip_id, draft_score=0.71)

    report = await _correr(session_factory)

    assert turn_id in _turnos(report, "V7"), f"V7 no aviso del defecto de septiembre: {report.as_dict()}"


async def test_v7_no_avisa_cuando_la_decision_si_quedo(session_factory) -> None:
    vip_id = await _seed_vip(session_factory, etiqueta="v7-ok")
    chat_id = 993100000 + (uuid.uuid4().int % 9_000_000)
    turn_id = await _seed_turn(session_factory, vip_id=vip_id, chat_id=chat_id, status="delivered")
    await _seed_outcome(
        session_factory,
        turn_id=turn_id,
        vip_id=vip_id,
        draft_score=0.71,
        owner_outcome="approved_as_is",
    )

    report = await _correr(session_factory)

    assert turn_id not in _turnos(report, "V7"), "V7 aviso de un turno cuya decision si se guardo"


# ---------------------------------------------------------------------------
# El aviso y sus fallas propias
# ---------------------------------------------------------------------------


async def test_un_vigilante_roto_sale_como_no_pude_revisar(session_factory, tmp_path: Path) -> None:
    """Una consulta rota no puede parecerse a "todo bien"."""
    roto = tmp_path / "vigilantes.sql"
    roto.write_text(
        "-- V9 | activo | C-PRUEBA | consulta rota a proposito\n"
        "SELECT columna_que_no_existe FROM tabla_que_no_existe;\n",
        encoding="utf-8",
    )

    service = _service(session_factory, sql_path=roto)
    report = await service.revisar()

    assert [falla.vigilante_id for falla in report.failures] == ["V9"]
    mensaje = service.componer_mensaje(report)
    assert mensaje is not None
    assert "No pude revisar" in mensaje


async def test_el_aviso_no_nombra_tablas_y_dice_que_hacer(session_factory) -> None:
    await _seed_huella(session_factory, tabla="memories", dias_atras=0)

    service = _service(session_factory)
    report = await service.revisar()
    mensaje = service.componer_mensaje(report, swallowed_delta={"owner_notify_failed_x": 2})

    assert mensaje is not None
    for tabla in ("memories", "profiles", "examples", "policies", "contexts", "turn_outcome_log"):
        assert tabla not in mensaje, f"el aviso nombra una tabla interna: {tabla}"
    assert "Que paso:" in mensaje and "Que hacer:" in mensaje and "Desde cuando:" in mensaje
    # Los contadores de fallos internos entran al aviso, en palabras de negocio.
    assert "Avisos tuyos que no te llegaron: 2" in mensaje


async def test_sin_nada_roto_no_hay_mensaje(session_factory, tmp_path: Path) -> None:
    vacio = tmp_path / "vigilantes.sql"
    vacio.write_text(
        "-- V8 | activo | C-PRUEBA | chequeo que no encuentra nada\nSELECT 0 AS alerta;\n",
        encoding="utf-8",
    )

    service = _service(session_factory, sql_path=vacio)
    report = await service.revisar()

    assert report.ok
    assert service.componer_mensaje(report) is None


def test_los_vigilantes_activos_son_los_documentados() -> None:
    """El contrato del SQL: solo estos corren, y V3 corre calibrado."""
    activos = {v["id"] for v in leer_vigilantes() if v["activo"]}

    assert activos == {"V1", "V2", "V3", "V7"}


# ---------------------------------------------------------------------------
# El job: latido y no repeticion
# ---------------------------------------------------------------------------


async def test_el_job_deja_latido_y_no_repite_lo_ya_avisado(session_factory, tmp_path: Path) -> None:
    from diana.jobs.contract_watchdog import run_contract_watchdog_cycle

    latido = tmp_path / "latido.json"
    vip_id = await _seed_vip(session_factory, etiqueta="job")
    chat_id = 994000000 + (uuid.uuid4().int % 9_000_000)
    turn_id = await _seed_turn(session_factory, vip_id=vip_id, chat_id=chat_id, status="delivered")
    await _seed_trace(session_factory, turn_id=turn_id, chat_id=chat_id, vip_id=vip_id, decision={})

    avisos: list[str] = []

    class _Notifier:
        async def notify_info(self, texto: str, *, chat_id: int | None = None) -> None:
            avisos.append(texto)

    service = _service(session_factory)
    primero = await run_contract_watchdog_cycle(
        service, heartbeat_path=latido, notifier=_Notifier(), swallowed_counts=lambda: {}
    )

    assert primero["result"] == "alertas"
    assert f"V2:{turn_id}" in primero["alerted"], "el caso nuevo no quedo como avisado"
    assert avisos and "un intercambio del" in avisos[0], f"el aviso no cuenta que paso: {avisos}"
    # La copia al usuario no lleva ids internos: se cuentan cuando y donde, no la clave.
    assert turn_id not in avisos[0], "el aviso le muestra un id interno a la duena"
    assert latido.exists(), "la corrida no dejo latido"

    # La corrida siguiente ya no vuelve a avisar el mismo caso.
    segundo = await run_contract_watchdog_cycle(
        service, heartbeat_path=latido, notifier=_Notifier(), swallowed_counts=lambda: {}
    )

    assert f"V2:{turn_id}" not in segundo["alerted"], (
        "el caso ya avisado volvio a quedar en alerta: el aviso se repetiria todos los dias"
    )
