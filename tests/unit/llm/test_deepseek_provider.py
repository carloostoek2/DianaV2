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
    client = provider._client
    try:
        text = await provider.generate(
            [{"role": "user", "content": "hello"}],
            temperature=0.5,
            max_tokens=128,
        )
        assert text == "draft reply"
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_structured_parses_json_into_schema() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "response_format" in payload or "json" in json.dumps(payload).lower()
        # Schema instruction is leading system message
        assert payload["messages"][0]["role"] == "system"
        return _openai_chat_response(json.dumps({"value": "ok", "count": 7}))

    provider = _provider_with_transport(handler)
    client = provider._client
    try:
        result = await provider.generate_structured(
            [{"role": "user", "content": "extract"}],
            _TinySchema,
        )
        assert result == _TinySchema(value="ok", count=7)
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_structured_strips_markdown_fences() -> None:
    fenced = '```json\n{"value": "fenced", "count": 3}\n```'

    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_chat_response(fenced)

    provider = _provider_with_transport(handler)
    client = provider._client
    try:
        result = await provider.generate_structured(
            [{"role": "user", "content": "x"}],
            _TinySchema,
        )
        assert result == _TinySchema(value="fenced", count=3)
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_structured_invalid_json_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_chat_response("not-json-at-all")

    provider = _provider_with_transport(handler)
    client = provider._client
    try:
        with pytest.raises(ValueError, match="valid JSON"):
            await provider.generate_structured(
                [{"role": "user", "content": "x"}],
                _TinySchema,
            )
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_structured_disables_thinking_mode() -> None:
    """DeepSeek v4 defaults thinking=on; empty content after CoT breaks Analyst JSON."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return _openai_chat_response(json.dumps({"value": "ok", "count": 1}))

    provider = _provider_with_transport(handler)
    client = provider._client
    try:
        await provider.generate_structured(
            [{"role": "user", "content": "x"}],
            _TinySchema,
        )
    finally:
        await provider.aclose()
        await client.aclose()
    assert seen["payload"].get("thinking") == {"type": "disabled"}


@pytest.mark.asyncio
async def test_generate_structured_empty_content_raises_clearly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_chat_response("")

    provider = _provider_with_transport(handler)
    client = provider._client
    try:
        with pytest.raises(ValueError, match="empty|null|valid JSON"):
            await provider.generate_structured(
                [{"role": "user", "content": "x"}],
                _TinySchema,
            )
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_extract_content_falls_back_to_reasoning_json() -> None:
    """If content is empty but reasoning_content holds JSON, use it."""
    body = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": 'Here is the object: {"value": "from-cot", "count": 9}',
                },
                "finish_reason": "stop",
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    provider = _provider_with_transport(handler)
    client = provider._client
    try:
        result = await provider.generate_structured(
            [{"role": "user", "content": "x"}],
            _TinySchema,
        )
        assert result == _TinySchema(value="from-cot", count=9)
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_structured_schema_mismatch_raises_validation_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_chat_response(json.dumps({"value": "only"}))

    provider = _provider_with_transport(handler)
    client = provider._client
    try:
        with pytest.raises(ValidationError):
            await provider.generate_structured(
                [{"role": "user", "content": "x"}],
                _TinySchema,
            )
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_structured_attaches_raw_when_schema_has_field() -> None:
    from diana.cognitive.models import Comprehension

    payload = {
        "intent": "greet",
        "topics": ["hi"],
        "emotion": "neutral",
        "urgency": "baja",
        "risk": "bajo",
        "needs_memory": False,
        "needs_policy": False,
        "needs_schedule": False,
        "needs_examples": False,
        "needs_history": True,
        "needs_context": True,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        schema_text = body["messages"][0]["content"]
        assert "raw_llm_output" not in schema_text
        return _openai_chat_response(json.dumps(payload))

    provider = _provider_with_transport(handler)
    client = provider._client
    try:
        result = await provider.generate_structured(
            [{"role": "user", "content": "x"}],
            Comprehension,
        )
        assert isinstance(result, Comprehension)
        assert result.raw_llm_output is not None
        assert result.raw_llm_output["intent"] == "greet"
    finally:
        await provider.aclose()
        await client.aclose()


def test_empty_api_key_fails_loud_on_construct() -> None:
    with pytest.raises(ValueError, match="api_key"):
        DeepSeekProvider(api_key=SecretStr(""), base_url="https://api.deepseek.com")


def test_whitespace_api_key_fails_loud_on_construct() -> None:
    with pytest.raises(ValueError, match="api_key"):
        DeepSeekProvider(api_key=SecretStr("   "), base_url="https://api.deepseek.com")


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://api.deepseek.com",
        "file:///etc/passwd",
        "https://169.254.169.254/latest",
        "https://127.0.0.1/",
        "https://10.0.0.5/v1",
    ],
)
def test_unsafe_base_url_rejected(bad_url: str) -> None:
    with pytest.raises(ValueError):
        DeepSeekProvider(api_key=SecretStr("k"), base_url=bad_url)


def test_provider_name() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: _openai_chat_response("x"))
    )
    provider = DeepSeekProvider(
        api_key=SecretStr("k"),
        base_url="https://api.deepseek.com",
        client=client,
    )
    assert provider.name == "deepseek"
