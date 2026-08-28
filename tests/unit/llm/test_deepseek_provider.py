"""Unit tests for DeepSeekProvider — MockTransport only, no live network."""

from __future__ import annotations

import json
import logging

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


def _cap_empty_response(
    *,
    content: str = "",
    finish_reason: str = "length",
    reasoning: str | None = "internal monologue never send this",
    status_code: int = 200,
) -> httpx.Response:
    """Build a chat completion used by cap-empty ladder tests."""
    message: dict = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    body = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
    }
    return httpx.Response(status_code, json=body)


def _provider_with_transport(
    handler,
    *,
    api_key: str = "test-key",
    base_url: str = "https://api.deepseek.com",
    thinking_enabled: bool = True,
    thinking_effort: str = "medium",
) -> DeepSeekProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url=base_url)
    return DeepSeekProvider(
        api_key=SecretStr(api_key),
        base_url=base_url,
        client=client,
        model="deepseek-chat",
        thinking_enabled=thinking_enabled,
        thinking_effort=thinking_effort,
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
    assert "reasoning_effort" not in seen["payload"]


@pytest.mark.asyncio
async def test_generate_enables_thinking_mode_by_default() -> None:
    """Free-text generate() uses thinking when thinking_enabled (draft quality)."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return _openai_chat_response("ok")

    provider = _provider_with_transport(handler, thinking_enabled=True)
    client = provider._client
    try:
        await provider.generate([{"role": "user", "content": "x"}])
    finally:
        await provider.aclose()
        await client.aclose()
    assert seen["payload"].get("thinking") == {"type": "enabled"}
    assert seen["payload"].get("reasoning_effort") == "medium"
    assert seen["payload"].get("max_tokens") == 4096


@pytest.mark.asyncio
async def test_generate_disables_thinking_when_flag_off() -> None:
    """Operator can turn thinking off via thinking_enabled=False."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return _openai_chat_response("ok")

    provider = _provider_with_transport(handler, thinking_enabled=False)
    client = provider._client
    try:
        await provider.generate([{"role": "user", "content": "x"}])
    finally:
        await provider.aclose()
        await client.aclose()
    assert seen["payload"].get("thinking") == {"type": "disabled"}
    assert "reasoning_effort" not in seen["payload"]
    assert seen["payload"].get("max_tokens") == 1024


@pytest.mark.asyncio
async def test_generate_never_leaks_reasoning_content_as_draft(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cap-empty forever must not leak CoT in return or logs; ladder ≤3 HTTP."""
    seen: dict = {"call_count": 0}
    cot = "internal monologue never send this"

    def handler(request: httpx.Request) -> httpx.Response:
        seen["call_count"] += 1
        return _cap_empty_response(reasoning=cot)

    provider = _provider_with_transport(handler, thinking_enabled=True)
    client = provider._client
    try:
        with caplog.at_level(logging.ERROR, logger="diana.llm.deepseek"):
            text = await provider.generate([{"role": "user", "content": "x"}])
        assert text == ""
        assert cot not in text
        assert seen["call_count"] == 3
        assert seen["call_count"] <= 3
        for rec in caplog.records:
            assert cot not in rec.getMessage()
            assert cot not in str(getattr(rec, "msg", ""))
            extra_blob = " ".join(f"{k}={v}" for k, v in rec.__dict__.items())
            assert cot not in extra_blob
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_cap_empty_retries_once_same_config_then_succeeds() -> None:
    """First cap-empty → second same thinking+effort+max_tokens returns draft."""
    seen: dict = {"payloads": [], "call_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["call_count"] += 1
        payload = json.loads(request.content)
        seen["payloads"].append(payload)
        if seen["call_count"] == 1:
            return _cap_empty_response()
        return _openai_chat_response("recovered draft")

    provider = _provider_with_transport(handler, thinking_enabled=True)
    client = provider._client
    try:
        text = await provider.generate([{"role": "user", "content": "x"}])
        assert text == "recovered draft"
        assert seen["call_count"] == 2
        p0, p1 = seen["payloads"]
        assert p0.get("thinking") == {"type": "enabled"}
        assert p0.get("reasoning_effort") == "medium"
        assert p1.get("thinking") == p0.get("thinking")
        assert p1.get("reasoning_effort") == p0.get("reasoning_effort")
        assert p1.get("max_tokens") == p0.get("max_tokens")
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_double_cap_empty_falls_back_thinking_off() -> None:
    """Two cap-empty calls → third with thinking off, same max_tokens."""
    seen: dict = {"payloads": [], "call_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["call_count"] += 1
        payload = json.loads(request.content)
        seen["payloads"].append(payload)
        if seen["call_count"] <= 2:
            return _cap_empty_response()
        return _openai_chat_response("fallback draft")

    provider = _provider_with_transport(handler, thinking_enabled=True)
    client = provider._client
    try:
        text = await provider.generate([{"role": "user", "content": "x"}])
        assert text == "fallback draft"
        assert seen["call_count"] == 3
        p0, p1, p2 = seen["payloads"]
        assert p0.get("thinking") == {"type": "enabled"}
        assert p0.get("reasoning_effort") == "medium"
        assert p1.get("thinking") == p0.get("thinking")
        assert p1.get("reasoning_effort") == p0.get("reasoning_effort")
        assert p2.get("thinking") == {"type": "disabled"}
        assert "reasoning_effort" not in p2
        assert p2.get("max_tokens") == p0.get("max_tokens")
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_double_cap_empty_thinking_off_still_empty_returns_empty_no_leak() -> None:
    """3× empty (cap-empty ×2 then thinking-off empty) → '' without CoT leak."""
    seen: dict = {"call_count": 0}
    cot = "internal monologue never send this"

    def handler(request: httpx.Request) -> httpx.Response:
        seen["call_count"] += 1
        if seen["call_count"] <= 2:
            return _cap_empty_response(reasoning=cot)
        return _cap_empty_response(
            content="",
            finish_reason="stop",
            reasoning=cot,
        )

    provider = _provider_with_transport(handler, thinking_enabled=True)
    client = provider._client
    try:
        text = await provider.generate([{"role": "user", "content": "x"}])
        assert text == ""
        assert "internal monologue" not in text
        assert seen["call_count"] == 3
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_empty_without_cap_predicate_does_not_retry() -> None:
    """Empty + finish_reason=stop + no reasoning → exactly one HTTP → ''."""
    seen: dict = {"call_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["call_count"] += 1
        return _cap_empty_response(
            content="",
            finish_reason="stop",
            reasoning=None,
        )

    provider = _provider_with_transport(handler, thinking_enabled=True)
    client = provider._client
    try:
        text = await provider.generate([{"role": "user", "content": "x"}])
        assert text == ""
        assert seen["call_count"] == 1
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_small_max_tokens_forces_thinking_off() -> None:
    """Callers with max_tokens < 512 (e.g. recontact 180) skip thinking + ladder."""
    seen: dict = {"payloads": [], "call_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["call_count"] += 1
        seen["payloads"].append(json.loads(request.content))
        return _openai_chat_response("short")

    provider = _provider_with_transport(handler, thinking_enabled=True)
    client = provider._client
    try:
        text = await provider.generate(
            [{"role": "user", "content": "x"}],
            max_tokens=180,
        )
        assert text == "short"
        assert seen["call_count"] == 1
        payload = seen["payloads"][0]
        assert payload.get("thinking") == {"type": "disabled"}
        assert "reasoning_effort" not in payload
        assert payload.get("max_tokens") == 180
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_empty_length_without_reasoning_does_not_retry() -> None:
    """empty + length + no reasoning is not cap-empty → exactly 1 HTTP."""
    seen: dict = {"call_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["call_count"] += 1
        return _cap_empty_response(
            content="",
            finish_reason="length",
            reasoning=None,
        )

    provider = _provider_with_transport(handler, thinking_enabled=True)
    client = provider._client
    try:
        text = await provider.generate([{"role": "user", "content": "x"}])
        assert text == ""
        assert seen["call_count"] == 1
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_empty_stop_with_reasoning_does_not_retry() -> None:
    """empty + stop + reasoning is not cap-empty → exactly 1 HTTP."""
    seen: dict = {"call_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["call_count"] += 1
        return _cap_empty_response(
            content="",
            finish_reason="stop",
            reasoning="internal monologue never send this",
        )

    provider = _provider_with_transport(handler, thinking_enabled=True)
    client = provider._client
    try:
        text = await provider.generate([{"role": "user", "content": "x"}])
        assert text == ""
        assert "internal monologue" not in text
        assert seen["call_count"] == 1
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_floor_boundary_511_forces_thinking_off() -> None:
    """max_tokens=511 is below the floor → thinking disabled, 1 HTTP."""
    seen: dict = {"payloads": [], "call_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["call_count"] += 1
        seen["payloads"].append(json.loads(request.content))
        return _openai_chat_response("below floor")

    provider = _provider_with_transport(handler, thinking_enabled=True)
    client = provider._client
    try:
        text = await provider.generate(
            [{"role": "user", "content": "x"}],
            max_tokens=511,
        )
        assert text == "below floor"
        assert seen["call_count"] == 1
        payload = seen["payloads"][0]
        assert payload.get("thinking") == {"type": "disabled"}
        assert "reasoning_effort" not in payload
        assert payload.get("max_tokens") == 511
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_floor_boundary_512_enables_thinking() -> None:
    """max_tokens=512 meets the floor → thinking on + effort medium."""
    seen: dict = {"payloads": [], "call_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["call_count"] += 1
        seen["payloads"].append(json.loads(request.content))
        return _openai_chat_response("at floor")

    provider = _provider_with_transport(handler, thinking_enabled=True)
    client = provider._client
    try:
        text = await provider.generate(
            [{"role": "user", "content": "x"}],
            max_tokens=512,
        )
        assert text == "at floor"
        assert seen["call_count"] == 1
        payload = seen["payloads"][0]
        assert payload.get("thinking") == {"type": "enabled"}
        assert payload.get("reasoning_effort") == "medium"
        assert payload.get("max_tokens") == 512
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_flag_off_cap_empty_is_single_http() -> None:
    """Master switch off → even cap-empty-shaped bodies stay 1 HTTP."""
    seen: dict = {"payloads": [], "call_count": 0}
    cot = "internal monologue never send this"

    def handler(request: httpx.Request) -> httpx.Response:
        seen["call_count"] += 1
        seen["payloads"].append(json.loads(request.content))
        return _cap_empty_response(reasoning=cot)

    provider = _provider_with_transport(handler, thinking_enabled=False)
    client = provider._client
    try:
        text = await provider.generate([{"role": "user", "content": "x"}])
        assert text == ""
        assert cot not in text
        assert seen["call_count"] == 1
        payload = seen["payloads"][0]
        assert payload.get("thinking") == {"type": "disabled"}
        assert "reasoning_effort" not in payload
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_cap_empty_then_non_cap_empty_stops_without_third() -> None:
    """Attempt1 cap-empty then attempt2 stop-empty → 2 HTTP, no thinking-off third."""
    seen: dict = {"payloads": [], "call_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["call_count"] += 1
        seen["payloads"].append(json.loads(request.content))
        if seen["call_count"] == 1:
            return _cap_empty_response()
        return _cap_empty_response(
            content="",
            finish_reason="stop",
            reasoning=None,
        )

    provider = _provider_with_transport(handler, thinking_enabled=True)
    client = provider._client
    try:
        text = await provider.generate([{"role": "user", "content": "x"}])
        assert text == ""
        assert seen["call_count"] == 2
        p0, p1 = seen["payloads"]
        assert p0.get("thinking") == {"type": "enabled"}
        assert p0.get("reasoning_effort") == "medium"
        assert p1.get("thinking") == {"type": "enabled"}
        assert p1.get("reasoning_effort") == "medium"
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_uses_configured_thinking_effort() -> None:
    """reasoning_effort follows the provider's thinking_effort (e.g. high)."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return _openai_chat_response("ok")

    provider = _provider_with_transport(
        handler, thinking_enabled=True, thinking_effort="high"
    )
    client = provider._client
    try:
        await provider.generate([{"role": "user", "content": "x"}])
    finally:
        await provider.aclose()
        await client.aclose()
    assert seen["payload"].get("thinking") == {"type": "enabled"}
    assert seen["payload"].get("reasoning_effort") == "high"


def test_deepseek_rejects_invalid_thinking_effort() -> None:
    from pydantic import SecretStr

    with pytest.raises(ValueError, match="thinking_effort"):
        DeepSeekProvider(api_key=SecretStr("k"), thinking_effort="extreme")


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
async def test_extract_content_does_not_fall_back_to_reasoning() -> None:
    """reasoning_content is never returned as content — it's internal CoT."""
    body = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "internal chain-of-thought must not leak",
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
        with pytest.raises(ValueError, match="empty|null|valid JSON"):
            await provider.generate_structured(
                [{"role": "user", "content": "x"}],
                _TinySchema,
            )
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
