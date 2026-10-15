"""C-AUT-02 — la puerta de recomendación mide y nunca envía sola.

Prueba E2 contra Postgres REAL (copia de la base real en un contenedor
desechable, ver ``audit/ENTORNO.md``). El contenedor se arma con ``build_app``
y se asertan filas: ``vips.auto_send``, ``vip_trust_budget`` y los turnos
terminados de los que sale la coincidencia. El único simulado es el modelo de
lenguaje externo (``llm/fake.py``); el actuador de Telegram es un doble que
solo registra lo que se habría enviado.

Promesa bajo prueba (``audit/contracts/C-AUT-02.md``, AGENTS.md §3 flujo 4.19):
  (1) ``ready`` es True SOLO con las tres condiciones a la vez — confianza del
      VIP ≥ 0.90, coincidencia global ≥ 95 % en la ventana y cero escalaciones
      por seguridad — y el motivo dice cuál falta;
  (2) ``activate`` escribe ``vips.auto_send`` solo cuando ``ready`` es True;
  (3) activar NO envía nada;
  (4) H-1: ``FEATURE_AUTONOMY_COINCIDENCE_ENABLED`` no la lee ningún módulo
      (bandera muerta: la coincidencia se calcula igual con la bandera en OFF);
  (6) H-6: ``activate`` dice "Activado" y escribe ``auto_send=true`` aunque el
      interruptor maestro L1 (``FEATURE_AUTONOMOUS_MODE``) esté apagado, y con
      L1 apagado el envío real no ocurre nunca.

Escenario de datos: la copia real trae la ventana de 14 días ya poblada
(94 turnos terminados, coincidencia 93 %). Las condiciones globales
(coincidencia y escalaciones de seguridad) no son por VIP, así que cada
prueba ajusta la ventana con turnos PROPIOS (chat y fechas propios) y los
borra al terminar. Nunca se tocan filas reales.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

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

RAIZ = Path(__file__).resolve().parents[2]

# Ids propios, fuera de los rangos reales de Telegram.
VIP_LISTO = 999600101  # confianza alta (0.95)
VIP_LEJOS = 999600102  # confianza baja (0.45)
CHAT_PIPE = VIP_LISTO  # chat real del VIP (el handler solo acepta VIP conocidos)
CHAT_SEMILLA = 999600202  # chat de los turnos sembrados para la ventana

TEXTO_VIP = "Hola Diana, ya estoy en casa tranquila y queria saludarte un rato."

EVALUACION_ALTA: dict[str, Any] = {
    "naturalness": 0.9,
    "precision": 0.9,
    "doctrine": 0.9,
    "consistency": 0.9,
    "safety": 0.95,
    "coverage": 0.9,
    "empathy": 0.9,
}
COMPRENSION: dict[str, Any] = {
    "intent": "saludar",
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


# ---------------------------------------------------------------------------
# Configuración: solo lo que la prueba necesita; el resto en su default.
# ---------------------------------------------------------------------------
def _settings(
    *, coincidence: bool = True, autonomous: bool = False, recommendation: bool = True
) -> Settings:
    return Settings.model_construct(
        telegram_bot_token=SecretStr(TOKEN),
        owner_telegram_id=OWNER_ID,
        database_url=SecretStr(
            "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder"
        ),
        deepseek_api_key="",
        global_mode="supervised",
        feature_autonomy_quality_enabled=True,
        feature_autonomy_readiness_enabled=True,
        feature_autonomy_coincidence_enabled=coincidence,
        feature_autonomy_recommendation_enabled=recommendation,
        feature_trust_budget=True,
        feature_phatic_autonomy=True,
        feature_phatic_auto_send=False,
        feature_gray_zone_enabled=False,
        feature_memory_enabled=False,
        feature_staging_enabled=False,
        feature_quality_feedback_enabled=False,
        feature_autonomous_mode=autonomous,
        feature_sandbox_enabled=False,
        log_level="WARNING",
    )


class SesionEspia:
    """Doble del actuador de Telegram: registra lo que se habría enviado.

    ``envios`` cuenta SOLO mensajes (nada de ``SendChatAction``/lecturas): es la
    evidencia de "no se envió nada al VIP", no de "hubo actividad".
    """

    MENSAJES = frozenset(
        {
            "SendMessage",
            "SendPhoto",
            "SendVideo",
            "SendVoice",
            "SendAudio",
            "SendDocument",
            "SendAnimation",
            "SendSticker",
        }
    )

    def __init__(self) -> None:
        self.metodos: list[str] = []
        self.envios: list[tuple[str, int]] = []
        self.textos: list[tuple[int, str]] = []

    async def __call__(self, bot: Any, method: Any, timeout: Any = None) -> Any:
        nombre = type(method).__name__
        self.metodos.append(nombre)
        if nombre in self.MENSAJES:
            chat_id = int(getattr(method, "chat_id", 0) or 0)
            self.envios.append((nombre, chat_id))
            texto = getattr(method, "text", None) or getattr(method, "caption", None)
            if texto:
                self.textos.append((chat_id, str(texto)))
            return Message(
                message_id=1000 + len(self.metodos),
                date=datetime(2026, 10, 8, 12, 0, 0),
                chat=Chat(id=chat_id, type="private"),
                text=str(texto) if texto else None,
            )
        return None

    async def close(self) -> None:
        return None


def _llm(*, turnos: int = 1) -> FakeLLM:
    return FakeLLM(
        structured_responses=(
            [Comprehension.model_validate(COMPRENSION) for _ in range(turnos)]
            + [EvaluationProfile.model_validate(EVALUACION_ALTA) for _ in range(turnos)]
        ),
        text_responses=["Claro, aqui seguimos con calma."] * turnos,
    )


def _update_negocio(chat_id: int, texto: str, message_id: int = 11) -> Update:
    msg = Message(
        message_id=message_id,
        date=datetime(2026, 10, 8, 12, 0, 0),
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=chat_id, is_bot=False, first_name="Vip"),
        text=texto,
        business_connection_id=f"bc-audit-{chat_id}",
    )
    return Update(update_id=message_id, business_message=msg)


def _app(settings: Settings, *, engine, session_factory) -> tuple[Any, SesionEspia]:
    bot = Bot(token=TOKEN)
    espia = SesionEspia()
    bot.session = espia  # type: ignore[assignment]
    app = build_app(
        settings,
        bot=bot,
        llm=_llm(),
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    return app, espia


# ---------------------------------------------------------------------------
# Lecturas y siembra sobre filas reales
# ---------------------------------------------------------------------------
async def _vip_id(session_factory, telegram_user_id: int) -> str:
    async with session_factory() as s:
        return str(
            (
                await s.execute(
                    text("select id::text from vips where telegram_user_id = :u"),
                    {"u": telegram_user_id},
                )
            ).scalar_one()
        )


async def _auto_send(session_factory, vip_id: str) -> bool:
    async with session_factory() as s:
        return bool(
            (
                await s.execute(
                    text("select auto_send from vips where id = :v"), {"v": vip_id}
                )
            ).scalar_one()
        )


async def _resumen(app) -> dict[str, Any]:
    """Resumen real de coincidencia + escalaciones de la ventana del panel."""
    return await app.autonomy_readiness._summary()  # noqa: SLF001 (lectura del panel)


async def _sembrar_turnos(
    session_factory,
    *,
    chat_id: int,
    vip_id: str,
    n: int,
    estado: str = "delivered",
    evaluacion: dict[str, Any] | None = None,
) -> list[str]:
    """Siembra turnos TERMINADOS con su traza (escenario de la ventana).

    Es data de escenario, no un doble: el panel relee estas filas por la misma
    consulta real (`list_finished_source_turns`) y las re-decide con el Decisor
    sombra real. ``delivered`` sin corrección = acierto; ``escalated`` con
    veredicto sombra ``send`` = desacuerdo; ``escalated`` con ``safety`` bajo el
    gate = escalación de seguridad.
    """
    ids: list[str] = []
    async with session_factory() as s:
        for _ in range(n):
            turn_id = str(uuid4())
            ids.append(turn_id)
            await s.execute(
                text(
                    "insert into turns (id, chat_id, vip_id, channel_type, status, created_at) "
                    "values (:id, :chat, :vip, 'vip', :estado, now())"
                ),
                {"id": turn_id, "chat": chat_id, "vip": vip_id, "estado": estado},
            )
            await s.execute(
                text(
                    "insert into pipeline_traces (id, turn_id, vip_id, chat_id, channel_type, "
                    "comprehension, evaluation, generated_text, decision, created_at) "
                    "values (:id, :tid, :vip, :chat, 'vip', cast(:comp as jsonb), "
                    "cast(:ev as jsonb), 'borrador de escenario', '{}'::jsonb, now())"
                ),
                {
                    "id": str(uuid4()),
                    "tid": turn_id,
                    "vip": vip_id,
                    "chat": chat_id,
                    "comp": json.dumps(COMPRENSION),
                    "ev": json.dumps(evaluacion or EVALUACION_ALTA),
                },
            )
        await s.commit()
    return ids


async def _sembrar_confianza(
    session_factory, *, vip_id: str, categoria: str, score: float
) -> None:
    async with session_factory() as s:
        await s.execute(
            text(
                "insert into vip_trust_budget (vip_id, turn_category, trust_score) "
                "values (:vip, :cat, :score) "
                "on conflict (vip_id, turn_category) do update set trust_score = :score, "
                "autonomous_count = 0, correction_count = 0, last_correction_at = null"
            ),
            {"vip": vip_id, "cat": categoria, "score": score},
        )
        await s.commit()


async def _limpiar_lo_nuestro(
    session_factory, *, chats: list[int], vips_tg: list[int]
) -> None:
    """Borra SOLO lo creado por la prueba, resolviendo las FK por catálogo."""
    async with session_factory() as s:
        vip_ids = (
            (
                await s.execute(
                    text("select id::text from vips where telegram_user_id = any(:ids)"),
                    {"ids": vips_tg},
                )
            )
            .scalars()
            .all()
        )
        if not vip_ids:
            return
        refs = (
            await s.execute(
                text(
                    "select tc.table_name, kcu.column_name "
                    "from information_schema.table_constraints tc "
                    "join information_schema.key_column_usage kcu "
                    "  on kcu.constraint_name = tc.constraint_name "
                    "join information_schema.constraint_column_usage ccu "
                    "  on ccu.constraint_name = tc.constraint_name "
                    "where tc.constraint_type = 'FOREIGN KEY' "
                    "  and ccu.table_name in ('turns', 'vips')"
                )
            )
        ).all()
        por_tabla: dict[str, set[str]] = {}
        for tabla, col in refs:
            por_tabla.setdefault(tabla, set()).add(col)
        turnos = "select id from turns where chat_id = any(:chats) or vip_id = any(:vips)"
        for tabla, cols in por_tabla.items():
            clausulas = []
            if "turn_id" in cols:
                clausulas.append(f"turn_id in ({turnos})")
            if "vip_id" in cols:
                clausulas.append("vip_id = any(:vips)")
            if not clausulas:
                continue
            await s.execute(
                text(f"delete from {tabla} where " + " or ".join(clausulas)),
                {"chats": chats, "vips": vip_ids},
            )
        await s.execute(
            text("delete from turns where chat_id = any(:chats) or vip_id = any(:vips)"),
            {"chats": chats, "vips": vip_ids},
        )
        await s.execute(
            text("delete from vips where id = any(:vips)"), {"vips": vip_ids}
        )
        await s.execute(
            text("delete from message_history where chat_id = any(:chats)"),
            {"chats": chats},
        )
        await s.commit()


async def _assert_vip_nuevo(session_factory, telegram_user_id: int) -> None:
    async with session_factory() as s:
        previo = (
            await s.execute(
                text("select count(*) from vips where telegram_user_id = :u"),
                {"u": telegram_user_id},
            )
        ).scalar_one()
    assert previo == 0, (
        f"el VIP {telegram_user_id} ya existe en la base; elegir otro id de prueba"
    )


async def _base_de_la_puerta(app, session_factory) -> tuple[str, str]:
    """Da de alta los dos VIP de la prueba con su confianza ya sembrada."""
    await _assert_vip_nuevo(session_factory, VIP_LISTO)
    await _assert_vip_nuevo(session_factory, VIP_LEJOS)
    await app.vips.add(VIP_LISTO, display_name="Puerta lista")
    await app.vips.add(VIP_LEJOS, display_name="Puerta lejos")
    rico = await _vip_id(session_factory, VIP_LISTO)
    lejos = await _vip_id(session_factory, VIP_LEJOS)
    await _sembrar_confianza(
        session_factory, vip_id=rico, categoria="fatico", score=0.95
    )
    await _sembrar_confianza(
        session_factory, vip_id=lejos, categoria="fatico", score=0.45
    )
    return rico, lejos


def _turnos_para_superar_la_meta(resumen: dict[str, Any]) -> int:
    """Aciertos propios necesarios para que (a+n)/(a+d+n) >= 0.95."""
    a0, d0 = resumen["aciertos"], resumen["desacuerdos"]
    return max(0, ceil(19 * d0 - a0)) + 2


def _turnos_para_quedar_bajo_la_meta(resumen: dict[str, Any]) -> int:
    """Desacuerdos propios necesarios para que a/(a+d+n) < 0.95."""
    a0, d0 = resumen["aciertos"], resumen["desacuerdos"]
    return max(1, int(a0 / 19 - d0) + 2)


# ---------------------------------------------------------------------------
# (1) las tres condiciones, una por una
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
async def test_1_falta_la_coincidencia_global(engine, session_factory, alembic_applied):
    """Dos de tres: confianza OK y cero escalaciones, pero la coincidencia baja.

    La ventana real viene al 93 % (< 95 %), así que este caso es el estado
    natural de la base; si una copia futura ya viniera ≥ 95 %, la prueba agrega
    los desacuerdos que hagan falta para volver a dejarla por debajo.
    """
    app, espia = _app(_settings(), engine=engine, session_factory=session_factory)
    try:
        rico, _ = await _base_de_la_puerta(app, session_factory)
        data = await _resumen(app)
        assert data["safety_escalations"] == 0, "la ventana trae escalaciones reales"
        await _sembrar_turnos(
            session_factory,
            chat_id=CHAT_SEMILLA,
            vip_id=rico,
            n=_turnos_para_quedar_bajo_la_meta(data["summary"]),
            estado="escalated",
        )

        readiness = await app.autonomy_readiness.recommendation(UUID(rico))
        assert readiness is not None
        # Las otras dos condiciones están cumplidas (si no, no aislaría nada).
        assert readiness.meets_confidence is True, (
            f"la confianza no era alta: {readiness.best_trust}"
        )
        assert readiness.global_safety_escalations == 0
        assert readiness.global_rate is not None
        assert readiness.global_rate < 0.95, (
            f"se esperaba la coincidencia por debajo de la meta: {readiness.global_rate}"
        )
        assert readiness.ready is False, "la puerta se abrió con la coincidencia baja"

        motivo = app.autonomy_readiness._not_ready_reason(readiness)  # noqa: SLF001
        assert "coincidencia global" in motivo, f"motivo inesperado: {motivo}"
        assert "confianza" not in motivo, f"culpó a otra condición: {motivo}"
        assert "escalación" not in motivo, f"culpó a otra condición: {motivo}"

        ok, texto = await app.autonomy_readiness.activate(UUID(rico))
        assert ok is False, f"activate abrió la puerta: {texto}"
        assert "coincidencia global" in texto, f"no devolvió el motivo: {texto}"
        assert await _auto_send(session_factory, rico) is False, (
            "activate escribió auto_send con ready=False"
        )
        assert espia.metodos == [], f"activate tocó Telegram: {espia.metodos}"
    finally:
        await _limpiar_lo_nuestro(
            session_factory, chats=[CHAT_SEMILLA], vips_tg=[VIP_LISTO, VIP_LEJOS]
        )
        await app.bot.session.close()


@pytest.mark.db
@pytest.mark.asyncio
async def test_2_falta_la_confianza(engine, session_factory, alembic_applied):
    """Dos de tres: coincidencia y escalaciones OK, pero la confianza del VIP no.

    La ventana se empuja a ≥ 95 % con aciertos propios (turnos entregados y
    aprobados por la dueña) para que la única condición que falte sea la
    confianza.
    """
    app, espia = _app(_settings(), engine=engine, session_factory=session_factory)
    try:
        rico, lejos = await _base_de_la_puerta(app, session_factory)
        data = await _resumen(app)
        assert data["safety_escalations"] == 0, "la ventana trae escalaciones reales"
        n = _turnos_para_superar_la_meta(data["summary"])
        assert n > 0, "la copia ya venía con la coincidencia sobre la meta"
        await _sembrar_turnos(session_factory, chat_id=CHAT_SEMILLA, vip_id=rico, n=n)

        readiness = await app.autonomy_readiness.recommendation(UUID(lejos))
        assert readiness is not None
        assert readiness.global_rate is not None and readiness.global_rate >= 0.95, (
            f"la coincidencia no llegó a la meta: {readiness.global_rate}"
        )
        assert readiness.global_safety_escalations == 0
        assert readiness.meets_confidence is False
        assert readiness.ready is False, "la puerta se abrió con la confianza baja"

        motivo = app.autonomy_readiness._not_ready_reason(readiness)  # noqa: SLF001
        assert "confianza 0.45 < 0.90" in motivo, f"motivo inesperado: {motivo}"
        assert "coincidencia" not in motivo, f"culpó a otra condición: {motivo}"
        assert "escalación" not in motivo, f"culpó a otra condición: {motivo}"

        ok, texto = await app.autonomy_readiness.activate(UUID(lejos))
        assert ok is False and "confianza" in texto, f"activate: {ok} {texto}"
        assert await _auto_send(session_factory, lejos) is False
        assert espia.metodos == [], f"activate tocó Telegram: {espia.metodos}"
    finally:
        await _limpiar_lo_nuestro(
            session_factory, chats=[CHAT_SEMILLA], vips_tg=[VIP_LISTO, VIP_LEJOS]
        )
        await app.bot.session.close()


@pytest.mark.db
@pytest.mark.asyncio
async def test_3_falta_una_escalacion_de_seguridad(engine, session_factory, alembic_applied):
    """Dos de tres: confianza y coincidencia OK, pero hubo escalación de seguridad.

    La escalación se cuenta sobre las comparativas recomputadas en sombra
    (`shadow_reason == "safety_below_threshold"`), así que se siembra un turno
    terminado con `safety` por debajo del gate: el Decisor sombra real lo
    re-decide y el panel lo cuenta.
    """
    app, espia = _app(_settings(), engine=engine, session_factory=session_factory)
    try:
        rico, _ = await _base_de_la_puerta(app, session_factory)
        data = await _resumen(app)
        if data["safety_escalations"] > 0:
            pytest.skip(
                "la copia ya trae escalaciones de seguridad reales en la ventana; "
                "el conteo exacto no sería demostrable sin borrar datos reales"
            )
        n = _turnos_para_superar_la_meta(data["summary"])
        assert n > 0, "la copia ya venía con la coincidencia sobre la meta"
        await _sembrar_turnos(session_factory, chat_id=CHAT_SEMILLA, vip_id=rico, n=n)
        await _sembrar_turnos(
            session_factory,
            chat_id=CHAT_SEMILLA,
            vip_id=rico,
            n=1,
            estado="escalated",
            evaluacion={**EVALUACION_ALTA, "safety": 0.1},
        )

        readiness = await app.autonomy_readiness.recommendation(UUID(rico))
        assert readiness is not None
        assert readiness.meets_confidence is True
        assert readiness.global_rate is not None and readiness.global_rate >= 0.95
        assert readiness.global_safety_escalations == 1, (
            f"el panel no contó la escalación sembrada: "
            f"{readiness.global_safety_escalations}"
        )
        assert readiness.ready is False, (
            "la puerta se abrió con una escalación de seguridad"
        )

        motivo = app.autonomy_readiness._not_ready_reason(readiness)  # noqa: SLF001
        assert "escalación(es) de seguridad" in motivo, f"motivo inesperado: {motivo}"
        assert "confianza" not in motivo, f"culpó a otra condición: {motivo}"
        assert "coincidencia" not in motivo, f"culpó a otra condición: {motivo}"

        ok, texto = await app.autonomy_readiness.activate(UUID(rico))
        assert ok is False and "escalación" in texto, f"activate: {ok} {texto}"
        assert await _auto_send(session_factory, rico) is False
        assert espia.metodos == [], f"activate tocó Telegram: {espia.metodos}"
    finally:
        await _limpiar_lo_nuestro(
            session_factory, chats=[CHAT_SEMILLA], vips_tg=[VIP_LISTO, VIP_LEJOS]
        )
        await app.bot.session.close()


# ---------------------------------------------------------------------------
# (2) + (3) las tres cumplidas: escribe auto_send y no envía nada
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
async def test_4_las_tres_cumplidas_activa_y_no_envia(
    engine, session_factory, alembic_applied
):
    """Con las tres condiciones, `activate` escribe `vips.auto_send` (DB real).

    Y no envía nada: el actuador no recibe ni una llamada de envío antes ni
    después de activar (el interruptor maestro sigue gobernando el envío real).
    """
    app, espia = _app(_settings(), engine=engine, session_factory=session_factory)
    try:
        rico, _ = await _base_de_la_puerta(app, session_factory)
        data = await _resumen(app)
        if data["safety_escalations"] > 0:
            pytest.skip(
                "la copia ya trae escalaciones de seguridad reales en la ventana; "
                "el caso 'todo cumplido' no sería demostrable sin borrar datos reales"
            )
        await _sembrar_turnos(
            session_factory,
            chat_id=CHAT_SEMILLA,
            vip_id=rico,
            n=_turnos_para_superar_la_meta(data["summary"]),
        )

        readiness = await app.autonomy_readiness.recommendation(UUID(rico))
        assert readiness is not None
        assert readiness.ready is True, (
            app.autonomy_readiness._not_ready_reason(readiness)  # noqa: SLF001
        )
        assert readiness.meets_confidence and readiness.global_rate >= 0.95
        assert readiness.global_safety_escalations == 0
        assert await _auto_send(session_factory, rico) is False

        # El panel (lo que ve la dueña) marca LISTO solo al que cumple las tres;
        # al otro le dice exactamente qué le falta.
        panel = await app.autonomy_readiness.render_by_vip()
        assert "Puerta lista — ✅ LISTO" in panel, f"el panel no marcó listo:\n{panel}"
        assert "Puerta lejos — ⏳ en camino" in panel, f"el panel marcó de más:\n{panel}"
        assert "Faltan: confianza 0.45 < 0.90." in panel, (
            f"el panel no explicó el motivo:\n{panel}"
        )

        envios_antes = list(espia.envios)
        ok, texto = await app.autonomy_readiness.activate(UUID(rico))
        assert ok is True, f"no activó con las tres cumplidas: {texto}"
        assert "Activado" in texto, f"confirmación inesperada: {texto}"
        assert await _auto_send(session_factory, rico) is True, (
            "activate no escribió auto_send en la base"
        )
        assert espia.envios == envios_antes == [], (
            f"activar envió algo por Telegram: {espia.envios}"
        )
    finally:
        await _limpiar_lo_nuestro(
            session_factory, chats=[CHAT_SEMILLA], vips_tg=[VIP_LISTO, VIP_LEJOS]
        )
        await app.bot.session.close()


# ---------------------------------------------------------------------------
# (4) H-1 — la bandera de coincidencia no la lee nadie
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
async def test_5_h1_bandera_de_coincidencia_es_muerta(
    engine, session_factory, alembic_applied
):
    """H-1: con la bandera en OFF la coincidencia se calcula igual.

    Se documenta el comportamiento REAL: la única diferencia entre los dos
    contenedores es el valor de `settings`; el resumen de coincidencia (la
    fuente de la condición 2 de la puerta) es idéntico. Se agrega el escaneo
    estático del código: ningún módulo fuera de la definición/el catálogo
    menciona la bandera.
    """
    bot_on = Bot(token=TOKEN)
    bot_on.session = SesionEspia()  # type: ignore[assignment]
    app_on = build_app(
        _settings(coincidence=True),
        bot=bot_on,
        llm=_llm(),
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    bot_off = Bot(token=TOKEN)
    bot_off.session = SesionEspia()  # type: ignore[assignment]
    app_off = build_app(
        _settings(coincidence=False),
        bot=bot_off,
        llm=_llm(),
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    try:
        assert app_on.settings.feature_autonomy_coincidence_enabled is True
        assert app_off.settings.feature_autonomy_coincidence_enabled is False

        resumen_on = await _resumen(app_on)
        resumen_off = await _resumen(app_off)
        campos = ("n", "n_labeled", "aciertos", "desacuerdos", "conservadora", "rate")
        for campo in campos:
            assert resumen_on["summary"][campo] == resumen_off["summary"][campo], (
                f"la bandera cambió la coincidencia en {campo}: "
                f"{resumen_on['summary'][campo]} != {resumen_off['summary'][campo]}"
            )
        assert resumen_on["safety_escalations"] == resumen_off["safety_escalations"]
        # La capacidad sigue viva con la bandera apagada (no es "desactivada").
        assert resumen_off["summary"]["n"] > 0, (
            "con la bandera OFF no se calculó ninguna comparativa"
        )
        assert resumen_off["summary"]["rate"] is not None

        # Escaneo estático: quién menciona la bandera en el código.
        lectores = set()
        for archivo in (RAIZ / "src" / "diana").rglob("*.py"):
            if "autonomy_coincidence" in archivo.read_text(encoding="utf-8"):
                lectores.add(str(archivo.relative_to(RAIZ)))
        assert lectores <= {
            "src/diana/config/settings.py",
            "src/diana/config/banderas_nucleo.py",
        }, f"apareció un lector nuevo de la bandera: {sorted(lectores)}"
    finally:
        await app_on.bot.session.close()
        await app_off.bot.session.close()


# ---------------------------------------------------------------------------
# (6) H-6 — "Activado" con el maestro apagado
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
async def test_6_h6_activar_dice_activado_aunque_el_maestro_este_apagado(
    engine, session_factory, alembic_applied
):
    """H-6: `activate` responde "Activado" y escribe `auto_send=true` con L1 en OFF.

    Y el envío real no ocurre: un mensaje real del VIP deja el turno en
    `pending_approval` (cola de la dueña), sin un solo envío al chat del VIP.
    El contraste con L1 en ON sobre el MISMO VIP y el mismo `auto_send=true`
    muestra que la diferencia es exactamente el interruptor maestro.
    """
    app, espia = _app(
        _settings(autonomous=False), engine=engine, session_factory=session_factory
    )
    app_on = None
    try:
        rico, _ = await _base_de_la_puerta(app, session_factory)
        data = await _resumen(app)
        if data["safety_escalations"] > 0:
            pytest.skip("la copia trae escalaciones de seguridad reales en la ventana")
        await _sembrar_turnos(
            session_factory,
            chat_id=CHAT_SEMILLA,
            vip_id=rico,
            n=_turnos_para_superar_la_meta(data["summary"]),
        )

        # La dueña toca "Activar": el botón dice Activado y la base lo refleja.
        ok, texto = await app.autonomy_readiness.activate(UUID(rico))
        assert ok is True and "Activado" in texto, f"activate: {ok} {texto}"
        assert await _auto_send(session_factory, rico) is True
        assert app.settings.feature_autonomous_mode is False, (
            "el escenario necesita el maestro apagado"
        )

        # Y aun así, un mensaje real del VIP NO se envía solo.
        await app.dispatcher.feed_update(app.bot, _update_negocio(CHAT_PIPE, TEXTO_VIP))
        async with session_factory() as s:
            fila = (
                await s.execute(
                    text(
                        "select id::text, status from turns where chat_id = :c "
                        "order by created_at desc limit 1"
                    ),
                    {"c": CHAT_PIPE},
                )
            ).one()
        assert fila.status == "pending_approval", (
            f"con L1 apagado el turno no debía enviarse solo: {fila.status}"
        )
        assert [c for _, c in espia.envios if c == CHAT_PIPE] == [], (
            f"se envió algo al VIP con L1 apagado: {espia.envios}"
        )

        # Contraste: mismo VIP, mismo auto_send, L1 encendido → sí se envía solo.
        bot_on = Bot(token=TOKEN)
        espia_on = SesionEspia()
        bot_on.session = espia_on  # type: ignore[assignment]
        app_on = build_app(
            _settings(autonomous=True),
            bot=bot_on,
            llm=_llm(),
            session_factory=session_factory,
            engine=engine,
            delay_policy=FixedDelayPolicy(),
        )
        assert app_on.settings.feature_autonomous_mode is True
        await app_on.dispatcher.feed_update(
            bot_on, _update_negocio(CHAT_PIPE, TEXTO_VIP, 12)
        )
        async with session_factory() as s:
            fila_on = (
                await s.execute(
                    text(
                        "select id::text, status from turns where chat_id = :c "
                        "order by created_at desc limit 1"
                    ),
                    {"c": CHAT_PIPE},
                )
            ).one()
        assert fila_on.status == "delivered", (
            f"con L1 encendido y auto_send=true el turno no se envió solo: "
            f"{fila_on.status}"
        )
        assert [c for _, c in espia_on.envios if c == CHAT_PIPE] == [CHAT_PIPE], (
            f"no salió el mensaje autónomo al VIP: {espia_on.envios}"
        )
        assert any(
            c == CHAT_PIPE and t == "Claro, aqui seguimos con calma."
            for c, t in espia_on.textos
        ), f"el texto enviado no fue el borrador autónomo: {espia_on.textos}"
    finally:
        if app_on is not None:
            await app_on.bot.session.close()
        await _limpiar_lo_nuestro(
            session_factory,
            chats=[CHAT_SEMILLA, VIP_LISTO],
            vips_tg=[VIP_LISTO, VIP_LEJOS],
        )
        await app.bot.session.close()


# ---------------------------------------------------------------------------
# (2b) la bandera del panel apagada: `activate` se niega y no escribe
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
async def test_7_con_la_recomendacion_apagada_activate_no_escribe(
    engine, session_factory, alembic_applied
):
    """La otra bandera de la puerta: sin panel, `activate` no escribe nada.

    Se usa un VIP que SÍ cumpliría las tres condiciones: la negativa tiene que
    venir de la bandera, no del estado de los datos.
    """
    app, espia = _app(
        _settings(recommendation=False), engine=engine, session_factory=session_factory
    )
    try:
        rico, _ = await _base_de_la_puerta(app, session_factory)
        data = await _resumen(app)
        if data["safety_escalations"] > 0:
            pytest.skip("la copia trae escalaciones de seguridad reales en la ventana")
        await _sembrar_turnos(
            session_factory,
            chat_id=CHAT_SEMILLA,
            vip_id=rico,
            n=_turnos_para_superar_la_meta(data["summary"]),
        )
        readiness = await app.autonomy_readiness.recommendation(UUID(rico))
        assert readiness.ready is True, (
            app.autonomy_readiness._not_ready_reason(readiness)  # noqa: SLF001
        )

        ok, texto = await app.autonomy_readiness.activate(UUID(rico))
        assert ok is False, f"activó con el panel apagado: {texto}"
        assert "desactivada" in texto, f"motivo inesperado: {texto}"
        assert await _auto_send(session_factory, rico) is False, (
            "escribió auto_send con la recomendación apagada"
        )
        assert espia.metodos == [], f"tocó Telegram: {espia.metodos}"
    finally:
        await _limpiar_lo_nuestro(
            session_factory, chats=[CHAT_SEMILLA], vips_tg=[VIP_LISTO, VIP_LEJOS]
        )
        await app.bot.session.close()
