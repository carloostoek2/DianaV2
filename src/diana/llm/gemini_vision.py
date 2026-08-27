"""Gemini vision provider — HTTP client for image captioning (I/O only).

Talks to the Google Generative Language API (``generateContent``) with an
inline base64 image. This module is a pure I/O boundary, exactly like
``DeepSeekProvider``: no business prompts (the caller passes ``prompt``), no
privacy decisions, no knowledge of Telegram. Construction fails loud when the
API key is empty; network failures surface as httpx exceptions for the caller
to handle (fail-open at the orchestration layer).

Privacy note: images are sent to Google only after the local OCR filter
classified them as non-sensitive (see ``application.image_vision_service``).
The image bytes are never stored anywhere by this module.
"""

from __future__ import annotations

import base64
import logging

import httpx
from pydantic import SecretStr

logger = logging.getLogger(__name__)

_GENERATE_CONTENT_PATH = "/v1beta/models/{model}:generateContent"
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
_MAX_OUTPUT_TOKENS = 300


class GeminiVisionProvider:
    """Minimal Gemini image captioning client (chat completions style)."""

    name: str = "gemini_vision"

    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str = "gemini-3.6-flash",
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not isinstance(api_key, SecretStr):
            raise TypeError("api_key must be a pydantic SecretStr")
        key = api_key.get_secret_value().strip()
        if not key:
            raise ValueError("api_key must not be empty for GeminiVisionProvider")
        if not model or not str(model).strip():
            raise ValueError("model must not be empty")
        self._api_key = key
        self._model = str(model).strip()
        self._timeout = float(timeout)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=_GEMINI_BASE_URL,
            timeout=self._timeout,
            headers={"Content-Type": "application/json"},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def describe_image(
        self,
        image_bytes: bytes,
        *,
        mime_type: str,
        prompt: str,
    ) -> str:
        """Caption the image via Gemini; returns the model text.

        Raises httpx/ValueError on failure — callers decide the fallback
        (fail-open keeps the plain media tag when Gemini is unavailable).
        """
        if not image_bytes:
            raise ValueError("image_bytes must not be empty")
        if not mime_type or not str(mime_type).strip():
            raise ValueError("mime_type must not be empty")
        if not prompt or not str(prompt).strip():
            raise ValueError("prompt must not be empty")
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": str(mime_type).strip(),
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": _MAX_OUTPUT_TOKENS,
                "candidateCount": 1,
            },
        }
        url = f"{_GEMINI_BASE_URL}{_GENERATE_CONTENT_PATH.format(model=self._model)}"
        response = await self._client.post(
            url,
            json=payload,
            params={"key": self._api_key},
        )
        if response.is_error:
            detail = response.text[:2000]
            logger.error(
                "gemini_vision http %s %s — %s",
                response.status_code,
                url,
                detail,
            )
            response.raise_for_status()
        return _extract_text(response.json())


def _extract_text(data: dict) -> str:
    """Pull the first candidate's text parts from a generateContent response."""
    try:
        candidates = data["candidates"]
        parts = candidates[0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("unexpected generateContent response shape") from exc
    text = "".join(
        str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict) and part.get("text")
    )
    return text.strip()


__all__ = ["GeminiVisionProvider"]
