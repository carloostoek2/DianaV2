"""C-PII-01 — Los datos personales del texto no viajan al proveedor y vuelven intactos.

Prueba E2 sobre Postgres real (copia de la base real en un contenedor
desechable, ver ``audit/ENTORNO.md``). Se entra por ``build_app`` con las
banderas de cada escenario; el cableado, el proveedor ``DeepSeekProvider``, el
enmascarado (``pii_masker``), el pipeline cognitivo, los repositorios y el
orquestador son los REALES.

Lo único que se sustituye es el transporte HTTP del proveedor del modelo
(``httpx.MockTransport``): ``validate_llm_base_url`` rechaza loopback, así que
un servidor local no sirve; en su lugar se captura el CUERPO EXACTO que el
proveedor real armaría y se le devuelve una respuesta sintética. Ningún
componente prometido está simulado y ninguna aserción dice "se llamó a X":
todas miran el cuerpo HTTP capturado o el estado persistido.

Datos: TODOS sintéticos y propios de esta prueba (correo, teléfono, tarjeta y
enlace inventados). Los chats son ids propios en el rango 9992001xx; cada
inserción y cada aserción se acota a ellos y se limpia al final, porque la
copia trae datos reales de los VIP.

Casos que registran un HUECO (comportamiento real que contradice la promesa)
lo dicen en su docstring; no se corrige código de producción aquí.
"""

from __future__ import annotations

import contextlib
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from aiogram import Bot
from aiogram.types import Chat, Message, PhotoSize, Update, User
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import text

import diana.llm.deepseek as deepseek_module
import diana.llm.gemini_vision as gemini_vision_module
from diana.behavior.fake import FixedDelayPolicy
from diana.composition import build_app
from diana.config.settings import Settings

pytestmark = pytest.mark.db

TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"
OWNER_ID = 999001
BUSINESS_CONNECTION_ID = "bc-c-pii-01-audit"

# Datos personales SINTÉTICOS de esta prueba (inventados, nunca de un VIP).
EMAIL = "vip.auditoria@correo-privado.test"
PHONE = "55 9876 5432"
CARD = "4111 1111 1111 1111"
URL = "https://ejemplo-privado.test/oferta"

# Chats propios de la auditoría.
CHAT_FLUJO = 999200101
CHAT_RESTAURACION = 999200102
CHAT_BANDERA_OFF = 999200103
CHAT_HOT_SWAP = 999200104
CHAT_MEMORIA = 999200105
CHAT_SINTESIS = 999200106
CHAT_VISION = 999200107

CERO_384 = "[" + ",".join(["0"] * 384) + "]"


# ---------------------------------------------------------------------------
# Captura del borde HTTP del proveedor de texto (el ÚNICO borde simulado)
# ---------------------------------------------------------------------------


def _comprehension_json() -> str:
    return json.dumps(
        {
            "intent": "consultar",
            # El modelo "repite" el marcador en un campo estructurado: sirve
            # para medir qué queda en ``raw_llm_output`` tras la restauración
            # (caso 9: el contrato pide que la traza muestre los originales).
            "topics": ["contacto", "[correo]"],
            "emotion": "neutral",
            "urgency": "baja",
            "risk": "bajo",
            "needs_memory": False,
            "needs_policy": False,
            "needs_schedule": False,
            "needs_examples": False,
            "needs_history": False,
            "needs_context": False,
            "needs_persona_facts": False,
            "needs_voice_patterns": False,
            "needs_profile": False,
        }
    )


def _evaluation_json() -> str:
    return json.dumps(
        {
            "naturalness": 0.9,
            "precision": 0.9,
            "doctrine": 0.9,
            "consistency": 0.9,
            "safety": 0.95,
            "coverage": 0.9,
            "empathy": 0.9,
        }
    )


def _structured_response(payload: dict[str, Any]) -> str:
    """Respuesta sintética según el esquema pedido (nunca datos del VIP)."""
    blob = json.dumps(payload.get("messages", []), ensure_ascii=False)
    if "stable_traits" in blob:
        return json.dumps(
            {
                "stable_traits": {"gustos": ["café"]},
                "recent_trend": {"tema": "contacto"},
                "sensitivities": [],
                "changes_summary": "perfil de auditoría",
                "confidence": 0.9,
            }
        )
    if "hechos" in blob:
        return json.dumps({"hechos": []})
    if "naturalness" in blob:
        return _evaluation_json()
    if "intent" in blob or "topics" in blob:
        return _comprehension_json()
    # Un objeto vacío haría fallar el pipeline por validación y ocultaría el
    # motivo real; fallar aquí es más honesto.
    raise AssertionError(f"esquema estructurado no reconocido: {blob[:400]}")


