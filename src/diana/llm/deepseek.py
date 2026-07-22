"""DeepSeek OpenAI-compatible client via httpx (I/O boundary only)."""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel, SecretStr


class DeepSeekProvider:
    """HTTP client for DeepSeek chat completions (OpenAI-compatible).

    Construction fails loud if ``api_key`` is empty. Unit tests must inject an
    ``httpx.AsyncClient`` backed by ``httpx.MockTransport`` — never hit the network.
    """

    name: str = "deepseek"

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        secret = api_key.get_secret_value().strip()
        if not secret:
            raise ValueError("api_key must not be empty for DeepSeekProvider")
        self._api_key = secret
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        # Ensure auth is set even when caller supplies a bare client.
        if "Authorization" not in self._client.headers:
            self._client.headers["Authorization"] = f"Bearer {self._api_key}"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def generate(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        data = await self._chat_completions(payload)
        return self._extract_content(data)

    async def generate_structured(
        self,
        messages: list[dict],
        schema: type[BaseModel],
        **kwargs: Any,
    ) -> BaseModel:
        temperature = float(kwargs.get("temperature", 0.0))
        max_tokens = int(kwargs.get("max_tokens", 1024))
        schema_hint = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        instruction = (
            "Respond with a single JSON object only (no markdown fences) that "
            f"matches this JSON Schema:\n{schema_hint}"
        )
        augmented = list(messages) + [{"role": "system", "content": instruction}]
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": augmented,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        data = await self._chat_completions(payload)
        content = self._extract_content(data)
        parsed = json.loads(content)
        return schema.model_validate(parsed)

    async def _chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/chat/completions"
        response = await self._client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"unexpected chat completion shape: {data!r}") from exc
        if content is None:
            raise ValueError("assistant content is null")
        return str(content)
