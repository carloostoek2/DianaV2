"""Unit tests for DeepSeekProvider — MockTransport only, no live network."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel, SecretStr, ValidationError

from diana.llm.deepseek import DeepSeekProvider


class _TinySchema(BaseModel):
    value: str
    count: int


def _openai_chat_response(content: str, *, status_code: int = 200) -> httpx.Response:
    body = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    return httpx.Response(status_code, json=body)


def _provider_with_transport(
    handler,
    *,
    api_key: str = "test-key",
    base_url: str = "https://api.deepseek.com",
) -> DeepSeekProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url=base_url)
    return DeepSeekProvider(
        api_key=SecretStr(api_key),
        base_url=base_url,
        client=client,
        model="deepseek-chat",
    )


@pytest.mark.asyncio
async def test_generate_returns_assistant_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["messages"][0]["content"] == "hello"
        assert payload["temperature"] == 0.5
        return _openai_chat_response("draft reply")

    provider = _provider_with_transport(handler)
    try:
        text = await provider.generate(
            [{"role": "user", "content": "hello"}],
            temperature=0.5,
            max_tokens=128,
        )
        assert text == "draft reply"
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_generate_structured_parses_json_into_schema() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "response_format" in payload or "json" in json.dumps(payload).lower()
        return _openai_chat_response(json.dumps({"value": "ok", "count": 7}))

    provider = _provider_with_transport(handler)
    try:
        result = await provider.generate_structured(
            [{"role": "user", "content": "extract"}],
            _TinySchema,
        )
        assert result == _TinySchema(value="ok", count=7)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_generate_structured_invalid_json_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_chat_response("not-json-at-all")

    provider = _provider_with_transport(handler)
    try:
        with pytest.raises((json.JSONDecodeError, ValueError, ValidationError)):
            await provider.generate_structured(
                [{"role": "user", "content": "x"}],
                _TinySchema,
            )
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_generate_structured_schema_mismatch_raises_validation_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_chat_response(json.dumps({"value": "only"}))

    provider = _provider_with_transport(handler)
    try:
        with pytest.raises(ValidationError):
            await provider.generate_structured(
                [{"role": "user", "content": "x"}],
                _TinySchema,
            )
    finally:
        await provider.aclose()


def test_empty_api_key_fails_loud_on_construct() -> None:
    with pytest.raises(ValueError, match="api_key"):
        DeepSeekProvider(api_key=SecretStr(""), base_url="https://api.deepseek.com")


def test_whitespace_api_key_fails_loud_on_construct() -> None:
    with pytest.raises(ValueError, match="api_key"):
        DeepSeekProvider(api_key=SecretStr("   "), base_url="https://api.deepseek.com")


def test_provider_name() -> None:
    provider = DeepSeekProvider(
        api_key=SecretStr("k"),
        base_url="https://api.deepseek.com",
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: _openai_chat_response("x"))),
    )
    assert provider.name == "deepseek"
