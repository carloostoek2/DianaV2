"""C-CTX-01 — el contexto temporal interpretado llega al modelo, y se retira al vencer.

Prueba E2 sobre Postgres real, con el contenedor armado por ``build_app`` y el
pipeline completo. Solo se simula el modelo de lenguaje externo (``FakeLLM``
determinista): el almacén, el escritor post-turno y el lector son los reales.

Promesa bajo prueba (REQ-MEM-06):
 1. Con la bandera encendida y un snapshot vigente en ``contexts``, el bloque
    ``knowledge.context`` que recibe el modelo sale DEL SNAPSHOT.
 2. Con el snapshot vencido, ese bloque NO se usa: se deriva del historial.
 3. Con la bandera apagada, el snapshot no se lee (comportamiento previo intacto).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from diana.application.ports import VipInboundMessage
from diana.behavior.fake import FixedDelayPolicy
from diana.cognitive.models import Comprehension, EvaluationProfile
from diana.cognitive.retrievers.context import _is_first_message_of_day, _to_cdmx
from diana.composition import build_app
from diana.config.settings import Settings
from diana.llm.fake import FakeLLM

TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"


class SpyBotSession:
    """Doble de la salida a Telegram: ningún mensaje sale de la máquina.

    Devuelve un mensaje mínimo (con `message_id`) porque el aviso a la dueña
    encola el id del mensaje del borrador.
    """

    def __init__(self) -> None:
        self.methods: list[str] = []

    async def __call__(self, bot: Any, method: Any, timeout: Any = None) -> Any:
        self.methods.append(type(method).__name__)
        return SimpleNamespace(message_id=len(self.methods))

    async def close(self) -> None:
        return None


def _bot():
    from aiogram import Bot

    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    return bot

CONTEXT_MARK = "## Knowledge: knowledge.context"

# Un chat por escenario: el contenedor de la sesión acumula filas entre pruebas.
CHAT_ACTIVO = 999000881
CHAT_VENCIDO = 999000882
CHAT_BANDERA_OFF = 999000883

# El snapshot dice lo contrario que el historial sembrado: así se distingue
# "salió del snapshot" de "salió del historial".
SNAPSHOT_HECHOS: dict[str, Any] = {
    "waiting_for_reply_since": None,
    "is_first_message_of_day": True,
    "dia_semana": "lunes",
    "hora_actual": "00:00",
}

# Clave que SOLO existe en el snapshot: prueba que el snapshot se sigue leyendo
# (si el almacén se desconectara, esta clave desaparecería del prompt).
CLAVE_SOLO_DEL_SNAPSHOT = "tema_pendiente"


def _settings(*, context_enabled: bool) -> Settings:
    return Settings.model_construct(
        telegram_bot_token=SecretStr(TOKEN),
        owner_telegram_id=999001,
        database_url=SecretStr(
            "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder"
        ),
        deepseek_api_key="",
        global_mode="supervised",
        feature_context_enabled=context_enabled,
        feature_memory_enabled=False,
        log_level="INFO",
    )


def _comprehension() -> Comprehension:
    """Comprensión con `needs_context` encendido y sin saludo puro."""
    return Comprehension(
        intent="consultar",
        topics=["contenido"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_history=True,
        needs_context=True,
        needs_memory=False,
        needs_policy=False,
        needs_schedule=False,
        needs_examples=False,
    )


def _profile() -> EvaluationProfile:
    return EvaluationProfile(
        naturalness=0.9,
        precision=0.8,
        doctrine=0.85,
        consistency=0.9,
        safety=0.95,
        coverage=0.7,
        empathy=0.8,
    )


def _fake_llm() -> FakeLLM:
    """Analista y Evaluador con esquema; Generador en texto. Decisor determinista."""
    return FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=["Claro, te cuento."],
    )


async def _seed_vip(session_factory, telegram_user_id: int) -> str:
    async with session_factory() as session:
        vip_id = (
            await session.execute(
                text(
                    "insert into vips (telegram_user_id, display_name) "
                    "values (:t, 'Prueba contexto') returning id"
                ),
                {"t": telegram_user_id},
            )
        ).scalar_one()
        await session.commit()
        return str(vip_id)


async def _seed_history(session_factory, chat_id: int, n: int) -> None:
    """Siembra `n` mensajes del VIP de hoy, para que la derivación en vivo diga
    `is_first_message_of_day = False` (más de uno en el día)."""
    now = datetime.now(UTC)
    async with session_factory() as session:
        for i in range(n):
            await session.execute(
                text(
                    "insert into message_history "
                    "(chat_id, telegram_message_id, role, text, timestamp) "
                    "values (:c, :m, 'vip', :t, :ts)"
                ),
                {"c": chat_id, "m": 900000 + i, "t": f"previo {i}", "ts": now},
            )
        await session.commit()


async def _seed_snapshot(
    session_factory,
    chat_id: int,
    *,
    vip_id: str | None,
    expira_en_horas: float,
    hechos: dict[str, Any] | None = None,
) -> None:
    ahora = datetime.now(UTC)
    body = {
        "tipo": "interpretado",
        "hechos": {**(hechos or SNAPSHOT_HECHOS), CLAVE_SOLO_DEL_SNAPSHOT: "entrega"},
    }
    emb = "[" + ",".join(["0.01"] * 384) + "]"
    async with session_factory() as session:
        await session.execute(
            text(
                "insert into contexts (chat_id, vip_id, embedding, content, expires_at) "
                "values (:c, cast(:v as uuid), cast(:e as vector), cast(:b as jsonb), :x)"
            ),
            {
                "c": chat_id,
                "v": vip_id,
                "e": emb,
                "b": json.dumps(body),
                "x": ahora + timedelta(hours=expira_en_horas),
            },
        )
        await session.commit()


def _bloque_contexto(llm: FakeLLM) -> dict[str, Any] | None:
    """Extrae el bloque `knowledge.context` del prompt que recibió el modelo."""
    for method, kwargs in llm.calls:
        if method != "generate":
            continue
        texto = "\n".join(
            str(m.get("content") or "") for m in kwargs.get("messages", [])
        )
        i = texto.find(CONTEXT_MARK)
        if i < 0:
            continue
        resto = texto[i + len(CONTEXT_MARK):]
        j = resto.find("{")
        k = resto.find("\n}", j)
        if j < 0 or k < 0:
            continue
        return json.loads(resto[j:k + 2])
    return None


async def _correr_turno(app, chat_id: int, telegram_message_id: int):
    return await app.orchestrator.handle_vip_message(
        VipInboundMessage(
            chat_id=chat_id,
            text="quiero saber si el video premium es nuevo",
            telegram_message_id=telegram_message_id,
            business_connection_id="bc-ctx-audit",
        )
    )


@pytest.mark.db
@pytest.mark.asyncio
async def test_la_derivacion_en_vivo_gana_al_snapshot_vigente(
    engine, session_factory, alembic_applied
) -> None:
    """Regresión del defecto medido en producción.

    Las cuatro claves del bloque describen el momento presente, así que un
    snapshot escrito al cerrar el turno anterior no puede aportarlas: el bloque
    que recibe el modelo tiene que coincidir con el historial que está leyendo
    en el mismo prompt. El snapshot se sigue leyendo (aporta sus claves propias).
    """
    vivo = await _seed_vip(session_factory, CHAT_ACTIVO)
    await _seed_history(session_factory, CHAT_ACTIVO, 3)
    await _seed_snapshot(session_factory, CHAT_ACTIVO, vip_id=vivo, expira_en_horas=2)

    llm = _fake_llm()
    bot = _bot()
    app = build_app(
        _settings(context_enabled=True),
        bot=bot,
        llm=llm,
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    await _correr_turno(app, CHAT_ACTIVO, 1)

    bloque = _bloque_contexto(llm)
    assert bloque is not None, f"el prompt no trae el bloque de contexto: {llm.calls}"

    # El snapshot vigente dice lo contrario que el historial: gana el historial.
    assert bloque["is_first_message_of_day"] is False, (
        f"el bloque trae el valor viejo del snapshot: {bloque}"
    )
    assert bloque["waiting_for_reply_since"] is not None, (
        f"el bloque dice que no hay respuesta pendiente con el cliente "
        f"escribiendo: {bloque}"
    )
    # Y el snapshot se sigue leyendo: su clave propia llega al prompt.
    assert bloque.get(CLAVE_SOLO_DEL_SNAPSHOT) == "entrega", (
        f"el snapshot dejó de leerse (almacén desconectado): {bloque}"
    )
    # El historial sembrado dice lo contrario: la prueba distingue de verdad.
    ahora = datetime.now(UTC)
    filas_vip = [{"role": "vip", "timestamp": ahora.isoformat()}] * 3
    assert _is_first_message_of_day(filas_vip, today=_to_cdmx(ahora).date()) is False, (
        "el escenario no distingue snapshot de historial: revisar la siembra"
    )


@pytest.mark.db
@pytest.mark.asyncio
async def test_el_snapshot_vencido_no_se_usa(
    engine, session_factory, alembic_applied
) -> None:
    """Al vencer, el bloque se deriva del historial (el snapshot se retira)."""
    vivo = await _seed_vip(session_factory, CHAT_VENCIDO)
    await _seed_history(session_factory, CHAT_VENCIDO, 3)
    await _seed_snapshot(
        session_factory, CHAT_VENCIDO, vip_id=vivo, expira_en_horas=-1
    )

    llm = _fake_llm()
    bot = _bot()
    app = build_app(
        _settings(context_enabled=True),
        bot=bot,
        llm=llm,
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    await _correr_turno(app, CHAT_VENCIDO, 2)

    bloque = _bloque_contexto(llm)
    assert bloque is not None, "el prompt no trae el bloque de contexto"
    assert bloque["is_first_message_of_day"] is False, (
        f"se siguió usando un snapshot vencido: {bloque}"
    )
    assert bloque["waiting_for_reply_since"] is not None, (
        f"se siguió usando un snapshot vencido: {bloque}"
    )


@pytest.mark.db
@pytest.mark.asyncio
async def test_con_la_bandera_apagada_el_snapshot_no_se_lee(
    engine, session_factory, alembic_applied
) -> None:
    """Bandera apagada: el repositorio no se inyecta y todo se deriva en vivo."""
    vivo = await _seed_vip(session_factory, CHAT_BANDERA_OFF)
    await _seed_history(session_factory, CHAT_BANDERA_OFF, 3)
    await _seed_snapshot(
        session_factory, CHAT_BANDERA_OFF, vip_id=vivo, expira_en_horas=2
    )

    llm = _fake_llm()
    bot = _bot()
    app = build_app(
        _settings(context_enabled=False),
        bot=bot,
        llm=llm,
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    await _correr_turno(app, CHAT_BANDERA_OFF, 3)

    bloque = _bloque_contexto(llm)
    assert bloque is not None, "el prompt no trae el bloque de contexto"
    assert bloque["is_first_message_of_day"] is False, (
        f"con la bandera apagada se leyó el snapshot: {bloque}"
    )
    assert bloque["waiting_for_reply_since"] is not None, (
        f"con la bandera apagada se leyó el snapshot: {bloque}"
    )
