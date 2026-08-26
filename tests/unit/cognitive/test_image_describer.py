"""ImageDescriber — captioning fail-open behavior (unit)."""

from __future__ import annotations

import pytest

from diana.cognitive.image_vision import ImageDescriber


class _FakeVision:
    def __init__(self, text: str | None = None, error: bool = False) -> None:
        self._text = text
        self._error = error
        self.last_prompt: str | None = None

    async def describe_image(self, image_bytes, *, mime_type, prompt) -> str:
        self.last_prompt = prompt
        if self._error:
            raise RuntimeError("gemini down")
        return self._text


@pytest.mark.asyncio
async def test_describe_returns_caption() -> None:
    vision = _FakeVision(text="una taza de café")
    describer = ImageDescriber(vision=vision)
    caption = await describer.describe(b"img", mime_type="image/jpeg")
    assert caption == "una taza de café"
    assert vision.last_prompt and "40 palabras" in vision.last_prompt


@pytest.mark.asyncio
async def test_provider_error_returns_none_fail_open() -> None:
    vision = _FakeVision(error=True)
    describer = ImageDescriber(vision=vision)
    assert await describer.describe(b"img", mime_type="image/jpeg") is None


@pytest.mark.asyncio
async def test_empty_caption_returns_none() -> None:
    vision = _FakeVision(text="   ")
    describer = ImageDescriber(vision=vision)
    assert await describer.describe(b"img", mime_type="image/jpeg") is None


@pytest.mark.asyncio
async def test_caption_is_truncated_to_max_chars() -> None:
    long = "x" * 500
    vision = _FakeVision(text=long)
    describer = ImageDescriber(vision=vision)
    caption = await describer.describe(b"img", mime_type="image/jpeg")
    assert caption is not None
    assert len(caption) == 400
