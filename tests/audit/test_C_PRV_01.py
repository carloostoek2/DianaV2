"""C-PRV-01 — una foto con documento o dato fuerte no sale del servidor.

Prueba E2 sobre Postgres real (copia de la base real en un contenedor
desechable, ver ``audit/ENTORNO.md``). Se entra por ``build_app`` con las
banderas de cada escenario y por el handler real de mensajes de negocio
(``dispatcher.feed_update``); el pipeline cognitivo, el repositorio, el filtro
de privacidad, el OCR local y el enmascarado son los reales.

Solo se simulan los DOS bordes externos que la promesa nombra:

* la descarga de Telegram — se sustituye ``download_media_bytes`` por una
  función que devuelve los bytes sintéticos de la foto (nunca hay red);
* el proveedor Gemini — se levanta un servidor HTTP local y se desvía el
  transporte de ``httpx`` hacia él. El ``GeminiVisionProvider`` real arma el
  payload (base64 inline_data); el servidor captura exactamente lo que llegó.

Lo que se asierta son bytes capturados en el borde y estado persistido
(``message_history`` / ``pending_approvals`` / ``turns``), nunca "se llamó a
X" ni objetos internos simulados.

Los casos 2, 3, 5 y 6 fijaban el COMPORTAMIENTO VIEJO que la auditoría midió
(ver ``audit/contracts/C-PRV-01.md``, Puntos ciegos 1–4). Tras las decisiones
de la dueña del 2026-10-24 ahora exigen la conducta nueva:

* documento de identidad gana SIEMPRE sobre una tarjeta (no sale);
* una foto solo se bloquea cuando no se pudo verificar (texto ilegible,
  borrosa o sin contraste); una foto normal sin texto se describe;
* los separadores de tarjeta cubren punto, espacio duro, tabulador y salto;
* las corridas de 16 dígitos pasan por Luhn (una que falla NO se enmascara).
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from aiogram import Bot
from aiogram.types import Chat, Message, PhotoSize, Update, User
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pydantic import SecretStr
from sqlalchemy import text

import diana.llm.gemini_vision as gemini_vision_module
from diana.behavior.fake import FixedDelayPolicy
from diana.cognitive.models import Comprehension, EvaluationProfile
from diana.composition import build_app
from diana.config.settings import Settings
from diana.infrastructure.vision.ocr import OcrEngine
from diana.llm.fake import FakeLLM

TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"
OWNER_ID = 999001
BUSINESS_CONNECTION_ID = "bc-prv01-audit"
PHOTO_FILE_ID = "foto-prv01-grande"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Respuesta fija del proveedor simulado: identifica que el texto del turno
# salió de la descripción y no de otro camino.
CAPTION = "Pago con tarjeta sobre una mesa."

# Chats propios de la auditoría (la copia trae datos reales; todo se acota a
# estos ids y se limpia al final).
CHAT_DOC_IDENTIDAD = 999100101
CHAT_DOC_MAS_TARJETA = 999100102
CHAT_OCR_VACIO = 999100103
CHAT_TARJETA_AGRUPADA = 999100104
CHAT_TARJETA_CON_PUNTOS = 999100105
CHAT_DIEZ6_SIN_LUHN = 999100106
CHAT_FACTURA = 999100107
CHAT_BANDERA_OFF = 999100108
CHAT_PROVEEDOR_CAIDO = 999100109
CHAT_PERSISTENCIA = 999100110
CHAT_FOTO_SIN_TEXTO = 999100111
CHAT_FOTO_BORROSA = 999100112
CHAT_TARJETA_AMEX_PUNTOS = 999100113
CHAT_TARJETA_GRUPOS_6_10 = 999100114
CHAT_TARJETA_GRUPOS_2_14 = 999100115
CHAT_TARJETA_4X4X4X3 = 999100116


# ---------------------------------------------------------------------------
# Imágenes sintéticas (el texto se dibuja y el OCR real lo vuelve a leer)
# ---------------------------------------------------------------------------


def _image_bytes(
    lines: list[str],
    *,
    width: int = 900,
    font_size: int = 40,
    blur_radius: float = 0,
) -> bytes:
    """Una foto JPEG sintética con las líneas pedidas (texto negro, fondo blanco)."""
    height = 60 + len(lines) * (font_size + 25)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(FONT_PATH, font_size)
    y = 25
    for line in lines:
        draw.text((30, y), line, font=font, fill="black")
        y += font_size + 25
    if blur_radius:
        image = image.filter(ImageFilter.GaussianBlur(blur_radius))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def _photo_without_text(*, blur_radius: float = 0) -> bytes:
    """Foto normal sin texto (paisaje/persona): formas de color, nada que leer."""
    image = Image.new("RGB", (800, 600), (30, 90, 160))
    draw = ImageDraw.Draw(image)
    draw.rectangle([100, 100, 400, 350], fill=(250, 200, 40))
    draw.ellipse([420, 220, 720, 520], fill=(220, 40, 60))
    draw.polygon([(80, 560), (300, 300), (520, 560)], fill=(20, 180, 90))
    draw.line([(0, 0), (800, 600)], fill="white", width=12)
    if blur_radius:
        image = image.filter(ImageFilter.GaussianBlur(blur_radius))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


DOCUMENTO_IDENTIDAD = [
    "REPUBLICA ARGENTINA",
    "DOCUMENTO NACIONAL DE IDENTIDAD",
    "DNI 30445566",
    "APELLIDO GOMEZ",
]


# ---------------------------------------------------------------------------
# Proveedor Gemini simulado: servidor HTTP local que captura lo que llega
# ---------------------------------------------------------------------------


class _GeminiCaptureServer:
    """Servidor local que recibe el POST real del ``GeminiVisionProvider``.

    Guarda el payload JSON completo; los bytes de imagen se decodifican del
    bloque ``inline_data`` (base64), que es exactamente lo que viajaría a
    Google.
    """

    def __init__(self, *, caption: str = CAPTION, status: int = 200) -> None:
        self.caption = caption
        self.status = status
        self.payloads: list[dict[str, Any]] = []
        server = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 (nombre fijado por http.server)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                try:
                    payload = json.loads(raw)
                except Exception:
                    payload = {"_raw": raw.decode("utf-8", "replace")}
                server.payloads.append(payload)
                if server.status >= 400:
                    body = b'{"error":{"message":"proveedor caido"}}'
                    self.send_response(server.status)
                else:
                    body = json.dumps(
                        {
                            "candidates": [
                                {"content": {"parts": [{"text": server.caption}]}}
                            ]
                        }
                    ).encode("utf-8")
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: Any) -> None:
                return None

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        host, port = self._httpd.server_address[:2]
        self.base_url = f"http://{host}:{port}"
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )
        self._thread.start()

    @property
    def request_count(self) -> int:
        return len(self.payloads)

    @property
    def sent_images(self) -> list[bytes]:
        """Bytes de cada imagen que llegó al proveedor (ya decodificados)."""
        out: list[bytes] = []
        for payload in self.payloads:
            try:
                parts = payload["contents"][0]["parts"]
            except (KeyError, IndexError, TypeError):
                continue
            for part in parts:
                inline = part.get("inline_data") if isinstance(part, dict) else None
                if inline and inline.get("data"):
                    out.append(base64.b64decode(inline["data"]))
        return out

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


class _LocalTransport(httpx.AsyncBaseTransport):
    """Reenvía el pedido real (URL absoluta a Google) al servidor local."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        target = self._base_url + request.url.raw_path.decode("ascii")
        headers = [
            (key, value)
            for key, value in request.headers.raw
            if key.lower() != b"host"
        ]
        forwarded = httpx.Request(
            request.method, target, headers=headers, content=body
        )
        response = await self._inner.handle_async_request(forwarded)
        content = await response.aread()
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=content,
            request=request,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


