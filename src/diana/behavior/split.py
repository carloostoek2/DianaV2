"""Pure text split helpers for advanced delivery (H3.6).

Never mutates meaning beyond boundary selection. No I/O, no LLM.
"""

from __future__ import annotations

import re

_BREAK_CHARS = frozenset(".,\n")
_BLANK_LINE_RE = re.compile(r"\n\s*\n")
# Single-newline fallback: each line must look like a real paragraph, not
# a short chat burst ("Hola" / "qué onda").
_MIN_SOFT_PARAGRAPH_LEN = 40


def split_paragraphs(text: str) -> list[str]:
    """Split conversational text into paragraph bubbles.

    Preference:
    1. Blank-line blocks — the model already chose paragraphs.
    2. Single newlines only when every non-empty line is long enough to be
       a paragraph (not a short two-line greeting).
    3. Otherwise keep a single bubble.

    Empty / whitespace-only inputs yield ``[]``. Segments are stripped.
    """
    stripped = text.strip()
    if not stripped:
        return []

    blank_parts = [p.strip() for p in _BLANK_LINE_RE.split(stripped) if p.strip()]
    if len(blank_parts) >= 2:
        return blank_parts

    lines = [ln.strip() for ln in stripped.split("\n") if ln.strip()]
    if (
        len(lines) >= 2
        and all(len(ln) >= _MIN_SOFT_PARAGRAPH_LEN for ln in lines)
    ):
        return lines
    return [stripped]


def split_text(text: str, max_chars: int) -> list[str]:
    """Split ``text`` into segments of at most ``max_chars``.

    Preference order inside each window:
    1. Last ``.`` / ``,`` / newline (include punct in left segment)
    2. Last whitespace (exclude space from both sides after strip)
    3. Hard cut at ``max_chars`` (no mid-character for ASCII; UTF-8 safe via str slice)

    Empty / whitespace-only inputs yield ``[]``. Segments are stripped; empties dropped.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")

    remaining = text.strip()
    if not remaining:
        return []
    if len(remaining) <= max_chars:
        return [remaining]

    parts: list[str] = []
    while remaining:
        if len(remaining) <= max_chars:
            parts.append(remaining)
            break

        window = remaining[:max_chars]
        cut = _find_cut(window)
        segment = remaining[:cut].strip()
        if segment:
            parts.append(segment)
        # cut is always >= 1 for non-empty window (_find_cut); remaining shrinks.
        remaining = remaining[cut:].lstrip()

    return [p for p in parts if p]


def _find_cut(window: str) -> int:
    """Return cut index in ``window`` (exclusive end for left segment)."""
    # Prefer punctuation / newline; include the break char in left segment.
    for i in range(len(window) - 1, -1, -1):
        if window[i] in _BREAK_CHARS:
            return i + 1
    # Whitespace: cut before the space (left ends at last non-space run).
    for i in range(len(window) - 1, -1, -1):
        if window[i].isspace():
            return i if i > 0 else len(window)
    return len(window)
