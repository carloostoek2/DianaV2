"""C-EMB-01 (tramos ejemplo / política / memoria) — la huella es real y busca.

Prueba E2: entra por los caminos REALES que guardan cada cosa (mensaje VIP que
termina entregado → extracción post-turno; botón "Destacar" de la dueña;
respuesta de doctrina de la dueña) sobre el contenedor armado por ``build_app``
y verifica el efecto en Postgres real. No se simula el motor de huellas: se usa
el que arma producción. El único simulado es el modelo de lenguaje externo
(``llm/fake.py``).

Promesa bajo prueba (``audit/contracts/C-EMB-01.md``): lo que Diana "recuerda"
se guarda con su huella semántica real (384 dimensiones, NO el vector de ceros)
y la recuperación por parecido lo encuentra y lo pone primero.

Nota de alcance: el tramo ``profiles`` ya está cubierto por
``tests/audit/test_C_EMB_01.py`` (ronda anterior). Este archivo cubre las tres
tablas que quedaron sin re-medir: ``memories``, ``examples`` y ``policies``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from pydantic import SecretStr
from sqlalchemy import text

from diana.application.memory_backfill_service import HechoExtracted, WindowExtraction
from diana.application.policy_embedding import policy_embedding_text
from diana.behavior.fake import FixedDelayPolicy
from diana.cognitive.embedding import EmbeddingService
from diana.cognitive.models import Comprehension, EvaluationProfile, IncomingTurn
from diana.cognitive.retrievers.examples import ExamplesRetriever
from diana.cognitive.retrievers.memory import MemoryRetriever
from diana.cognitive.retrievers.policy import PolicyRetriever
from diana.composition import build_app
from diana.config.settings import Settings
from diana.infrastructure.db.repositories.examples import ExamplesRepo
from diana.infrastructure.db.repositories.memories import MemoriesRepo
from diana.infrastructure.db.repositories.policies import PoliciesRepo
from diana.llm.fake import FakeLLM
from diana.telegram.keyboards import (
    encode_callback,
    encode_doctrine_callback,
    encode_doctrine_scope,
    encode_gold_confirm,
)

OWNER_ID = 999001
BOT_ID = 999002
TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"

# Fuera de los rangos reales; un id por escenario.
VIP_MEMORIA = 999000901
VIP_EJEMPLO = 999000911
VIP_POLITICA = 999000921

# Texto con sustancia y muy distintivo: la copia de la base real tiene datos
# reales (miles de filas), así que una consulta genérica podría tener un vecino
# más cercano y la prueba no podría distinguir lo suyo de lo ajeno.
TEXTO_VIP_MEMORIA = (
    "Hola Diana, te cuento que me mudé a Villa Merced de los Andes y desde "
    "ahora voy a estar disponible solamente los martes por la tarde."
)
HECHO_MEMORIA = "Está disponible solamente los martes por la tarde."
# Paráfrasis real (no copia del hecho). Medido: 0.563 de parecido contra el
# hecho guardado, por encima del umbral 0.52 del recuperador de memoria.
CONSULTA_PARECIDA_MEMORIA = "¿Qué días estoy disponible por la tarde?"

TEXTO_VIP_EJEMPLO = (
    "Hola Diana, quiero coordinar la entrega del kit de bienvenida en la "
    "terminal de ómnibus de Villa Merced de los Andes."
)
CONSULTA_PARECIDA_EJEMPLO = (
    "Quiero coordinar la entrega del kit de bienvenida en la terminal de "
    "ómnibus de Villa Merced de los Andes."
)

# Zona gris: un tema que NO está en el catálogo de reglas fijas, para que el
# pipeline pida doctrina de verdad en vez de encontrar una regla ya escrita.
TEMA_SIN_REGLA = "logistica_entrega"
PREGUNTA_POLITICA = (
    "¿Puedo cambiar la dirección de entrega del kit después de la confirmación?"
)
REGLA_POLITICA = "El envío se puede reprogramar una vez sin costo."

CERO = [0.0] * 384


# ---------------------------------------------------------------------------
# Configuración: se enciende SOLO la bandera del camino bajo prueba.
# ---------------------------------------------------------------------------
def _settings(
    *,
    memory_enabled: bool = False,
    quality_feedback_enabled: bool = False,
    staging_enabled: bool = False,
    gray_zone_enabled: bool = False,
) -> Settings:
    return Settings.model_construct(
        telegram_bot_token=SecretStr(TOKEN),
        owner_telegram_id=OWNER_ID,
        database_url=SecretStr(
            "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder"
        ),
        deepseek_api_key="",
        global_mode="supervised",
        feature_memory_enabled=memory_enabled,
        feature_quality_feedback_enabled=quality_feedback_enabled,
        feature_staging_enabled=staging_enabled,
        feature_gray_zone_enabled=gray_zone_enabled,
        feature_gray_zone_proposal_enabled=False,
        feature_autonomy_quality_enabled=False,
        feature_autonomous_mode=False,
        feature_sandbox_enabled=False,
        log_level="INFO",
    )


def _fake_llm(
    *,
    structured: list[Any],
    textos: list[str] | None = None,
) -> FakeLLM:
    """Solo el modelo externo es falso; el resto del sistema es el real.

    Un turno consume un borrador y, si hay regeneración (doctrina), otro más.
    """
    return FakeLLM(
        structured_responses=structured,
        text_responses=textos or ["Claro, quedamos así."],
    )


def _comprension(**overrides: Any) -> Comprehension:
    datos: dict[str, Any] = {
        "intent": "chat",
        "topics": ["general"],
        "emotion": "neutral",
        "urgency": "baja",
        "risk": "bajo",
        "needs_memory": False,
        "needs_policy": False,
        "needs_schedule": False,
        "needs_examples": False,
        "needs_history": True,
        "needs_context": True,
    }
    datos.update(overrides)
    return Comprehension(**datos)


def _evaluacion() -> EvaluationProfile:
    return EvaluationProfile(
        naturalness=0.9,
        precision=0.9,
        doctrine=0.9,
        consistency=0.9,
        safety=0.95,
        coverage=0.9,
        empathy=0.9,
    )


class SpyBotSession:
    """Doble de la salida a Telegram: ningún mensaje sale de la máquina."""

    def __init__(self) -> None:
        self.methods: list[str] = []

    async def __call__(self, bot: Any, method: Any, timeout: Any = None) -> Any:
        name = type(method).__name__
        self.methods.append(name)
        if name.startswith("Send"):
            texto = getattr(method, "text", None) or getattr(method, "caption", None)
            return Message(
                message_id=1000 + len(self.methods),
                date=datetime(2026, 10, 8, 12, 0, 0),
                chat=Chat(id=getattr(method, "chat_id", 0) or 0, type="private"),
                text=str(texto) if texto else None,
            )
        return None

    async def close(self) -> None:
        return None


class CaptureHandler(logging.Handler):
    """Captura eventos INFO de los módulos bajo prueba (pytest los descarta)."""

    LOGGERS = ("diana.application", "diana.infrastructure.db.repositories")

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
    """Mensaje privado real de la dueña (texto libre)."""
    msg = Message(
        message_id=update_id,
        date=datetime(2026, 10, 8, 12, 5, 0),
        chat=Chat(id=OWNER_ID, type="private"),
        from_user=User(id=OWNER_ID, is_bot=False, first_name="Duenia"),
        text=texto,
    )
    return Update(update_id=update_id, message=msg)


async def _turn_id(session_factory, chat_id: int) -> str:
    async with session_factory() as sesion:
        fila = (
            await sesion.execute(
                text(
                    "select id::text as id, status from turns where chat_id = :chat "
                    "order by created_at desc limit 1"
                ),
                {"chat": chat_id},
            )
        ).one_or_none()
    assert fila is not None, f"no se creó ningún turno para el chat {chat_id}"
    return fila.id


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


async def _huella_esperada(texto: str) -> list[float]:
    """Lo que el motor REAL produce para ese texto."""
    return await EmbeddingService().embed(texto)


def _desvio_maximo(a: list[float], b: list[float]) -> float:
    return max(abs(x - y) for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# memories
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.slow
async def test_memoria_del_turno_real_lleva_huella_y_se_recupera(
    engine, session_factory, alembic_applied
) -> None:
    """La extracción post-turno guarda el hecho con huella real y se recupera.

    Camino: mensaje VIP → pipeline real → entrega aprobada por la dueña →
    extracción post-turno (el servicio que arma ``build_app``) → fila en
    ``memories``. Después: el recuperador de memoria del VIP lo devuelve
    PRIMERO para una consulta parecida.
    """
    captura = CaptureHandler()
    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    llm = _fake_llm(
        structured=[
            _comprension(),
            _evaluacion(),
            # Respuesta del extractor post-turno (mismo esquema que producción).
            WindowExtraction(
                hechos=[
                    HechoExtracted(
                        seccion="preferencias",
                        texto=HECHO_MEMORIA,
                        confianza=0.9,
                    )
                ]
            ),
        ]
    )
    app = await _app_y_vip(
        _settings(memory_enabled=True),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=llm,
        vip_tg_id=VIP_MEMORIA,
    )
    try:
        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=VIP_MEMORIA, from_user_id=VIP_MEMORIA, text=TEXTO_VIP_MEMORIA
            ),
        )
        turn_id = await _turn_id(session_factory, VIP_MEMORIA)
        await app.dispatcher.feed_update(
            bot, _owner_callback_update(encode_callback("approve", turn_id))
        )

        # --- La fila real en `memories` -----------------------------------
        async with session_factory() as sesion:
            fila = (
                await sesion.execute(
                    text(
                        "select m.embedding::text as embedding, m.content, "
                        "m.category, m.status, m.vip_id::text as vip_id "
                        "from memories m join vips v on v.id = m.vip_id "
                        "where v.telegram_user_id = :uid and m.category = :cat"
                    ),
                    {"uid": VIP_MEMORIA, "cat": "preferencias"},
                )
            ).one_or_none()

        assert fila is not None, (
            "la extracción post-turno no guardó ningún hecho: "
            f"eventos vistos: {captura.eventos()[-15:]}"
        )
        assert HECHO_MEMORIA in str(fila.content), (
            f"el hecho no quedó guardado: {fila.content}"
        )

        import json

        embedding = [float(x) for x in json.loads(fila.embedding)]
        _huella_valida(embedding, quien="memories")

        # Salió DEL MOTOR REAL: coincide con el mismo texto pasado por él.
        esperado = await _huella_esperada(HECHO_MEMORIA)
        assert _desvio_maximo(embedding, esperado) < 1e-6, (
            "la huella guardada no la produjo el motor real"
        )

        # --- Y el recuperador lo devuelve PRIMERO --------------------------
        turno = IncomingTurn(
            turn_id=uuid4(),
            chat_id=VIP_MEMORIA,
            vip_id=UUID(fila.vip_id),
            text=CONSULTA_PARECIDA_MEMORIA,
        )
        recuperador = MemoryRetriever(
            embedding_service=EmbeddingService(),
            repo=MemoriesRepo(session_factory),
        )
        resultados = await recuperador.fetch(turno, _comprension(needs_memory=True))
        assert resultados, (
            "el recuperador de memoria no devolvió nada para una consulta parecida"
        )
        assert HECHO_MEMORIA in resultados[0], (
            f"el hecho no quedó primero en la recuperación: {resultados}"
        )
    finally:
        captura.close()
        await bot.session.close()


# ---------------------------------------------------------------------------
# examples
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.slow
async def test_ejemplo_dorado_destacado_lleva_huella_y_se_recupera(
    engine, session_factory, alembic_applied
) -> None:
    """El botón "Destacar" de la dueña guarda el ejemplo con huella real.

    Camino: mensaje VIP → pipeline real → cola de la dueña → Destacar (alcance
    este VIP) → fila dorada en ``examples``. Después: el recuperador de ejemplos
    lo devuelve PRIMERO para una consulta parecida.
    """
    captura = CaptureHandler()
    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    llm = _fake_llm(structured=[_comprension(), _evaluacion()])
    app = await _app_y_vip(
        _settings(quality_feedback_enabled=True, staging_enabled=True),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=llm,
        vip_tg_id=VIP_EJEMPLO,
    )
    try:
        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=VIP_EJEMPLO, from_user_id=VIP_EJEMPLO, text=TEXTO_VIP_EJEMPLO
            ),
        )
        turn_id = await _turn_id(session_factory, VIP_EJEMPLO)

        # La dueña: Destacar → alcance "este VIP".
        await app.dispatcher.feed_update(
            bot, _owner_callback_update(encode_callback("gold", turn_id))
        )
        await app.dispatcher.feed_update(
            bot,
            _owner_callback_update(
                encode_gold_confirm(UUID(turn_id), "v"), update_id=902
            ),
        )

        async with session_factory() as sesion:
            fila = (
                await sesion.execute(
                    text(
                        "select e.embedding::text as embedding, e.turn_text, "
                        "e.quality, e.vip_id::text as vip_id, e.is_counter_example "
                        "from examples e where e.turn_text = :t"
                    ),
                    {"t": TEXTO_VIP_EJEMPLO},
                )
            ).one_or_none()

        assert fila is not None, (
            "Destacar no guardó el ejemplo dorado: "
            f"eventos vistos: {captura.eventos()[-15:]}"
        )
        assert fila.quality == "gold", f"no quedó como dorado: {fila.quality}"
        assert fila.is_counter_example is False

        import json

        embedding = [float(x) for x in json.loads(fila.embedding)]
        _huella_valida(embedding, quien="examples")
        esperado = await _huella_esperada(TEXTO_VIP_EJEMPLO)
        assert _desvio_maximo(embedding, esperado) < 1e-6, (
            "la huella guardada no la produjo el motor real"
        )

        turno = IncomingTurn(
            turn_id=uuid4(),
            chat_id=VIP_EJEMPLO,
            vip_id=UUID(fila.vip_id),
            text=CONSULTA_PARECIDA_EJEMPLO,
        )
        recuperador = ExamplesRetriever(
            embedding_service=EmbeddingService(),
            repo=ExamplesRepo(session_factory),
        )
        resultados = await recuperador.fetch(turno, _comprension(needs_examples=True))
        assert resultados, "el recuperador de ejemplos no devolvió nada"
        assert TEXTO_VIP_EJEMPLO in resultados[0], (
            f"el ejemplo guardado no quedó primero: {resultados[:3]}"
        )
    finally:
        captura.close()
        await bot.session.close()


# ---------------------------------------------------------------------------
# policies
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.slow
async def test_politica_de_zona_gris_lleva_huella_y_se_recupera(
    engine, session_factory, alembic_applied
) -> None:
    """La regla que escribe la dueña se guarda VIVA con huella real.

    Camino: mensaje VIP sin regla aplicable → el pipeline pide doctrina (zona
    gris, VIP congelado) → la dueña responde con la regla ("Escribir regla" +
    texto libre) → ``policies`` con la regla viva. Después: el recuperador de
    reglas la devuelve para una consulta parecida.
    """
    from uuid import UUID as _UUID

    captura = CaptureHandler()
    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    comprehension = _comprension(
        intent="consulta_logistica",
        topics=[TEMA_SIN_REGLA],
        needs_policy=True,
    )
    regen_comprehension = _comprension(
        intent="consulta_logistica",
        topics=[TEMA_SIN_REGLA],
        needs_policy=True,
    )
    llm = _fake_llm(
        structured=[
            comprehension,
            _evaluacion(),
            regen_comprehension,
            _evaluacion(),
        ],
        textos=[
            "Déjame confirmarlo con el equipo.",
            "Sí, se puede reprogramar sin costo.",
        ],
    )
    app = await _app_y_vip(
        _settings(gray_zone_enabled=True),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=llm,
        vip_tg_id=VIP_POLITICA,
    )
    try:
        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=VIP_POLITICA, from_user_id=VIP_POLITICA, text=PREGUNTA_POLITICA
            ),
        )
        turn_id = await _turn_id(session_factory, VIP_POLITICA)
        async with session_factory() as sesion:
            estado = (
                await sesion.execute(
                    text("select status from turns where id = :tid"), {"tid": turn_id}
                )
            ).scalar_one()
        assert estado == "gray_zone", (
            f"el pipeline no abrió zona gris: {estado} · eventos {captura.eventos()[-10:]}"
        )

        # La dueña escribe la regla (botón real + texto libre real).
        await app.dispatcher.feed_update(
            bot, _owner_callback_update(encode_doctrine_callback(_UUID(turn_id)))
        )
        await app.dispatcher.feed_update(
            bot,
            _owner_text_update(REGLA_POLITICA, update_id=903),
        )
        # La dueña confirma el alcance (a todos): solo entonces se guarda la regla.
        await app.dispatcher.feed_update(
            bot,
            _owner_callback_update(
                encode_doctrine_scope(_UUID(turn_id), "all"), update_id=904
            ),
        )

        async with session_factory() as sesion:
            fila = (
                await sesion.execute(
                    text(
                        "select p.embedding::text as embedding, "
                        "p.trigger_description, p.rule, p.is_active, p.scope "
                        "from policies p where p.rule = :r"
                    ),
                    {"r": REGLA_POLITICA},
                )
            ).one_or_none()

        assert fila is not None, (
            "la regla de la dueña no quedó viva en policies: "
            f"eventos vistos: {captura.eventos()[-20:]}"
        )
        assert fila.is_active is True
        assert fila.trigger_description == PREGUNTA_POLITICA, (
            f"el disparador de la regla no es la pregunta del VIP: {fila.trigger_description}"
        )

        import json

        embedding = [float(x) for x in json.loads(fila.embedding)]
        _huella_valida(embedding, quien="policies")

        esperado = await EmbeddingService().embed(
            policy_embedding_text(fila.trigger_description, fila.rule)
        )
        assert _desvio_maximo(embedding, esperado) < 1e-6, (
            "la huella guardada no la produjo el motor real"
        )

        turno = IncomingTurn(
            turn_id=uuid4(),
            chat_id=VIP_POLITICA,
            vip_id=None,
            text=PREGUNTA_POLITICA,
        )
        recuperador = PolicyRetriever(
            embedding_service=EmbeddingService(),
            repo=PoliciesRepo(session_factory),
            static_policies=None,
        )
        resultados = await recuperador.fetch(
            turno, _comprension(topics=[TEMA_SIN_REGLA], needs_policy=True)
        )
        assert resultados, (
            "el recuperador de reglas no devolvió nada para una consulta parecida: "
            "la regla quedó guardada pero es invisible para la búsqueda"
        )
        assert REGLA_POLITICA in resultados[0], (
            f"la regla guardada no quedó primera: {resultados[:3]}"
        )
    finally:
        captura.close()
        await bot.session.close()