def _install_gemini_transport(
    monkeypatch: pytest.MonkeyPatch, base_url: str
) -> list[httpx.AsyncClient]:
    """Desvía SOLO el borde HTTP del proveedor de visión al servidor local."""
    clients: list[httpx.AsyncClient] = []

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        client = httpx.AsyncClient(transport=_LocalTransport(base_url), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(
        gemini_vision_module, "httpx", SimpleNamespace(AsyncClient=_factory)
    )
    return clients


@contextlib.contextmanager
def _gemini(caption: str = CAPTION, status: int = 200):
    server = _GeminiCaptureServer(caption=caption, status=status)
    try:
        yield server
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# Bot: la salida a Telegram no sale de la máquina (borde de notificación)
# ---------------------------------------------------------------------------


class _SpyBotSession:
    """Doble de la salida a Telegram; registra el método, nunca hace red."""

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


def _photo_update(chat_id: int, message_id: int) -> Update:
    message = Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=chat_id, is_bot=False, first_name="Vip"),
        photo=[
            PhotoSize(
                file_id="foto-prv01-chica",
                file_unique_id="u-chica",
                width=90,
                height=60,
            ),
            PhotoSize(
                file_id=PHOTO_FILE_ID,
                file_unique_id="u-grande",
                width=900,
                height=400,
            ),
        ],
        business_connection_id=BUSINESS_CONNECTION_ID,
    )
    return Update(update_id=chat_id, business_message=message)


