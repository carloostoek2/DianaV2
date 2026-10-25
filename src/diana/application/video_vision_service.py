"""VideoVisionService — revisión local de privacidad + descripción de un video.

Capa de aplicación (solo orquesta; no genera texto de negocio).

Un video no se puede "tapar" como una foto: o viaja completo o no viaja. Por eso
el criterio es de semáforo, con la misma revisión local de siempre:

1. Se extraen unos pocos fotogramas en el servidor (ffmpeg) y se les aplica el
   mismo reconocimiento de texto y las mismas reglas de sensibilidad que a las
   fotos (``image_vision_service.scan_sensitive``).
2. Si algún fotograma muestra un documento de identidad o datos fuertes
   (tarjeta, cuenta, clave), el video no sale: queda para revisión manual de la
   dueña, igual que una foto de documento.
3. Si los fotogramas están limpios, el video viaja completo y se describe con
   la capa cognitiva (Gemini).

Cierra ante la duda: si no se pueden extraer fotogramas o el texto no es
legible, el video se marca sensible y no sale del servidor. Abre ante un fallo
de descripción: el turno sigue con la etiqueta plana de media.

Los bytes del video y los fotogramas nunca se guardan: solo entra al pipeline el
texto de la descripción.
"""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from typing import Callable

from PIL import Image

from diana.application.image_vision_service import (
    SensitiveScan,
    evidence_is_unverifiable,
    record_vision_activity,
    scan_sensitive,
    text_is_scarce,
)
from diana.cognitive.video_vision import VideoDescriber
from diana.infrastructure.vision.ocr import OcrEngine, OcrUnavailableError
from diana.infrastructure.vision.resize import downscale_image
from diana.infrastructure.vision.video_frames import (
    FrameExtractionError,
    FrameExtractor,
    FrameReviewIncompleteError,
    VideoFrame,
)

# Un video más pesado que esto no entra en un solo envío al proveedor: en su
# lugar viajan los cuadros ya revisados localmente (nunca el archivo completo).
_DEFAULT_SEND_MAX_BYTES = 20 * 1024 * 1024
# Cuadros que se envían como máximo en ese caso.
_DEFAULT_FRAMES_TO_SEND = 20
# Calidad del JPEG al que se convierten los cuadros que viajan.
_FRAME_JPEG_QUALITY = 82
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

logger = logging.getLogger("diana.application")


@dataclass(frozen=True, slots=True)
class VideoVisionResult:
    """Resultado de analizar un video entrante.

    ``enabled=False`` ⇒ función apagada ⇒ quien llama conserva la etiqueta
    plana de media.
    ``sensitive=True`` ⇒ no se envió a Google; la dueña lo revisa a mano.
    ``description`` solo se llena cuando los fotogramas estaban limpios.
    """

    enabled: bool
    sensitive: bool | None = None
    reason: str | None = None
    description: str | None = None


