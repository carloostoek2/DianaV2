"""Draft versioning: ensure_versions, navigate, regenerate (unit)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from diana.application.draft_variants import (
    AUTONOMY_KEY,
    DOCTRINE_NA_LABEL,
    DOCTRINE_RELEVANT_KEY,
    DraftVariantService,
    build_owner_draft_text,
    ensure_versions,
    localize_reason,
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
async def test_edit_draft_forwards_quality_feedback_flag() -> None:
    OWNER = 99
    approvals = InMemoryPendingApprovalStore()
    turns = InMemoryTurnStore()
    turn_id = uuid4()
    vip_id = uuid4()
    await turns.create(
        TurnRecord(
            id=turn_id,
            chat_id=1,
            status="pending_approval",
            vip_id=vip_id,
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
            vip_id=vip_id,
        )
    )
    notifier = FakeOwnerNotifier()
    svc = DraftVariantService(
        approvals=approvals,
        turns=turns,
        director=FakeDirector(["x"]),
        notifier=notifier,
        owner_telegram_id=OWNER,
        feature_quality_feedback_enabled=True,
    )
    r = await svc.navigate(turn_id, actor_id=OWNER, delta=1)
    assert r.ok
    assert notifier.draft_edits
    assert notifier.draft_edits[-1]["show_quality_feedback"] is True


async def _pending_approval_fixture(
    *,
    draft: str = "primera",
    status: str = "pending_approval",
    owner_message_id: int = 501,
) -> tuple:
    OWNER = 99
    approvals = InMemoryPendingApprovalStore()
    turns = InMemoryTurnStore()
    turn_id = uuid4()
    await turns.create(
        TurnRecord(
            id=turn_id,
            chat_id=1,
            status=status,
            trigger_message_id=10,
        )
    )
    eval_dict = ensure_versions(
        {"naturalness": 0.8},
        draft_text=draft,
        reason="ok",
        vip_text="hola",
    )
    await approvals.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=turn_id,
            chat_id=1,
            business_connection_id="bc",
            draft_text=draft,
            evaluation=eval_dict,
            owner_message_id=owner_message_id,
            trigger_message_id=10,
        )
    )
    return OWNER, approvals, turns, turn_id


@pytest.mark.asyncio
async def test_regenerate_appends_variant() -> None:
    OWNER, approvals, turns, turn_id = await _pending_approval_fixture()
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


@pytest.mark.asyncio
async def test_regenerate_rejects_terminal_turn_without_director() -> None:
    """Do not re-run cognition or revive UI when the turn is already dead."""
    OWNER, approvals, turns, turn_id = await _pending_approval_fixture(
        status="superseded"
    )
    director = FakeDirector(["no debe usarse"])
    notifier = FakeOwnerNotifier()
    svc = DraftVariantService(
        approvals=approvals,
        turns=turns,
        director=director,
        notifier=notifier,
        owner_telegram_id=OWNER,
    )
    r = await svc.regenerate(turn_id, actor_id=OWNER)
    assert not r.ok and r.token == "stale"
    assert director.calls == 0
    live = await approvals.get_by_turn(turn_id)
    assert live is not None
    assert live.draft_text == "primera"
    assert not any(str(t).startswith("edit_draft:") for t, _ in notifier.infos)


@pytest.mark.asyncio
async def test_regenerate_cancelled_mid_llm_does_not_revive_ui() -> None:
    """If approval dies during regen, do not rewrite draft or restore buttons."""
    OWNER, approvals, turns, turn_id = await _pending_approval_fixture()

    class CancelMidDirector:
        def __init__(self) -> None:
            self.calls = 0

        async def handle_turn(self, turn: IncomingTurn) -> Decision:
            self.calls += 1
            await approvals.mark_status(turn.turn_id, "cancelled")
            await turns.transition(turn.turn_id, "superseded")
            return Decision(
                action="approve",
                reason="late",
                evaluation=_eval(),
                draft_text="versión zombie",
            )

    director = CancelMidDirector()
    notifier = FakeOwnerNotifier()
    svc = DraftVariantService(
        approvals=approvals,
        turns=turns,
        director=director,
        notifier=notifier,
        owner_telegram_id=OWNER,
    )
    r = await svc.regenerate(turn_id, actor_id=OWNER)
    assert not r.ok and r.token == "stale"
    assert director.calls == 1
    live = await approvals.get_by_turn(turn_id)
    assert live is not None
    assert live.status == "cancelled"
    assert live.draft_text == "primera"  # not overwritten
    assert not any(str(t).startswith("edit_draft:") for t, _ in notifier.infos)


@pytest.mark.asyncio
async def test_regenerate_fires_on_start_during_success() -> None:
    """Live 'Regenerando' signal fires once, after the soft-lock, mid-run."""
    OWNER, approvals, turns, turn_id = await _pending_approval_fixture()
    director = FakeDirector(["segunda"])
    notifier = FakeOwnerNotifier()
    svc = DraftVariantService(
        approvals=approvals,
        turns=turns,
        director=director,
        notifier=notifier,
        owner_telegram_id=OWNER,
    )
    fired: list[str] = []

    async def on_start() -> None:
        fired.append("start")

    r = await svc.regenerate(turn_id, actor_id=OWNER, on_start=on_start)
    assert r.ok and r.token == "regen_ok"
    assert fired == ["start"]
    assert director.calls == 1
    # Success path refreshes the owner message with the new version (legend
    # replaced by the notifier, not left behind by the service).
    assert any(str(t).startswith("edit_draft:") for t, _ in notifier.infos)


@pytest.mark.asyncio
async def test_regenerate_skips_on_start_when_early_return() -> None:
    """Blocked/stale early returns never fire the 'Regenerando' signal."""
    OWNER, approvals, turns, turn_id = await _pending_approval_fixture(
        status="superseded"
    )
    director = FakeDirector(["no debe usarse"])
    svc = DraftVariantService(
        approvals=approvals,
        turns=turns,
        director=director,
        notifier=FakeOwnerNotifier(),
        owner_telegram_id=OWNER,
    )
    fired: list[str] = []

    async def on_start() -> None:
        fired.append("start")

    r = await svc.regenerate(turn_id, actor_id=OWNER, on_start=on_start)
    assert not r.ok and r.token == "stale"
    assert fired == []
    assert director.calls == 0


@pytest.mark.asyncio
async def test_regenerate_on_start_fault_does_not_abort() -> None:
    """A fault inside the 'Regenerando' callback must never abort the run."""
    OWNER, approvals, turns, turn_id = await _pending_approval_fixture()
    director = FakeDirector(["segunda"])
    svc = DraftVariantService(
        approvals=approvals,
        turns=turns,
        director=director,
        notifier=FakeOwnerNotifier(),
        owner_telegram_id=OWNER,
    )

    async def on_start() -> None:
        raise RuntimeError("edit failed")

    r = await svc.regenerate(turn_id, actor_id=OWNER, on_start=on_start)
    assert r.ok and r.token == "regen_ok"
    assert director.calls == 1


@pytest.mark.asyncio
async def test_update_draft_cas_skips_non_waiting() -> None:
    OWNER, approvals, turns, turn_id = await _pending_approval_fixture()
    await approvals.mark_status(turn_id, "cancelled")
    updated = await approvals.update_draft(
        turn_id,
        draft_text="no debe entrar",
        evaluation={"x": 1},
        cognitive_summary="nope",
    )
    assert updated is None
    live = await approvals.get_by_turn(turn_id)
    assert live is not None
    assert live.draft_text == "primera"


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


def test_build_owner_draft_text_appends_doc_no_aplica() -> None:
    eval_dict = ensure_versions(
        {
            "naturalness": 0.9,
            "precision": 0.8,
            "safety": 0.95,
            "doctrine": 0.50,
            DOCTRINE_RELEVANT_KEY: False,
        },
        draft_text="hola",
        reason="ok",
        vip_text="msg del vip",
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
    assert "<b>Doctrina:</b> no aplica" in body
    assert "<b>Doctrina:</b> 0.50" not in body
    assert "<b>Motivo:</b>" in body
    assert "<b>Evaluación</b>" in body


def test_build_owner_draft_text_appends_doc_number_when_relevant() -> None:
    eval_dict = ensure_versions(
        {
            "naturalness": 0.9,
            "precision": 0.8,
            "safety": 0.95,
            "doctrine": 0.90,
            DOCTRINE_RELEVANT_KEY: True,
        },
        draft_text="hola",
        reason="ok",
        vip_text="msg del vip",
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
    assert "<b>Doctrina:</b> 0.90" in body
    assert DOCTRINE_NA_LABEL not in body


def test_build_owner_draft_text_shows_doctrine_number_fail_open_when_flag_absent() -> None:
    # Legacy record without the relevance flag: the number is shown (fail-open,
    # matching _resolve_doctrine_relevant), never inferred as "no aplica".
    eval_dict = ensure_versions(
        {"naturalness": 0.9, "precision": 0.8, "safety": 0.95, "doctrine": 0.50},
        draft_text="hola",
        reason="ok",
        vip_text="msg del vip",
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
    assert "<b>Doctrina:</b> 0.50" in body
    assert "<b>Doctrina:</b> no aplica" not in body


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


# --- improved owner draft view: Motivo localizado, Evaluación, Autonomía -------

def _dims_eval_dict(
    *,
    reason: str = "ok_for_human_review",
    draft: str = "hola",
    vip_text: str = "msg del vip",
    doctrine_relevant: bool = True,
    **dims: float,
) -> dict:
    base: dict[str, Any] = {
        "naturalness": 0.9,
        "precision": 0.9,
        "doctrine": 0.9,
        "consistency": 0.9,
        "safety": 0.95,
        "coverage": 0.9,
        "empathy": 0.9,
    }
    base.update(dims)
    base[DOCTRINE_RELEVANT_KEY] = doctrine_relevant
    return ensure_versions(base, draft_text=draft, reason=reason, vip_text=vip_text)


def _owner_rec(eval_dict: dict, *, chat_id: int = 123) -> ApprovalRecord:
    return ApprovalRecord(
        id=uuid4(),
        turn_id=uuid4(),
        chat_id=chat_id,
        business_connection_id="bc",
        draft_text="hola",
        cognitive_summary="ok_for_human_review",
        evaluation=eval_dict,
    )


def _autonomy_snap(*, has_history: bool = False, **kw: Any) -> dict:
    snap: dict[str, Any] = {
        "v": 1,
        "mins": {"safety_min": 0.9, "doctrine_min": 0.8, "naturalness_min": 0.7},
        "has_history": has_history,
        "confidence_min": 0.9,
        "match_rate_min": 0.95,
        "window_days": 14,
    }
    snap.update(kw)
    return snap


def test_draft_header_shows_italic_version_counter() -> None:
    rec = _owner_rec(_dims_eval_dict())
    body = build_owner_draft_text(rec)
    assert "<b>Propuesta de respuesta para 123</b> — <i>borrador 1/1</i>" in body
    assert "<b>[usuario]</b>\nmsg del vip" in body
    assert "<b>[propuesta]</b>\nhola" in body


def test_evaluation_section_lists_all_seven_dims_in_spanish() -> None:
    rec = _owner_rec(_dims_eval_dict())
    body = build_owner_draft_text(rec)
    assert "<b>Evaluación</b>" in body
    for label, value in (
        ("Naturalidad", "0.90"),
        ("Precisión", "0.90"),
        ("Doctrina", "0.90"),
        ("Consistencia", "0.90"),
        ("Seguridad", "0.95"),
        ("Cobertura", "0.90"),
        ("Empatía", "0.90"),
    ):
        assert f"• <b>{label}:</b> {value}" in body


def test_evaluation_doctrine_no_aplica_when_not_relevant() -> None:
    eval_dict = _dims_eval_dict(doctrine_relevant=False, doctrine=0.5)
    body = build_owner_draft_text(_owner_rec(eval_dict))
    assert "<b>Doctrina:</b> no aplica" in body
    assert "<b>Doctrina:</b> 0.50" not in body


def test_motivo_localized_in_body() -> None:
    eval_dict = _dims_eval_dict(reason="autonomous_below_threshold")
    rec = _owner_rec(eval_dict)
    rec = ApprovalRecord(
        id=rec.id,
        turn_id=rec.turn_id,
        chat_id=rec.chat_id,
        business_connection_id="bc",
        draft_text="hola",
        cognitive_summary="autonomous_below_threshold",
        evaluation=eval_dict,
    )
    body = build_owner_draft_text(rec)
    assert "<b>Motivo:</b>" in body
    assert "no alcanzó los mínimos de autonomía" in body


def test_localize_reason_known_unknown_and_sandbox_prefix() -> None:
    assert "revisión" in localize_reason("ok_for_human_review")
    assert localize_reason("token_desconocido") == "token_desconocido"
    out = localize_reason("SANDBOX — profile: p | ok_for_human_review")
    assert out.startswith("SANDBOX — profile: p |")
    assert "revisión" in out


def test_autonomy_section_absent_without_snapshot() -> None:
    body = build_owner_draft_text(_owner_rec(_dims_eval_dict()))
    assert "<b>Autonomía</b>" not in body


def test_autonomy_sin_historial_shows_discreet_line() -> None:
    eval_dict = _dims_eval_dict()
    eval_dict[AUTONOMY_KEY] = _autonomy_snap(has_history=False)
    body = build_owner_draft_text(_owner_rec(eval_dict))
    assert "<b>Autonomía</b>" in body
    assert "aún sin historial para evaluar autonomía con este contacto" in body


def test_autonomy_draft_missing_dim_and_vip_en_camino() -> None:
    eval_dict = _dims_eval_dict(naturalness=0.6)
    eval_dict[AUTONOMY_KEY] = _autonomy_snap(
        has_history=True,
        best_trust=0.55,
        trust_rows=[
            {
                "category": "emocional",
                "trust_score": 0.55,
                "autonomous_count": 1,
                "correction_count": 4,
            }
        ],
        global_rate=0.9,
        global_safety_escalations=0,
        meets_confidence=False,
        ready=False,
        auto_send=False,
    )
    body = build_owner_draft_text(_owner_rec(eval_dict))
    assert "<b>Autonomía</b>" in body
    # parte (a): este borrador no habría ido solo por naturalidad.
    assert "Este borrador no habría ido solo" in body
    assert "naturalidad (0.60; se pide 0.70)" in body
    # parte (b): al VIP le falta confianza y coincidencia.
    assert "todavía no le alcanza la confianza en conversaciones emocionales" in body
    assert "la mejor confianza es 0.55 de 0.90" in body
    assert "La coincidencia de Diana con tus aprobaciones está en 90 % (se pide 95 %)." in body


def test_autonomy_vip_ready_waits_activation() -> None:
    eval_dict = _dims_eval_dict()
    eval_dict[AUTONOMY_KEY] = _autonomy_snap(
        has_history=True,
        best_trust=0.95,
        trust_rows=[
            {
                "category": "informativo",
                "trust_score": 0.95,
                "autonomous_count": 6,
                "correction_count": 0,
            }
        ],
        global_rate=0.96,
        global_safety_escalations=0,
        meets_confidence=True,
        ready=True,
        auto_send=False,
    )
    body = build_owner_draft_text(_owner_rec(eval_dict))
    assert "sí cumpliría los mínimos para el envío autónomo" in body
    assert "solo falta activarlo" in body


def test_autonomy_vip_ready_and_active() -> None:
    eval_dict = _dims_eval_dict()
    eval_dict[AUTONOMY_KEY] = _autonomy_snap(
        has_history=True,
        best_trust=0.95,
        trust_rows=[
            {
                "category": "informativo",
                "trust_score": 0.95,
                "autonomous_count": 6,
                "correction_count": 0,
            }
        ],
        global_rate=0.96,
        global_safety_escalations=0,
        meets_confidence=True,
        ready=True,
        auto_send=True,
    )
    body = build_owner_draft_text(_owner_rec(eval_dict))
    assert "puede enviar sola" in body


def test_render_uses_selected_versions_own_dims() -> None:
    """Per-version eval: old variants keep their own dimension floats."""
    eval_dict = _dims_eval_dict(naturalness=0.9)
    items = eval_dict["_draft_versions"]["items"]
    # Variant 1 was an older draft with low naturalness.
    items[0]["evaluation"] = {
        **items[0]["evaluation"],
        "naturalness": 0.1,
    }
    items.append(
        {
            "text": "v2",
            "reason": "r2",
            "evaluation": {**items[0]["evaluation"], "naturalness": 0.9},
        }
    )
    eval_dict["_draft_versions"]["selected"] = 0
    body = build_owner_draft_text(_owner_rec(eval_dict))
    assert "<b>Naturalidad:</b> 0.10" in body
    eval_dict["_draft_versions"]["selected"] = 1
    body = build_owner_draft_text(_owner_rec(eval_dict))
    assert "<b>Naturalidad:</b> 0.90" in body
