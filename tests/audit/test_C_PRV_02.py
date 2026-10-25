"""C-PRV-02 — un video se revisa fotograma a fotograma antes de salir.

Prueba E2: entra por el ``business_message`` real cableado por ``build_app`` y
verifica el texto que queda persistido en Postgres (copia de la base real) más
lo que recibe el proveedor externo. Reales: ffmpeg, ffprobe, tesseract,
``FfmpegFrameExtractor``, ``OcrEngine``, ``scan_sensitive``,
``VideoVisionService``, ``VideoDescriber`` y el handler de negocio.

Simulados SOLO los dos bordes externos:
- la descarga de Telegram (devuelve los bytes de un mp4 real generado aquí);
- el proveedor Gemini (determinista: registra método, mime y cada payload que
  recibiría, y puede aceptar o rechazar).

Promesa bajo prueba: si en cualquier fotograma revisado aparece un dato fuerte
(tarjeta, cuenta, clave) o un documento de identidad, el video NO sale y el
turno queda con la marca sensible; si todo está limpio se describe; si el
archivo supera el tope de descarga, ffmpeg no está, el OCR no está o el video
no se puede leer, se cierra (sensible) sin llamar al proveedor. Un video de más
de 30 segundos —o con duración desconocida— tampoco sale: la cobertura no se
puede garantizar (decisión de la dueña, 2026-10-24). Cuando el video no entra
en un solo envío, salen únicamente los cuadros ya revisados, siempre con un par
bytes/MIME coherente. La bandera apagada no descarga, no extrae y deja
``[video]`` plano.

Privacidad: solo se leen filas de los ids de prueba; nunca texto de VIP reales.
"""

from __future__ import annotations

import io
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiogram import Bot
from aiogram.types import Chat, Message, Update, User, Video
from PIL import Image, ImageDraw, ImageFont
from pydantic import SecretStr
from sqlalchemy import text

from diana.application.image_vision_service import scan_sensitive
from diana.behavior.fake import FixedDelayPolicy
from diana.cognitive.models import Comprehension, EvaluationProfile
from diana.composition import build_app
from diana.config.settings import Settings
from diana.infrastructure.vision.ocr import OcrEngine
from diana.infrastructure.vision.video_frames import FfmpegFrameExtractor
from diana.llm.fake import FakeLLM

pytestmark = pytest.mark.db

TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"
OWNER_ID = 999001
BUSINESS_CONNECTION_ID = "bc-prv02-audit"
SENSITIVE_TEXT = "[video] ⚠️ contiene información sensible (no analizada)"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"

# Ids propios de 13 dígitos (más allá de cualquier id real de Telegram, hoy de
# 10-11 dígitos). Se valida al arrancar que no existan: si existieran, la prueba
# no puede distinguir lo que hizo ella de lo que ya estaba.
CHAT_CARD = 9_000_000_020_101
CHAT_FRAMES = 9_000_000_020_102
CHAT_FRAMES_SENSITIVE = 9_000_000_020_103
CHAT_TOO_LARGE = 9_000_000_020_104
CHAT_NO_FFMPEG = 9_000_000_020_105
CHAT_FLAG_OFF = 9_000_000_020_106
CHAT_NO_OCR = 9_000_000_020_107
CHAT_CORRUPT = 9_000_000_020_108
CHAT_INVOICE = 9_000_000_020_109
CHAT_CAPTION_CARD = 9_000_000_020_110
CHAT_CARD_INNOCENT_CAPTION = 9_000_000_020_111
CHAT_PNG_MIME = 9_000_000_020_112
CHAT_PNG_FAILOPEN = 9_000_000_020_113
CHAT_MATRIX_ON = 9_000_000_020_114
CHAT_TOO_LONG = 9_000_000_020_115


# ---------------------------------------------------------------------------
# Dobles de los bordes externos
# ---------------------------------------------------------------------------


class SpyBotSession:
    """Doble de la salida a Telegram: nada sale de la máquina.

    Devuelve un mensaje mínimo con ``message_id`` para que el aviso de borrador
    a la dueña (que guarda ese id) no rompa el turno.
    """

    def __init__(self) -> None:
        self.methods: list[str] = []

    async def __call__(self, bot: Any, method: Any, timeout: Any = None) -> Any:
        self.methods.append(type(method).__name__)
        return SimpleNamespace(message_id=len(self.methods))

    async def close(self) -> None:
        return None


class RecordingDownloader:
    """Doble de la descarga de Telegram: entrega bytes reales y registra file_id."""

    def __init__(self, payloads: dict[str, bytes]) -> None:
        self._payloads = dict(payloads)
        self.calls: list[str] = []

    async def __call__(self, bot: Any, file_id: str) -> bytes:
        self.calls.append(file_id)
        return self._payloads[file_id]


