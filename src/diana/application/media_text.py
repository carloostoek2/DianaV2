"""Texto del turno para la media ya analizada (foto o video).

Vive en la capa de aplicación porque lo usan dos caminos que no se conocen
entre sí: el handler de negocio (media que llega en vivo) y el importador de
historial (media que el VIP mandó antes de estar en la lista).

El caption nunca participa en la decisión de privacidad: viaja como texto
normal y lo procesa el control de seguridad del pipeline, igual que cualquier
mensaje del VIP.
"""

from __future__ import annotations

from diana.application.image_vision_service import ImageVisionResult
from diana.application.video_vision_service import VideoVisionResult

# Se agrega a la etiqueta cuando el filtro local marcó la media como sensible:
# no fue al proveedor y la dueña la revisa a mano.
SENSITIVE_MARK = "⚠️ contiene información sensible (no analizada)"


def media_without_description(
    result: ImageVisionResult | VideoVisionResult,
) -> bool:
    """True cuando la media llegó sin descripción (nada que leer ni contar).

    Cubre los tres caminos en que el modelo no puede saber qué mostraba la
    media: la visión estaba apagada, el filtro local la marcó sensible (nunca
    salió del servidor) o el proveedor no respondió (fail-open). Es la señal
    que impide que un turno con media no verificada se envíe solo.
    """
    return not (
        result.enabled and not result.sensitive and bool(result.description)
    )


def compose_media_text(
    result: ImageVisionResult | VideoVisionResult,
    *,
    tag: str,
    caption: str = "",
) -> str:
    """Arma el texto del turno a partir del resultado de visión."""
    if not result.enabled:
        text = f"[{tag}]"
    elif result.sensitive:
        text = f"[{tag}] {SENSITIVE_MARK}"
    elif result.description:
        text = f"[{tag}: {result.description}]"
    else:
        text = f"[{tag}]"
    if caption:
        text = f"{text} {caption}"
    return text


__all__ = ["SENSITIVE_MARK", "compose_media_text", "media_without_description"]
