"""C-SHADOW-01 — el modo sombra deja registro real por cada turno VIP.

Prueba E2: entra por el camino real de un turno VIP (mensaje de negocio por el
``dispatcher`` armado por ``build_app``) y por la acción real de la dueña
(aprobar por botón), y verifica el efecto en Postgres real. Nunca se aserta
"se llamó a X": se asertan filas. El único simulado es el modelo de lenguaje
externo (``llm/fake.py``); el resto del sistema es el de producción.

Promesa bajo prueba (``audit/contracts/C-SHADOW-01.md``):
  (a) un turno VIP entregado deja fila en ``turn_outcome_log`` con
      ``shadow_verdict`` y ``draft_score``;
  (b) tras aprobar, ``owner_outcome`` queda guardado y un guardado posterior
      del MISMO turno no lo borra (regresión del commit 3ade3b3);
  (c) con la bandera apagada no hay fila (por diseño);
  (d) las rutas que no pasan por el pipeline (escalación por palabra clave y
      saludo de plantilla) no escriben fila, y es por diseño, no por un error
      tragado.

Matriz de bandera (``feature_autonomy_quality_enabled``):
  ON  → todo el círculo de aprendizaje escribe (filas (a), (b) y (d) descritas).
  OFF → el orquestador recibe ``outcome_log=None``: ninguna fila, y es el
        comportamiento anterior byte a byte.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from pydantic import SecretStr
from sqlalchemy import text

from diana.application.ports import TurnOutcomeLogRecord
from diana.behavior.fake import FixedDelayPolicy
from diana.cognitive.models import Comprehension, EvaluationProfile
from diana.composition import build_app
from diana.config.settings import Settings
from diana.llm.fake import FakeLLM
from diana.telegram.keyboards import encode_callback

OWNER_ID = 999001
BOT_ID = 999002
TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"

# Fuera de los rangos reales; un id por escenario (la prueba falla si el VIP
# ya existe, así que cada escenario necesita el suyo).
VIP_A = 999000801  # (a) entrega supervisada con la bandera encendida
VIP_C = 999000811  # (c) contraprueba de bandera apagada
VIP_B = 999000841  # (b) resolución de la dueña y re-guardado
VIP_D_PALABRA = 999000821  # (d) escalación por palabra clave
VIP_D_SALUDO = 999000831  # (d) saludo de plantilla

# El texto del VIP: con sustancia, para que NO lo corte el atajo de saludo.
TEXTO_CON_SUSTANCIA = (
    "Hola Diana, estuve pensando en lo que hablamos el otro día y quería "
    "retomar el tema para ver cómo seguimos."
)
# J.4 pago_precio: escalación determinística, sin Director ni LLM.
TEXTO_PALABRA_CLAVE = "¿Cuánto cuesta el plan completo?"
# Saludo puro: corte de plantilla tras el Analista.
TEXTO_SALUDO = "Hola"

# Eventos que delatarían un fallo tragado en el círculo de aprendizaje.
EVENTOS_DE_FALLO = frozenset(
    {
        "outcome_log_error",
        "outcome_record_shadow_failed",
        "outcome_record_owner_failed",
    }
)


# ---------------------------------------------------------------------------
# Configuración: solo la bandera bajo prueba cambia; todo lo demás apagado para
# que el hueco (si lo hay) no se pueda atribuir a otra pieza.
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


def _fake_llm(
    *,
    intent: str = "chat",
    risk: str = "bajo",
    safety: float = 0.95,
) -> FakeLLM:
    """Solo el modelo externo es falso; el resto del sistema es el real."""
    return FakeLLM(
        structured_responses=[
            Comprehension(
                intent=intent,
                topics=["general"],
                emotion="neutral",
                urgency="baja",
                risk=risk,
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
                safety=safety,
                coverage=0.9,
                empathy=0.9,
            ),
        ],
        text_responses=["Claro, seguimos con lo que hablamos."],
    )


class SpyBotSession:
    """Doble de la salida a Telegram: ningún mensaje sale de la máquina.

    Los métodos de envío devuelven un ``Message`` de verdad (con ``message_id``)
    porque el código real lee ese identificador para poder editar el mensaje
    después; devolver ``None`` rompería el flujo por una razón que no es la que
    se está probando.
    """

    def __init__(self) -> None:
        self.methods: list[str] = []
        self.sent_texts: list[str] = []

    async def __call__(self, bot: Any, method: Any, timeout: Any = None) -> Any:
        name = type(method).__name__
        self.methods.append(name)
        if name.startswith("Send"):
            texto = getattr(method, "text", None) or getattr(method, "caption", None)
            if texto:
                self.sent_texts.append(str(texto))
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
    """Captura los eventos del módulo de aplicación.

    En pytest el nivel efectivo hereda de la raíz (WARNING) y los INFO se
    descartarían antes de llegar aquí; se fija el nivel a propósito.
    """

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
    *,
    chat_id: int,
    from_user_id: int,
    text: str,
    message_id: int = 11,
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


def _owner_callback_update(data: str) -> Update:
    """Callback real de la dueña sobre el DM del borrador."""
    dm = Message(
        message_id=900,
        date=datetime(2026, 10, 8, 12, 0, 0),
        chat=Chat(id=OWNER_ID, type="private"),
        from_user=User(id=BOT_ID, is_bot=True, first_name="Diana"),
        text="Borrador",
    )
    return Update(
        update_id=901,
        callback_query=CallbackQuery(
            id="cb-1",
            from_user=User(id=OWNER_ID, is_bot=False, first_name="Duenia"),
            chat_instance="1",
            data=data,
            message=dm,
        ),
    )


# ---------------------------------------------------------------------------
# Lecturas sobre filas reales
# ---------------------------------------------------------------------------
async def _turn_row(session_factory, chat_id: int) -> dict[str, Any]:
    async with session_factory() as sesion:
        fila = (
            await sesion.execute(
                text(
                    "select id::text as id, status, vip_id::text as vip_id, "
                    "channel_type "
                    "from turns where chat_id = :chat "
                    "order by created_at desc limit 1"
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
                    "select shadow_verdict, shadow_reason, draft_score, "
                    "owner_outcome, sent_score, quality_delta, blocked_dims, "
                    "vip_signal, correction_severity "
                    "from turn_outcome_log where turn_id = :tid"
                ),
                {"tid": turn_id},
            )
        ).all()
    return [dict(f._mapping) for f in filas]


async def _trace_row(session_factory, turn_id: str) -> dict[str, Any]:
    async with session_factory() as sesion:
        fila = (
            await sesion.execute(
                text(
                    "select evaluation, comprehension, generated_text, decision "
                    "from pipeline_traces where turn_id = :tid"
                ),
                {"tid": turn_id},
            )
        ).one_or_none()
    return dict(fila._mapping) if fila is not None else {}


async def _assert_vip_nuevo(session_factory, vip_tg_id: int) -> None:
    """El VIP de la prueba no debe existir antes de la prueba."""
    async with session_factory() as sesion:
        previo = await sesion.execute(
            text("select count(*) from vips where telegram_user_id = :uid"),
            {"uid": vip_tg_id},
        )
        assert previo.scalar_one() == 0, (
            f"el VIP {vip_tg_id} ya existe en la base; elegir otro id de prueba"
        )


async def _app_y_vip(settings: Settings, *, engine, session_factory, bot, llm, vip_tg_id):
    """Arma el contenedor real y da de alta al VIP de la prueba."""
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
# (a) + (c) — la bandera enciende y apaga la fila, con su efecto medido
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quality_enabled", "filas_esperadas"),
    [(True, 1), (False, 0)],
    ids=["bandera_on", "bandera_off"],
)
async def test_a_turno_vip_entregado_deja_fila_con_veredicto_y_nota(
    engine,
    session_factory,
    alembic_applied,
    quality_enabled: bool,
    filas_esperadas: int,
) -> None:
    """(a) ON: el turno entregado deja la fila con veredicto y nota reales.

    (c) OFF: no deja ninguna fila — el efecto de la bandera se mide en los dos
    estados, no se supone.
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
        vip_tg_id=VIP_A if quality_enabled else VIP_C,
    )
    chat_id = VIP_A if quality_enabled else VIP_C
    try:
        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=chat_id,
                from_user_id=chat_id,
                text=TEXTO_CON_SUSTANCIA,
            ),
        )

        turn = await _turn_row(session_factory, chat_id)
        assert turn["status"] == "pending_approval", (
            f"el turno no quedó esperando aprobación: {turn}"
        )
        assert turn["vip_id"] is not None, f"el turno quedó sin VIP: {turn}"

        # La dueña aprueba: el turno se entrega de verdad.
        await app.dispatcher.feed_update(
            bot, _owner_callback_update(encode_callback("approve", turn["id"]))
        )
        turn = await _turn_row(session_factory, chat_id)
        assert turn["status"] == "delivered", f"el turno no se entregó: {turn}"

        filas = await _outcome_rows(session_factory, turn["id"])
        assert len(filas) == filas_esperadas, (
            f"con la bandera en {quality_enabled} se esperaban "
            f"{filas_esperadas} fila(s): {filas}"
        )
        assert captura.fallos_tragados() == [], (
            "el círculo de aprendizaje falló en silencio: "
            f"{captura.fallos_tragados()}"
        )

        if filas_esperadas == 0:
            # Apagado a propósito: la pieza no está cableada, y eso se ve en el
            # contenedor (no es una excepción tragada).
            assert app.settings.feature_autonomy_quality_enabled is False
            return

        fila = filas[0]
        # El veredicto es del vocabulario real, no un relleno.
        assert fila["shadow_verdict"] in {"send", "blocked", "escalate", "doctrine"}, (
            f"veredicto fuera del vocabulario: {fila}"
        )
        assert fila["shadow_reason"], f"sin motivo de la decisión sombra: {fila}"
        # La nota del borrador es un número real, en rango, no None ni 0.0.
        nota = fila["draft_score"]
        assert nota is not None, f"sin nota del borrador: {fila}"
        assert 0.0 < float(nota) <= 1.0, f"nota fuera de rango: {nota}"
    finally:
        captura.close()
        await bot.session.close()