# ---------------------------------------------------------------------------
# Escenario: settings, siembra, ejecución y lectura de lo persistido
# ---------------------------------------------------------------------------


def _settings(*, vision_enabled: bool) -> Settings:
    return Settings.model_construct(
        telegram_bot_token=SecretStr(TOKEN),
        owner_telegram_id=OWNER_ID,
        database_url=SecretStr(
            "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder"
        ),
        deepseek_api_key="",
        global_mode="supervised",
        feature_image_vision_enabled=vision_enabled,
        feature_video_vision_enabled=False,
        feature_gray_zone_enabled=False,
        feature_autonomous_mode=False,
        gemini_api_key=SecretStr("clave-falsa-de-auditoria"),
        log_level="ERROR",
    )


def _comprehension() -> Comprehension:
    return Comprehension(
        intent="consultar",
        topics=["imagen"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_history=False,
        needs_context=False,
        needs_memory=False,
        needs_policy=False,
        needs_schedule=False,
        needs_examples=False,
    )


def _evaluation() -> EvaluationProfile:
    return EvaluationProfile(
        naturalness=0.9,
        precision=0.9,
        doctrine=0.9,
        consistency=0.9,
        safety=0.95,
        coverage=0.9,
        empathy=0.9,
    )


async def _seed_vip(session_factory: Any, chat_id: int) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                "insert into vips (telegram_user_id, display_name) "
                "values (:t, 'Prueba privacidad C-PRV-01')"
            ),
            {"t": chat_id},
        )
        await session.commit()


async def _delete_chat_data(session_factory: Any, chat_id: int) -> None:
    """Limpia SOLO las filas de este chat (la copia trae datos reales)."""
    async with session_factory() as session:
        await session.execute(
            text(
                "delete from pending_deliveries where chat_id = :c"
            ),
            {"c": chat_id},
        )
        await session.execute(
            text(
                "delete from escalation_events where turn_id in "
                "(select id from turns where chat_id = :c)"
            ),
            {"c": chat_id},
        )
        await session.execute(
            text("delete from pending_approvals where chat_id = :c"), {"c": chat_id}
        )
        await session.execute(
            text("delete from pipeline_traces where chat_id = :c"), {"c": chat_id}
        )
        await session.execute(
            text("delete from message_history where chat_id = :c"), {"c": chat_id}
        )
        await session.execute(
            text("delete from turn_category_log where chat_id = :c"), {"c": chat_id}
        )
        await session.execute(
            text("delete from turns where chat_id = :c"), {"c": chat_id}
        )
        await session.execute(
            text("delete from vips where telegram_user_id = :c"), {"c": chat_id}
        )
        await session.commit()


@dataclass
class _Outcome:
    gemini: _GeminiCaptureServer
    downloader_calls: list[str]
    history_text: str | None
    approval: dict[str, Any] | None
    turn_status: str | None
    bot_methods: list[str] = field(default_factory=list)

    @property
    def sent_images(self) -> list[bytes]:
        return self.gemini.sent_images


@contextlib.asynccontextmanager
async def _run_photo_case(
    engine: Any,
    session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    gemini: _GeminiCaptureServer,
    *,
    chat_id: int,
    message_id: int,
    image: bytes,
    vision_enabled: bool = True,
):
    """Siembra el VIP, arma la app real y entrega la foto por el handler real."""
    await _seed_vip(session_factory, chat_id)

    downloader_calls: list[str] = []

    async def _fake_download(_bot: Any, file_id: str) -> bytes:
        # `build_app` arma `functools.partial(download_media_bytes, bot)`, así
        # que el primer argumento posicional es el bot (no se usa aquí).
        downloader_calls.append(file_id)
        return image

    # Borde externo 1: la descarga de Telegram (bytes sintéticos).
    monkeypatch.setattr(
        "diana.composition.download_media_bytes", _fake_download
    )
    # Borde externo 2: el proveedor Gemini (servidor local que captura).
    clients = _install_gemini_transport(monkeypatch, gemini.base_url)

    llm = FakeLLM(
        structured_responses=[_comprehension(), _evaluation()],
        text_responses=["Claro, te cuento."],
    )
    bot = _bot()
    app = build_app(
        _settings(vision_enabled=vision_enabled),
        bot=bot,
        llm=llm,
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )

    try:
        await app.dispatcher.feed_update(bot, _photo_update(chat_id, message_id))

        async with session_factory() as session:
            history_text = (
                await session.execute(
                    text(
                        "select text from message_history "
                        "where chat_id = :c and telegram_message_id = :m "
                        "order by id desc limit 1"
                    ),
                    {"c": chat_id, "m": message_id},
                )
            ).scalar_one_or_none()
            approval_row = (
                await session.execute(
                    text(
                        "select draft_text, photo_file_id, status, turn_id "
                        "from pending_approvals where chat_id = :c "
                        "order by created_at desc limit 1"
                    ),
                    {"c": chat_id},
                )
            ).mappings().first()
            turn_status = (
                await session.execute(
                    text(
                        "select status from turns where chat_id = :c "
                        "order by created_at desc limit 1"
                    ),
                    {"c": chat_id},
                )
            ).scalar_one_or_none()

        yield _Outcome(
            gemini=gemini,
            downloader_calls=downloader_calls,
            history_text=history_text,
            approval=dict(approval_row) if approval_row is not None else None,
            turn_status=turn_status,
            bot_methods=list(getattr(bot.session, "methods", [])),
        )
    finally:
        for client in clients:
            with contextlib.suppress(Exception):
                await client.aclose()
        with contextlib.suppress(Exception):
            await bot.session.close()