class _DeepSeekCapture:
    """Cuerpos HTTP reales que el ``DeepSeekProvider`` habría enviado.

    Si el payload trae ``response_format`` es una llamada estructurada
    (analista, evaluador, extracción, síntesis) y se responde con el JSON del
    esquema; si no, es generación de texto libre y se responde ``draft``.
    """

    def __init__(self, *, draft: str = "Hola, todo bien.") -> None:
        self.draft = draft
        self.requests: list[dict[str, Any]] = []

    @property
    def bodies(self) -> list[str]:
        return [json.dumps(p, ensure_ascii=False) for p in self.requests]

    def response_for(self, payload: dict[str, Any]) -> str:
        if "response_format" not in payload:
            return self.draft
        return _structured_response(payload)

    def handle(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        self.requests.append(payload)
        content = self.response_for(payload)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": content}, "finish_reason": "stop"}
                ]
            },
        )


def _install_deepseek_transport(
    monkeypatch: pytest.MonkeyPatch, capture: _DeepSeekCapture
) -> list[httpx.AsyncClient]:
    """Sustituye SOLO la creación del cliente HTTP dentro de ``deepseek``."""
    created: list[httpx.AsyncClient] = []

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(capture.handle), **kwargs
        )
        created.append(client)
        return client

    monkeypatch.setattr(
        deepseek_module, "httpx", SimpleNamespace(AsyncClient=_factory)
    )
    return created


def _payloads_text(capture: _DeepSeekCapture) -> str:
    return "\n".join(capture.bodies)


def _structured_payloads(capture: _DeepSeekCapture) -> list[dict[str, Any]]:
    return [p for p in capture.requests if "response_format" in p]


def _text_payloads(capture: _DeepSeekCapture) -> list[dict[str, Any]]:
    return [p for p in capture.requests if "response_format" not in p]


def _payload_of(capture: _DeepSeekCapture, *, schema_key: str) -> dict[str, Any]:
    for payload in _structured_payloads(capture):
        blob = json.dumps(payload.get("messages", []), ensure_ascii=False)
        if schema_key in blob:
            return payload
    raise AssertionError(
        f"no hubo llamada estructurada con {schema_key!r}; "
        f"capturadas={len(capture.requests)}"
    )


# ---------------------------------------------------------------------------
# Bot y updates (la salida a Telegram no sale de la máquina)
# ---------------------------------------------------------------------------


class _SpyBotSession:
    """Doble del transporte de Telegram; registra el método, nunca hace red."""

    def __init__(self) -> None:
        self.methods: list[str] = []

    async def __call__(self, bot: Any, method: Any, timeout: Any = None) -> Any:
        self.methods.append(type(method).__name__)
        return SimpleNamespace(message_id=len(self.methods))

    async def close(self) -> None:
        return None


def _bot() -> Bot:
    bot = Bot(token=TOKEN)
    bot.session = _SpyBotSession()  # type: ignore[assignment]
    return bot


def _text_update(chat_id: int, message_id: int, text: str) -> Update:
    message = Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=chat_id, is_bot=False, first_name="Vip"),
        text=text,
        business_connection_id=BUSINESS_CONNECTION_ID,
    )
    return Update(update_id=chat_id, business_message=message)


def _photo_update(chat_id: int, message_id: int, caption: str) -> Update:
    message = Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=chat_id, is_bot=False, first_name="Vip"),
        photo=[
            PhotoSize(
                file_id="foto-c-pii-01-chica",
                file_unique_id="u-chica",
                width=90,
                height=60,
            ),
            PhotoSize(
                file_id="foto-c-pii-01-grande",
                file_unique_id="u-grande",
                width=320,
                height=240,
            ),
        ],
        caption=caption,
        business_connection_id=BUSINESS_CONNECTION_ID,
    )
    return Update(update_id=chat_id, business_message=message)


# ---------------------------------------------------------------------------
# Settings, app real por escenario y acceso al proveedor cableado
# ---------------------------------------------------------------------------


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "telegram_bot_token": SecretStr(TOKEN),
        "owner_telegram_id": OWNER_ID,
        "database_url": SecretStr(
            "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder"
        ),
        # Clave no vacía → composition construye el DeepSeekProvider REAL
        # (con la bandera de PII tal como la pase el escenario) y lo envuelve
        # en HotSwapLLMProvider, igual que en producción.
        "deepseek_api_key": SecretStr("clave-falsa-auditoria-c-pii-01"),
        "global_mode": "supervised",
        "log_level": "ERROR",
    }
    base.update(overrides)
    return Settings.model_construct(**base)


