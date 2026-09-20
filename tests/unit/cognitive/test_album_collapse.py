"""collapse_album_runs — an album is N rows in the DB, one line for the model."""

from __future__ import annotations

from diana.cognitive.album_collapse import collapse_album_runs


def _row(role: str, text: str, *, ts: str = "2026-09-20T00:00:00+00:00") -> dict:
    return {"role": role, "text": text, "timestamp": ts}


def test_album_run_collapses_to_first_row_with_count() -> None:
    rows = [
        _row("owner", "[imagen parte de álbum]"),
        _row("owner", "[imagen parte de álbum]"),
        _row("owner", "[imagen parte de álbum]"),
    ]
    out = collapse_album_runs(rows)
    assert len(out) == 1
    assert out[0]["text"] == "[imagen parte de álbum ×3]"


def test_lone_album_row_keeps_no_count_noise() -> None:
    """A single member (or a lone image) must not grow a '×1'."""
    out = collapse_album_runs([_row("owner", "[imagen parte de álbum]")])
    assert out[0]["text"] == "[imagen parte de álbum]"


def test_non_album_rows_pass_through_untouched() -> None:
    rows = [
        _row("vip", "hola"),
        _row("owner", "[imagen]"),
        _row("vip", "[documento] cv.pdf"),
    ]
    assert collapse_album_runs(rows) == rows


def test_runs_of_different_roles_do_not_merge() -> None:
    """An album from the owner next to one from the VIP is two albums."""
    rows = [
        _row("owner", "[imagen parte de álbum]"),
        _row("owner", "[imagen parte de álbum]"),
        _row("vip", "[imagen parte de álbum]"),
        _row("vip", "[imagen parte de álbum]"),
    ]
    out = collapse_album_runs(rows)
    assert [r["text"] for r in out] == [
        "[imagen parte de álbum ×2]",
        "[imagen parte de álbum ×2]",
    ]


def test_runs_split_by_another_row_stay_separate() -> None:
    rows = [
        _row("owner", "[imagen parte de álbum]"),
        _row("owner", "[imagen parte de álbum]"),
        _row("owner", "ya te atiendo"),
        _row("owner", "[imagen parte de álbum]"),
    ]
    out = collapse_album_runs(rows)
    assert [r["text"] for r in out] == [
        "[imagen parte de álbum ×2]",
        "ya te atiendo",
        "[imagen parte de álbum]",
    ]


def test_caption_on_first_member_survives_the_collapse() -> None:
    """Telegram attaches the album caption to one member; keeping row 1 keeps it."""
    rows = [
        _row("owner", "[imagen parte de álbum] las de la boda"),
        _row("owner", "[imagen parte de álbum]"),
        _row("owner", "[imagen parte de álbum]"),
    ]
    out = collapse_album_runs(rows)
    assert out[0]["text"] == "[imagen parte de álbum ×3] las de la boda"


def test_count_lands_before_the_description_not_after() -> None:
    rows = [
        _row("vip", "[imagen parte de álbum: una playa]"),
        _row("vip", "[imagen parte de álbum: una playa]"),
    ]
    out = collapse_album_runs(rows)
    assert out[0]["text"] == "[imagen parte de álbum ×2: una playa]"


def test_input_rows_are_not_mutated() -> None:
    rows = [
        _row("owner", "[imagen parte de álbum]"),
        _row("owner", "[imagen parte de álbum]"),
    ]
    snapshot = [dict(r) for r in rows]
    collapse_album_runs(rows)
    assert rows == snapshot


def test_empty_and_non_dict_rows_are_safe() -> None:
    assert collapse_album_runs([]) == []
    rows: list[dict] = [{"role": "owner"}, {"text": None}]  # type: ignore[list-item]
    assert collapse_album_runs(rows) == rows
