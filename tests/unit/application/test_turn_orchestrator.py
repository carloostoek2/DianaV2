"""TurnOrchestrator: VIP message → decision application (incl. autonomous send)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from diana.application.admin_service import AdminService
from diana.application.autonomous_mode_service import AutonomousModeService
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryMessageHistoryWriter,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryTraceReaderWriter,
    InMemoryTurnStore,
    InMemoryVipStore,
)
from diana.application.ports import VipInboundMessage
from diana.application.turn_coordinator import TurnCoordinator
from diana.application.turn_orchestrator import TurnOrchestrator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.cognitive.analyst import Analyst
from diana.cognitive.context_builder import ContextBuilder
from diana.cognitive.decider import Decider
from diana.cognitive.director import CognitiveDirector
from diana.cognitive.evaluator import Evaluator
from diana.cognitive.generator import Generator
from diana.cognitive.models import (
    Comprehension,
    Decision,
    EvaluationProfile,
    IncomingTurn,
)
from diana.cognitive.planner import Planner
from diana.cognitive.ports import TRACE_KEYS
from diana.cognitive.registry import build_default_registry
from diana.learning.post_turn import LearningService
from diana.llm.fake import FakeLLM

OWNER_ID = 999001


class AsyncSleepClock:
    """Clock that actually awaits sleep (for mid-flight supersede tests)."""

    def __init__(self) -> None:
        self._now = datetime.now(UTC)
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self._now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if seconds > 0:
            await asyncio.sleep(seconds)


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


class FakeDirector:
    def __init__(self, decision: Decision | Exception) -> None:
        self._decision = decision
        self.calls: list[IncomingTurn] = []

    async def handle_turn(self, turn: IncomingTurn) -> Decision:
        self.calls.append(turn)
        if isinstance(self._decision, Exception):
            raise self._decision
        return self._decision


class SlowDirector:
    """Director that blocks until released — for concurrency tests."""

    def __init__(self, decision: Decision, *, delay: float = 0.15) -> None:
        self._decision = decision
        self.delay = delay
        self.started = asyncio.Event()
        self.calls: list[IncomingTurn] = []

    async def handle_turn(self, turn: IncomingTurn) -> Decision:
        self.calls.append(turn)
        self.started.set()
        await asyncio.sleep(self.delay)
        return self._decision


class RecordingLearning:
    def __init__(self, inner: LearningService | None = None) -> None:
        self.calls: list[UUID] = []
        self._inner = inner

    async def run_post_turn(self, turn_id: UUID):
        self.calls.append(turn_id)
        if self._inner:
            return await self._inner.run_post_turn(turn_id)
        return None


class FakeGrayZone:
    """Fake GrayZoneService for consult_doctrine tests."""

    def __init__(self) -> None:
        self.queries: list[dict] = []
        self.next_query_id: UUID = uuid4()

    async def create_query(
        self,
        vip_id: UUID,
        turn_id: UUID,
        question: str,
        draft: str,
        **kwargs,
    ) -> object:
        self.queries.append({
            "vip_id": vip_id,
            "turn_id": turn_id,
            "question": question,
            "draft": draft,
        })
        # Return a simple object matching GrayZoneQueryView protocol (id: UUID).
        return type("_Query", (), {"id": self.next_query_id})()


def _build(
    director: object,
    *,
    learning: RecordingLearning | None = None,
    gray_zone: FakeGrayZone | None = None,
    feature_gray_zone_enabled: bool = False,
    wire_autonomous: bool = False,
    feature_autonomous_mode: bool = False,
    feature_advanced_behavior: bool = False,
    global_mode: str = "supervised",
    delivery_mode: str = "supervised",
    vip_store: InMemoryVipStore | None = None,
    actuator: FakeTelegramActuator | None = None,
    clock: object | None = None,
    delay_policy: FixedDelayPolicy | None = None,
    behavior_override: object | None = None,
) -> dict:
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    history = InMemoryMessageHistoryWriter()
    notifier = FakeOwnerNotifier()
    act = actuator or FakeTelegramActuator()
    behavior = behavior_override or BehaviorEngine(
        act,
        deliveries,
        clock=clock or ImmediateClock(),
        delay_policy=delay_policy or FixedDelayPolicy(),
        feature_advanced_behavior=feature_advanced_behavior,
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)  # type: ignore[arg-type]
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,  # type: ignore[arg-type]
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER_ID,
        delivery_mode=delivery_mode,  # type: ignore[arg-type]
        feature_advanced_behavior=feature_advanced_behavior,
    )
    learn = learning or RecordingLearning(LearningService(traces))
    vips = vip_store or InMemoryVipStore()
    ams: AutonomousModeService | None = None
    if wire_autonomous:
        ams = AutonomousModeService(
            feature_autonomous_mode=feature_autonomous_mode,
            global_mode=global_mode,
            vip_store=vips,
            notifier=notifier,
        )
    orch = TurnOrchestrator(
        coordinator=coordinator,
        director=director,  # type: ignore[arg-type]
        admin=admin,
        learning=learn,
        history=history,
        gray_zone=gray_zone,
        feature_gray_zone_enabled=feature_gray_zone_enabled,
        behavior=behavior if wire_autonomous else None,  # type: ignore[arg-type]
        autonomous_mode=ams,
        vip_store=vips if wire_autonomous else None,
        traces=traces if wire_autonomous else None,
        delivery_mode=delivery_mode,  # type: ignore[arg-type]
        feature_advanced_behavior=feature_advanced_behavior,
    )
    return {
        "orch": orch,
        "director": director,
        "admin": admin,
        "gray_zone": gray_zone,
        "learning": learn,
        "actuator": act,
        "behavior": behavior,
        "notifier": notifier,
        "turns": turns,
        "approvals": approvals,
        "coordinator": coordinator,
        "history": history,
        "traces": traces,
        "deliveries": deliveries,
        "vip_store": vips,
        "ams": ams,
    }


def _vip(**kw) -> VipInboundMessage:
    data = {
        "chat_id": 100,
        "text": "hola diana",
        "telegram_message_id": 11,
        "business_connection_id": "bc-vip",
    }
    data.update(kw)
    return VipInboundMessage(**data)


@pytest.mark.asyncio
async def test_r1_approve_never_auto_delivers() -> None:
    decision = Decision(
        action="approve",
        reason="good",
        evaluation=_eval(),
        draft_text="reply draft",
    )
    g = _build(FakeDirector(decision))
    turn_id = await g["orch"].handle_vip_message(_vip())
    assert g["actuator"].send_count() == 0
    assert len(g["notifier"].drafts) == 1
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"
    assert g["director"].calls[0].turn_id == turn_id


@pytest.mark.asyncio
async def test_r2_supersede_cancels_approval_and_delivery() -> None:
    decision = Decision(
        action="approve",
        reason="good",
        evaluation=_eval(),
        draft_text="draft A",
    )
    g = _build(FakeDirector(decision))
    a = await g["orch"].handle_vip_message(_vip(text="msg A"))
    appr_a = await g["approvals"].get_by_turn(a)
    assert appr_a is not None and appr_a.status == "waiting"
    b = await g["orch"].handle_vip_message(_vip(text="msg B"))
    assert a != b
    stored_a = await g["turns"].get(a)
    assert stored_a is not None
    assert stored_a.status == "superseded"
    assert stored_a.superseded_by == b
    appr_a2 = await g["approvals"].get_by_turn(a)
    assert appr_a2 is not None and appr_a2.status == "cancelled"
    stored_b = await g["turns"].get(b)
    assert stored_b is not None and stored_b.status == "pending_approval"


@pytest.mark.asyncio
async def test_r4_learning_called_once_after_branch() -> None:
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="d",
    )
    g = _build(FakeDirector(decision))
    turn_id = await g["orch"].handle_vip_message(_vip())
    assert g["learning"].calls == [turn_id]


@pytest.mark.asyncio
async def test_learning_on_escalate_path() -> None:
    decision = Decision(
        action="escalate",
        reason="risk",
        evaluation=_eval(),
        draft_text="",
    )
    g = _build(FakeDirector(decision))
    turn_id = await g["orch"].handle_vip_message(_vip())
    assert g["learning"].calls == [turn_id]
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "escalated"


@pytest.mark.asyncio
async def test_r5_approve_after_supersede_no_deliver() -> None:
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="old draft",
    )
    g = _build(FakeDirector(decision))
    a = await g["orch"].handle_vip_message(_vip(text="A"))
    await g["orch"].handle_vip_message(_vip(text="B"))
    result = await g["admin"].handle_approve(a, actor_id=OWNER_ID)
    assert result is None
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_escalate_path_no_deliver() -> None:
    decision = Decision(
        action="escalate",
        reason="risk alto",
        evaluation=_eval(),
        draft_text="",
    )
    g = _build(FakeDirector(decision))
    turn_id = await g["orch"].handle_vip_message(_vip())
    assert g["actuator"].send_count() == 0
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "escalated"
    assert len(g["notifier"].escalations) == 1


@pytest.mark.asyncio
async def test_send_without_ams_marks_failed_not_wired() -> None:
    """Defense: send with AMS not injected → no deliver, failed autonomous_not_wired."""
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="would deliver",
    )
    g = _build(FakeDirector(decision))
    turn_id = await g["orch"].handle_vip_message(_vip())
    assert g["actuator"].send_count() == 0
    assert g["learning"].calls == [turn_id]
    failed = await g["turns"].get(turn_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "autonomous_not_wired"


@pytest.mark.asyncio
async def test_send_autonomous_delivers_and_marks_delivered() -> None:
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="auto reply",
    )
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        delivery_mode="autonomous",
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=uuid4()))
    assert g["actuator"].send_count() >= 1
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "delivered"
    assert g["learning"].calls == [turn_id]
    assert await g["approvals"].get_by_turn(turn_id) is None
    assert g["traces"].get_delivery_result(turn_id) is not None


@pytest.mark.asyncio
async def test_send_ams_disabled_falls_back_to_approve() -> None:
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="would auto",
    )
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=False,  # L1 off
        global_mode="autonomous",
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=uuid4()))
    assert g["actuator"].send_count() == 0
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"
    assert len(g["notifier"].drafts) == 1
    assert g["notifier"].drafts[0].reason == "autonomous_mode_disabled"
    assert g["learning"].calls == [turn_id]


@pytest.mark.asyncio
async def test_send_ams_supervised_without_auto_send_falls_back_to_approve() -> None:
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="would auto",
    )
    store = InMemoryVipStore()
    vip = await store.add(5001)
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="supervised",
        vip_store=store,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip.id))
    assert g["actuator"].send_count() == 0
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"
    appr = await g["approvals"].get_by_turn(turn_id)
    assert appr is not None
    # SUG-2: demote reason must not keep autonomous_ok
    assert appr.cognitive_summary == "autonomous_mode_disabled"
    assert len(g["notifier"].drafts) == 1
    assert g["notifier"].drafts[0].reason == "autonomous_mode_disabled"


@pytest.mark.asyncio
async def test_send_supervised_with_auto_send_delivers() -> None:
    """SUG-1: L1 on + supervised + vip.auto_send → deliver path."""
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="per-vip auto",
    )
    store = InMemoryVipStore()
    vip = await store.add(5100, display_name="AutoVIP")
    updated = vip.model_copy(update={"auto_send": True})
    await store._upsert(updated)  # noqa: SLF001 — test seed
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="supervised",
        delivery_mode="supervised",
        vip_store=store,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip.id))
    assert g["actuator"].send_count() >= 1
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "delivered"
    assert await g["approvals"].get_by_turn(turn_id) is None
    assert g["learning"].calls == [turn_id]


@pytest.mark.asyncio
async def test_send_frozen_after_prepare_no_deliver() -> None:
    """BUG-1: freeze between prepare and deliver fails closed, no VIP send."""
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="race freeze",
    )
    store = InMemoryVipStore()
    vip = await store.add(5200)
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        delivery_mode="autonomous",
        vip_store=store,
    )
    # Second _is_vip_frozen call is the post-lock re-check → treat as frozen.
    calls = {"n": 0}
    real_is_frozen = g["orch"]._is_vip_frozen  # noqa: SLF001

    async def freeze_on_second_check(vip_id: UUID | None) -> bool:
        calls["n"] += 1
        if calls["n"] >= 2:
            return True
        return await real_is_frozen(vip_id)

    g["orch"]._is_vip_frozen = freeze_on_second_check  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip.id))
    assert g["actuator"].send_count() == 0
    stored = await g["turns"].get(turn_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error == "vip_frozen"
    assert g["learning"].calls == [turn_id]


@pytest.mark.asyncio
async def test_send_frozen_vip_no_deliver() -> None:
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="frozen draft",
    )
    store = InMemoryVipStore()
    vip = await store.add(5002)
    await store.freeze_vip(vip.id, datetime.now(UTC) + timedelta(hours=2))
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        vip_store=store,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip.id))
    assert g["actuator"].send_count() == 0
    stored = await g["turns"].get(turn_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error == "vip_frozen"
    assert g["learning"].calls == [turn_id]
    assert any("vip_frozen" in t or "frozen" in t.lower() for t, _ in g["notifier"].infos)


@pytest.mark.asyncio
async def test_send_empty_draft_no_deliver() -> None:
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="   ",
    )
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=uuid4()))
    assert g["actuator"].send_count() == 0
    stored = await g["turns"].get(turn_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error == "empty_draft"
    assert g["learning"].calls == [turn_id]


@pytest.mark.asyncio
async def test_send_deliver_fail_marks_failed_and_notifies() -> None:
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="boom",
    )

    class BoomActuator(FakeTelegramActuator):
        async def send_message(
            self,
            chat_id: int,
            text: str,
            *,
            business_connection_id: str,
        ) -> int:
            raise RuntimeError("telegram_down")

    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        delivery_mode="autonomous",
        actuator=BoomActuator(),
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=uuid4()))
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "failed"
    assert stored.error is not None
    assert any(
        "delivery_failed" in text or "failed" in text.lower()
        for text, _ in g["notifier"].infos
    )
    assert g["traces"].get_delivery_result(turn_id) is not None
    assert g["learning"].calls == [turn_id]


@pytest.mark.asyncio
async def test_send_supersede_mid_flight_no_delivered_revive() -> None:
    """Second VIP message supersedes while first deliver sleeps — no delivered revive."""
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="slow auto",
    )
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        delivery_mode="autonomous",
        clock=AsyncSleepClock(),
        delay_policy=FixedDelayPolicy(initial=0.35, typing=0.0),
    )
    first = asyncio.create_task(
        g["orch"].handle_vip_message(_vip(text="msg A", telegram_message_id=11))
    )
    await asyncio.sleep(0.05)
    second = asyncio.create_task(
        g["orch"].handle_vip_message(_vip(text="msg B", telegram_message_id=12))
    )
    turn_a, turn_b = await asyncio.gather(first, second)
    stored_a = await g["turns"].get(turn_a)
    assert stored_a is not None
    assert stored_a.status != "delivered"
    assert stored_a.status in {"superseded", "failed"}
    stored_b = await g["turns"].get(turn_b)
    assert stored_b is not None
    # Second may deliver (still live) or land elsewhere — must not revive A.
    assert stored_a.status != "delivered"


@pytest.mark.asyncio
async def test_director_exception_marks_failed_and_reraises() -> None:
    g = _build(FakeDirector(RuntimeError("llm down")))
    with pytest.raises(RuntimeError, match="llm down"):
        await g["orch"].handle_vip_message(_vip())
    non_term = await g["turns"].list_non_terminal(100)
    assert non_term == []
    # Exactly one turn and it is failed with error text
    # (scan via a second begin would supersede — load by director call)
    # Director never returned; turn was minted before fail.
    assert g["actuator"].send_count() == 0
    assert g["learning"].calls == []
    failed_ids = [
        t.id
        for t in g["turns"]._turns.values()  # noqa: SLF001 — test assertion
        if t.chat_id == 100
    ]
    assert len(failed_ids) == 1
    failed = await g["turns"].get(failed_ids[0])
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "llm down"
    # Generic director errors do not use the Analyst schema-fail notify path.
    assert g["notifier"].infos == []


# --- Item4 Task4: advanced behavior builder wiring ---


class _CapturingDeliverer:
    """Spy BehaviorDeliverer that records DeliveryContext on deliver."""

    def __init__(self) -> None:
        self.ctxs: list = []
        self.texts: list[list[str]] = []

    async def deliver(
        self,
        texts: list[str],
        ctx: object,
        turn_id: UUID,
        decision: object | None = None,
    ) -> object:
        from diana.application.ports import DeliveryResult

        self.ctxs.append(ctx)
        self.texts.append(list(texts))
        return DeliveryResult(success=True, message_ids=[1])


@pytest.mark.asyncio
async def test_orch_advanced_flag_on_sets_allow_on_deliver_ctx() -> None:
    spy = _CapturingDeliverer()
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="auto reply",
    )
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        feature_advanced_behavior=True,
        global_mode="autonomous",
        delivery_mode="autonomous",
        behavior_override=spy,
    )
    await g["orch"].handle_vip_message(_vip(vip_id=uuid4()))
    assert len(spy.ctxs) == 1
    ctx = spy.ctxs[0]
    assert ctx.allow_split is True
    assert ctx.allow_human_quirks is True
    assert ctx.split_chars == 4096


@pytest.mark.asyncio
async def test_orch_advanced_flag_off_allow_defaults_false() -> None:
    spy = _CapturingDeliverer()
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="auto reply",
    )
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        feature_advanced_behavior=False,
        global_mode="autonomous",
        delivery_mode="autonomous",
        behavior_override=spy,
    )
    await g["orch"].handle_vip_message(_vip(vip_id=uuid4()))
    assert len(spy.ctxs) == 1
    ctx = spy.ctxs[0]
    assert ctx.allow_split is False
    assert ctx.allow_human_quirks is False
    assert ctx.split_chars == 4096


@pytest.mark.asyncio
async def test_orch_autonomous_send_still_works_flag_off_regression() -> None:
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="auto reply",
    )
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        feature_advanced_behavior=False,
        global_mode="autonomous",
        delivery_mode="autonomous",
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=uuid4()))
    assert g["actuator"].send_count() >= 1
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "delivered"


@pytest.mark.asyncio
async def test_orchestrator_analyst_schema_fail_marks_failed_notifies_owner() -> None:
    """A.6: schema fail → failed + analista_schema_invalido + owner notify; no VIP send."""
    from diana.cognitive.exceptions import AnalystSchemaInvalidError

    invalid = {"intent": "only"}
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    history = InMemoryMessageHistoryWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER_ID,
    )
    llm = FakeLLM(structured_responses=[invalid, invalid], text_responses=[])
    director = CognitiveDirector(
        analyst=Analyst(llm),
        planner=Planner(),
        registry=build_default_registry(history),
        context_builder=ContextBuilder(),
        generator=Generator(llm),
        evaluator=Evaluator(llm),
        decider=Decider(),
        trace=traces,
        persona="You are Diana.",
        history=history,
        analyst_history_limit=8,
        status_sink=coordinator,
    )
    learn = RecordingLearning()
    orch = TurnOrchestrator(
        coordinator=coordinator,
        director=director,
        admin=admin,
        learning=learn,
        history=history,
    )

    with pytest.raises(AnalystSchemaInvalidError):
        await orch.handle_vip_message(_vip(text="schema-fail-msg"))

    failed_ids = [
        t.id
        for t in turns._turns.values()  # noqa: SLF001 — test assertion
        if t.chat_id == 100
    ]
    assert len(failed_ids) == 1
    failed = await turns.get(failed_ids[0])
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "analista_schema_invalido"

    assert actuator.send_count() == 0
    assert learn.calls == []
    assert len(notifier.infos) == 1
    assert notifier.drafts == []
    assert notifier.escalations == []
    info_text, _info_chat = notifier.infos[0]
    assert "analista_schema_invalido" in info_text
    assert str(failed_ids[0]) in info_text


@pytest.mark.asyncio
async def test_orchestrator_evaluator_schema_fail_marks_failed_notifies_owner() -> None:
    """B.6: Evaluator schema fail → failed + evaluador_schema_invalido + owner notify; no VIP send."""
    from diana.cognitive.exceptions import EvaluatorSchemaInvalidError

    incomplete = {
        "naturalness": 0.5,
        "precision": 0.5,
        "doctrine": 0.5,
        "consistency": 0.5,
        "safety": 0.5,
        "coverage": 0.5,
        # empathy missing
    }
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    history = InMemoryMessageHistoryWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER_ID,
    )
    llm = FakeLLM(
        structured_responses=[
            # valid Comprehension
            {
                "intent": "chat",
                "topics": ["x"],
                "emotion": "neutral",
                "urgency": "baja",
                "risk": "bajo",
                "needs_memory": False,
                "needs_policy": False,
                "needs_schedule": False,
                "needs_examples": False,
                "needs_history": True,
                "needs_context": True,
            },
            incomplete,
            incomplete,
        ],
        text_responses=["draft text for vip"],
    )
    director = CognitiveDirector(
        analyst=Analyst(llm),
        planner=Planner(),
        registry=build_default_registry(history),
        context_builder=ContextBuilder(),
        generator=Generator(llm),
        evaluator=Evaluator(llm),
        decider=Decider(),
        trace=traces,
        persona="You are Diana.",
        history=history,
        analyst_history_limit=8,
        status_sink=coordinator,
    )
    learn = RecordingLearning()
    orch = TurnOrchestrator(
        coordinator=coordinator,
        director=director,
        admin=admin,
        learning=learn,
        history=history,
    )

    with pytest.raises(EvaluatorSchemaInvalidError):
        await orch.handle_vip_message(_vip(text="eval-schema-fail-msg"))

    failed_ids = [
        t.id
        for t in turns._turns.values()  # noqa: SLF001 — test assertion
        if t.chat_id == 100
    ]
    assert len(failed_ids) == 1
    failed = await turns.get(failed_ids[0])
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "evaluador_schema_invalido"

    assert actuator.send_count() == 0
    assert learn.calls == []
    assert len(notifier.infos) == 1
    assert notifier.drafts == []
    assert notifier.escalations == []
    info_text, _info_chat = notifier.infos[0]
    assert "evaluador_schema_invalido" in info_text
    assert str(failed_ids[0]) in info_text


@pytest.mark.asyncio
async def test_orchestrator_context_exceeds_limit_marks_failed_notifies_owner() -> None:
    """D.6: size fail → failed + contexto_excede_limite + owner notify; no VIP send."""
    from diana.cognitive.exceptions import ContextExceedsLimitError

    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    history = InMemoryMessageHistoryWriter()
    # Seed huge history so ContextBuilder with tiny budget raises on build.
    await history.append(
        100,
        role="vip",
        text="HUGE-HISTORY-" + ("X" * 500),
        telegram_message_id=1,
    )
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER_ID,
    )
    llm = FakeLLM(
        structured_responses=[
            {
                "intent": "chat",
                "topics": ["x"],
                "emotion": "neutral",
                "urgency": "baja",
                "risk": "bajo",
                "needs_memory": False,
                "needs_policy": False,
                "needs_schedule": False,
                "needs_examples": False,
                "needs_history": True,
                "needs_context": True,
            },
        ],
        text_responses=["should-not-send"],
    )
    director = CognitiveDirector(
        analyst=Analyst(llm),
        planner=Planner(),
        registry=build_default_registry(history),
        context_builder=ContextBuilder(max_prompt_chars=80),
        generator=Generator(llm),
        evaluator=Evaluator(llm),
        decider=Decider(),
        trace=traces,
        persona="You are Diana.",
        history=history,
        analyst_history_limit=8,
        status_sink=coordinator,
    )
    learn = RecordingLearning()
    orch = TurnOrchestrator(
        coordinator=coordinator,
        director=director,
        admin=admin,
        learning=learn,
        history=history,
    )

    with pytest.raises(ContextExceedsLimitError):
        await orch.handle_vip_message(_vip(text="size-fail-msg"))

    failed_ids = [
        t.id
        for t in turns._turns.values()  # noqa: SLF001 — test assertion
        if t.chat_id == 100
    ]
    assert len(failed_ids) == 1
    failed = await turns.get(failed_ids[0])
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "contexto_excede_limite"

    assert actuator.send_count() == 0
    assert learn.calls == []
    assert len(notifier.infos) == 1
    assert notifier.drafts == []
    assert notifier.escalations == []
    info_text, _info_chat = notifier.infos[0]
    assert "contexto_excede_limite" in info_text
    assert str(failed_ids[0]) in info_text


@pytest.mark.asyncio
async def test_orchestrator_generator_empty_marks_failed_notifies_owner() -> None:
    """E.4: Generator empty → failed + generador_salida_vacia + owner notify; no VIP send."""
    from diana.cognitive.exceptions import GeneratorEmptyOutputError

    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    history = InMemoryMessageHistoryWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER_ID,
    )
    llm = FakeLLM(
        structured_responses=[
            {
                "intent": "chat",
                "topics": ["x"],
                "emotion": "neutral",
                "urgency": "baja",
                "risk": "bajo",
                "needs_memory": False,
                "needs_policy": False,
                "needs_schedule": False,
                "needs_examples": False,
                "needs_history": True,
                "needs_context": True,
            },
        ],
        text_responses=["", ""],
    )
    director = CognitiveDirector(
        analyst=Analyst(llm),
        planner=Planner(),
        registry=build_default_registry(history),
        context_builder=ContextBuilder(),
        generator=Generator(llm),
        evaluator=Evaluator(llm),
        decider=Decider(),
        trace=traces,
        persona="You are Diana.",
        history=history,
        analyst_history_limit=8,
        status_sink=coordinator,
    )
    learn = RecordingLearning()
    orch = TurnOrchestrator(
        coordinator=coordinator,
        director=director,
        admin=admin,
        learning=learn,
        history=history,
    )

    with pytest.raises(GeneratorEmptyOutputError):
        await orch.handle_vip_message(_vip(text="gen-empty-fail-msg"))

    failed_ids = [
        t.id
        for t in turns._turns.values()  # noqa: SLF001 — test assertion
        if t.chat_id == 100
    ]
    assert len(failed_ids) == 1
    failed = await turns.get(failed_ids[0])
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "generador_salida_vacia"

    assert actuator.send_count() == 0
    assert learn.calls == []
    assert len(notifier.infos) == 1
    assert notifier.drafts == []
    assert notifier.escalations == []
    info_text, _info_chat = notifier.infos[0]
    assert "generador_salida_vacia" in info_text
    assert str(failed_ids[0]) in info_text
    # No pending approval / empty draft in approval queue.
    assert await approvals.get_by_turn(failed_ids[0]) is None
    assert await approvals.list_waiting() == []


@pytest.mark.asyncio
async def test_turn_id_minted_before_director() -> None:
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="d",
    )
    g = _build(FakeDirector(decision))
    turn_id = await g["orch"].handle_vip_message(_vip())
    assert isinstance(turn_id, UUID)
    assert g["director"].calls[0].turn_id == turn_id
    assert g["director"].calls[0].text == "hola diana"


@pytest.mark.asyncio
async def test_history_appends_vip_message() -> None:
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="d",
    )
    g = _build(FakeDirector(decision))
    await g["orch"].handle_vip_message(_vip(text="keep me"))
    recent = await g["history"].get_recent(100)
    assert recent[-1]["role"] == "vip"
    assert recent[-1]["text"] == "keep me"


@pytest.mark.asyncio
async def test_missing_business_connection_id_fails_turn() -> None:
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="d",
    )
    g = _build(FakeDirector(decision))
    with pytest.raises(ValueError, match="business_connection_id"):
        await g["orch"].handle_vip_message(_vip(business_connection_id=None))
    non_term = await g["turns"].list_non_terminal(100)
    assert non_term == []
    failed_ids = [
        t
        for t in g["turns"]._turns.values()  # noqa: SLF001
        if t.chat_id == 100
    ]
    assert len(failed_ids) == 1
    assert failed_ids[0].status == "failed"


@pytest.mark.asyncio
async def test_owner_approve_after_orchestrator_delivers() -> None:
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="final draft",
    )
    g = _build(FakeDirector(decision))
    turn_id = await g["orch"].handle_vip_message(_vip())
    g["traces"].seed_keys(turn_id, TRACE_KEYS)
    result = await g["admin"].handle_approve(turn_id, actor_id=OWNER_ID)
    assert result is not None and result.success
    assert g["actuator"].send_count() == 1
    assert g["actuator"].calls[-1]["text"] == "final draft"
    # mark-as-read when telegram_message_id present
    assert any(c["op"] == "read_business_message" for c in g["actuator"].calls)


@pytest.mark.asyncio
async def test_concurrent_vip_messages_one_non_terminal_no_zombie() -> None:
    """Full chat lock + terminal latch: concurrent VIP msgs never revive old turn."""
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="draft",
    )
    slow = SlowDirector(decision, delay=0.1)
    g = _build(slow)

    task_a = asyncio.create_task(
        g["orch"].handle_vip_message(_vip(text="msg A", telegram_message_id=1))
    )
    await slow.started.wait()
    task_b = asyncio.create_task(
        g["orch"].handle_vip_message(_vip(text="msg B", telegram_message_id=2))
    )
    a_id, b_id = await asyncio.gather(task_a, task_b)

    non_term = await g["turns"].list_non_terminal(100)
    assert len(non_term) == 1
    # Older turn must not be pending_approval if superseded
    for tid in (a_id, b_id):
        rec = await g["turns"].get(tid)
        assert rec is not None
        if rec.status == "superseded":
            assert rec.superseded_by is not None
            # cannot have waiting approval on superseded
            appr = await g["approvals"].get_by_turn(tid)
            if appr is not None:
                assert appr.status != "waiting"
        elif rec.status == "pending_approval":
            assert non_term[0].id == tid

    # Approving the superseded turn never sends
    for tid in (a_id, b_id):
        rec = await g["turns"].get(tid)
        if rec is not None and rec.status == "superseded":
            result = await g["admin"].handle_approve(tid, actor_id=OWNER_ID)
            assert result is None
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_post_director_aborts_if_already_terminal() -> None:
    """Defense-in-depth: if turn is terminal after Director, no new approval."""

    class TerminalizingDirector:
        def __init__(self, coordinator: TurnCoordinator, decision: Decision) -> None:
            self._coordinator = coordinator
            self._decision = decision
            self.calls: list[IncomingTurn] = []

        async def handle_turn(self, turn: IncomingTurn) -> Decision:
            self.calls.append(turn)
            # Force terminal without going through begin_turn (simulates race).
            await self._coordinator.transition(turn.turn_id, "superseded")
            return self._decision

    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="stale",
    )
    # Build graph without director first
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    history = InMemoryMessageHistoryWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)
    director = TerminalizingDirector(coordinator, decision)
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER_ID,
    )
    learn = RecordingLearning()
    orch = TurnOrchestrator(
        coordinator=coordinator,
        director=director,  # type: ignore[arg-type]
        admin=admin,
        learning=learn,
        history=history,
    )
    turn_id = await orch.handle_vip_message(_vip())
    stored = await turns.get(turn_id)
    assert stored is not None
    assert stored.status == "superseded"
    assert await approvals.get_by_turn(turn_id) is None
    assert learn.calls == [turn_id]
    assert actuator.send_count() == 0


def _comprehension(**overrides) -> Comprehension:
    data = {
        "intent": "chat",
        "topics": ["general"],
        "emotion": "neutral",
        "urgency": "baja",
        "risk": "bajo",
        "needs_history": True,
        "needs_context": True,
        "needs_memory": False,
        "needs_policy": False,
        "needs_examples": False,
        "needs_schedule": False,
    }
    data.update(overrides)
    return Comprehension(**data)


def _profile(**overrides: float) -> EvaluationProfile:
    data = {
        "naturalness": 0.9,
        "precision": 0.8,
        "doctrine": 0.85,
        "consistency": 0.9,
        "safety": 0.95,
        "coverage": 0.7,
        "empathy": 0.8,
    }
    data.update(overrides)
    return EvaluationProfile(**data)


@pytest.mark.asyncio
async def test_orchestrator_happy_path_real_director_fake_llm() -> None:
    """End-to-end application shell: real CognitiveDirector + FakeLLM + fakes."""
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    history = InMemoryMessageHistoryWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER_ID,
    )
    llm = FakeLLM(
        structured_responses=[
            _comprehension(risk="medio"),
            _profile(safety=0.9),
        ],
        text_responses=["Real pipeline draft"],
    )
    director = CognitiveDirector(
        analyst=Analyst(llm),
        planner=Planner(),
        registry=build_default_registry(history),
        context_builder=ContextBuilder(),
        generator=Generator(llm),
        evaluator=Evaluator(llm),
        decider=Decider(),
        trace=traces,
        persona="You are Diana.",
        history=history,
        analyst_history_limit=8,
        status_sink=coordinator,
    )
    learning = LearningService(traces)
    orch = TurnOrchestrator(
        coordinator=coordinator,
        director=director,
        admin=admin,
        learning=learning,
        history=history,
    )

    turn_id = await orch.handle_vip_message(_vip(text="hola del VIP"))

    assert actuator.send_count() == 0
    assert len(notifier.drafts) == 1
    assert notifier.drafts[0].draft_text == "Real pipeline draft"

    stored = await turns.get(turn_id)
    assert stored is not None
    assert stored.status == "pending_approval"

    report = await learning.run_post_turn(turn_id)
    assert report.complete is True
    assert report.missing == []
    trace_keys = await traces.get_trace_keys(turn_id)
    assert set(TRACE_KEYS).issubset(trace_keys)
    assert "timings" in trace_keys

    methods = [name for name, _ in llm.calls]
    assert methods == [
        "generate_structured",
        "generate",
        "generate_structured",
    ]

    recent = await history.get_recent(100)
    assert recent[-1]["role"] == "vip"
    assert recent[-1]["text"] == "hola del VIP"

    result = await admin.handle_approve(turn_id, actor_id=OWNER_ID)
    assert result is not None and result.success is True
    assert actuator.send_count() == 1
    assert actuator.calls[-1]["text"] == "Real pipeline draft"
    delivered = await turns.get(turn_id)
    assert delivered is not None and delivered.status == "delivered"


@pytest.mark.asyncio
async def test_r2_supersede_invokes_behavior_cancel_pending() -> None:
    """Supersede cascade must call BehaviorEngine.cancel_pending (R2/TAC-07)."""

    class CountingBehavior(BehaviorEngine):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.cancel_calls: list[tuple[int, str]] = []

        async def cancel_pending(
            self, chat_id: int, reason: str = "new_message"
        ) -> None:
            self.cancel_calls.append((chat_id, reason))
            await super().cancel_pending(chat_id, reason)

    decision = Decision(
        action="approve",
        reason="good",
        evaluation=_eval(),
        draft_text="draft A",
    )
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    history = InMemoryMessageHistoryWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    behavior = CountingBehavior(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER_ID,
    )
    learn = RecordingLearning(LearningService(traces))
    orch = TurnOrchestrator(
        coordinator=coordinator,
        director=FakeDirector(decision),
        admin=admin,
        learning=learn,
        history=history,
    )
    await orch.handle_vip_message(_vip(text="msg A"))
    assert behavior.cancel_calls == []
    await orch.handle_vip_message(_vip(text="msg B"))
    assert behavior.cancel_calls == [(100, "new_message")]


# ── F2 consult_doctrine branch ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_consult_doctrine_happy_path() -> None:
    """Happy path: consult_doctrine → query created, owner notified, gray_zone."""
    decision = Decision(
        action="consult_doctrine",
        reason="doctrine_not_found",
        evaluation=_eval(),
        draft_text="need policy",
    )
    gz = FakeGrayZone()
    g = _build(
        FakeDirector(decision),
        gray_zone=gz,
        feature_gray_zone_enabled=True,
    )
    vip_id = uuid4()
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    assert len(gz.queries) == 1
    assert gz.queries[0]["vip_id"] == vip_id
    assert gz.queries[0]["turn_id"] == turn_id
    assert gz.queries[0]["question"] == "hola diana"
    assert gz.queries[0]["draft"] == "need policy"
    assert len(g["notifier"].doctrines) == 1
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "gray_zone"
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_consult_doctrine_raises_when_feature_disabled() -> None:
    """Guard: consult_doctrine action with feature disabled raises RuntimeError."""
    decision = Decision(
        action="consult_doctrine",
        reason="doctrine_not_found",
        evaluation=_eval(),
    )
    g = _build(FakeDirector(decision), gray_zone=FakeGrayZone())
    with pytest.raises(RuntimeError, match="gray zone feature is disabled"):
        await g["orch"].handle_vip_message(_vip())
    assert g["notifier"].doctrines == []


@pytest.mark.asyncio
async def test_consult_doctrine_raises_when_gray_zone_none() -> None:
    """Guard: consult_doctrine action with gray_zone=None raises RuntimeError."""
    decision = Decision(
        action="consult_doctrine",
        reason="doctrine_not_found",
        evaluation=_eval(),
    )
    g = _build(FakeDirector(decision), feature_gray_zone_enabled=True)
    with pytest.raises(RuntimeError, match="GrayZoneService is not injected"):
        await g["orch"].handle_vip_message(_vip())


@pytest.mark.asyncio
async def test_consult_doctrine_raises_when_vip_id_none() -> None:
    """Guard: consult_doctrine with vip_id=None raises RuntimeError."""
    decision = Decision(
        action="consult_doctrine",
        reason="doctrine_not_found",
        evaluation=_eval(),
    )
    g = _build(
        FakeDirector(decision),
        gray_zone=FakeGrayZone(),
        feature_gray_zone_enabled=True,
    )
    with pytest.raises(RuntimeError, match="consult_doctrine requires vip_id"):
        await g["orch"].handle_vip_message(_vip(vip_id=None))


@pytest.mark.asyncio
async def test_orchestrator_notify_fail_soft_increments_swallowed_counter() -> None:
    """Notify raise on schema-fail path still mark_failed + re-raise; counter +1."""
    from diana.application.observability import (
        get_swallowed_counts,
        reset_swallowed_counts,
    )
    from diana.cognitive.exceptions import AnalystSchemaInvalidError

    reset_swallowed_counts()
    g = _build(FakeDirector(AnalystSchemaInvalidError()))

    async def boom(text: str, *, chat_id: int | None = None) -> None:
        raise RuntimeError("notify down")

    g["notifier"].notify_info = boom  # type: ignore[method-assign]

    with pytest.raises(AnalystSchemaInvalidError):
        await g["orch"].handle_vip_message(_vip())

    failed_ids = [
        t.id
        for t in g["turns"]._turns.values()  # noqa: SLF001
        if t.chat_id == 100
    ]
    assert len(failed_ids) == 1
    failed = await g["turns"].get(failed_ids[0])
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "analista_schema_invalido"
    assert get_swallowed_counts().get(
        "owner_notify_failed_after_analyst_schema_invalid", 0
    ) == 1
    assert g["actuator"].send_count() == 0