@contextlib.asynccontextmanager
async def _app(
    engine: Any,
    session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    draft: str = "Hola, todo bien.",
    **flag_overrides: Any,
):
    """Arma la app REAL por ``build_app`` y devuelve (app, captura)."""
    capture = _DeepSeekCapture(draft=draft)
    clients = _install_deepseek_transport(monkeypatch, capture)
    bot = _bot()
    app = build_app(
        _settings(**flag_overrides),
        bot=bot,
        llm=None,
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    try:
        yield app, capture
    finally:
        for client in clients:
            with contextlib.suppress(Exception):
                await client.aclose()
        with contextlib.suppress(Exception):
            await bot.session.close()


def _provider(app: Any) -> Any:
    """El proveedor real cableado por composition (HotSwap → DeepSeek)."""
    return app.orchestrator._director._analyst._llm


# ---------------------------------------------------------------------------
# Siembra, lectura y limpieza acotadas a los chats propios
# ---------------------------------------------------------------------------


async def _seed_vip(session_factory: Any, chat_id: int) -> str:
    # Idempotente: si una corrida anterior dejó filas de este chat (p. ej.
    # tras un corte), se limpian antes de sembrar. Nunca toca otros chats.
    await _delete_chat_data(session_factory, chat_id)
    async with session_factory() as session:
        vip_id = (
            await session.execute(
                text(
                    "insert into vips (telegram_user_id, display_name) "
                    "values (:t, 'Prueba PII C-PII-01') returning id"
                ),
                {"t": chat_id},
            )
        ).scalar_one()
        await session.commit()
    return str(vip_id)


async def _read_approval(session_factory: Any, chat_id: int) -> dict[str, Any] | None:
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "select draft_text, status, turn_id from pending_approvals "
                    "where chat_id = :c order by created_at desc limit 1"
                ),
                {"c": chat_id},
            )
        ).mappings().first()
    return dict(row) if row is not None else None


async def _read_trace(session_factory: Any, chat_id: int) -> dict[str, Any] | None:
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "select prompt_text, generated_text, comprehension, evaluation, "
                    "decision from pipeline_traces "
                    "where chat_id = :c order by created_at desc limit 1"
                ),
                {"c": chat_id},
            )
        ).mappings().first()
    return dict(row) if row is not None else None


async def _delete_chat_data(session_factory: Any, chat_id: int) -> None:
    """Limpia SOLO las filas de este chat (la copia trae datos reales)."""
    async with session_factory() as session:
        for statement in (
            "delete from pending_deliveries where chat_id = :c",
            "delete from escalation_events where turn_id in "
            "(select id from turns where chat_id = :c)",
            "delete from pending_approvals where chat_id = :c",
            "delete from pipeline_traces where chat_id = :c",
            "delete from message_history where chat_id = :c",
            "delete from turn_category_log where chat_id = :c",
            "delete from emotional_signal_log where turn_id in "
            "(select id from turns where chat_id = :c)",
            "delete from turn_outcome_log where turn_id in "
            "(select id from turns where chat_id = :c)",
            "delete from turns where chat_id = :c",
            "delete from memories where vip_id in "
            "(select id from vips where telegram_user_id = :c)",
            "delete from vip_profile_history where vip_id in "
            "(select id from vips where telegram_user_id = :c)",
            "delete from vip_profile where vip_id in "
            "(select id from vips where telegram_user_id = :c)",
            "delete from profile_synthesis_queue where vip_id in "
            "(select id from vips where telegram_user_id = :c)",
            "delete from backfill_queue where vip_id in "
            "(select id from vips where telegram_user_id = :c)",
            "delete from staging_candidates where vip_id in "
            "(select id from vips where telegram_user_id = :c)",
            "delete from vips where telegram_user_id = :c",
        ):
            with contextlib.suppress(Exception):
                await session.execute(text(statement), {"c": chat_id})
        await session.commit()


@pytest.fixture
async def chats(session_factory: Any):
    registrados: list[int] = []
    yield registrados
    for chat_id in registrados:
        await _delete_chat_data(session_factory, chat_id)


# ---------------------------------------------------------------------------
# Config runtime ``llm``: se neutraliza para que el escenario sea determinista
# ---------------------------------------------------------------------------


async def _read_llm_config(session_factory: Any) -> Any:
    async with session_factory() as session:
        row = (
            await session.execute(
                text("select value from system_config where key = 'llm'")
            )
        ).first()
    return row[0] if row is not None else None


