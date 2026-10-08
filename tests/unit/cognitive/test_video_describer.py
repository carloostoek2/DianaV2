"""VideoDescriber — pregunta única, fallo abierto."""

from __future__ import annotations

import pytest

from diana.cognitive.video_vision import VideoDescriber


class _Provider:
    def __init__(self, text: str | None = None, error: bool = False) -> None:
        self._text = text
        self._error = error
        self.seen_prompt: str | None = None
        self.seen_mime: str | None = None
        self.calls = 0

    async def describe_video(self, video_bytes, *, mime_type, prompt) -> str:
        self.calls += 1
        self.seen_prompt = prompt
        self.seen_mime = mime_type
        if self._error:
            raise RuntimeError("gemini down")
        return self._text


@pytest.mark.asyncio
async def test_returns_the_model_caption() -> None:
    provider = _Provider("un video de dedicatoria")
    caption = await VideoDescriber(vision=provider).describe(
        b"mp4", mime_type="video/mp4"
    )
    assert caption == "un video de dedicatoria"
    assert provider.seen_mime == "video/mp4"
    assert "video" in (provider.seen_prompt or "")


@pytest.mark.asyncio
async def test_provider_failure_is_fail_open() -> None:
    provider = _Provider(error=True)
    caption = await VideoDescriber(vision=provider).describe(
        b"mp4", mime_type="video/mp4"
    )
    assert caption is None


@pytest.mark.asyncio
async def test_empty_caption_becomes_none() -> None:
    provider = _Provider("   ")
    caption = await VideoDescriber(vision=provider).describe(
        b"mp4", mime_type="video/mp4"
    )
    assert caption is None


@pytest.mark.asyncio
async def test_caption_is_truncated() -> None:
    provider = _Provider("a" * 900)
    caption = await VideoDescriber(vision=provider).describe(
        b"mp4", mime_type="video/mp4"
    )
    assert caption is not None
    assert len(caption) == 400


class _MultiProvider:
    def __init__(self, text: str = "un video de dedicatoria") -> None:
        self._text = text
        self.calls = 0
        self.seen_images: list[bytes] | None = None
        self.seen_prompt: str | None = None

    async def describe_images(self, images, *, mime_type, prompt) -> str:
        self.calls += 1
        self.seen_images = list(images)
        self.seen_prompt = prompt
        return self._text


@pytest.mark.asyncio
async def test_frames_are_described_in_a_single_call() -> None:
    """Los cuadros van todos en una sola llamada, no una por cuadro."""
    provider = _MultiProvider()
    caption = await VideoDescriber(vision=provider).describe_frames(
        [b"cuadro-1", b"cuadro-2", b"cuadro-3"], mime_type="image/jpeg"
    )
    assert caption == "un video de dedicatoria"
    assert provider.calls == 1
    assert provider.seen_images == [b"cuadro-1", b"cuadro-2", b"cuadro-3"]
    assert "video" in (provider.seen_prompt or "")


@pytest.mark.asyncio
async def test_without_frames_nothing_is_sent() -> None:
    provider = _MultiProvider()
    caption = await VideoDescriber(vision=provider).describe_frames(
        [], mime_type="image/jpeg"
    )
    assert caption is None
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_frames_failure_is_fail_open() -> None:
    class _Broken(_MultiProvider):
        async def describe_images(self, images, *, mime_type, prompt) -> str:
            raise RuntimeError("gemini caído")

    caption = await VideoDescriber(vision=_Broken()).describe_frames(
        [b"cuadro"], mime_type="image/jpeg"
    )
    assert caption is None
