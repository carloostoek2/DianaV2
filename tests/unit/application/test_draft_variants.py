"""Draft versioning: ensure_versions, navigate, regenerate (unit)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.application.draft_variants import (
    DraftVariantService,
    build_owner_draft_text,
    ensure_versions,
    read_versions,
    resolve_vip_display_name,
    selected_text,
)
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryPendingApprovalStore,
    InMemoryTurnStore,
    InMemoryVipStore,
)
from diana.application.ports import ApprovalRecord, TurnRecord
from diana.cognitive.models import Decision, EvaluationProfile, IncomingTurn


def _eval() -> EvaluationProfile:
    return EvaluationProfile(
        naturalness=0.9,
        precision=0.9,
        doctrine=0.9,
        consistency=0.9,
        safety=0.95,
        coverage=0.9,
        empathy=0.9,
    )


def test_ensure_and_read_versions() -> None:
    e = ensure_versions(
        {"naturalness": 0.5},
        draft_text="hola",
        reason="ok",
        vip_text="msg vip",
    )
    v = read_versions(e)
    assert v["selected"] == 0
    assert v["items"][0]["text"] == "hola"
    assert v["vip_text"] == "msg vip"
    assert selected_text(e, "fallback") == "hola"


class FakeDirector:
    def __init__(self, drafts: list[str]) -> None:
        self._drafts = list(drafts)
        self.calls = 0

    async def handle_turn(self, turn: IncomingTurn) -> Decision:
        self.calls += 1
        text = self._drafts.pop(0) if self._drafts else "fallback"
        return Decision(
            action="approve",
            reason="regen_ok",
            evaluation=_eval(),
            draft_text=text,
        )


@pytest.mark.asyncio
async def test_navigate_prev_next() -> None:
    OWNER = 99
    approvals = InMemoryPendingApprovalStore()
    turns = InMemoryTurnStore()
    turn_id = uuid4()
    await turns.create(
        TurnRecord(
            id=turn_id,
            chat_id=1,
            status="pending_approval",
            vip_id=None,
            trigger_message_id=10,
        )
    )
    eval_dict = ensure_versions(
        {},
        draft_text="v1",
        reason="r1",
        vip_text="user said hi",
    )
    eval_dict["_draft_versions"]["items"].append({"text": "v2", "reason": "r2"})
    eval_dict["_draft_versions"]["selected"] = 0
    await approvals.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=turn_id,
            chat_id=1,
            business_connection_id="bc",
            draft_text="v1",
            evaluation=eval_dict,
            owner_message_id=500,
            trigger_message_id=10,
        )
    )
    svc = DraftVariantService(
        approvals=approvals,
        turns=turns,
        director=FakeDirector(["x"]),
        notifier=FakeOwnerNotifier(),
        owner_telegram_id=OWNER,
    )
    r = await svc.navigate(turn_id, actor_id=OWNER, delta=1)
    assert r.ok and r.token == "nav_ok"
    assert r.approval is not None
    assert r.approval.draft_text == "v2"
    r2 = await svc.navigate(turn_id, actor_id=OWNER, delta=1)
    assert not r2.ok and r2.token == "blocked_last"
    r3 = await svc.navigate(turn_id, actor_id=OWNER, delta=-1)
    assert r3.ok and r3.approval is not None
    assert r3.approval.draft_text == "v1"


@pytest.mark.asyncio
async def test_regenerate_appends_variant() -> None:
    OWNER = 99
    approvals = InMemoryPendingApprovalStore()
    turns = InMemoryTurnStore()
    turn_id = uuid4()
    await turns.create(
        TurnRecord(
            id=turn_id,
            chat_id=1,
            status="pending_approval",
            trigger_message_id=10,
        )
    )
    eval_dict = ensure_versions(
        {"naturalness": 0.8},
        draft_text="primera",
        reason="ok",
        vip_text="hola",
    )
    await approvals.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=turn_id,
            chat_id=1,
            business_connection_id="bc",
            draft_text="primera",
            evaluation=eval_dict,
            owner_message_id=501,
            trigger_message_id=10,
        )
    )
    director = FakeDirector(["segunda versión"])
    notifier = FakeOwnerNotifier()
    svc = DraftVariantService(
        approvals=approvals,
        turns=turns,
        director=director,
        notifier=notifier,
        owner_telegram_id=OWNER,
    )
    r = await svc.regenerate(turn_id, actor_id=OWNER)
    assert r.ok and r.token == "regen_ok"
    assert r.approval is not None
    assert r.approval.draft_text == "segunda versión"
    v = read_versions(r.approval.evaluation)
    assert len(v["items"]) == 2
    assert v["selected"] == 1
    assert director.calls == 1


def test_build_owner_draft_text_falls_back_to_chat_id() -> None:
    eval_dict = ensure_versions(
        {}, draft_text="hola", reason="ok", vip_text="msg del vip"
    )
    rec = ApprovalRecord(
        id=uuid4(),
        turn_id=uuid4(),
        chat_id=123,
        business_connection_id="bc",
        draft_text="hola",
        evaluation=eval_dict,
    )
    body = build_owner_draft_text(rec)
    assert "123" in body
    assert "Marian" not in body


def test_build_owner_draft_text_uses_resolved_name() -> None:
    eval_dict = ensure_versions(
        {}, draft_text="hola", reason="ok", vip_text="msg del vip"
    )
    rec = ApprovalRecord(
        id=uuid4(),
        turn_id=uuid4(),
        chat_id=123,
        business_connection_id="bc",
        draft_text="hola",
        evaluation=eval_dict,
    )
    body = build_owner_draft_text(rec, vip_name="Marian")
    assert "Marian" in body
    assert "123" not in body


@pytest.mark.asyncio
async def test_resolve_vip_display_name() -> None:
    assert await resolve_vip_display_name(None, None, 1) is None
    vips = InMemoryVipStore()
    assert await resolve_vip_display_name(vips, None, 999) is None
    await vips.add(1, display_name="Marian")
    assert await resolve_vip_display_name(vips, None, 1) == "Marian"
    vip_id = (await vips.get_by_telegram_user_id(1)).id
    assert await resolve_vip_display_name(vips, vip_id, 1) == "Marian"


@pytest.mark.asyncio
async def test_refresh_owner_message_uses_vip_display_name() -> None:
    OWNER = 99
    approvals = InMemoryPendingApprovalStore()
    turns = InMemoryTurnStore()
    vips = InMemoryVipStore()
    turn_id = uuid4()
    await turns.create(
        TurnRecord(
            id=turn_id,
            chat_id=1,
            status="pending_approval",
            trigger_message_id=10,
        )
    )
    await vips.add(1, display_name="Marian")
    eval_dict = ensure_versions(
        {}, draft_text="v1", reason="r1", vip_text="user said hi"
    )
    eval_dict["_draft_versions"]["items"].append({"text": "v2", "reason": "r2"})
    eval_dict["_draft_versions"]["selected"] = 0
    await approvals.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=turn_id,
            chat_id=1,
            business_connection_id="bc",
            draft_text="v1",
            evaluation=eval_dict,
            owner_message_id=500,
            trigger_message_id=10,
        )
    )
    notifier = FakeOwnerNotifier()
    svc = DraftVariantService(
        approvals=approvals,
        turns=turns,
        director=FakeDirector(["x"]),
        notifier=notifier,
        owner_telegram_id=OWNER,
        vips=vips,
    )
    r = await svc.navigate(turn_id, actor_id=OWNER, delta=1)
    assert r.ok and r.token == "nav_ok"
    assert any("Marian" in text for text, _ in notifier.infos)
    assert not any("Propuesta de respuesta para 1" in text for text, _ in notifier.infos)
