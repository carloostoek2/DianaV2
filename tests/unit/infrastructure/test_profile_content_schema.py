"""Pure profile content schema helpers (facts + notes). No DB."""

from __future__ import annotations

import pytest

from diana.profile_content import (
    MAX_FACT_KEY_LEN,
    MAX_FACT_VALUE_LEN,
    MAX_NOTE_TEXT_LEN,
    apply_add_note,
    apply_delete_fact,
    apply_delete_note,
    apply_set_fact,
    empty_content,
    is_hollow_content,
    normalize_content,
)
# Re-export path still works for infra consumers.
from diana.infrastructure.db.repositories.profiles import (
    is_hollow_content as is_hollow_via_repo,
)


def test_empty_content_shell() -> None:
    assert empty_content() == {"facts": {}, "notes": []}


@pytest.mark.parametrize("raw", [None, {}, "bad", 42, []])
def test_normalize_content_invalid_to_empty_shell(raw: object) -> None:
    assert normalize_content(raw) == {"facts": {}, "notes": []}  # type: ignore[arg-type]


def test_normalize_content_keeps_facts_notes_drops_extra() -> None:
    raw = {"facts": {"a": "1"}, "notes": [], "extra": 1}
    out = normalize_content(raw)
    assert out == {"facts": {"a": "1"}, "notes": []}
    assert "extra" not in out


def test_normalize_content_coerces_bad_facts_and_notes() -> None:
    raw = {
        "facts": {"ok": "v", "": "x", "  ": "y", "k": "", "n": 1},
        "notes": [
            {"date": "2026-07-27", "text": "keep"},
            {"date": "bad", "text": "still"},
            "not-a-dict",
            {"date": "2026-01-01", "text": ""},
            {"text": "no-date"},
        ],
    }
    out = normalize_content(raw)
    assert out["facts"] == {"ok": "v"}
    assert out["notes"] == [
        {"date": "2026-07-27", "text": "keep"},
        {"date": "bad", "text": "still"},
    ]


def test_is_hollow_content() -> None:
    assert is_hollow_content(empty_content()) is True
    assert is_hollow_content({"facts": {}, "notes": []}) is True
    assert is_hollow_content({"facts": {"k": "v"}, "notes": []}) is False
    assert is_hollow_content({"facts": {}, "notes": [{"date": "2026-01-01", "text": "n"}]}) is False


def test_is_hollow_whitespace_only_facts() -> None:
    """Whitespace-only fact values normalize away → hollow (H2 parity)."""
    assert is_hollow_content({"facts": {"city": "  "}, "notes": []}) is True
    assert is_hollow_content({"facts": {"city": "  "}}) is True


def test_is_hollow_legacy_flat_not_hollow() -> None:
    """Legacy flat non-empty remains a hit for cognitive read."""
    assert is_hollow_content({"fact": "prefers morning"}) is False
    assert is_hollow_via_repo({"fact": "prefers morning"}) is False


def test_is_hollow_shared_reexport_matches() -> None:
    payload = {"facts": {"k": "v"}, "notes": []}
    assert is_hollow_content(payload) is is_hollow_via_repo(payload)


def test_apply_set_fact_sets_and_overwrites() -> None:
    c = empty_content()
    c2 = apply_set_fact(c, "city", "BA")
    assert c2["facts"]["city"] == "BA"
    c3 = apply_set_fact(c2, "city", "MDZ")
    assert c3["facts"]["city"] == "MDZ"
    # original shell not mutated
    assert c["facts"] == {}


def test_apply_set_fact_rejects_empty_key_or_value() -> None:
    c = empty_content()
    with pytest.raises(ValueError):
        apply_set_fact(c, "", "v")
    with pytest.raises(ValueError):
        apply_set_fact(c, "  ", "v")
    with pytest.raises(ValueError):
        apply_set_fact(c, "k", "")
    with pytest.raises(ValueError):
        apply_set_fact(c, "k", "  ")


def test_apply_delete_fact_returns_deleted_flag() -> None:
    c = apply_set_fact(empty_content(), "city", "BA")
    c2, deleted = apply_delete_fact(c, "city")
    assert deleted is True
    assert "city" not in c2["facts"]
    c3, deleted2 = apply_delete_fact(c2, "city")
    assert deleted2 is False
    assert c3["facts"] == {}


def test_apply_add_note_appends() -> None:
    c = empty_content()
    c2 = apply_add_note(c, "met at event", "2026-07-27")
    assert c2["notes"] == [{"date": "2026-07-27", "text": "met at event"}]
    c3 = apply_add_note(c2, "follow-up", "2026-07-28")
    assert len(c3["notes"]) == 2
    assert c3["notes"][1] == {"date": "2026-07-28", "text": "follow-up"}


def test_apply_add_note_rejects_empty_text() -> None:
    with pytest.raises(ValueError):
        apply_add_note(empty_content(), "", "2026-07-27")
    with pytest.raises(ValueError):
        apply_add_note(empty_content(), "  ", "2026-07-27")


def test_apply_delete_note_zero_based() -> None:
    c = apply_add_note(empty_content(), "a", "2026-01-01")
    c = apply_add_note(c, "b", "2026-01-02")
    c2, ok = apply_delete_note(c, 0)
    assert ok is True
    assert c2["notes"] == [{"date": "2026-01-02", "text": "b"}]
    c3, ok2 = apply_delete_note(c2, 5)
    assert ok2 is False
    assert c3["notes"] == c2["notes"]
    c4, ok3 = apply_delete_note(c2, -1)
    assert ok3 is False


def test_apply_set_fact_rejects_oversize() -> None:
    c = empty_content()
    with pytest.raises(ValueError, match="max length"):
        apply_set_fact(c, "k" * (MAX_FACT_KEY_LEN + 1), "v")
    with pytest.raises(ValueError, match="max length"):
        apply_set_fact(c, "k", "v" * (MAX_FACT_VALUE_LEN + 1))


def test_apply_add_note_rejects_oversize() -> None:
    with pytest.raises(ValueError, match="max length"):
        apply_add_note(empty_content(), "x" * (MAX_NOTE_TEXT_LEN + 1), "2026-07-27")
