"""Collapse album members into a single history line for the model.

An album arrives as N separate Telegram messages, so N history rows are written
— one per member, each tagged ``[imagen parte de álbum]``. The rows stay
one-per-member (the raw history keeps every real timestamp, which the memory
boundary logic reads), but the model does not need 30 near-identical lines
eating its short history window. So the collapse happens here, on the way in to
the Analyst, not on the way to the database.

The surviving line is the first member — its text (with the caption, which
Telegram attaches to one of the members) is kept — annotated with how many
members the album carried: ``[imagen parte de álbum ×30]``. A run of one is
returned untouched, so a lone image in no album keeps its plain tag.

The album marker is written by the telegram layer; the local copy below is
deliberate — Cognitive never imports telegram/ (AGENTS §Capas).
"""

from __future__ import annotations

from typing import Any

# Local copy of ``telegram/media_tags.ALBUM_MARK``. Do not import telegram/.
_ALBUM_MARK = " parte de álbum"


def collapse_album_runs(rows: list[dict]) -> list[dict]:
    """Collapse consecutive album-member rows (same role) into the first one.

    Rows are port rows (``role`` / ``text`` / ``timestamp``). Non-album rows and
    the overall order are preserved. Rows are copied, never mutated, and a
    single-member run is returned as-is (no ``×1`` noise).
    """
    out: list[dict] = []
    index = 0
    total = len(rows)
    while index < total:
        row = rows[index]
        if not _is_album_row(row):
            out.append(row)
            index += 1
            continue
        role = row.get("role")
        end = index + 1
        while end < total and _is_album_row(rows[end]) and rows[end].get("role") == role:
            end += 1
        count = end - index
        out.append(row if count == 1 else _annotate(row, count))
        index = end
    return out


def _is_album_row(row: Any) -> bool:
    return isinstance(row, dict) and _ALBUM_MARK in str(row.get("text") or "")


def _annotate(row: dict, count: int) -> dict:
    text = str(row.get("text") or "")
    return {**row, "text": text.replace(_ALBUM_MARK, f"{_ALBUM_MARK} ×{count}", 1)}


__all__ = ["collapse_album_runs"]
