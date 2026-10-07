"""C-EMB-01 (tramo `profiles`) — guardar una ficha le pone una huella de verdad.

Prueba E2: entra por el camino real de la dueña (``/add_vip`` → botón "añadir
nota" del menú → texto libre) sobre el contenedor armado por ``build_app`` y
verifica el efecto en Postgres real. No se simula el motor de huellas: se usa el
que arma producción.

Promesa bajo prueba: al guardar una ficha, la columna ``embedding`` queda con la
huella real del contenido — distinta de cero y producida por el motor real —, no
con el vector de ceros.

Nota de alcance: la huella de una ficha **no se consume** en ninguna búsqueda (el
lector va por ``vip_id``; la búsqueda por parecido se eliminó el 2026-10-07). Lo
que esta prueba demuestra es que el dato se escribe bien, no que se use.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import pytest
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from pydantic import SecretStr
from sqlalchemy import text

from diana.behavior.fake import FixedDelayPolicy
from diana.cognitive.embedding import EmbeddingService
from diana.composition import build_app
from diana.config.settings import Settings
from diana.infrastructure.db.repositories.profiles import _content_to_embedding_text
from diana.telegram.keyboards import encode_menu_vip_action

OWNER_ID = 999001
BOT_ID = 999002
# Fuera de los rangos reales; un id por combinación de banderas (la prueba falla
# si el VIP ya existe, así que cada fila de la matriz necesita el suyo).
VIP_ID = 999000778
VIP_ID_MEMORY_ON = 999000779
TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"
REPO_LOGGER = "diana.infrastructure.db.repositories.profiles"
NOTA = "Prefiere que le escriban por la mañana y sin audios largos."


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
    """Captura los registros del repositorio de fichas.

    En pytest el nivel efectivo hereda de la raíz (WARNING) y los DEBUG se
    descartarían antes de llegar aquí; se fija el nivel del logger a propósito.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []
        self._log = logging.getLogger(REPO_LOGGER)
        self._nivel = self._log.level
        self._log.setLevel(logging.DEBUG)
        self._log.addHandler(self)

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def zeros_events(self) -> list[logging.LogRecord]:
        return [
            r for r in self.records if r.getMessage() == "profile_embedding_zeros"
        ]

    def close(self) -> None:
        self._log.removeHandler(self)
        self._log.setLevel(self._nivel)
        super().close()


def _settings(*, memory_enabled: bool) -> Settings:
    return Settings.model_construct(
        telegram_bot_token=SecretStr(TOKEN),
        owner_telegram_id=OWNER_ID,
        database_url=SecretStr(
            "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder"
        ),
        deepseek_api_key="",
        global_mode="supervised",
        # La bandera de memoria gobierna secciones OPCIONALES de la ficha (la
        # sección semántica), no el guardado de la nota ni su huella. Se corre
        # con los dos valores para que la matriz sea medida, no supuesta.
        feature_memory_enabled=memory_enabled,
        log_level="INFO",
    )


def _message(texto: str, message_id: int, *, from_user: User) -> Message:
    return Message(
        message_id=message_id,
        date=datetime(2026, 10, 7, 12, 0, 0),
        chat=Chat(id=OWNER_ID, type="private"),
        from_user=from_user,
        text=texto,
    )


def _update_texto(texto: str, message_id: int) -> Update:
    return Update(
        update_id=message_id,
        message=_message(
            texto, message_id, from_user=User(id=OWNER_ID, is_bot=False, first_name="Duenia")
        ),
    )


def _update_callback(data: str) -> Update:
    """Callback real del menú, con el mismo `callback_data` que arma producción."""
    mensaje_del_bot = _message(
        "Ficha del VIP",
        900,
        from_user=User(id=BOT_ID, is_bot=True, first_name="Diana"),
    )
    return Update(
        update_id=901,
        callback_query=CallbackQuery(
            id="cb-1",
            from_user=User(id=OWNER_ID, is_bot=False, first_name="Duenia"),
            chat_instance="1",
            data=data,
            message=mensaje_del_bot,
        ),
    )