@pytest.fixture
async def chats(session_factory: Any):
    """Registra los chats de la prueba y los limpia aunque la prueba falle."""
    registrados: list[int] = []
    yield registrados
    for chat_id in registrados:
        await _delete_chat_data(session_factory, chat_id)


def _assert_turno_completo(outcome: _Outcome) -> None:
    """El pipeline llegó a la cola de la dueña (turno + aprobación persistidos)."""
    assert outcome.approval is not None, (
        "el turno no llegó a la cola de aprobación: "
        f"history={outcome.history_text!r} turn={outcome.turn_status!r}"
    )
    assert outcome.approval["draft_text"], "el borrador persistido está vacío"
    assert outcome.approval["status"] == "waiting", (
        f"estado de aprobación inesperado: {outcome.approval!r}"
    )


# ---------------------------------------------------------------------------
# 1. Documento de identidad legible → sensible, CERO bytes al proveedor
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_documento_de_identidad_no_sale_y_queda_marcado_sensible(
    engine, session_factory, monkeypatch, chats
) -> None:
    chats.append(CHAT_DOC_IDENTIDAD)
    image = _image_bytes(DOCUMENTO_IDENTIDAD)
    with _gemini() as gemini:
        async with _run_photo_case(
            engine,
            session_factory,
            monkeypatch,
            gemini,
            chat_id=CHAT_DOC_IDENTIDAD,
            message_id=1,
            image=image,
        ) as outcome:
            assert outcome.history_text == (
                "[imagen] ⚠️ contiene información sensible (no analizada)"
            ), f"texto del turno inesperado: {outcome.history_text!r}"
            # El OCR real leyó el documento (no es una foto vacía).
            assert "DNI 30445566" in OcrEngine().extract_text(image)
            # Nada salió: ni el original ni una copia tapada.
            assert gemini.request_count == 0, (
                f"la imagen viajó al proveedor {gemini.request_count} vez/veces"
            )
            assert outcome.sent_images == []
            _assert_turno_completo(outcome)
            # La foto sí llega al mensaje de la dueña (revisión manual).
            assert outcome.approval["photo_file_id"] == PHOTO_FILE_ID


# ---------------------------------------------------------------------------
# 2. Documento + número de 16 dígitos → la identidad GANA: no sale
#    (arreglo del Punto ciego 1)
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_documento_con_numero_de_16_digitos_no_sale(
    engine, session_factory, monkeypatch, chats
) -> None:
    """Conducta nueva: un documento de identidad no sale NUNCA, ni tapado.

    Antes ``scan_sensitive`` devolvía "tarjeta" antes de buscar identidad y la
    imagen viajaba con el documento legible. Ahora la identidad se clasifica
    primero (decisión de la dueña, 2026-10-24): cero bytes al proveedor.
    """
    chats.append(CHAT_DOC_MAS_TARJETA)
    image = _image_bytes(
        [
            "DOCUMENTO NACIONAL DE IDENTIDAD",
            "DNI 30445566",
            "4111 1111 1111 1111",
        ]
    )
    with _gemini() as gemini:
        async with _run_photo_case(
            engine,
            session_factory,
            monkeypatch,
            gemini,
            chat_id=CHAT_DOC_MAS_TARJETA,
            message_id=2,
            image=image,
        ) as outcome:
            assert outcome.history_text == (
                "[imagen] ⚠️ contiene información sensible (no analizada)"
            ), f"el turno no se marcó sensible: {outcome.history_text!r}"
            assert gemini.request_count == 0, (
                "la imagen del documento viajó al proveedor "
                f"{gemini.request_count} vez/veces"
            )
            assert outcome.sent_images == []
            _assert_turno_completo(outcome)
            assert outcome.approval["photo_file_id"] == PHOTO_FILE_ID


