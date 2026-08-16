"""Destacar / Reprender keyboards, parsers, and CorrectSession payload."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from diana.telegram.handlers.callbacks import CorrectSessionStore
from diana.telegram.keyboards import (
    draft_keyboard,
    encode_gold_confirm,
    encode_reprimand_confirm,
    gold_scope_keyboard,
    parse_callback,
    parse_gold_confirm,
    parse_reprimand_confirm,
    reprimand_combo_keyboard,
)

_VOSEO = re.compile(
    r"querés|tenés|hacés|decime|sos |vos |Revisá|Elegí",
    re.IGNORECASE,
)
OWNER = 999001


def _all_callback_data(kb) -> list[str]:
    return [b.callback_data or "" for row in kb.inline_keyboard for b in row]


def _all_labels(kb) -> list[str]:
    return [b.text or "" for row in kb.inline_keyboard for b in row]


class TestDraftQualityRow:
    def test_default_has_ace_without_quality_prefixes(self) -> None:
        tid = uuid4()
        kb = draft_keyboard(tid)
        cbs = _all_callback_data(kb)
        assert any(cb.startswith(f"a:{tid}") for cb in cbs)
        assert any(cb.startswith(f"c:{tid}") for cb in cbs)
        assert any(cb.startswith(f"e:{tid}") for cb in cbs)
        assert not any(cb.startswith("gd:") or cb.startswith("rp:") for cb in cbs)

    def test_flag_on_adds_destacar_reprender_row(self) -> None:
        tid = uuid4()
        kb = draft_keyboard(tid, show_quality_feedback=True)
        labels = _all_labels(kb)
        assert "Destacar" in labels
        assert "Reprender" in labels
        cbs = _all_callback_data(kb)
        assert f"gd:{tid}" in cbs
        assert f"rp:{tid}" in cbs

    def test_all_draft_callbacks_fit_64_bytes(self) -> None:
        tid = uuid4()
        kb = draft_keyboard(tid, chat_id=42, show_quality_feedback=True)
        for cb in _all_callback_data(kb):
            assert len(cb.encode("utf-8")) <= 64, cb


class TestGoldAndReprimandKeyboards:
    def test_gold_scope_keyboard_encodes_general_vip_back(self) -> None:
        tid = uuid4()
        kb = gold_scope_keyboard(tid)
        cbs = _all_callback_data(kb)
        labels = " ".join(_all_labels(kb))
        assert f"gdc:{tid}:g" in cbs
        assert f"gdc:{tid}:v" in cbs
        assert f"gdc:{tid}:x" in cbs
        assert "General" in labels
        assert "Este VIP" in labels
        assert "Volver" in labels
        for cb in cbs:
            assert len(cb.encode("utf-8")) <= 64, cb

    def test_reprimand_combo_keyboard_two_by_two(self) -> None:
        tid = uuid4()
        kb = reprimand_combo_keyboard(tid)
        assert len(kb.inline_keyboard) == 2
        assert [b.callback_data for b in kb.inline_keyboard[0]] == [
            f"rpc:{tid}:pol:g",
            f"rpc:{tid}:pol:v",
        ]
        assert [b.callback_data for b in kb.inline_keyboard[1]] == [
            f"rpc:{tid}:ex:g",
            f"rpc:{tid}:ex:v",
        ]
        assert kb.inline_keyboard[0][0].text == "Regla dura · General"
        assert kb.inline_keyboard[0][1].text == "Regla dura · Este VIP"
        assert kb.inline_keyboard[1][0].text == "No repetir · General"
        assert kb.inline_keyboard[1][1].text == "No repetir · Este VIP"
        for cb in _all_callback_data(kb):
            assert len(cb.encode("utf-8")) <= 64, cb

    def test_labels_have_no_voseo(self) -> None:
        tid = uuid4()
        blobs = [
            " ".join(_all_labels(draft_keyboard(tid, show_quality_feedback=True))),
            " ".join(_all_labels(gold_scope_keyboard(tid))),
            " ".join(_all_labels(reprimand_combo_keyboard(tid))),
        ]
        for blob in blobs:
            assert _VOSEO.search(blob) is None, blob


class TestQualityParsers:
    def test_parse_callback_ignores_confirm_prefixes(self) -> None:
        tid = uuid4()
        assert parse_callback(f"gdc:{tid}:g") is None
        assert parse_callback(f"rpc:{tid}:pol:g") is None

    def test_parse_callback_maps_gd_and_rp(self) -> None:
        tid = uuid4()
        assert parse_callback(f"gd:{tid}") == ("gold", tid)
        assert parse_callback(f"rp:{tid}") == ("reprimand", tid)

    def test_gold_confirm_roundtrip(self) -> None:
        tid = uuid4()
        assert parse_gold_confirm(encode_gold_confirm(tid, "g")) == (tid, "global")
        assert parse_gold_confirm(encode_gold_confirm(tid, "v")) == (tid, "vip")
        assert parse_gold_confirm(f"gdc:{tid}:x") == "cancel"

    def test_reprimand_confirm_roundtrip(self) -> None:
        tid = uuid4()
        assert parse_reprimand_confirm(encode_reprimand_confirm(tid, "pol", "g")) == (
            tid,
            "policy",
            "global",
        )
        assert parse_reprimand_confirm(encode_reprimand_confirm(tid, "ex", "v")) == (
            tid,
            "counter_example",
            "vip",
        )

    def test_parsers_reject_garbage(self) -> None:
        assert parse_gold_confirm("garbage") is None
        assert parse_gold_confirm("gdc:not-a-uuid:g") is None
        assert parse_gold_confirm("gdc:") is None
        assert parse_reprimand_confirm("rpc:nope") is None
        assert parse_reprimand_confirm(f"rpc:{uuid4()}:zz:g") is None
        assert parse_reprimand_confirm("") is None


class TestCorrectSessionPayload:
    def test_start_default_resolve_get_compat(self) -> None:
        store = CorrectSessionStore()
        tid = uuid4()
        store.start(OWNER, tid)
        assert store.get(OWNER) == tid
        assert store.resolve(OWNER) == ("live", tid)

    def test_start_reprimand_sets_mode_and_chat(self) -> None:
        store = CorrectSessionStore()
        tid = uuid4()
        store.start(OWNER, tid, mode="reprimand", chat_id=7)
        sess = store.get_session(OWNER)
        assert sess is not None
        assert sess.mode == "reprimand"
        assert sess.chat_id == 7
        assert sess.phase == "await_text"

    def test_capture_reprimand_refreshes_ttl(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        clock_box = {"t": now}

        def clock() -> datetime:
            return clock_box["t"]

        store = CorrectSessionStore(ttl=timedelta(minutes=15), clock=clock)
        tid = uuid4()
        cid = uuid4()
        store.start(OWNER, tid, mode="reprimand", chat_id=7)
        clock_box["t"] = now + timedelta(minutes=10)
        store.capture_reprimand(OWNER, candidate_id=cid, corrected_text="x")
        sess = store.get_session(OWNER)
        assert sess is not None
        assert sess.phase == "reprimand_combo"
        assert sess.candidate_id == cid
        clock_box["t"] = now + timedelta(minutes=20)
        assert store.resolve(OWNER) == ("live", tid)

    def test_expire_combo_distinct_from_correct_expire(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        clock_box = {"t": now}

        def clock() -> datetime:
            return clock_box["t"]

        store = CorrectSessionStore(ttl=timedelta(minutes=15), clock=clock)
        tid = uuid4()
        store.start(OWNER, tid, mode="reprimand", chat_id=7)
        store.capture_reprimand(OWNER, candidate_id=uuid4(), corrected_text="x")
        clock_box["t"] = now + timedelta(minutes=16)
        assert store.resolve(OWNER) == ("expired_combo", tid)

    def test_cancel_combo_for_chat_spares_correct_sessions(self) -> None:
        store = CorrectSessionStore()
        combo_tid = uuid4()
        correct_tid = uuid4()
        other_owner = OWNER + 1
        store.start(OWNER, combo_tid, mode="reprimand", chat_id=7)
        store.capture_reprimand(OWNER, candidate_id=uuid4(), corrected_text="x")
        store.start(other_owner, correct_tid)
        store.cancel_combo_for_chat(7)
        assert store.get(OWNER) is None
        assert store.get(other_owner) == correct_tid
