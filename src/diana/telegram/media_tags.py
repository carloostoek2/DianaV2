"""How an inbound media message is shown to the model.

One place decides the tag, shared by the two paths that record what a human
sent: the VIP inbound handler (``handlers/business.py``) and the owner's own
messages (``middlewares/owner.py``). Keeping it in one module is deliberate —
the two drifted apart once already, and the owner's media ended up with no tag
at all while the VIP's had one.

Telegram quirk that shapes the table: a GIF from the GIF picker carries BOTH
``animation`` and ``document`` (the Bot API sets ``document`` as well whenever
``animation`` is present, for backward compatibility). Lookup is first-match,
so ``animation`` must come before ``document``. Every other content type is
exclusive — a video/voice/audio message sets no ``document`` — so that pair is
the only order-sensitive one.
"""

from __future__ import annotations

from typing import Any

# Content types that carry no text: the model sees only the tag so it knows a
# file was sent. Order matters, see the module docstring.
_MEDIA_TAGS: tuple[tuple[str, str], ...] = (
    ("photo", "imagen"),
    ("animation", "gif"),
    ("video", "video"),
    ("audio", "audio"),
    ("voice", "voz"),
    ("video_note", "video"),
    ("document", "documento"),
    ("sticker", "sticker"),
)

# Appended to the tag of every member of an album (media group). Each member
# arrives as its own update and gets its own history row, so the tag must read
# as "one image OF an album" — never as "an album", which the model would read
# as N separate albums when it sees N rows.
ALBUM_MARK = " parte de álbum"


def media_tag(message: Any) -> str:
    """Bare media tag for a message, or ``''`` when it carries no media.

    Album members carry the album mark: ``imagen`` → ``imagen parte de álbum``.
    """
    for kind, tag in _MEDIA_TAGS:
        if getattr(message, kind, None) is not None:
            if getattr(message, "media_group_id", None) is not None:
                return f"{tag}{ALBUM_MARK}"
            return tag
    return ""


def inbound_text(message: Any) -> str:
    """Text for the inbound DTO: media gets a visible type tag + caption.

    A media message without caption has neither ``text`` nor ``caption``, so
    the model would otherwise see an empty message. Non-media messages keep
    their raw text, unchanged.
    """
    tag = media_tag(message)
    if not tag:
        return (
            getattr(message, "text", None)
            or getattr(message, "caption", None)
            or ""
        )
    caption = (getattr(message, "caption", None) or "").strip()
    return f"[{tag}]" if not caption else f"[{tag}] {caption}"


__all__ = ["ALBUM_MARK", "inbound_text", "media_tag"]
