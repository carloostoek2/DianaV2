"""C-HIST-01 (b) — el alta de un VIP nuevo no consulta Telegram con la cuenta anterior.

Prueba E2: entra por el comando real de alta (``/add_vip``) sobre el contenedor
armado por ``build_app`` y verifica el efecto en Postgres real. Solo se simulan
las dos fronteras externas: la sesión de Telethon (cuenta personal) y el envío
de mensajes a Telegram. Nada más.

Promesa bajo prueba: con la importación de historial apagada a propósito, dar de
alta un VIP deja el alta hecha, no toca la sesión personal y registra el motivo.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pytest
from aiogram import Bot
from aiogram.types import Chat, Message, Update, User
from pydantic import SecretStr
from sqlalchemy import text

from diana.behavior.fake import FixedDelayPolicy
from diana.composition import build_app
from diana.config.settings import Settings

OWNER_ID = 999001
VIP_ID = 999000777  # fuera de los rangos reales; la prueba falla si ya existe
TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"
APLICACION = "diana.application"


class SpyTelethonFetcher:
    """Doble de la frontera de Telethon: registra si alguien la construye."""

    instances: list["SpyTelethonFetcher"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.fetched: list[int] = []
        SpyTelethonFetcher.instances.append(self)

    async def fetch_recent(
        self, user_id: int, *, limit: int, username: str | None = None
    ) -> list[Any]:
        self.fetched.append(user_id)
        return []


class SpyNotifier:
    """Doble del aviso a la dueña: registra lo que se le habría enviado."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.infos: list[str] = []

    async def notify_info(self, text: str) -> None:
        self.infos.append(text)

    def __getattr__(self, name: str) -> Any:
        async def _noop(*args: Any, **kwargs: Any) -> None:
            return None

        return _noop


class SpyBotSession:
    """Doble de la salida a Telegram: ningún mensaje sale de la máquina."""

    def __init__(self) -> None:
        self.methods: list[str] = []

    async def __call__(self, bot: Any, method: Any, timeout: Any = None) -> Any:
        self.methods.append(type(method).__name__)
        return None

    async def close(self) -> None:
        return None


class CaptureHandler(logging.Handler):
    """Captura los registros de los módulos bajo prueba.

    Fija el nivel de cada logger: en pytest el nivel efectivo hereda de la raíz
    (WARNING) y los registros INFO se descartarían antes de llegar aquí.
    """

    LOGGERS = ("diana.application", "diana.composition")

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []
        self._niveles: list[tuple[logging.Logger, int]] = []
        for nombre in self.LOGGERS:
            log = logging.getLogger(nombre)
            self._niveles.append((log, log.level))
            log.setLevel(logging.INFO)
            log.addHandler(self)

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def events(self) -> list[str]:
        return [r.getMessage() for r in self.records]

    def close(self) -> None:
        for log, nivel in self._niveles:
            log.removeHandler(self)
            log.setLevel(nivel)
        super().close()


def _settings(*, seed_enabled: bool) -> Settings:
    return Settings.model_construct(
        telegram_bot_token=SecretStr(TOKEN),
        owner_telegram_id=OWNER_ID,
        database_url=SecretStr(
            "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder"
        ),
        deepseek_api_key="",
        global_mode="supervised",
        # Credenciales presentes a propósito: configurar Telethon ya no alcanza.
        telethon_api_id=31515582,
        telethon_api_hash=SecretStr("hash-de-prueba"),
        telethon_session_path="/tmp/diana_session_de_prueba",
        feature_vip_history_seed_enabled=seed_enabled,
        feature_memory_enabled=False,
        log_level="INFO",
    )


def _update_alta(texto: str) -> Update:
    msg = Message(
        message_id=1,
        date=datetime(2026, 10, 7, 12, 0, 0),
        chat=Chat(id=OWNER_ID, type="private"),
        from_user=User(id=OWNER_ID, is_bot=False, first_name="Duenia"),
        text=texto,
    )
    return Update(update_id=1, message=msg)


