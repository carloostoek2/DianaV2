"""VideoDescriber — una sola pregunta: ¿qué muestra este video?

Componente cognitivo (una pregunta, una respuesta) que convierte los bytes de
un video en una frase corta y objetiva en español neutro. No conoce Telegram ni
el filtro de privacidad: la capa de aplicación lo llama solo para videos que ya
pasaron la revisión local, y trata un fallo como fail-open (etiqueta plana de
media).

El prompt vive aquí (los prompts de negocio son de la capa cognitiva; la capa
de proveedor nunca los contiene). La llamada multimodal sale por el puerto
``VisionProvider`` (``llm.gemini_vision`` en producción), así que este módulo
nunca importa telegram ni aiogram.
"""

from __future__ import annotations

import logging

from diana.cognitive.ports import VisionProvider

logger = logging.getLogger(__name__)

# Español neutro, objetivo y corto. El video ya pasó la revisión local de
# fotogramas; aun así el prompt prohíbe repetir datos personales, para que la
# descripción nunca los exponga.
_SYSTEM_PROMPT = (
    "Describe brevemente qué muestra este video, como si se lo describieras "
    "a una amiga por chat. Una sola frase, máximo 40 palabras, en español "
    "neutro, objetiva y sin adornos. Di qué se ve y qué pasa; si hay frases "
    "escritas sobre el video, cuenta de qué tratan sin copiarlas palabra por "
    "palabra. No inventes información que no aparezca. Si el video no se "
    "entiende, di exactamente: 'video no claro'. No repitas números, nombres "
    "ni datos personales."
)

_MAX_CAPTION_CHARS = 400


class VideoDescriber:
    """Describe un video a través del proveedor de visión (fail-open)."""

    def __init__(self, vision: VisionProvider) -> None:
        self._vision = vision

    async def describe(self, video_bytes: bytes, *, mime_type: str) -> str | None:
        """Devuelve una descripción corta, o None cuando el proveedor falla.

        None es la señal de fail-open: quien llama conserva la etiqueta plana
        de media y el turno sigue igual que antes de la visión de video.
        """
        try:
            text = await self._vision.describe_video(
                video_bytes,
                mime_type=mime_type,
                prompt=_SYSTEM_PROMPT,
            )
        except Exception as exc:
            logger.warning(
                "video_describer_failed_fail_open",
                extra={"error_type": type(exc).__name__},
            )
            return None
        caption = (text or "").strip()
        if not caption:
            return None
        return caption[: _MAX_CAPTION_CHARS]


__all__ = ["VideoDescriber"]
