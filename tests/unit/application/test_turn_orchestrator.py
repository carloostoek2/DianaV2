"""TurnOrchestrator: VIP message → decision application (no auto-send)."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from diana.application.admin_service import AdminService
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryMessageHistoryWriter,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryTraceReaderWriter,
    InMemoryTurnStore,
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
) -> dict:
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
    learn = learning or RecordingLearning(LearningService(traces))
    orch = TurnOrchestrator(
        coordinator=coordinator,
        director=director,  # type: ignore[arg-type]
        admin=admin,
        learning=learn,
        history=history,
        gray_zone=gray_zone,
        feature_gray_zone_enabled=feature_gray_zone_enabled,
    )
    return {
        "orch": orch,
        "director": director,
        "admin": admin,
        "gray_zone": gray_zone,
        "learning": learn,
        "actuator": actuator,
        "behavior": behavior,
        "notifier": notifier,
        "turns": turns,
        "approvals": approvals,
        "coordinator": coordinator,
        "history": history,
        "traces": traces,
        "deliveries": deliveries,
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
async def test_send_action_fail_closed_marks_failed() -> None:
    """Item1: Decision(action=send) is constructible; orchestrator stays fail-closed."""
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="would deliver",
    )
    g = _build(FakeDirector(decision))
    with pytest.raises(ValueError, match="unexpected F2 action: 'send'"):
        await g["orch"].handle_vip_message(_vip())
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
    assert failed.error == "unexpected F2 action: 'send'"


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
    # Reconstruct: only failed terminal exists for chat — probe by creating nothing
    # and checking list_non_terminal already empty; also try get via coordinator
    # history of transitions is not stored; use internal store scan:
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