# ---------------------------------------------------------------------------
# 3. Documento borroso sin texto legible → no verificable: no sale
#    (arreglo del Punto ciego 2)
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_documento_borroso_con_ocr_vacio_no_sale(
    engine, session_factory, monkeypatch, chats
) -> None:
    """Conducta nueva: si no se puede verificar, no sale.

    El OCR real devuelve "" y la evidencia local (nitidez/contraste) dice que
    la imagen está borrosa: se marca sensible en lugar de viajar sin revisar.
    """
    chats.append(CHAT_OCR_VACIO)
    image = _image_bytes(
        ["DOCUMENTO NACIONAL DE IDENTIDAD", "DNI 30445566"], blur_radius=14
    )
    # El escenario es el declarado: el OCR real de esta foto no devuelve texto.
    assert OcrEngine().extract_text(image) == "", (
        "la foto borrosa produjo texto: el escenario no es 'OCR vacío'"
    )
    with _gemini() as gemini:
        async with _run_photo_case(
            engine,
            session_factory,
            monkeypatch,
            gemini,
            chat_id=CHAT_OCR_VACIO,
            message_id=3,
            image=image,
        ) as outcome:
            assert outcome.history_text == (
                "[imagen] ⚠️ contiene información sensible (no analizada)"
            ), f"el turno no se marcó sensible: {outcome.history_text!r}"
            assert gemini.request_count == 0, (
                "una imagen no verificable viajó al proveedor"
            )
            _assert_turno_completo(outcome)


# ---------------------------------------------------------------------------
# 4. Tarjeta Luhn válida agrupada → enmascarada, viajan otros bytes
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_tarjeta_valida_agrupada_sale_enmascarada(
    engine, session_factory, monkeypatch, chats
) -> None:
    chats.append(CHAT_TARJETA_AGRUPADA)
    image = _image_bytes(["4111 1111 1111 1111", "VENCE 12/29"])
    with _gemini() as gemini:
        async with _run_photo_case(
            engine,
            session_factory,
            monkeypatch,
            gemini,
            chat_id=CHAT_TARJETA_AGRUPADA,
            message_id=4,
            image=image,
        ) as outcome:
            assert outcome.history_text == f"[imagen: {CAPTION}]", (
                f"texto del turno inesperado: {outcome.history_text!r}"
            )
            assert gemini.request_count == 1
            sent = outcome.sent_images
            assert len(sent) == 1
            assert sent[0] != image, "viajaron los bytes originales sin tapar"
            texto_que_salio = OcrEngine().extract_text(sent[0])
            assert "4111" not in texto_que_salio, (
                f"el número de tarjeta sigue legible en lo enviado: "
                f"{texto_que_salio!r}"
            )
            assert "VENCE" in texto_que_salio, (
                "se tapó de más: el resto de la imagen debía viajar"
            )
            _assert_turno_completo(outcome)


# ---------------------------------------------------------------------------
# 5. Tarjeta con puntos → se detecta y se tapa (arreglo del Punto ciego 3)
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_tarjeta_con_separadores_de_punto_sale_enmascarada(
    engine, session_factory, monkeypatch, chats
) -> None:
    """Conducta nueva: ``4111.1111.1111.1111`` se detecta y se tapa.

    Los patrones ahora cubren punto, espacio duro, tabulador y salto de línea
    (decisión de la dueña, 2026-10-24). El enmascarado sigue usando las cajas
    reales del OCR.
    """
    chats.append(CHAT_TARJETA_CON_PUNTOS)
    image = _image_bytes(["4111.1111.1111.1111", "VENCE 12/29"])
    assert "4111.1111.1111.1111" in OcrEngine().extract_text(image), (
        "el OCR no conservó los puntos: el escenario no es el declarado"
    )
    with _gemini() as gemini:
        async with _run_photo_case(
            engine,
            session_factory,
            monkeypatch,
            gemini,
            chat_id=CHAT_TARJETA_CON_PUNTOS,
            message_id=5,
            image=image,
        ) as outcome:
            assert outcome.history_text == f"[imagen: {CAPTION}]", (
                f"texto del turno inesperado: {outcome.history_text!r}"
            )
            assert gemini.request_count == 1
            sent = outcome.sent_images
            assert len(sent) == 1
            assert sent[0] != image, "viajaron los bytes originales sin tapar"
            texto_que_salio = OcrEngine().extract_text(sent[0])
            assert "4111" not in texto_que_salio, (
                f"el número de tarjeta sigue legible en lo enviado: "
                f"{texto_que_salio!r}"
            )
            assert "VENCE" in texto_que_salio, (
                "se tapó de más: el resto de la imagen debía viajar"
            )
            _assert_turno_completo(outcome)


