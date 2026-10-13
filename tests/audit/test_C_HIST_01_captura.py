"""C-HIST-01 (a) — cada entrega deja su fila con texto y id de Telegram.

Prueba E2: entra por los caminos REALES de entrega (aprobar el borrador,
corregirlo, y el recontacto automático) sobre el contenedor armado por
``build_app`` y verifica el efecto en Postgres real. Solo se simulan las dos
fronteras externas: el modelo de lenguaje (``llm/fake.py``) y la salida a
Telegram (el ``bot.session`` falso, que devuelve ``message_id`` reales como
los devolvería Telegram). El resto del sistema es el de producción.

Promesa bajo prueba (``audit/contracts/C-HIST-01.md`` cláusula (a)):
"cada mensaje que la dueña envía por Diana queda en el historial del chat
(pares texto ↔ id de Telegram)". No se aserta "se llamó a
``append_owner_delivery_history``": se leen las filas de ``message_history`` y
se exige que el ``telegram_message_id`` guardado sea EXACTAMENTE el que el
canal devolvió para ese texto.

Matriz de banderas medida aquí:
  · entrega normal / corrección / recontacto  → la fila SIEMPRE se escribe (no
    hay bandera que la apague: el historial es contrato de Fase 1).
  · sesión de prueba (sandbox) activa → NO se escribe, y es a propósito
    (§4.20: la memoria del usuario es efímera en sandbox). El caso se mide en
    los dos estados y se exige el rastro del motivo, no solo la ausencia.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from pydantic import SecretStr
from sqlalchemy import text

from diana.application.ports import DeliveryRecord, TurnRecord
from diana.behavior.fake import FixedDelayPolicy
from diana.cognitive.models import Comprehension, EvaluationProfile
from diana.composition import build_app
from diana.config.settings import Settings
from diana.llm.fake import FakeLLM
from diana.telegram.keyboards import encode_callback

OWNER_ID = 999001
BOT_ID = 999002
TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"

# Fuera de los rangos reales; un id por escenario (la prueba falla si el VIP ya
# existe, así que cada escenario necesita el suyo).
VIP_NORMAL = 999000951
VIP_CORRECCION = 999000952
VIP_RECONTACTO = 999000953

TEXTO_VIP = (
    "Hola Diana, estuve pensando en lo que hablamos el otro día y quería "
    "retomar el tema para ver cómo seguimos."
)
# Lo que la dueña escribe al corregir: distinto del borrador, para poder
# distinguir en la fila cuál de los dos textos quedó guardado.
TEXTO_CORREGIDO = (
    "Hola, qué lindo leerte de nuevo. ¿Retomamos donde quedamos la última vez?"
)
TEXTO_RECONTACTO = "Hola, hace unos días que no hablamos. ¿Cómo estás?"

# Eventos que delatarían un fallo tragado al escribir el historial.
EVENTO_FALLO_ESCRITURA = "owner_history_append_failed"
EVENTO_SALTEO_SANDBOX = "owner_history_skipped_sandbox"


# ---------------------------------------------------------------------------
# Configuración: solo lo que cada escenario necesita, para que un hueco no se
# pueda atribuir a otra pieza.
# ---------------------------------------------------------------------------
def _settings(
    *,
    sandbox_enabled: bool = False,
    recontact_enabled: bool = False,
    autonomous_mode: bool = False,
    promo_enabled: bool = False,
    general_mode_enabled: bool = False,
) -> Settings:
    return Settings.model_construct(
        telegram_bot_token=SecretStr(TOKEN),
        owner_telegram_id=OWNER_ID,
        database_url=SecretStr(
            "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder"
        ),
        deepseek_api_key="",
        global_mode="autonomous" if autonomous_mode else "supervised",
        feature_sandbox_enabled=sandbox_enabled,
        feature_recontact_enabled=recontact_enabled,
        feature_autonomous_mode=autonomous_mode,
        feature_promo_enabled=promo_enabled,
        feature_general_mode_enabled=general_mode_enabled,
        feature_memory_enabled=False,
        feature_staging_enabled=False,
        feature_quality_feedback_enabled=False,
        feature_gray_zone_enabled=False,
        feature_autonomy_quality_enabled=False,
        feature_advanced_behavior=False,
        log_level="INFO",
    )


def _fake_llm() -> FakeLLM:
    """Solo el modelo externo es falso; el resto del sistema es el real.

    Dos respuestas estructuradas por turno: el Analista (comprensión) y el
    Evaluador (perfil). El Decisor NO consulta al modelo: es determinista.
    """
    return FakeLLM(
        structured_responses=[
            Comprehension(
                intent="chat",
                topics=["general"],
                emotion="neutral",
                urgency="baja",
                risk="bajo",
                needs_memory=False,
                needs_policy=False,
                needs_schedule=False,
                needs_examples=False,
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
        text_responses=["Claro, quedamos así."],
    )


class CanalFalso:
    """Doble de la salida a Telegram que guarda QUÉ se mandó y CON QUÉ id.

    Es la pieza que permite exigir el par texto ↔ id: Telegram devuelve un
    ``message_id`` por cada envío, y el contrato promete que ese id queda
    guardado junto al texto. Devolver ``None`` (como haría un doble perezoso)
    rompería el flujo por una razón que no es la que se prueba.
    """

    def __init__(self) -> None:
        self.envios: list[dict[str, Any]] = []
        self._siguiente_id = 5000

    async def __call__(self, bot: Any, method: Any, timeout: Any = None) -> Any:
        nombre = type(method).__name__
        chat_id = getattr(method, "chat_id", None)
        texto = getattr(method, "text", None) or getattr(method, "caption", None)
        self._siguiente_id += 1
        message_id = self._siguiente_id
        self.envios.append(
            {
                "metodo": nombre,
                "chat_id": chat_id,
                "texto": texto,
                "message_id": message_id,
            }
        )
        if nombre.startswith("Send"):
            return Message(
                message_id=message_id,
                date=datetime(2026, 10, 8, 12, 0, 0),
                chat=Chat(id=chat_id or 0, type="private"),
                text=str(texto) if texto else None,
            )
        return None

    def textos_a(self, chat_id: int) -> list[str]:
        return [
            str(e["texto"])
            for e in self.envios
            if e["chat_id"] == chat_id and e["texto"]
        ]

    def ids_a(self, chat_id: int) -> list[int]:
        return [
            int(e["message_id"])
            for e in self.envios
            if e["chat_id"] == chat_id and e["metodo"].startswith("Send")
        ]

    async def close(self) -> None:
        return None


class CaptureHandler(logging.Handler):
    """Captura los eventos del módulo de aplicación (en pytest el nivel raíz
    los descartaría antes de llegar aquí, así que se fija a propósito)."""

    LOGGERS = ("diana.application", "diana.behavior")

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
                    "select id::text as id, status, vip_id::text as vip_id, "
                    "created_at "
                    "from turns where chat_id = :chat order by created_at desc limit 1"
                ),
                {"chat": chat_id},
            )
        ).one_or_none()
    assert fila is not None, f"no se creó ningún turno para el chat {chat_id}"
    return dict(fila._mapping)


async def _filas_duena(session_factory, chat_id: int) -> list[dict[str, Any]]:
    """Filas del historial escritas por Diana (role='owner')."""
    async with session_factory() as sesion:
        filas = (
            await sesion.execute(
                text(
                    "select text, telegram_message_id, timestamp "
                    "from message_history where chat_id = :chat and role = 'owner' "
                    "order by id"
                ),
                {"chat": chat_id},
            )
        ).all()
    return [dict(f._mapping) for f in filas]


async def _draft_oficial(session_factory, turn_id: str) -> str:
    async with session_factory() as sesion:
        valor = (
            await sesion.execute(
                text("select draft_text from pending_approvals where turn_id = :tid"),
                {"tid": turn_id},
            )
        ).scalar_one_or_none()
    assert valor is not None, f"no hay borrador registrado para el turno {turn_id}"
    return str(valor)


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


# ---------------------------------------------------------------------------
# (a1) entrega normal — aprobar el borrador
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
async def test_entrega_normal_deja_fila_con_texto_y_su_id_de_telegram(
    engine, session_factory, alembic_applied
) -> None:
    """Aprobar deja UNA fila con el texto enviado y el id que devolvió el canal.

    Antes de aprobar no hay ninguna fila: el historial registra lo que Diana
    mandó, no lo que estuvo a punto de mandar.
    """
    captura = CaptureHandler()
    canal = CanalFalso()
    bot = Bot(token=TOKEN)
    bot.session = canal  # type: ignore[assignment]
    app = await _app_y_vip(
        _settings(),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
        vip_tg_id=VIP_NORMAL,
    )
    try:
        await app.dispatcher.feed_update(
            bot, _business_update(chat_id=VIP_NORMAL, from_user_id=VIP_NORMAL, text=TEXTO_VIP)
        )
        turn = await _turn_row(session_factory, VIP_NORMAL)
        turn_id = turn["id"]
        assert turn["status"] == "pending_approval", f"el turno no quedó en cola: {turn}"

        assert await _filas_duena(session_factory, VIP_NORMAL) == [], (
            "apareció una fila de historial ANTES de que la dueña aprobara"
        )
        borrador = await _draft_oficial(session_factory, turn_id)

        await app.dispatcher.feed_update(
            bot, _owner_callback_update(encode_callback("approve", turn_id))
        )
        turn = await _turn_row(session_factory, VIP_NORMAL)
        assert turn["status"] == "delivered", f"el turno no se entregó: {turn}"

        filas = await _filas_duena(session_factory, VIP_NORMAL)
        assert len(filas) == 1, f"se esperaba UNA fila de historial, hay {len(filas)}: {filas}"
        fila = filas[0]

        # El texto guardado es el que de verdad salió por el canal.
        enviados = canal.textos_a(VIP_NORMAL)
        assert enviados, f"el canal no registró ningún envío al VIP: {canal.envios}"
        assert fila["text"] == enviados[0], (
            f"el historial guardó {fila['text']!r} y el canal mandó {enviados[0]!r}"
        )
        assert fila["text"] == borrador, (
            "el historial no guardó el borrador aprobado: "
            f"{fila['text']!r} != {borrador!r}"
        )

        # El id de Telegram: no nulo y EXACTAMENTE el que devolvió el canal.
        assert fila["telegram_message_id"] is not None, (
            f"la fila quedó sin id de Telegram: {fila}"
        )
        assert int(fila["telegram_message_id"]) in canal.ids_a(VIP_NORMAL), (
            "el id guardado no es ninguno de los que el canal devolvió: "
            f"{fila['telegram_message_id']} vs {canal.ids_a(VIP_NORMAL)}"
        )

        # La fila es posterior al turno (es su consecuencia, no un resto previo).
        assert fila["timestamp"] >= turn["created_at"], (
            f"la fila de historial es ANTERIOR al turno que la produjo: "
            f"{fila['timestamp']} < {turn['created_at']}"
        )

        assert EVENTO_FALLO_ESCRITURA not in captura.eventos(), (
            f"la escritura del historial falló en silencio: {captura.eventos()[-10:]}"
        )
    finally:
        captura.close()
        await bot.session.close()


# ---------------------------------------------------------------------------
# (a2) corrección — la fila guarda lo CORREGIDO, no el borrador
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
async def test_correccion_deja_fila_con_el_texto_corregido_y_su_id(
    engine, session_factory, alembic_applied
) -> None:
    """Corregir deja la fila con el texto de la dueña y el id real del envío."""
    captura = CaptureHandler()
    canal = CanalFalso()
    bot = Bot(token=TOKEN)
    bot.session = canal  # type: ignore[assignment]
    app = await _app_y_vip(
        _settings(),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
        vip_tg_id=VIP_CORRECCION,
    )
    try:
        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=VIP_CORRECCION, from_user_id=VIP_CORRECCION, text=TEXTO_VIP
            ),
        )
        turn = await _turn_row(session_factory, VIP_CORRECCION)
        turn_id = turn["id"]
        borrador = await _draft_oficial(session_factory, turn_id)
        assert borrador != TEXTO_CORREGIDO, "el borrador debe diferir del texto corregido"

        # La dueña toca "Corregir" y escribe su versión.
        await app.dispatcher.feed_update(
            bot, _owner_callback_update(encode_callback("correct", turn_id))
        )
        await app.dispatcher.feed_update(bot, _owner_text_update(TEXTO_CORREGIDO))

        turn = await _turn_row(session_factory, VIP_CORRECCION)
        assert turn["status"] == "delivered", f"la corrección no entregó: {turn}"

        filas = await _filas_duena(session_factory, VIP_CORRECCION)
        assert len(filas) == 1, f"se esperaba UNA fila, hay {len(filas)}: {filas}"
        fila = filas[0]

        assert fila["text"] == TEXTO_CORREGIDO, (
            f"el historial guardó {fila['text']!r} en vez de lo corregido "
            f"{TEXTO_CORREGIDO!r} (¿se guardó el borrador descartado?)"
        )
        assert canal.textos_a(VIP_CORRECCION) == [TEXTO_CORREGIDO], (
            f"por el canal no salió el texto corregido: {canal.textos_a(VIP_CORRECCION)}"
        )
        assert fila["telegram_message_id"] is not None, f"sin id de Telegram: {fila}"
        assert int(fila["telegram_message_id"]) in canal.ids_a(VIP_CORRECCION), (
            f"el id guardado no es el del envío: {fila} vs {canal.ids_a(VIP_CORRECCION)}"
        )
        assert EVENTO_FALLO_ESCRITURA not in captura.eventos(), (
            f"escritura fallida en silencio: {captura.eventos()[-10:]}"
        )
    finally:
        captura.close()
        await bot.session.close()


# ---------------------------------------------------------------------------
# (a3) recontacto automático
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
async def test_recontacto_deja_fila_con_texto_y_su_id_de_telegram(
    engine, session_factory, alembic_applied
) -> None:
    """El recontacto por silencio también deja su fila (mismo contrato).

    Camino real: se siembra la ruta del VIP (una entrega activa, que es de donde
    el recontacto saca chat y conexión) y se corre ``execute_recontact`` del
    servicio que arma ``build_app``. El recontacto solo ENTREGA con el envío
    automático del VIP encendido; sin él queda en aviso a la dueña y no hay
    nada que historiar (se mide abajo, en la matriz).
    """
    captura = CaptureHandler()
    canal = CanalFalso()
    bot = Bot(token=TOKEN)
    bot.session = canal  # type: ignore[assignment]
    app = await _app_y_vip(
        _settings(recontact_enabled=True, autonomous_mode=True),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
        vip_tg_id=VIP_RECONTACTO,
    )
    try:
        assert app.recontact is not None, "el recontacto no quedó cableado"
        vip = await app.vips.get_by_telegram_user_id(VIP_RECONTACTO)
        assert vip is not None, "el VIP no quedó dado de alta"
        await app.vips.set_auto_send(vip.id, True)

        # Ruta: una entrega activa del VIP (chat + conexión de negocios).
        turno_ruta = await app.turns.create(
            TurnRecord(
                id=uuid4(),
                chat_id=VIP_RECONTACTO,
                status="received",
                vip_id=vip.id,
            )
        )
        await app.deliveries.insert_pending(
            DeliveryRecord(
                id=uuid4(),
                chat_id=VIP_RECONTACTO,
                business_connection_id=f"bc-audit-{VIP_RECONTACTO}",
                texts=[TEXTO_RECONTACTO],
                decision={"kind": "recontact"},
                scheduled_at=datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC),
                turn_id=turno_ruta.id,
                vip_id=vip.id,
            )
        )

        estado = await app.recontact.execute_recontact(vip.id)
        assert estado == "delivered", (
            f"el recontacto no entregó (estado {estado!r}); "
            f"eventos: {captura.eventos()[-12:]}"
        )

        filas = await _filas_duena(session_factory, VIP_RECONTACTO)
        assert len(filas) == 1, (
            f"el recontacto entregado no dejó su fila de historial: {filas}"
        )
        fila = filas[0]
        enviados = canal.textos_a(VIP_RECONTACTO)
        assert enviados, f"el canal no registró el recontacto: {canal.envios}"
        assert fila["text"] == enviados[0], (
            f"el historial guardó {fila['text']!r} y el canal mandó {enviados[0]!r}"
        )
        assert fila["telegram_message_id"] is not None, f"sin id de Telegram: {fila}"
        assert int(fila["telegram_message_id"]) in canal.ids_a(VIP_RECONTACTO), (
            f"el id guardado no es el del envío: {fila} vs {canal.ids_a(VIP_RECONTACTO)}"
        )
        assert EVENTO_FALLO_ESCRITURA not in captura.eventos(), (
            f"escritura fallida en silencio: {captura.eventos()[-10:]}"
        )
    finally:
        captura.close()
        await bot.session.close()


# ---------------------------------------------------------------------------
# Matriz: sesión de prueba (sandbox) — la fila NO se escribe, y se ve el motivo
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sandbox_activo", "filas_esperadas", "vip_id"),
    [
        (False, 1, 999000954),
        (True, 0, 999000955),
    ],
    ids=["sin_sandbox_escribe", "sandbox_no_escribe"],
)
async def test_matriz_sandbox_decide_si_la_entrega_deja_historial(
    engine,
    session_factory,
    alembic_applied,
    sandbox_activo: bool,
    filas_esperadas: int,
    vip_id: int,
) -> None:
    """El historial durable se escribe siempre, salvo en una sesión de prueba.

    Es la clasificación de los casos "entregado sin historial" que aparecen en
    producción: en sandbox la omisión es por diseño (``should_persist`` falso) y
    deja rastro ``owner_history_skipped_sandbox``; fuera de sandbox, la fila
    existe. La prueba mide los dos estados, no supone ninguno.
    """
    captura = CaptureHandler()
    canal = CanalFalso()
    bot = Bot(token=TOKEN)
    bot.session = canal  # type: ignore[assignment]
    app = await _app_y_vip(
        _settings(sandbox_enabled=sandbox_activo),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
        vip_tg_id=vip_id,
    )
    try:
        if sandbox_activo:
            assert app.sandbox is not None, "el sandbox no quedó cableado"
            activado, error = app.sandbox.activate(vip_id, "nuevo")
            assert activado, f"no se pudo activar el sandbox: {error}"
            assert app.sandbox.should_persist(vip_id) is False

        await app.dispatcher.feed_update(
            bot, _business_update(chat_id=vip_id, from_user_id=vip_id, text=TEXTO_VIP)
        )
        turn = await _turn_row(session_factory, vip_id)
        await app.dispatcher.feed_update(
            bot, _owner_callback_update(encode_callback("approve", turn["id"]))
        )
        turn = await _turn_row(session_factory, vip_id)
        assert turn["status"] == "delivered", f"el turno no se entregó: {turn}"

        filas = await _filas_duena(session_factory, vip_id)
        assert len(filas) == filas_esperadas, (
            f"con sandbox={sandbox_activo} se esperaban {filas_esperadas} fila(s): {filas}"
        )
        if filas_esperadas == 0:
            # No basta la ausencia: tiene que verse POR QUÉ, y no como error.
            assert EVENTO_SALTEO_SANDBOX in captura.eventos(), (
                "la omisión en sandbox no dejó rastro del motivo: "
                f"{captura.eventos()[-15:]}"
            )
            assert EVENTO_FALLO_ESCRITURA not in captura.eventos(), (
                f"la omisión se reportó como fallo de escritura: {captura.eventos()[-15:]}"
            )
    finally:
        captura.close()
        await bot.session.close()


# ---------------------------------------------------------------------------
# (a4) promoción a un chat que NO es VIP — el hueco por diseño de los 18 de V4
# ---------------------------------------------------------------------------
DISPARADOR_PROMO = "PROMO E2 RONDA DOS"
CHAT_PROMO = 999000956
CHAT_PROMO_APAGADA = 999000957
SECUENCIA_PROMO = [
    "Hola! Te paso mis promos.",
    "Precios en pesos mexicanos.",
    "Cualquier duda me escribes.",
]


@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("promo_habilitada", "chat_id"),
    [(True, CHAT_PROMO), (False, CHAT_PROMO_APAGADA)],
    ids=["promo_on", "promo_off"],
)
async def test_promocion_a_un_chat_que_no_es_vip_no_deja_historial_por_diseno(
    engine,
    session_factory,
    alembic_applied,
    promo_habilitada: bool,
    chat_id: int,
) -> None:
    """La promoción a un no-VIP entrega y NO escribe historial: es diseño.

    Es la clasificación de los 18 casos que el vigilante V4 marca hoy en
    producción (todos ``channel_type='atencion'``). El camino de promoción
    entrega con ``BehaviorEngine.deliver_with_sequence`` — no pasa por el
    pipeline y no llama a ``append_owner_delivery_history``. La prueba exige las
    tres cosas juntas, para que el hueco no se pueda atribuir a un no-op ni a un
    fallo tragado: (1) la secuencia SÍ salió por el canal, (2) el turno quedó
    entregado en el canal de atención, (3) el historial quedó vacío y sin
    rastro de error ni de sesión de prueba.
    """
    captura = CaptureHandler()
    canal = CanalFalso()
    bot = Bot(token=TOKEN)
    bot.session = canal  # type: ignore[assignment]
    app = build_app(
        _settings(promo_enabled=promo_habilitada, general_mode_enabled=True),
        bot=bot,
        llm=_fake_llm(),
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    try:
        # El chat NO está en la lista de VIP: es un desconocido, el público de
        # la promoción.
        async with session_factory() as sesion:
            previo = (
                await sesion.execute(
                    text("select count(*) from vips where telegram_user_id = :uid"),
                    {"uid": chat_id},
                )
            ).scalar_one()
            assert previo == 0, f"el chat {chat_id} ya es VIP; elegir otro id"
            await sesion.execute(
                text(
                    "insert into promo_triggers (id, trigger_text, response_sequence) "
                    "values (:id, :texto, cast(:seq as jsonb)) "
                    "on conflict (trigger_text) do update "
                    "set response_sequence = excluded.response_sequence"
                ),
                {
                    "id": str(uuid4()),
                    "texto": DISPARADOR_PROMO,
                    "seq": json.dumps(SECUENCIA_PROMO),
                },
            )
            await sesion.commit()

        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=chat_id, from_user_id=chat_id, text=DISPARADOR_PROMO
            ),
        )

        if not promo_habilitada:
            # Caso OFF (P7): la pieza no está cableada y NO hay efecto. Se exige
            # explícitamente que no exista turno ni envío — no basta con que
            # "no se llame a nada".
            async with session_factory() as sesion:
                turnos = (
                    await sesion.execute(
                        text("select count(*) from turns where chat_id = :c"),
                        {"c": chat_id},
                    )
                ).scalar_one()
            assert turnos == 0, (
                f"con la promoción apagada se creó un turno ({turnos}): la "
                "medición del caso encendido no vale"
            )
            assert canal.textos_a(chat_id) == [], (
                f"con la promoción apagada igual se envió algo: {canal.envios}"
            )
            assert await _filas_duena(session_factory, chat_id) == [], (
                "con la promoción apagada se escribió historial"
            )
            return

        turno = await _turn_row(session_factory, chat_id)
        assert turno["status"] == "delivered", f"la promoción no se entregó: {turno}"

        # (1) La secuencia SÍ salió: el hueco no es "no se mandó nada".
        enviados = canal.textos_a(chat_id)
        assert enviados == SECUENCIA_PROMO, (
            f"la secuencia no salió como estaba definida: {enviados}"
        )

        # (2) El turno queda en el canal de atención (modo general encendido),
        #     que es exactamente lo que V4 ve en producción.
        async with session_factory() as sesion:
            canal_tipo = (
                await sesion.execute(
                    text(
                        "select channel_type from turns where chat_id = :c "
                        "order by created_at desc limit 1"
                    ),
                    {"c": chat_id},
                )
            ).scalar_one()
        assert canal_tipo == "atencion", (
            f"canal inesperado para una promoción con modo general: {canal_tipo}"
        )

        # (3) Y NO deja historial — el hueco por diseño, no un fallo.
        assert await _filas_duena(session_factory, chat_id) == [], (
            "la promoción escribió historial: la clasificación de los 18 casos "
            "del vigilante V4 cambia"
        )
        assert EVENTO_FALLO_ESCRITURA not in captura.eventos(), (
            f"la escritura del historial falló en silencio: {captura.eventos()[-10:]}"
        )
        assert EVENTO_SALTEO_SANDBOX not in captura.eventos(), (
            "el hueco se atribuyó a una sesión de prueba (sandbox): "
            f"{captura.eventos()[-10:]}"
        )
    finally:
        captura.close()
        await bot.session.close()
