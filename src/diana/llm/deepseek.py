"""DeepSeek OpenAI-compatible client via httpx (I/O boundary only)."""

from __future__ import annotations

import ipaddress
import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, SecretStr

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?\s*```\s*$",
    re.DOTALL,
)
_INTERNAL_SCHEMA_FIELDS = frozenset({"raw_llm_output"})
_METADATA_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata",
        "169.254.169.254",
    }
)


def validate_llm_base_url(base_url: str) -> str:
    """Require https and reject file:// / private metadata endpoints."""
    url = (base_url or "").strip()
    if not url:
        raise ValueError("base_url must not be empty")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("llm_base_url / base_url must use https scheme")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("base_url must include a hostname")
    if host in _METADATA_HOSTS:
        raise ValueError("base_url host is not allowed (metadata endpoint)")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise ValueError("base_url must not target private or link-local addresses")
    return url.rstrip("/")


def strip_json_fences(content: str) -> str:
    """Remove optional markdown code fences around a JSON payload.

    Strict mode: only accepts content that is either wrapped in a single
    markdown fence or that starts and ends with a JSON object. With
    ``response_format: json_object`` enforced upstream, the LLM is contracted
    to return JSON; we no longer auto-substring between the first ``{`` and
    the last ``}`` because that fallback was too permissive (e.g. prose with
    an unrelated ``{`` mid-sentence would be silently extracted as a broken
    JSON object).
    """
    text = content.strip()
    match = _FENCE_RE.match(text)
    if match:
        return match.group(1).strip()
    # If the whole content already looks like a single JSON object, return as-is.
    if text.startswith("{") and text.endswith("}"):
        return text
    # Otherwise fail loud — caller will raise ValueError on json.loads.
    return text


def schema_hint_for_llm(schema: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema for the model without internal fields like raw_llm_output."""
    hint = schema.model_json_schema()
    props = hint.get("properties")
    if isinstance(props, dict):
        for name in _INTERNAL_SCHEMA_FIELDS:
            props.pop(name, None)
        required = hint.get("required")
        if isinstance(required, list):
            hint["required"] = [r for r in required if r not in _INTERNAL_SCHEMA_FIELDS]
    return hint


class DeepSeekProvider:
    """HTTP client for DeepSeek chat completions (OpenAI-compatible).

    Construction fails loud if ``api_key`` is empty or ``base_url`` is unsafe.
    Unit tests must inject an ``httpx.AsyncClient`` backed by
    ``httpx.MockTransport`` — never hit the network.

    Ownership: when ``client`` is injected, the caller owns lifecycle;
    ``aclose()`` only closes a client created by this provider.
    """

    name: str = "deepseek"

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
        thinking_enabled: bool = True,
    ) -> None:
        if not isinstance(api_key, SecretStr):
            raise TypeError("api_key must be a pydantic SecretStr")
        secret = api_key.get_secret_value().strip()
        if not secret:
            raise ValueError("api_key must not be empty for DeepSeekProvider")
        self._api_key = secret  # kept only for Authorization header at I/O boundary
        self._base_url = validate_llm_base_url(base_url)
        self._model = model
        self._thinking_enabled = thinking_enabled
        self._owns_client = client is None
        # Thinking adds CoT latency; give more room than the plain-text default.
        self._timeout = timeout if not thinking_enabled else max(timeout, 120.0)
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        # Always bind Authorization from constructor api_key (ignore pre-set client auth).
        self._client.headers["Authorization"] = f"Bearer {self._api_key}"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def generate(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.4,
        max_tokens: int | None = None,
    ) -> str:
        # With thinking on, CoT + final draft share the token budget.
        if max_tokens is None:
            max_tokens = 4096 if self._thinking_enabled else 1024
        thinking_type = "enabled" if self._thinking_enabled else "disabled"
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # Free-text drafts may use thinking for better quality.
            # Never fall back to reasoning_content as the draft (leak risk).
            "thinking": {"type": thinking_type},
        }
        data = await self._chat_completions(payload)
        content = self._extract_content(data)
        if not content.strip():
            logger.error(
                "deepseek generate empty content",
                extra={
                    "model": self._model,
                    "thinking": thinking_type,
                    "finish_reason": _finish_reason(data),
                    "had_reasoning": _has_reasoning_content(data),
                },
            )
        return content

    async def generate_structured(
        self,
        messages: list[dict],
        schema: type[BaseModel],
        **kwargs: Any,
    ) -> BaseModel:
        temperature = float(kwargs.get("temperature", 0.0))
        # Structured nodes need headroom; default higher than free-text generate.
        max_tokens = int(kwargs.get("max_tokens", 2048))
        schema_hint = json.dumps(schema_hint_for_llm(schema), ensure_ascii=False)
        instruction = (
            "Respond with a single JSON object only (no markdown fences) that "
            f"matches this JSON Schema:\n{schema_hint}"
        )
        # Merge with existing system message to avoid consecutive system roles.
        augmented: list[dict[str, Any]] = []
        if messages and messages[0].get("role") == "system":
            first = messages[0]
            augmented.append({
                "role": "system",
                "content": f"{instruction}\n\n{first['content']}",
            })
            augmented.extend(messages[1:])
        else:
            augmented = [{"role": "system", "content": instruction}, *messages]
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": augmented,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            # ALWAYS disabled for structured JSON: CoT can exhaust max_tokens
            # and leave content empty → Analyst/Evaluator schema failures.
            # Independent of llm_thinking_enabled (draft-only switch).
            "thinking": {"type": "disabled"},
        }
        data = await self._chat_completions(payload)
        content = self._extract_content(data)
        cleaned = strip_json_fences(content)
        if not cleaned.strip():
            logger.error(
                "deepseek structured empty content",
                extra={
                    "model": self._model,
                    "finish_reason": _finish_reason(data),
                    "content_preview": repr(content)[:200],
                },
            )
            raise ValueError("assistant content is empty after structured call")
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error(
                "deepseek structured invalid JSON",
                extra={
                    "model": self._model,
                    "content_preview": cleaned[:500],
                    "json_error": str(exc),
                },
            )
            raise ValueError(
                "assistant content is not valid JSON after fence strip"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError("structured response must be a JSON object")
        # Drop internal fields the model may have hallucinated.
        payload_for_model = {
            k: v for k, v in parsed.items() if k not in _INTERNAL_SCHEMA_FIELDS
        }
        instance = schema.model_validate(payload_for_model)
        if "raw_llm_output" in schema.model_fields:
            instance = instance.model_copy(
                update={"raw_llm_output": dict(payload_for_model)}
            )
        return instance

    async def _chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/chat/completions"
        response = await self._client.post(url, json=payload)
        if response.is_error:
            detail = response.text
            logger.error(
                "deepseek http %s %s — response: %s",
                response.status_code,
                url,
                detail[:2000],
            )
            response.raise_for_status()
        return response.json()

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str:
        try:
            message = data["choices"][0]["message"]
            content = message.get("content")
        except (KeyError, IndexError, TypeError) as exc:
            # Avoid dumping full completion bodies into exception messages.
            raise ValueError("unexpected chat completion shape") from exc
        if content is None:
            content = ""
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and "text" in part:
                    parts.append(str(part["text"]))
            content = "".join(parts)
        return str(content)


def _finish_reason(data: dict[str, Any]) -> str | None:
    try:
        return data["choices"][0].get("finish_reason")
    except (KeyError, IndexError, TypeError):
        return None


def _has_reasoning_content(data: dict[str, Any]) -> bool:
    """True when the model returned internal CoT (never use as public draft)."""
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return False
    reasoning = message.get("reasoning_content")
    return isinstance(reasoning, str) and bool(reasoning.strip())