# ---------------------------------------------------------------------------
# 5b. Formatos de tarjeta del hallazgo H2 → se detectan y se tapan
# ---------------------------------------------------------------------------


@pytest.mark.db
@pytest.mark.parametrize(
    ("chat_id", "linea", "prohibido", "message_id"),
    [
        (CHAT_TARJETA_AMEX_PUNTOS, "3782.822463.10005", "3782", 13),
        (CHAT_TARJETA_GRUPOS_6_10, "411111 1111111111", "411111", 14),
        (CHAT_TARJETA_GRUPOS_2_14, "41 11111111111111", "41111", 15),
        (CHAT_TARJETA_4X4X4X3, "4111 1111 1111 1111 123", "4111", 16),
    ],
    ids=["amex-con-puntos", "grupos-6-10", "grupos-2-14", "diecinueve-4-4-4-4-3"],
)
async def test_formatos_de_tarjeta_del_hallazgo_se_tapan(
    engine,
    session_factory,
    monkeypatch,
    chats,
    chat_id,
    linea,
    prohibido,
    message_id,
) -> None:
    """H2: Amex con puntos, 6-10, 2-14 y 4-4-4-4-3 nunca salen legibles.

    Los tres formatos viajaban limpios porque la visión tenía sus propios
    patrones (solo espacio y guion). Ahora comparte la detección del
    enmascarador de texto: separadores completos y Luhn sobre el prefijo.
    La imagen se tapa localmente y se comprueba que el número ya no se lea
    en los bytes que llegaron al proveedor.
    """
    chats.append(chat_id)
    image = _image_bytes([linea, "VENCE 12/29"])
    assert linea in OcrEngine().extract_text(image), (
        "el OCR no conservó el formato: el escenario no es el declarado"
    )
    with _gemini() as gemini:
        async with _run_photo_case(
            engine,
            session_factory,
            monkeypatch,
            gemini,
            chat_id=chat_id,
            message_id=message_id,
            image=image,
        ) as outcome:
            assert outcome.history_text == f"[imagen: {CAPTION}]", (
                f"texto del turno inesperado: {outcome.history_text!r}"
            )
            assert gemini.request_count == 1
            sent = outcome.sent_images
            assert len(sent) == 1
            assert sent[0] != image, "viajaron los bytes originales sin tapar"
            texto_que_salio = OcrEngine().extract_text(sent[0])
            assert prohibido not in texto_que_salio, (
                f"el número de tarjeta sigue legible en lo enviado: "
                f"{texto_que_salio!r}"
            )
            assert "VENCE" in texto_que_salio, (
                "se tapó de más: el resto de la imagen debía viajar"
            )
            _assert_turno_completo(outcome)


# ---------------------------------------------------------------------------
# 6. 16 dígitos que fallan Luhn → NO se enmascaran (arreglo del Punto ciego 4)
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_diez6_digitos_sin_luhn_viaja_sin_enmascarar(
    engine, session_factory, monkeypatch, chats
) -> None:
    """Conducta nueva: una corrida de 16 dígitos debe pasar Luhn para taparse.

    ``1234567890123456`` no es una tarjeta válida (número de pedido): la foto
    viaja tal cual y se describe. Antes el patrón agrupado lo tomaba como
    tarjeta antes de Luhn.
    """
    chats.append(CHAT_DIEZ6_SIN_LUHN)
    image = _image_bytes(["PEDIDO 1234567890123456", "GRACIAS"])
    assert "1234567890123456" in OcrEngine().extract_text(image)
    with _gemini() as gemini:
        async with _run_photo_case(
            engine,
            session_factory,
            monkeypatch,
            gemini,
            chat_id=CHAT_DIEZ6_SIN_LUHN,
            message_id=6,
            image=image,
        ) as outcome:
            assert outcome.history_text == f"[imagen: {CAPTION}]"
            assert gemini.request_count == 1
            sent = outcome.sent_images
            assert len(sent) == 1
            assert sent[0] == image, (
                "el número sin Luhn se enmascaró; no es una tarjeta"
            )
            texto_que_salio = OcrEngine().extract_text(sent[0])
            assert "1234567890123456" in texto_que_salio
            assert "GRACIAS" in texto_que_salio
            _assert_turno_completo(outcome)


