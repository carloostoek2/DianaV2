"""FfmpegFrameExtractor — reparto de fotogramas y fallos de entorno."""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from diana.infrastructure.vision.video_frames import (
    FfmpegFrameExtractor,
    FrameExtractionError,
    FrameReviewIncompleteError,
    VideoFrame,
)

_FFMPEG = shutil.which("ffmpeg")


def _timestamps(duration_s: float | None, max_frames: int = 30) -> tuple[float, ...]:
    return FfmpegFrameExtractor(max_frames=max_frames)._timestamps(duration_s)


def test_short_video_is_reviewed_second_by_second() -> None:
    """Un video corto se mira completo: un cuadro por segundo, sin huecos."""
    stamps = _timestamps(15.0)
    assert len(stamps) == 15
    assert stamps == tuple(sorted(stamps))  # en orden
    assert all(0.0 <= s < 15.0 for s in stamps)
    # Cubre cada segundo del video: no hay ningún hueco de más de 1 s.
    assert stamps[0] == 0.0
    assert stamps[-1] == 14.0
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(gap <= 1.0 for gap in gaps)


def test_long_video_spreads_the_cap_over_the_whole_video() -> None:
    """Un video largo no se queda solo con el comienzo."""
    stamps = _timestamps(300.0, max_frames=30)
    assert len(stamps) == 30
    assert stamps[0] < 10.0
    assert stamps[-1] > 290.0


def test_very_short_video_still_yields_a_frame() -> None:
    assert _timestamps(0.4) == (0.0,)


def test_unknown_duration_falls_back_to_the_first_seconds() -> None:
    assert _timestamps(None, max_frames=3) == (0.0, 1.0, 2.0)
    assert _timestamps(0.0, max_frames=2) == (0.0, 1.0)


def test_empty_payload_raises() -> None:
    with pytest.raises(FrameExtractionError):
        FfmpegFrameExtractor().extract_frames(b"")


def test_missing_binary_raises_instead_of_hanging() -> None:
    """Si ffmpeg no está, el video queda sin verificar (no se inventa nada)."""
    extractor = FfmpegFrameExtractor(
        ffmpeg_bin="ffmpeg-que-no-existe", ffprobe_bin="ffprobe-que-no-existe"
    )
    with pytest.raises(FrameExtractionError):
        extractor.extract_frames(b"no es un video")


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg no está instalado")
def test_real_video_yields_one_frame_per_second() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "prueba.mp4"
        built = subprocess.run(
            [
                _FFMPEG,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=160x120:rate=10:duration=3",
                "-pix_fmt",
                "yuv420p",
                str(source),
            ],
            capture_output=True,
            check=False,
        )
        assert built.returncode == 0, built.stderr.decode("utf-8", "replace")
        frames = FfmpegFrameExtractor().extract_frames(source.read_bytes())

    # El video de prueba dura 3 segundos: tres cuadros, uno por segundo.
    assert len(frames) == 3
    for frame in frames:
        assert frame.png_bytes.startswith(b"\x89PNG")
        with Image.open(io.BytesIO(frame.png_bytes)) as img:
            assert img.size == (160, 120)


def _sample_rate(duration_s: float | None, max_frames: int = 30) -> float:
    return FfmpegFrameExtractor(max_frames=max_frames)._sample_rate(duration_s)


def test_short_video_samples_one_frame_per_second() -> None:
    assert _sample_rate(15.0) == 1.0


def test_long_video_lowers_the_rate_to_respect_the_cap() -> None:
    """En un video largo el tope se reparte por todo el video."""
    assert _sample_rate(300.0, max_frames=30) == 0.1
    assert _sample_rate(60.0, max_frames=30) == 0.5


def test_unknown_duration_keeps_one_per_second() -> None:
    assert _sample_rate(None) == 1.0
    assert _sample_rate(0.0) == 1.0


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg no está instalado")
def test_a_video_at_the_coverage_window_is_fully_reviewed() -> None:
    """Con la cobertura garantizada, el tope de cuadros se respeta."""
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "cubierto.mp4"
        built = subprocess.run(
            [
                _FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=4",
                "-pix_fmt", "yuv420p", str(source),
            ],
            capture_output=True,
            check=False,
        )
        assert built.returncode == 0, built.stderr.decode("utf-8", "replace")
        frames = FfmpegFrameExtractor(max_frames=4).extract_frames(source.read_bytes())

    assert len(frames) == 4


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg no está instalado")
def test_a_video_longer_than_the_coverage_window_is_not_reviewed() -> None:
    """Más segundos que cuadros ⇒ no se puede garantizar la cobertura."""
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "largo.mp4"
        built = subprocess.run(
            [
                _FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=12",
                "-pix_fmt", "yuv420p", str(source),
            ],
            capture_output=True,
            check=False,
        )
        assert built.returncode == 0, built.stderr.decode("utf-8", "replace")
        with pytest.raises(FrameReviewIncompleteError) as excinfo:
            FfmpegFrameExtractor(max_frames=4).extract_frames(source.read_bytes())

    assert excinfo.value.reason == "too_long"


# --- M2: ventana constante de 30 s y último cuadro que cubre el final --------


def test_coverage_window_stays_thirty_seconds_even_with_more_frames() -> None:
    """Subir VIDEO_VISION_MAX_FRAMES no amplía la ventana de producto.

    Con 120 cuadros configurados, un video de 60 s seguiría sin poder
    revisarse a un cuadro por segundo dentro de la ventana de 30 s.
    """
    extractor = FfmpegFrameExtractor(max_frames=120)
    with pytest.raises(FrameReviewIncompleteError) as excinfo:
        extractor._ensure_coverage(60.0)
    assert excinfo.value.reason == "too_long"


def test_smaller_frame_budget_narrows_the_effective_window() -> None:
    """Con menos cuadros no se puede cubrir la ventana completa."""
    extractor = FfmpegFrameExtractor(max_frames=10)
    with pytest.raises(FrameReviewIncompleteError) as excinfo:
        extractor._ensure_coverage(12.0)
    assert excinfo.value.reason == "too_long"


def test_last_frame_not_reaching_the_end_is_blocked() -> None:
    """La extracción puede quedarse corta aunque la duración sea válida."""
    extractor = FfmpegFrameExtractor(max_frames=30)
    frames = [VideoFrame(png_bytes=b"x", timestamp_s=5.0)]
    with pytest.raises(FrameReviewIncompleteError) as excinfo:
        extractor._ensure_last_frame_covers_end(frames, 10.0)
    assert excinfo.value.reason == "coverage_gap"


def test_last_frame_covering_the_end_is_accepted() -> None:
    extractor = FfmpegFrameExtractor(max_frames=30)
    extractor._ensure_last_frame_covers_end(
        [VideoFrame(png_bytes=b"x", timestamp_s=9.0)], 10.0
    )


def test_non_integer_duration_samples_the_final_second() -> None:
    """12.5 s necesita una muestra en el segundo 12 (ceil), no solo 0…11."""
    stamps = _timestamps(12.5)
    assert stamps[-1] == 12.0
