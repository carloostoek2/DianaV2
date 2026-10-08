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