# ---------------------------------------------------------------------------
# 7. Factura → viaja tal cual, importe visible, con descripción
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_factura_viaja_con_el_importe_visible(
    engine, session_factory, monkeypatch, chats
) -> None:
    chats.append(CHAT_FACTURA)
    image = _image_bytes(["FACTURA", "Total 99.90", "IVA incluido"])
    with _gemini() as gemini:
        async with _run_photo_case(
            engine,
            session_factory,
            monkeypatch,
            gemini,
            chat_id=CHAT_FACTURA,
            message_id=7,
            image=image,
        ) as outcome:
            assert outcome.history_text == f"[imagen: {CAPTION}]", (
                f"texto del turno inesperado: {outcome.history_text!r}"
            )
            assert gemini.request_count == 1
            sent = outcome.sent_images
            assert len(sent) == 1
            assert sent[0] == image, "la factura no viajó tal cual"
            texto_que_salio = OcrEngine().extract_text(sent[0])
            assert "99.90" in texto_que_salio, (
                f"el importe no quedó visible en lo enviado: {texto_que_salio!r}"
            )
            _assert_turno_completo(outcome)


# ---------------------------------------------------------------------------
# 8. Bandera OFF → sin descarga, sin OCR, etiqueta plana y sin foto en la
#    aprobación
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_bandera_apagada_no_descarga_ni_analiza(
    engine, session_factory, monkeypatch, chats
) -> None:
    chats.append(CHAT_BANDERA_OFF)
    image = _image_bytes(DOCUMENTO_IDENTIDAD)
    with _gemini() as gemini:
        async with _run_photo_case(
            engine,
            session_factory,
            monkeypatch,
            gemini,
            chat_id=CHAT_BANDERA_OFF,
            message_id=8,
            image=image,
            vision_enabled=False,
        ) as outcome:
            assert outcome.history_text == "[imagen]", (
                f"con la bandera apagada el turno cambió: {outcome.history_text!r}"
            )
            assert outcome.downloader_calls == [], (
                f"se descargó la foto con la visión apagada: "
                f"{outcome.downloader_calls!r}"
            )
            assert gemini.request_count == 0
            _assert_turno_completo(outcome)
            assert outcome.approval["photo_file_id"] is None, (
                "la foto viajó a la aprobación con la bandera apagada"
            )


# ---------------------------------------------------------------------------
# 9. Proveedor caído → etiqueta plana y turno completo (fail-open)
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_proveedor_caido_deja_etiqueta_plana_y_el_turno_sigue(
    engine, session_factory, monkeypatch, chats
) -> None:
    chats.append(CHAT_PROVEEDOR_CAIDO)
    image = _image_bytes(["FACTURA", "Total 99.90"])
    with _gemini(status=503) as gemini:
        async with _run_photo_case(
            engine,
            session_factory,
            monkeypatch,
            gemini,
            chat_id=CHAT_PROVEEDOR_CAIDO,
            message_id=9,
            image=image,
        ) as outcome:
            assert outcome.history_text == "[imagen]", (
                f"el fallo del proveedor no fue fail-open: "
                f"{outcome.history_text!r}"
            )
            assert gemini.request_count == 1, (
                "la llamada al proveedor no se intentó (el escenario no es 'caído')"
            )
            _assert_turno_completo(outcome)
            assert outcome.approval["photo_file_id"] == PHOTO_FILE_ID, (
                "la dueña perdió la foto cuando el proveedor falló"
            )


# ---------------------------------------------------------------------------
# 11. Foto normal sin texto → se describe (decisión (b) de la dueña)
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_foto_normal_sin_texto_se_describe(
    engine, session_factory, monkeypatch, chats
) -> None:
    """Una foto sin texto (paisaje/persona) NO se bloquea: sigue su curso."""
    chats.append(CHAT_FOTO_SIN_TEXTO)
    image = _photo_without_text()
    assert OcrEngine().extract_text(image) == "", (
        "la foto de formas produjo texto: el escenario no es 'sin texto'"
    )
    with _gemini() as gemini:
        async with _run_photo_case(
            engine,
            session_factory,
            monkeypatch,
            gemini,
            chat_id=CHAT_FOTO_SIN_TEXTO,
            message_id=11,
            image=image,
        ) as outcome:
            assert outcome.history_text == f"[imagen: {CAPTION}]", (
                f"una foto normal sin texto se bloqueó: {outcome.history_text!r}"
            )
            assert gemini.request_count == 1
            sent = outcome.sent_images
            assert len(sent) == 1
            assert sent[0] == image, "la foto limpia no viajó tal cual"
            _assert_turno_completo(outcome)


