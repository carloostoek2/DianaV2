"""Admin Destacar / Reprender (quality feedback) — no Telegram."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from diana.application.ports import DeliveryResult
from diana.application.staging_service import AtencionPromoteBlocked
from diana.application.memory import InMemoryMessageHistoryWriter
from tests.unit.application.test_admin_service import (
    OTHER_USER,
    OWNER_ID,
    _FakeTrustBudgetAdmin,
    _MINIMAL_SIX,
    _admin_graph,
    _decision,
    _incoming,
    _real_staging,
)


async def _pending_vip_draft(
    *,
    feature_on: bool = True,
    staging=None,
    history=None,
    trust_budget=None,
    vip_id=None,
    channel_type: str = "vip",
    draft: str = "original draft",
):
    if staging is None:
        staging, _repo = _real_staging()
    else:
        _repo = staging._staging  # noqa: SLF001 — infra border already mocked
    insert_row = _repo.insert.return_value
    pending = SimpleNamespace(
        id=getattr(insert_row, "id", uuid4()),
        status="pending",
        candidate_type="example",
        payload={
            "original_draft": "original draft",
            "corrected_text": "corrected",
            "context": {"turn_text": "vip trigger text"},
            "channel_type": channel_type,
        },
    )
    _repo.insert.return_value = pending
    _repo.get_by_id = AsyncMock(return_value=pending)
    _repo.update_status = AsyncMock(return_value=True)
    if history is None:
        history = InMemoryMessageHistoryWriter()
        await history.append(
            42, role="vip", text="vip trigger text", telegram_message_id=7
        )
    g = _admin_graph(
        staging=staging,
        history=history,
        feature_quality_feedback_enabled=feature_on,
        trust_budget=trust_budget,
    )
    turn = await g["coordinator"].begin_turn(
        chat_id=42,
        trigger_message_id=7,
        vip_id=vip_id,
        channel_type=channel_type,
    )
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id, telegram_message_id=7, vip_id=vip_id, channel_type=channel_type),
        _decision(draft=draft),
        turn.id,
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    return g, turn, staging, _repo


@pytest.mark.asyncio
async def test_handle_mark_gold_global_inserts_gold_and_approves() -> None:
    staging, staging_repo = _real_staging()
    g, turn, staging, _ = await _pending_vip_draft(staging=staging)
    result = await g["admin"].handle_mark_gold(
        turn.id, scope="global", actor_id=OWNER_ID
    )
    assert result is not None and result.success
    assert g["actuator"].send_count() == 1
    assert g["actuator"].calls[-1]["text"] == "original draft"
    staging._examples.insert.assert_awaited_once()  # noqa: SLF001
    kwargs = staging._examples.insert.await_args.kwargs
    assert kwargs["quality"] == "gold"
    assert kwargs["vip_id"] is None
    assert kwargs["draft_text"] == kwargs["corrected_text"] == "original draft"
    staging_repo.insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_mark_gold_vip_scopes_example() -> None:
    vid = uuid4()
    staging, _ = _real_staging()
    g, turn, staging, _ = await _pending_vip_draft(staging=staging, vip_id=vid)
    result = await g["admin"].handle_mark_gold(
        turn.id, scope="vip", actor_id=OWNER_ID
    )
    assert result is not None and result.success
    kwargs = staging._examples.insert.await_args.kwargs
    assert kwargs["quality"] == "gold"
    assert kwargs["vip_id"] == vid


@pytest.mark.asyncio
async def test_handle_mark_gold_blocks_atencion_before_send() -> None:
    staging, _ = _real_staging()
    g, turn, staging, _ = await _pending_vip_draft(
        staging=staging, channel_type="atencion"
    )
    with pytest.raises(AtencionPromoteBlocked, match="atencion"):
        await g["admin"].handle_mark_gold(turn.id, scope="global", actor_id=OWNER_ID)
    staging._examples.insert.assert_not_awaited()
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_handle_mark_gold_skips_insert_when_approve_none() -> None:
    staging, _ = _real_staging()
    g, turn, staging, _ = await _pending_vip_draft(staging=staging)
    g["admin"].handle_approve = AsyncMock(return_value=None)  # type: ignore[method-assign]
    result = await g["admin"].handle_mark_gold(
        turn.id, scope="global", actor_id=OWNER_ID
    )
    assert result is None
    staging._examples.insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_mark_gold_skips_insert_when_approve_cancelled() -> None:
    staging, _ = _real_staging()
    g, turn, staging, _ = await _pending_vip_draft(staging=staging)
    g["admin"].handle_approve = AsyncMock(  # type: ignore[method-assign]
        return_value=DeliveryResult(success=False, cancelled=True)
    )
    result = await g["admin"].handle_mark_gold(
        turn.id, scope="global", actor_id=OWNER_ID
    )
    assert result is not None and result.cancelled
    staging._examples.insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_mark_gold_sandbox_delivers_without_insert() -> None:
    from diana.application.sandbox import SandboxService

    sandbox = SandboxService(profiles=_MINIMAL_SIX)
    sandbox.activate(42, "nuevo")
    staging, _ = _real_staging(sandbox=sandbox)
    g, turn, staging, _ = await _pending_vip_draft(staging=staging)
    result = await g["admin"].handle_mark_gold(
        turn.id, scope="global", actor_id=OWNER_ID
    )
    assert result is not None and result.success
    assert g["actuator"].send_count() == 1
    staging._examples.insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_quality_feedback_flag_off_raises_and_leaves_correct_approve() -> None:
    from diana.application.admin_service import QualityFeedbackDisabled

    staging, _ = _real_staging()
    g, turn, staging, _ = await _pending_vip_draft(feature_on=False, staging=staging)
    with pytest.raises(QualityFeedbackDisabled):
        await g["admin"].handle_mark_gold(turn.id, scope="global", actor_id=OWNER_ID)
    with pytest.raises(QualityFeedbackDisabled):
        await g["admin"].handle_reprimand(
            turn.id,
            "fixed",
            mode="counter_example",
            scope="global",
            actor_id=OWNER_ID,
        )
    staging._examples.insert.assert_not_awaited()
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None and result.success


@pytest.mark.asyncio
async def test_handle_reprimand_counter_example_uses_save_correction_id() -> None:
    trust = _FakeTrustBudgetAdmin()
    staging, staging_repo = _real_staging()
    save_spy = AsyncMock(wraps=staging.save_correction)
    staging.save_correction = save_spy  # type: ignore[method-assign]
    promote_spy = AsyncMock(wraps=staging.promote_to_counter_example)
    staging.promote_to_counter_example = promote_spy  # type: ignore[method-assign]
    g, turn, staging, _ = await _pending_vip_draft(
        staging=staging, trust_budget=trust
    )
    result = await g["admin"].handle_reprimand(
        turn.id,
        "corrected final",
        mode="counter_example",
        scope="global",
        actor_id=OWNER_ID,
    )
    assert result is not None and result.success
    save_spy.assert_awaited_once()
    persisted_id = staging_repo.insert.return_value.id
    promote_spy.assert_awaited_once()
    assert promote_spy.await_args.args[0] == persisted_id
    staging_repo.list_pending.assert_not_called()
    assert trust.correction_calls == [turn.id]
    assert g["actuator"].calls[-1]["text"] == "corrected final"


@pytest.mark.asyncio
async def test_handle_reprimand_policy_forwards_vip_and_trigger() -> None:
    vid = uuid4()
    staging, _ = _real_staging()
    promote_spy = AsyncMock()
    staging.promote_to_policy = promote_spy  # type: ignore[method-assign]
    g, turn, staging, _ = await _pending_vip_draft(staging=staging, vip_id=vid)
    result = await g["admin"].handle_reprimand(
        turn.id,
        "do not discount",
        mode="policy",
        scope="vip",
        actor_id=OWNER_ID,
    )
    assert result is not None and result.success
    promote_spy.assert_awaited_once()
    kwargs = promote_spy.await_args.kwargs
    assert kwargs["vip_id"] == vid
    assert kwargs["scope"] == "all"
    assert kwargs["rule"] == "do not discount"
    assert kwargs["trigger"] == "vip trigger text"


@pytest.mark.asyncio
async def test_handle_reprimand_stale_does_not_promote() -> None:
    staging, _ = _real_staging()
    promote_spy = AsyncMock(wraps=staging.promote_to_counter_example)
    staging.promote_to_counter_example = promote_spy  # type: ignore[method-assign]
    g, turn, staging, _ = await _pending_vip_draft(staging=staging)
    g["admin"]._resolve_and_deliver = AsyncMock(return_value=None)  # noqa: SLF001
    result = await g["admin"].handle_reprimand(
        turn.id,
        "late fix",
        mode="counter_example",
        scope="global",
        actor_id=OWNER_ID,
    )
    assert result is None
    promote_spy.assert_not_awaited()

    g2, turn2, staging2, _ = await _pending_vip_draft()
    promote2 = AsyncMock(wraps=staging2.promote_to_counter_example)
    staging2.promote_to_counter_example = promote2  # type: ignore[method-assign]
    g2["admin"]._resolve_and_deliver = AsyncMock(  # noqa: SLF001
        return_value=DeliveryResult(success=False, cancelled=True)
    )
    result2 = await g2["admin"].handle_reprimand(
        turn2.id,
        "late fix",
        mode="counter_example",
        scope="global",
        actor_id=OWNER_ID,
    )
    assert result2 is not None and result2.cancelled
    promote2.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_reprimand_sandbox_delivers_without_promote() -> None:
    from diana.application.sandbox import SandboxService

    sandbox = SandboxService(profiles=_MINIMAL_SIX)
    sandbox.activate(42, "nuevo")
    staging, _ = _real_staging(sandbox=sandbox)
    promote_spy = AsyncMock(wraps=staging.promote_to_counter_example)
    staging.promote_to_counter_example = promote_spy  # type: ignore[method-assign]
    g, turn, staging, _ = await _pending_vip_draft(staging=staging)
    result = await g["admin"].handle_reprimand(
        turn.id,
        "sandbox corrected",
        mode="counter_example",
        scope="global",
        actor_id=OWNER_ID,
    )
    assert result is not None and result.success
    promote_spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_reprimand_blocks_atencion_before_correct() -> None:
    staging, staging_repo = _real_staging()
    g, turn, staging, _ = await _pending_vip_draft(
        staging=staging, channel_type="atencion"
    )
    with pytest.raises(AtencionPromoteBlocked, match="atencion"):
        await g["admin"].handle_reprimand(
            turn.id,
            "fixed",
            mode="counter_example",
            scope="global",
            actor_id=OWNER_ID,
        )
    staging_repo.insert.assert_not_awaited()
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_handle_reprimand_candidate_id_promotes_only() -> None:
    trust = _FakeTrustBudgetAdmin()
    candidate_id = uuid4()
    staging, staging_repo = _real_staging()
    staging_repo.get_by_id.return_value = SimpleNamespace(
        id=candidate_id,
        status="pending",
        candidate_type="example",
        payload={
            "original_draft": "old",
            "corrected_text": "fixed",
            "context": {"turn_text": "vip trigger text"},
            "channel_type": "vip",
        },
    )
    staging_repo.update_status.return_value = True
    save_spy = AsyncMock(wraps=staging.save_correction)
    staging.save_correction = save_spy  # type: ignore[method-assign]
    promote_spy = AsyncMock(wraps=staging.promote_to_counter_example)
    staging.promote_to_counter_example = promote_spy  # type: ignore[method-assign]
    g, turn, staging, _ = await _pending_vip_draft(
        staging=staging, trust_budget=trust
    )
    result = await g["admin"].handle_reprimand(
        turn.id,
        "fixed",
        mode="counter_example",
        scope="global",
        actor_id=OWNER_ID,
        candidate_id=candidate_id,
    )
    assert result is None
    save_spy.assert_not_awaited()
    assert trust.correction_calls == []
    promote_spy.assert_awaited_once()
    assert promote_spy.await_args.args[0] == candidate_id
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_handle_mark_gold_and_reprimand_reject_non_owner() -> None:
    from diana.application.admin_service import OwnerAuthError

    staging, _ = _real_staging()
    g, turn, staging, _ = await _pending_vip_draft(staging=staging)
    with pytest.raises(OwnerAuthError):
        await g["admin"].handle_mark_gold(turn.id, scope="global", actor_id=OTHER_USER)
    with pytest.raises(OwnerAuthError):
        await g["admin"].handle_reprimand(
            turn.id,
            "fixed",
            mode="counter_example",
            scope="global",
            actor_id=OTHER_USER,
        )


@pytest.mark.asyncio
async def test_handle_correct_with_candidate_returns_delivery_and_uuid() -> None:
    import inspect

    from diana.application.admin_service import AdminService
    from diana.application.ports import DeliveryResult

    staging, _ = _real_staging()
    g, turn, staging, _ = await _pending_vip_draft(staging=staging)
    delivery, candidate_id = await g["admin"].handle_correct_with_candidate(
        turn.id, "fixed text", actor_id=OWNER_ID
    )
    assert delivery is not None and delivery.success
    assert candidate_id is not None

    staging2, _ = _real_staging()
    g2, turn2, _, _ = await _pending_vip_draft(staging=staging2)
    only_delivery = await g2["admin"].handle_correct(
        turn2.id, "also fixed", actor_id=OWNER_ID
    )
    assert not isinstance(only_delivery, tuple)
    assert only_delivery is not None and hasattr(only_delivery, "success")

    ann = inspect.signature(AdminService.handle_correct).return_annotation
    assert ann == DeliveryResult | None or "tuple" not in str(ann).lower()
