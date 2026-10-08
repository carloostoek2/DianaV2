"""Media del historial importado: se describe con la visión o queda muda.

El VIP manda videos y fotos antes de estar en la lista. Si el historial los
guarda como una etiqueta vacía, el bot arranca sin saber qué le mandaron.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from diana.application.image_vision_service import ImageVisionResult
from diana.application.memory import InMemoryMessageHistoryWriter
from diana.application.video_vision_service import VideoVisionResult
from diana.application.vip_history_seed import (
    HistoryLine,
    VipHistorySeedService,
    map_raw_messages_to_lines,
)

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _Fetcher:
    def __init__(self, lines: list[HistoryLine]) -> None:
        self._lines = lines

    async def fetch_recent(self, user_id, *, limit, username=None):
        return list(self._lines)


def _fake(result, *, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(enabled=enabled, analyze=AsyncMock(return_value=result))


def _video_line(**overrides) -> HistoryLine:
    base = {
        "role": "vip",
        "text": "[video]",
        "telegram_message_id": 7,
        "media_kind": "video",
        "media_bytes": b"mp4",
        "media_mime": "video/mp4",
    }
    base.update(overrides)
    return HistoryLine(**base)  # type: ignore[arg-type]


async def _seed(lines, *, image=None, video=None):
    """Devuelve (resultado, filas guardadas) del historial importado."""
    history = InMemoryMessageHistoryWriter()
    service = VipHistorySeedService(
        history=history,
        fetcher=_Fetcher(lines),
        limit=20,
        image_vision=image,
        video_vision=video,
    )
    outcome = await service.seed_for_new_vip(123)
    return outcome, await history.get_recent(123, limit=20)


def test_map_carries_media_bytes_and_caption() -> None:
    lines = map_raw_messages_to_lines(
        [
            {
                "id": 5,
                "date": None,
                "sender_id": 123,
                "text": "mira esto",
                "is_diana": False,
                "media_kind": "video",
                "media_bytes": b"mp4",
                "media_mime": "video/mp4",
            }
        ]
    )
    assert len(lines) == 1
    assert lines[0].caption == "mira esto"
    assert lines[0].media_kind == "video"
    assert lines[0].media_bytes == b"mp4"
    assert lines[0].media_mime == "video/mp4"


@pytest.mark.asyncio
async def test_imported_video_is_described_instead_of_mute_tag() -> None:
    video = _fake(
        VideoVisionResult(
            enabled=True, sensitive=False, description="dedicatoria con sus fotos"
        )
    )
    _, stored = await _seed([_video_line()], video=video)
    assert stored[0]["text"] == "[video: dedicatoria con sus fotos]"
    video.analyze.assert_awaited_once()


@pytest.mark.asyncio
async def test_imported_photo_with_caption_keeps_the_caption() -> None:
    image = _fake(
        ImageVisionResult(enabled=True, sensitive=False, description="una playa")
    )
    line = HistoryLine(
        role="vip",
        text="mira",
        caption="mira",
        telegram_message_id=8,
        media_kind="foto",
        media_bytes=_PNG,
    )
    _, stored = await _seed([line], image=image)
    assert stored[0]["text"] == "[imagen: una playa] mira"


@pytest.mark.asyncio
async def test_sensitive_imported_media_is_marked_not_described() -> None:
    video = _fake(VideoVisionResult(enabled=True, sensitive=True, reason="tarjeta"))
    _, stored = await _seed([_video_line()], video=video)
    assert "información sensible" in stored[0]["text"]


@pytest.mark.asyncio
async def test_without_vision_the_mute_tag_is_kept() -> None:
    _, stored = await _seed([_video_line()])
    assert stored[0]["text"] == "[video]"


@pytest.mark.asyncio
async def test_vision_failure_keeps_the_history_intact() -> None:
    video = _fake(VideoVisionResult(enabled=True))
    video.analyze = AsyncMock(side_effect=RuntimeError("gemini caído"))
    outcome, stored = await _seed([_video_line()], video=video)
    assert outcome.kind == "ok"
    assert stored[0]["text"] == "[video]"


@pytest.mark.asyncio
async def test_owner_media_is_not_described() -> None:
    """La media de la dueña viaja en el historial, pero no se analiza."""
    video = _fake(VideoVisionResult(enabled=True, sensitive=False, description="x"))
    _, stored = await _seed(
        [_video_line(role="owner", telegram_message_id=12)], video=video
    )
    assert stored[0]["text"] == "[video]"
    video.analyze.assert_not_awaited()
