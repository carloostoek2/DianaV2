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
