"""C-AUT-01 — el envío autónomo entrega de verdad, y solo con las dos puertas abiertas.

Prueba E2: entra por ``build_app`` (contenedor real) con el mensaje de negocio
recorriendo el ``dispatcher`` real (middlewares incluidos) hasta el orquestador,
y asierta el efecto en Postgres real y en la salida real del actuador. Nunca se
asienta "se llamó a X": se asientan filas (``turns.status``,
``pending_approvals``) y los textos realmente enviados. Lo único simulado es el
modelo de lenguaje externo (``llm/fake.py``) y la frontera con Telegram (la
sesión del ``Bot``), que es el mismo doble que usa el resto de la auditoría.

Doble puerta del envío autónomo (``audit/contracts/C-AUT-01.md``):
  L1 = ``FEATURE_AUTONOMOUS_MODE`` (interruptor maestro, ``Settings``).
  L2 = ``vips.auto_send`` del VIP, o ``GLOBAL_MODE=autonomous``.

Cara positiva: L1 ON + L2 ON + Decisor ``send`` → el mensaje SALE al VIP, el
turno queda ``DELIVERED`` y NO hay fila en ``pending_approvals``.

Cara negativa (fail-closed): con cualquiera de las dos puertas cerrada no sale
nada y el borrador cae en la cola de la dueña.

Escenarios cubiertos (uno por prueba, cada uno con su aserción):
  S0  matriz L1 × L2 → entregado o pendiente de aprobación.
  S1  L1 OFF (aunque L2 ON) → ``PENDING_APPROVAL`` y cero envíos.
  S2  L1 ON y L2 OFF (VIP sin ``auto_send``) → ``PENDING_APPROVAL``, cero envíos.
  S3  L1 ON + L2 ON pero VIP congelado → el mensaje ni siquiera entra al motor.
  S4  L1 ON + L2 ON pero VIP pausado → la pausa se aplica en la entrada;
      hallazgo H-AUT1-2: la ventana de pausa a mitad del turno NO se rechequea
      (marcado ``xfail``: la promesa de fail-closed no se cumple ahí).
  S5  canal de Atención (``vip_id=None``) con L1 ON y ``GLOBAL_MODE=autonomous``
      → nunca autónomo, siempre supervisado.
  S6  L1 ON + L2 ON pero el BehaviorEngine no cableado → turno ``FAILED`` y el
      borrador NO cae en la cola (hallazgo del contrato, se fija con evidencia).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram import Bot
from aiogram.types import Chat, Message, Update, User
from pydantic import SecretStr
from sqlalchemy import text

from diana.behavior.fake import FixedDelayPolicy
from diana.cognitive.models import Comprehension, EvaluationProfile
from diana.composition import build_app
from diana.config.settings import Settings
from diana.llm.fake import FakeLLM

OWNER_ID = 999001
BOT_ID = 999002
TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"

# Fuera de los rangos reales. Un id por escenario: la prueba falla si el VIP ya
# existe, así que cada escenario necesita el suyo.
VIP_S0_SUPERVISED = 999000901  # S0: L2 por VIP (auto_send) con L1 ON
VIP_S0_GLOBAL = 999000902  # S0: L2 global (GLOBAL_MODE=autonomous)
VIP_S1_L1_OFF = 999000911  # S1: L1 OFF con L2 ON
VIP_S1_GLOBAL_L1_OFF = 999000912  # S1: L1 OFF con GLOBAL_MODE=autonomous
VIP_S2_L2_OFF = 999000921  # S2: L1 ON y auto_send OFF
VIP_S3_FROZEN = 999000931  # S3: VIP congelado
VIP_S4_PAUSED = 999000941  # S4: VIP pausado en la entrada
VIP_S4B_WINDOW = 999000942  # S4b: pausa inyectada a mitad del turno
VIP_S6_NO_BEHAVIOR = 999000961  # S6: BehaviorEngine no cableado
CHAT_ATENCION = 999000951  # S5: chat no-VIP (canal de Atención)

TEXTO_CON_SUSTANCIA = (
    "Hola Diana, estuve pensando en lo que hablamos el otro día y quería "
    "retomar el tema para ver cómo seguimos."
)
BORRADOR = "Claro, seguimos con lo que hablamos."

CLAVE_TRAINING_MODE = "training_mode_enabled"


# ---------------------------------------------------------------------------
# Configuración: solo L1 y GLOBAL_MODE cambian; todo lo demás apagado para que
# el efecto medido no se pueda atribuir a otra pieza.
# ---------------------------------------------------------------------------
def _settings(*, l1: bool, global_mode: str = "supervised") -> Settings:
    return Settings.model_construct(
        telegram_bot_token=SecretStr(TOKEN),
        owner_telegram_id=OWNER_ID,
        database_url=SecretStr(
            "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder"
        ),
        deepseek_api_key="",
        global_mode=global_mode,
        feature_autonomous_mode=l1,
        feature_memory_enabled=False,
        feature_staging_enabled=False,
        feature_quality_feedback_enabled=False,
        feature_gray_zone_enabled=False,
        feature_sandbox_enabled=False,
        feature_advanced_behavior=False,
        feature_autonomy_readiness_enabled=False,
        feature_autonomy_quality_enabled=False,
        feature_general_mode_enabled=False,
        log_level="INFO",
    )


def _fake_llm(
    *,
    intent: str = "chat",
    risk: str = "bajo",
    safety: float = 0.95,
) -> FakeLLM:
    """Solo el modelo externo es falso; el resto del sistema es el real.

    Con ``safety=0.95`` / ``doctrine=0.9`` / ``naturalness=0.9`` el Decisor
    cruza los umbrales autónomos (0.9 / 0.8 / 0.7) y emite ``send`` cuando L1
    está encendida.
    """
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
        text_responses=[BORRADOR],
    )


class _PausaAMitadDelTurnoLLM(FakeLLM):
    """FakeLLM que, en la primera llamada del pipeline, pausa al VIP.

    Simula el único evento externo que puede abrir la ventana: la dueña pausa
    al VIP después de que su mensaje ya pasó los middlewares (la pausa es una
    acción del menú, en paralelo al turno en curso). El resto del modelo sigue
    siendo el doble determinista: no se agrega ninguna pieza de producción.
    """

    def __init__(self, *, al_pausar: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._al_pausar = al_pausar
        self._ya_pauso = False

    async def generate_structured(self, messages, schema, **kwargs):  # type: ignore[override]
        if not self._ya_pauso:
            self._ya_pauso = True
            await self._al_pausar()
        return await super().generate_structured(messages, schema, **kwargs)


class SpyBotSession:
    """Doble de la salida a Telegram: ningún mensaje sale de la máquina.

    Registra ``(chat_id, texto)`` de cada envío real del actuador, que es lo
    que permite asertar "salió o no salió" sin mirar llamadas a métodos.
    """

    def __init__(self) -> None:
        self.methods: list[str] = []
        self.envios: list[dict[str, Any]] = []

    async def __call__(self, bot: Any, method: Any, timeout: Any = None) -> Any:
        name = type(method).__name__
        self.methods.append(name)
        texto = getattr(method, "text", None) or getattr(method, "caption", None)
        chat_id = getattr(method, "chat_id", None)
        if name.startswith("Send") and texto is not None:
            self.envios.append({"metodo": name, "chat_id": chat_id, "texto": str(texto)})
        if name.startswith("Send"):
            return Message(
                message_id=1000 + len(self.methods),
                date=datetime(2026, 10, 9, 12, 0, 0),
                chat=Chat(id=chat_id or 0, type="private"),
                text=str(texto) if texto else None,
            )
        return None

    def textos_a(self, chat_id: int) -> list[str]:
        return [e["texto"] for e in self.envios if e["chat_id"] == chat_id]

    async def close(self) -> None:
        return None


class CaptureHandler(logging.Handler):
    """Captura los eventos de los módulos de aplicación y de Telegram.

    En pytest el nivel efectivo hereda de la raíz (WARNING); se fija INFO a
    propósito para poder distinguir "no salió por diseño" de "salió un error".
    """

    LOGGERS = ("diana.application", "diana.telegram")

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
    *,
    chat_id: int,
    from_user_id: int,
    text: str,
    message_id: int = 11,
) -> Update:
    msg = Message(
        message_id=message_id,
        date=datetime(2026, 10, 9, 12, 0, 0),
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=from_user_id, is_bot=False, first_name="Vip"),
        text=text,
        business_connection_id=f"bc-audit-{chat_id}",
    )
    return Update(update_id=message_id, business_message=msg)


# ---------------------------------------------------------------------------
# Lecturas sobre filas reales
# ---------------------------------------------------------------------------
async def _turn_row(session_factory, chat_id: int) -> dict[str, Any] | None:
    async with session_factory() as sesion:
        fila = (
            await sesion.execute(
                text(
                    "select id::text as id, status, vip_id::text as vip_id, "
                    "channel_type, error "
                    "from turns where chat_id = :chat "
                    "order by created_at desc limit 1"
                ),
                {"chat": chat_id},
            )
        ).one_or_none()
    return None if fila is None else dict(fila._mapping)


async def _approval_rows(session_factory, chat_id: int) -> list[dict[str, Any]]:
    async with session_factory() as sesion:
        filas = (
            await sesion.execute(
                text(
                    "select id::text as id, turn_id::text as turn_id, status, "
                    "vip_id::text as vip_id, draft_text, cognitive_summary "
                    "from pending_approvals where chat_id = :chat "
                    "order by created_at desc"
                ),
                {"chat": chat_id},
            )
        ).all()
    return [dict(f._mapping) for f in filas]


async def _turn_count(session_factory, chat_id: int) -> int:
    async with session_factory() as sesion:
        return int(
            (
                await sesion.execute(
                    text("select count(*) from turns where chat_id = :chat"),
                    {"chat": chat_id},
                )
            ).scalar_one()
        )


async def _trace_decision(session_factory, turn_id: str) -> dict[str, Any]:
    async with session_factory() as sesion:
        fila = (
            await sesion.execute(
                text(
                    "select decision, generated_text from pipeline_traces "
                    "where turn_id = :tid"
                ),
                {"tid": turn_id},
            )
        ).one_or_none()
    if fila is None:
        return {}
    datos = dict(fila._mapping)
    return datos.get("decision") or {}


async def _historial_dueno(session_factory, chat_id: int) -> list[str]:
    """Filas de historial con rol dueña/bot escritas por la entrega autónoma."""
    async with session_factory() as sesion:
        filas = (
            await sesion.execute(
                text(
                    "select role, text from message_history "
                    "where chat_id = :chat and role in ('owner', 'bot') "
                    "order by timestamp desc"
                ),
                {"chat": chat_id},
            )
        ).all()
    return [f.text for f in filas]


# ---------------------------------------------------------------------------
# Alta del VIP y limpieza (la base es la copia de la real: siempre acotar)
# ---------------------------------------------------------------------------
async def _assert_vip_nuevo(session_factory, vip_tg_id: int) -> None:
    async with session_factory() as sesion:
        previo = await sesion.execute(
            text("select count(*) from vips where telegram_user_id = :uid"),
            {"uid": vip_tg_id},
        )
        assert previo.scalar_one() == 0, (
            f"el VIP {vip_tg_id} ya existe en la base; elegir otro id de prueba"
        )


async def _limpiar(session_factory, *, chat_id: int, vip_tg_id: int | None = None) -> None:
    """Borra solo las filas de esta prueba (por chat y por telegram_user_id)."""
    async with session_factory() as sesion:
        sub = "(select id from turns where chat_id = :chat)"
        for sql in (
            f"delete from turn_outcome_log where turn_id in {sub}",
            f"delete from escalation_events where turn_id in {sub}",
            f"delete from pipeline_traces where turn_id in {sub}",
            f"delete from pending_deliveries where turn_id in {sub}",
            "delete from pending_approvals where chat_id = :chat",
            "delete from turns where chat_id = :chat",
            "delete from message_history where chat_id = :chat",
            "delete from daily_message_limits where chat_id = :chat",
        ):
            await sesion.execute(text(sql), {"chat": chat_id})
        if vip_tg_id is not None:
            await sesion.execute(
                text("delete from vips where telegram_user_id = :uid"),
                {"uid": vip_tg_id},
            )
        await sesion.commit()


async def _app(
    *,
    settings: Settings,
    engine,
    session_factory,
    bot,
    llm,
):
    return build_app(
        settings,
        bot=bot,
        llm=llm,
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )


def _bot_con_spy() -> tuple[Bot, SpyBotSession]:
    bot = Bot(token=TOKEN)
    spy = SpyBotSession()
    bot.session = spy  # type: ignore[assignment]
    return bot, spy


async def _set_training_mode(session_factory, enabled: bool) -> None:
    async with session_factory() as sesion:
        await sesion.execute(
            text(
                "insert into system_config (key, value, updated_at) "
                "values (:k, cast(:v as jsonb), now()) "
                "on conflict (key) do update set value = excluded.value, "
                "updated_at = now()"
            ),
            {"k": CLAVE_TRAINING_MODE, "v": json.dumps(enabled)},
        )
        await sesion.commit()


async def _leer_training_mode(session_factory) -> Any:
    async with session_factory() as sesion:
        valor = (
            await sesion.execute(
                text("select value from system_config where key = :k"),
                {"k": CLAVE_TRAINING_MODE},
            )
        ).scalar_one_or_none()
    return valor


async def _restaurar_training_mode(session_factory, previo: Any) -> None:
    async with session_factory() as sesion:
        if previo is None:
            await sesion.execute(
                text("delete from system_config where key = :k"),
                {"k": CLAVE_TRAINING_MODE},
            )
        else:
            await sesion.execute(
                text(
                    "update system_config set value = cast(:v as jsonb), "
                    "updated_at = now() where key = :k"
                ),
                {"k": CLAVE_TRAINING_MODE, "v": json.dumps(previo)},
            )
        await sesion.commit()


# ===========================================================================
# S0 — la doble puerta abierta: el mensaje SALE y no hay cola de aprobación
# ===========================================================================
@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("l2_por_vip", "global_mode", "chat_id"),
    [
        (True, "supervised", VIP_S0_SUPERVISED),
        (False, "autonomous", VIP_S0_GLOBAL),
    ],
    ids=["l2_vip_auto_send", "l2_global_mode"],
)
async def test_s0_doble_puerta_abierta_entrega_sin_cola(
    engine,
    session_factory,
    alembic_applied,
    l2_por_vip: bool,
    global_mode: str,
    chat_id: int,
) -> None:
    """L1 ON + L2 ON (por VIP o global) → DELIVERED, salida real y 0 aprobaciones."""
    captura = CaptureHandler()
    bot, spy = _bot_con_spy()
    app = await _app(
        settings=_settings(l1=True, global_mode=global_mode),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
    )
    try:
        await _assert_vip_nuevo(session_factory, chat_id)
        rec = await app.vips.add(chat_id, display_name="Prueba E2")
        if l2_por_vip:
            assert await app.vips.set_auto_send(rec.id, True) is True

        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=chat_id, from_user_id=chat_id, text=TEXTO_CON_SUSTANCIA
            ),
        )

        turn = await _turn_row(session_factory, chat_id)
        assert turn is not None, "no se creó ningún turno para el chat de prueba"
        assert turn["status"] == "delivered", (
            f"el envío autónomo no entregó: {turn}"
        )
        assert turn["vip_id"] is not None, f"el turno quedó sin VIP: {turn}"

        # Salida real del actuador, con el texto real del borrador.
        envios = spy.textos_a(chat_id)
        assert envios == [BORRADOR], (
            f"no salió exactamente el borrador del modelo: {envios}"
        )

        # Y NO hay fila en la cola de la dueña.
        assert await _approval_rows(session_factory, chat_id) == [], (
            "el envío autónomo dejó un borrador en la cola de aprobación"
        )

        decision = await _trace_decision(session_factory, turn["id"])
        assert decision.get("action") == "send", f"el Decisor no envió: {decision}"
        assert decision.get("reason") == "autonomous_ok", (
            f"motivo inesperado de la decisión: {decision}"
        )

        # El historial de salida se guarda (efecto persistido no trivial).
        historial = await _historial_dueno(session_factory, chat_id)
        assert BORRADOR in historial, (
            f"la entrega autónoma no dejó el borrador en el historial: {historial}"
        )
    finally:
        captura.close()
        await _limpiar(session_factory, chat_id=chat_id, vip_tg_id=chat_id)
        await bot.session.close()


# ===========================================================================
# S1 — L1 OFF: nada sale, aunque L2 esté abierto
# ===========================================================================
@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("global_mode", "auto_send", "chat_id"),
    [
        ("supervised", True, VIP_S1_L1_OFF),
        ("autonomous", True, VIP_S1_GLOBAL_L1_OFF),
    ],
    ids=["l2_por_vip", "l2_global"],
)
async def test_s1_l1_apagado_nada_sale_y_cae_en_la_cola(
    engine,
    session_factory,
    alembic_applied,
    global_mode: str,
    auto_send: bool,
    chat_id: int,
) -> None:
    """L1 OFF (aunque L2 ON) → PENDING_APPROVAL, 0 salidas y borrador en la cola."""
    captura = CaptureHandler()
    bot, spy = _bot_con_spy()
    app = await _app(
        settings=_settings(l1=False, global_mode=global_mode),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
    )
    try:
        await _assert_vip_nuevo(session_factory, chat_id)
        rec = await app.vips.add(chat_id, display_name="Prueba E2")
        if auto_send:
            assert await app.vips.set_auto_send(rec.id, True) is True

        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=chat_id, from_user_id=chat_id, text=TEXTO_CON_SUSTANCIA
            ),
        )

        turn = await _turn_row(session_factory, chat_id)
        assert turn is not None, "no se creó ningún turno para el chat de prueba"
        assert turn["status"] == "pending_approval", (
            f"con L1 OFF el turno no quedó en la cola: {turn}"
        )
        assert spy.textos_a(chat_id) == [], (
            f"con L1 OFF salió un mensaje al VIP: {spy.textos_a(chat_id)}"
        )

        aprobaciones = await _approval_rows(session_factory, chat_id)
        assert len(aprobaciones) == 1, (
            f"el borrador no cayó en la cola de la dueña: {aprobaciones}"
        )
        assert aprobaciones[0]["draft_text"] == BORRADOR, (
            f"la cola no tiene el borrador real: {aprobaciones}"
        )
        assert aprobaciones[0]["turn_id"] == turn["id"], (
            "la fila de aprobación no apunta al turno: "
            f"{aprobaciones} vs {turn['id']}"
        )

        # El corte ocurre en el Decisor (L1 es su único candado de envío).
        decision = await _trace_decision(session_factory, turn["id"])
        assert decision.get("action") == "approve", (
            f"el Decisor no demotó: {decision}"
        )
        assert decision.get("reason") == "ok_for_human_review", (
            f"el corte no fue el del Decisor sin L1: {decision}"
        )
    finally:
        captura.close()
        await _limpiar(session_factory, chat_id=chat_id, vip_tg_id=chat_id)
        await bot.session.close()


# ===========================================================================
# S2 — L1 ON y L2 OFF: el Decisor sí envía, el orquestador demota
# ===========================================================================
@pytest.mark.db
@pytest.mark.asyncio
async def test_s2_l2_cerrado_el_orquestador_demota_y_cae_en_la_cola(
    engine, session_factory, alembic_applied
) -> None:
    """L1 ON pero VIP sin ``auto_send`` → PENDING_APPROVAL, 0 salidas, motivo de L2.

    Es el punto ciego declarado del contrato: el Decisor solo mira L1 y emite
    ``send``; la segunda puerta se cierra recién en ``_prepare_autonomous_send``.
    """
    captura = CaptureHandler()
    bot, spy = _bot_con_spy()
    app = await _app(
        settings=_settings(l1=True, global_mode="supervised"),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
    )
    try:
        await _assert_vip_nuevo(session_factory, VIP_S2_L2_OFF)
        rec = await app.vips.add(VIP_S2_L2_OFF, display_name="Prueba E2")
        assert rec.auto_send is False, "el VIP de prueba nació con auto_send"

        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=VIP_S2_L2_OFF,
                from_user_id=VIP_S2_L2_OFF,
                text=TEXTO_CON_SUSTANCIA,
            ),
        )

        turn = await _turn_row(session_factory, VIP_S2_L2_OFF)
        assert turn is not None, "no se creó ningún turno para el chat de prueba"
        assert turn["status"] == "pending_approval", (
            f"con L2 cerrado el turno no quedó en la cola: {turn}"
        )
        assert spy.textos_a(VIP_S2_L2_OFF) == [], (
            f"con L2 cerrado salió un mensaje al VIP: {spy.textos_a(VIP_S2_L2_OFF)}"
        )

        aprobaciones = await _approval_rows(session_factory, VIP_S2_L2_OFF)
        assert len(aprobaciones) == 1, (
            f"el borrador no cayó en la cola de la dueña: {aprobaciones}"
        )
        assert aprobaciones[0]["draft_text"] == BORRADOR, (
            f"la cola no tiene el borrador real: {aprobaciones}"
        )
        assert aprobaciones[0]["cognitive_summary"] == "autonomous_mode_disabled", (
            f"el motivo de la democión no es el de L2: {aprobaciones}"
        )

        decision = await _trace_decision(session_factory, turn["id"])
        assert decision.get("action") == "send", (
            "el Decisor no emitió send: entonces esta prueba no está midiendo la "
            f"segunda puerta: {decision}"
        )
        assert decision.get("reason") == "autonomous_ok", f"motivo: {decision}"
    finally:
        captura.close()
        await _limpiar(
            session_factory, chat_id=VIP_S2_L2_OFF, vip_tg_id=VIP_S2_L2_OFF
        )
        await bot.session.close()


# ===========================================================================
# S3 — VIP congelado: el mensaje ni siquiera entra al motor
# ===========================================================================
@pytest.mark.db
@pytest.mark.asyncio
async def test_s3_vip_congelado_no_entra_al_motor_y_no_hay_envio(
    engine, session_factory, alembic_applied
) -> None:
    """L1 ON + L2 ON pero ``frozen_until`` futuro → sin turno, sin salida, sin cola."""
    captura = CaptureHandler()
    bot, spy = _bot_con_spy()
    app = await _app(
        settings=_settings(l1=True, global_mode="supervised"),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
    )
    try:
        await _assert_vip_nuevo(session_factory, VIP_S3_FROZEN)
        rec = await app.vips.add(VIP_S3_FROZEN, display_name="Prueba E2")
        assert await app.vips.set_auto_send(rec.id, True) is True
        await app.vips.freeze_vip(rec.id, datetime.now(UTC) + timedelta(days=1))

        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=VIP_S3_FROZEN,
                from_user_id=VIP_S3_FROZEN,
                text=TEXTO_CON_SUSTANCIA,
            ),
        )

        # La puerta de congelado está en los middlewares: no nace turno.
        assert await _turn_count(session_factory, VIP_S3_FROZEN) == 0, (
            "el mensaje de un VIP congelado llegó al motor"
        )
        assert spy.textos_a(VIP_S3_FROZEN) == [], (
            f"salió un mensaje a un VIP congelado: {spy.textos_a(VIP_S3_FROZEN)}"
        )
        assert await _approval_rows(session_factory, VIP_S3_FROZEN) == [], (
            "la cola de la dueña recibió un borrador de un VIP congelado"
        )
    finally:
        captura.close()
        await _limpiar(
            session_factory, chat_id=VIP_S3_FROZEN, vip_tg_id=VIP_S3_FROZEN
        )
        await bot.session.close()


# ===========================================================================
# S4 — VIP pausado: la pausa se aplica en la entrada
# ===========================================================================
@pytest.mark.db
@pytest.mark.asyncio
async def test_s4_vip_pausado_queda_fuera_en_la_entrada_y_al_reanudar_entrega(
    engine, session_factory, alembic_applied
) -> None:
    """L1 ON + L2 ON pero ``paused_until`` futuro → el mensaje no llega al motor.

    El contraste es la evidencia: el MISMO VIP, la MISMA configuración y el
    MISMO flujo, con la pausa quitada, sí entrega. Lo único que cambió es la
    pausa.
    """
    captura = CaptureHandler()
    bot, spy = _bot_con_spy()
    app = await _app(
        settings=_settings(l1=True, global_mode="supervised"),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
    )
    try:
        await _assert_vip_nuevo(session_factory, VIP_S4_PAUSED)
        rec = await app.vips.add(VIP_S4_PAUSED, display_name="Prueba E2")
        assert await app.vips.set_auto_send(rec.id, True) is True
        await app.vips.pause_vip(rec.id, datetime.now(UTC) + timedelta(days=1))

        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=VIP_S4_PAUSED,
                from_user_id=VIP_S4_PAUSED,
                text=TEXTO_CON_SUSTANCIA,
            ),
        )
        assert await _turn_count(session_factory, VIP_S4_PAUSED) == 0, (
            "el mensaje de un VIP pausado llegó al motor (no se aplicó la pausa "
            "en la entrada)"
        )
        assert spy.textos_a(VIP_S4_PAUSED) == [], (
            f"salió un mensaje a un VIP pausado: {spy.textos_a(VIP_S4_PAUSED)}"
        )
        assert "auth_drop_not_allowed" in captura.eventos(), (
            "el mensaje no se descartó por la puerta de autorización: "
            f"{sorted(set(captura.eventos()))}"
        )

        # Reanudar es lo único que cambia: ahora sí hay turno y sí sale.
        await app.vips.unpause_vip(rec.id)
        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=VIP_S4_PAUSED,
                from_user_id=VIP_S4_PAUSED,
                text=TEXTO_CON_SUSTANCIA,
                message_id=12,
            ),
        )
        turn = await _turn_row(session_factory, VIP_S4_PAUSED)
        assert turn is not None and turn["status"] == "delivered", (
            f"al reanudar el VIP no recibió el envío autónomo: {turn}"
        )
        assert spy.textos_a(VIP_S4_PAUSED) == [BORRADOR], (
            f"al reanudar no salió el borrador: {spy.textos_a(VIP_S4_PAUSED)}"
        )
    finally:
        captura.close()
        await _limpiar(
            session_factory, chat_id=VIP_S4_PAUSED, vip_tg_id=VIP_S4_PAUSED
        )
        await bot.session.close()


# ===========================================================================
# S4b — hallazgo H-AUT1-2: la ventana de pausa a mitad del turno
# ===========================================================================
@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.xfail(
    reason=(
        "H-AUT1-2: el camino autónomo no rechequea paused_until (solo "
        "_is_vip_paused se usa en la ruta fática). Un VIP pausado durante el "
        "turno recibe igual el envío automático."
    ),
    strict=False,
)
async def test_s4b_ventana_pausa_a_mitad_del_turno_no_detiene_el_envio(
    engine, session_factory, alembic_applied
) -> None:
    """La promesa de fail-closed incluye la pausa: un VIP pausado no recibe nada.

    La pausa se inyecta cuando el pipeline ya arrancó (el mensaje pasó los
    middlewares antes de la pausa), que es el único hueco posible: la puerta de
    entrada ya quedó atrás.
    """
    captura = CaptureHandler()
    bot, spy = _bot_con_spy()
    estado: dict[str, Any] = {}

    async def _pausar() -> None:
        await app.vips.pause_vip(estado["vip_id"], datetime.now(UTC) + timedelta(days=1))

    app = await _app(
        settings=_settings(l1=True, global_mode="supervised"),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_pausa_a_mitad(_pausar),
    )
    try:
        await _assert_vip_nuevo(session_factory, VIP_S4B_WINDOW)
        rec = await app.vips.add(VIP_S4B_WINDOW, display_name="Prueba E2")
        estado["vip_id"] = rec.id
        assert await app.vips.set_auto_send(rec.id, True) is True

        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=VIP_S4B_WINDOW,
                from_user_id=VIP_S4B_WINDOW,
                text=TEXTO_CON_SUSTANCIA,
            ),
        )

        # El VIP quedó pausado antes de que el orquestador preparara el envío.
        vip = await app.vips.get_by_id(rec.id)
        assert vip is not None and vip.paused_until is not None, (
            "la pausa no se aplicó: la prueba no está midiendo la ventana"
        )

        turn = await _turn_row(session_factory, VIP_S4B_WINDOW)
        envios = spy.textos_a(VIP_S4B_WINDOW)
        assert turn is not None and turn["status"] != "delivered" and envios == [], (
            f"un VIP pausado recibió el envío autónomo: turno={turn} "
            f"envios={envios}"
        )
    finally:
        captura.close()
        await _limpiar(
            session_factory, chat_id=VIP_S4B_WINDOW, vip_tg_id=VIP_S4B_WINDOW
        )
        await bot.session.close()


def _pausa_a_mitad(al_pausar: Any) -> FakeLLM:
    """Arma el doble del modelo con la pausa inyectada en la primera llamada."""
    return _PausaAMitadDelTurnoLLM(
        al_pausar=al_pausar,
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
        text_responses=[BORRADOR],
    )


# ===========================================================================
# S5 — canal de Atención (vip_id=None): nunca autónomo, ni con L1 + global
# ===========================================================================
@pytest.mark.db
@pytest.mark.asyncio
async def test_s5_atencion_con_l1_y_modo_global_nunca_es_autonomo(
    engine, session_factory, alembic_applied
) -> None:
    """``vip_id=None`` + L1 ON + ``GLOBAL_MODE=autonomous`` → supervisado.

    Se entra por el flujo real de un chat no-VIP (modo entrenamiento), que es
    la única vía por la que un canal de Atención llega al pipeline.
    """
    captura = CaptureHandler()
    bot, spy = _bot_con_spy()
    previo_training = await _leer_training_mode(session_factory)
    await _set_training_mode(session_factory, True)
    app = await _app(
        settings=_settings(l1=True, global_mode="autonomous"),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
    )
    try:
        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=CHAT_ATENCION,
                from_user_id=CHAT_ATENCION,
                text=TEXTO_CON_SUSTANCIA,
            ),
        )

        turn = await _turn_row(session_factory, CHAT_ATENCION)
        assert turn is not None, (
            "el chat de Atención no llegó al pipeline (modo entrenamiento): "
            f"eventos={sorted(set(captura.eventos()))}"
        )
        assert turn["channel_type"] == "atencion", f"canal inesperado: {turn}"
        assert turn["vip_id"] is None, f"el canal de Atención trae VIP: {turn}"

        assert turn["status"] == "pending_approval", (
            f"el canal de Atención no fue supervisado: {turn}"
        )
        assert spy.textos_a(CHAT_ATENCION) == [], (
            f"el canal de Atención envió solo: {spy.textos_a(CHAT_ATENCION)}"
        )

        aprobaciones = await _approval_rows(session_factory, CHAT_ATENCION)
        assert len(aprobaciones) == 1, (
            f"el borrador de Atención no cayó en la cola: {aprobaciones}"
        )
        assert aprobaciones[0]["vip_id"] is None, (
            f"la fila de aprobación de Atención trae VIP: {aprobaciones}"
        )

        decision = await _trace_decision(session_factory, turn["id"])
        assert decision.get("action") == "send", (
            "el Decisor no emitió send: la prueba no está midiendo el guard "
            f"de vip_id=None: {decision}"
        )
    finally:
        captura.close()
        await _limpiar(session_factory, chat_id=CHAT_ATENCION)
        await _restaurar_training_mode(session_factory, previo_training)
        await bot.session.close()


# ===========================================================================
# S6 — BehaviorEngine no cableado: turno FAILED y borrador perdido
# ===========================================================================
@pytest.mark.db
@pytest.mark.asyncio
async def test_s6_sin_behavior_el_turno_falla_y_el_borrador_no_va_a_la_cola(
    engine, session_factory, alembic_applied
) -> None:
    """L1 ON + L2 ON sin motor de envío → ``FAILED``, 0 salidas y 0 aprobaciones.

    La pieza no cableada se inyecta sobre el contenedor real (``build_app``
    siempre cablea el motor; el ramal existe para un cableado parcial). Fija el
    punto ciego del contrato: el mensaje del VIP queda sin respuesta y sin cola.
    """
    captura = CaptureHandler()
    bot, spy = _bot_con_spy()
    app = await _app(
        settings=_settings(l1=True, global_mode="supervised"),
        engine=engine,
        session_factory=session_factory,
        bot=bot,
        llm=_fake_llm(),
    )
    app.orchestrator._behavior = None  # noqa: SLF001  # falla inyectada
    try:
        await _assert_vip_nuevo(session_factory, VIP_S6_NO_BEHAVIOR)
        rec = await app.vips.add(VIP_S6_NO_BEHAVIOR, display_name="Prueba E2")
        assert await app.vips.set_auto_send(rec.id, True) is True

        await app.dispatcher.feed_update(
            bot,
            _business_update(
                chat_id=VIP_S6_NO_BEHAVIOR,
                from_user_id=VIP_S6_NO_BEHAVIOR,
                text=TEXTO_CON_SUSTANCIA,
            ),
        )

        turn = await _turn_row(session_factory, VIP_S6_NO_BEHAVIOR)
        assert turn is not None, "no se creó ningún turno para el chat de prueba"
        assert turn["status"] == "failed", (
            f"sin motor de envío el turno no quedó fallado: {turn}"
        )
        assert turn["error"] == "autonomous_behavior_not_wired", (
            f"el motivo del fallo no es el esperado: {turn}"
        )
        assert spy.textos_a(VIP_S6_NO_BEHAVIOR) == [], (
            f"salió un mensaje sin motor: {spy.textos_a(VIP_S6_NO_BEHAVIOR)}"
        )
        # Hallazgo del contrato: el borrador NO cae en la cola de la dueña.
        assert await _approval_rows(session_factory, VIP_S6_NO_BEHAVIOR) == [], (
            "el borrador sí cayó en la cola (la promesa mejoró: actualizar el "
            "contrato C-AUT-01, punto ciego 5)"
        )
        assert "autonomous_behavior_not_wired" in captura.eventos(), (
            "el fallo no dejó rastro visible en los eventos"
        )
    finally:
        captura.close()
        await _limpiar(
            session_factory, chat_id=VIP_S6_NO_BEHAVIOR, vip_tg_id=VIP_S6_NO_BEHAVIOR
        )
        await bot.session.close()
