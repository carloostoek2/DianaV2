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
import logging
from dataclasses import dataclass
from typing import Callable

from diana.application.image_vision_service import SensitiveScan, scan_sensitive
from diana.cognitive.video_vision import VideoDescriber
from diana.infrastructure.vision.ocr import OcrEngine, OcrUnavailableError
from diana.infrastructure.vision.resize import downscale_image
from diana.infrastructure.vision.video_frames import (
    FrameExtractionError,
    FrameExtractor,
    VideoFrame,
)

# Un video más pesado que esto no entra en un solo envío al proveedor: en su
# lugar viajan los cuadros ya revisados localmente (nunca el archivo completo).
_DEFAULT_SEND_MAX_BYTES = 20 * 1024 * 1024
# Cuadros que se envían como máximo en ese caso.
_DEFAULT_FRAMES_TO_SEND = 20

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
        # 1) y 2) Revisión local (ffmpeg + OCR), fuera del hilo del bot: con un
        #    video largo son varios segundos de trabajo y bloquear ese hilo
        #    retrasaría los demás chats.
        blocked, frames = await asyncio.to_thread(self._review_frames, video_bytes)
        if blocked is not None:
            return blocked
        # 3) Cuadros limpios ⇒ se describe el video. Si es demasiado pesado para
        #    viajar entero, viajan los cuadros ya revisados (una sola llamada).
        if len(video_bytes) > self._send_max_bytes:
            description = await self._describe_by_frames(frames)
        else:
            description = await self._describer.describe(
                video_bytes, mime_type=mime_type
            )
        return VideoVisionResult(
            enabled=True,
            sensitive=False,
            reason=None,
            description=description,
        )

    async def _describe_by_frames(self, frames: tuple[VideoFrame, ...]) -> str | None:
        """Describe el video con los cuadros ya revisados, en un solo envío.

        Los cuadros se reducen antes de salir: veinte cuadros a resolución
        completa no entran en un pedido, y el costo por cuadro no cambia.
        """
        selected = _spread(frames, self._frames_to_send)
        prepared = [_prepare_frame(frame.png_bytes) for frame in selected]
        logger.info(
            "video_vision_describe_by_frames",
            extra={"frames": len(prepared), "extracted": len(frames)},
        )
        return await self._describer.describe_frames(
            [item for item in prepared if item], mime_type="image/jpeg"
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


def _spread(frames: tuple[VideoFrame, ...], count: int) -> list[VideoFrame]:
    """Elige hasta ``count`` cuadros repartidos por todo el video."""
    if len(frames) <= count:
        return list(frames)
    step = len(frames) / count
    return [frames[int(index * step)] for index in range(count)]


def _prepare_frame(png_bytes: bytes) -> bytes:
    """Reduce el cuadro antes de enviarlo; si no se puede, va tal cual."""
    return downscale_image(png_bytes) or png_bytes


__all__ = ["VideoVisionResult", "VideoVisionService"]
