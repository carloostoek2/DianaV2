"""ImageDescriber — single question: what does this image show?

A cognitive component (one question, one answer) that turns image bytes into a
short objective Spanish caption. It knows nothing about Telegram or the privacy
filter: the application layer calls it ONLY for images already classified as
non-sensitive, and treats a failure as fail-open (plain media tag).

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
# sensitivity filter; the prompt still forbids echoing personal data so the
# caption never surfaces identifiers even on a false-negative edge case.
_SYSTEM_PROMPT = (
    "Describe brevemente qué muestra esta imagen, como si se la describieras "
    "a una amiga por chat. Una sola frase, máximo 40 palabras, en español "
    "neutro, objetiva y sin adornos. No inventes información que no se vea. "
    "Si la imagen es ilegible o no se entiende, di exactamente: "
    "'imagen no clara'. No repitas números, nombres ni datos personales."
)

_MAX_CAPTION_CHARS = 400


class ImageDescriber:
    """Captions an image via the injected vision provider (fail-open)."""

    def __init__(self, vision: VisionProvider) -> None:
        self._vision = vision

    async def describe(
        self, image_bytes: bytes, *, mime_type: str
    ) -> str | None:
        """Return a short caption, or None when the provider call fails.

        None is the fail-open signal: the caller keeps the plain media tag and
        the turn continues exactly as before the vision feature.
        """
        try:
            text = await self._vision.describe_image(
                image_bytes,
                mime_type=mime_type,
                prompt=_SYSTEM_PROMPT,
            )
        except Exception as exc:
            logger.warning(
                "image_describer_failed_fail_open",
                extra={"error_type": type(exc).__name__},
            )
            return None
        caption = (text or "").strip()
        if not caption:
            return None
        return caption[: _MAX_CAPTION_CHARS]


__all__ = ["ImageDescriber"]
