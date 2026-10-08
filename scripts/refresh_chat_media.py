"""Refresca la media importada de un chat: vuelve a bajarla y la describe.

La importación del alta es idempotente y no reescribe filas que ya existen, así
que un archivo que quedó sin describir (por peso, por un fallo del proveedor o
porque la visión estaba apagada) se queda mudo para siempre. Este script arregla
eso para un chat puntual:

    .venv/bin/python scripts/refresh_chat_media.py --chat 5896134400

Vuelve a traer los últimos mensajes con archivo por la cuenta personal, los pasa
por el mismo filtro de privacidad que la media en vivo y actualiza la fila del
historial con la descripción. Nunca guarda la foto ni el video: solo su texto.

Ejecutar desde la raíz del repositorio con el intérprete del proyecto.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

os.chdir(_ROOT)

from diana.application.image_vision_service import ImageVisionService  # noqa: E402
from diana.application.media_text import compose_media_text  # noqa: E402
from diana.application.video_vision_service import VideoVisionService  # noqa: E402
from diana.cognitive.image_vision import ImageDescriber  # noqa: E402
from diana.cognitive.video_vision import VideoDescriber  # noqa: E402
from diana.config.settings import Settings  # noqa: E402
from diana.infrastructure.db.repositories.history import (  # noqa: E402
    SqlMessageHistoryRepo,
)
from diana.infrastructure.db.session import (  # noqa: E402
    create_engine,
    create_session_factory,
)
from diana.infrastructure.telethon.vip_history_fetcher import (  # noqa: E402
    TelethonVipHistoryFetcher,
)
from diana.infrastructure.vision.ocr import OcrEngine, detect_image_mime  # noqa: E402
from diana.infrastructure.vision.video_frames import (  # noqa: E402
    FfmpegFrameExtractor,
)
from diana.llm.gemini_vision import GeminiVisionProvider  # noqa: E402


# Una fila ya descrita empieza con la etiqueta y dos puntos: "[video: …]".
_YA_DESCRITA = re.compile(r"^\[(?:imagen|foto|video):")


async def _describe(line, *, image_vision, video_vision, tag_for_kind):
    """Describe la media de una línea; devuelve None si no hay nada que hacer."""
    kind = (line.media_kind or "").lower()
    tag = tag_for_kind(kind)
    if tag is None:
        return None
    if kind.startswith("foto"):
        result = await image_vision.analyze(
            line.media_bytes, mime_type=detect_image_mime(line.media_bytes)
        )
    else:
        result = await video_vision.analyze(
            line.media_bytes, mime_type=line.media_mime or "video/mp4"
        )
    if not result.enabled:
        return None
    if not result.description and not result.sensitive:
        # Fallo abierto del proveedor (sin cuota, sin red, error): no hay nada
        # nuevo que escribir. Sin esta guarda, un fallo BORRARÍA una
        # descripción ya guardada y dejaría la etiqueta muda en su lugar.
        return None
    return compose_media_text(result, tag=tag, caption=line.caption)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Refresca la media de un chat")
    parser.add_argument("--chat", type=int, required=True, help="chat_id del VIP")
    parser.add_argument("--window", type=int, default=20, help="mensajes a mirar")
    parser.add_argument(
        "--limit", type=int, default=5, help="archivos a traer y describir"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="muestra lo que haría, sin escribir"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="vuelve a describir lo que ya tiene descripción (gasta cuota)",
    )
    args = parser.parse_args()

    settings = Settings()
    engine = create_engine()
    sf = create_session_factory(engine)
    history = SqlMessageHistoryRepo(sf)

    provider = GeminiVisionProvider(
        api_key=settings.gemini_api_key,
        model=settings.gemini_vision_model,
        timeout=settings.gemini_vision_timeout_s,
        video_timeout=settings.gemini_video_timeout_s,
    )
    ocr = OcrEngine()
    image_vision = ImageVisionService(
        ocr=ocr,
        describer=ImageDescriber(vision=provider),
        enabled=settings.feature_image_vision_enabled,
    )
    video_vision = VideoVisionService(
        frames=FfmpegFrameExtractor(max_frames=settings.video_vision_max_frames),
        ocr=ocr,
        describer=VideoDescriber(vision=provider),
        enabled=settings.feature_video_vision_enabled,
        send_max_bytes=settings.video_vision_send_max_bytes,
        frames_to_send=settings.video_vision_frames_sent,
    )
    fetcher = TelethonVipHistoryFetcher(
        api_id=int(settings.telethon_api_id or 0),
        api_hash=settings.telethon_api_hash.get_secret_value(),
        session_path=settings.telethon_session_path,
        media_limit=args.limit,
    )

    def tag_for_kind(kind: str) -> str | None:
        if kind.startswith("foto"):
            return "imagen"
        if kind.startswith("video"):
            return "video"
        return None

    print(f"trayendo los últimos {args.window} mensajes del chat {args.chat}…")
    lines = await fetcher.fetch_recent(args.chat, limit=args.window)
    stored = {
        row["telegram_message_id"]: row
        for row in await history.get_recent(args.chat, limit=args.window)
    }

    cambios = 0
    for line in lines:
        if line.role != "vip" or not line.media_bytes:
            continue
        texto = await _describe(
            line,
            image_vision=image_vision,
            video_vision=video_vision,
            tag_for_kind=tag_for_kind,
        )
        if not texto:
            continue
        actual = stored.get(line.telegram_message_id)
        if actual is not None and actual.get("text") == texto:
            print(f"  id={line.telegram_message_id}: sin cambios")
            continue
        if (
            actual is not None
            and _YA_DESCRITA.search(str(actual.get("text") or ""))
            and not args.force
        ):
            # Ya tiene descripción: volver a describirla gasta cuota y puede
            # cambiarla por otra peor.
            print(f"  id={line.telegram_message_id}: ya estaba descrita, se deja igual")
            continue
        antes = (actual or {}).get("text")
        print(f"  id={line.telegram_message_id}:")
        print(f"    antes: {antes!r}")
        print(f"    ahora: {texto!r}")
        if not args.dry_run:
            await history.upsert_vip_message(
                args.chat,
                text=texto,
                telegram_message_id=line.telegram_message_id,
                timestamp=line.timestamp,
            )
        cambios += 1

    await provider.aclose()
    await engine.dispose()
    print(f"{cambios} fila(s) {'por actualizar' if args.dry_run else 'actualizada(s)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
