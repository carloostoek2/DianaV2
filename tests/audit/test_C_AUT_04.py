"""C-AUT-04 — el ajuste de confianza no se cuenta dos veces (y H-2 al apagarlo).

Prueba E2 contra Postgres REAL (copia de la base real en un contenedor
desechable). El turno se produce por el camino real (``business_message`` por el
``dispatcher`` armado con ``build_app``) y la resolución de la dueña también
(botón "Aprobar" / "Corregir" + texto libre). Se asertan filas:
``vip_trust_budget.trust_score`` / ``autonomous_count`` / ``correction_count`` y
``turn_outcome_log``. El único simulado es el modelo de lenguaje externo
(``llm/fake.py``).

Promesa bajo prueba (``audit/contracts/C-AUT-04.md``, AGENTS.md §3 flujo 4.18):
  (5) con ``FEATURE_AUTONOMY_READINESS_ENABLED=true`` la vía sombra
      (``record_autonomous`` en el orquestador y ``record_correction`` en el
      admin) está suprimida y el trust se mueve por UNA sola vía:
      ``record_outcome`` (aprobación +0.05, corrección −0.20). Con la bandera en
      OFF vuelve el doble conteo (aprobación +0.10, corrección −0.40).
  (6) H-2: con readiness ON y ``FEATURE_AUTONOMY_QUALITY_ENABLED=false`` las dos
      vías quedan suprimidas (la sombra por el guard, la de resultado porque el
      servicio de medición no se cablea) y la confianza queda congelada EN
      SILENCIO: ni un aviso, ni un error.

Para que la vía sombra exista de verdad, el turno se clasifica ``fatico``
confiado (``would_autonomous=true`` en ``turn_category_log``) y el borrador
sombra sale ``send`` (evaluación por encima de los mínimos autónomos); la
corrección exige además ``feature_staging_enabled`` (el decremento por
corrección solo dispara si la corrección quedó persistida). La confianza de
partida se siembra en 0.50 para que ningún delta toque el techo ni el piso del
clamp y las cifras sean exactas.
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

from diana.behavior.fake import FixedDelayPolicy
from diana.cognitive.models import Comprehension, EvaluationProfile
from diana.composition import build_app
from diana.config.settings import Settings
from diana.llm.fake import FakeLLM
from diana.telegram.keyboards import encode_callback

OWNER_ID = 999001
BOT_ID = 999002
TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"

# Ids propios (un VIP por escenario; la prueba falla si ya existe).
VIP_ON = 999610101  # readiness ON (via única)
VIP_OFF = 999610102  # readiness OFF (doble conteo)
VIP_H2_ON = 999610103  # H-2 con la medición de calidad encendida
VIP_H2_OFF = 999610104  # H-2 con la medición de calidad apagada

CONFIANZA_INICIAL = 0.5
CATEGORIA = "fatico"

# Texto con sustancia: se clasifica fatico (saludo sin carga) pero NO lo corta el
# atajo de plantilla (no es un saludo puro ni un check-in), así que el pipeline
# completa y hay evaluación + veredicto sombra.
TEXTO_VIP = "Hola Diana, ya estoy en casa tranquila y queria saludarte un rato."
TEXTO_CORREGIDO = "Hola, aqui sigo pendiente de ti. Cuentame como te fue hoy."

EVENTOS_SOSPECHOSOS = ("trust", "outcome", "autonom", "quality")


def _comprehension() -> Comprehension:
    return Comprehension(
        intent="saludar",
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


def _settings(*, readiness: bool, quality: bool) -> Settings:
    return Settings.model_construct(
        telegram_bot_token=SecretStr(TOKEN),
        owner_telegram_id=OWNER_ID,
        database_url=SecretStr(
            "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder"
        ),
        deepseek_api_key="",
        global_mode="supervised",
        feature_autonomy_quality_enabled=quality,
        feature_autonomy_readiness_enabled=readiness,
        feature_autonomy_recommendation_enabled=True,
        feature_trust_budget=True,
        feature_phatic_autonomy=True,
        feature_phatic_auto_send=False,
        feature_staging_enabled=True,
        feature_memory_enabled=False,
        feature_quality_feedback_enabled=False,
        feature_gray_zone_enabled=False,
        feature_autonomous_mode=False,
        feature_sandbox_enabled=False,
        log_level="WARNING",
    )


class SesionEspia:
    """Doble del actuador de Telegram: ningún mensaje sale de la máquina."""

    def __init__(self) -> None:
        self.metodos: list[str] = []

    async def __call__(self, bot: Any, method: Any, timeout: Any = None) -> Any:
        self.metodos.append(type(method).__name__)
        return Message(
            message_id=1000 + len(self.metodos),
            date=datetime(2026, 10, 8, 12, 0, 0),
            chat=Chat(id=int(getattr(method, "chat_id", 0) or 0), type="private"),
            text=getattr(method, "text", None),
        )

    async def close(self) -> None:
        return None


class CapturaAvisos(logging.Handler):
    """Recoge WARNING+ de la aplicación para probar que NO hay aviso."""

    LOGGERS = ("diana.application", "diana.telegram", "diana.composition")

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []
        self._previos: list[tuple[logging.Logger, int]] = []
        for nombre in self.LOGGERS:
            log = logging.getLogger(nombre)
            self._previos.append((log, log.level))
            log.setLevel(logging.WARNING)
            log.addHandler(self)

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def avisos_del_tema(self) -> list[str]:
        return [
            r.getMessage()
            for r in self.records
            if any(k in r.getMessage().lower() for k in EVENTOS_SOSPECHOSOS)
        ]

    def close(self) -> None:
        for log, nivel in self._previos:
            log.removeHandler(self)
            log.setLevel(nivel)
        super().close()


def _update_negocio(vip_tg: int, texto: str, message_id: int) -> Update:
    msg = Message(
        message_id=message_id,
        date=datetime(2026, 10, 8, 12, 0, 0),
        chat=Chat(id=vip_tg, type="private"),
        from_user=User(id=vip_tg, is_bot=False, first_name="Vip"),
        text=texto,
        business_connection_id=f"bc-audit-{vip_tg}",
    )
    return Update(update_id=message_id, business_message=msg)


def _update_callback(data: str, update_id: int) -> Update:
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


def _update_texto_duena(texto: str, update_id: int) -> Update:
    msg = Message(
        message_id=update_id,
        date=datetime(2026, 10, 8, 12, 0, 0),
        chat=Chat(id=OWNER_ID, type="private"),
        from_user=User(id=OWNER_ID, is_bot=False, first_name="Duenia"),
        text=texto,
    )
    return Update(update_id=update_id, message=msg)


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


async def _confianza(session_factory, vip_id: str) -> dict[str, Any]:
    """Fila real del presupuesto de confianza del VIP (una sola categoría)."""
    async with session_factory() as s:
        fila = (
            await s.execute(
                text(
                    "select turn_category, trust_score, autonomous_count, "
                    "correction_count from vip_trust_budget where vip_id = :v"
                ),
                {"v": vip_id},
            )
        ).one_or_none()
    assert fila is not None, "el VIP no tiene fila de confianza"
    return dict(fila._mapping)


async def _ultimo_turno(session_factory, chat_id: int) -> dict[str, Any]:
    async with session_factory() as s:
        fila = (
            await s.execute(
                text(
                    "select id::text as id, status, vip_id::text as vip_id, "
                    "chat_id from turns where chat_id = :c "
                    "order by created_at desc limit 1"
                ),
                {"c": chat_id},
            )
        ).one()
    return dict(fila._mapping)


async def _clasificacion(session_factory, turn_id: str) -> dict[str, Any]:
    async with session_factory() as s:
        fila = (
            await s.execute(
                text(
                    "select category, confidence, would_autonomous "
                    "from turn_category_log where turn_id = :t"
                ),
                {"t": turn_id},
            )
        ).one_or_none()
    assert fila is not None, "el turno no quedó clasificado (sin vía sombra posible)"
    return dict(fila._mapping)


async def _outcome(session_factory, turn_id: str) -> dict[str, Any] | None:
    async with session_factory() as s:
        fila = (
            await s.execute(
                text(
                    "select shadow_verdict, shadow_reason, owner_outcome, draft_score, "
                    "sent_score, vip_signal, correction_severity "
                    "from turn_outcome_log where turn_id = :t"
                ),
                {"t": turn_id},
            )
        ).one_or_none()
    return dict(fila._mapping) if fila is not None else None


async def _sembrar_confianza(session_factory, vip_id: str) -> None:
    async with session_factory() as s:
        await s.execute(
            text(
                "insert into vip_trust_budget (vip_id, turn_category, trust_score) "
                "values (:vip, :cat, :score) "
                "on conflict (vip_id, turn_category) do update set trust_score = :score, "
                "autonomous_count = 0, correction_count = 0, last_correction_at = null"
            ),
            {"vip": vip_id, "cat": CATEGORIA, "score": CONFIANZA_INICIAL},
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


async def _escenario_completo(
    *,
    settings: Settings,
    vip_tg: int,
    engine,
    session_factory,
) -> dict[str, Any]:
    """Un turno aprobado y otro corregido, por el camino real de Telegram.

    Devuelve las mediciones reales (confianza y ledger) de cada paso.
    """
    bot = Bot(token=TOKEN)
    bot.session = SesionEspia()  # type: ignore[assignment]
    app = build_app(
        settings,
        bot=bot,
        llm=FakeLLM(
            structured_responses=[
                _comprehension(),
                _evaluacion(),
                _comprehension(),
                _evaluacion(),
            ],
            text_responses=["Claro, aqui seguimos con calma.", "Con gusto, aqui ando."],
        ),
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    medidas: dict[str, Any] = {}
    try:
        await _assert_vip_nuevo(session_factory, vip_tg)
        await app.vips.add(vip_tg, display_name=f"Confianza {vip_tg}")
        vip_id = await _vip_id(session_factory, vip_tg)
        await _sembrar_confianza(session_factory, vip_id)
        medidas["vip_id"] = vip_id
        medidas["antes"] = await _confianza(session_factory, vip_id)

        # --- turno 1: la dueña aprueba -----------------------------------
        await app.dispatcher.feed_update(
            bot, _update_negocio(vip_tg, TEXTO_VIP, message_id=11)
        )
        turno1 = await _ultimo_turno(session_factory, vip_tg)
        assert turno1["status"] == "pending_approval", f"turno 1: {turno1}"
        clas1 = await _clasificacion(session_factory, turno1["id"])
        assert clas1["category"] == CATEGORIA, f"categoría inesperada: {clas1}"
        assert clas1["would_autonomous"] is True, (
            f"el turno no alimenta la vía sombra: {clas1}"
        )
        sombra1 = await _outcome(session_factory, turno1["id"])
        medidas["turno1_id"] = turno1["id"]
        medidas["sombra1_antes"] = sombra1
        await app.dispatcher.feed_update(
            bot,
            _update_callback(encode_callback("approve", turno1["id"]), update_id=901),
        )
        turno1 = await _ultimo_turno(session_factory, vip_tg)
        assert turno1["status"] == "delivered", f"turno 1 no se entregó: {turno1}"
        medidas["tras_aprobar"] = await _confianza(session_factory, vip_id)
        medidas["sombra1"] = await _outcome(session_factory, turno1["id"])

        # --- turno 2: la dueña corrige ------------------------------------
        await app.dispatcher.feed_update(
            bot, _update_negocio(vip_tg, TEXTO_VIP, message_id=12)
        )
        turno2 = await _ultimo_turno(session_factory, vip_tg)
        assert turno2["status"] == "pending_approval", f"turno 2: {turno2}"
        medidas["turno2_id"] = turno2["id"]
        # El botón "Corregir" abre la sesión y el texto libre la resuelve.
        await app.dispatcher.feed_update(
            bot,
            _update_callback(encode_callback("correct", turno2["id"]), update_id=902),
        )
        await app.dispatcher.feed_update(
            bot, _update_texto_duena(TEXTO_CORREGIDO, update_id=950)
        )
        turno2 = await _ultimo_turno(session_factory, vip_tg)
        assert turno2["status"] == "delivered", f"turno 2 no se entregó: {turno2}"
        medidas["tras_corregir"] = await _confianza(session_factory, vip_id)
        medidas["sombra2"] = await _outcome(session_factory, turno2["id"])
        medidas["orchestrator_outcome_none"] = app.orchestrator._outcome_log is None  # noqa: SLF001
        medidas["admin_outcome_none"] = app.admin._outcome is None  # noqa: SLF001
        return medidas
    finally:
        await bot.session.close()


def _huella(fila: dict[str, Any]) -> tuple[float, int, int]:
    """(confianza redondeada, autónomos, correcciones) de una fila real."""
    return (
        round(float(fila["trust_score"]), 6),
        int(fila["autonomous_count"]),
        int(fila["correction_count"]),
    )


# ---------------------------------------------------------------------------
# (5) la vía única de confianza, con la bandera en los dos estados
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("readiness", "vip_tg", "esperado_aprobar", "esperado_corregir"),
    [
        (True, VIP_ON, (0.55, 1, 0), (0.35, 1, 1)),
        (False, VIP_OFF, (0.60, 2, 0), (0.25, 3, 2)),
    ],
    ids=["readiness_on", "readiness_off"],
)
async def test_5_una_sola_via_de_confianza(
    engine,
    session_factory,
    alembic_applied,
    readiness: bool,
    vip_tg: int,
    esperado_aprobar: tuple[float, int, int],
    esperado_corregir: tuple[float, int, int],
) -> None:
    """ON: aprueba +0.05 y corrige −0.20 UNA vez. OFF: el doble conteo.

    Se mide la confianza real antes/después de cada resolución de la dueña.
    Los contadores (``autonomous_count`` / ``correction_count``) muestran
    cuántos eventos escribieron: con readiness ON la sombra no aporta ninguno.
    """
    medidas = await _escenario_completo(
        settings=_settings(readiness=readiness, quality=True),
        vip_tg=vip_tg,
        engine=engine,
        session_factory=session_factory,
    )
    try:
        assert _huella(medidas["antes"]) == (CONFIANZA_INICIAL, 0, 0)

        tras_aprobar = medidas["tras_aprobar"]
        assert _huella(tras_aprobar) == esperado_aprobar, (
            f"readiness={readiness}: la aprobación no dejó la huella esperada: "
            f"{_huella(tras_aprobar)} (esperado {esperado_aprobar})"
        )
        # El ledger real confirma que el evento de resultado existió.
        assert medidas["sombra1"]["shadow_verdict"] == "send", (
            f"el veredicto sombra no era 'send' (no habría acierto): "
            f"{medidas['sombra1']}"
        )
        assert medidas["sombra1"]["owner_outcome"] == "approved_as_is", (
            f"la resolución de la dueña no quedó en el ledger: {medidas['sombra1']}"
        )

        tras_corregir = medidas["tras_corregir"]
        assert _huella(tras_corregir) == esperado_corregir, (
            f"readiness={readiness}: la corrección no dejó la huella esperada: "
            f"{_huella(tras_corregir)} (esperado {esperado_corregir})"
        )
        assert medidas["sombra2"]["owner_outcome"] == "corrected"
        assert medidas["sombra2"]["correction_severity"] == "moderate"
        # La reacción del VIP (C3) no aporta un evento extra en este escenario:
        # si el hook la clasificó, fue sin delta (neutral/silencio).
        assert medidas["sombra1"]["vip_signal"] in (None, "neutral", "silence"), (
            f"la señal del VIP movería la confianza y arruinaría la medición exacta: "
            f"{medidas['sombra1']['vip_signal']}"
        )
    finally:
        await _limpiar_lo_nuestro(
            session_factory, chats=[vip_tg], vips_tg=[vip_tg]
        )


# ---------------------------------------------------------------------------
# (6) H-2 — medición apagada + readiness encendido = confianza congelada
# ---------------------------------------------------------------------------
@pytest.mark.db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quality", "vip_tg", "esperado_aprobar", "esperado_corregir"),
    [
        (True, VIP_H2_ON, (0.55, 1, 0), (0.35, 1, 1)),
        (False, VIP_H2_OFF, (0.50, 0, 0), (0.50, 0, 0)),
    ],
    ids=["quality_on", "quality_off"],
)
async def test_6_h2_readiness_on_con_quality_off_congela_la_confianza(
    engine,
    session_factory,
    alembic_applied,
    quality: bool,
    vip_tg: int,
    esperado_aprobar: tuple[float, int, int],
    esperado_corregir: tuple[float, int, int],
) -> None:
    """H-2: con readiness ON y quality OFF la confianza no se mueve y nadie avisa.

    Con quality ON la aprobación deja +0.05 y la corrección −0.20. Con quality
    OFF (readiness sigue ON) el turno se resuelve igual — la dueña ve el flujo
    normal — pero la fila de confianza queda idéntica: la vía sombra está
    suprimida por el guard y la vía de resultado no está cableada, así que no
    corre ninguna. La comprobación de "en silencio" es que no aparece ningún
    WARNING/ERROR de la aplicación sobre confianza/outcome/autonomía.
    """
    captura = CapturaAvisos()
    try:
        medidas = await _escenario_completo(
            settings=_settings(readiness=True, quality=quality),
            vip_tg=vip_tg,
            engine=engine,
            session_factory=session_factory,
        )
        tras_aprobar = medidas["tras_aprobar"]
        tras_corregir = medidas["tras_corregir"]
        assert _huella(tras_aprobar) == esperado_aprobar, (
            f"quality={quality}: tras aprobar: {_huella(tras_aprobar)} "
            f"(esperado {esperado_aprobar})"
        )
        assert _huella(tras_corregir) == esperado_corregir, (
            f"quality={quality}: tras corregir: {_huella(tras_corregir)} "
            f"(esperado {esperado_corregir})"
        )

        if quality:
            assert medidas["sombra1"] is not None, "con quality ON falta el ledger"
            assert medidas["orchestrator_outcome_none"] is False
            assert medidas["admin_outcome_none"] is False
        else:
            # La medición no está cableada: no hay fila de ledger, ni aviso.
            assert medidas["sombra1"] is None, (
                f"con quality OFF igual se escribió el ledger: {medidas['sombra1']}"
            )
            assert medidas["sombra2"] is None
            # Ni el orquestador ni el admin reciben el servicio de medición
            # (por eso `record_outcome` no puede correr): la supresión de la vía
            # sombra y la ausencia de la vía de resultado se combinan sin guarda.
            assert medidas["orchestrator_outcome_none"] is True, (
                "el orquestador SÍ recibió el servicio de medición"
            )
            assert medidas["admin_outcome_none"] is True, (
                "el admin SÍ recibió el servicio de medición"
            )
            assert captura.avisos_del_tema() == [], (
                "el congelamiento avisó algo: "
                f"{captura.avisos_del_tema()}"
            )
    finally:
        captura.close()
        await _limpiar_lo_nuestro(session_factory, chats=[vip_tg], vips_tg=[vip_tg])
