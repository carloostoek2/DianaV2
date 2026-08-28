"""HotSwapLLMProvider — runtime LLM provider swap (ADM-03).

Wraps the base DeepSeek provider and re-reads runtime overrides (system_config
key ``llm``: ``model`` / ``base_url`` / ``api_key``) on a short TTL. When the
owner changes the model via the admin surface, the next call after the TTL
rebuilds the underlying provider with the new configuration — no restart.

With no overrides the wrapper delegates to the base provider untouched, so the
default runtime is byte-identical to a plain DeepSeekProvider (ADM-03 keeps the
"no override" path a no-op).

Concurrency: swaps happen under a lock and only when the fingerprint changed;
replaced providers are closed so sockets are not leaked. The config read is
cached for ``ttl_seconds`` so the hot path does not hit the DB per call.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import SecretStr

from diana.llm.deepseek import DeepSeekProvider

logger = logging.getLogger(__name__)

# system_config key holding the runtime LLM overrides ({model, base_url, api_key}).
LLM_CONFIG_KEY = "llm"

LLMConfigSource = Callable[[], Awaitable[Any]]


class HotSwapLLMProvider:
    """LLMProvider facade that hot-swaps the underlying DeepSeek provider.

    The public surface mirrors ``DeepSeekProvider`` (``generate`` /
    ``generate_structured`` / ``aclose``) so the DI graph is unchanged.
    """

    name: str = "hot_swap"

    def __init__(
        self,
        *,
        base: DeepSeekProvider,
        api_key: SecretStr,
        base_url: str,
        model: str,
        thinking_enabled: bool,
        thinking_effort: str = "medium",
        config_source: LLMConfigSource,
        provider_factory: Callable[[str, str, str], Any] | None = None,
        ttl_seconds: float = 30.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not isinstance(api_key, SecretStr):
            raise TypeError("api_key must be a pydantic SecretStr")
        self._base = base
        self._api_key = api_key.get_secret_value()
        self._base_url = base_url
        self._base_model = model
        self._thinking_enabled = thinking_enabled
        self._thinking_effort = thinking_effort
        self._config_source = config_source
        # Injectable factory so tests can swap in MockTransport-backed providers
        # (the production default builds a plain DeepSeekProvider).
        self._factory = provider_factory or self._default_factory
        self._ttl = ttl_seconds
        self._clock = clock or time.monotonic
        self._current = base
        # Fingerprint of the config the current provider was built with;
        # (None, None, None) means "base provider, no overrides".
        self._active_fp: tuple[Any, Any, Any] = (None, None, None)
        self._cache: Mapping[str, Any] | None = None
        self._cached_at: float | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    def _default_factory(
        self, api_key: str, base_url: str, model: str
    ) -> DeepSeekProvider:
        return DeepSeekProvider(
            api_key=SecretStr(api_key),
            base_url=base_url,
            model=model,
            thinking_enabled=self._thinking_enabled,
            thinking_effort=self._thinking_effort,
            pii_masking=True,
        )

    async def _overrides(self) -> Mapping[str, Any]:
        now = self._clock()
        if (
            self._cache is None
            or self._cached_at is None
            or now - self._cached_at > self._ttl
        ):
            raw = await self._config_source()
            self._cache = raw if isinstance(raw, Mapping) else {}
            self._cached_at = now
        return self._cache

    async def _maybe_swap(self) -> None:
        overrides = await self._overrides()
        fp = (
            overrides.get("model") or None,
            overrides.get("base_url") or None,
            overrides.get("api_key") or None,
        )
        if fp == self._active_fp or self._closed:
            return
        async with self._lock:
            if fp == self._active_fp or self._closed:
                return
            old = self._current
            if fp == (None, None, None):
                self._current = self._base
            else:
                self._current = self._factory(
                    str(overrides.get("api_key") or self._api_key),
                    str(overrides.get("base_url") or self._base_url),
                    str(overrides.get("model") or self._base_model),
                )
            self._active_fp = fp
            logger.info(
                "llm_hot_swap",
                extra={
                    "model": getattr(self._current, "_model", "?"),
                    "active_fp": str(fp),
                },
            )
            if old is not None and old is not self._base:
                try:
                    await old.aclose()
                except Exception:
                    logger.warning("llm_hot_swap_old_close_failed", exc_info=True)

    async def generate(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.4,
        max_tokens: int | None = None,
    ) -> str:
        await self._maybe_swap()
        return await self._current.generate(
            messages, temperature=temperature, max_tokens=max_tokens
        )

    async def generate_structured(
        self,
        messages: list[dict],
        schema: type[Any],
        **kwargs: Any,
    ) -> Any:
        await self._maybe_swap()
        return await self._current.generate_structured(messages, schema, **kwargs)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._current is not self._base:
            try:
                await self._current.aclose()
            except Exception:
                logger.warning("llm_hot_swap_close_failed", exc_info=True)
        await self._base.aclose()


__all__ = ["HotSwapLLMProvider", "LLM_CONFIG_KEY"]
