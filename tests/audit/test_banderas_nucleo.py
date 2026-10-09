"""Aviso de arranque por banderas nucleo apagadas — prueba E2 con el sistema real.

Entra por ``build_app`` (composicion real, con el ``notifier`` real cableado a Telegram) y por el
servidor ``/health`` real, levantado y consultado por HTTP. Lo unico simulado es la salida a
Telegram (``SpyBotSession``): ningun mensaje sale de la maquina.

Promesa bajo prueba (``audit/INVESTIGACION-C.md`` §4):

  (a) una bandera nucleo apagada **sin declarar** sale en la advertencia del registro, queda en
      ``/health`` y la dueña recibe un mensaje;
  (b) la **misma** bandera apagada, declarada con motivo y fecha, sale como declarada, **no**
      genera advertencia y **no** manda mensaje;
  (c) el caso real ``FEATURE_HISTORY_REIMPORT_ENABLED`` (apagada a proposito desde el 2026-09-06)
      sale como declarada;
  (d) ``/health`` publica el resumen sin cambiar su estado general;
  (e) dos arranques seguidos con la misma advertencia mandan **un** mensaje;
  (f) una bandera escrita en el entorno que el codigo no conoce se reporta aparte;
  (g) todo esto es un aviso: el arranque sigue aunque falle.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot
from pydantic import SecretStr

from diana.application.aviso_banderas import avisar_banderas_nucleo, leer_estado
from diana.behavior.fake import FixedDelayPolicy
from diana.composition import build_app
from diana.config import banderas_nucleo
from diana.config.banderas_nucleo import ApagadoDeclarado, BanderaNucleo, CATALOGO
from diana.config.settings import Settings
from diana.llm.fake import FakeLLM
from diana.telegram.health import HealthServer

pytestmark = pytest.mark.db

TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"
OWNER_ID = 999001

#: Catalogo de un solo elemento, para aislar el escenario de la bandera que se prueba.
BANDERA_UNICA = "feature_memory_enabled"


class SpyBotSession:
    """Doble de la salida a Telegram: nada sale de la maquina."""

    def __init__(self) -> None:
        self.sent_texts: list[str] = []

    async def __call__(self, bot: Any, method: Any, timeout: Any = None) -> Any:
        texto = getattr(method, "text", None)
        if texto:
            self.sent_texts.append(str(texto))
        return None

    async def close(self) -> None:
        return None


class CaptureHandler(logging.Handler):
    """Captura los eventos del modulo de aplicacion, incluidos los INFO."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []
        self._log = logging.getLogger("diana.application")
        self._nivel = self._log.level
        self._log.setLevel(logging.INFO)
        self._log.addHandler(self)

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def del_evento(self, nombre: str) -> list[logging.LogRecord]:
        return [r for r in self.records if getattr(r, "event", None) == nombre]

    def close(self) -> None:
        self._log.removeHandler(self)
        self._log.setLevel(self._nivel)
        super().close()


def _settings(**overrides: Any) -> Settings:
    """Ajustes de prueba: composicion minima, sin leer el entorno real de la maquina."""
    base: dict[str, Any] = {
        "telegram_bot_token": SecretStr(TOKEN),
        "owner_telegram_id": OWNER_ID,
        "database_url": SecretStr(
            "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder"
        ),
        "deepseek_api_key": "",
        "global_mode": "supervised",
        "log_level": "WARNING",
    }
    base.update(overrides)
    return Settings.model_construct(**base)


def _catalogo_declarado(*, declarada: bool) -> None:
    """Instala un catalogo de una bandera, con o sin declaracion de apagado."""
    declaracion = (
        ApagadoDeclarado(
            desde=date(2026, 9, 6),
            motivo="Motivo de prueba declarado por la dueña.",
            condicion_para_reactivar="Cuando la condicion de prueba se cumpla.",
        )
        if declarada
        else None
    )
    banderas_nucleo.CATALOGO = (
        BanderaNucleo(
            campo=BANDERA_UNICA,
            que_se_pierde="Diana deja de recordar lo que el VIP conto antes.",
            apagada_a_proposito=declaracion,
        ),
    )