@dataclass
class ProviderCall:
    kind: str
    mime_type: str
    prompt: str
    payloads: list[bytes] = field(default_factory=list)


class RecordingVisionProvider:
    """Doble determinista del proveedor Gemini (borde externo).

    No decide nada: registra exactamente qué habría recibido (método, mime y
    bytes de cada parte) y devuelve una descripción fija o falla a pedido.
    """

    def __init__(
        self,
        *,
        response: str = "una escena de prueba",
        fail_with: BaseException | None = None,
    ) -> None:
        self.response = response
        self.fail_with = fail_with
        self.calls: list[ProviderCall] = []

    async def describe_video(
        self, video_bytes: bytes, *, mime_type: str, prompt: str
    ) -> str:
        self.calls.append(
            ProviderCall("video", mime_type, prompt, [bytes(video_bytes)])
        )
        return self._answer()

    async def describe_images(
        self, images: list[bytes], *, mime_type: str, prompt: str
    ) -> str:
        self.calls.append(
            ProviderCall("images", mime_type, prompt, [bytes(i) for i in images])
        )
        return self._answer()

    async def describe_image(
        self, image_bytes: bytes, *, mime_type: str, prompt: str
    ) -> str:  # pragma: no cover - la visión de fotos no entra en este contrato
        self.calls.append(
            ProviderCall("image", mime_type, prompt, [bytes(image_bytes)])
        )
        return self._answer()

    async def aclose(self) -> None:
        return None

    def _answer(self) -> str:
        if self.fail_with is not None:
            raise self.fail_with
        return self.response


# ---------------------------------------------------------------------------
# Videos reales (mp4 generado con ffmpeg a partir de fotogramas dibujados)
# ---------------------------------------------------------------------------


