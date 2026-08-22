"""Unit tests for HotSwapLLMProvider (ADM-03) — MockTransport only, no network."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from diana.llm.deepseek import DeepSeekProvider
from diana.llm.hot_swap import HotSwapLLMProvider


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _openai_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        },
    )


class _Factory:
    """Builds MockTransport-backed providers and records each build."""

    def __init__(self) -> None:
        self.built: list[tuple[str, str, str]] = []
        self.closed: list[str] = []

    def __call__(self, api_key: str, base_url: str, model: str) -> DeepSeekProvider:
        self.built.append((api_key, base_url, model))

        def _handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            if "response_format" in payload:
                return _openai_response(json.dumps({"value": model}))
            return _openai_response(model)

        provider = DeepSeekProvider(
            api_key=SecretStr(api_key),
            base_url=base_url,
            model=model,
            thinking_enabled=False,
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(_handler),
                base_url=base_url,
            ),
        )
        original_close = provider.aclose

        async def _tracked_close() -> None:
            self.closed.append(model)
            await original_close()

        provider.aclose = _tracked_close  # type: ignore[method-assign]
        return provider


def _base_provider() -> DeepSeekProvider:
    return DeepSeekProvider(
        api_key=SecretStr("base-key"),
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        thinking_enabled=False,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: _openai_response("base")),
            base_url="https://api.deepseek.com",
        ),
    )


def _build(
    config: dict | None = None,
    *,
    ttl: float = 30.0,
    clock: _FakeClock | None = None,
) -> tuple[HotSwapLLMProvider, _Factory, _FakeClock, dict]:
    state: dict = {"value": config}
    factory = _Factory()
    clk = clock or _FakeClock()

    async def _config_source():
        return state["value"]

    base = _base_provider()
    wrapper = HotSwapLLMProvider(
        base=base,
        api_key=SecretStr("base-key"),
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        thinking_enabled=False,
        config_source=_config_source,
        provider_factory=factory,
        ttl_seconds=ttl,
        clock=clk,
    )
    return wrapper, factory, clk, state


@pytest.mark.asyncio
async def test_no_overrides_delegates_to_base() -> None:
    wrapper, factory, _, state = _build(None)
    try:
        text = await wrapper.generate([{"role": "user", "content": "hola"}])
        assert text == "base"
        assert factory.built == []  # never rebuilt without overrides
    finally:
        await wrapper.aclose()


@pytest.mark.asyncio
async def test_model_override_swaps_provider_after_ttl() -> None:
    wrapper, factory, clk, state = _build(None)
    try:
        # First call with no overrides → base.
        await wrapper.generate([{"role": "user", "content": "hola"}])
        assert factory.built == []

        # Owner changes the model; within the TTL the change is not seen yet.
        state["value"] = {"model": "deepseek-chat"}
        await wrapper.generate([{"role": "user", "content": "hola"}])
        assert factory.built == []

        # After the TTL the next call rebuilds with the new model.
        clk.advance(31)
        text = await wrapper.generate([{"role": "user", "content": "hola"}])
        assert text == "deepseek-chat"
        assert factory.built == [("base-key", "https://api.deepseek.com", "deepseek-chat")]
    finally:
        await wrapper.aclose()


@pytest.mark.asyncio
async def test_reset_returns_to_base_and_closes_swapped() -> None:
    wrapper, factory, clk, state = _build(None)
    try:
        state["value"] = {"model": "deepseek-chat"}
        clk.advance(31)
        await wrapper.generate([{"role": "user", "content": "hola"}])
        assert factory.built == [("base-key", "https://api.deepseek.com", "deepseek-chat")]

        # Owner resets (empty overrides) → back to the base provider.
        state["value"] = {}
        clk.advance(31)
        text = await wrapper.generate([{"role": "user", "content": "hola"}])
        assert text == "base"
        assert factory.closed == ["deepseek-chat"]  # swapped provider closed
    finally:
        await wrapper.aclose()


@pytest.mark.asyncio
async def test_base_url_override_uses_custom_endpoint() -> None:
    wrapper, factory, clk, state = _build(None)
    try:
        state["value"] = {"base_url": "https://proxy.example.com"}
        clk.advance(31)
        await wrapper.generate([{"role": "user", "content": "hola"}])
        assert factory.built == [
            ("base-key", "https://proxy.example.com", "deepseek-v4-flash")
        ]
    finally:
        await wrapper.aclose()


@pytest.mark.asyncio
async def test_structured_path_also_swaps() -> None:
    from pydantic import BaseModel

    class _S(BaseModel):
        value: str

    wrapper, factory, clk, state = _build(None)
    try:
        state["value"] = {"model": "deepseek-chat"}
        clk.advance(31)
        result = await wrapper.generate_structured(
            [{"role": "user", "content": "x"}], _S
        )
        assert result.value == "deepseek-chat"
    finally:
        await wrapper.aclose()


@pytest.mark.asyncio
async def test_aclose_closes_base() -> None:
    wrapper, factory, _, _ = _build(None)
    base = wrapper._base
    original = base.aclose
    closed: list[str] = []

    async def _tracked() -> None:
        closed.append("base")
        await original()

    base.aclose = _tracked  # type: ignore[method-assign]
    await wrapper.aclose()
    assert closed == ["base"]