@pytest.fixture
def catalogo_limpio(monkeypatch: pytest.MonkeyPatch):
    """Restaura el catalogo real al terminar, para no contaminar otras pruebas."""
    monkeypatch.setattr(banderas_nucleo, "CATALOGO", CATALOGO)
    return banderas_nucleo


@pytest.fixture
def env_limpio(tmp_path: Path) -> Path:
    ruta = tmp_path / ".env"
    ruta.write_text("TELEGRAM_BOT_TOKEN=123:abc\n", encoding="utf-8")
    return ruta


async def _app(settings: Settings, *, engine, session_factory, bot: Bot) -> Any:
    return build_app(
        settings,
        bot=bot,
        llm=FakeLLM(text_responses=["ok"]),
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )


def _bot_con_espia() -> tuple[Bot, SpyBotSession]:
    bot = Bot(token=TOKEN)
    espia = SpyBotSession()
    bot.session = espia  # type: ignore[assignment]
    return bot, espia


async def _leer_health(server: HealthServer) -> dict[str, Any]:
    """Consulta real por HTTP contra el servidor levantado."""
    sockets = server._server.sockets or []  # noqa: SLF001 — el puerto real lo da el socket
    puerto = sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", puerto)
    try:
        writer.write(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        await writer.drain()
        crudo = await reader.read(65536)
    finally:
        writer.close()
        await writer.wait_closed()
    _, _, cuerpo = crudo.partition(b"\r\n\r\n")
    return json.loads(cuerpo.decode("utf-8"))


# ---------------------------------------------------------------------------
# (a) y (b): con y sin declaracion
# ---------------------------------------------------------------------------
async def test_a_bandera_apagada_sin_declarar_avisa(
    engine, session_factory, tmp_path: Path, env_limpio: Path, catalogo_limpio
) -> None:
    """(a) Apagada sin declarar: advertencia en el registro, en /health y mensaje a la dueña."""
    _catalogo_declarado(declarada=False)
    captura = CaptureHandler()
    bot, espia = _bot_con_espia()
    ruta = tmp_path / "banderas.json"
    app = await _app(_settings(feature_memory_enabled=False), engine=engine,
                     session_factory=session_factory, bot=bot)
    try:
        estado = await avisar_banderas_nucleo(app, env_path=env_limpio, state_path=ruta)
        assert estado is not None
        assert [b.variable for b in estado.apagadas_sin_declarar] == ["FEATURE_MEMORY_ENABLED"]

        eventos = captura.del_evento("banderas_nucleo")
        assert eventos, "el resumen tiene que quedar en el registro"
        assert eventos[0].levelname == "WARNING"
        assert "SIN declarar" in eventos[0].getMessage()

        assert len(espia.sent_texts) == 1, "la dueña tiene que recibir el aviso"
        assert "FEATURE_MEMORY_ENABLED" in espia.sent_texts[0]

        server = HealthServer(
            host="127.0.0.1", port=0, session_factory=session_factory, bot=bot,
            flags_state_path=ruta,
        )
        await server.start()
        try:
            cuerpo = await _leer_health(server)
        finally:
            await server.stop()
        assert cuerpo["checks"]["flags"]["sin_declarar"] == ["FEATURE_MEMORY_ENABLED"]
    finally:
        captura.close()
        await bot.session.close()


async def test_b_la_misma_bandera_declarada_no_avisa(
    engine, session_factory, tmp_path: Path, env_limpio: Path, catalogo_limpio
) -> None:
    """(b) Declarada con motivo y fecha: sale como declarada y no molesta a la dueña."""
    _catalogo_declarado(declarada=True)
    captura = CaptureHandler()
    bot, espia = _bot_con_espia()
    ruta = tmp_path / "banderas.json"
    app = await _app(_settings(feature_memory_enabled=False), engine=engine,
                     session_factory=session_factory, bot=bot)
    try:
        estado = await avisar_banderas_nucleo(app, env_path=env_limpio, state_path=ruta)

        assert estado is not None
        assert estado.hay_advertencia is False
        assert [b.variable for b in estado.apagadas_declaradas] == ["FEATURE_MEMORY_ENABLED"]
        assert espia.sent_texts == [], "declarar el apagado es lo que silencia el aviso"

        eventos = captura.del_evento("banderas_nucleo")
        assert eventos and eventos[0].levelname == "INFO"
        assert "2026-09-06" in eventos[0].getMessage()
        assert "Motivo de prueba" in eventos[0].getMessage()
    finally:
        captura.close()
        await bot.session.close()


# ---------------------------------------------------------------------------
# (c) el caso real del proyecto
# ---------------------------------------------------------------------------
async def test_c_caso_real_recarga_de_historial(
    engine, session_factory, tmp_path: Path, env_limpio: Path, catalogo_limpio
) -> None:
    """La recarga de historial esta apagada a proposito desde el 2026-09-06, no sin declarar."""
    bot, _ = _bot_con_espia()
    ruta = tmp_path / "banderas.json"
    app = await _app(
        _settings(feature_history_reimport_enabled=False),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
    )
    try:
        estado = await avisar_banderas_nucleo(app, env_path=env_limpio, state_path=ruta)

        assert estado is not None
        declaradas = {b.variable: b for b in estado.apagadas_declaradas}
        assert "FEATURE_HISTORY_REIMPORT_ENABLED" in declaradas
        assert "FEATURE_HISTORY_REIMPORT_ENABLED" not in {
            b.variable for b in estado.apagadas_sin_declarar
        }
        declaracion = declaradas["FEATURE_HISTORY_REIMPORT_ENABLED"].declaracion
        assert declaracion is not None and declaracion.desde == date(2026, 9, 6)
    finally:
        await bot.session.close()


# ---------------------------------------------------------------------------
# (d) /health
# ---------------------------------------------------------------------------
async def test_d_health_publica_el_resumen_sin_degradar(
    engine, session_factory, tmp_path: Path, env_limpio: Path, catalogo_limpio
) -> None:
    _catalogo_declarado(declarada=False)
    bot, _ = _bot_con_espia()
    ruta = tmp_path / "banderas.json"
    app = await _app(_settings(feature_memory_enabled=False), engine=engine,
                     session_factory=session_factory, bot=bot)
    server = HealthServer(
        host="127.0.0.1", port=0, session_factory=session_factory, bot=bot, flags_state_path=ruta
    )
    try:
        await avisar_banderas_nucleo(app, env_path=env_limpio, state_path=ruta)
        await server.start()
        cuerpo = await _leer_health(server)

        bloque = cuerpo["checks"]["flags"]
        assert bloque["ok"] is False
        assert bloque["nucleo_total"] == 1
        assert bloque["sin_declarar"] == ["FEATURE_MEMORY_ENABLED"]
        assert cuerpo["status"] == "ok", "una bandera apagada no es una falla del sistema"
    finally:
        await server.stop()
        await bot.session.close()


async def test_d2_sin_resumen_previo_el_health_no_cambia(
    engine, session_factory, tmp_path: Path
) -> None:
    """Sin latido de banderas, ``/health`` responde igual que antes de este cambio."""
    bot, _ = _bot_con_espia()
    server = HealthServer(
        host="127.0.0.1",
        port=0,
        session_factory=session_factory,
        bot=bot,
        flags_state_path=tmp_path / "no-existe.json",
    )
    try:
        await server.start()
        cuerpo = await _leer_health(server)

        assert "flags" not in cuerpo["checks"]
        assert cuerpo["status"] == "ok"
    finally:
        await server.stop()
        await bot.session.close()


# ---------------------------------------------------------------------------
# (e) y (f)
# ---------------------------------------------------------------------------
async def test_e_dos_arranques_seguidos_un_solo_mensaje(
    engine, session_factory, tmp_path: Path, env_limpio: Path, catalogo_limpio
) -> None:
    _catalogo_declarado(declarada=False)
    bot, espia = _bot_con_espia()
    ruta = tmp_path / "banderas.json"
    settings = _settings(feature_memory_enabled=False)
    app = await _app(settings, engine=engine, session_factory=session_factory, bot=bot)
    try:
        await avisar_banderas_nucleo(app, env_path=env_limpio, state_path=ruta)
        await avisar_banderas_nucleo(app, env_path=env_limpio, state_path=ruta)

        assert len(espia.sent_texts) == 1, "un aviso que llega en cada reinicio se vuelve ruido"
    finally:
        await bot.session.close()


async def test_f_bandera_del_entorno_que_el_codigo_no_conoce(
    engine, session_factory, tmp_path: Path, catalogo_limpio
) -> None:
    _catalogo_declarado(declarada=True)
    entorno = tmp_path / ".env"
    entorno.write_text("FEATURE_MEMORIA_ENABLED=true\n", encoding="utf-8")
    bot, espia = _bot_con_espia()
    app = await _app(_settings(feature_memory_enabled=True), engine=engine,
                     session_factory=session_factory, bot=bot)
    try:
        estado = await avisar_banderas_nucleo(
            app, env_path=entorno, state_path=tmp_path / "banderas.json"
        )

        assert estado is not None
        assert estado.desconocidas == ("FEATURE_MEMORIA_ENABLED",)
        assert len(espia.sent_texts) == 1
        assert "FEATURE_MEMORIA_ENABLED" in espia.sent_texts[0]
    finally:
        await bot.session.close()


# ---------------------------------------------------------------------------
# (g) aviso, nunca bloqueo
# ---------------------------------------------------------------------------
class _NotifierQueFalla:
    async def notify_info(self, text: str, *, chat_id: int | None = None) -> None:
        raise RuntimeError("Telegram caido")


async def test_g1_si_telegram_falla_el_resumen_igual_queda(
    engine, session_factory, tmp_path: Path, env_limpio: Path, catalogo_limpio
) -> None:
    """El aviso no puede tumbar el arranque, y el resumen tiene que quedar igual en /health."""
    _catalogo_declarado(declarada=False)
    captura = CaptureHandler()
    bot, _ = _bot_con_espia()
    ruta = tmp_path / "banderas.json"
    app = await _app(_settings(feature_memory_enabled=False), engine=engine,
                     session_factory=session_factory, bot=bot)
    app.notifier = _NotifierQueFalla()  # type: ignore[assignment]
    try:
        estado = await avisar_banderas_nucleo(app, env_path=env_limpio, state_path=ruta)

        assert estado is not None, "el aviso no puede tumbar el arranque"
        eventos = [r.getMessage() for r in captura.records]
        assert "banderas_arranque_aviso_no_enviado" in eventos, (
            "si el mensaje no sale, tiene que quedar registrado"
        )
        assert "banderas_arranque_fallo" not in eventos, (
            "un Telegram caido no puede abortar el resumen entero"
        )
        assert leer_estado(ruta) is not None, "/health tiene que recibir el resumen igual"
    finally:
        captura.close()
        await bot.session.close()


async def test_g2_si_no_se_puede_guardar_el_latido_igual_avisa(
    engine, session_factory, tmp_path: Path, env_limpio: Path, catalogo_limpio
) -> None:
    """El latido y el mensaje son independientes: si uno falla, el otro sigue."""
    _catalogo_declarado(declarada=False)
    captura = CaptureHandler()
    bot, espia = _bot_con_espia()
    # Un directorio con el nombre del archivo: la escritura atomica no puede reemplazarlo.
    ruta = tmp_path / "banderas.json"
    ruta.mkdir()
    app = await _app(_settings(feature_memory_enabled=False), engine=engine,
                     session_factory=session_factory, bot=bot)
    try:
        estado = await avisar_banderas_nucleo(app, env_path=env_limpio, state_path=ruta)

        assert estado is not None
        eventos = [r.getMessage() for r in captura.records]
        assert "banderas_arranque_estado_no_escrito" in eventos, (
            "si el latido no se puede escribir, tiene que quedar registrado"
        )
        assert len(espia.sent_texts) == 1, "el mensaje sale aunque el latido falle"
    finally:
        captura.close()
        await bot.session.close()
