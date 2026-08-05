"""Memory approval keyboard encode/parse contracts (mp:/md:)."""

from __future__ import annotations

from uuid import uuid4

from diana.telegram.keyboards import (
    encode_memory_approve,
    encode_memory_discard,
    memory_pending_keyboard,
    parse_callback,
    parse_memory_approval_callback,
)


class TestMemoryApprovalKeyboards:
    def test_approve_roundtrip(self) -> None:
        fid = uuid4()
        data = encode_memory_approve(fid)
        assert parse_memory_approval_callback(data) == ("approve", fid)

    def test_discard_roundtrip(self) -> None:
        fid = uuid4()
        data = encode_memory_discard(fid)
        assert parse_memory_approval_callback(data) == ("discard", fid)

    def test_encoded_under_64_bytes(self) -> None:
        fid = uuid4()
        for data in (encode_memory_approve(fid), encode_memory_discard(fid)):
            assert len(data.encode("utf-8")) <= 64

    def test_parse_rejects_foreign_prefixes(self) -> None:
        assert parse_memory_approval_callback(f"a:{uuid4()}") is None
        assert parse_memory_approval_callback("mx:e") is None
        assert parse_memory_approval_callback("garbage") is None
        assert parse_memory_approval_callback("") is None
        assert parse_memory_approval_callback("mp:not-a-uuid") is None
        assert parse_memory_approval_callback(f"m:{uuid4()}") is None

    def test_parse_callback_ignores_memory_prefixes(self) -> None:
        """Catch-all parse_callback must not claim mp:/md: (A1 collision)."""
        fid = uuid4()
        assert parse_callback(encode_memory_approve(fid)) is None
        assert parse_callback(encode_memory_discard(fid)) is None

    def test_keyboard_buttons_spanish(self) -> None:
        fid = uuid4()
        kb = memory_pending_keyboard(fid)
        row = kb.inline_keyboard[0]
        assert len(row) == 2
        assert row[0].callback_data == encode_memory_approve(fid)
        assert row[1].callback_data == encode_memory_discard(fid)
        assert "Aprobar" in (row[0].text or "")
        assert "Descartar" in (row[1].text or "")