def _frames(
    folder: Path,
    *,
    width: int,
    height: int,
    seconds: int,
    fps: int,
    card_window: tuple[float, float] | None,
    lines: tuple[str, ...] = (),
) -> Path:
    """Dibuja los fotogramas del video de prueba (PNG)."""
    folder.mkdir(parents=True, exist_ok=True)
    for previous in folder.glob("*.png"):
        previous.unlink()
    title_font = ImageFont.truetype(FONT_PATH, 44)
    card_font = ImageFont.truetype(FONT_PATH, 64)
    line_font = ImageFont.truetype(FONT_PATH, 40)
    for index in range(seconds * fps):
        moment = index / fps
        image = Image.new("RGB", (width, height), (245, 245, 245))
        draw = ImageDraw.Draw(image)
        draw.text((40, 40), "VIDEO DE PRUEBA", font=title_font, fill=(20, 20, 20))
        if card_window is not None and card_window[0] <= moment <= card_window[1]:
            # 4111 1111 1111 1111 es Luhn-válida.
            draw.text(
                (60, height // 2 - 40),
                "4111 1111 1111 1111",
                font=card_font,
                fill=(0, 0, 0),
            )
        for line_index, line in enumerate(lines):
            draw.text(
                (60, height // 2 + 40 + line_index * 70),
                line,
                font=line_font,
                fill=(0, 0, 0),
            )
        image.save(folder / f"f{index:04d}.png")
    return folder


def _encode(
    folder: Path,
    target: Path,
    *,
    fps: int,
    cbr_bitrate: str | None = None,
) -> bytes:
    """Codifica los PNG en un mp4 real; CBR infla el archivo sin tocar el texto."""
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(folder / "f%04d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
    ]
    if cbr_bitrate is None:
        command += ["-crf", "23"]
    else:
        command += [
            "-b:v",
            cbr_bitrate,
            "-minrate",
            cbr_bitrate,
            "-maxrate",
            cbr_bitrate,
            "-bufsize",
            "4M",
            "-x264-params",
            "nal-hrd=cbr:force-cfr=1",
        ]
    command.append(str(target))
    result = subprocess.run(command, capture_output=True, timeout=180)
    assert result.returncode == 0, (
        "ffmpeg no pudo generar el video de prueba: "
        + result.stderr.decode("utf-8", "replace")[-500:]
    )
    return target.read_bytes()


@pytest.fixture(scope="session")
def videos(tmp_path_factory: pytest.TempPathFactory) -> dict[str, bytes]:
    """Genera una sola vez los mp4 reales que usan todos los casos."""
    root = tmp_path_factory.mktemp("prv02-videos")
    fps = 5
    seconds = 6
    card_window = (2.5, 3.5)

    card = _encode(
        _frames(
            root / "card",
            width=1280,
            height=360,
            seconds=seconds,
            fps=fps,
            card_window=card_window,
        ),
        root / "card.mp4",
        fps=fps,
    )
    clean = _encode(
        _frames(
            root / "clean",
            width=640,
            height=360,
            seconds=seconds,
            fps=fps,
            card_window=None,
        ),
        root / "clean.mp4",
        fps=fps,
    )
    invoice = _encode(
        _frames(
            root / "invoice",
            width=640,
            height=360,
            seconds=seconds,
            fps=fps,
            card_window=None,
            lines=("FACTURA", "TOTAL A PAGAR 1500"),
        ),
        root / "invoice.mp4",
        fps=fps,
    )
    # > 1 MiB y < 20 MiB: el tope de descarga real (20 MiB) no interviene.
    large_clean = _encode(
        _frames(
            root / "large-clean",
            width=1280,
            height=720,
            seconds=seconds,
            fps=fps,
            card_window=None,
        ),
        root / "large_clean.mp4",
        fps=fps,
        cbr_bitrate="2M",
    )
    large_card = _encode(
        _frames(
            root / "large-card",
            width=1280,
            height=720,
            seconds=seconds,
            fps=fps,
            card_window=card_window,
        ),
        root / "large_card.mp4",
        fps=fps,
        cbr_bitrate="2M",
    )
    assert b"ftyp" in card[:32], "el insumo no es un mp4 real"
    assert len(large_clean) > 1024 * 1024, "el video grande debe superar 1 MiB"
    assert len(large_clean) < 20 * 1024 * 1024
    assert len(large_card) > 1024 * 1024
    # Video de 36 s: excede la ventana de 30 s (un cuadro por segundo) y no se
    # puede revisar completo ⇒ debe bloquearse sin llamar al proveedor.
    long_clean = _encode(
        _frames(
            root / "long-clean",
            width=640,
            height=360,
            seconds=36,
            fps=2,
            card_window=None,
        ),
        root / "long_clean.mp4",
        fps=2,
    )
    return {
        "card": card,
        "clean": clean,
        "invoice": invoice,
        "large_clean": large_clean,
        "large_card": large_card,
        "long_clean": long_clean,
    }


# ---------------------------------------------------------------------------
# Base de datos: acotar, leer y limpiar solo lo propio
# ---------------------------------------------------------------------------


async def _assert_clean(session_factory: Any, chat_id: int) -> None:
    async with session_factory() as session:
        vip = await session.execute(
            text("select count(*) from vips where telegram_user_id = :uid"),
            {"uid": chat_id},
        )
        assert vip.scalar_one() == 0, (
            f"el id de prueba {chat_id} ya existe en vips; elegir otro"
        )
        history = await session.execute(
            text("select count(*) from message_history where chat_id = :cid"),
            {"cid": chat_id},
        )
        assert history.scalar_one() == 0, (
            f"el chat de prueba {chat_id} ya tiene historial; elegir otro"
        )
        turns = await session.execute(
            text("select count(*) from turns where chat_id = :cid"),
            {"cid": chat_id},
        )
        assert turns.scalar_one() == 0, (
            f"el chat de prueba {chat_id} ya tiene turnos; elegir otro"
        )


async def _persisted_text(
    session_factory: Any, chat_id: int, telegram_message_id: int
) -> str | None:
    async with session_factory() as session:
        result = await session.execute(
            text(
                "select text from message_history "
                "where chat_id = :cid and role = 'vip' "
                "and telegram_message_id = :mid "
                "order by id desc limit 1"
            ),
            {"cid": chat_id, "mid": telegram_message_id},
        )
        return result.scalar_one_or_none()


async def _turn_state(session_factory: Any, chat_id: int) -> tuple[int, Any, Any]:
    async with session_factory() as session:
        result = await session.execute(
            text(
                "select count(*), max(vip_id::text), max(status) "
                "from turns where chat_id = :cid"
            ),
            {"cid": chat_id},
        )
        row = result.one()
        return int(row[0]), row[1], row[2]


# Hijos de un turno que no llevan chat_id: se borran antes que ``turns``.
_TURN_CHILD_TABLES = ("escalation_events", "staging_candidates", "owner_marks")
# Llevan chat_id y FK a turns: antes que ``turns``.
_TURN_CHAT_TABLES = (
    "pipeline_traces",
    "pending_deliveries",
    "pending_approvals",
    "gray_zone_queries",
    "turn_category_log",
)
# Llevan chat_id sin FK a turns.
_PLAIN_CHAT_TABLES = (
    "contexts",
    "backfill_queue",
    "promo_executions",
    "daily_message_limits",
    "atencion_cycles",
    "message_history",
)
# Llevan vip_id y FK a turns: antes que ``turns``.
_VIP_TURN_TABLES = ("emotional_signal_log", "turn_outcome_log")
# Llevan vip_id y FK a vips: antes que ``vips``.
_VIP_TABLES = (
    "vip_profile",
    "vip_profile_history",
    "vip_mood_state",
    "vip_trust_budget",
    "profile_synthesis_queue",
    "memories",
    "policies",
    "examples",
    "learning_metrics",
    "recontact_schedules",
)


async def _cleanup(session_factory: Any, chat_id: int) -> None:
    """Borra solo las filas del chat/vip de esta prueba (ids propios).

    Orden explícito por dependencias: primero los hijos del turno, después las
    tablas por ``chat_id``, luego ``turns`` y por último ``vips``.
    """
    by_turn = "where turn_id in (select id from turns where chat_id = :cid)"
    by_vip = (
        "where vip_id in (select id from vips where telegram_user_id = :cid)"
    )
    statements = [
        (f"delete from {table} {by_turn}", {"cid": chat_id})
        for table in _TURN_CHILD_TABLES
    ]
    statements += [
        (f"delete from {table} {by_vip}", {"cid": chat_id})
        for table in _VIP_TURN_TABLES
    ]
    statements += [
        (f"delete from {table} where chat_id = :cid", {"cid": chat_id})
        for table in _TURN_CHAT_TABLES + _PLAIN_CHAT_TABLES
    ]
    statements.append(("delete from turns where chat_id = :cid", {"cid": chat_id}))
    statements += [
        (f"delete from {table} {by_vip}", {"cid": chat_id})
        for table in _VIP_TABLES
    ]
    statements.append(
        ("delete from vips where telegram_user_id = :cid", {"cid": chat_id})
    )
    async with session_factory() as session:
        for sql, params in statements:
            try:
                async with session.begin_nested():
                    await session.execute(text(sql), params)
            except Exception:
                # Una tabla nueva/renombrada no debe enmascarar el resultado.
                continue
        await session.commit()
        left = await session.execute(
            text(
                "select (select count(*) from vips "
                "where telegram_user_id = :cid) "
                "+ (select count(*) from message_history where chat_id = :cid) "
                "+ (select count(*) from turns where chat_id = :cid)"
            ),
            {"cid": chat_id},
        )
        assert left.scalar_one() == 0, (
            f"la limpieza dejó filas propias del chat de prueba {chat_id}"
        )


# ---------------------------------------------------------------------------
# Arranque del escenario
# ---------------------------------------------------------------------------


def _pipeline_llm() -> FakeLLM:
    """LLM doble que permite completar el pipeline real hasta la cola de la dueña.

    El texto del turno no cambia (lo que se prueba es la visión), pero así el
    turno termina en ``pending_approval`` y no en un fallo posterior.
    """
    return FakeLLM(
        structured_responses=[
            Comprehension(
                intent="compartir_media",
                topics=[],
                emotion="neutral",
                urgency="baja",
                risk="bajo",
                needs_memory=False,
                needs_policy=False,
                needs_schedule=False,
                needs_examples=False,
                needs_history=False,
                needs_context=False,
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
        text_responses=["Borrador de prueba para el turno."],
    )


def _settings(test_settings: Settings, **updates: Any) -> Settings:
    base: dict[str, Any] = {
        "gemini_api_key": SecretStr("clave-gemini-de-prueba"),
        "feature_video_vision_enabled": True,
        "feature_image_vision_enabled": False,
        "video_vision_max_frames": 30,
        "video_vision_send_max_bytes": 20 * 1024 * 1024,
        "video_vision_frames_sent": 20,
        "log_level": "WARNING",
    }
    base.update(updates)
    return test_settings.model_copy(update=base)


def _video_update(
    chat_id: int,
    *,
    file_id: str,
    payload: bytes,
    caption: str | None,
    declared_size: int,
    message_id: int,
    update_id: int,
) -> Update:
    width, height = 640, 360
    message = Message(
        message_id=message_id,
        date=datetime(2026, 10, 24, 12, 0, 0),
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=chat_id, is_bot=False, first_name="VIP de prueba"),
        video=Video(
            file_id=file_id,
            file_unique_id=f"uniq-{file_id}",
            width=width,
            height=height,
            duration=6,
            file_size=declared_size,
            mime_type="video/mp4",
        ),
        caption=caption,
        business_connection_id=BUSINESS_CONNECTION_ID,
    )
    return Update(update_id=update_id, business_message=message)


@dataclass
class ScenarioResult:
    provider: RecordingVisionProvider
    downloader: RecordingDownloader
    persisted: str | None
    turn_count: int
    turn_vip_id: Any
    turn_status: Any


async def _run_scenario(
    *,
    engine: Any,
    session_factory: Any,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    chat_id: int,
    payload: bytes,
    caption: str | None = None,
    declared_size: int | None = None,
    provider: RecordingVisionProvider | None = None,
    settings_updates: dict[str, Any] | None = None,
    path_dir: Path | None = None,
    message_id: int = 701,
    update_id: int = 900_701,
) -> ScenarioResult:
    """Arma la app con las banderas del caso, alimenta el handler y lee el efecto."""
    await _assert_clean(session_factory, chat_id)
    provider = provider or RecordingVisionProvider()
    file_id = f"file-prv02-{chat_id}"
    downloader = RecordingDownloader({file_id: payload})
    settings = _settings(test_settings, **(settings_updates or {}))

    monkeypatch.setattr(
        "diana.composition.GeminiVisionProvider", lambda **_: provider
    )
    monkeypatch.setattr(
        "diana.composition.download_media_bytes", downloader
    )
    bot = Bot(token=TOKEN)
    bot.session = SpyBotSession()  # type: ignore[assignment]
    app = build_app(
        settings,
        bot=bot,
        llm=_pipeline_llm(),
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    if path_dir is not None:
        monkeypatch.setenv("PATH", str(path_dir))

    try:
        await app.vips.add(chat_id, display_name="Prueba C-PRV-02")
        update = _video_update(
            chat_id,
            file_id=file_id,
            payload=payload,
            caption=caption,
            declared_size=declared_size if declared_size is not None else len(payload),
            message_id=message_id,
            update_id=update_id,
        )
        await app.dispatcher.feed_update(bot, update)
        persisted = await _persisted_text(session_factory, chat_id, message_id)
        turn_count, turn_vip_id, turn_status = await _turn_state(
            session_factory, chat_id
        )
        # El turno tiene que completar el pipeline real: si muriera antes, el
        # texto persistido seguiría ahí y la prueba sería engañosa.
        assert turn_count == 1, f"se esperaba un turno, hay {turn_count}"
        assert turn_vip_id is not None, "el turno quedó sin VIP"
        assert turn_status == "pending_approval", (
            f"el turno no completó el pipeline: status={turn_status!r}"
        )
        assert persisted, "el texto del turno no quedó persistido"
        return ScenarioResult(
            provider=provider,
            downloader=downloader,
            persisted=persisted,
            turn_count=turn_count,
            turn_vip_id=turn_vip_id,
            turn_status=turn_status,
        )
    finally:
        await _cleanup(session_factory, chat_id)


def _review_locally(video_bytes: bytes) -> list[str]:
    """Revisión real (ffmpeg + OCR + política) para no asertar sobre un caso vacío."""
    frames = FfmpegFrameExtractor(max_frames=30).extract_frames(video_bytes)
    ocr = OcrEngine()
    return [ocr.extract_text(frame.png_bytes) for frame in frames]


# ---------------------------------------------------------------------------
# Casos
# ---------------------------------------------------------------------------


async def test_dato_fuerte_en_un_fotograma_intermedio_bloquea_el_video(
    engine, session_factory, test_settings, monkeypatch, videos
) -> None:
    """Caso 1: tarjeta visible solo en el segundo 3 ⇒ no sale, cero llamadas."""
    # El insumo realmente contiene el dato: sin esto la prueba podría pasar por
    # un OCR que no leyó nada (reason no_verificable) y no por la tarjeta.
    textos = _review_locally(videos["card"])
    fuertes = [scan for scan in map(scan_sensitive, textos) if scan.strong]
    assert fuertes and fuertes[0].reason == "tarjeta", (
        "el OCR real no detectó la tarjeta del fotograma intermedio; "
        f"textos vistos: {[t[:60] for t in textos]}"
    )

    result = await _run_scenario(
        engine=engine,
        session_factory=session_factory,
        test_settings=test_settings,
        monkeypatch=monkeypatch,
        chat_id=CHAT_CARD,
        payload=videos["card"],
    )

    assert result.persisted == SENSITIVE_TEXT, (
        f"el turno no quedó marcado como sensible: {result.persisted!r}"
    )
    assert result.provider.calls == [], (
        "salió una llamada al proveedor con un fotograma sensible: "
        f"{[(c.kind, c.mime_type, len(c.payloads)) for c in result.provider.calls]}"
    )
    assert result.downloader.calls, "el video con visión ON ni siquiera se descargó"
    assert result.turn_count == 1 and result.turn_vip_id is not None, (
        "el turno no quedó persistido con su VIP"
    )


async def test_video_grande_manda_solo_los_cuadros_ya_revisados(
    engine, session_factory, test_settings, monkeypatch, videos
) -> None:
    """Caso 2: > send_max_bytes ⇒ una sola llamada con cuadros revisados."""
    provider = RecordingVisionProvider(response="un paisaje nublado")
    result = await _run_scenario(
        engine=engine,
        session_factory=session_factory,
        test_settings=test_settings,
        monkeypatch=monkeypatch,
        chat_id=CHAT_FRAMES,
        payload=videos["large_clean"],
        provider=provider,
        settings_updates={
            "video_vision_send_max_bytes": 1024 * 1024,
            "video_vision_frames_sent": 3,
        },
    )

    kinds = [call.kind for call in result.provider.calls]
    assert kinds == ["images"], (
        f"el archivo completo viajó o hubo más de una llamada: {kinds}"
    )
    call = result.provider.calls[0]
    assert 1 <= len(call.payloads) <= 3, (
        f"se enviaron {len(call.payloads)} cuadros y el tope era 3"
    )
    for payload in call.payloads:
        assert payload != videos["large_clean"], "viajó el archivo completo"
        # El par bytes/MIME es coherente (JPEG rotulado JPEG), no un PNG
        # rotulado JPEG como antes.
        assert payload.startswith(JPEG_MAGIC), (
            "el cuadro enviado no es JPEG aunque el MIME declarado es image/jpeg"
        )
    assert call.mime_type == "image/jpeg"
    assert result.persisted == "[video: un paisaje nublado]"


async def test_video_grande_con_un_cuadro_sensible_no_llama_al_proveedor(
    engine, session_factory, test_settings, monkeypatch, videos
) -> None:
    """Caso 2 (variante): aunque el video sea grande, un dato fuerte lo deja fuera."""
    textos = _review_locally(videos["large_card"])
    assert any(scan_sensitive(texto).strong for texto in textos), (
        "el OCR real no detectó la tarjeta del video grande; el caso estaría vacío"
    )
    result = await _run_scenario(
        engine=engine,
        session_factory=session_factory,
        test_settings=test_settings,
        monkeypatch=monkeypatch,
        chat_id=CHAT_FRAMES_SENSITIVE,
        payload=videos["large_card"],
        settings_updates={
            "video_vision_send_max_bytes": 1024 * 1024,
            "video_vision_frames_sent": 3,
        },
    )

    assert result.persisted == SENSITIVE_TEXT
    assert result.provider.calls == [], "un video grande con tarjeta salió al proveedor"


async def test_video_declarado_mayor_al_tope_no_se_descarga(
    engine, session_factory, test_settings, monkeypatch, videos
) -> None:
    """Caso 3: 25 MiB declarados ⇒ ni descarga, ni cuadros, ni proveedor."""
    result = await _run_scenario(
        engine=engine,
        session_factory=session_factory,
        test_settings=test_settings,
        monkeypatch=monkeypatch,
        chat_id=CHAT_TOO_LARGE,
        payload=videos["clean"],
        caption="mira esto",
        declared_size=25 * 1024 * 1024,
    )

    assert result.downloader.calls == [], "se descargó un video por encima del tope"
    assert result.provider.calls == []
    assert result.persisted == "[video] mira esto"


async def test_video_de_mas_de_30_segundos_se_bloquea_sin_llamar_al_proveedor(
    engine, session_factory, test_settings, monkeypatch, videos, caplog
) -> None:
    """Caso 3b: 36 s ⇒ la cobertura no se puede garantizar, el video NO sale.

    Antes el tope de 30 cuadros bajaba el muestreo y un dato entre muestras
    pasaba como limpio. Decisión de la dueña (2026-10-24): si no se puede
    revisar a un cuadro por segundo, el video se bloquea.
    """
    caplog.set_level(logging.WARNING, logger="diana.application")
    result = await _run_scenario(
        engine=engine,
        session_factory=session_factory,
        test_settings=test_settings,
        monkeypatch=monkeypatch,
        chat_id=CHAT_TOO_LONG,
        payload=videos["long_clean"],
    )

    assert result.persisted == SENSITIVE_TEXT, (
        f"un video de 36 s no quedó bloqueado: {result.persisted!r}"
    )
    assert result.provider.calls == [], (
        "un video que excede la ventana cubierta salió al proveedor"
    )
    assert result.downloader.calls, "el video ni siquiera se descargó"
    assert any(
        record.message == "video_vision_coverage_incomplete"
        and getattr(record, "reason", None) == "too_long"
        for record in caplog.records
        if record.name == "diana.application"
    ), "el bloqueo no vino de la cobertura incompleta que este caso provoca"
    assert result.turn_count == 1 and result.turn_status == "pending_approval"


async def test_ffmpeg_ausente_cierra_sin_llamar_al_proveedor(
    engine, session_factory, test_settings, monkeypatch, videos, tmp_path, caplog
) -> None:
    """Caso 4: sin ffmpeg/ffprobe en PATH ⇒ sensible y el turno no se cuelga."""
    caplog.set_level(logging.WARNING, logger="diana.application")
    empty_bin = tmp_path / "sin-ffmpeg"
    empty_bin.mkdir()
    result = await _run_scenario(
        engine=engine,
        session_factory=session_factory,
        test_settings=test_settings,
        monkeypatch=monkeypatch,
        chat_id=CHAT_NO_FFMPEG,
        payload=videos["clean"],
        path_dir=empty_bin,
    )

    assert result.persisted == SENSITIVE_TEXT
    assert result.provider.calls == [], "sin ffmpeg el video salió al proveedor"
    assert result.turn_count == 1, "el turno no se completó (¿se colgó la extracción?)"
    # Sin ffprobe la duración es desconocida ⇒ la cobertura no se garantiza y
    # el cierre es explícito (antes el caso se confundía con un fallo de
    # extracción genérico).
    assert any(
        record.message == "video_vision_coverage_incomplete"
        and getattr(record, "reason", None) == "coverage_unknown"
        for record in caplog.records
        if record.name == "diana.application"
    ), "el cierre no vino de la cobertura no garantizable que este caso provoca"


@pytest.mark.parametrize(
    ("video_on", "chat_id", "expected_text", "expect_provider_call"),
    [
        (True, CHAT_MATRIX_ON, "[video: una escena de prueba] con texto", True),
        (False, CHAT_FLAG_OFF, "[video] con texto", False),
    ],
    ids=["bandera_on", "bandera_off"],
)
async def test_matriz_bandera_on_off(
    engine,
    session_factory,
    test_settings,
    monkeypatch,
    videos,
    video_on,
    chat_id,
    expected_text,
    expect_provider_call,
) -> None:
    """Caso 5: misma entrada con la bandera ON y OFF; el efecto cambia con ella.

    La foto queda encendida en los dos casos, así que el descargador está
    cableado incluso con el video apagado: la diferencia no es "no hay quien
    descargue", es la bandera de video.
    """
    provider = RecordingVisionProvider(response="una escena de prueba")
    result = await _run_scenario(
        engine=engine,
        session_factory=session_factory,
        test_settings=test_settings,
        monkeypatch=monkeypatch,
        chat_id=chat_id,
        payload=videos["clean"],
        caption="con texto",
        provider=provider,
        settings_updates={
            "feature_video_vision_enabled": video_on,
            "feature_image_vision_enabled": True,
        },
    )

    assert result.persisted == expected_text
    if expect_provider_call:
        assert [call.kind for call in result.provider.calls] == ["video"]
        assert result.downloader.calls, "con la bandera ON no se descargó el video"
    else:
        assert result.downloader.calls == [], (
            "con la bandera de video apagada se descargó el archivo"
        )
        assert result.provider.calls == [], (
            "con la bandera de video apagada se llamó al proveedor"
        )


async def test_ocr_ausente_cierra_sin_llamar_al_proveedor(
    engine, session_factory, test_settings, monkeypatch, videos, tmp_path, caplog
) -> None:
    """Caso 6: ffmpeg presente pero tesseract fuera de PATH ⇒ sensible."""
    # La extracción SÍ puede correr con este video (el único cambio será el OCR).
    assert len(_review_locally(videos["clean"])) == 6
    caplog.set_level(logging.WARNING, logger="diana.infrastructure.vision")
    caplog.set_level(logging.WARNING, logger="diana.application")
    binaries = tmp_path / "sin-tesseract"
    binaries.mkdir()
    (binaries / "ffmpeg").symlink_to("/usr/bin/ffmpeg")
    (binaries / "ffprobe").symlink_to("/usr/bin/ffprobe")
    result = await _run_scenario(
        engine=engine,
        session_factory=session_factory,
        test_settings=test_settings,
        monkeypatch=monkeypatch,
        chat_id=CHAT_NO_OCR,
        payload=videos["clean"],
        path_dir=binaries,
    )

    assert result.persisted == SENSITIVE_TEXT
    assert result.provider.calls == [], "sin OCR el video salió al proveedor"
    failed = [
        record.message
        for record in caplog.records
        if record.message in {"video_frames_command_failed", "video_vision_frames_failed"}
    ]
    assert failed == [], (
        f"la extracción falló y no fue el OCR lo que cerró el caso: {failed}"
    )


async def test_video_corrupto_cierra_sin_llamar_al_proveedor(
    engine, session_factory, test_settings, monkeypatch
) -> None:
    """Caso 7: bytes que no son video ⇒ cero cuadros ⇒ sensible."""
    result = await _run_scenario(
        engine=engine,
        session_factory=session_factory,
        test_settings=test_settings,
        monkeypatch=monkeypatch,
        chat_id=CHAT_CORRUPT,
        payload=b"esto no es un video, es texto plano" * 100,
    )

    assert result.persisted == SENSITIVE_TEXT
    assert result.provider.calls == [], "un video ilegible salió al proveedor"


async def test_factura_sola_viaja_igual_que_en_fotos(
    engine, session_factory, test_settings, monkeypatch, videos
) -> None:
    """Caso 8: factura/recibo sin datos fuertes ⇒ se describe."""
    textos = _review_locally(videos["invoice"])
    scans = list(map(scan_sensitive, textos))
    assert any(scan.receipt for scan in scans), "el OCR real no leyó la factura"
    assert not any(scan.strong or scan.has_identity for scan in scans), (
        "el video de factura contiene, sin querer, un dato fuerte"
    )

    provider = RecordingVisionProvider(response="un comprobante de pago")
    result = await _run_scenario(
        engine=engine,
        session_factory=session_factory,
        test_settings=test_settings,
        monkeypatch=monkeypatch,
        chat_id=CHAT_INVOICE,
        payload=videos["invoice"],
        provider=provider,
    )

    assert [call.kind for call in result.provider.calls] == ["video"]
    assert result.provider.calls[0].payloads[0] == videos["invoice"]
    assert result.persisted == "[video: un comprobante de pago]"


async def test_el_caption_no_decide_la_privacidad_del_video(
    engine, session_factory, test_settings, monkeypatch, videos
) -> None:
    """Caso 9a: caption con tarjeta + cuadros limpios ⇒ el video viaja."""
    caption = "mi tarjeta es 4111 1111 1111 1111"
    provider = RecordingVisionProvider(response="una persona saludando")
    result = await _run_scenario(
        engine=engine,
        session_factory=session_factory,
        test_settings=test_settings,
        monkeypatch=monkeypatch,
        chat_id=CHAT_CAPTION_CARD,
        payload=videos["clean"],
        caption=caption,
        provider=provider,
    )

    assert [call.kind for call in result.provider.calls] == ["video"], (
        "el caption (texto) bloqueó o desvió la revisión del video"
    )
    call = result.provider.calls[0]
    assert call.payloads == [videos["clean"]]
    assert caption not in call.prompt, "el caption viajó dentro del prompt de visión"
    assert result.persisted == f"[video: una persona saludando] {caption}"


async def test_tarjeta_en_cuadro_con_caption_inocente_queda_bloqueada(
    engine, session_factory, test_settings, monkeypatch, videos
) -> None:
    """Caso 9b: caption inocente + tarjeta en un cuadro ⇒ no sale."""
    textos = _review_locally(videos["card"])
    assert any(scan_sensitive(texto).strong for texto in textos), (
        "el OCR real no detectó la tarjeta; el caso estaría vacío"
    )
    result = await _run_scenario(
        engine=engine,
        session_factory=session_factory,
        test_settings=test_settings,
        monkeypatch=monkeypatch,
        chat_id=CHAT_CARD_INNOCENT_CAPTION,
        payload=videos["card"],
        caption="hola, mira",
    )

    assert result.provider.calls == []
    assert result.persisted == f"{SENSITIVE_TEXT} hola, mira"


async def test_rama_de_cuadros_manda_jpeg_coherente(
    engine, session_factory, test_settings, monkeypatch, videos
) -> None:
    """Caso 10: el par bytes/MIME de la rama de cuadros es coherente.

    Antes viajaba un PNG rotulado ``image/jpeg``. Ahora los cuadros se
    convierten a JPEG (o, si no se puede, viajan como PNG rotulado PNG): lo
    que se declara es lo que se envía.
    """
    result = await _run_scenario(
        engine=engine,
        session_factory=session_factory,
        test_settings=test_settings,
        monkeypatch=monkeypatch,
        chat_id=CHAT_PNG_MIME,
        payload=videos["clean"],
        provider=RecordingVisionProvider(response="una escena"),
        settings_updates={
            "video_vision_send_max_bytes": 1,
            "video_vision_frames_sent": 2,
        },
    )

    assert [call.kind for call in result.provider.calls] == ["images"]
    call = result.provider.calls[0]
    assert call.mime_type == "image/jpeg", (
        f"el mime enviado cambió: {call.mime_type!r}"
    )
    assert call.payloads, "no viajó ningún cuadro"
    for payload in call.payloads:
        assert payload.startswith(JPEG_MAGIC), (
            "el MIME dice image/jpeg pero los bytes no son JPEG"
        )
        with Image.open(io.BytesIO(payload)) as img:
            assert img.format == "JPEG"
    # El efecto no falla si el proveedor acepta el par: la descripción entra.
    assert result.persisted == "[video: una escena]"


async def test_rama_de_cuadros_termina_en_fail_open_si_el_proveedor_rechaza(
    engine, session_factory, test_settings, monkeypatch, videos
) -> None:
    """Caso 10b: un rechazo del proveedor pierde la descripción (fail-open)."""
    result = await _run_scenario(
        engine=engine,
        session_factory=session_factory,
        test_settings=test_settings,
        monkeypatch=monkeypatch,
        chat_id=CHAT_PNG_FAILOPEN,
        payload=videos["clean"],
        provider=RecordingVisionProvider(
            fail_with=RuntimeError("el proveedor rechaza la llamada")
        ),
        settings_updates={
            "video_vision_send_max_bytes": 1,
            "video_vision_frames_sent": 2,
        },
    )

    assert [call.kind for call in result.provider.calls] == ["images"], (
        "la llamada con los cuadros no ocurrió: no se probó el fail-open"
    )
    assert all(p.startswith(JPEG_MAGIC) for p in result.provider.calls[0].payloads)
    assert result.persisted == "[video]", (
        "el efecto no fue fail-open: la descripción se perdió pero el texto cambió"
    )
