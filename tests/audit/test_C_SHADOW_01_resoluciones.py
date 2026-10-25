"""C-SHADOW-01 (tramos que faltaban) — corregir, escalar y la reacción del VIP.

La ronda anterior probó ``approved_as_is``. Faltaban, según el propio contrato
(``audit/contracts/C-SHADOW-01.md`` → "Sin cubrir"): los tramos ``corrected`` y
``escalated`` de ``owner_outcome``, y la reacción del VIP (``vip_signal``) por
sus DOS caminos reales — el gancho inmediato cuando el VIP contesta, y el job
de respaldo cuando no contesta (o cuando su respuesta nunca pasó por el
pipeline).

Prueba E2: entra por los caminos reales (botón de la dueña sobre el DM del
borrador; mensaje de negocio del VIP; el ciclo del job) sobre el contenedor
armado por ``build_app``, contra Postgres real. Solo el modelo de lenguaje y la
salida a Telegram son falsos. Nunca se aserta "se llamó a X": se leen filas.

Matriz de bandera (``feature_autonomy_quality_enabled``):
  ON  → los tres tramos escriben su valor real.
  OFF → no hay fila que escribir: el orquestador recibe ``outcome_log=None`` y
        el clasificador de reacción va en ``None``. Se mide en los dos estados.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from pydantic import SecretStr
from sqlalchemy import text

from diana.behavior.fake import FixedDelayPolicy
from diana.cognitive.models import Comprehension, EvaluationProfile
from diana.composition import build_app
from diana.config.settings import Settings
from diana.jobs.outcome_reaction import run_outcome_reaction_cycle
from diana.llm.fake import FakeLLM
from diana.telegram.keyboards import encode_callback

OWNER_ID = 999001
BOT_ID = 999002
TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"

# Fuera de los rangos reales; un id por escenario.
VIP_CORRIGE_ON = 999000961
VIP_CORRIGE_OFF = 999000962
VIP_ESCALA_ON = 999000963
VIP_ESCALA_OFF = 999000964
VIP_SENAL_HOOK = 999000965
VIP_SENAL_JOB_SILENCIO = 999000966
VIP_SENAL_JOB_TEXTO = 999000967

TEXTO_VIP = (
    "Hola Diana, estuve pensando en lo que hablamos el otro día y quería "
    "retomar el tema para ver cómo seguimos."
)
TEXTO_CORREGIDO = (
    "Hola, qué lindo leerte de nuevo. ¿Retomamos donde quedamos la última vez?"
)
# Reacción positiva del VIP: el léxico del clasificador es determinista
# ("gracias"/"genial") y la emoción del Analista también manda.
TEXTO_REACCION = "Gracias Diana, genial lo que me cuentas."

EVENTOS_DE_FALLO = frozenset(
    {
        "outcome_log_error",
        "outcome_record_shadow_failed",
        "outcome_record_owner_failed",
        "outcome_reaction_error",
        "outcome_record_reaction_failed",
    }
)


# ---------------------------------------------------------------------------
# Configuración: solo la bandera bajo prueba cambia.
# ---------------------------------------------------------------------------
def _settings(*, quality_enabled: bool) -> Settings:
    return Settings.model_construct(
        telegram_bot_token=SecretStr(TOKEN),
        owner_telegram_id=OWNER_ID,
        database_url=SecretStr(
            "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder"
        ),
        deepseek_api_key="",
        global_mode="supervised",
        feature_autonomy_quality_enabled=quality_enabled,
        feature_memory_enabled=False,
        feature_staging_enabled=False,
        feature_quality_feedback_enabled=False,
        feature_gray_zone_enabled=False,
        feature_autonomous_mode=False,
        feature_sandbox_enabled=False,
        feature_autonomy_readiness_enabled=False,
        log_level="INFO",
    )


def _comprension(*, emotion: str = "neutral") -> Comprehension:
    return Comprehension(
        intent="chat",
        topics=["general"],
        emotion=emotion,
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=False,
        needs_schedule=False,
        needs_examples=False,
        needs_history=True,
        needs_context=True,
    )


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


def _fake_llm(*, emociones: list[str] | None = None) -> FakeLLM:
    """Solo el modelo externo es falso; el resto del sistema es el real.

    Un turno consume una comprensión y una evaluación. La prueba de reacción
    necesita DOS turnos (el entregado y la respuesta del VIP), así que se
    encolan pares; la emoción del segundo decide la señal.
    """
    emociones = emociones or ["neutral"]
    structured: list[Any] = []
    for emocion in emociones:
        structured.append(_comprension(emotion=emocion))
        structured.append(_evaluacion())
    return FakeLLM(
        structured_responses=structured,
        text_responses=["Claro, quedamos así."] * max(1, len(emociones)),
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
                message_id=9000 + len(self.methods),
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

    def fallos_tragados(self) -> list[str]:
        return [e for e in self.eventos() if e in EVENTOS_DE_FALLO]

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
                    "created_at, updated_at "
                    "from turns where chat_id = :chat order by created_at desc limit 1"
                ),
                {"chat": chat_id},
            )
        ).one_or_none()
    assert fila is not None, f"no se creó ningún turno para el chat {chat_id}"
    return dict(fila._mapping)


async def _outcome_rows(session_factory, turn_id: str) -> list[dict[str, Any]]:
    async with session_factory() as sesion:
        filas = (
            await sesion.execute(
                text(
                    "select shadow_verdict, shadow_reason, draft_score, owner_outcome, "
                    "sent_score, quality_delta, vip_signal, correction_severity "
                    "from turn_outcome_log where turn_id = :tid"
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


async def _turno_entregado(app, bot, canal, session_factory, vip_id: int) -> dict[str, Any]:
    """Mensaje VIP → cola de la dueña → aprobar → turno entregado."""
    await app.dispatcher.feed_update(
        bot, _business_update(chat_id=vip_id, from_user_id=vip_id, text=TEXTO_VIP)
    )
    turn = await _turn_row(session_factory, vip_id)
    assert turn["status"] == "pending_approval", f"el turno no quedó en cola: {turn}"
    await app.dispatcher.feed_update(
        bot, _owner_callback_update(encode_callback("approve", turn["id"]))
    )
    turn = await _turn_row(session_factory, vip_id)
    assert turn["status"] == "delivered", f"el turno no se entregó: {turn}"
    return turn


# ---------------------------------------------------------------------------
# (b1) corregir → owner_outcome = 'corrected'
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quality_enabled", "filas_esperadas", "vip_id"),
    [(True, 1, VIP_CORRIGE_ON), (False, 0, VIP_CORRIGE_OFF)],
    ids=["bandera_on", "bandera_off"],
)
async def test_corregir_guarda_owner_outcome_corrected(
    engine,
    session_factory,
    alembic_applied,
    quality_enabled: bool,
    filas_esperadas: int,
    vip_id: int,
) -> None:
    """La corrección de la dueña queda guardada como ``corrected``, con su nota.

    ON: la fila trae ``owner_outcome='corrected'``, la nota de lo ENVIADO (el
    texto corregido, no el borrador descartado) y la diferencia contra la nota
    del borrador. OFF: no hay fila — la pieza no está cableada, no es un error
    tragado.
    """
    captura = CaptureHandler()
    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    app = await _app_y_vip(
        _settings(quality_enabled=quality_enabled),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
        vip_tg_id=vip_id,
    )
    try:
        await app.dispatcher.feed_update(
            bot, _business_update(chat_id=vip_id, from_user_id=vip_id, text=TEXTO_VIP)
        )
        turn = await _turn_row(session_factory, vip_id)
        turn_id = turn["id"]

        await app.dispatcher.feed_update(
            bot, _owner_callback_update(encode_callback("correct", turn_id))
        )
        await app.dispatcher.feed_update(bot, _owner_text_update(TEXTO_CORREGIDO))

        turn = await _turn_row(session_factory, vip_id)
        assert turn["status"] == "delivered", f"la corrección no entregó: {turn}"

        filas = await _outcome_rows(session_factory, turn_id)
        assert len(filas) == filas_esperadas, (
            f"con la bandera en {quality_enabled} se esperaban {filas_esperadas} "
            f"fila(s): {filas}"
        )
        assert captura.fallos_tragados() == [], (
            f"la resolución de la dueña falló en silencio: {captura.fallos_tragados()}"
        )
        if filas_esperadas == 0:
            assert app.settings.feature_autonomy_quality_enabled is False
            return

        fila = filas[0]
        assert fila["owner_outcome"] == "corrected", (
            f"la corrección no quedó registrada como 'corrected': {fila}"
        )
        assert fila["sent_score"] is not None, (
            f"sin nota de lo enviado tras corregir: {fila}"
        )
        assert fila["quality_delta"] is not None, (
            f"sin diferencia contra la nota del borrador: {fila}"
        )
        # La severidad que viaja al libro de confianza: la corrección por texto
        # libre no muestra el selector, así que es la de siempre ('moderate').
        assert fila["correction_severity"] == "moderate", (
            f"severidad inesperada para una corrección por texto: {fila}"
        )
        assert fila["draft_score"] is not None, f"sin nota del borrador: {fila}"
    finally:
        captura.close()
        await bot.session.close()


# ---------------------------------------------------------------------------
# (b2) escalar → owner_outcome = 'escalated'
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quality_enabled", "filas_esperadas", "vip_id"),
    [(True, 1, VIP_ESCALA_ON), (False, 0, VIP_ESCALA_OFF)],
    ids=["bandera_on", "bandera_off"],
)
async def test_escalar_guarda_owner_outcome_escalated(
    engine,
    session_factory,
    alembic_applied,
    quality_enabled: bool,
    filas_esperadas: int,
    vip_id: int,
) -> None:
    """La escalación de la dueña queda guardada como ``escalated`` y sin nota.

    Escalar no envía nada, así que no hay texto del cual sacar nota: el
    contrato exige que ``sent_score`` y ``quality_delta`` queden vacíos, no
    inventados. Se mide también que la fila de sombra ya existía (el veredicto
    del sistema se conserva) para que el caso no pase por "no había nada".
    """
    captura = CaptureHandler()
    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    app = await _app_y_vip(
        _settings(quality_enabled=quality_enabled),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
        vip_tg_id=vip_id,
    )
    try:
        await app.dispatcher.feed_update(
            bot, _business_update(chat_id=vip_id, from_user_id=vip_id, text=TEXTO_VIP)
        )
        turn = await _turn_row(session_factory, vip_id)
        turn_id = turn["id"]

        antes = await _outcome_rows(session_factory, turn_id)
        assert len(antes) == filas_esperadas, (
            f"la fila de sombra no existía antes de escalar: {antes}"
        )

        await app.dispatcher.feed_update(
            bot, _owner_callback_update(encode_callback("escalate", turn_id))
        )
        turn = await _turn_row(session_factory, vip_id)
        assert turn["status"] == "escalated", (
            f"el turno no quedó escalado: {turn} (eventos: {captura.eventos()[-8:]})"
        )

        filas = await _outcome_rows(session_factory, turn_id)
        assert len(filas) == filas_esperadas, (
            f"con la bandera en {quality_enabled} se esperaban {filas_esperadas} "
            f"fila(s): {filas}"
        )
        assert captura.fallos_tragados() == [], (
            f"la escalación falló en silencio: {captura.fallos_tragados()}"
        )
        if filas_esperadas == 0:
            assert app.settings.feature_autonomy_quality_enabled is False
            return

        fila = filas[0]
        assert fila["owner_outcome"] == "escalated", (
            f"la escalación no quedó registrada: {fila}"
        )
        assert fila["sent_score"] is None, (
            f"se inventó una nota de envío en una escalación: {fila}"
        )
        assert fila["quality_delta"] is None, (
            f"se inventó una diferencia sin texto enviado: {fila}"
        )
        assert fila["shadow_verdict"] in {"send", "blocked", "escalate", "doctrine"}, (
            f"el veredicto del sistema se perdió al escalar: {fila}"
        )
    finally:
        captura.close()
        await bot.session.close()


# ---------------------------------------------------------------------------
# (c1) reacción del VIP por el mensaje siguiente (gancho inmediato)
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
async def test_reaccion_del_vip_por_el_mensaje_siguiente(
    engine, session_factory, alembic_applied
) -> None:
    """Si el VIP contesta después, su reacción queda en la fila del turno.

    Camino real: el turno se entrega, el VIP manda otro mensaje y el gancho del
    orquestador clasifica ESA respuesta (emoción del Analista + léxico fijo,
    sin modelo). Se exige que la señal sea del vocabulario y que la haya
    resuelto el turno ANTERIOR, no el nuevo.
    """
    captura = CaptureHandler()
    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    app = await _app_y_vip(
        _settings(quality_enabled=True),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        # Dos turnos: el entregado (neutro) y la respuesta del VIP (positiva).
        llm=_fake_llm(emociones=["neutral", "positiva"]),
        vip_tg_id=VIP_SENAL_HOOK,
    )
    try:
        turn = await _turno_entregado(app, bot, bot.session, session_factory, VIP_SENAL_HOOK)
        turn_id = turn["id"]

        antes = await _outcome_rows(session_factory, turn_id)
        assert len(antes) == 1, f"falta la fila del turno entregado: {antes}"
        assert antes[0]["vip_signal"] is None, (
            f"la reacción existía antes de que el VIP contestara: {antes}"
        )

        # El VIP contesta.
        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=VIP_SENAL_HOOK,
                from_user_id=VIP_SENAL_HOOK,
                text=TEXTO_REACCION,
                message_id=12,
            ),
        )

        despues = await _outcome_rows(session_factory, turn_id)
        assert len(despues) == 1, f"la reacción duplicó la fila: {despues}"
        assert despues[0]["vip_signal"] is not None, (
            "el mensaje siguiente del VIP no dejó su reacción en el turno "
            f"anterior: {despues} (eventos: {captura.eventos()[-10:]})"
        )
        assert despues[0]["vip_signal"] in {"positive", "neutral", "negative"}, (
            f"señal fuera del vocabulario: {despues}"
        )
        assert captura.fallos_tragados() == [], (
            f"la reacción falló en silencio: {captura.fallos_tragados()}"
        )
    finally:
        captura.close()
        await bot.session.close()


# ---------------------------------------------------------------------------
# (c2) reacción por el job de respaldo — el VIP se quedó callado
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
async def test_job_de_respaldo_marca_silencio_cuando_el_vip_no_contesta(
    engine, session_factory, alembic_applied
) -> None:
    """Un turno entregado sin respuesta cierra su ventana como ``silence``.

    Camino real: se corre un ciclo del job de respaldo (``run_outcome_reaction_cycle``),
    el mismo que corre dentro del bot. El ciclo usa la ventana ya vencida, así
    que la fila recién entregada queda elegible. Se exige la señal guardada y
    que un SEGUNDO ciclo sea idempotente (no vuelve a aplicar el evento).
    """
    captura = CaptureHandler()
    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    app = await _app_y_vip(
        _settings(quality_enabled=True),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
        vip_tg_id=VIP_SENAL_JOB_SILENCIO,
    )
    try:
        turn = await _turno_entregado(
            app, bot, bot.session, session_factory, VIP_SENAL_JOB_SILENCIO
        )
        turn_id = turn["id"]
        assert app.outcome_log is not None, "el ledger no quedó cableado"
        assert app.history is not None, "el historial no quedó cableado"

        # Un ciclo real del job, con la ventana ya cerrada (window_hours=0).
        informe = await run_outcome_reaction_cycle(
            outcome=app.outcome_log,
            history=app.history,
            window_hours=0,
        )
        assert informe["errors"] == 0, f"el ciclo del job falló: {informe}"
        assert informe["processed"] >= 1, (
            f"el job no tomó el turno entregado como ventana pendiente: {informe}"
        )

        filas = await _outcome_rows(session_factory, turn_id)
        assert len(filas) == 1, f"el job duplicó la fila: {filas}"
        assert filas[0]["vip_signal"] == "silence", (
            f"el VIP no contestó y el job no marcó silencio: {filas}"
        )

        # Segundo ciclo: no cambia nada (idempotente por valor de señal).
        informe2 = await run_outcome_reaction_cycle(
            outcome=app.outcome_log,
            history=app.history,
            window_hours=0,
        )
        assert informe2["errors"] == 0, f"el segundo ciclo falló: {informe2}"
        filas2 = await _outcome_rows(session_factory, turn_id)
        assert filas2[0]["vip_signal"] == "silence", (
            f"el segundo ciclo cambió la señal: {filas2}"
        )
        assert len(filas2) == 1, f"el segundo ciclo duplicó la fila: {filas2}"
        assert captura.fallos_tragados() == [], (
            f"el job falló en silencio: {captura.fallos_tragados()}"
        )
    finally:
        captura.close()
        await bot.session.close()


# ---------------------------------------------------------------------------
# (c3) reacción por el job de respaldo — respuesta que nunca pasó por el pipeline
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
async def test_job_de_respaldo_clasifica_la_respuesta_que_no_paso_por_el_pipeline(
    engine, session_factory, alembic_applied
) -> None:
    """El respaldo clasifica la respuesta aunque el gancho inmediato no la viera.

    Es el caso "el bot estuvo caído y el VIP igual contestó": la respuesta está
    en el historial del chat pero nunca entró al pipeline. El job la lee del
    historial y la clasifica por léxico (sin modelo), dentro de la ventana.
    """
    captura = CaptureHandler()
    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    app = await _app_y_vip(
        _settings(quality_enabled=True),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
        vip_tg_id=VIP_SENAL_JOB_TEXTO,
    )
    try:
        turn = await _turno_entregado(
            app, bot, bot.session, session_factory, VIP_SENAL_JOB_TEXTO
        )
        turn_id = turn["id"]

        # La respuesta del VIP quedó en el historial pero no pasó por el pipeline:
        # se siembra la fila con una marca de tiempo posterior a la entrega y
        # dentro de la ventana, y se comprueba que el job la ve donde la lee.
        ancla = turn["updated_at"] or turn["created_at"]
        async with session_factory() as sesion:
            await sesion.execute(
                text(
                    "insert into message_history "
                    "(chat_id, role, text, timestamp, telegram_message_id) "
                    "values (:chat, 'vip', :texto, now(), 777)"
                ),
                {"chat": VIP_SENAL_JOB_TEXTO, "texto": TEXTO_REACCION},
            )
            await sesion.commit()

        visibles = await app.history.get_recent(VIP_SENAL_JOB_TEXTO, limit=50)
        sembrada = [
            r
            for r in visibles
            if isinstance(r, dict) and r.get("text") == TEXTO_REACCION
        ]
        assert sembrada, (
            "la respuesta sembrada no quedó visible para el job en el historial: "
            f"{visibles[:3]}"
        )
        # El historial entrega la marca como texto ISO (`rows_to_recent_messages`),
        # no como `datetime`: exigir un `datetime` era el defecto que dejaba esta
        # rama inalcanzable (el job descartaba todas las filas y cerraba 'silence').
        marca = sembrada[0].get("timestamp")
        assert isinstance(marca, str), f"marca de tiempo inservible: {marca!r}"
        marca_dt = datetime.fromisoformat(marca)
        assert marca_dt > ancla, (
            f"la respuesta sembrada quedó ANTES de la entrega: {marca_dt} <= {ancla}"
        )

        informe = await run_outcome_reaction_cycle(
            outcome=app.outcome_log,
            history=app.history,
            window_hours=0,
        )
        assert informe["errors"] == 0, f"el ciclo del job falló: {informe}"
        assert informe["reactions"] >= 1, (
            "el job no clasificó la respuesta que estaba en el historial: "
            f"{informe}"
        )

        filas = await _outcome_rows(session_factory, turn_id)
        assert len(filas) == 1, f"el job duplicó la fila: {filas}"
        assert filas[0]["vip_signal"] == "positive", (
            "la respuesta positiva del VIP no se clasificó como tal: "
            f"{filas} (texto sembrado: {TEXTO_REACCION!r})"
        )
        assert captura.fallos_tragados() == [], (
            f"el job falló en silencio: {captura.fallos_tragados()}"
        )
    finally:
        captura.close()
        await bot.session.close()
