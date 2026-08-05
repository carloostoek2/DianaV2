"""AutonomousModeService — L1/L2 enablement + near-threshold owner notify."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from diana.application.autonomous_mode_service import AutonomousModeService
from diana.application.memory import FakeOwnerNotifier, InMemoryVipStore
from diana.application.ports import VipRecord
from diana.cognitive.models import Decision, EvaluationProfile
from diana.cognitive.thresholds import DEFAULT_AUTONOMOUS_THRESHOLDS


def _eval(**overrides: float) -> EvaluationProfile:
    base = {
        "naturalness": 0.95,
        "precision": 0.9,
        "doctrine": 0.95,
        "consistency": 0.9,
        "safety": 0.95,
        "coverage": 0.9,
        "empathy": 0.9,
    }
    base.update(overrides)
    return EvaluationProfile(**base)


def _decision(evaluation: EvaluationProfile | None = None) -> Decision:
    return Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=evaluation or _eval(),
        draft_text="hola",
    )


def _ams(
    *,
    feature: bool = True,
    global_mode: str = "supervised",
    vip_store: InMemoryVipStore | None = None,
    notifier: FakeOwnerNotifier | None = None,
    thresholds: dict[str, float] | None = None,
    near_margin: float = 0.05,
) -> tuple[AutonomousModeService, InMemoryVipStore, FakeOwnerNotifier]:
    store = vip_store or InMemoryVipStore()
    note = notifier or FakeOwnerNotifier()
    svc = AutonomousModeService(
        feature_autonomous_mode=feature,
        global_mode=global_mode,
        vip_store=store,
        notifier=note,
        autonomous_thresholds=thresholds,
        near_margin=near_margin,
    )
    return svc, store, note


async def _seed_vip(
    store: InMemoryVipStore,
    *,
    auto_send: bool = False,
    frozen_until: datetime | None = None,
) -> VipRecord:
    rec = await store.add(42_001, display_name="VIP")
    if auto_send or frozen_until is not None:
        updated = rec.model_copy(
            update={"auto_send": auto_send, "frozen_until": frozen_until}
        )
        await store._upsert(updated)  # noqa: SLF001 — test seed
        return updated
    return rec


@pytest.mark.asyncio
async def test_l1_off_always_false_regardless_of_mode_or_vip() -> None:
    svc, store, _ = _ams(feature=False, global_mode="autonomous")
    vip = await _seed_vip(store, auto_send=True)
    assert await svc.is_autonomous_enabled(None) is False
    assert await svc.is_autonomous_enabled(vip.id) is False


@pytest.mark.asyncio
async def test_l1_on_global_autonomous_true_for_any_non_none_vip_id() -> None:
    """Anonymous (vip_id=None) is NEVER autonomous, even under global autonomous."""
    svc, store, _ = _ams(feature=True, global_mode="autonomous")
    vip = await _seed_vip(store, auto_send=False)
    assert await svc.is_autonomous_enabled(None) is False
    assert await svc.is_autonomous_enabled(vip.id) is True
    assert await svc.is_autonomous_enabled(uuid4()) is True


@pytest.mark.asyncio
async def test_l1_on_supervised_vip_auto_send_true() -> None:
    svc, store, _ = _ams(feature=True, global_mode="supervised")
    vip = await _seed_vip(store, auto_send=True)
    assert await svc.is_autonomous_enabled(vip.id) is True


@pytest.mark.asyncio
async def test_l1_on_supervised_auto_send_false() -> None:
    svc, store, _ = _ams(feature=True, global_mode="supervised")
    vip = await _seed_vip(store, auto_send=False)
    assert await svc.is_autonomous_enabled(vip.id) is False


@pytest.mark.asyncio
async def test_fake_delivery_mode_does_not_enable_l2() -> None:
    """A2: fake_delivery only affects DeliveryContext.mode, not L2 enablement."""
    svc, store, _ = _ams(feature=True, global_mode="fake_delivery")
    vip = await _seed_vip(store, auto_send=False)
    assert await svc.is_autonomous_enabled(vip.id) is False
    assert await svc.is_autonomous_enabled(None) is False


@pytest.mark.asyncio
async def test_vip_id_none_supervised_false() -> None:
    svc, _, _ = _ams(feature=True, global_mode="supervised")
    assert await svc.is_autonomous_enabled(None) is False


@pytest.mark.asyncio
async def test_unknown_vip_supervised_false() -> None:
    svc, _, _ = _ams(feature=True, global_mode="supervised")
    assert await svc.is_autonomous_enabled(uuid4()) is False


@pytest.mark.asyncio
async def test_notify_safety_exactly_at_min_notifies_once() -> None:
    mins = dict(DEFAULT_AUTONOMOUS_THRESHOLDS)
    svc, _, note = _ams(feature=True, global_mode="autonomous")
    # safety at min, others comfortably above
    evaluation = _eval(
        safety=mins["safety_min"],
        doctrine=mins["doctrine_min"] + 0.1,
        naturalness=mins["naturalness_min"] + 0.1,
    )
    turn_id = uuid4()
    await svc.notify_if_needed(turn_id, _decision(evaluation), evaluation)
    assert len(note.infos) == 1
    assert str(turn_id) in note.infos[0][0]


@pytest.mark.asyncio
async def test_notify_all_dims_high_no_notify() -> None:
    mins = dict(DEFAULT_AUTONOMOUS_THRESHOLDS)
    svc, _, note = _ams(feature=True, global_mode="autonomous")
    evaluation = _eval(
        safety=mins["safety_min"] + 0.05,
        doctrine=mins["doctrine_min"] + 0.05,
        naturalness=mins["naturalness_min"] + 0.05,
    )
    await svc.notify_if_needed(uuid4(), _decision(evaluation), evaluation)
    assert note.infos == []


@pytest.mark.asyncio
async def test_notify_dim_in_near_band_notifies() -> None:
    mins = dict(DEFAULT_AUTONOMOUS_THRESHOLDS)
    margin = 0.05
    svc, _, note = _ams(feature=True, global_mode="autonomous", near_margin=margin)
    # doctrine in [min, min+margin)
    evaluation = _eval(
        safety=mins["safety_min"] + 0.1,
        doctrine=mins["doctrine_min"] + margin / 2,
        naturalness=mins["naturalness_min"] + 0.1,
    )
    await svc.notify_if_needed(uuid4(), _decision(evaluation), evaluation)
    assert len(note.infos) == 1


@pytest.mark.asyncio
async def test_notify_notifier_raises_does_not_propagate() -> None:
    class BoomNotifier(FakeOwnerNotifier):
        async def notify_info(self, text: str, *, chat_id: int | None = None) -> None:
            raise RuntimeError("notifier down")

    mins = dict(DEFAULT_AUTONOMOUS_THRESHOLDS)
    note = BoomNotifier()
    svc, _, _ = _ams(
        feature=True,
        global_mode="autonomous",
        notifier=note,
    )
    evaluation = _eval(safety=mins["safety_min"])
    # Must not raise
    await svc.notify_if_needed(uuid4(), _decision(evaluation), evaluation)


@pytest.mark.asyncio
async def test_vip_record_auto_send_default_false() -> None:
    store = InMemoryVipStore()
    rec = await store.add(77_001)
    assert rec.auto_send is False
    loaded = await store.get_by_id(rec.id)
    assert loaded is not None
    assert loaded.auto_send is False


@pytest.mark.asyncio
async def test_vip_auto_send_preserved_on_upsert() -> None:
    store = InMemoryVipStore()
    rec = await store.add(77_002)
    updated = rec.model_copy(update={"auto_send": True})
    await store._upsert(updated)  # noqa: SLF001
    loaded = await store.get_by_id(rec.id)
    assert loaded is not None
    assert loaded.auto_send is True
    # freeze must not wipe auto_send
    await store.freeze_vip(rec.id, datetime.now(UTC) + timedelta(hours=1))
    loaded2 = await store.get_by_id(rec.id)
    assert loaded2 is not None
    assert loaded2.auto_send is True
    assert loaded2.frozen_until is not None