# ---------------------------------------------------------------------------
# 12. Foto borrosa sin texto legible → no verificable: no sale
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_foto_borrosa_sin_texto_no_sale(
    engine, session_factory, monkeypatch, chats
) -> None:
    """La nitidez/contraste local distingue una foto normal de una borrosa."""
    chats.append(CHAT_FOTO_BORROSA)
    image = _photo_without_text(blur_radius=14)
    assert OcrEngine().extract_text(image) == ""
    with _gemini() as gemini:
        async with _run_photo_case(
            engine,
            session_factory,
            monkeypatch,
            gemini,
            chat_id=CHAT_FOTO_BORROSA,
            message_id=12,
            image=image,
        ) as outcome:
            assert outcome.history_text == (
                "[imagen] ⚠️ contiene información sensible (no analizada)"
            ), f"una foto borrosa viajó sin verificar: {outcome.history_text!r}"
            assert gemini.request_count == 0
            _assert_turno_completo(outcome)


# ---------------------------------------------------------------------------
# 10. Persistencia: ni bytes de la imagen en DB ni archivos en disco; el
#     texto del turno sí queda en message_history
# ---------------------------------------------------------------------------


async def _columnas_con_bytes(session_factory: Any, tablas: tuple[str, ...]):
    """Columnas donde podrían caber bytes de imagen: texto/JSON y bytea."""
    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "select table_name, column_name, data_type "
                    "from information_schema.columns "
                    "where table_schema = 'public' "
                    "and table_name = any(:t) "
                    "and data_type in "
                    "('text', 'character varying', 'jsonb', 'json', 'bytea')"
                ),
                {"t": list(tablas)},
            )
        ).all()
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]


async def _apariciones(
    session_factory: Any,
    tablas: tuple[str, ...],
    marca_base64: str,
    marca_bytes: bytes,
) -> list[str]:
    """Tablas.columnas (de las tocadas por el turno) donde aparece la marca."""
    encontrados: list[str] = []
    async with session_factory() as session:
        for tabla, columna, tipo in await _columnas_con_bytes(
            session_factory, tablas
        ):
            if tipo == "bytea":
                consulta = text(
                    f"select count(*) from {tabla} "
                    f"where position(cast(:p as bytea) in {columna}) > 0"
                )
                params = {"p": marca_bytes}
            else:
                consulta = text(
                    f"select count(*) from {tabla} "
                    f"where {columna}::text like :p"
                )
                params = {"p": f"%{marca_base64}%"}
            count = (await session.execute(consulta, params)).scalar_one()
            if count:
                encontrados.append(f"{tabla}.{columna} ({count})")
    return encontrados


@pytest.mark.db
async def test_la_imagen_no_se_persiste_y_el_texto_del_turno_si(
    engine, session_factory, monkeypatch, chats, tmp_path
) -> None:
    chats.append(CHAT_PERSISTENCIA)
    image = _image_bytes(["4111 1111 1111 1111", "VENCE 12/29"])
    # Cualquier escritura temporal caería aquí; al final el directorio debe
    # seguir vacío (la imagen solo vive en memoria durante el análisis).
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv("TMPDIR", str(scratch))
    monkeypatch.setenv("TEMP", str(scratch))
    monkeypatch.setenv("TMP", str(scratch))
    monkeypatch.setattr(tempfile, "tempdir", str(scratch), raising=False)

    with _gemini() as gemini:
        async with _run_photo_case(
            engine,
            session_factory,
            monkeypatch,
            gemini,
            chat_id=CHAT_PERSISTENCIA,
            message_id=10,
            image=image,
        ) as outcome:
            assert outcome.history_text == f"[imagen: {CAPTION}]"
            sent = outcome.sent_images
            assert len(sent) == 1
            # Marca única tomada del centro del payload que sí viajó: si los
            # bytes de la imagen se hubieran guardado en claro o en base64,
            # esta marca aparecería en alguna columna de texto.
            marca_bytes = sent[0][len(sent[0]) // 2:][:48]
            marca_base64 = base64.b64encode(marca_bytes).decode()
            assert len(marca_base64) >= 40
            tablas = (
                "message_history",
                "pending_approvals",
                "pipeline_traces",
                "turns",
                "vips",
            )
            apariciones = await _apariciones(
                session_factory, tablas, marca_base64, marca_bytes
            )
            assert apariciones == [], (
                f"bytes de la imagen persistidos en {apariciones}"
            )
            # El texto del turno sí está persistido y con contenido no trivial.
            assert outcome.history_text and len(outcome.history_text) > 20
            _assert_turno_completo(outcome)

    assert list(scratch.iterdir()) == [], (
        "se escribieron archivos temporales durante el análisis de la imagen"
    )