async def _write_llm_config(session_factory: Any, value: Any) -> None:
    async with session_factory() as session:
        if value is None:
            await session.execute(
                text("delete from system_config where key = 'llm'")
            )
        else:
            await session.execute(
                text(
                    "insert into system_config (key, value) "
                    "values ('llm', cast(:v as jsonb)) "
                    "on conflict (key) do update set value = excluded.value, "
                    "updated_at = now()"
                ),
                {"v": json.dumps(value)},
            )
        await session.commit()


async def _expire_hot_swap_cache(app: Any) -> None:
    """Expira la caché de configuración del wrapper (TTL 30 s) sin tocar código.

    El wrapper real se conserva; solo se le pide releer ``system_config`` en la
    siguiente llamada para que la prueba no espere el TTL.
    """
    provider = _provider(app)
    provider._cache = None  # noqa: SLF001 — expiración explícita del TTL
    provider._cached_at = None  # noqa: SLF001


@pytest.fixture(autouse=True)
async def llm_sin_override(session_factory: Any):
    """Neutraliza ``system_config['llm']`` y lo restaura al terminar.

    La copia real puede traer un override del menú (modelo/base_url): sin esto
    el escenario de bandera OFF no sería determinista. Se restaura el valor
    original aunque la prueba falle.
    """
    original = await _read_llm_config(session_factory)
    await _write_llm_config(session_factory, None)
    yield
    await _write_llm_config(session_factory, original)


# ---------------------------------------------------------------------------
# 1. Flujo de punta a punta: máscara en el HTTP, originales en cola y traza
# ---------------------------------------------------------------------------


@dataclass
class _TurnOutcome:
    capture: _DeepSeekCapture
    approval: dict[str, Any] | None
    trace: dict[str, Any] | None
    bot_methods: list[str] = field(default_factory=list)


@contextlib.asynccontextmanager
async def _run_text_turn(
    engine: Any,
    session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    chat_id: int,
    text_: str,
    draft: str,
    **flags: Any,
):
    await _seed_vip(session_factory, chat_id)
    async with _app(engine, session_factory, monkeypatch, draft=draft, **flags) as (
        app,
        capture,
    ):
        bot = app.bot
        await app.dispatcher.feed_update(bot, _text_update(chat_id, 1, text_))
        approval = await _read_approval(session_factory, chat_id)
        trace = await _read_trace(session_factory, chat_id)
        yield _TurnOutcome(
            capture=capture,
            approval=approval,
            trace=trace,
            bot_methods=list(getattr(bot.session, "methods", [])),
        )


DRAFT_ECO = (
    "Listo, te escribo a [correo] o al [telefono]. Puedo cobrar con [tarjeta] "
    "y te paso el detalle en [enlace]."
)


