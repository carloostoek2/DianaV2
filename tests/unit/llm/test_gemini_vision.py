"""GeminiVisionProvider — httpx MockTransport unit tests (no network)."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from pydantic import SecretStr

from diana.llm.gemini_vision import GeminiVisionProvider


def _transport(responder) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(responder))


@pytest.mark.asyncio
async def test_describe_image_sends_inline_data_and_returns_text() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("key") == "k-123"
        body = json.loads(request.content)
        parts = body["contents"][0]["parts"]
        assert parts[0]["text"] == "Qué muestra esta imagen?"
        assert parts[1]["inline_data"]["mime_type"] == "image/jpeg"
        # The image bytes travel base64-encoded inline.
        decoded = base64.b64decode(parts[1]["inline_data"]["data"])
        assert decoded == b"\x89PNG-fake"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "una taza de café"}]}}
                ]
            },
        )

    client = _transport(responder)
    provider = GeminiVisionProvider(
        api_key=SecretStr("k-123"),
        model="gemini-3.6-flash",
        client=client,
    )
    text = await provider.describe_image(
        b"\x89PNG-fake",
        mime_type="image/jpeg",
        prompt="Qué muestra esta imagen?",
    )
    assert text == "una taza de café"
    await provider.aclose()


@pytest.mark.asyncio
async def test_describe_image_joins_multiple_text_parts() -> None:
    def responder(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "una factura "},
                                {"text": "de supermercado"},
                            ]
                        }
                    }
                ]
            },
        )

    client = _transport(responder)
    provider = GeminiVisionProvider(
        api_key=SecretStr("k"), client=client
    )
    text = await provider.describe_image(
        b"img", mime_type="image/jpeg", prompt="describe"
    )
    assert text == "una factura de supermercado"
    await provider.aclose()


@pytest.mark.asyncio
async def test_describe_image_raises_on_http_error() -> None:
    def responder(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="API key invalid")

    client = _transport(responder)
    provider = GeminiVisionProvider(api_key=SecretStr("k"), client=client)
    with pytest.raises(httpx.HTTPStatusError):
        await provider.describe_image(
            b"img", mime_type="image/jpeg", prompt="describe"
        )
    await provider.aclose()


@pytest.mark.asyncio
async def test_describe_image_rejects_malformed_response() -> None:
    def responder(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    client = _transport(responder)
    provider = GeminiVisionProvider(api_key=SecretStr("k"), client=client)
    with pytest.raises(ValueError, match="response shape"):
        await provider.describe_image(
            b"img", mime_type="image/jpeg", prompt="describe"
        )
    await provider.aclose()


def test_empty_api_key_fails_loud() -> None:
    with pytest.raises(ValueError, match="api_key"):
        GeminiVisionProvider(api_key=SecretStr(""))


def test_empty_model_fails_loud() -> None:
    with pytest.raises(ValueError, match="model"):
        GeminiVisionProvider(api_key=SecretStr("k"), model="  ")


@pytest.mark.asyncio
async def test_describe_image_rejects_empty_args() -> None:
    client = _transport(lambda _r: httpx.Response(200, json={}))
    provider = GeminiVisionProvider(api_key=SecretStr("k"), client=client)
    with pytest.raises(ValueError, match="image_bytes"):
        await provider.describe_image(b"", mime_type="image/jpeg", prompt="d")
    with pytest.raises(ValueError, match="mime_type"):
        await provider.describe_image(b"x", mime_type="", prompt="d")
    with pytest.raises(ValueError, match="prompt"):
        await provider.describe_image(b"x", mime_type="image/jpeg", prompt=" ")
    await provider.aclose()
