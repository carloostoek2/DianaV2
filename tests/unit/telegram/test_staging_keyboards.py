"""Staging promote/discard keyboard encode/parse contracts (sp:/sd:)."""

from __future__ import annotations

from uuid import uuid4

from diana.telegram.keyboards import (
    encode_staging_discard,
    encode_staging_promote,
    parse_callback,
    parse_staging_callback,
    staging_candidate_keyboard,
)


class TestStagingKeyboards:
    def test_promote_roundtrip(self) -> None:
        cid = uuid4()
        data = encode_staging_promote(cid)
        assert parse_staging_callback(data) == ("promote", cid)

    def test_discard_roundtrip(self) -> None:
        cid = uuid4()
        data = encode_staging_discard(cid)
        assert parse_staging_callback(data) == ("discard", cid)

    def test_encoded_under_64_bytes(self) -> None:
        cid = uuid4()
        for data in (encode_staging_promote(cid), encode_staging_discard(cid)):
            assert len(data.encode("utf-8")) <= 64

    def test_parse_rejects_foreign_prefixes(self) -> None:
        assert parse_staging_callback(f"a:{uuid4()}") is None
        assert parse_staging_callback("mx:e") is None
        assert parse_staging_callback("garbage") is None
        assert parse_staging_callback("") is None
        assert parse_staging_callback(f"sp:not-a-uuid") is None

    def test_parse_callback_ignores_staging_prefixes(self) -> None:
        """Catch-all parse_callback must not claim sp:/sd:."""
        cid = uuid4()
        assert parse_callback(encode_staging_promote(cid)) is None
        assert parse_callback(encode_staging_discard(cid)) is None

    def test_keyboard_buttons_english(self) -> None:
        cid = uuid4()
        kb = staging_candidate_keyboard(cid)
        row = kb.inline_keyboard[0]
        assert len(row) == 2
        assert row[0].callback_data == encode_staging_promote(cid)
        assert row[1].callback_data == encode_staging_discard(cid)
        assert "Promote" in (row[0].text or "")
        assert "Discard" in (row[1].text or "")