async def test_flujo_completo_enmascara_en_http_y_restaura_en_cola_y_traza(
    engine, session_factory, monkeypatch, chats
) -> None:
    """Efecto prometido de punta a punta, con todos los llamadores del turno."""
    chats.append(CHAT_FLUJO)
    async with _run_text_turn(
        engine,
        session_factory,
        monkeypatch,
        chat_id=CHAT_FLUJO,
        text_=(
            f"Holaa, escríbeme a {EMAIL} o al {PHONE}. "
            f"Mi tarjeta es {CARD}, y el enlace {URL}"
        ),
        draft=DRAFT_ECO,
        feature_pii_masking_enabled=True,
    ) as outcome:
        capture = outcome.capture
        # Llamadores reales del pipeline: analista y evaluador (structured) y
        # generador (texto libre).
        analista = _payload_of(capture, schema_key="intent")
        evaluador = _payload_of(capture, schema_key="naturalness")
        generadores = _text_payloads(capture)
        assert generadores, "no hubo llamada de texto libre del generador"

        # 1) En el HTTP salen los marcadores y NO los originales.
        for nombre, payload in (
            ("analista", analista),
            ("evaluador", evaluador),
            ("generador", generadores[0]),
        ):
            cuerpo = json.dumps(payload, ensure_ascii=False)
            for original in (EMAIL, PHONE, CARD, URL):
                assert original not in cuerpo, (
                    f"el dato original {original!r} viajó al proveedor en {nombre}"
                )
        cuerpo_analista = json.dumps(analista, ensure_ascii=False)
        for marcador in ("[correo]", "[telefono]", "[tarjeta]", "[enlace]"):
            assert marcador in cuerpo_analista, (
                f"falta {marcador!r} en la petición del analista"
            )
        # El evaluador recibe el borrador ya restaurado y el texto del turno;
        # el generador recibe el prompt con el texto del turno: ambos vuelven
        # a enmascarar antes de salir.
        for nombre, payload in (
            ("evaluador", evaluador),
            ("generador", generadores[0]),
        ):
            cuerpo = json.dumps(payload, ensure_ascii=False)
            for marcador in (
                "[correo]",
                "[telefono]",
                "[tarjeta]",
                "[enlace]",
            ):
                assert marcador in cuerpo, (
                    f"falta {marcador!r} en la petición del {nombre}"
                )

        # 2) El borrador que llega a la cola de la dueña tiene los ORIGINALES.
        assert outcome.approval is not None, "el turno no llegó a la cola"
        assert outcome.approval["status"] == "waiting"
        draft = outcome.approval["draft_text"]
        for original in (EMAIL, PHONE, CARD, URL):
            assert original in draft, (
                f"el borrador no restauró {original!r}: {draft!r}"
            )
        assert "[correo]" not in draft and "[tarjeta]" not in draft

        # 3) La traza persistida también tiene el borrador restaurado y el
        #    prompt ORIGINAL (decisión de diseño del contrato, caso 9).
        assert outcome.trace is not None, "no se persistió la traza"
        generated = outcome.trace["generated_text"]
        prompt = outcome.trace["prompt_text"]
        for original in (EMAIL, PHONE, CARD, URL):
            assert original in generated, (
                f"pipeline_traces.generated_text no restauró {original!r}: "
                f"{generated!r}"
            )
            assert original in prompt, (
                f"pipeline_traces.prompt_text no guarda el original {original!r}"
            )
        # ``raw_llm_output`` también queda RESTAURADO en la base (decisión de
        # diseño del contrato; el costo en reposo está en el punto ciego 5).
        comprension = json.dumps(
            outcome.trace["comprehension"], ensure_ascii=False
        )
        assert EMAIL in comprension, (
            "se esperaba el correo restaurado en comprehension.raw_llm_output"
        )


# ---------------------------------------------------------------------------
# 2. Tarjeta seguida de otro grupo: el caso real sale EN CLARO (hueco)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("4111 1111 1111 1111 12/27", "4111 1111 1111 1111 12/27"),
        ("4111 1111 1111 1111 123", "4111 1111 1111 1111 123"),
        ("4111111111111111 12/27", "4111111111111111 12/27"),
    ],
    ids=["tarjeta-caducidad", "tarjeta-cvv", "contigua-caducidad"],
)
async def test_tarjeta_seguida_de_otro_grupo_viaja_en_claro(
    engine, session_factory, monkeypatch, texto, esperado
) -> None:
    """HUECO (ficha, punto ciego 1): tarjeta + caducidad/CVV sale sin enmascarar.

    El regex acepta 13–19 dígitos y el Luhn se evalúa sobre el match completo;
    ``re.sub`` no reintenta una corrida más corta, así que la tarjeta real
    viaja en claro al proveedor. Se registra el hecho; no se corrige.
    """
    async with _app(
        engine, session_factory, monkeypatch, feature_pii_masking_enabled=True
    ) as (app, capture):
        await _provider(app).generate(
            [{"role": "user", "content": texto}], max_tokens=64
        )
        body = capture.requests[-1]["messages"][-1]["content"]
        assert body == esperado, f"cuerpo HTTP inesperado: {body!r}"
        assert "[tarjeta]" not in body


# ---------------------------------------------------------------------------
# 3. Separadores no cubiertos → EN CLARO (hueco)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("4111 1111 1111 1111", "4111 1111 1111 1111"),
        ("4111\n1111 1111 1111", "4111\n1111 1111 1111"),
        ("4111.1111.1111.1111", "4111.1111.1111.1111"),
    ],
    ids=["espacio-duro", "salto-de-linea", "puntos"],
)
async def test_separadores_no_cubiertos_viajan_en_claro(
    engine, session_factory, monkeypatch, texto, esperado
) -> None:
    """HUECO (ficha, punto ciego 2): NBSP, salto de línea y puntos no se enmascaran.

    El patrón de tarjeta solo admite espacio ASCII y guion. Se registra qué
    sale realmente en el cuerpo HTTP.
    """
    async with _app(
        engine, session_factory, monkeypatch, feature_pii_masking_enabled=True
    ) as (app, capture):
        await _provider(app).generate(
            [{"role": "user", "content": texto}], max_tokens=64
        )
        body = capture.requests[-1]["messages"][-1]["content"]
        assert body == esperado, f"cuerpo HTTP inesperado: {body!r}"
        assert "[tarjeta]" not in body and "[telefono]" not in body


