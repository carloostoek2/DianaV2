"""ProfilesRepo — VIP permanent profile by PK (BR-15 anti-contamination).

Content schema (owner-editable enrichable layer)::

    {"facts": {str: str}, "notes": [{"date": "YYYY-MM-DD", "text": str}]}

Pure helpers normalize/mutate content without DB. Writers upsert by ``vip_id``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from diana.infrastructure.db.models import Profile

_ZERO_EMBEDDING: list[float] = [0.0] * 384


def empty_content() -> dict[str, Any]:
    """Return the canonical empty facts/notes shell."""
    return {"facts": {}, "notes": []}


def normalize_content(raw: Any) -> dict[str, Any]:
    """Coerce arbitrary payload to the locked facts/notes schema.

    Drops unknown top-level keys. Invalid facts/notes entries are skipped.
    Non-dict / missing input yields an empty shell.
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


def is_hollow_content(content: Any) -> bool:
    """True when content is an empty facts+notes shell (after normalize)."""
    normalized = normalize_content(content)
    return len(normalized["facts"]) == 0 and len(normalized["notes"]) == 0


def apply_set_fact(content: dict[str, Any], key: str, value: str) -> dict[str, Any]:
    """Return a new content dict with ``facts[key]=value``. Rejects empty key/value."""
    k = (key or "").strip()
    v = (value or "").strip()
    if not k or not v:
        raise ValueError("fact key and value must be non-empty")
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
    """Append a note ``{date, text}``. Rejects empty text."""
    t = (text or "").strip()
    d = (date or "").strip()
    if not t:
        raise ValueError("note text must be non-empty")
    if not d:
        raise ValueError("note date must be non-empty")
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


def profile_to_dict(row: Profile) -> dict:
    """Convert a Profile ORM row to a plain dict for retriever consumption."""
    return {
        "vip_id": str(row.vip_id),
        "tipo": row.tipo,
        "content": row.content,
        "created_at": (
            row.created_at.isoformat()
            if hasattr(row.created_at, "isoformat")
            else str(row.created_at)
        ),
        "updated_at": (
            row.updated_at.isoformat()
            if hasattr(row.updated_at, "isoformat")
            else str(row.updated_at)
        ),
    }


class ProfilesRepo:
    """VIP permanent profile store (BR-15: every query filters by vip_id)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def _load(self, session: AsyncSession, vip_id: UUID) -> Profile | None:
        result = await session.execute(
            select(Profile).where(Profile.vip_id == vip_id)
        )
        return result.scalar_one_or_none()

    async def get_by_vip_id(self, vip_id: UUID) -> dict | None:
        """Return the profile row for ``vip_id``, or None if missing."""
        async with self._sf() as session:
            row = await self._load(session, vip_id)
            return profile_to_dict(row) if row else None

    async def set_fact(self, vip_id: UUID, key: str, value: str) -> dict:
        """Upsert row if missing; set ``facts[key]=value``; return profile dict."""
        # Validate early so empty key/value never opens a DB session.
        content = apply_set_fact(empty_content(), key, value)
        async with self._sf() as session:
            row = await self._load(session, vip_id)
            if row is None:
                row = Profile(
                    vip_id=vip_id,
                    embedding=list(_ZERO_EMBEDDING),
                    content=content,
                    tipo="summary",
                )
                session.add(row)
            else:
                row.content = apply_set_fact(
                    normalize_content(row.content), key, value
                )
                flag_modified(row, "content")
            await session.commit()
            await session.refresh(row)
            return profile_to_dict(row)

    async def delete_fact(self, vip_id: UUID, key: str) -> dict | None:
        """Delete fact key. Missing row → None; missing key → current dict."""
        async with self._sf() as session:
            row = await self._load(session, vip_id)
            if row is None:
                return None
            new_content, _deleted = apply_delete_fact(
                normalize_content(row.content), key
            )
            row.content = new_content
            flag_modified(row, "content")
            await session.commit()
            await session.refresh(row)
            return profile_to_dict(row)

    async def add_note(
        self, vip_id: UUID, text: str, *, date: str | None = None
    ) -> dict:
        """Upsert shell if missing; append note; return profile dict."""
        note_date = (date or datetime.now(UTC).date().isoformat()).strip()
        # Validate early.
        content = apply_add_note(empty_content(), text, note_date)
        async with self._sf() as session:
            row = await self._load(session, vip_id)
            if row is None:
                row = Profile(
                    vip_id=vip_id,
                    embedding=list(_ZERO_EMBEDDING),
                    content=content,
                    tipo="summary",
                )
                session.add(row)
            else:
                row.content = apply_add_note(
                    normalize_content(row.content), text, note_date
                )
                flag_modified(row, "content")
            await session.commit()
            await session.refresh(row)
            return profile_to_dict(row)

    async def delete_note(self, vip_id: UUID, index: int) -> dict | None:
        """Delete note at 0-based index. Missing row or OOB → None."""
        async with self._sf() as session:
            row = await self._load(session, vip_id)
            if row is None:
                return None
            new_content, deleted = apply_delete_note(
                normalize_content(row.content), index
            )
            if not deleted:
                return None
            row.content = new_content
            flag_modified(row, "content")
            await session.commit()
            await session.refresh(row)
            return profile_to_dict(row)


__all__ = [
    "ProfilesRepo",
    "apply_add_note",
    "apply_delete_fact",
    "apply_delete_note",
    "apply_set_fact",
    "empty_content",
    "is_hollow_content",
    "normalize_content",
    "profile_to_dict",
]
