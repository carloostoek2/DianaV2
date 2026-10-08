"""Extracción local de fotogramas de un video (ffmpeg).

Vive en infraestructura porque solo hace entrada y salida: recibe los bytes de
un video y devuelve unos pocos fotogramas en PNG. No decide nada sobre
privacidad y no conoce Telegram.

El video nunca se guarda de forma permanente: se copia a un directorio
temporal, se extraen los fotogramas y el directorio se borra al terminar.

Un fotograma que falla se descarta; si no se obtiene ninguno, se levanta
``FrameExtractionError`` y quien llama decide (el filtro de privacidad lo
trata como "no verificable" y el video no sale del servidor).
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("diana.infrastructure.vision")

_DEFAULT_TIMEOUT_S = 30.0
# Un cuadro por segundo: mirar solo unos instantes sueltos deja pasar cualquier
# dato que aparezca entre dos muestras. La revisión es local y no cuesta nada
# en el proveedor, así que se mira el video segundo por segundo.
_FRAMES_PER_SECOND = 1.0
# Los instantes se piden en segundos exactos: ffmpeg entrega el cuadro que
# empieza en ese segundo, así que pedir 0, 1, 2… recorre el video completo. Con
# medio segundo de más se saltaría el primer cuadro de cada segundo.
_FIRST_SAMPLE_S = 0.0
# Cuando ffprobe no informa la duración se prueban unos segundos; los cuadros
# que caigan fuera del video simplemente no se obtienen.
_UNKNOWN_DURATION_FRAMES = 10


class FrameExtractionError(RuntimeError):
    """No se pudo obtener ningún fotograma del video."""


@dataclass(frozen=True, slots=True)
class VideoFrame:
    """Un fotograma extraído, en PNG, con el segundo del video al que pertenece."""

    png_bytes: bytes
    timestamp_s: float


class FrameExtractor(Protocol):
    """Extrae fotogramas de un video (implementación real: ffmpeg)."""

    def extract_frames(self, video_bytes: bytes) -> tuple[VideoFrame, ...]: ...


class FfmpegFrameExtractor:
    """Extrae fotogramas repartidos a lo largo del video usando ffmpeg."""

    def __init__(
        self,
        *,
        max_frames: int = 30,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        ffmpeg_bin: str = "ffmpeg",
        ffprobe_bin: str = "ffprobe",
    ) -> None:
        self._max_frames = max(1, int(max_frames))
        self._timeout_s = float(timeout_s)
        self._ffmpeg = ffmpeg_bin
        self._ffprobe = ffprobe_bin

    def extract_frames(self, video_bytes: bytes) -> tuple[VideoFrame, ...]:
        """Devuelve los fotogramas obtenidos (al menos uno) o levanta error."""
        if not video_bytes:
            raise FrameExtractionError("video vacío")
        with tempfile.TemporaryDirectory(prefix="diana-video-") as tmp:
            source = Path(tmp) / "entrada.bin"
            source.write_bytes(video_bytes)
            duration = self._probe_duration(source)
            frames = self._grab_in_one_pass(source, Path(tmp), duration)
            if not frames:
                # Si el filtro no dio nada se prueba cuadro por cuadro (video
                # con metadatos raros). Es mucho más lento, por eso no es el
                # camino normal.
                frames = self._grab_one_by_one(source, Path(tmp), duration)
        if not frames:
            logger.warning(
                "video_frames_none",
                extra={"max_frames": self._max_frames},
            )
            raise FrameExtractionError("ffmpeg no produjo ningún fotograma")
        return tuple(frames)

    def _grab_in_one_pass(
        self, source: Path, tmp: Path, duration_s: float | None
    ) -> list[VideoFrame]:
        """Extrae todos los cuadros en UNA pasada de ffmpeg.

        Pedirlos de a uno obliga a ffmpeg a decodificar el video entero cada
        vez: en un archivo pesado eso son decenas de segundos. Una sola pasada
        los saca todos juntos.
        """
        rate = self._sample_rate(duration_s)
        pattern = tmp / "pasada_%04d.png"
        result = self._run(
            [
                self._ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source),
                "-vf",
                f"fps={rate:.6f}",
                "-frames:v",
                str(self._max_frames),
                "-f",
                "image2",
                "-vcodec",
                "png",
                str(pattern),
            ]
        )
        if result is None or result.returncode != 0:
            return []
        frames: list[VideoFrame] = []
        for index, path in enumerate(sorted(tmp.glob("pasada_*.png"))):
            data = path.read_bytes()
            path.unlink(missing_ok=True)
            if data:
                frames.append(
                    VideoFrame(png_bytes=data, timestamp_s=index / rate)
                )
        return frames

    def _grab_one_by_one(
        self, source: Path, tmp: Path, duration_s: float | None
    ) -> list[VideoFrame]:
        """Respaldo: pide cada cuadro por separado (lento pero tolerante)."""
        frames: list[VideoFrame] = []
        for index, stamp in enumerate(self._timestamps(duration_s)):
            png = self._grab(source, stamp, tmp / f"cuadro_{index}.png")
            if png is not None:
                frames.append(VideoFrame(png_bytes=png, timestamp_s=stamp))
        return frames

    def _sample_rate(self, duration_s: float | None) -> float:
        """Cuadros por segundo que hay que sacar para no pasar del tope.

        En un video corto es 1 (un cuadro por segundo); en uno largo baja, de
        modo que el tope se reparte por todo el video en vez de quedarse con el
        comienzo.
        """
        if duration_s is None or duration_s <= 0:
            return _FRAMES_PER_SECOND
        if duration_s <= self._max_frames:
            return _FRAMES_PER_SECOND
        return self._max_frames / duration_s

    def _timestamps(self, duration_s: float | None) -> tuple[float, ...]:
        """Segundos que se van a revisar.

        Video corto (hasta el tope): un cuadro por segundo, de punta a punta.
        Video largo: los cuadros disponibles repartidos por todo el video, para
        no quedarse solo con el comienzo.
        """
        if duration_s is None or duration_s <= 0:
            return tuple(
                float(i)
                for i in range(min(self._max_frames, _UNKNOWN_DURATION_FRAMES))
            )
        if duration_s <= self._max_frames:
            wanted = min(self._max_frames, max(1, int(duration_s)))
            stamps = tuple(
                _FIRST_SAMPLE_S + i / _FRAMES_PER_SECOND for i in range(wanted)
            )
            inside = tuple(s for s in stamps if s < duration_s)
            return inside or (duration_s / 2.0,)
        step = duration_s / self._max_frames
        return tuple(step * (i + 0.5) for i in range(self._max_frames))

    def _probe_duration(self, source: Path) -> float | None:
        """Duración del video en segundos, o None si ffprobe no la informa."""
        result = self._run(
            [
                self._ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(source),
            ]
        )
        if result is None or result.returncode != 0:
            return None
        try:
            value = float(result.stdout.decode("utf-8", "replace").strip())
        except ValueError:
            return None
        return value if value > 0 else None

    def _grab(self, source: Path, stamp: float, target: Path) -> bytes | None:
        """Un fotograma en PNG en el segundo indicado, o None si no se pudo."""
        result = self._run(
            [
                self._ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-ss",
                f"{stamp:.3f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-f",
                "image2",
                "-vcodec",
                "png",
                str(target),
            ]
        )
        if result is None or result.returncode != 0 or not target.exists():
            return None
        data = target.read_bytes()
        target.unlink(missing_ok=True)
        return data or None

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[bytes] | None:
        """Ejecuta una herramienta externa; un fallo de entorno devuelve None."""
        try:
            return subprocess.run(
                command,
                capture_output=True,
                timeout=self._timeout_s,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning(
                "video_frames_command_failed",
                extra={"error_type": type(exc).__name__},
            )
            return None


__all__ = [
    "FfmpegFrameExtractor",
    "FrameExtractionError",
    "FrameExtractor",
    "VideoFrame",
]