# ---------------------------------------------------------------------------
# 4. Tarjetas que SÍ se enmascaran (efecto esperado)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto",
    [
        "4111111111111111",
        "4111 1111 1111 1111",
        "378282246310005",
        "3782 822463 10005",
    ],
    ids=["visa-contigua", "visa-agrupada", "amex-contigua", "amex-4-6-5"],
)
async def test_tarjetas_validas_se_enmascaran(
    engine, session_factory, monkeypatch, texto
) -> None:
    """Efecto prometido: las tarjetas que pasan Luhn no salen del servidor."""
    async with _app(
        engine, session_factory, monkeypatch, feature_pii_masking_enabled=True
    ) as (app, capture):
        await _provider(app).generate(
            [{"role": "user", "content": texto}], max_tokens=64
        )
        body = capture.requests[-1]["messages"][-1]["content"]
        assert body == "[tarjeta]", f"cuerpo HTTP inesperado: {body!r}"


async def test_diez6_digitos_que_fallan_luhn_no_se_marcan_como_tarjeta(
    engine, session_factory, monkeypatch
) -> None:
    """Comportamiento documentado: sin Luhn válido no se marca como tarjeta."""
    async with _app(
        engine, session_factory, monkeypatch, feature_pii_masking_enabled=True
    ) as (app, capture):
        await _provider(app).generate(
            [{"role": "user", "content": "4111111111111112"}], max_tokens=64
        )
        body = capture.requests[-1]["messages"][-1]["content"]
        assert body == "4111111111111112"
        assert "[tarjeta]" not in body


# ---------------------------------------------------------------------------
# 5. Restauración: solo el marcador literal (hueco)
# ---------------------------------------------------------------------------


async def test_restauracion_solo_reconoce_el_marcador_literal(
    engine, session_factory, monkeypatch, chats
) -> None:
    """HUECO (ficha, punto ciego 11): marcadores deformados llegan al VIP.

    El modelo repite ``[correo]`` (se restaura, incluso dos veces) pero
    ``[CORREO]`` y ``[correo ]`` NO están en el mapping y llegan visibles al
    borrador que ve la dueña (y al VIP si se aprueba).
    """
    chats.append(CHAT_RESTAURACION)
    draft = (
        "Te escribo a [correo] y otra vez a [correo]. "
        "Ojo: [CORREO] y [correo ] quedan como están."
    )
    async with _run_text_turn(
        engine,
        session_factory,
        monkeypatch,
        chat_id=CHAT_RESTAURACION,
        text_=f"mi correo es {EMAIL}",
        draft=draft,
        feature_pii_masking_enabled=True,
    ) as outcome:
        assert outcome.approval is not None
        persistido = outcome.approval["draft_text"]
        # Dos apariciones del marcador literal → dos originales restaurados.
        assert persistido.count(EMAIL) == 2, (
            f"no se restauró dos veces: {persistido!r}"
        )
        # Los deformados NO se restauran: el marcador visible llega al VIP.
        assert "[CORREO]" in persistido
        assert "[correo ]" in persistido


# ---------------------------------------------------------------------------
# 6. Matriz de bandera: OFF manda el texto en claro
# ---------------------------------------------------------------------------


async def test_bandera_off_manda_el_texto_en_claro(
    engine, session_factory, monkeypatch, chats
) -> None:
    """Con ``FEATURE_PII_MASKING_ENABLED=false`` el texto viaja tal cual."""
    chats.append(CHAT_BANDERA_OFF)
    async with _run_text_turn(
        engine,
        session_factory,
        monkeypatch,
        chat_id=CHAT_BANDERA_OFF,
        text_=f"escríbeme a {EMAIL} o al {PHONE}, tarjeta {CARD}, link {URL}",
        draft="Hola, todo bien.",
        feature_pii_masking_enabled=False,
    ) as outcome:
        capture = outcome.capture
        assert capture.requests, "el pipeline no llegó al proveedor"
        # Solo el contenido de los mensajes USER. Las palabras del VIP tienen
        # que viajar SIN sustituir; el system del generador menciona los
        # marcadores como vocabulario de la regla de pago y el modelo puede
        # repetirlos, y eso no es texto del VIP.
        contenido_usuario = "\n".join(
            mensaje.get("content", "")
            for payload in capture.requests
            for mensaje in payload.get("messages", [])
            if mensaje.get("role") == "user" and isinstance(mensaje.get("content"), str)
        )
        for original in (EMAIL, PHONE, CARD, URL):
            assert original in contenido_usuario, (
                f"con la bandera OFF el original {original!r} no viajó"
            )
        for frase_enmascarada in (
            "escríbeme a [correo]",
            "al [telefono]",
            "tarjeta [tarjeta]",
            "link [enlace]",
        ):
            assert frase_enmascarada not in contenido_usuario
        assert outcome.approval is not None