# ---------------------------------------------------------------------------
# (b) — la resolución de la dueña sobrevive al re-guardado del turno
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
async def test_b_lo_que_decide_la_duena_sobrevive_al_reguardado_del_turno(
    engine, session_factory, alembic_applied
) -> None:
    """(b) Tras aprobar, ``owner_outcome`` queda y NO lo borra un guardado nuevo.

    Regresión del commit 3ade3b3: el ``finally`` posterior a la aprobación
    volvía a llamar el guardado del turno y el ``INSERT … ON CONFLICT`` pisaba
    con NULL lo que la dueña ya había decidido.
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
        vip_tg_id=VIP_B,
    )
    try:
        await app.dispatcher.feed_update(
            bot,
            _business_update(chat_id=VIP_B, from_user_id=VIP_B, text=TEXTO_CON_SUSTANCIA),
        )
        turn = await _turn_row(session_factory, VIP_B)
        turn_id = turn["id"]

        # Antes de la dueña: fila de sombra sin resolución.
        antes = await _outcome_rows(session_factory, turn_id)
        assert len(antes) == 1, f"la fila de sombra no existía antes: {antes}"
        assert antes[0]["owner_outcome"] is None, (
            f"la resolución de la dueña existía antes de que ella decidiera: {antes}"
        )
        veredicto_original = antes[0]["shadow_verdict"]

        await app.dispatcher.feed_update(
            bot, _owner_callback_update(encode_callback("approve", turn_id))
        )
        turn = await _turn_row(session_factory, VIP_B)
        assert turn["status"] == "delivered"

        tras_aprobar = await _outcome_rows(session_factory, turn_id)
        assert len(tras_aprobar) == 1, f"la aprobación duplicó la fila: {tras_aprobar}"
        assert tras_aprobar[0]["owner_outcome"] == "approved_as_is", (
            f"la decisión de la dueña no quedó guardada: {tras_aprobar}"
        )
        assert tras_aprobar[0]["sent_score"] is not None, (
            f"sin nota de lo enviado: {tras_aprobar}"
        )

        # 1) El camino real: el `finally` posterior a la entrega vuelve a
        #    llamar el guardado del turno (es lo que hacía el defecto).
        await app.orchestrator._maybe_post_turn(turn["id"], VIP_B)  # noqa: SLF001
        re_hook = await _outcome_rows(session_factory, turn_id)
        assert len(re_hook) == 1, f"el re-guardado duplicó la fila: {re_hook}"
        assert re_hook[0]["owner_outcome"] == "approved_as_is", (
            f"el re-guardado borró la decisión de la dueña: {re_hook}"
        )
        assert re_hook[0]["sent_score"] == tras_aprobar[0]["sent_score"], (
            f"el re-guardado pisó la nota de lo enviado: {re_hook}"
        )
        assert re_hook[0]["shadow_verdict"] == veredicto_original, (
            f"el re-guardado cambió el veredicto original: {re_hook}"
        )

        # 2) El guardado crudo que hacía el defecto: mismo turno, columnas de la
        #    dueña en blanco. Un `INSERT … ON CONFLICT` sin la corrección las
        #    pisa con NULL. Se usa el repositorio REAL del contenedor.
        repo = app.turn_outcome_repo
        assert repo is not None, "el ledger no quedó cableado con la bandera ON"
        await repo.insert(
            TurnOutcomeLogRecord(
                turn_id=UUID(turn_id),
                vip_id=UUID(turn["vip_id"]),
                shadow_verdict=veredicto_original,
                shadow_reason="re-guardado de prueba",
                owner_outcome=None,
                draft_score=None,
                sent_score=None,
            )
        )
        tras_reguardado_crudo = await _outcome_rows(session_factory, turn_id)
        assert len(tras_reguardado_crudo) == 1, (
            f"el re-guardado crudo duplicó la fila: {tras_reguardado_crudo}"
        )
        assert tras_reguardado_crudo[0]["owner_outcome"] == "approved_as_is", (
            "el re-guardado crudo borró la decisión de la dueña: "
            f"{tras_reguardado_crudo}"
        )
        assert tras_reguardado_crudo[0]["sent_score"] == tras_aprobar[0]["sent_score"], (
            f"el re-guardado crudo pisó la nota de lo enviado: {tras_reguardado_crudo}"
        )
        assert captura.fallos_tragados() == [], (
            f"hubo un fallo tragado en el camino: {captura.fallos_tragados()}"
        )
    finally:
        captura.close()
        await bot.session.close()


# ---------------------------------------------------------------------------
# (d) — rutas que NO pasan por el pipeline: el hueco es diseño, no fallo
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
async def test_d_escalacion_por_palabra_clave_no_escribe_fila_por_diseno(
    engine, session_factory, alembic_applied
) -> None:
    """(d) La escalación determinística no escribe fila, y se ve POR QUÉ.

    No basta con que no haya fila: hay que demostrar que el turno nunca entró al
    pipeline cognitivo (no hay traza) y que no hubo ningún error tragado. Si no,
    "no hay fila" sería indistinguible de "algo se rompió en silencio".
    """
    captura = CaptureHandler()
    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    llm = _fake_llm()
    app = await _app_y_vip(
        _settings(quality_enabled=True),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=llm,
        vip_tg_id=VIP_D_PALABRA,
    )
    try:
        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=VIP_D_PALABRA,
                from_user_id=VIP_D_PALABRA,
                text=TEXTO_PALABRA_CLAVE,
            ),
        )

        turn = await _turn_row(session_factory, VIP_D_PALABRA)
        assert turn["status"] == "escalated", f"no escaló: {turn}"

        # El turno existe y escaló, pero SIN pasar por el pipeline cognitivo.
        traza = await _trace_row(session_factory, turn["id"])
        assert traza == {}, (
            f"el turno determinístico escribió traza: es otra ruta, no esta: {traza}"
        )
        assert llm.calls == [], (
            f"la escalación determinística llamó al modelo: {llm.calls}"
        )

        # La escalación quedó registrada por su vía (no se perdió).
        async with session_factory() as sesion:
            esc = (
                await sesion.execute(
                    text(
                        "select tipo, motivo from escalation_events "
                        "where turn_id = :tid"
                    ),
                    {"tid": turn["id"]},
                )
            ).all()
        assert esc, "la escalación no quedó registrada en escalation_events"
        assert esc[0].tipo == "pago_precio", f"tipo inesperado: {esc[0].tipo}"

        filas = await _outcome_rows(session_factory, turn["id"])
        assert filas == [], (
            f"la ruta determinística no debe escribir fila de resultado: {filas}"
        )
        assert captura.fallos_tragados() == [], (
            f"no hay fila, pero además hubo un fallo tragado: "
            f"{captura.fallos_tragados()}"
        )
    finally:
        captura.close()
        await bot.session.close()


@pytest.mark.db
@pytest.mark.asyncio
async def test_d_saludo_de_plantilla_no_escribe_fila_por_diseno(
    engine, session_factory, alembic_applied
) -> None:
    """(d) El saludo cortado por plantilla no escribe fila, y se ve POR QUÉ.

    El corte ocurre tras el Analista: la traza guarda la comprensión pero NO una
    evaluación. Sin evaluación no hay con qué comparar el borrador, así que el
    modo sombra no inventa un veredicto — se queda sin fila a propósito.
    """
    captura = CaptureHandler()
    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    app = await _app_y_vip(
        _settings(quality_enabled=True),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(intent="saludar"),
        vip_tg_id=VIP_D_SALUDO,
    )
    try:
        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=VIP_D_SALUDO,
                from_user_id=VIP_D_SALUDO,
                text=TEXTO_SALUDO,
            ),
        )

        turn = await _turn_row(session_factory, VIP_D_SALUDO)
        assert turn["status"] == "pending_approval", (
            f"el saludo no llegó a la cola de la dueña: {turn}"
        )

        traza = await _trace_row(session_factory, turn["id"])
        assert traza, "el saludo no dejó traza: entonces es otra ruta, no esta"
        assert traza.get("comprehension") is not None, (
            f"el Analista no dejó su comprensión: {traza}"
        )
        assert traza.get("evaluation") is None, (
            "el corte de saludo evaluó el borrador: la ausencia de fila ya no "
            f"sería por diseño: {traza.get('evaluation')}"
        )
        decision = traza.get("decision") or {}
        assert decision.get("reason") == "plantilla_saludo", (
            f"no fue el corte de saludo: {decision}"
        )

        filas = await _outcome_rows(session_factory, turn["id"])
        assert filas == [], (
            f"el saludo de plantilla no debe escribir fila de resultado: {filas}"
        )
        assert captura.fallos_tragados() == [], (
            f"no hay fila, pero además hubo un fallo tragado: "
            f"{captura.fallos_tragados()}"
        )
    finally:
        captura.close()
        await bot.session.close()