@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "memory_enabled", [False, True], ids=["memoria_off", "memoria_on"]
)
async def test_guardar_una_ficha_le_pone_una_huella_real(
    engine, session_factory, alembic_applied, fake_llm, memory_enabled
) -> None:
    """El camino real de la dueña deja una huella distinta de cero.

    Se corre con la bandera de memoria en los dos valores: el guardado de la
    nota y su huella no dependen de ella (solo cambian secciones opcionales de
    la ficha mostrada).
    """
    vip_id = VIP_ID_MEMORY_ON if memory_enabled else VIP_ID

    # El VIP de la prueba no debe existir antes: si existe, la prueba no puede
    # distinguir lo que hizo este guardado de lo que ya estaba.
    async with session_factory() as sesion:
        previo = await sesion.execute(
            text("select count(*) from vips where telegram_user_id = :uid"),
            {"uid": vip_id},
        )
        assert previo.scalar_one() == 0, (
            f"el VIP {vip_id} ya existe en la base; elegir otro id de prueba"
        )

    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    app = build_app(
        _settings(memory_enabled=memory_enabled),
        bot=bot,
        llm=fake_llm,
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    captura = CaptureHandler()
    try:
        # 1. Alta del VIP (el camino real; la ficha tiene FK a `vips`).
        await app.dispatcher.feed_update(
            bot, _update_texto(f"/add_vip {vip_id} Prueba E2", 1)
        )
        # 2. Botón "añadir nota" de la ficha → abre la sesión de texto libre.
        await app.dispatcher.feed_update(
            bot, _update_callback(encode_menu_vip_action(vip_id, "note_add"))
        )
        # 3. El texto de la dueña → ProfileAdminService.add_note → ProfilesRepo.
        await app.dispatcher.feed_update(bot, _update_texto(NOTA, 3))

        # --- Efecto real, leído en sesión nueva --------------------------
        async with session_factory() as sesion:
            fila = (
                await sesion.execute(
                    text(
                        "select p.embedding::text as embedding, p.content "
                        "from profiles p join vips v on v.id = p.vip_id "
                        "where v.telegram_user_id = :uid"
                    ),
                    {"uid": vip_id},
                )
            ).one()

        embedding = [float(x) for x in json.loads(fila.embedding)]
        content = fila.content

        # a. El guardado ocurrió de verdad (no es un no-op).
        def _nota_texto(n: Any) -> str:
            if isinstance(n, dict):
                return str(n.get("text") or n.get("texto") or "")
            return str(n)

        notas = content.get("notes") or []
        assert any(NOTA in _nota_texto(n) for n in notas), (
            f"la nota no quedó guardada en la ficha: {content}"
        )

        # b. La huella es de 384 dimensiones y NO es el vector de ceros.
        assert len(embedding) == 384
        assert any(x != 0.0 for x in embedding), (
            "la ficha quedó con la huella en ceros: el motor de huellas no corrió"
        )
        norma = sum(x * x for x in embedding) ** 0.5
        assert norma > 0.5, f"norma sospechosamente baja ({norma}): {embedding[:5]}"

        # c. Salió DEL MOTOR REAL: coincide con el mismo texto pasado por él.
        texto = _content_to_embedding_text(content).strip()
        esperado = await EmbeddingService().embed(texto)
        desvio = max(abs(a - b) for a, b in zip(embedding, esperado))
        assert desvio < 1e-6, (
            f"la huella guardada no coincide con la del motor (máx. desvío {desvio})"
        )

        # d. Y no dejó rastro de "guardado en ceros": la huella se calculó.
        ceros = captura.zeros_events()
        assert ceros == [], (
            "se guardó la huella en ceros: "
            f"{[getattr(r, 'reason', '?') for r in ceros]}"
        )

        # e. La respuesta del menú sí salió (el flujo corrió de verdad).
        assert "SendMessage" in bot.session.methods  # type: ignore[attr-defined]
    finally:
        captura.close()
        await bot.session.close()
