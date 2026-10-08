"""Descarga de media del historial importado (Telethon): tope y tolerancia."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from diana.infrastructure.telethon.vip_history_fetcher import _fetch_raw_messages


def _photo_media() -> object:
    return type("MessageMediaPhoto", (), {})()


def _video_media() -> object:
    attribute = type("DocumentAttributeVideo", (), {"round_message": False})()
    return type(
        "MessageMediaDocument", (), {"document": SimpleNamespace(attributes=[attribute])}
    )()


class _Msg:
    def __init__(self, mid: int, media, *, size: int = 1000, mime: str = "video/mp4"):
        self.id = mid
        self.date = None
        self.sender_id = 111
        self.out = False
        self.text = ""
        self.message = None
        self.caption = None
        self.media = media
        self.file = SimpleNamespace(size=size, mime_type=mime)


class _Client:
    """Cliente Telethon mínimo: los mensajes llegan del más nuevo al más viejo."""

    def __init__(self, messages: list[_Msg], *, fail_on: set[int] | None = None) -> None:
        self._messages = messages
        self._fail_on = fail_on or set()
        self.downloaded: list[int] = []

    async def get_me(self):
        return SimpleNamespace(id=999)

    def iter_messages(self, entity, limit=None):
        async def _gen():
            for msg in self._messages[:limit]:
                yield msg

        return _gen()

    async def download_media(self, msg, file=bytes):
        if msg.id in self._fail_on:
            raise RuntimeError("falló la descarga")
        self.downloaded.append(msg.id)
        return b"contenido"


@pytest.mark.asyncio
async def test_only_the_newest_media_is_downloaded() -> None:
    client = _Client([_Msg(3, _video_media()), _Msg(2, _photo_media()), _Msg(1, _video_media())])
    raw = await _fetch_raw_messages(client, object(), 20, media_limit=1)
    # Un único archivo: el más reciente (id 3).
    assert client.downloaded == [3]


@pytest.mark.asyncio
async def test_media_limit_covers_the_newest_first() -> None:
    client = _Client([_Msg(3, _video_media()), _Msg(2, _photo_media()), _Msg(1, _video_media())])
    raw = await _fetch_raw_messages(client, object(), 20, media_limit=2)
    assert client.downloaded == [3, 2]
    with_bytes = [r for r in raw if r.get("media_bytes")]
    assert len(with_bytes) == 2


@pytest.mark.asyncio
async def test_zero_limit_never_downloads() -> None:
    client = _Client([_Msg(3, _video_media())])
    raw = await _fetch_raw_messages(client, object(), 20, media_limit=0)
    assert client.downloaded == []
    assert raw[0].get("media_bytes") is None


@pytest.mark.asyncio
async def test_oversized_media_is_skipped() -> None:
    client = _Client([_Msg(3, _video_media(), size=120 * 1024 * 1024)])
    raw = await _fetch_raw_messages(client, object(), 20, media_limit=3)
    assert client.downloaded == []
    assert raw[0].get("media_bytes") is None


@pytest.mark.asyncio
async def test_a_heavy_video_is_still_downloaded() -> None:
    """La descarga va por la cuenta personal: un video pesado se baja igual,
    porque después se describe con sus cuadros y no con el archivo completo."""
    client = _Client([_Msg(3, _video_media(), size=60 * 1024 * 1024)])
    raw = await _fetch_raw_messages(client, object(), 20, media_limit=3)
    assert client.downloaded == [3]
    assert raw[0].get("media_bytes") == b"contenido"


@pytest.mark.asyncio
async def test_download_failure_does_not_break_the_import() -> None:
    client = _Client([_Msg(3, _video_media())], fail_on={3})
    raw = await _fetch_raw_messages(client, object(), 20, media_limit=3)
    assert len(raw) == 1
    assert raw[0].get("media_bytes") is None


@pytest.mark.asyncio
async def test_messages_without_media_are_untouched() -> None:
    plain = _Msg(4, None)
    client = _Client([plain, _Msg(3, _video_media())])
    raw = await _fetch_raw_messages(client, object(), 20, media_limit=1)
    assert client.downloaded == [3]  # solo el mensaje con media
    by_id = {row["id"]: row for row in raw}
    assert by_id[4].get("media_bytes") is None
    assert by_id[3].get("media_bytes") == b"contenido"
