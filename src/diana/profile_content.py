"""Pure VIP enrichable profile content schema (facts + notes).

Shared across infrastructure writers, application admin, and cognitive read
path so hollow/normalize rules stay single-sourced. No I/O, no layer deps.
"""

from __future__ import annotations

from typing import Any

# Owner-write length caps (availability / prompt budget; SEC-PROF-06).
MAX_FACT_KEY_LEN = 64
MAX_FACT_VALUE_LEN = 500
MAX_NOTE_TEXT_LEN = 1000

__all__ = [
    "MAX_FACT_KEY_LEN",
    "MAX_FACT_VALUE_LEN",
    "MAX_NOTE_TEXT_LEN",
    "apply_add_note",
    "apply_delete_fact",
    "apply_delete_note",
    "apply_set_fact",
    "empty_content",
    "is_hollow_content",
    "normalize_content",
]


def empty_content() -> dict[str, Any]:
    """Return the canonical empty facts/notes shell."""
    return {"facts": {}, "notes": []}


def normalize_content(raw: Any) -> dict[str, Any]:
    """Coerce arbitrary payload to the locked facts/notes schema.

    Drops unknown top-level keys. Invalid facts/notes entries are skipped
    (including whitespace-only values). Non-dict / missing input → empty shell.
    """
    if not isinstance(raw, dict):
        return empty_content()

    facts_raw = raw.get("facts")
    facts: dict[str, str] = {}
    if isinstance(facts_raw, dict):
        for k, v in facts_raw.items():
            if not isinstance(k, str):
                continue
            key = k.strip()
            if not key:
                continue
            if not isinstance(v, str):
                continue
            val = v.strip()
            if not val:
                continue
            facts[key] = val

    notes_raw = raw.get("notes")
    notes: list[dict[str, str]] = []
    if isinstance(notes_raw, list):
        for item in notes_raw:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            date = item.get("date")
            if not isinstance(text, str) or not text.strip():
                continue
            if not isinstance(date, str) or not date.strip():
                continue
            notes.append({"date": date.strip(), "text": text.strip()})

    return {"facts": facts, "notes": notes}


def _payload_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict, tuple, set)) and len(value) == 0:
        return True
    return False


def is_hollow_content(content: Any) -> bool:
    """True when content has no meaningful enrichable / legacy profile payload.

    Option A (structured schema): after ``normalize_content``, empty facts and
    empty notes with no other non-empty top-level keys → hollow. Whitespace-only
    fact values are dropped by normalize and therefore hollow.

    Legacy flat shapes like ``{"fact": "prefers morning"}`` remain **not**
    hollow (other keys with non-empty payload keep the cognitive hit).
    """
    if content is None:
        return True
    if isinstance(content, (list, dict, tuple, set)) and len(content) == 0:
        return True
    if isinstance(content, str) and not content.strip():
        return True
    if not isinstance(content, dict):
        return True

    normalized = normalize_content(content)
    schema_empty = len(normalized["facts"]) == 0 and len(normalized["notes"]) == 0
    if not schema_empty:
        return False

    for key, value in content.items():
        if key in ("facts", "notes"):
            continue
        if not _payload_empty(value):
            return False
    return True


def apply_set_fact(content: dict[str, Any], key: str, value: str) -> dict[str, Any]:
    """Return a new content dict with ``facts[key]=value``.

    Rejects empty key/value and oversize key/value (raises ``ValueError``).
    """
    k = (key or "").strip()
    v = (value or "").strip()
    if not k or not v:
        raise ValueError("fact key and value must be non-empty")
    if len(k) > MAX_FACT_KEY_LEN:
        raise ValueError(f"fact key exceeds max length ({MAX_FACT_KEY_LEN})")
    if len(v) > MAX_FACT_VALUE_LEN:
        raise ValueError(f"fact value exceeds max length ({MAX_FACT_VALUE_LEN})")
    out = normalize_content(content)
    out["facts"] = dict(out["facts"])
    out["facts"][k] = v
    out["notes"] = list(out["notes"])
    return out


def apply_delete_fact(
    content: dict[str, Any], key: str
) -> tuple[dict[str, Any], bool]:
    """Delete ``facts[key]``. Returns (new_content, deleted)."""
    k = (key or "").strip()
    out = normalize_content(content)
    facts = dict(out["facts"])
    deleted = k in facts
    if deleted:
        del facts[k]
    out["facts"] = facts
    out["notes"] = list(out["notes"])
    return out, deleted


def apply_add_note(
    content: dict[str, Any], text: str, date: str
) -> dict[str, Any]:
    """Append a note ``{date, text}``. Rejects empty/oversize text."""
    t = (text or "").strip()
    d = (date or "").strip()
    if not t:
        raise ValueError("note text must be non-empty")
    if not d:
        raise ValueError("note date must be non-empty")
    if len(t) > MAX_NOTE_TEXT_LEN:
        raise ValueError(f"note text exceeds max length ({MAX_NOTE_TEXT_LEN})")
    out = normalize_content(content)
    out["facts"] = dict(out["facts"])
    out["notes"] = list(out["notes"])
    out["notes"].append({"date": d, "text": t})
    return out


def apply_delete_note(
    content: dict[str, Any], index: int
) -> tuple[dict[str, Any], bool]:
    """Delete note at 0-based index. OOB → (unchanged, False)."""
    out = normalize_content(content)
    notes = list(out["notes"])
    if not isinstance(index, int) or index < 0 or index >= len(notes):
        out["facts"] = dict(out["facts"])
        out["notes"] = notes
        return out, False
    notes.pop(index)
    out["facts"] = dict(out["facts"])
    out["notes"] = notes
    return out, True
