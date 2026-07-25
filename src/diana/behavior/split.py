"""Pure text split helpers for advanced delivery (H3.6).

Never mutates meaning beyond boundary selection. No I/O, no LLM.
"""

from __future__ import annotations

_BREAK_CHARS = frozenset(".,\n")


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
        remaining = remaining[cut:].lstrip()
        if not remaining and not segment:
            # Safety: hard-progress if strip emptied both sides.
            remaining = remaining  # pragma: no cover
            break

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
