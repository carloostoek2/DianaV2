"""ImageDescriber — single question: what does this image show?

A cognitive component (one question, one answer) that turns image bytes into a
short objective Spanish caption. It knows nothing about Telegram or the privacy
filter: the application layer calls it ONLY for images that are safe to leave
the server (clean or locally redacted), and treats a failure as fail-open
(plain media tag).

The prompt lives here (cognitive owns business-facing prompts — the LLM
provider layer never contains them). The multimodal call goes through the
injected ``VisionProvider`` port (``llm.gemini_vision`` in production), so this
module never imports telegram/ or aiogram.
"""

from __future__ import annotations

import logging

from diana.cognitive.ports import VisionProvider

logger = logging.getLogger(__name__)

# Spanish-neutral, objective, short. The image already passed the local
# sensitivity filter (clean, or redacted with black boxes over hidden data);
# the prompt still forbids echoing personal data so the caption never surfaces
# identifiers even on a false-negative edge case. Redacted zones must be
# ignored completely — never mentioned, never guessed at.
_SYSTEM_PROMPT = (
    "Describe brevemente qué muestra esta imagen, como si se la describieras "
    "a una amiga por chat. Una sola frase, máximo 40 palabras, en español "
    "neutro, objetiva y sin adornos. No inventes información que no se vea. "
    "Si la imagen es ilegible o no se entiende, di exactamente: "
    "'imagen no clara'. Si la imagen tiene zonas tapadas con rectángulos "
    "negros (datos ocultos), ignóralas por completo: no las menciones, no "
    "intentes adivinar qué hay debajo y describe solo el resto de la imagen. "
    "No repitas números, nombres ni datos personales."
)

_MAX_CAPTION_CHARS = 400

# Un tropiezo de red no debe dejar la foto sin describir: el primer intento se
# repite una vez. Sin reintento, ~1 de cada 4 fotos reales llegaba al pipeline
# como "[imagen]" (medido 2026-10-27: ReadTimeout con el servicio respondiendo
# en 2–5 s en la siguiente llamada).
_ATTEMPTS = 2


class ImageDescriber:
    """Captions an image via the injected vision provider (fail-open)."""

    def __init__(self, vision: VisionProvider) -> None:
        self._vision = vision

    async def describe(
        self, image_bytes: bytes, *, mime_type: str
    ) -> str | None:
        """Return a short caption, or None when the provider call fails.

        None is the fail-open signal: the caller keeps the plain media tag and
        the turn continues exactly as before the vision feature. The provider
        is asked up to ``_ATTEMPTS`` times; a transient stall is retried once
        instead of giving up on the image.
        """
        text: str | None = None
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                text = await self._vision.describe_image(
                    image_bytes,
                    mime_type=mime_type,
                    prompt=_SYSTEM_PROMPT,
                )
                break
            except Exception as exc:
                if attempt < _ATTEMPTS:
                    logger.warning(
                        "image_describer_retrying",
                        extra={
                            "error_type": type(exc).__name__,
                            "attempt": attempt,
                        },
                    )
                    continue
                logger.warning(
                    "image_describer_failed_fail_open",
                    extra={
                        "error_type": type(exc).__name__,
                        "attempts": attempt,
                    },
                )
                return None
        caption = (text or "").strip()
        if not caption:
            return None
        return caption[: _MAX_CAPTION_CHARS]


__all__ = ["ImageDescriber"]