async def test_cambio_de_modelo_en_caliente_reenciende_el_enmascarado_con_bandera_off(
    engine, session_factory, monkeypatch, chats
) -> None:
    """HUECO (ficha, punto ciego 4): el swap fija ``pii_masking=True``.

    Con la bandera OFF, el proveedor base manda el texto en claro; en cuanto
    la dueña cambia el modelo (``system_config['llm']``), ``hot_swap.py`` crea
    el reemplazo con ``pii_masking=True`` y el texto vuelve a enmascararse.
    """
    chats.append(CHAT_HOT_SWAP)
    await _seed_vip(session_factory, CHAT_HOT_SWAP)
    async with _app(
        engine, session_factory, monkeypatch, feature_pii_masking_enabled=False
    ) as (app, capture):
        provider = _provider(app)
        await _expire_hot_swap_cache(app)
        await provider.generate([{"role": "user", "content": CARD}], max_tokens=64)
        antes = capture.requests[-1]["messages"][-1]["content"]
        assert antes == CARD, (
            f"la bandera OFF debía mandar el texto en claro: {antes!r}"
        )

        # La dueña cambia el modelo desde el menú (fila real de system_config).
        await _write_llm_config(
            session_factory, {"model": "deepseek-v4-flash-auditoria"}
        )
        await _expire_hot_swap_cache(app)
        await provider.generate([{"role": "user", "content": CARD}], max_tokens=64)
        despues = capture.requests[-1]["messages"][-1]["content"]
        assert despues == "[tarjeta]", (
            "tras el swap caliente se esperaba el enmascarado reactivado "
            f"(hot_swap.py fija pii_masking=True); salió {despues!r}"
        )


# ---------------------------------------------------------------------------
# 7. Cobertura de llamadores: extracción de memoria y síntesis de perfiles
# ---------------------------------------------------------------------------


async def test_extraccion_de_memoria_enmascara_el_cierre_del_turno(
    engine, session_factory, monkeypatch, chats
) -> None:
    """El post-turno real (``extract_post_turn``) enmascara el historial."""
    chats.append(CHAT_MEMORIA)
    vip_id = await _seed_vip(session_factory, CHAT_MEMORIA)
    async with _app(
        engine,
        session_factory,
        monkeypatch,
        feature_pii_masking_enabled=True,
        feature_memory_enabled=True,
    ) as (app, capture):
        # Turno terminal propio (la extracción solo corre en delivered/…).
        async with session_factory() as session:
            await session.execute(
                text(
                    "insert into message_history "
                    "(chat_id, telegram_message_id, role, text, timestamp) "
                    "values (:c, 1, 'vip', :t, now() - interval '60 seconds')"
                ),
                {
                    "c": CHAT_MEMORIA,
                    "t": f"mi correo es {EMAIL} y mi tarjeta {CARD}",
                },
            )
            turn_id = (
                await session.execute(
                    text(
                        "insert into turns (chat_id, vip_id, channel_type, status, "
                        "trigger_message_id, created_at, updated_at) "
                        "values (:c, cast(:v as uuid), 'vip', 'delivered', 1, "
                        "now() - interval '50 seconds', now()) returning id"
                    ),
                    {"c": CHAT_MEMORIA, "v": vip_id},
                )
            ).scalar_one()
            await session.commit()

        report = await app.orchestrator._memory_extraction.extract_post_turn(
            turn_id, CHAT_MEMORIA
        )
        assert getattr(report, "status", None) != "disabled"

        extraccion = _payload_of(capture, schema_key="hechos")
        cuerpo = json.dumps(extraccion, ensure_ascii=False)
        for original in (EMAIL, CARD):
            assert original not in cuerpo, (
                f"la extracción de memoria mandó {original!r} al proveedor"
            )
        assert "[correo]" in cuerpo and "[tarjeta]" in cuerpo