class VideoVisionService:
    """Orquesta la revisión por fotogramas y la descripción de un video."""

    def __init__(
        self,
        *,
        frames: FrameExtractor,
        ocr: OcrEngine,
        describer: VideoDescriber | None,
        enabled: bool,
        scan: Callable[[str], SensitiveScan] = scan_sensitive,
        send_max_bytes: int = _DEFAULT_SEND_MAX_BYTES,
        frames_to_send: int = _DEFAULT_FRAMES_TO_SEND,
    ) -> None:
        self._frames = frames
        self._ocr = ocr
        self._describer = describer
        self._enabled = bool(enabled) and describer is not None
        self._scan = scan
        self._send_max_bytes = max(1, int(send_max_bytes))
        self._frames_to_send = max(1, int(frames_to_send))

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def analyze(self, video_bytes: bytes, *, mime_type: str) -> VideoVisionResult:
        """Analiza un video. Cierra ante la duda; abre si falla la descripción."""
        if not self._enabled:
            return VideoVisionResult(enabled=False)
        record_vision_activity("video", "analyzed")
        # 1) y 2) Revisión local (ffmpeg + OCR), fuera del hilo del bot: con un
        #    video largo son varios segundos de trabajo y bloquear ese hilo
        #    retrasaría los demás chats.
        blocked, frames = await asyncio.to_thread(self._review_frames, video_bytes)
        if blocked is not None:
            record_vision_activity("video", "sensitive")
            return blocked
        # 3) Cuadros limpios ⇒ se describe el video. Si es demasiado pesado para
        #    viajar entero, viajan los cuadros ya revisados (una sola llamada).
        if len(video_bytes) > self._send_max_bytes:
            description = await self._describe_by_frames(frames)
        else:
            description = await self._describer.describe(
                video_bytes, mime_type=mime_type
            )
        if description is not None:
            record_vision_activity("video", "described")
        return VideoVisionResult(
            enabled=True,
            sensitive=False,
            reason=None,
            description=description,
        )

    async def _describe_by_frames(self, frames: tuple[VideoFrame, ...]) -> str | None:
        """Describe el video con los cuadros ya revisados, en un solo envío.

        Los cuadros se reducen antes de salir: veinte cuadros a resolución
        completa no entran en un pedido, y el costo por cuadro no cambia. El
        par bytes/MIME se mantiene verdadero: si TODOS se pueden convertir a
        JPEG viaja ``image/jpeg``; si no, viajan los PNG originales rotulados
        ``image/png``. Nunca un PNG rotulado JPEG.
        """
        selected = _spread(frames, self._frames_to_send)
        payloads, mime_type = _prepare_frames(selected)
        logger.info(
            "video_vision_describe_by_frames",
            extra={
                "frames": len(payloads),
                "extracted": len(frames),
                "mime_type": mime_type,
            },
        )
        return await self._describer.describe_frames(
            payloads, mime_type=mime_type
        )

    def _review_frames(
        self, video_bytes: bytes
    ) -> tuple[VideoVisionResult | None, tuple[VideoFrame, ...]]:
        """Mira los fotogramas localmente.

        Devuelve ``(resultado, cuadros)``: el resultado es ``sensitive`` cuando
        algo impide enviar el video, y ``None`` cuando está limpio (los cuadros
        quedan disponibles por si hay que describirlo sin mandar el archivo).
        """
        try:
            frames = self._frames.extract_frames(video_bytes)
        except FrameReviewIncompleteError as exc:
            # Duración > ventana cubierta o duración desconocida / ffprobe
            # ausente: no se puede garantizar la cobertura ⇒ no sale.
            logger.warning(
                "video_vision_coverage_incomplete",
                extra={"reason": exc.reason, "error_type": type(exc).__name__},
            )
            return (
                VideoVisionResult(
                    enabled=True, sensitive=True, reason=exc.reason
                ),
                (),
            )
        except FrameExtractionError as exc:
            logger.warning(
                "video_vision_frames_failed",
                extra={"error_type": type(exc).__name__},
            )
            return (
                VideoVisionResult(
                    enabled=True, sensitive=True, reason="no_verificable"
                ),
                (),
            )
        if not frames:
            # Sin un solo fotograma no hay nada que revisar: no se envía a
            # ciegas.
            logger.warning("video_vision_no_frames")
            return (
                VideoVisionResult(
                    enabled=True, sensitive=True, reason="no_verificable"
                ),
                (),
            )
        for frame in frames:
            try:
                text = self._ocr.extract_text(frame.png_bytes)
            except OcrUnavailableError:
                return (
                    VideoVisionResult(
                        enabled=True, sensitive=True, reason="no_verificable"
                    ),
                    (),
                )
            # Texto vacío o escaso: la sonda local decide si el cuadro se pudo
            # verificar (borroso / plano / marcas ilegibles). Un cuadro que no
            # se puede verificar bloquea el video, igual que en las fotos.
            if text_is_scarce(text) and self._frame_is_unverifiable(
                frame, text_seen=bool(text.strip())
            ):
                return (
                    VideoVisionResult(
                        enabled=True, sensitive=True, reason="no_verificable"
                    ),
                    (),
                )
            scan = self._scan(text)
            if scan.has_identity:
                return (
                    VideoVisionResult(
                        enabled=True, sensitive=True, reason="identidad"
                    ),
                    (),
                )
            if scan.strong:
                return (
                    VideoVisionResult(
                        enabled=True, sensitive=True, reason=scan.reason
                    ),
                    (),
                )
        return None, frames

    def _frame_is_unverifiable(self, frame: VideoFrame, *, text_seen: bool) -> bool:
        """Sonda local de un cuadro con texto vacío o escaso (M1).

        Un doble de OCR sin ``probe_image`` conserva la conducta anterior
        (texto escaso ⇒ limpio); el motor real siempre la ofrece y una sonda
        caída cierra en sensible.
        """
        probe = getattr(self._ocr, "probe_image", None)
        if probe is None:
            return False
        try:
            evidence = probe(frame.png_bytes)
        except OcrUnavailableError:
            return True
        return evidence_is_unverifiable(evidence, text_seen=text_seen)


def _spread(frames: tuple[VideoFrame, ...], count: int) -> list[VideoFrame]:
    """Elige hasta ``count`` cuadros repartidos por todo el video."""
    if len(frames) <= count:
        return list(frames)
    step = len(frames) / count
    return [frames[int(index * step)] for index in range(count)]


def _to_jpeg(image_bytes: bytes) -> bytes | None:
    """Re-encode a frame to JPEG; ``None`` when it cannot be decoded/encoded."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            buffer = io.BytesIO()
            img.convert("RGB").save(
                buffer, format="JPEG", quality=_FRAME_JPEG_QUALITY
            )
            return buffer.getvalue()
    except Exception:
        return None


def _prepare_frames(
    frames: list[VideoFrame],
) -> tuple[list[bytes], str]:
    """Return (payloads, truthful mime) for the frames that travel.

    All frames are converted to JPEG (downscaled when large). If any frame
    cannot be converted, the whole batch travels as the original PNGs — the
    declared MIME always matches the bytes.
    """
    converted = [
        downscale_image(frame.png_bytes) or _to_jpeg(frame.png_bytes)
        for frame in frames
    ]
    if converted and all(payload is not None for payload in converted):
        payloads = [payload for payload in converted if payload is not None]
        return payloads, "image/jpeg"
    originals = [frame.png_bytes for frame in frames]
    return originals, _mime_for(originals)


def _mime_for(payloads: list[bytes]) -> str:
    """MIME that matches every payload (PNG or JPEG), defaulting to JPEG."""
    if payloads and all(p.startswith(_PNG_MAGIC) for p in payloads):
        return "image/png"
    if payloads and all(p.startswith(_JPEG_MAGIC) for p in payloads):
        return "image/jpeg"
    return "image/jpeg"


__all__ = ["VideoVisionResult", "VideoVisionService"]
