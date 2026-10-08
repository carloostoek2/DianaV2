"""Vigilante de contratos — piezas puras: copy al usuario, latido y semaforo de /health.

Aca no hay base: se prueban las decisiones que no dependen de datos (como se lee un contador
de fallos internos, que se repite y que no, y cuando /health tiene que decir que el vigilante
dejo de correr).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from diana.application.contract_watchdog_service import (
    ContractWatchdogService,
    WatchdogAlert,
    WatchdogFailure,
    WatchdogReport,
    claves_avisadas,
    filtrar_ya_avisados,
    lineas_swallowed,
)
from diana.application.watchdog_heartbeat import (
    read_heartbeat,
    summarize_heartbeat,
    write_heartbeat,
)
from diana.jobs.contract_watchdog import ContractWatchdogJob, run_contract_watchdog_cycle
from diana.telegram.health import build_health_payload


# ---------------------------------------------------------------------------
# Los contadores de fallos internos, en palabras de negocio
# ---------------------------------------------------------------------------


def test_los_fallos_internos_se_agrupan_por_familia_y_en_espanol() -> None:
    lineas = lineas_swallowed(
        {
            "owner_notify_failed_after_empty_draft": 2,
            "owner_notify_failed_after_vip_frozen": 1,
            "mood_engine_error": 4,
        }
    )

    assert "Avisos tuyos que no te llegaron: 3" in lineas
    assert "Lecturas de animo que fallaron: 4" in lineas


def test_un_fallo_interno_que_no_crecio_no_se_reporta() -> None:
    """La primera corrida de un proceso puede dar deltas negativos: no se reportan."""
    assert lineas_swallowed({"mood_engine_error": -2, "owner_notify_failed_x": 0}) == []


# ---------------------------------------------------------------------------
# No repetir el mismo aviso
# ---------------------------------------------------------------------------


def _reporte_con(*turnos: str) -> WatchdogReport:
    return WatchdogReport(
        alerts=(
            WatchdogAlert(
                vigilante_id="V2",
                titulo="titulo tecnico",
                contrato="C-SHADOW-01",
                rows=tuple({"turno": turno, "alerta": 1} for turno in turnos),
            ),
        )
    )


def test_un_caso_ya_avisado_no_vuelve_a_sonar() -> None:
    reporte = _reporte_con("a", "b")

    filtrado = filtrar_ya_avisados(reporte, ["V2:a"])

    assert [fila["turno"] for fila in filtrado.alerts[0].rows] == ["b"]
    assert claves_avisadas(filtrado) == ["V2:b"]


def test_un_vigilante_sin_casos_nuevos_desaparece_del_aviso() -> None:
    filtrado = filtrar_ya_avisados(_reporte_con("a"), ["V2:a"])

    assert filtrado.alerts == ()
    assert filtrado.ok


def test_lo_que_resume_por_dato_no_se_filtra_por_identidad() -> None:
    """V1 no lista intercambios: su unico tope es la ventana de tiempo del SQL."""
    reporte = WatchdogReport(
        alerts=(
            WatchdogAlert(
                vigilante_id="V1",
                titulo="t",
                contrato="C-EMB-01",
                rows=({"tabla": "memories", "alerta": 2, "historico": 2},),
            ),
        )
    )

    assert filtrar_ya_avisados(reporte, ["V1:memories"]).alerts == reporte.alerts


# ---------------------------------------------------------------------------
# El mensaje
# ---------------------------------------------------------------------------


def test_sin_nada_para_revisar_no_hay_mensaje() -> None:
    service = ContractWatchdogService(None)  # type: ignore[arg-type]

    assert service.componer_mensaje(WatchdogReport()) is None


def test_el_mensaje_cuenta_que_paso_desde_cuando_y_que_hacer() -> None:
    service = ContractWatchdogService(None)  # type: ignore[arg-type]
    reporte = WatchdogReport(
        alerts=(
            WatchdogAlert(
                vigilante_id="V1",
                titulo="huellas semanticas NUEVAS en ceros",
                contrato="C-EMB-01",
                rows=({"tabla": "profiles", "alerta": 2, "historico": 2},),
            ),
        ),
        failures=(WatchdogFailure("V9", "consulta rota", "UndefinedColumnError"),),
        skipped_sandbox=5,
    )

    mensaje = service.componer_mensaje(reporte, swallowed_delta={"owner_notify_failed_x": 1})

    assert mensaje is not None
    assert "las fichas de tus VIP" in mensaje
    assert "profiles" not in mensaje
    assert "Que paso:" in mensaje and "Desde cuando:" in mensaje and "Que hacer:" in mensaje
    assert "No pude revisar" in mensaje
    assert "Descarte 5" in mensaje


# ---------------------------------------------------------------------------
# Latido y /health
# ---------------------------------------------------------------------------


def test_el_latido_va_y_vuelve(tmp_path) -> None:
    ruta = tmp_path / "latido.json"

    write_heartbeat({"last_run_at": "2026-10-08T10:17:00+00:00", "result": "ok"}, ruta)

    assert read_heartbeat(ruta)["result"] == "ok"


def test_un_latido_ilegible_no_rompe_a_quien_lo_lee(tmp_path) -> None:
    ruta = tmp_path / "latido.json"
    ruta.write_text("{esto no es json", encoding="utf-8")

    assert read_heartbeat(ruta) is None
    assert read_heartbeat(tmp_path / "no_existe.json") is None


def test_el_semaforo_del_vigilante_en_health() -> None:
    ahora = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    # Apagado y sin latido: /health no dice nada del vigilante (igual que antes).
    assert summarize_heartbeat(None, enabled=False, now=ahora) is None

    # Encendido y sin corrida todavia: no se degrada por un arranque recien hecho.
    sin_corrida = summarize_heartbeat(None, enabled=True, now=ahora)
    assert sin_corrida is not None and sin_corrida["ok"] is True

    # Corrida reciente y sana.
    sano = summarize_heartbeat(
        {"last_run_at": (ahora - timedelta(hours=2)).isoformat(), "result": "ok"}, enabled=True, now=ahora
    )
    assert sano is not None and sano["ok"] is True

    # Corrida vencida: el vigilante dejo de correr y tiene que verse.
    vencido = summarize_heartbeat(
        {"last_run_at": (ahora - timedelta(hours=40)).isoformat(), "result": "ok"}, enabled=True, now=ahora
    )
    assert vencido is not None and vencido["ok"] is False

    # Corrida que fallo.
    fallado = summarize_heartbeat(
        {"last_run_at": ahora.isoformat(), "result": "fallo"}, enabled=True, now=ahora
    )
    assert fallado is not None and fallado["ok"] is False


def test_un_vigilante_vencido_deja_el_health_en_degraded() -> None:
    degradado = build_health_payload(
        db_ok=True,
        db_latency_ms=3,
        bot_ok=True,
        bot_username="diana",
        watchdog={"ok": False, "result": "ok"},
    )
    assert degradado["status"] == "degraded"
    assert degradado["checks"]["watchdog"] == {"ok": False, "result": "ok"}


def test_sin_vigilante_el_health_responde_igual_que_antes() -> None:
    payload = build_health_payload(db_ok=True, db_latency_ms=3, bot_ok=True, bot_username="diana")

    assert payload["status"] == "ok"
    assert "watchdog" not in payload["checks"]
    assert "swallowed" not in payload["checks"]


def test_los_contadores_de_fallos_internos_se_publican_en_health() -> None:
    payload = build_health_payload(
        db_ok=True,
        db_latency_ms=3,
        bot_ok=True,
        bot_username="diana",
        swallowed={"mood_engine_error": 2},
    )

    assert payload["checks"]["swallowed"] == {"mood_engine_error": 2}


# ---------------------------------------------------------------------------
# El job: cuando corre y que hace si no puede
# ---------------------------------------------------------------------------


class _ServicioContador:
    """Doble del servicio: cuenta corridas y no toca la base."""

    def __init__(self) -> None:
        self.llamadas = 0

    async def revisar(self) -> WatchdogReport:
        self.llamadas += 1
        return WatchdogReport()

    def componer_mensaje(self, report, *, swallowed_delta=None):  # noqa: ANN001, ANN202
        return None


async def test_el_job_no_corre_dos_veces_el_mismo_dia(tmp_path) -> None:
    """Un reinicio del bot no puede adelantar el chequeo del dia."""
    ahora = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    ruta = tmp_path / "latido.json"
    servicio = _ServicioContador()
    job = ContractWatchdogJob(
        servicio,  # type: ignore[arg-type]
        heartbeat_path=ruta,
        min_hours_between_runs=20,
        now=lambda: ahora,
    )

    write_heartbeat({"last_run_at": (ahora - timedelta(hours=3)).isoformat()}, ruta)
    assert await job._correr_si_toca() == {"corrido": False, "edad_segundos": 3 * 3600}
    assert servicio.llamadas == 0

    write_heartbeat({"last_run_at": (ahora - timedelta(hours=25)).isoformat()}, ruta)
    resultado = await job._correr_si_toca()
    assert resultado["corrido"] is True
    assert servicio.llamadas == 1


def test_la_espera_nunca_es_cero(tmp_path) -> None:
    """Sin piso, un latido que no se puede escribir dejaria el bucle girando sin descanso."""
    job = ContractWatchdogJob(
        _ServicioContador(),  # type: ignore[arg-type]
        heartbeat_path=tmp_path / "no_existe.json",
    )

    assert job._segundos_hasta_la_proxima() > 0


async def test_si_el_vigilante_no_puede_correr_igual_avisa(tmp_path) -> None:
    """Morir callado es el peor resultado posible."""

    class _ServicioRoto:
        async def revisar(self) -> WatchdogReport:
            raise RuntimeError("la base no responde")

    avisos: list[str] = []

    class _Notifier:
        async def notify_info(self, texto: str, *, chat_id: int | None = None) -> None:
            avisos.append(texto)

    latido = await run_contract_watchdog_cycle(
        _ServicioRoto(),  # type: ignore[arg-type]
        heartbeat_path=tmp_path / "latido.json",
        notifier=_Notifier(),
        swallowed_counts=lambda: {},
    )

    assert latido["result"] == "fallo"
    assert avisos and "no pudo correr" in avisos[0]
    assert read_heartbeat(tmp_path / "latido.json")["result"] == "fallo"
