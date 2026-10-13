"""C-EMB-01 (tramo que faltaba) — el contraejemplo de "Reprender" deja su huella.

La ronda anterior cubrió memoria, ejemplo dorado ("Destacar") y política. El
propio contrato (``audit/contracts/C-EMB-01.md`` → "Sin cubrir: el camino de
'Reprender' (contraejemplo) por su propio flujo") dejó afuera este tramo.

Prueba E2: entra por el camino REAL de la dueña (botón "Reprender" sobre el DM
del borrador → su texto de corrección → el combo que promociona la lección como
contraejemplo) sobre el contenedor armado por ``build_app``, contra Postgres
real y con el motor de huellas REAL (no se simula). El único falso es el modelo
de lenguaje externo. Nunca se aserta "se llamó a X": se leen filas.

Matriz de banderas:
  · ``feature_quality_feedback_enabled`` OFF → el botón ni se atiende: no hay
    lección (por diseño; el teclado clásico no ofrece Destacar/Reprender).
  · ``feature_staging_enabled`` OFF → la corrección se entrega pero NO queda
    candidato, así que no hay nada que promocionar a contraejemplo.
  Las dos se miden: el caso apagado no es "silencio", es una pieza no cableada.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from pydantic import SecretStr
from sqlalchemy import text

from diana.behavior.fake import FixedDelayPolicy
from diana.cognitive.embedding import EmbeddingService
from diana.cognitive.models import Comprehension, EvaluationProfile, IncomingTurn
from diana.cognitive.retrievers.examples import ExamplesRetriever
from diana.composition import build_app
from diana.config.settings import Settings
from diana.infrastructure.db.repositories.examples import ExamplesRepo
from diana.llm.fake import FakeLLM
from diana.telegram.keyboards import (
    encode_callback,
    encode_reprimand_confirm,
)

OWNER_ID = 999001
BOT_ID = 999002
TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"

# Fuera de los rangos reales; un id por escenario.
VIP_REPRENDER = 999000971
VIP_REPRENDER_SIN_STAGING = 999000972
VIP_REPRENDER_SIN_FEEDBACK = 999000973

# Texto distintivo: la copia de la base real tiene miles de filas, así que una
# consulta genérica podría tener un vecino más cercano y no se podría distinguir
# lo propio de lo ajeno.
TEXTO_VIP = (
    "Hola Diana, quiero coordinar la entrega del kit de bienvenida en la "
    "terminal de ómnibus de Villa Merced de los Andes."
)
CONSULTA_PARECIDA = (
    "Quiero coordinar la entrega del kit de bienvenida en la terminal de "
    "ómnibus de Villa Merced de los Andes."
)
# Lo que la dueña escribe al reprender: la lección (qué NO hay que decir).
TEXTO_REPRENSION = (
    "No prometas una terminal específica sin confirmarla antes con el cliente."
)

CERO = [0.0] * 384


# ---------------------------------------------------------------------------
# Configuración: solo las banderas del camino bajo prueba.
# ---------------------------------------------------------------------------
def _settings(
    *,
    quality_feedback_enabled: bool = True,
    staging_enabled: bool = True,
) -> Settings:
    return Settings.model_construct(
        telegram_bot_token=SecretStr(TOKEN),
        owner_telegram_id=OWNER_ID,
        database_url=SecretStr(
            "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder"
        ),
        deepseek_api_key="",
        global_mode="supervised",
        feature_quality_feedback_enabled=quality_feedback_enabled,
        feature_staging_enabled=staging_enabled,
        feature_memory_enabled=False,
        feature_gray_zone_enabled=False,
        feature_autonomous_mode=False,
        feature_sandbox_enabled=False,
        feature_autonomy_quality_enabled=False,
        log_level="INFO",
    )


def _fake_llm() -> FakeLLM:
    """Solo el modelo externo es falso; el resto del sistema es el real."""
    return FakeLLM(
        structured_responses=[
            Comprehension(
                intent="consulta_logistica",
                topics=["logistica_entrega"],
                emotion="neutral",
                urgency="baja",
                risk="bajo",
                needs_memory=False,
                needs_policy=False,
                needs_schedule=False,
                needs_examples=True,
                needs_history=True,
                needs_context=True,
            ),
            EvaluationProfile(
                naturalness=0.9,
                precision=0.9,
                doctrine=0.9,
                consistency=0.9,
                safety=0.95,
                coverage=0.9,
                empathy=0.9,
            ),
        ],
        text_responses=["Claro, coordinamos la entrega."],
    )


class SpyBotSession:
    """Doble de la salida a Telegram: ningún mensaje sale de la máquina."""

    def __init__(self) -> None:
        self.methods: list[str] = []

    async def __call__(self, bot: Any, method: Any, timeout: Any = None) -> Any:
        nombre = type(method).__name__
        self.methods.append(nombre)
        if nombre.startswith("Send"):
            texto = getattr(method, "text", None) or getattr(method, "caption", None)
            return Message(
                message_id=7000 + len(self.methods),
                date=datetime(2026, 10, 8, 12, 0, 0),
                chat=Chat(id=getattr(method, "chat_id", 0) or 0, type="private"),
                text=str(texto) if texto else None,
            )
        return None

    async def close(self) -> None:
        return None


class CaptureHandler(logging.Handler):
    LOGGERS = ("diana.application",)

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

    def eventos(self) -> list[str]:
        return [r.getMessage() for r in self.records]

    def close(self) -> None:
        for log, nivel in self._niveles:
            log.removeHandler(self)
            log.setLevel(nivel)
        super().close()


# ---------------------------------------------------------------------------
# Constructores de updates reales
# ---------------------------------------------------------------------------
def _business_update(
    *, chat_id: int, from_user_id: int, text: str, message_id: int = 11
) -> Update:
    msg = Message(
        message_id=message_id,
        date=datetime(2026, 10, 8, 12, 0, 0),
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=from_user_id, is_bot=False, first_name="Vip"),
        text=text,
        business_connection_id=f"bc-audit-{chat_id}",
    )
    return Update(update_id=message_id, business_message=msg)


def _owner_callback_update(data: str, *, update_id: int = 901) -> Update:
    dm = Message(
        message_id=900,
        date=datetime(2026, 10, 8, 12, 0, 0),
        chat=Chat(id=OWNER_ID, type="private"),
        from_user=User(id=BOT_ID, is_bot=True, first_name="Diana"),
        text="Borrador",
    )
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"cb-{update_id}",
            from_user=User(id=OWNER_ID, is_bot=False, first_name="Duenia"),
            chat_instance="1",
            data=data,
            message=dm,
        ),
    )


def _owner_text_update(texto: str, *, update_id: int = 903) -> Update:
    msg = Message(
        message_id=update_id,
        date=datetime(2026, 10, 8, 12, 5, 0),
        chat=Chat(id=OWNER_ID, type="private"),
        from_user=User(id=OWNER_ID, is_bot=False, first_name="Duenia"),
        text=texto,
    )
    return Update(update_id=update_id, message=msg)


# ---------------------------------------------------------------------------
# Lecturas sobre filas reales
# ---------------------------------------------------------------------------
async def _turn_row(session_factory, chat_id: int) -> dict[str, Any]:
    async with session_factory() as sesion:
        fila = (
            await sesion.execute(
                text(
                    "select id::text as id, status, vip_id::text as vip_id "
                    "from turns where chat_id = :chat order by created_at desc limit 1"
                ),
                {"chat": chat_id},
            )
        ).one_or_none()
    assert fila is not None, f"no se creó ningún turno para el chat {chat_id}"
    return dict(fila._mapping)


async def _contraejemplos(
    session_factory, turn_text: str, *, vip_tg_id: int
) -> list[dict[str, Any]]:
    """Contraejemplos de ESE VIP (el contenedor es compartido entre pruebas)."""
    async with session_factory() as sesion:
        filas = (
            await sesion.execute(
                text(
                    "select e.embedding::text as embedding, e.turn_text, "
                    "e.draft_text, e.corrected_text, e.quality, "
                    "e.is_counter_example, e.vip_id::text as vip_id "
                    "from examples e "
                    "join vips v on v.id = e.vip_id "
                    "where e.turn_text = :t and e.is_counter_example "
                    "and v.telegram_user_id = :uid"
                ),
                {"t": turn_text, "uid": vip_tg_id},
            )
        ).all()
    return [dict(f._mapping) for f in filas]


async def _candidatos(session_factory, turn_id: str) -> list[dict[str, Any]]:
    async with session_factory() as sesion:
        filas = (
            await sesion.execute(
                text(
                    "select candidate_type, status from staging_candidates "
                    "where turn_id = :tid"
                ),
                {"tid": turn_id},
            )
        ).all()
    return [dict(f._mapping) for f in filas]


async def _assert_vip_nuevo(session_factory, vip_tg_id: int) -> None:
    async with session_factory() as sesion:
        previo = await sesion.execute(
            text("select count(*) from vips where telegram_user_id = :uid"),
            {"uid": vip_tg_id},
        )
        assert previo.scalar_one() == 0, (
            f"el VIP {vip_tg_id} ya existe en la base; elegir otro id de prueba"
        )


async def _app_y_vip(settings: Settings, *, engine, session_factory, bot, llm, vip_tg_id):
    app = build_app(
        settings,
        bot=bot,
        llm=llm,
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    await _assert_vip_nuevo(session_factory, vip_tg_id)
    await app.vips.add(vip_tg_id, display_name="Prueba E2")
    return app


def _huella_valida(embedding: list[float], *, quien: str) -> None:
    """La huella existe, tiene 384 dimensiones y NO es el vector de ceros."""
    assert embedding != CERO, f"{quien}: la huella quedó en ceros"
    assert len(embedding) == 384, f"{quien}: dimensión inesperada {len(embedding)}"
    assert any(x != 0.0 for x in embedding), f"{quien}: la huella es todo ceros"
    norma = sum(x * x for x in embedding) ** 0.5
    assert norma > 0.5, f"{quien}: norma sospechosamente baja ({norma})"


async def _reprender(app, bot, session_factory, vip_id: int, *, confirmar: bool) -> dict[str, Any]:
    """Flujo real de Reprender: botón → texto de la dueña → (combo)."""
    await app.dispatcher.feed_update(
        bot, _business_update(chat_id=vip_id, from_user_id=vip_id, text=TEXTO_VIP)
    )
    turn = await _turn_row(session_factory, vip_id)
    assert turn["status"] == "pending_approval", f"el turno no quedó en cola: {turn}"
    turn_id = turn["id"]

    # La dueña toca "Reprender" y escribe la lección.
    await app.dispatcher.feed_update(
        bot, _owner_callback_update(encode_callback("reprimand", turn_id))
    )
    await app.dispatcher.feed_update(bot, _owner_text_update(TEXTO_REPRENSION))

    if confirmar:
        # El combo que promociona la lección como CONTRAEJEMPLO, alcance este VIP.
        await app.dispatcher.feed_update(
            bot,
            _owner_callback_update(
                encode_reprimand_confirm(UUID(turn_id), "ex", "v"), update_id=904
            ),
        )
    return turn


# ---------------------------------------------------------------------------
# El camino completo: la lección queda como contraejemplo, con huella real
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.slow
async def test_reprender_deja_contraejemplo_con_huella_real_y_se_recupera(
    engine, session_factory, alembic_applied
) -> None:
    """Reprender guarda el contraejemplo con huella real, y la búsqueda lo halla.

    No basta con que exista la fila: el contraejemplo tiene que ser alcanzable
    por el recuperador de ejemplos (si su huella quedara en ceros, sería
    invisible para la búsqueda por parecido — el disfraz del incidente de
    agosto).
    """
    captura = CaptureHandler()
    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    app = await _app_y_vip(
        _settings(),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
        vip_tg_id=VIP_REPRENDER,
    )
    try:
        turn = await _reprender(app, bot, session_factory, VIP_REPRENDER, confirmar=True)
        turn_id = turn["id"]

        # 1) La lección quedó como candidato promocionado (no colgado).
        candidatos = await _candidatos(session_factory, turn_id)
        assert len(candidatos) == 1, (
            f"la corrección no dejó un candidato: {candidatos} "
            f"(eventos: {captura.eventos()[-12:]})"
        )
        assert candidatos[0]["status"] == "promoted", (
            f"el candidato no quedó promocionado: {candidatos}"
        )

        # 2) La fila del contraejemplo, con su texto y su alcance.
        filas = await _contraejemplos(session_factory, TEXTO_VIP, vip_tg_id=VIP_REPRENDER)
        assert len(filas) == 1, (
            f"Reprender no dejó el contraejemplo: {filas} "
            f"(eventos: {captura.eventos()[-12:]})"
        )
        fila = filas[0]
        assert fila["is_counter_example"] is True, (
            f"la fila no quedó marcada como contraejemplo: {fila}"
        )
        assert fila["corrected_text"] == TEXTO_REPRENSION, (
            f"la lección no quedó guardada: {fila}"
        )
        assert fila["vip_id"] is not None, (
            f"el contraejemplo quedó sin VIP (alcance perdido): {fila}"
        )
        assert fila["quality"] != "gold", (
            f"un contraejemplo no puede quedar como dorado: {fila}"
        )

        # 3) La huella es REAL: la produjo el motor de producción para el texto
        #    que el propio código eligió como ancla, y no es el vector de ceros.
        embedding = [float(x) for x in json.loads(fila["embedding"])]
        _huella_valida(embedding, quien="examples (contraejemplo)")
        ancla = fila["turn_text"] or fila["corrected_text"] or fila["draft_text"]
        esperado = await EmbeddingService().embed(ancla)
        desvio = max(abs(x - y) for x, y in zip(embedding, esperado))
        assert desvio < 1e-6, (
            "la huella guardada no la produjo el motor real para el texto ancla: "
            f"desvío máximo {desvio}"
        )

        # 4) El recuperador la devuelve: sin esto, la huella sería un adorno.
        turno = IncomingTurn(
            turn_id=UUID(turn_id),
            chat_id=VIP_REPRENDER,
            vip_id=UUID(fila["vip_id"]),
            text=CONSULTA_PARECIDA,
        )
        recuperador = ExamplesRetriever(
            embedding_service=EmbeddingService(),
            repo=ExamplesRepo(session_factory),
        )
        resultados = await recuperador.fetch(
            turno,
            Comprehension(
                intent="consulta_logistica",
                topics=["logistica_entrega"],
                emotion="neutral",
                urgency="baja",
                risk="bajo",
                needs_memory=False,
                needs_policy=False,
                needs_schedule=False,
                needs_examples=True,
                needs_history=False,
                needs_context=False,
            ),
        )
        assert resultados, "el recuperador de ejemplos no devolvió nada"
        contra = [r for r in resultados if "[COUNTER-EXAMPLE]" in r]
        assert contra, (
            "el contraejemplo guardado NO se recupera: la huella existe pero no "
            f"sirve para buscar. Resultados: {resultados[:3]}"
        )
        assert TEXTO_VIP in contra[0], (
            f"el contraejemplo recuperado no es el que se guardó: {contra[0]}"
        )
    finally:
        captura.close()
        await bot.session.close()


# ---------------------------------------------------------------------------
# Matriz de banderas: sin la pieza cableada no hay lección (y se ve por qué)
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quality_feedback_enabled", "staging_enabled", "vip_id"),
    [
        (False, True, VIP_REPRENDER_SIN_FEEDBACK),
        (True, False, VIP_REPRENDER_SIN_STAGING),
    ],
    ids=["sin_feedback", "sin_staging"],
)
async def test_matriz_sin_la_pieza_cableada_no_hay_contraejemplo(
    engine,
    session_factory,
    alembic_applied,
    quality_feedback_enabled: bool,
    staging_enabled: bool,
    vip_id: int,
) -> None:
    """Con la bandera apagada NO queda contraejemplo, y el motivo es visible.

    · sin ``feature_quality_feedback_enabled``: el botón "Reprender" ni se
      atiende (el teclado clásico no lo ofrece) → sin lección.
    · sin ``feature_staging_enabled``: la corrección se entrega, pero no queda
      candidato que promocionar → sin lección.
    Ninguno de los dos es un error tragado: la prueba exige que no haya fila.
    """
    captura = CaptureHandler()
    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    app = await _app_y_vip(
        _settings(
            quality_feedback_enabled=quality_feedback_enabled,
            staging_enabled=staging_enabled,
        ),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
        vip_tg_id=vip_id,
    )
    try:
        turn = await _reprender(app, bot, session_factory, vip_id, confirmar=True)

        filas = await _contraejemplos(session_factory, TEXTO_VIP, vip_tg_id=vip_id)
        assert filas == [], (
            "con la bandera apagada igual quedó un contraejemplo: "
            f"{filas} (quality_feedback={quality_feedback_enabled}, "
            f"staging={staging_enabled})"
        )
        assert await _candidatos(session_factory, turn["id"]) == [], (
            "quedó un candidato de staging con la pieza apagada"
        )
        assert app.settings.feature_quality_feedback_enabled is quality_feedback_enabled
        assert app.settings.feature_staging_enabled is staging_enabled
    finally:
        captura.close()
        await bot.session.close()
