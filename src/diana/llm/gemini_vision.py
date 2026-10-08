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
from collections.abc import Sequence

import httpx
from pydantic import SecretStr

logger = logging.getLogger(__name__)

_GENERATE_CONTENT_PATH = "/v1beta/models/{model}:generateContent"
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
_MAX_OUTPUT_TOKENS = 300
# Un video tarda más que una foto: hay que subir el archivo y el modelo lo
# recorre cuadro por cuadro. El plazo de las fotos (15 s) queda corto.
_DEFAULT_VIDEO_TIMEOUT_S = 45.0


class GeminiVisionProvider:
    """Minimal Gemini image captioning client (chat completions style)."""

    name: str = "gemini_vision"

    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str = "gemini-3.6-flash",
        timeout: float = 15.0,
        video_timeout: float = _DEFAULT_VIDEO_TIMEOUT_S,
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
        self._video_timeout = float(video_timeout)
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
        return await self._describe_media(
            image_bytes,
            mime_type=mime_type,
            prompt=prompt,
            timeout=self._timeout,
            empty_error="image_bytes must not be empty",
        )

    async def describe_video(
        self,
        video_bytes: bytes,
        *,
        mime_type: str,
        prompt: str,
    ) -> str:
        """Describe el video con Gemini; devuelve el texto del modelo.

        Mismo contrato que las fotos, con un plazo más largo. El video solo
        llega aquí después de la revisión local de fotogramas (ver
        ``application.video_vision_service``); estos bytes nunca se guardan.
        """
        return await self._describe_media(
            video_bytes,
            mime_type=mime_type,
            prompt=prompt,
            timeout=self._video_timeout,
            empty_error="video_bytes must not be empty",
        )

    async def describe_images(
        self,
        images: Sequence[bytes],
        *,
        mime_type: str,
        prompt: str,
    ) -> str:
        """Describe varias imágenes en UNA sola llamada.

        Se usa para los videos que no entran en un solo envío: viajan los
        cuadros ya revisados localmente, no el archivo completo.
        """
        return await self._describe_media_many(
            list(images),
            mime_type=mime_type,
            prompt=prompt,
            timeout=self._video_timeout,
            empty_error="images must not be empty",
        )

    async def _describe_media(
        self,
        media_bytes: bytes,
        *,
        mime_type: str,
        prompt: str,
        timeout: float,
        empty_error: str,
    ) -> str:
        """Envía una media en línea (inline_data) y devuelve el texto del modelo."""
        return await self._describe_media_many(
            [media_bytes],
            mime_type=mime_type,
            prompt=prompt,
            timeout=timeout,
            empty_error=empty_error,
        )

    async def _describe_media_many(
        self,
        media: list[bytes],
        *,
        mime_type: str,
        prompt: str,
        timeout: float,
        empty_error: str,
    ) -> str:
        """Envía una o varias medias en un único pedido."""
        if not media or any(not item for item in media):
            raise ValueError(empty_error)
        if not mime_type or not str(mime_type).strip():
            raise ValueError("mime_type must not be empty")
        if not prompt or not str(prompt).strip():
            raise ValueError("prompt must not be empty")
        parts: list[dict[str, object]] = [{"text": prompt}]
        parts.extend(
            {
                "inline_data": {
                    "mime_type": str(mime_type).strip(),
                    "data": base64.b64encode(item).decode("ascii"),
                }
            }
            for item in media
        )
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": _MAX_OUTPUT_TOKENS,
                "candidateCount": 1,
                # El modelo "piensa" antes de responder y ese razonamiento se
                # descuenta del tope de salida: con el tope puesto en la
                # respuesta, la descripción quedaba cortada a la mitad
                # (finishReason=MAX_TOKENS). Describir lo que se ve no necesita
                # razonamiento.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        url = f"{_GEMINI_BASE_URL}{_GENERATE_CONTENT_PATH.format(model=self._model)}"
        response = await self._client.post(
            url,
            json=payload,
            params={"key": self._api_key},
            timeout=timeout,
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