@pytest.mark.db
@pytest.mark.asyncio
async def test_alta_de_vip_con_importacion_apagada_no_toca_la_sesion(
    engine, session_factory, alembic_applied, fake_llm, monkeypatch
) -> None:
    """El alta se completa, no se importa nada y el motivo queda registrado."""
    SpyTelethonFetcher.instances.clear()
    notifier = SpyNotifier()
    monkeypatch.setattr(
        "diana.composition.AiogramOwnerNotifier", lambda *a, **k: notifier
    )
    monkeypatch.setattr(
        "diana.infrastructure.telethon.vip_history_fetcher.TelethonVipHistoryFetcher",
        SpyTelethonFetcher,
    )

    captura = CaptureHandler()

    # El VIP de la prueba no debe existir antes: si existe, la prueba no puede
    # distinguir lo que hizo el alta de lo que ya estaba.
    async with session_factory() as sesion:
        previo = await sesion.execute(
            text("select count(*) from vips where telegram_user_id = :uid"),
            {"uid": VIP_ID},
        )
        assert previo.scalar_one() == 0, (
            f"el VIP {VIP_ID} ya existe en la base; elegir otro id de prueba"
        )

    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    app = build_app(
        _settings(seed_enabled=False),
        bot=bot,
        llm=fake_llm,
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    try:
        await app.dispatcher.feed_update(
            bot, _update_alta(f"/add_vip {VIP_ID} Prueba E2")
        )

        # 1. Efecto real: el alta ocurrió.
        async with session_factory() as sesion:
            alta = await sesion.execute(
                text("select count(*) from vips where telegram_user_id = :uid"),
                {"uid": VIP_ID},
            )
            assert alta.scalar_one() == 1, "el alta del VIP no quedó registrada"

            # 2. Efecto real: el historial del chat no recibió nada.
            historial = await sesion.execute(
                text("select count(*) from message_history where chat_id = :uid"),
                {"uid": VIP_ID},
            )
            assert historial.scalar_one() == 0, (
                "el alta escribió historial: la importación no estaba apagada"
            )

        # 3. La sesión personal de Telegram nunca se abrió.
        assert SpyTelethonFetcher.instances == [], (
            "el alta construyó el importador de Telethon con la importación apagada"
        )

        # 4. El motivo queda escrito, no en silencio.
        eventos = captura.events()
        assert "vip_history_seed_disabled_by_flag" in eventos, (
            f"falta el registro del arranque con el motivo; vistos: {eventos}"
        )
        assert "vip_history_seed_skipped_disabled" in eventos, (
            f"falta el registro del alta con el motivo; vistos: {eventos}"
        )
        motivo = [
            r for r in captura.records
            if r.getMessage() == "vip_history_seed_skipped_disabled"
        ][0]
        assert getattr(motivo, "reason", None) == "flag_off"
        assert getattr(motivo, "telegram_user_id", None) == VIP_ID

        # 5. Sin aviso a la dueña: apagado a propósito no genera ruido.
        assert notifier.infos == [], (
            f"la dueña recibió avisos con la importación apagada: {notifier.infos}"
        )
        # 6. La respuesta del alta sí salió (el alta fue real, no un no-op).
        assert "SendMessage" in bot.session.methods  # type: ignore[attr-defined]
    finally:
        captura.close()
        await bot.session.close()


@pytest.mark.db
@pytest.mark.asyncio
async def test_con_la_bandera_encendida_la_pieza_si_se_cablea(
    engine, session_factory, alembic_applied, fake_llm, monkeypatch
) -> None:
    """Contraprueba: encender la bandera vuelve a construir el importador.

    Sin esto, la prueba anterior podría pasar por una pieza rota en vez de por
    una puerta cerrada. Con la bandera encendida no se envía ningún mensaje, así
    que no se abre ninguna sesión real.
    """
    SpyTelethonFetcher.instances.clear()
    monkeypatch.setattr(
        "diana.infrastructure.telethon.vip_history_fetcher.TelethonVipHistoryFetcher",
        SpyTelethonFetcher,
    )

    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    app = build_app(
        _settings(seed_enabled=True),
        bot=bot,
        llm=fake_llm,
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    try:
        assert len(SpyTelethonFetcher.instances) == 1, (
            "con la bandera encendida el importador debería quedar cableado"
        )
        assert SpyTelethonFetcher.instances[0].fetched == []
        assert app is not None
    finally:
        await bot.session.close()