async def test_sintesis_de_perfiles_enmascara_los_hechos(
    engine, session_factory, monkeypatch, chats
) -> None:
    """El job real de síntesis de perfiles enmascara los hechos del VIP."""
    chats.append(CHAT_SINTESIS)
    vip_id = await _seed_vip(session_factory, CHAT_SINTESIS)
    async with _app(
        engine,
        session_factory,
        monkeypatch,
        feature_pii_masking_enabled=True,
        feature_profile_synthesis_enabled=True,
    ) as (app, capture):
        assert app.profile_synthesis_service is not None
        async with session_factory() as session:
            await session.execute(
                text(
                    "insert into memories (vip_id, embedding, content, category, "
                    "confidence, status) values (cast(:v as uuid), cast(:e as vector), "
                    "cast(:cont as jsonb), 'comercial', 0.9, 'auto')"
                ),
                {
                    "v": vip_id,
                    "e": CERO_384,
                    "cont": json.dumps(
                        {
                            "texto": (
                                f"prefiere que le escriban a {EMAIL} "
                                f"y paga con {CARD}"
                            )
                        }
                    ),
                },
            )
            await session.commit()

        await app.profile_synthesis_service.synthesize(vip_id, "volume")

        sintesis = _payload_of(capture, schema_key="stable_traits")
        cuerpo = json.dumps(sintesis, ensure_ascii=False)
        for original in (EMAIL, CARD):
            assert original not in cuerpo, (
                f"la síntesis de perfiles mandó {original!r} al proveedor"
            )
        assert "[correo]" in cuerpo and "[tarjeta]" in cuerpo


# ---------------------------------------------------------------------------
# 8. Visión: el payload de Gemini no lleva texto del chat ni el caption
# ---------------------------------------------------------------------------


class _GeminiCapture:
    def __init__(self, descripcion: str = "Una foto de prueba.") -> None:
        self.descripcion = descripcion
        self.payloads: list[dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": self.descripcion}]}}
                ]
            },
        )


def _install_gemini_transport(
    monkeypatch: pytest.MonkeyPatch, capture: _GeminiCapture
) -> list[httpx.AsyncClient]:
    created: list[httpx.AsyncClient] = []

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(capture.handle), **kwargs
        )
        created.append(client)
        return client

    monkeypatch.setattr(
        gemini_vision_module, "httpx", SimpleNamespace(AsyncClient=_factory)
    )
    return created


def _blank_jpeg() -> bytes:
    image = Image.new("RGB", (320, 240), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


async def test_vision_no_recibe_texto_del_chat_ni_el_caption(
    engine, session_factory, monkeypatch, chats
) -> None:
    """Gemini recibe SOLO el prompt fijo + bytes; el caption no viaja.

    El caption (con el correo) entra al pipeline de texto como cualquier
    mensaje y ahí SÍ se enmascara (se asierta en el mismo caso).
    """
    chats.append(CHAT_VISION)
    await _seed_vip(session_factory, CHAT_VISION)
    caption = f"Mira, escríbeme a {EMAIL}"
    image_bytes = _blank_jpeg()

    async def _fake_download(*args: Any) -> bytes:
        # composition lo envuelve con functools.partial(..., bot): acepta los
        # dos argumentos y devuelve los bytes sintéticos, sin red.
        return image_bytes

    gemini = _GeminiCapture()
    # El partial del downloader se arma en build_app: se parchea antes.
    monkeypatch.setattr("diana.composition.download_media_bytes", _fake_download)
    gemini_clients = _install_gemini_transport(monkeypatch, gemini)

    async with _app(
        engine,
        session_factory,
        monkeypatch,
        feature_pii_masking_enabled=True,
        feature_image_vision_enabled=True,
        gemini_api_key=SecretStr("clave-falsa-gemini-c-pii-01"),
    ) as (app, capture):
        try:
            await app.dispatcher.feed_update(
                app.bot, _photo_update(CHAT_VISION, 1, caption)
            )
        finally:
            for client in gemini_clients:
                with contextlib.suppress(Exception):
                    await client.aclose()

        assert len(gemini.payloads) == 1, (
            f"se esperaba UNA llamada a visión, hubo {len(gemini.payloads)}"
        )
        payload_texto = json.dumps(gemini.payloads[0], ensure_ascii=False)
        assert EMAIL not in payload_texto
        assert PHONE not in payload_texto
        assert "Mira, escríbeme" not in payload_texto
        partes = gemini.payloads[0]["contents"][0]["parts"]
        assert len(partes) == 2
        assert "Describe brevemente" in partes[0]["text"]
        assert "inline_data" in partes[1]

        # El caption SÍ entró al pipeline de texto, y ahí se enmascaró.
        cuerpo_deepseek = _payloads_text(capture)
        assert "[correo]" in cuerpo_deepseek
        assert EMAIL not in cuerpo_deepseek
