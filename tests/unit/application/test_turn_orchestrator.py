"""TurnOrchestrator: VIP message → decision application (incl. autonomous send)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from unittest.mock import ANY, AsyncMock
from uuid import UUID, uuid4

import pytest

from diana.application.admin_service import AdminService
from diana.application.approval_ui import ApprovalDraftVoider
from diana.application.autonomous_mode_service import AutonomousModeService
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryMessageHistoryWriter,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryRuntimeTimerStore,
    InMemoryTraceReaderWriter,
    InMemoryTurnStore,
    InMemoryVipStore,
)
from diana.application.ports import (
    EmotionalSignalRecord,
    TurnCategoryLogRecord,
    TurnRecord,
    VipInboundMessage,
    VipMoodStateRecord,
)
from diana.application.mood_engine import MoodEngine, MoodSignal, MoodState
from diana.application.turn_classifier import TurnClassification
from diana.application.turn_coordinator import TurnCoordinator
from diana.application.turn_orchestrator import (
    ATENCION_DAILY_LIMIT_CLOSE,
    ATENCION_PAYMENT_NOTICE,
    TurnOrchestrator,
    _PAYMENT_NOTIFY_TTL,
    _detect_payment_intent,
)
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
    is_turn_status_terminal,
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


class RecordingExtraction:
    """Fake post-turn memory extractor (F5 Pool 3): records (turn_id, chat_id)."""

    def __init__(self, *, raise_on_call: bool = False) -> None:
        self.calls: list[tuple[UUID, int]] = []
        self._raise_on_call = raise_on_call

    async def extract_post_turn(self, turn_id: UUID, chat_id: int) -> None:
        if self._raise_on_call:
            raise RuntimeError("extraction boom")
        self.calls.append((turn_id, chat_id))


class FakeGrayZone:
    """Fake GrayZoneService for consult_doctrine tests."""

    def __init__(
        self, *, existing_chat_query: object | None = None
    ) -> None:
        self.queries: list[dict] = []
        self.next_query_id: UUID = uuid4()
        self.discarded: list[UUID] = []
        self._existing_chat_query = existing_chat_query

    async def create_query(
        self,
        vip_id: UUID,
        turn_id: UUID,
        question: str,
        draft: str,
        **kwargs,
    ) -> object:
        self.queries.append({
            "id": self.next_query_id,
            "vip_id": vip_id,
            "turn_id": turn_id,
            "question": question,
            "draft": draft,
            "chat_id": kwargs.get("chat_id"),
            "business_connection_id": kwargs.get("business_connection_id"),
        })
        # Return a simple object matching GrayZoneQueryView protocol (id: UUID).
        return type("_Query", (), {"id": self.next_query_id})()

    async def get_open_query_by_chat_id(self, chat_id: int) -> object | None:
        return self._existing_chat_query

    async def discard_and_close(self, query_id: UUID) -> object:
        self.discarded.append(query_id)
        self.queries = [q for q in self.queries if q.get("id") != query_id]
        return type("_Query", (), {"id": query_id, "vip_id": None})()


class _FakeTraceReader:
    """Fixed pipeline trace for REQ-ATN-12 payment detection tests."""

    def __init__(self, trace: dict | None, *, error: bool = False) -> None:
        self._trace = trace
        self._error = error

    async def get_full_trace(self, turn_id: UUID) -> dict | None:
        if self._error:
            raise RuntimeError("trace down")
        return self._trace


def _build(
    director: object,
    *,
    learning: RecordingLearning | None = None,
    gray_zone: FakeGrayZone | None = None,
    feature_gray_zone_enabled: bool = False,
    feature_general_mode_enabled: bool = False,
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
    daily_limit: object | None = None,
    turns: InMemoryTurnStore | None = None,
    persona_catalog_provider: object | None = None,
    trace_reader: object | None = None,
    atencion_cycles: object | None = None,
    memory_extraction: object | None = None,
    emotional_detector: object | None = None,
    emotional_signal_log: object | None = None,
    profile_synthesis_trigger: object | None = None,
    turn_classifier: object | None = None,
    turn_category_log: object | None = None,
    mood_engine: object | None = None,
    vip_mood_state: object | None = None,
) -> dict:
    turns = turns or InMemoryTurnStore()
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
    coordinator = TurnCoordinator(
        turns,
        approvals,
        behavior,  # type: ignore[arg-type]
        approval_ui=ApprovalDraftVoider(notifier),
    )
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
        feature_general_mode_enabled=feature_general_mode_enabled,
        behavior=behavior if wire_autonomous else None,  # type: ignore[arg-type]
        autonomous_mode=ams,
        vip_store=vips if wire_autonomous else None,
        traces=traces if wire_autonomous else None,
        delivery_mode=delivery_mode,  # type: ignore[arg-type]
        feature_advanced_behavior=feature_advanced_behavior,
        delay_policy=delay_policy,
        daily_message_limit_store=daily_limit,
        turns=turns,
        persona_catalog_provider=persona_catalog_provider,
        trace_reader=trace_reader,
        atencion_cycles=atencion_cycles,
        memory_extraction=memory_extraction,
        emotional_detector=emotional_detector,
        emotional_signal_log=emotional_signal_log,
        profile_synthesis_trigger=profile_synthesis_trigger,
        turn_classifier=turn_classifier,
        turn_category_log=turn_category_log,
        mood_engine=mood_engine,
        vip_mood_state=vip_mood_state,
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
        "atencion_cycles": atencion_cycles,
        "emotional_detector": emotional_detector,
        "emotional_signal_log": emotional_signal_log,
        "profile_synthesis_trigger": profile_synthesis_trigger,
        "turn_classifier": turn_classifier,
        "turn_category_log": turn_category_log,
        "mood_engine": mood_engine,
        "vip_mood_state": vip_mood_state,
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
async def test_supersede_coalesces_open_vip_burst_into_director_turn() -> None:
    """Latest turn cancels prior; Director receives all open VIP msgs in that round."""
    decision = Decision(
        action="approve",
        reason="good",
        evaluation=_eval(),
        draft_text="draft for both",
    )
    g = _build(FakeDirector(decision))
    a = await g["orch"].handle_vip_message(
        _vip(text="primer mensaje", telegram_message_id=101)
    )
    b = await g["orch"].handle_vip_message(
        _vip(text="segundo mensaje", telegram_message_id=102)
    )
    assert a != b
    # First pipeline still ran (pre-coalesce cost); second sees full open burst.
    assert len(g["director"].calls) == 2
    first = g["director"].calls[0]
    second = g["director"].calls[1]
    assert first.text == "primer mensaje"
    assert "primer mensaje" in second.text
    assert "segundo mensaje" in second.text
    assert second.telegram_message_id == 102
    # Single-message turns stay plain (no multi-header on first).
    assert "varios mensajes" not in first.text.lower()


@pytest.mark.asyncio
async def test_vip_edit_replaces_history_and_cancels_prior_turn() -> None:
    """Edited message: only latest text in history; prior pipeline cancelled."""
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="reply to edit",
    )
    g = _build(
        FakeDirector(decision),
        delay_policy=FixedDelayPolicy(initial=0.08),
    )
    # Original message starts pre-delay pipeline.
    t1 = asyncio.create_task(
        g["orch"].handle_vip_message(
            _vip(text="texto original", telegram_message_id=9001)
        )
    )
    await asyncio.sleep(0.02)
    # Edit same message_id → cancels t1 epoch, upserts history.
    t2 = asyncio.create_task(
        g["orch"].handle_vip_message(
            _vip(
                text="texto editado final",
                telegram_message_id=9001,
                is_edit=True,
            )
        )
    )
    await asyncio.gather(t1, t2)

    recent = await g["history"].get_recent(100, limit=20)
    vip_rows = [r for r in recent if r.get("telegram_message_id") == 9001]
    assert len(vip_rows) == 1
    assert vip_rows[0]["text"] == "texto editado final"
    # Model only processes the winning epoch (latest edit).
    assert len(g["director"].calls) == 1
    assert "texto editado final" in g["director"].calls[0].text
    assert "texto original" not in g["director"].calls[0].text


@pytest.mark.asyncio
async def test_single_vip_message_turn_text_unchanged() -> None:
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="d",
    )
    g = _build(FakeDirector(decision))
    await g["orch"].handle_vip_message(_vip(text="solo uno", telegram_message_id=55))
    assert g["director"].calls[0].text == "solo uno"


@pytest.mark.asyncio
async def test_vip_burst_stops_at_owner_reply() -> None:
    """Coalesce only trailing VIP lines after last owner message."""
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="d",
    )
    g = _build(FakeDirector(decision))
    # Prior answered exchange in durable history.
    await g["history"].append(100, role="vip", text="ayer te escribí", telegram_message_id=1)
    await g["history"].append(100, role="owner", text="hola de ayer", telegram_message_id=2)
    await g["orch"].handle_vip_message(
        _vip(text="msg nuevo A", telegram_message_id=201)
    )
    await g["orch"].handle_vip_message(
        _vip(text="msg nuevo B", telegram_message_id=202)
    )
    second = g["director"].calls[1]
    assert "msg nuevo A" in second.text
    assert "msg nuevo B" in second.text
    assert "ayer te escribí" not in second.text


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


# ── F5 Pool 3: post-turn memory extraction composition (best-effort) ──────


@pytest.mark.asyncio
async def test_post_turn_memory_extraction_called_on_terminal_turn() -> None:
    """Autonomous DELIVERED turn → _maybe_post_turn runs LearningService AND
    the memory extraction (both composed; run_post_turn untouched)."""
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="auto reply",
    )
    extraction = RecordingExtraction()
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        delivery_mode="autonomous",
        memory_extraction=extraction,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=uuid4()))
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "delivered"
    # Both run: Learning first, extraction after (same _maybe_post_turn).
    assert g["learning"].calls == [turn_id]
    assert extraction.calls == [(turn_id, 100)]


@pytest.mark.asyncio
async def test_post_turn_memory_extraction_not_called_when_none() -> None:
    """Default wiring (memory_extraction=None) → extraction never invoked;
    the pre-Pool 3 behavior (learning only) stays byte-identical."""
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
    assert g["orch"]._memory_extraction is None  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=uuid4()))
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "delivered"
    assert g["learning"].calls == [turn_id]


@pytest.mark.asyncio
async def test_post_turn_memory_extraction_error_does_not_break_turn() -> None:
    """R1: an extraction failure is swallowed (log_swallowed) — the already
    delivered turn completes and LearningService still ran."""
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="auto reply",
    )
    extraction = RecordingExtraction(raise_on_call=True)
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        delivery_mode="autonomous",
        memory_extraction=extraction,
    )
    # Must NOT raise despite the extractor blowing up.
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=uuid4()))
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "delivered"
    assert g["learning"].calls == [turn_id]
    assert g["actuator"].send_count() >= 1


@pytest.mark.asyncio
async def test_post_turn_memory_extraction_skipped_on_sandbox() -> None:
    """The sandbox gate in _maybe_post_turn cuts BEFORE both run_post_turn
    and the extraction (same guard, no extra logic — A1)."""
    from diana.application.sandbox import SandboxService

    # inline six-profile catalog (same fixture as test_sandbox_skips_learning_post_turn)
    MINIMAL_SIX = {
        "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
        "cercano": {
            "label": "VIP cercano",
            "description": "",
            "facts": {"name": "Mateo", "personality": "confiado"},
            "notes": [{"date": "2026-05-10", "text": "Le gusta el trato cercano"}],
        },
        "distante": {
            "label": "VIP reservado",
            "description": "",
            "facts": {"personality": "formal"},
            "notes": [],
        },
        "intenso": {
            "label": "VIP emocional",
            "description": "",
            "facts": {"relationship": "recién separado"},
            "notes": [],
        },
        "vip_largo": {
            "label": "VIP largo",
            "description": "",
            "facts": {"name": "Sofía"},
            "notes": [],
        },
        "inyeccion_previa": {
            "label": "Fixture adversarial",
            "description": "",
            "facts": {"name": "TestUser"},
            "notes": [],
        },
    }
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="draft",
    )
    learn = RecordingLearning()
    extraction = RecordingExtraction()
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    sandbox.activate(100, "nuevo")
    g = _build(
        FakeDirector(decision),
        learning=learn,
        memory_extraction=extraction,
    )
    g["orch"]._sandbox = sandbox  # noqa: SLF001
    await g["orch"].handle_vip_message(_vip(chat_id=100))
    assert learn.calls == []
    assert extraction.calls == []


@pytest.mark.asyncio
async def test_autonomous_finalize_appends_owner_history() -> None:
    """H7.2: autonomous DELIVERED writes vip inbound then owner outbound history."""
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
    chat_id = 100
    turn_id = await g["orch"].handle_vip_message(
        _vip(chat_id=chat_id, vip_id=uuid4(), text="hola diana")
    )
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "delivered"
    rows = await g["history"].get_recent(chat_id)
    roles = [r["role"] for r in rows]
    assert "vip" in roles
    assert "owner" in roles
    vip_idx = next(i for i, r in enumerate(rows) if r["role"] == "vip")
    owner_idx = next(i for i, r in enumerate(rows) if r["role"] == "owner")
    assert vip_idx < owner_idx
    assert rows[owner_idx]["text"] == "auto reply"


@pytest.mark.asyncio
async def test_autonomous_no_owner_history_on_frozen_or_fail() -> None:
    """H7.2: freeze-after-prepare fail path must not append owner history."""
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="race freeze",
    )
    store = InMemoryVipStore()
    vip = await store.add(5201)
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        delivery_mode="autonomous",
        vip_store=store,
    )
    calls = {"n": 0}
    real_is_frozen = g["orch"]._is_vip_frozen  # noqa: SLF001

    async def freeze_on_second_check(vip_id: UUID | None) -> bool:
        calls["n"] += 1
        if calls["n"] >= 2:
            return True
        return await real_is_frozen(vip_id)

    g["orch"]._is_vip_frozen = freeze_on_second_check  # noqa: SLF001
    chat_id = 100
    turn_id = await g["orch"].handle_vip_message(_vip(chat_id=chat_id, vip_id=vip.id))
    stored = await g["turns"].get(turn_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error == "vip_frozen"
    rows = await g["history"].get_recent(chat_id)
    assert any(r.get("role") == "vip" for r in rows)
    assert not any(r.get("role") == "owner" for r in rows)


@pytest.mark.asyncio
async def test_autonomous_sandbox_skips_owner_history() -> None:
    """Sandbox active: autonomous DELIVERED leaves no durable vip or owner history."""
    from diana.application.sandbox import SandboxService

    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="sandbox auto reply",
    )
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        delivery_mode="autonomous",
    )
    # Minimal catalog matching other sandbox orch tests.
    MINIMAL_SIX = {
        "nuevo": {"label": "n", "description": "", "facts": {}, "notes": []},
        "cercano": {"label": "c", "description": "", "facts": {}, "notes": []},
        "distante": {"label": "d", "description": "", "facts": {}, "notes": []},
        "intenso": {"label": "i", "description": "", "facts": {}, "notes": []},
        "vip_largo": {"label": "v", "description": "", "facts": {}, "notes": []},
        "inyeccion_previa": {
            "label": "x",
            "description": "",
            "facts": {},
            "notes": [],
        },
    }
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    chat_id = 100
    sandbox.activate(chat_id, "nuevo")
    g["orch"]._sandbox = sandbox  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(
        _vip(chat_id=chat_id, vip_id=uuid4(), text="hola diana")
    )
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "delivered"
    rows = await g["history"].get_recent(chat_id)
    # Sandbox product isolation: no durable vip inbound and no owner outbound.
    assert not any(r.get("role") == "vip" for r in rows)
    assert not any(r.get("role") == "owner" for r in rows)


@pytest.mark.asyncio
async def test_sandbox_skips_vip_inbound_history(caplog: pytest.LogCaptureFixture) -> None:
    """Sandbox active (supervised): VIP inbound must not append durable history."""
    import logging

    from diana.application.sandbox import SandboxService

    decision = Decision(
        action="approve",
        reason="supervised",
        evaluation=_eval(),
        draft_text="pending for owner",
    )
    g = _build(FakeDirector(decision))
    MINIMAL_SIX = {
        "nuevo": {"label": "n", "description": "", "facts": {}, "notes": []},
        "cercano": {"label": "c", "description": "", "facts": {}, "notes": []},
        "distante": {"label": "d", "description": "", "facts": {}, "notes": []},
        "intenso": {"label": "i", "description": "", "facts": {}, "notes": []},
        "vip_largo": {"label": "v", "description": "", "facts": {}, "notes": []},
        "inyeccion_previa": {
            "label": "x",
            "description": "",
            "facts": {},
            "notes": [],
        },
    }
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    chat_id = 100
    sandbox.activate(chat_id, "nuevo")
    g["orch"]._sandbox = sandbox  # noqa: SLF001
    with caplog.at_level(logging.INFO, logger="diana.application"):
        turn_id = await g["orch"].handle_vip_message(
            _vip(chat_id=chat_id, vip_id=uuid4(), text="hola sandbox")
        )
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"
    rows = await g["history"].get_recent(chat_id)
    assert not any(r.get("role") == "vip" for r in rows)
    assert any(
        "vip_history_skipped_sandbox" in r.message for r in caplog.records
    )


class _MultiMidDeliverer:
    """Spy BehaviorDeliverer returning multi-segment DeliveryResult."""

    def __init__(
        self,
        *,
        message_ids: list[int] | None = None,
        texts: list[str] | None = None,
    ) -> None:
        from diana.application.ports import DeliveryResult

        self.message_ids = message_ids if message_ids is not None else [10, 11, 12]
        self.segment_texts = (
            texts if texts is not None else ["seg-a", "seg-b", "seg-c"]
        )
        self.ctxs: list = []
        self._DeliveryResult = DeliveryResult

    async def deliver(
        self,
        texts: list[str],
        ctx: object,
        turn_id: UUID,
        decision: object | None = None,
    ) -> object:
        self.ctxs.append(ctx)
        return self._DeliveryResult(
            success=True,
            message_ids=list(self.message_ids),
            texts=list(self.segment_texts),
        )


@pytest.mark.asyncio
async def test_autonomous_multi_message_ids_appends_all_owner_history() -> None:
    """Autonomous multi-segment deliver writes one owner row per message_id."""
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="auto full draft",
    )
    spy = _MultiMidDeliverer(
        message_ids=[10, 11, 12],
        texts=["seg-a", "seg-b", "seg-c"],
    )
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        delivery_mode="autonomous",
        behavior_override=spy,
    )
    chat_id = 100
    turn_id = await g["orch"].handle_vip_message(
        _vip(chat_id=chat_id, vip_id=uuid4(), text="hola diana")
    )
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "delivered"
    rows = await g["history"].get_recent(chat_id)
    roles = [r["role"] for r in rows]
    assert "vip" in roles
    owner_rows = [r for r in rows if r.get("role") == "owner"]
    assert len(owner_rows) == 3
    assert [r["text"] for r in owner_rows] == ["seg-a", "seg-b", "seg-c"]
    assert [r["telegram_message_id"] for r in owner_rows] == [10, 11, 12]
    vip_idx = next(i for i, r in enumerate(rows) if r["role"] == "vip")
    first_owner_idx = next(i for i, r in enumerate(rows) if r["role"] == "owner")
    assert vip_idx < first_owner_idx


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
            parse_mode: str | None = None,
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
    """With pre-pipeline delay, concurrent messages complete independently.

    The pre-send delay now runs BEFORE the lock in handle_vip_message,
    so both tasks sleep concurrently. The first to wake enters the lock,
    pipelines, and delivers. The second follows after. Neither supersedes
    the other because delivery is instant (skip_initial_delay=True).
    """
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
    )
    vip_id = uuid4()
    first = asyncio.create_task(
        g["orch"].handle_vip_message(
            _vip(text="msg A", telegram_message_id=11, vip_id=vip_id)
        )
    )
    await asyncio.sleep(0.02)
    second = asyncio.create_task(
        g["orch"].handle_vip_message(
            _vip(text="msg B", telegram_message_id=12, vip_id=vip_id)
        )
    )
    turn_a, turn_b = await asyncio.gather(first, second)
    stored_a = await g["turns"].get(turn_a)
    assert stored_a is not None
    # Both complete — pre-pipeline delay runs concurrently outside the lock.
    stored_b = await g["turns"].get(turn_b)
    assert stored_b is not None
    # At least B delivered; A may be delivered or superseded depending on timing.
    assert stored_b.status == "delivered"


@pytest.mark.asyncio
async def test_director_exception_marks_failed_and_reraises() -> None:
    g = _build(FakeDirector(RuntimeError("llm down")))
    with pytest.raises(RuntimeError, match="llm down"):
        await g["orch"].handle_vip_message(_vip())
    non_term = await g["turns"].list_non_terminal(100)
    assert non_term == []
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
    # Director never returned; turn was minted before fail.
    assert g["actuator"].send_count() == 0
    # R4: the bare-except mark-failed-then-raise site fires the post-turn hook
    # in a finally — the FAILED (extractable) turn still runs learning + memory
    # extraction exactly once, despite the re-raise.
    assert g["learning"].calls == [failed_ids[0]]
    # Generic director errors do not use the Analyst schema-fail notify path.
    assert g["notifier"].infos == []


@pytest.mark.asyncio
async def test_missing_bc_marks_failed_and_fires_post_turn_hook() -> None:
    """R4: the bc-None mark-failed-then-raise site fires the post-turn hook in
    a finally — the FAILED (extractable) turn is extracted exactly once despite
    the re-raise (previously the hook was stranded: the path never reached the
    normal hook site)."""
    g = _build(FakeDirector(Decision(action="approve", reason="ok", evaluation=_eval())))
    with pytest.raises(ValueError, match="business_connection_id is required"):
        await g["orch"].handle_vip_message(_vip(business_connection_id=None))
    failed_ids = [
        t.id
        for t in g["turns"]._turns.values()  # noqa: SLF001 — test assertion
        if t.chat_id == 100
    ]
    assert len(failed_ids) == 1
    failed = await g["turns"].get(failed_ids[0])
    assert failed is not None and failed.status == "failed"
    assert g["learning"].calls == [failed_ids[0]]


@pytest.mark.asyncio
async def test_unexpected_f2_action_marks_failed_and_fires_post_turn_hook() -> None:
    """R4: the unexpected-F2 mark-failed-then-raise site fires the post-turn hook
    in a finally — the FAILED (extractable) turn is extracted exactly once
    despite the re-raise."""
    # ``Decision.action`` is a Pydantic Literal — build without validation so
    # the orchestrator sees the unexpected-F2 failure path at runtime.
    decision = Decision.model_construct(
        action="bogus",
        reason="?",
        evaluation=_eval(),
        draft_text="x",
    )
    g = _build(FakeDirector(decision))
    with pytest.raises(ValueError, match="unexpected F2 action"):
        await g["orch"].handle_vip_message(_vip())
    failed_ids = [
        t.id
        for t in g["turns"]._turns.values()  # noqa: SLF001 — test assertion
        if t.chat_id == 100
    ]
    assert len(failed_ids) == 1
    failed = await g["turns"].get(failed_ids[0])
    assert failed is not None and failed.status == "failed"
    assert g["learning"].calls == [failed_ids[0]]


@pytest.mark.asyncio
async def test_escalate_persist_then_raise_still_fires_hook() -> None:
    """R4: an ESCALATED transition inside ``_apply_decision_after_director``
    that persists then raises must still fire the post-turn hook — the
    except-on-exception fires it (read-back gated) before re-raising, and the
    ESCALATED turn is extracted exactly once."""
    decision = Decision(
        action="escalate",
        reason="direct",
        evaluation=_eval(),
        draft_text="",
    )
    store = _PersistThenRaiseStore()
    store.arm = True
    g = _build(FakeDirector(decision), turns=store)
    with pytest.raises(RuntimeError, match="simulated persist-then-raise"):
        await g["orch"].handle_vip_message(_vip())
    escalated_ids = [
        t.id for t in store._turns.values() if t.status == "escalated"  # noqa: SLF001
    ]
    assert len(escalated_ids) == 1
    assert g["learning"].calls == escalated_ids


@pytest.mark.asyncio
async def test_autonomous_finalize_persist_then_raise_still_fires_hook() -> None:
    """R4: a DELIVERED transition inside ``_finalize_autonomous_delivery`` that
    persists then raises must still fire the post-turn hook — the caller's
    ``finally`` (keyed on the mutable holder set before the transition) fires it
    OUTSIDE the chat lock, and the DELIVERED turn is extracted exactly once."""
    spy = _CapturingDeliverer()
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="auto reply",
    )
    store = _PersistThenRaiseStore()
    store.arm = True
    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        delivery_mode="autonomous",
        behavior_override=spy,
        turns=store,
    )
    with pytest.raises(RuntimeError, match="simulated persist-then-raise"):
        await g["orch"].handle_vip_message(_vip(vip_id=uuid4()))
    delivered_ids = [
        t.id for t in store._turns.values() if t.status == "delivered"  # noqa: SLF001
    ]
    assert len(delivered_ids) == 1
    assert g["learning"].calls == delivered_ids


# --- Item4 Task4: advanced behavior builder wiring ---


class _CapturingDeliverer:
    """Spy BehaviorDeliverer that records DeliveryContext on deliver."""

    def __init__(self) -> None:
        self.ctxs: list = []
        self.texts: list[list[str]] = []
        self.turn_ids: list[UUID] = []
        self.decisions: list = []

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
        self.turn_ids.append(turn_id)
        self.decisions.append(decision)
        return DeliveryResult(success=True, message_ids=[1])


class _PersistThenRaiseStore(InMemoryTurnStore):
    """R4 fault injection: persists a terminal transition, then raises.

    Mirrors a store that commits the row then loses the connection — the turn
    is already terminal (the read-back gate in the post-turn hook sees
    DELIVERED / FAILED / ESCALATED), but the transition call raised, so the
    happy-path hook site would be skipped without the R4 fix.
    """

    def __init__(self) -> None:
        super().__init__()
        self.arm: bool = False
        self._disarmed: bool = False

    async def transition(
        self,
        turn_id: UUID,
        status: object,
        *,
        superseded_by: UUID | None = None,
        error: str | None = None,
    ) -> TurnRecord:
        result = await super().transition(  # type: ignore[arg-type]
            turn_id,
            status,  # type: ignore[arg-type]
            superseded_by=superseded_by,
            error=error,
        )
        if self.arm and not self._disarmed and is_turn_status_terminal(result.status):
            self._disarmed = True
            raise RuntimeError("simulated persist-then-raise")
        return result


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

    turn_id = await orch.handle_vip_message(_vip(text="schema-fail-msg"))
    failed = await turns.get(turn_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "analista_schema_invalido"

    assert actuator.send_count() == 0
    # Soft-handled: post-turn still runs (trace completeness); no VIP send.
    assert learn.calls == [turn_id]
    assert len(notifier.infos) == 1
    assert notifier.drafts == []
    assert notifier.escalations == []
    info_text, _info_chat = notifier.infos[0]
    assert "analista_schema_invalido" in info_text
    assert str(turn_id) in info_text


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

    turn_id = await orch.handle_vip_message(_vip(text="eval-schema-fail-msg"))
    failed = await turns.get(turn_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "evaluador_schema_invalido"

    assert actuator.send_count() == 0
    assert learn.calls == [turn_id]
    assert len(notifier.infos) == 1
    assert notifier.drafts == []
    assert notifier.escalations == []
    info_text, _info_chat = notifier.infos[0]
    assert "evaluador_schema_invalido" in info_text
    assert str(turn_id) in info_text


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

    turn_id = await orch.handle_vip_message(_vip(text="size-fail-msg"))
    failed = await turns.get(turn_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "contexto_excede_limite"

    assert actuator.send_count() == 0
    assert learn.calls == [turn_id]
    assert len(notifier.infos) == 1
    assert notifier.drafts == []
    assert notifier.escalations == []
    info_text, _info_chat = notifier.infos[0]
    assert "contexto_excede_limite" in info_text
    assert str(turn_id) in info_text


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

    turn_id = await orch.handle_vip_message(_vip(text="gen-empty-fail-msg"))
    failed = await turns.get(turn_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "generador_salida_vacia"

    assert actuator.send_count() == 0
    assert learn.calls == [turn_id]
    assert len(notifier.infos) == 1
    assert notifier.drafts == []
    assert notifier.escalations == []
    info_text, _info_chat = notifier.infos[0]
    assert "generador_salida_vacia" in info_text
    assert str(turn_id) in info_text
    # No pending approval / empty draft in approval queue.
    assert await approvals.get_by_turn(turn_id) is None
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
    # Older turn must not be pending_approval if superseded / cancelled by newer VIP
    for tid in (a_id, b_id):
        rec = await g["turns"].get(tid)
        assert rec is not None
        if rec.status == "superseded":
            # cannot have waiting approval on superseded
            appr = await g["approvals"].get_by_turn(tid)
            if appr is not None:
                assert appr.status != "waiting"
        elif rec.status == "pending_approval":
            assert non_term[0].id == tid

    # Winner answers the full open burst (A + B), not only the last text.
    assert len(slow.calls) >= 1
    winner_texts = [c.text for c in slow.calls]
    assert any("msg A" in t and "msg B" in t for t in winner_texts) or any(
        t == "msg B" for t in winner_texts
    )
    # At most one waiting approval (the live turn).
    waiting = await g["approvals"].list_waiting()
    assert len(waiting) == 1

    # Approving the superseded turn never sends
    for tid in (a_id, b_id):
        rec = await g["turns"].get(tid)
        if rec is not None and rec.status == "superseded":
            result = await g["admin"].handle_approve(tid, actor_id=OWNER_ID)
            assert result is None
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_newer_vip_aborts_older_before_director_during_pre_delay() -> None:
    """During human delay, a second VIP msg supersedes the first real turn."""
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="only for latest",
    )
    g = _build(
        FakeDirector(decision),
        delay_policy=FixedDelayPolicy(initial=0.08),
    )
    t1 = asyncio.create_task(
        g["orch"].handle_vip_message(
            _vip(text="primero", telegram_message_id=301)
        )
    )
    await asyncio.sleep(0.02)
    t2 = asyncio.create_task(
        g["orch"].handle_vip_message(
            _vip(text="segundo", telegram_message_id=302)
        )
    )
    id1, id2 = await asyncio.gather(t1, t2)

    # Both returns are durable turn rows (mint-before-delay).
    rec1 = await g["turns"].get(id1)
    rec2 = await g["turns"].get(id2)
    assert rec1 is not None
    assert rec2 is not None
    assert rec1.status == "superseded"
    assert rec1.superseded_by == id2

    assert len(g["director"].calls) == 1
    only = g["director"].calls[0]
    assert only.turn_id == id2
    assert "primero" in only.text
    assert "segundo" in only.text
    waiting = await g["approvals"].list_waiting()
    assert len(waiting) == 1
    live = waiting[0]
    assert live.turn_id == only.turn_id == id2
    assert g["learning"].calls == [id2]


@pytest.mark.asyncio
async def test_stale_epoch_skips_mint_does_not_supersede_winner() -> None:
    """Stale epoch under mint lock skips begin_turn (no supersede of winner)."""
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="winner only",
    )
    g = _build(
        FakeDirector(decision),
        delay_policy=FixedDelayPolicy(initial=0.0),
    )
    # Stall A after bump, before mint lock, so B can mint with a newer epoch.
    a_pre_mint = asyncio.Event()
    a_may_mint = asyncio.Event()
    b_minted = asyncio.Event()
    orig_append = g["orch"]._append_vip_history_if_persist
    orig_mint = g["orch"]._mint_turn_for_inbound

    async def stall_a_pre_mint(incoming):  # type: ignore[no-untyped-def]
        if incoming.telegram_message_id == 601:
            a_pre_mint.set()
            await a_may_mint.wait()
        return await orig_append(incoming)

    async def mint_and_signal(incoming, vip_epoch, *, before_inbound):  # type: ignore[no-untyped-def]
        result = await orig_mint(
            incoming, vip_epoch, before_inbound=before_inbound
        )
        if incoming.telegram_message_id == 602:
            b_minted.set()
        return result

    g["orch"]._append_vip_history_if_persist = stall_a_pre_mint  # type: ignore[method-assign]
    g["orch"]._mint_turn_for_inbound = mint_and_signal  # type: ignore[method-assign]

    t_a = asyncio.create_task(
        g["orch"].handle_vip_message(
            _vip(text="primero", telegram_message_id=601)
        )
    )
    await asyncio.wait_for(a_pre_mint.wait(), timeout=2.0)
    # A has epoch 1 and is blocked pre-mint; B bumps to 2 and mints first.
    t_b = asyncio.create_task(
        g["orch"].handle_vip_message(
            _vip(text="segundo", telegram_message_id=602)
        )
    )
    await asyncio.wait_for(b_minted.wait(), timeout=2.0)
    # B already holds the live turn; release A so it hits stale-epoch skip.
    a_may_mint.set()
    id_a, id_b = await asyncio.wait_for(asyncio.gather(t_a, t_b), timeout=3.0)

    # A skipped mint → returns winner id (B), no separate superseded A row.
    assert id_a == id_b
    rec_b = await g["turns"].get(id_b)
    assert rec_b is not None
    assert rec_b.status == "pending_approval"
    assert rec_b.superseded_by is None
    assert len(g["director"].calls) == 1
    assert g["director"].calls[0].turn_id == id_b
    non_term = await g["turns"].list_non_terminal(100)
    assert len(non_term) == 1
    assert non_term[0].id == id_b


@pytest.mark.asyncio
async def test_owner_cancel_during_pre_delay_supersedes_real_turn() -> None:
    """Owner business traffic during human wait supersedes the minted turn."""
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="should not reach approval",
    )
    g = _build(
        FakeDirector(decision),
        delay_policy=FixedDelayPolicy(initial=0.08),
    )
    chat_id = 100
    vip_task = asyncio.create_task(
        g["orch"].handle_vip_message(
            _vip(chat_id=chat_id, text="vip waiting", telegram_message_id=401)
        )
    )
    await asyncio.sleep(0.02)
    # Same path OwnerDetectionMiddleware uses: mark flag + coordinate(owner).
    g["coordinator"].mark_owner_intervened(chat_id)
    await g["coordinator"].coordinate(chat_id, "owner")
    turn_id = await vip_task

    rec = await g["turns"].get(turn_id)
    assert rec is not None
    assert rec.status == "superseded"
    assert len(g["director"].calls) == 0
    assert await g["approvals"].list_waiting() == []
    assert g["actuator"].send_count() == 0
    assert g["learning"].calls == []


@pytest.mark.asyncio
async def test_owner_flag_mid_director_no_draft_clean_abort() -> None:
    """A2: owner intervenes while Director runs → no draft, no raise, superseded."""
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="must not notify",
    )
    slow = SlowDirector(decision, delay=0.12)
    g = _build(slow, delay_policy=FixedDelayPolicy(initial=0.0))
    chat_id = 100
    vip_task = asyncio.create_task(
        g["orch"].handle_vip_message(
            _vip(chat_id=chat_id, text="vip gen", telegram_message_id=501)
        )
    )
    await slow.started.wait()
    # Flag only (coordinate would wait on chat_scope held by VIP path).
    g["coordinator"].mark_owner_intervened(chat_id)
    turn_id = await vip_task

    rec = await g["turns"].get(turn_id)
    assert rec is not None
    assert rec.status == "superseded"
    assert len(g["notifier"].drafts) == 0
    assert await g["approvals"].list_waiting() == []
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_owner_during_pre_mint_await_aborts_before_director() -> None:
    """Owner mark+coordinate while VIP is still in pre-mint await → 0 Director."""
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="should not run",
    )
    g = _build(
        FakeDirector(decision),
        delay_policy=FixedDelayPolicy(initial=0.0),
    )
    chat_id = 100
    history_entered = asyncio.Event()
    history_release = asyncio.Event()
    orig_append = g["orch"]._append_vip_history_if_persist

    async def slow_history(incoming):  # type: ignore[no-untyped-def]
        history_entered.set()
        await history_release.wait()
        return await orig_append(incoming)

    g["orch"]._append_vip_history_if_persist = slow_history  # type: ignore[method-assign]

    vip_task = asyncio.create_task(
        g["orch"].handle_vip_message(
            _vip(chat_id=chat_id, text="vip pre-mint", telegram_message_id=701)
        )
    )
    await history_entered.wait()
    # No turn yet — owner coordinate must keep the flag for mint.
    g["coordinator"].mark_owner_intervened(chat_id)
    await g["coordinator"].coordinate(chat_id, "owner")
    assert g["coordinator"].is_owner_intervened(chat_id) is True
    history_release.set()
    turn_id = await vip_task

    rec = await g["turns"].get(turn_id)
    assert rec is not None
    assert rec.status == "superseded"
    assert len(g["director"].calls) == 0
    assert await g["approvals"].list_waiting() == []
    assert g["learning"].calls == []
    assert g["actuator"].send_count() == 0


async def _wait_for_waiting_delay_turn(
    turns: object, chat_id: int, *, timeout: float = 2.0
) -> UUID:
    """Poll until a non-terminal waiting_delay turn exists for chat_id."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        non_term = await turns.list_non_terminal(chat_id)  # type: ignore[attr-defined]
        for rec in non_term:
            if rec.status == "waiting_delay":
                return rec.id
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(
                f"no waiting_delay turn for chat_id={chat_id} within {timeout}s"
            )
        await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_owner_supersede_vip1_still_aborts_vip2_pre_mint() -> None:
    """VIP1 live + owner coordinate must not clear flag for VIP2 pre-mint."""
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="should not draft for vip2",
    )
    g = _build(
        FakeDirector(decision),
        delay_policy=FixedDelayPolicy(initial=0.15),
    )
    chat_id = 100

    # VIP1 mints and enters human delay.
    t1 = asyncio.create_task(
        g["orch"].handle_vip_message(
            _vip(chat_id=chat_id, text="vip1 live", telegram_message_id=801)
        )
    )
    vip1_id = await _wait_for_waiting_delay_turn(g["turns"], chat_id)

    # VIP2 stalls in history (pre-mint) while VIP1 is still live.
    history_entered = asyncio.Event()
    history_release = asyncio.Event()
    orig_append = g["orch"]._append_vip_history_if_persist

    async def slow_vip2_history(incoming):  # type: ignore[no-untyped-def]
        if incoming.telegram_message_id == 802:
            history_entered.set()
            await history_release.wait()
        return await orig_append(incoming)

    g["orch"]._append_vip_history_if_persist = slow_vip2_history  # type: ignore[method-assign]

    t2 = asyncio.create_task(
        g["orch"].handle_vip_message(
            _vip(chat_id=chat_id, text="vip2 pre-mint", telegram_message_id=802)
        )
    )
    await asyncio.wait_for(history_entered.wait(), timeout=2.0)

    # Owner supersedes VIP1 (prior non-empty) — flag must remain for VIP2 mint.
    g["coordinator"].mark_owner_intervened(chat_id)
    await g["coordinator"].coordinate(chat_id, "owner")
    assert g["coordinator"].is_owner_intervened(chat_id) is True
    rec1 = await g["turns"].get(vip1_id)
    assert rec1 is not None
    assert rec1.status == "superseded"

    history_release.set()
    id1, id2 = await asyncio.wait_for(asyncio.gather(t1, t2), timeout=3.0)

    rec2 = await g["turns"].get(id2)
    assert rec2 is not None
    assert rec2.status == "superseded"
    # VIP2 must not produce a waiting approval or Director call on its turn.
    waiting = await g["approvals"].list_waiting()
    assert waiting == []
    assert all(c.turn_id != id2 for c in g["director"].calls)
    assert id2 not in g["learning"].calls
    _ = id1


@pytest.mark.asyncio
async def test_autonomous_owner_during_pre_delay_no_send() -> None:
    """Autonomous VIP: owner during wait → 0 actuator sends, turn superseded."""
    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="would have auto-sent",
    )
    g = _build(
        FakeDirector(decision),
        delay_policy=FixedDelayPolicy(initial=0.08),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
    )
    chat_id = 100
    vip_task = asyncio.create_task(
        g["orch"].handle_vip_message(
            _vip(chat_id=chat_id, text="auto vip", telegram_message_id=501)
        )
    )
    await asyncio.sleep(0.02)
    g["coordinator"].mark_owner_intervened(chat_id)
    await g["coordinator"].coordinate(chat_id, "owner")
    turn_id = await vip_task

    rec = await g["turns"].get(turn_id)
    assert rec is not None
    assert rec.status == "superseded"
    assert len(g["director"].calls) == 0
    assert g["actuator"].send_count() == 0
    assert await g["approvals"].list_waiting() == []
    assert g["learning"].calls == []


@pytest.mark.asyncio
async def test_pre_delay_persists_channel_type() -> None:
    """B4: the pre-delay timer payload carries the incoming channel_type so a
    restart can resume the atencion turn on the atencion channel."""
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="draft",
    )
    timers = InMemoryRuntimeTimerStore()
    g = _build(
        FakeDirector(decision),
        delay_policy=FixedDelayPolicy(initial=0.001),
    )
    g["orch"]._runtime_timers = timers  # noqa: SLF001
    await g["orch"].handle_vip_message(
        _vip(channel_type="atencion", text="hola atencion")
    )
    # The pre-delay timer is persisted at mint time and marked completed after
    # the (tiny) delay; the in-memory store keeps the record with its payload.
    assert len(timers._timers) == 1  # noqa: SLF001
    payload = next(iter(timers._timers.values())).payload  # noqa: SLF001
    assert payload["incoming"]["channel_type"] == "atencion"


@pytest.mark.asyncio
async def test_autonomous_prepare_sets_skip_initial_delay() -> None:
    """Post-delay autonomous deliver must skip BehaviorEngine initial delay."""
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
        global_mode="autonomous",
        delivery_mode="autonomous",
        behavior_override=spy,
        delay_policy=FixedDelayPolicy(initial=0.0),
    )
    await g["orch"].handle_vip_message(_vip(vip_id=uuid4()))
    assert len(spy.ctxs) == 1
    assert spy.ctxs[0].skip_initial_delay is True


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
    assert gz.queries[0]["chat_id"] == 100  # F19: chat_id propagated to query
    assert gz.queries[0]["business_connection_id"] == "bc-vip"  # F4: bc propagated
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
        await g["orch"].handle_vip_message(_vip(vip_id=uuid4()))
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
        await g["orch"].handle_vip_message(_vip(vip_id=uuid4()))


@pytest.mark.asyncio
async def test_consult_doctrine_vip_less_vip_channel_raises() -> None:
    """S2: only atencion vip-less turns demote; a VIP-channel turn without a
    vip_id must NOT demote — the RuntimeError guard stays reachable."""
    decision = Decision(
        action="consult_doctrine",
        reason="doctrine_not_found",
        evaluation=_eval(),
        draft_text="draft",
    )
    g = _build(
        FakeDirector(decision),
        gray_zone=FakeGrayZone(),
        feature_gray_zone_enabled=True,
    )
    with pytest.raises(RuntimeError, match="requires vip_id"):
        await g["orch"].handle_vip_message(_vip(vip_id=None))  # channel vip
    assert g["notifier"].drafts == []
    assert g["gray_zone"].queries == []


@pytest.mark.asyncio
async def test_consult_doctrine_atencion_demotes_to_approve() -> None:
    """atencion channel (vip_id=None) consult_doctrine demotes to approve, no crash.

    Gray zone feature OFF: the atencion demote path stays byte-identical
    (no query is created and the turn goes to pending_approval).
    """
    decision = Decision(
        action="consult_doctrine",
        reason="doctrine_not_found",
        evaluation=_eval(),
        draft_text="draft",
    )
    g = _build(
        FakeDirector(decision),
        gray_zone=FakeGrayZone(),
        feature_gray_zone_enabled=False,
    )
    turn_id = await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion")
    )
    turn = await g["turns"].get(turn_id)
    assert turn is not None
    assert turn.status == "pending_approval"
    assert len(g["notifier"].drafts) == 1
    assert g["notifier"].drafts[0].reason == "atencion_no_vip_doctrine"
    # no gray zone query was created for the demoted turn
    assert g["gray_zone"].queries == []
    # the atencion channel travelled through the director unchanged
    assert g["director"].calls[0].channel_type == "atencion"


@pytest.mark.asyncio
async def test_consult_doctrine_atencion_gray_zone_creates_query() -> None:
    """atencion channel (vip_id=None) consult_doctrine creates query + GRAY_ZONE.

    General + gray zone features ON: the open gray zone row (resolved by
    chat_id) is the atencion chat freeze (A1) — no VIP freeze, query carries
    chat_id.
    """
    decision = Decision(
        action="consult_doctrine",
        reason="doctrine_not_found",
        evaluation=_eval(),
        draft_text="draft",
    )
    g = _build(
        FakeDirector(decision),
        gray_zone=FakeGrayZone(),
        feature_gray_zone_enabled=True,
        feature_general_mode_enabled=True,
    )
    turn_id = await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=4242)
    )
    turn = await g["turns"].get(turn_id)
    assert turn is not None
    assert turn.status == "gray_zone"
    # F19 R1-9: the minted turn carries the atencion channel.
    assert turn.channel_type == "atencion"
    # owner was notified with the doctrine query
    assert len(g["notifier"].doctrines) == 1
    # F13a: gray zone never auto-delivers anything.
    assert g["actuator"].send_count() == 0
    # one query was created, anchored to chat_id with no VIP freeze
    assert len(g["gray_zone"].queries) == 1
    q = g["gray_zone"].queries[0]
    assert q["vip_id"] is None
    assert q["chat_id"] == 4242
    assert q["turn_id"] == turn_id
    # F4: business_connection_id propagated to the atencion query too.
    assert q["business_connection_id"] == "bc-vip"
    # the atencion channel travelled through the director unchanged
    assert g["director"].calls[0].channel_type == "atencion"


@pytest.mark.asyncio
async def test_consult_doctrine_atencion_requires_general_mode() -> None:
    """F10: gray zone ON but general mode OFF → demote (training-mode parity).

    Training mode sets channel_type=atencion without the general flag; the
    atencion gray zone must NOT create a query (no freeze) in that case.
    """
    decision = Decision(
        action="consult_doctrine",
        reason="doctrine_not_found",
        evaluation=_eval(),
        draft_text="draft",
    )
    g = _build(
        FakeDirector(decision),
        gray_zone=FakeGrayZone(),
        feature_gray_zone_enabled=True,
        feature_general_mode_enabled=False,
    )
    turn_id = await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=4343)
    )
    turn = await g["turns"].get(turn_id)
    assert turn is not None
    assert turn.status == "pending_approval"
    assert g["gray_zone"].queries == []
    assert len(g["notifier"].drafts) == 1
    assert g["notifier"].drafts[0].reason == "atencion_no_vip_doctrine"


@pytest.mark.asyncio
async def test_consult_doctrine_atencion_skips_when_already_open() -> None:
    """F20: an open atencion query with future freeze → supersede, no 2nd query."""
    decision = Decision(
        action="consult_doctrine",
        reason="doctrine_not_found",
        evaluation=_eval(),
        draft_text="draft",
    )
    existing = type(
        "_Query",
        (),
        {
            "id": uuid4(),
            "freeze_until": datetime.now(UTC) + timedelta(hours=1),
        },
    )()
    g = _build(
        FakeDirector(decision),
        gray_zone=FakeGrayZone(existing_chat_query=existing),
        feature_gray_zone_enabled=True,
        feature_general_mode_enabled=True,
    )
    turn_id = await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=4444)
    )
    turn = await g["turns"].get(turn_id)
    assert turn is not None
    assert turn.status == "superseded"
    assert g["gray_zone"].queries == []  # no second query created
    assert g["notifier"].doctrines == []  # no second DM


@pytest.mark.asyncio
async def test_consult_doctrine_atencion_notify_failure_discards_and_demotes() -> None:
    """F6: doctrine notify failure discards the query and demotes to approve."""
    decision = Decision(
        action="consult_doctrine",
        reason="doctrine_not_found",
        evaluation=_eval(),
        draft_text="draft",
    )
    g = _build(
        FakeDirector(decision),
        gray_zone=FakeGrayZone(),
        feature_gray_zone_enabled=True,
        feature_general_mode_enabled=True,
    )

    async def boom(payload: object) -> None:
        raise RuntimeError("tg down")

    g["notifier"].notify_doctrine = boom  # type: ignore[method-assign]

    turn_id = await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=4545)
    )
    turn = await g["turns"].get(turn_id)
    assert turn is not None
    assert turn.status == "pending_approval"
    # the orphaned query was discarded and the draft demoted for approval
    assert len(g["gray_zone"].discarded) == 1
    assert len(g["notifier"].drafts) == 1
    assert g["notifier"].drafts[0].reason == "atencion_doctrine_notify_failed"
    assert g["gray_zone"].queries == []


class _FlakyRecheckGrayZone(FakeGrayZone):
    """O3: DB failure on the freeze re-check — must fail OPEN."""

    async def get_open_query_by_chat_id(self, chat_id: int) -> object | None:
        raise RuntimeError("db down")


@pytest.mark.asyncio
async def test_consult_doctrine_atencion_recheck_fail_opens() -> None:
    """O3: DB error on the freeze re-check fails OPEN → query still created."""
    decision = Decision(
        action="consult_doctrine",
        reason="doctrine_not_found",
        evaluation=_eval(),
        draft_text="draft",
    )
    g = _build(
        FakeDirector(decision),
        gray_zone=_FlakyRecheckGrayZone(),
        feature_gray_zone_enabled=True,
        feature_general_mode_enabled=True,
    )
    turn_id = await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=5555)
    )
    turn = await g["turns"].get(turn_id)
    assert turn is not None
    assert turn.status == "gray_zone"  # real post-create status after send_doctrine_query
    assert len(g["gray_zone"].queries) == 1  # fail-open: query created despite re-check error


# ── REQ-ATN-12 payment detection ─────────────────────────────────────────


def test_detect_payment_intent_pure() -> None:
    """Deterministic payment signal: policy trigger OR confirmar_entrega+topics."""
    # empty / None → False
    assert _detect_payment_intent(None) is False
    assert _detect_payment_intent({}) is False
    # not a dict → False (never raises)
    assert _detect_payment_intent("trace") is False
    assert _detect_payment_intent(42) is False
    # primary signal: knowledge.policy (production list[str]) has datos_pago
    assert _detect_payment_intent(
        {"retrieved": {"knowledge.policy": ["Trigger: datos_pago\nRegla: ..."]}}
    ) is True
    # defensive: a bare str policy is still detected
    assert _detect_payment_intent(
        {"retrieved": {"knowledge.policy": "Trigger: datos_pago\nRegla: ..."}}
    ) is True
    # secondary signal: confirmar_entrega intent + payment topic
    assert _detect_payment_intent(
        {
            "retrieved": {"knowledge.policy": "otra"},
            "comprehension": {"intent": "confirmar_entrega", "topics": ["pago"]},
        }
    ) is True
    # case/whitespace insensitive
    assert _detect_payment_intent(
        {
            "comprehension": {"intent": " Confirmar_Entrega ", "topics": ["CONTENIDO"]},
        }
    ) is True
    # confirmar_entrega without a payment topic → False
    assert _detect_payment_intent(
        {
            "comprehension": {"intent": "confirmar_entrega", "topics": ["otro"]},
        }
    ) is False
    # payment topic but wrong intent → False
    assert _detect_payment_intent(
        {
            "comprehension": {"intent": "saludo", "topics": ["pago"]},
        }
    ) is False
    # malformed shapes never raise (F5/R1-8)
    assert _detect_payment_intent({"retrieved": None, "comprehension": None}) is False
    assert _detect_payment_intent({"retrieved": "string"}) is False
    # topics None / not a list → no crash, falls back to False
    assert _detect_payment_intent(
        {"comprehension": {"intent": "confirmar_entrega", "topics": None}}
    ) is False
    assert _detect_payment_intent(
        {"comprehension": {"intent": "confirmar_entrega", "topics": "pago"}}
    ) is False
    # policy not a string (non-list, non-str) → no crash, no primary signal
    assert _detect_payment_intent(
        {"retrieved": {"knowledge.policy": 42}}
    ) is False


def _payment_decision() -> Decision:
    return Decision(
        action="approve",
        reason="good",
        evaluation=_eval(),
        draft_text="reply draft",
    )


@pytest.mark.asyncio
async def test_atencion_payment_policy_trigger_notifies_owner() -> None:
    """REQ-ATN-12: retrieved datos_pago trigger → ONE informational DM."""
    g = _build(
        FakeDirector(_payment_decision()),
        feature_general_mode_enabled=True,
        trace_reader=_FakeTraceReader(
            {"retrieved": {"knowledge.policy": ["Trigger: datos_pago"]}}
        ),
    )
    turn_id = await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=100)
    )
    turn = await g["turns"].get(turn_id)
    assert turn is not None and turn.status == "pending_approval"
    expected = ATENCION_PAYMENT_NOTICE.format(chat_id=100)
    assert (expected, 100) in g["notifier"].infos
    assert len(g["notifier"].infos) == 1


@pytest.mark.asyncio
async def test_atencion_payment_confirm_intent_notifies_owner() -> None:
    """REQ-ATN-12: confirmar_entrega + payment topic → informational DM."""
    g = _build(
        FakeDirector(_payment_decision()),
        feature_general_mode_enabled=True,
        trace_reader=_FakeTraceReader(
            {
                "comprehension": {
                    "intent": "confirmar_entrega",
                    "topics": ["pago"],
                }
            }
        ),
    )
    await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=505)
    )
    expected = ATENCION_PAYMENT_NOTICE.format(chat_id=505)
    assert (expected, 505) in g["notifier"].infos
    assert len(g["notifier"].infos) == 1


@pytest.mark.asyncio
async def test_atencion_payment_intent_closes_cycle() -> None:
    """F4 lifecycle: payment intent → DM sent AND the atencion cycle closes.

    The chat leaves the atencion pipeline (auth gate only admits open cycles),
    so the owner delivers manually afterwards.
    """
    cycles = AsyncMock()
    cycles.close_payment = AsyncMock()
    g = _build(
        FakeDirector(_payment_decision()),
        feature_general_mode_enabled=True,
        trace_reader=_FakeTraceReader(
            {"retrieved": {"knowledge.policy": ["Trigger: datos_pago"]}}
        ),
        atencion_cycles=cycles,
    )
    await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=707)
    )
    expected = ATENCION_PAYMENT_NOTICE.format(chat_id=707)
    assert (expected, 707) in g["notifier"].infos
    cycles.close_payment.assert_awaited_once_with(707, now=ANY)


@pytest.mark.asyncio
async def test_atencion_no_payment_signal_keeps_cycle_open() -> None:
    """F4 lifecycle: a normal atencion turn without payment signal never closes."""
    cycles = AsyncMock()
    cycles.close_payment = AsyncMock()
    g = _build(
        FakeDirector(_payment_decision()),
        feature_general_mode_enabled=True,
        trace_reader=_FakeTraceReader(
            {"comprehension": {"intent": "saludo", "topics": ["promociones"]}}
        ),
        atencion_cycles=cycles,
    )
    await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=808)
    )
    assert g["notifier"].infos == []
    cycles.close_payment.assert_not_awaited()


@pytest.mark.asyncio
async def test_vip_payment_signal_not_notified() -> None:
    """REQ-ATN-12: VIP channel never fires the atencion payment DM."""
    g = _build(
        FakeDirector(_payment_decision()),
        trace_reader=_FakeTraceReader(
            {"retrieved": {"knowledge.policy": ["Trigger: datos_pago"]}}
        ),
    )
    await g["orch"].handle_vip_message(_vip(vip_id=uuid4(), chat_id=100))
    assert g["notifier"].infos == []


@pytest.mark.asyncio
async def test_atencion_without_payment_signal_not_notified() -> None:
    """REQ-ATN-12: atencion turn without a payment signal stays silent."""
    g = _build(
        FakeDirector(_payment_decision()),
        feature_general_mode_enabled=True,
        trace_reader=_FakeTraceReader(
            {
                "comprehension": {
                    "intent": "confirmar_entrega",
                    "topics": ["otro"],
                }
            }
        ),
    )
    await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=100)
    )
    assert g["notifier"].infos == []


@pytest.mark.asyncio
async def test_atencion_payment_reader_failure_fail_soft() -> None:
    """REQ-ATN-12: trace read failure never breaks the turn flow."""
    g = _build(
        FakeDirector(_payment_decision()),
        feature_general_mode_enabled=True,
        trace_reader=_FakeTraceReader(None, error=True),
    )
    turn_id = await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=100)
    )
    turn = await g["turns"].get(turn_id)
    assert turn is not None and turn.status == "pending_approval"
    assert g["notifier"].infos == []


@pytest.mark.asyncio
async def test_atencion_payment_without_reader_is_noop() -> None:
    """REQ-ATN-12: no trace_reader injected → no payment DM (A3 fail-soft)."""
    g = _build(FakeDirector(_payment_decision()))
    turn_id = await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=100)
    )
    turn = await g["turns"].get(turn_id)
    assert turn is not None and turn.status == "pending_approval"
    assert g["notifier"].infos == []


@pytest.mark.asyncio
async def test_atencion_payment_edit_skips_dm() -> None:
    """F4(a): edited atencion messages never fire the payment DM."""
    g = _build(
        FakeDirector(_payment_decision()),
        feature_general_mode_enabled=True,
        trace_reader=_FakeTraceReader(
            {"retrieved": {"knowledge.policy": ["Trigger: datos_pago"]}}
        ),
    )
    turn_id = await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=100, is_edit=True)
    )
    turn = await g["turns"].get(turn_id)
    assert turn is not None and turn.status == "pending_approval"
    assert g["notifier"].infos == []


@pytest.mark.asyncio
async def test_atencion_payment_consult_doctrine_skips_dm() -> None:
    """F4(c): consult_doctrine turns already send a doctrine DM — no payment DM."""
    decision = Decision(
        action="consult_doctrine",
        reason="doctrine_not_found",
        evaluation=_eval(),
        draft_text="draft",
    )
    g = _build(
        FakeDirector(decision),
        feature_general_mode_enabled=True,
        trace_reader=_FakeTraceReader(
            {"retrieved": {"knowledge.policy": ["Trigger: datos_pago"]}}
        ),
    )
    await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=100)
    )
    assert g["notifier"].infos == []


@pytest.mark.asyncio
async def test_atencion_payment_sandbox_skips_dm() -> None:
    """F16: sandboxed atencion chats never fire the payment DM."""
    g = _build(
        FakeDirector(_payment_decision()),
        feature_general_mode_enabled=True,
        trace_reader=_FakeTraceReader(
            {"retrieved": {"knowledge.policy": ["Trigger: datos_pago"]}}
        ),
    )
    g["orch"]._sandbox_active = lambda chat_id: chat_id == 100  # type: ignore[method-assign]
    await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=100)
    )
    assert g["notifier"].infos == []


@pytest.mark.asyncio
async def test_atencion_payment_cooldown_limits_dm_per_chat() -> None:
    """F4(b): a second payment signal within 20 min does not double-notify."""
    g = _build(
        FakeDirector(_payment_decision()),
        feature_general_mode_enabled=True,
        trace_reader=_FakeTraceReader(
            {"retrieved": {"knowledge.policy": ["Trigger: datos_pago"]}}
        ),
    )
    await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=100, text="pago 1")
    )
    assert len(g["notifier"].infos) == 1
    await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=100, text="pago 2")
    )
    assert len(g["notifier"].infos) == 1  # cooldown holds


@pytest.mark.asyncio
async def test_atencion_payment_notify_failure_does_not_consume_cooldown() -> None:
    """O1: a failed informational DM must NOT consume the 20-min cooldown."""
    g = _build(
        FakeDirector(_payment_decision()),
        feature_general_mode_enabled=True,
        trace_reader=_FakeTraceReader(
            {"retrieved": {"knowledge.policy": ["Trigger: datos_pago"]}}
        ),
    )
    calls = {"n": 0}

    async def flaky(text: str, *, chat_id: int | None = None) -> None:
        calls["n"] += 1
        raise RuntimeError("notify down")

    g["notifier"].notify_info = flaky  # type: ignore[method-assign]
    await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=100)
    )
    await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=100)
    )
    assert calls["n"] == 2  # 2nd attempt NOT suppressed → failure didn't stamp cooldown


@pytest.mark.asyncio
async def test_atencion_payment_general_mode_off_skips_dm() -> None:
    """O2: training mode (channel_type=atencion, general flag OFF) never fires the DM."""
    g = _build(
        FakeDirector(_payment_decision()),
        trace_reader=_FakeTraceReader(
            {"retrieved": {"knowledge.policy": ["Trigger: datos_pago"]}}
        ),
    )
    turn_id = await g["orch"].handle_vip_message(
        _vip(vip_id=None, channel_type="atencion", chat_id=100)
    )
    turn = await g["turns"].get(turn_id)
    assert turn is not None and turn.status == "pending_approval"
    assert g["notifier"].infos == []


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

    turn_id = await g["orch"].handle_vip_message(_vip())
    failed = await g["turns"].get(turn_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "analista_schema_invalido"
    assert get_swallowed_counts().get(
        "owner_notify_failed_after_analyst_schema_invalid", 0
    ) == 1
    assert g["actuator"].send_count() == 0


# ── Sandbox isolation + configured delivery_mode ────────────────────────


@pytest.mark.asyncio
async def test_sandbox_skips_learning_post_turn() -> None:

    from diana.application.sandbox import SandboxService
    # inline six-profile catalog
    MINIMAL_SIX = {
        "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
        "cercano": {
            "label": "VIP cercano",
            "description": "",
            "facts": {"name": "Mateo", "personality": "confiado"},
            "notes": [{"date": "2026-05-10", "text": "Le gusta el trato cercano"}],
        },
        "distante": {
            "label": "VIP reservado",
            "description": "",
            "facts": {"personality": "formal"},
            "notes": [],
        },
        "intenso": {
            "label": "VIP emocional",
            "description": "",
            "facts": {"relationship": "recién separado"},
            "notes": [],
        },
        "vip_largo": {
            "label": "VIP largo",
            "description": "",
            "facts": {"name": "Sofía"},
            "notes": [],
        },
        "inyeccion_previa": {
            "label": "Fixture adversarial",
            "description": "",
            "facts": {"name": "TestUser"},
            "notes": [],
        },
    }

    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="draft",
    )
    learn = RecordingLearning()
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    sandbox.activate(100, "nuevo")
    g = _build(FakeDirector(decision), learning=learn)
    g["orch"]._sandbox = sandbox  # noqa: SLF001
    await g["orch"].handle_vip_message(_vip(chat_id=100))
    assert learn.calls == []


@pytest.mark.asyncio
async def test_sandbox_inactive_still_runs_learning() -> None:

    from diana.application.sandbox import SandboxService
    # inline six-profile catalog
    MINIMAL_SIX = {
        "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
        "cercano": {
            "label": "VIP cercano",
            "description": "",
            "facts": {"name": "Mateo", "personality": "confiado"},
            "notes": [{"date": "2026-05-10", "text": "Le gusta el trato cercano"}],
        },
        "distante": {
            "label": "VIP reservado",
            "description": "",
            "facts": {"personality": "formal"},
            "notes": [],
        },
        "intenso": {
            "label": "VIP emocional",
            "description": "",
            "facts": {"relationship": "recién separado"},
            "notes": [],
        },
        "vip_largo": {
            "label": "VIP largo",
            "description": "",
            "facts": {"name": "Sofía"},
            "notes": [],
        },
        "inyeccion_previa": {
            "label": "Fixture adversarial",
            "description": "",
            "facts": {"name": "TestUser"},
            "notes": [],
        },
    }

    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="draft",
    )
    learn = RecordingLearning()
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    g = _build(FakeDirector(decision), learning=learn)
    g["orch"]._sandbox = sandbox  # noqa: SLF001
    await g["orch"].handle_vip_message(_vip(chat_id=100))
    assert len(learn.calls) == 1


@pytest.mark.asyncio
async def test_sandbox_autonomous_uses_configured_delivery_mode() -> None:
    """Sandbox must not force fake_delivery; mode equals configured delivery_mode.

    Also co-asserts product isolation (learning skip) on the autonomous-send path.
    """
    from diana.application.sandbox import SandboxService
    # inline six-profile catalog
    MINIMAL_SIX = {
        "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
        "cercano": {
            "label": "VIP cercano",
            "description": "",
            "facts": {"name": "Mateo", "personality": "confiado"},
            "notes": [{"date": "2026-05-10", "text": "Le gusta el trato cercano"}],
        },
        "distante": {
            "label": "VIP reservado",
            "description": "",
            "facts": {"personality": "formal"},
            "notes": [],
        },
        "intenso": {
            "label": "VIP emocional",
            "description": "",
            "facts": {"relationship": "recién separado"},
            "notes": [],
        },
        "vip_largo": {
            "label": "VIP largo",
            "description": "",
            "facts": {"name": "Sofía"},
            "notes": [],
        },
        "inyeccion_previa": {
            "label": "Fixture adversarial",
            "description": "",
            "facts": {"name": "TestUser"},
            "notes": [],
        },
    }

    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="auto reply",
    )
    learn = RecordingLearning()
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    sandbox.activate(100, "cercano")
    vip_store = InMemoryVipStore()
    rec = await vip_store.add(9001, display_name="V")
    captured: list = []

    class CaptureBehavior:
        async def deliver(self, texts, ctx, turn_id, **kwargs):
            captured.append(ctx)
            from diana.application.ports import DeliveryResult

            return DeliveryResult(success=True, cancelled=False)

        async def cancel_pending(self, chat_id, reason):
            return 0

    g = _build(
        FakeDirector(decision),
        learning=learn,
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        delivery_mode="supervised",
        vip_store=vip_store,
        behavior_override=CaptureBehavior(),
    )
    g["orch"]._sandbox = sandbox  # noqa: SLF001
    await g["orch"].handle_vip_message(_vip(chat_id=100, vip_id=rec.id))
    assert len(captured) == 1
    # CLARIFY: sandbox must not force fake — equals configured delivery_mode
    assert captured[0].mode == "supervised"
    assert learn.calls == []


@pytest.mark.asyncio
async def test_sandbox_autonomous_uses_autonomous_delivery_mode() -> None:
    """Sandbox + delivery_mode=autonomous yields autonomous (not forced fake)."""
    from diana.application.sandbox import SandboxService

    MINIMAL_SIX = {
        "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
        "cercano": {
            "label": "VIP cercano",
            "description": "",
            "facts": {"name": "Mateo", "personality": "confiado"},
            "notes": [{"date": "2026-05-10", "text": "Le gusta el trato cercano"}],
        },
        "distante": {
            "label": "VIP reservado",
            "description": "",
            "facts": {"personality": "formal"},
            "notes": [],
        },
        "intenso": {
            "label": "VIP emocional",
            "description": "",
            "facts": {"relationship": "recién separado"},
            "notes": [],
        },
        "vip_largo": {
            "label": "VIP largo",
            "description": "",
            "facts": {"name": "Sofía"},
            "notes": [],
        },
        "inyeccion_previa": {
            "label": "Fixture adversarial",
            "description": "",
            "facts": {"name": "TestUser"},
            "notes": [],
        },
    }

    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="auto reply",
    )
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    sandbox.activate(100, "cercano")
    vip_store = InMemoryVipStore()
    rec = await vip_store.add(9001, display_name="V")
    captured: list = []

    class CaptureBehavior:
        async def deliver(self, texts, ctx, turn_id, **kwargs):
            captured.append(ctx)
            from diana.application.ports import DeliveryResult

            return DeliveryResult(success=True, cancelled=False)

        async def cancel_pending(self, chat_id, reason):
            return 0

    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        delivery_mode="autonomous",
        vip_store=vip_store,
        behavior_override=CaptureBehavior(),
    )
    g["orch"]._sandbox = sandbox  # noqa: SLF001
    await g["orch"].handle_vip_message(_vip(chat_id=100, vip_id=rec.id))
    assert len(captured) == 1
    assert captured[0].mode == "autonomous"


@pytest.mark.asyncio
async def test_sandbox_respects_global_fake_delivery_mode() -> None:
    """Sandbox active + configured fake_delivery still yields fake (ops mode preserved)."""
    from diana.application.sandbox import SandboxService

    MINIMAL_SIX = {
        "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
        "cercano": {
            "label": "VIP cercano",
            "description": "",
            "facts": {"name": "Mateo", "personality": "confiado"},
            "notes": [{"date": "2026-05-10", "text": "Le gusta el trato cercano"}],
        },
        "distante": {
            "label": "VIP reservado",
            "description": "",
            "facts": {"personality": "formal"},
            "notes": [],
        },
        "intenso": {
            "label": "VIP emocional",
            "description": "",
            "facts": {"relationship": "recién separado"},
            "notes": [],
        },
        "vip_largo": {
            "label": "VIP largo",
            "description": "",
            "facts": {"name": "Sofía"},
            "notes": [],
        },
        "inyeccion_previa": {
            "label": "Fixture adversarial",
            "description": "",
            "facts": {"name": "TestUser"},
            "notes": [],
        },
    }

    decision = Decision(
        action="send",
        reason="autonomous_ok",
        evaluation=_eval(),
        draft_text="auto reply",
    )
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    sandbox.activate(100, "cercano")
    vip_store = InMemoryVipStore()
    rec = await vip_store.add(9001, display_name="V")
    captured: list = []

    class CaptureBehavior:
        async def deliver(self, texts, ctx, turn_id, **kwargs):
            captured.append(ctx)
            from diana.application.ports import DeliveryResult

            return DeliveryResult(success=True, cancelled=False)

        async def cancel_pending(self, chat_id, reason):
            return 0

    g = _build(
        FakeDirector(decision),
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        delivery_mode="fake_delivery",
        vip_store=vip_store,
        behavior_override=CaptureBehavior(),
    )
    g["orch"]._sandbox = sandbox  # noqa: SLF001
    await g["orch"].handle_vip_message(_vip(chat_id=100, vip_id=rec.id))
    assert len(captured) == 1
    assert captured[0].mode == "fake_delivery"


@pytest.mark.asyncio
async def test_sandbox_consult_doctrine_demotes_when_no_vip() -> None:

    from diana.application.sandbox import SandboxService
    # inline six-profile catalog
    MINIMAL_SIX = {
        "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
        "cercano": {
            "label": "VIP cercano",
            "description": "",
            "facts": {"name": "Mateo", "personality": "confiado"},
            "notes": [{"date": "2026-05-10", "text": "Le gusta el trato cercano"}],
        },
        "distante": {
            "label": "VIP reservado",
            "description": "",
            "facts": {"personality": "formal"},
            "notes": [],
        },
        "intenso": {
            "label": "VIP emocional",
            "description": "",
            "facts": {"relationship": "recién separado"},
            "notes": [],
        },
        "vip_largo": {
            "label": "VIP largo",
            "description": "",
            "facts": {"name": "Sofía"},
            "notes": [],
        },
        "inyeccion_previa": {
            "label": "Fixture adversarial",
            "description": "",
            "facts": {"name": "TestUser"},
            "notes": [],
        },
    }

    decision = Decision(
        action="consult_doctrine",
        reason="doctrine_not_found",
        evaluation=_eval(),
        draft_text="draft",
    )
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    sandbox.activate(100, "nuevo")
    g = _build(
        FakeDirector(decision),
        gray_zone=FakeGrayZone(),
        feature_gray_zone_enabled=True,
    )
    g["orch"]._sandbox = sandbox  # noqa: SLF001
    g["admin"]._sandbox = sandbox  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(_vip(chat_id=100, vip_id=None))
    turn = await g["turns"].get(turn_id)
    assert turn is not None
    assert turn.status == "pending_approval"
    assert len(g["notifier"].drafts) == 1
    assert "SANDBOX" in g["notifier"].drafts[0].reason


# ── F4-02: atencion daily limit (20 msgs/chat, CDMX civil day) ──────────


class _MemoryDailyLimitStore:
    """In-memory DailyMessageLimitStore for orchestrator limit tests."""

    def __init__(
        self, seed: dict[tuple[int, date], int] | None = None
    ) -> None:
        self._counts = dict(seed or {})
        self.calls: list[tuple[int, date]] = []

    async def increment(self, chat_id: int, *, fecha_local: date) -> int:
        self.calls.append((chat_id, fecha_local))
        key = (chat_id, fecha_local)
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]


class _RaisingDailyLimitStore:
    """DailyMessageLimitStore that fails on increment (store-outage probe)."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, date]] = []

    async def increment(self, chat_id: int, *, fecha_local: date) -> int:
        self.calls.append((chat_id, fecha_local))
        raise RuntimeError("daily_message_limits store unavailable")


class _RaisingCreateTurnStore(InMemoryTurnStore):
    """InMemoryTurnStore whose create() raises after recording (outage probe)."""

    def __init__(self) -> None:
        super().__init__()
        self.created: list[TurnRecord] = []

    async def create(self, turn: TurnRecord) -> TurnRecord:
        self.created.append(turn)
        raise RuntimeError("turns store unavailable")


class _RaisingTransitionTurnStore(InMemoryTurnStore):
    """InMemoryTurnStore whose transition() raises after recording."""

    def __init__(self) -> None:
        super().__init__()
        self.transitions: list[tuple[UUID, str, str | None]] = []

    async def transition(
        self,
        turn_id: UUID,
        status: str,
        *,
        superseded_by: UUID | None = None,
        error: str | None = None,
    ) -> TurnRecord:
        self.transitions.append((turn_id, status, error))
        raise RuntimeError("turns store unavailable")


class _RecordingTurnStore(InMemoryTurnStore):
    """TurnStore that records every minted TurnRecord (create/transition)."""

    def __init__(self) -> None:
        super().__init__()
        self.created: list[TurnRecord] = []
        self.transitions: list[tuple[UUID, str, str | None]] = []

    async def create(self, turn: TurnRecord) -> TurnRecord:
        self.created.append(turn)
        return await super().create(turn)

    async def transition(
        self,
        turn_id: UUID,
        status: str,
        *,
        superseded_by: UUID | None = None,
        error: str | None = None,
    ) -> TurnRecord:
        self.transitions.append((turn_id, status, error))
        return await super().transition(
            turn_id, status, superseded_by=superseded_by, error=error
        )


class FakeDayClock:
    """Mutable now()-clock to pin the CDMX civil date for limit tests."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now


# 2026-08-05 18:00 UTC == 12:00 America/Mexico_City 2026-08-05 (UTC-6).
_FIXED_DAY = datetime(2026, 8, 5, 18, 0, tzinfo=UTC)


def _limit_decision() -> Decision:
    return Decision(
        action="approve",
        reason="good",
        evaluation=_eval(),
        draft_text="reply draft",
    )


@pytest.mark.asyncio
async def test_atencion_limit_20_processes_normally() -> None:
    """F4-02: message #20 of the day still proceeds (turn minted)."""
    store = _MemoryDailyLimitStore(seed={(100, date(2026, 8, 5)): 19})
    g = _build(FakeDirector(_limit_decision()), daily_limit=store)
    g["orch"]._clock = FakeDayClock(_FIXED_DAY)  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(
        _vip(
            counts_toward_limit=True,
            channel_type="atencion",
            telegram_message_id=101,
        )
    )
    assert await g["turns"].get(turn_id) is not None
    assert store.calls == [(100, date(2026, 8, 5))]


@pytest.mark.asyncio
async def test_atencion_limit_21_sends_closing_once() -> None:
    """F4-02: message #21 closes with the fixed reply via a REAL minted turn.

    Mirrors PromoService.execute_promo: the close mints a promo_pending turn,
    delivers direct-to-chat with skip_initial_delay=True, then transitions the
    turn to delivered. No epoch bump / history write / pipeline for msg 21.
    """
    store = _MemoryDailyLimitStore(seed={(100, date(2026, 8, 5)): 20})
    turns = _RecordingTurnStore()
    spy = _CapturingDeliverer()
    g = _build(
        FakeDirector(_limit_decision()),
        daily_limit=store,
        wire_autonomous=True,
        behavior_override=spy,
        turns=turns,
    )
    g["orch"]._clock = FakeDayClock(_FIXED_DAY)  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(
        _vip(
            counts_toward_limit=True,
            channel_type="atencion",
            telegram_message_id=21,
        )
    )
    # A REAL turn was minted (non-terminal promo_pending) and returned.
    assert turn_id == turns.created[0].id
    assert turns.created[0].status == "promo_pending"
    assert turns.created[0].vip_id is None
    # Closing reply delivered exactly once, direct to chat, no supervised
    # ~120 s initial wait (skip_initial_delay neutralizes the delay).
    assert spy.texts == [[ATENCION_DAILY_LIMIT_CLOSE]]
    assert spy.ctxs[0].chat_id == 100
    assert spy.ctxs[0].business_connection_id == "bc-vip"
    assert spy.ctxs[0].skip_initial_delay is True
    assert spy.turn_ids == [turns.created[0].id]
    # Success → turn transitioned to delivered (promo-style bookkeeping).
    assert (await g["turns"].get(turn_id)).status == "delivered"
    assert turns.transitions == [(turn_id, "delivered", None)]
    # Over-limit message never bumps epoch, writes history, or runs pipeline.
    assert g["coordinator"].current_vip_epoch(100) == 0
    assert g["director"].calls == []
    history_ids = [
        row.get("telegram_message_id")
        for row in g["history"]._messages.get(100, [])  # noqa: SLF001
    ]
    assert 21 not in history_ids
    assert store.calls == [(100, date(2026, 8, 5))]


@pytest.mark.asyncio
async def test_atencion_limit_22_drops_silently() -> None:
    """F4-02: message #22 drops with no closing reply, no turn minted."""
    store = _MemoryDailyLimitStore(seed={(100, date(2026, 8, 5)): 21})
    spy = _CapturingDeliverer()
    g = _build(
        FakeDirector(_limit_decision()),
        daily_limit=store,
        wire_autonomous=True,
        behavior_override=spy,
    )
    g["orch"]._clock = FakeDayClock(_FIXED_DAY)  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(
        _vip(
            counts_toward_limit=True,
            channel_type="atencion",
            telegram_message_id=22,
        )
    )
    assert spy.texts == []
    assert g["director"].calls == []
    # Synthetic uuid4 returned — no turn minted for the dropped message.
    assert await g["turns"].get(turn_id) is None
    assert store.calls == [(100, date(2026, 8, 5))]


@pytest.mark.asyncio
async def test_atencion_limit_close_skips_when_no_behavior() -> None:
    """F4-02: closing reply skipped (no_sender_or_bc) when no sender wired."""
    store = _MemoryDailyLimitStore(seed={(100, date(2026, 8, 5)): 20})
    g = _build(FakeDirector(_limit_decision()), daily_limit=store)
    g["orch"]._clock = FakeDayClock(_FIXED_DAY)  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(
        _vip(
            counts_toward_limit=True,
            channel_type="atencion",
            telegram_message_id=21,
        )
    )
    # No behavior → close skipped, synthetic turn returned, no crash.
    assert isinstance(turn_id, UUID)
    assert await g["turns"].get(turn_id) is None
    assert g["director"].calls == []
    assert store.calls == [(100, date(2026, 8, 5))]


@pytest.mark.asyncio
async def test_atencion_limit_close_skips_when_no_bc() -> None:
    """F4-02: closing reply skipped when business_connection_id is empty."""
    store = _MemoryDailyLimitStore(seed={(100, date(2026, 8, 5)): 20})
    spy = _CapturingDeliverer()
    g = _build(
        FakeDirector(_limit_decision()),
        daily_limit=store,
        wire_autonomous=True,
        behavior_override=spy,
    )
    g["orch"]._clock = FakeDayClock(_FIXED_DAY)  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(
        _vip(
            counts_toward_limit=True,
            channel_type="atencion",
            business_connection_id=None,
            telegram_message_id=21,
        )
    )
    assert spy.texts == []
    assert await g["turns"].get(turn_id) is None
    assert store.calls == [(100, date(2026, 8, 5))]


@pytest.mark.asyncio
async def test_atencion_limit_close_no_turn_store_skips() -> None:
    """F4-02: closing reply skipped (no_turn_store) when turns not wired."""
    store = _MemoryDailyLimitStore(seed={(100, date(2026, 8, 5)): 20})
    spy = _CapturingDeliverer()
    g = _build(
        FakeDirector(_limit_decision()),
        daily_limit=store,
        wire_autonomous=True,
        behavior_override=spy,
    )
    g["orch"]._turns = None  # noqa: SLF001
    g["orch"]._clock = FakeDayClock(_FIXED_DAY)  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(
        _vip(
            counts_toward_limit=True,
            channel_type="atencion",
            telegram_message_id=21,
        )
    )
    assert spy.texts == []
    assert await g["turns"].get(turn_id) is None
    assert store.calls == [(100, date(2026, 8, 5))]


@pytest.mark.asyncio
async def test_atencion_limit_close_marks_turn_failed_on_deliver_error() -> None:
    """F4-02: a raising deliverer fails the minted close turn, no crash."""

    class _RaisingDeliverer:
        async def deliver(
            self, texts, ctx, turn_id, decision=None
        ) -> object:
            raise RuntimeError("send burst")

    store = _MemoryDailyLimitStore(seed={(100, date(2026, 8, 5)): 20})
    turns = _RecordingTurnStore()
    g = _build(
        FakeDirector(_limit_decision()),
        daily_limit=store,
        wire_autonomous=True,
        behavior_override=_RaisingDeliverer(),
        turns=turns,
    )
    g["orch"]._clock = FakeDayClock(_FIXED_DAY)  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(
        _vip(
            counts_toward_limit=True,
            channel_type="atencion",
            telegram_message_id=21,
        )
    )
    # Deliver raised → the minted turn is transitioned to failed, swallowed.
    assert turn_id == turns.created[0].id
    assert (await g["turns"].get(turn_id)).status == "failed"
    assert turns.transitions == [
        (turn_id, "failed", "atencion_limit_close_failed")
    ]
    assert g["director"].calls == []


@pytest.mark.asyncio
async def test_atencion_limit_close_failed_result_marks_turn_failed() -> None:
    """F4-02: a non-raising failed DeliveryResult still fails the minted turn.

    Unlike the raising-deliverer path (``atencion_limit_close_failed``), a
    deliverer that RETURNS ``DeliveryResult(success=False, error="boom")``
    must transition the close turn to ``failed`` with the result's error —
    and the best-effort close text is still sent once regardless of the
    result.
    """

    class _FailedResultDeliverer:
        def __init__(self) -> None:
            self.texts: list[list[str]] = []
            self.turn_ids: list[UUID] = []

        async def deliver(
            self, texts, ctx, turn_id, decision=None
        ) -> object:
            from diana.application.ports import DeliveryResult

            self.texts.append(list(texts))
            self.turn_ids.append(turn_id)
            return DeliveryResult(success=False, error="boom")

    store = _MemoryDailyLimitStore(seed={(100, date(2026, 8, 5)): 20})
    turns = _RecordingTurnStore()
    spy = _FailedResultDeliverer()
    g = _build(
        FakeDirector(_limit_decision()),
        daily_limit=store,
        wire_autonomous=True,
        behavior_override=spy,
        turns=turns,
    )
    g["orch"]._clock = FakeDayClock(_FIXED_DAY)  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(
        _vip(
            counts_toward_limit=True,
            channel_type="atencion",
            telegram_message_id=21,
        )
    )
    # Close turn minted (promo_pending), best-effort text still sent once.
    assert turn_id == turns.created[0].id
    assert turns.created[0].status == "promo_pending"
    assert spy.texts == [[ATENCION_DAILY_LIMIT_CLOSE]]
    assert spy.turn_ids == [turns.created[0].id]
    # Non-raising failure → turn transitioned failed with result.error == "boom".
    assert (await g["turns"].get(turn_id)).status == "failed"
    assert turns.transitions == [(turn_id, "failed", "boom")]
    assert g["director"].calls == []


@pytest.mark.asyncio
async def test_atencion_limit_close_skips_when_turn_create_raises() -> None:
    """F4-02 (FIX-A): a turn-store outage on create skips the close, no crash.

    The day is already closed at count 21; the fail-soft skip returns a
    synthetic uuid and the message must NOT fall through to the pipeline.
    """
    store = _MemoryDailyLimitStore(seed={(100, date(2026, 8, 5)): 20})
    turns = _RaisingCreateTurnStore()
    spy = _CapturingDeliverer()
    g = _build(
        FakeDirector(_limit_decision()),
        daily_limit=store,
        wire_autonomous=True,
        behavior_override=spy,
        turns=turns,
    )
    g["orch"]._clock = FakeDayClock(_FIXED_DAY)  # noqa: SLF001
    close_id = await g["orch"].handle_vip_message(
        _vip(
            counts_toward_limit=True,
            channel_type="atencion",
            telegram_message_id=21,
        )
    )
    # Mint attempted (promo_pending) but create raised → no row persisted.
    assert len(turns.created) == 1
    assert turns.created[0].status == "promo_pending"
    # Close skipped fail-soft (synthetic uuid), no crash, message NOT processed.
    assert isinstance(close_id, UUID)
    assert spy.texts == []
    assert g["director"].calls == []


@pytest.mark.asyncio
async def test_atencion_limit_close_swallows_transition_error() -> None:
    """F4-02 (FIX-A): a transition outage on the close turn is swallowed.

    The best-effort close text is still sent once and the real close turn id
    is returned; the failed bookkeeping must not drop the 21st message.
    """
    store = _MemoryDailyLimitStore(seed={(100, date(2026, 8, 5)): 20})
    turns = _RaisingTransitionTurnStore()
    spy = _CapturingDeliverer()
    g = _build(
        FakeDirector(_limit_decision()),
        daily_limit=store,
        wire_autonomous=True,
        behavior_override=spy,
        turns=turns,
    )
    g["orch"]._clock = FakeDayClock(_FIXED_DAY)  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(
        _vip(
            counts_toward_limit=True,
            channel_type="atencion",
            telegram_message_id=21,
        )
    )
    # Close delivered once with the real turn id; transition failure swallowed.
    assert spy.texts == [[ATENCION_DAILY_LIMIT_CLOSE]]
    assert spy.turn_ids == [turn_id]
    assert turns.transitions == [(turn_id, "delivered", None)]
    assert g["director"].calls == []


@pytest.mark.asyncio
async def test_atencion_limit_store_error_processes_normally() -> None:
    """F4-02 (S2): a store outage fails open — the message still processes."""
    store = _RaisingDailyLimitStore()
    g = _build(FakeDirector(_limit_decision()), daily_limit=store)
    g["orch"]._clock = FakeDayClock(_FIXED_DAY)  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(
        _vip(
            counts_toward_limit=True,
            channel_type="atencion",
            telegram_message_id=9,
        )
    )
    assert store.calls == [(100, date(2026, 8, 5))]
    assert await g["turns"].get(turn_id) is not None
    assert len(g["director"].calls) == 1


@pytest.mark.asyncio
async def test_atencion_limit_skips_edits() -> None:
    """F4-02: edits never count toward the daily limit (marker ignored)."""
    store = _MemoryDailyLimitStore()
    g = _build(FakeDirector(_limit_decision()), daily_limit=store)
    turn_id = await g["orch"].handle_vip_message(
        _vip(
            counts_toward_limit=True,
            is_edit=True,
            channel_type="atencion",
            telegram_message_id=31,
        )
    )
    assert await g["turns"].get(turn_id) is not None
    assert store.calls == []


@pytest.mark.asyncio
async def test_atencion_limit_skips_when_not_counted() -> None:
    """F4-02: sandbox/training atencion (no marker) is never counted."""
    store = _MemoryDailyLimitStore()
    g = _build(FakeDirector(_limit_decision()), daily_limit=store)
    turn_id = await g["orch"].handle_vip_message(
        _vip(channel_type="atencion", telegram_message_id=41)
    )
    assert await g["turns"].get(turn_id) is not None
    assert store.calls == []


@pytest.mark.asyncio
async def test_atencion_limit_no_store_processes_normally() -> None:
    """F4-02: without a store wired the hook is a no-op."""
    g = _build(FakeDirector(_limit_decision()))
    turn_id = await g["orch"].handle_vip_message(
        _vip(counts_toward_limit=True, channel_type="atencion")
    )
    assert await g["turns"].get(turn_id) is not None


@pytest.mark.asyncio
async def test_atencion_limit_day_boundary_resets() -> None:
    """F4-02: a new CDMX civil date starts a fresh counter."""
    store = _MemoryDailyLimitStore()
    day_clock = FakeDayClock(_FIXED_DAY)
    g = _build(FakeDirector(_limit_decision()), daily_limit=store)
    g["orch"]._clock = day_clock  # noqa: SLF001
    # 18:00 UTC → 12:00 CDMX 2026-08-05.
    t1 = await g["orch"].handle_vip_message(
        _vip(counts_toward_limit=True, channel_type="atencion", telegram_message_id=1)
    )
    assert await g["turns"].get(t1) is not None
    # 05:30 UTC next day → 23:30 CDMX 2026-08-05 (still the same civil date).
    day_clock.set(datetime(2026, 8, 6, 5, 30, tzinfo=UTC))
    t2 = await g["orch"].handle_vip_message(
        _vip(counts_toward_limit=True, channel_type="atencion", telegram_message_id=2)
    )
    assert await g["turns"].get(t2) is not None
    # 06:30 UTC → 00:30 CDMX 2026-08-06 (new civil date → counter resets).
    day_clock.set(datetime(2026, 8, 6, 6, 30, tzinfo=UTC))
    t3 = await g["orch"].handle_vip_message(
        _vip(counts_toward_limit=True, channel_type="atencion", telegram_message_id=3)
    )
    assert await g["turns"].get(t3) is not None
    assert store.calls == [
        (100, date(2026, 8, 5)),
        (100, date(2026, 8, 5)),
        (100, date(2026, 8, 6)),
    ]
    # Counts 1, 2, 1 — never over limit across the boundary.
    assert list(store._counts.values()) == [2, 1]  # noqa: SLF001


# ---------------------------------------------------------------------------
# REQ-ATN-05 — per-channel delivery_mode profile config
# ---------------------------------------------------------------------------


class _FakeCatalogProvider:
    """Dict-backed PersonaCatalogProvider double for channel-mode resolution."""

    def __init__(
        self,
        catalogs: dict[str, dict] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.catalogs = catalogs or {}
        self.error = error
        self.calls: list[str] = []

    async def get_catalog(self, channel_type: str = "vip") -> dict | None:
        self.calls.append(channel_type)
        if self.error is not None:
            raise self.error
        return self.catalogs.get(channel_type)


def _mode_decision() -> Decision:
    return Decision(
        action="approve",
        reason="good",
        evaluation=_eval(),
        draft_text="reply draft",
    )


@pytest.mark.asyncio
async def test_atencion_stays_supervised_under_autonomous_global() -> None:
    """Impact-report invariant: profile supervised wins over global autonomous.

    The atencion profile short-circuits BEFORE the AMS gate, so the autonomous
    global mode can never make atencion autonomous when the profile says
    supervised. Assert AMS was never consulted.
    """
    provider = _FakeCatalogProvider({"atencion": {"delivery_mode": "supervised"}})
    g = _build(
        FakeDirector(_mode_decision()),
        delivery_mode="autonomous",
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        persona_catalog_provider=provider,
    )
    g["ams"].is_autonomous_enabled = AsyncMock(
        side_effect=AssertionError("AMS must not be consulted")
    )
    mode = await g["orch"]._resolve_effective_mode(None, "atencion")  # noqa: SLF001
    assert mode == "supervised"
    assert provider.calls == ["atencion"]


@pytest.mark.asyncio
async def test_atencion_supervised_from_profile_when_global_autonomous() -> None:
    """Profile supervised beats global autonomous (the REQ-ATN-05 invariant)."""
    provider = _FakeCatalogProvider({"atencion": {"delivery_mode": "supervised"}})
    g = _build(
        FakeDirector(_mode_decision()),
        delivery_mode="autonomous",
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        persona_catalog_provider=provider,
    )
    mode = await g["orch"]._resolve_effective_mode(None, "atencion")  # noqa: SLF001
    assert mode == "supervised"


@pytest.mark.asyncio
async def test_vip_uses_global_when_profile_absent() -> None:
    """Catalog without delivery_mode → falls back to the global configured mode."""
    provider = _FakeCatalogProvider({"vip": {}})  # no delivery_mode key
    g = _build(
        FakeDirector(_mode_decision()),
        delivery_mode="fake_delivery",
        persona_catalog_provider=provider,
    )
    mode = await g["orch"]._resolve_effective_mode(None, "vip")  # noqa: SLF001
    assert mode == "fake_delivery"


@pytest.mark.asyncio
async def test_catalog_read_failure_falls_back_to_global() -> None:
    """Provider raises (unknown channel / DB error) → global mode, no crash."""
    provider = _FakeCatalogProvider(error=ValueError("unknown channel"))
    g = _build(
        FakeDirector(_mode_decision()),
        delivery_mode="fake_delivery",
        persona_catalog_provider=provider,
    )
    mode = await g["orch"]._resolve_effective_mode(None, "atencion")  # noqa: SLF001
    assert mode == "fake_delivery"


@pytest.mark.asyncio
async def test_atencion_autonomous_profile_still_demoted_by_ams() -> None:
    """Safety net: even a catalog delivery_mode=autonomous is demoted for
    vip_id=None when the AMS gate denies (global supervised, no vip)."""
    provider = _FakeCatalogProvider({"atencion": {"delivery_mode": "autonomous"}})
    g = _build(
        FakeDirector(_mode_decision()),
        delivery_mode="autonomous",
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="supervised",
        persona_catalog_provider=provider,
    )
    mode = await g["orch"]._resolve_effective_mode(None, "atencion")  # noqa: SLF001
    assert mode == "supervised"


@pytest.mark.asyncio
async def test_provider_none_uses_global() -> None:
    """No provider injected → global mode untouched (backward compat)."""
    g = _build(
        FakeDirector(_mode_decision()),
        delivery_mode="supervised",
    )
    mode = await g["orch"]._resolve_effective_mode(None, "atencion")  # noqa: SLF001
    assert mode == "supervised"


@pytest.mark.asyncio
async def test_provider_returns_none_uses_global() -> None:
    """Provider exists but get_catalog returns None (unknown channel, no
    exception) → global mode, same as the exception-fallback path."""
    provider = _FakeCatalogProvider({})  # unknown channel → None, no raise
    g = _build(
        FakeDirector(_mode_decision()),
        delivery_mode="fake_delivery",
        persona_catalog_provider=provider,
    )
    mode = await g["orch"]._resolve_effective_mode(None, "atencion")  # noqa: SLF001
    assert mode == "fake_delivery"


@pytest.mark.asyncio
async def test_atencion_real_seed_no_delivery_mode_demoted_by_ams_guard() -> None:
    """Real atencion seed state (no delivery_mode key) + global autonomous:
    the AMS vip_id=None guard demotes the channel to supervised (R1-1)."""
    provider = _FakeCatalogProvider({"atencion": {}})  # real seed has no delivery_mode
    g = _build(
        FakeDirector(_mode_decision()),
        delivery_mode="autonomous",
        wire_autonomous=True,
        feature_autonomous_mode=True,
        global_mode="autonomous",
        persona_catalog_provider=provider,
    )
    mode = await g["orch"]._resolve_effective_mode(None, "atencion")  # noqa: SLF001
    assert mode == "supervised"


def test_prune_payment_notify_removes_only_stale_entries() -> None:
    """F7/O6: pruning drops only entries older than the payment notify TTL."""
    g = _build(FakeDirector(_payment_decision()))
    orch = g["orch"]
    now = datetime.now(UTC)
    stale = now - _PAYMENT_NOTIFY_TTL - timedelta(minutes=1)
    recent = now - timedelta(minutes=1)
    orch._last_payment_notify = {111: stale, 222: recent}
    orch._prune_payment_notify(now)
    assert orch._last_payment_notify == {222: recent}


# --- Evo-Agente: emotional detector shadow hook ---------------------------------


class _FakeEmotionalTraceReader:
    """Trace reader for the detector hook: full trace + recent comprehension."""

    def __init__(self, trace: dict | None, baseline: list[dict] | None = None) -> None:
        self._trace = trace
        self.baseline = baseline or []
        self.get_full_calls: list[object] = []
        self.get_baseline_calls: list[tuple] = []

    async def get_full_trace(self, turn_id):
        self.get_full_calls.append(turn_id)
        return self._trace

    async def get_recent_comprehension(self, chat_id, *, limit=5, exclude_turn_id=None):
        self.get_baseline_calls.append((chat_id, limit, exclude_turn_id))
        return self.baseline


class _FakeEmotionalDetector:
    """Injected detector: returns the configured signal; records detect() calls."""

    def __init__(self, signal: object | Exception, min_baseline_turns: int = 5) -> None:
        self._signal = signal
        self.min_baseline_turns = min_baseline_turns
        self.calls: list[tuple] = []

    def detect(self, comprehension, baseline, decision_action):
        self.calls.append((comprehension, baseline, decision_action))
        if isinstance(self._signal, Exception):
            raise self._signal
        return self._signal


class _FakeEmotionalSignalLog:
    """In-memory emotional_signal_log writer for the hook."""

    def __init__(self) -> None:
        self.inserted: list[tuple] = []

    async def insert(self, *, turn_id, vip_id, signal):
        self.inserted.append((turn_id, vip_id, signal))


class _FakeTurnCategoryLog:
    """In-memory turn_category_log writer for the classifier hook."""

    def __init__(self) -> None:
        self.inserted: list[TurnCategoryLogRecord] = []

    async def insert(self, record: TurnCategoryLogRecord) -> TurnCategoryLogRecord:
        self.inserted.append(record)
        return record


class _FakeVipMoodState:
    """In-memory vip_mood_state store (get_by_vip/upsert) for the mood hook."""

    def __init__(self) -> None:
        self.rows: dict[UUID, VipMoodStateRecord] = {}
        self.upsert_calls: list[VipMoodStateRecord] = []

    async def get_by_vip(self, vip_id: UUID) -> VipMoodStateRecord | None:
        return self.rows.get(vip_id)

    async def upsert(self, record: VipMoodStateRecord) -> VipMoodStateRecord:
        self.upsert_calls.append(record)
        self.rows[record.vip_id] = record
        return record


class _FakeTurnClassifier:
    """Injected classifier: returns a fixed classification or raises."""

    def __init__(
        self, classification: object, *, confidence_min: float = 0.7
    ) -> None:
        self._classification = classification
        self.confidence_min = confidence_min
        self.calls: list[tuple] = []

    def classify(self, text, comprehension) -> TurnClassification:
        self.calls.append((text, comprehension))
        if isinstance(self._classification, Exception):
            raise self._classification
        return self._classification

    def is_confident(self, classification: TurnClassification) -> bool:
        return classification.confidence >= self.confidence_min


class _FakeMoodEngine:
    """Injected mood engine: fixed signal/update or raises."""

    def __init__(
        self,
        *,
        signal: MoodSignal | Exception | None = None,
        update_result: MoodState | Exception | None = None,
    ) -> None:
        self._signal = signal or MoodSignal(0.4, 0.2, 0.0)
        self._update_result = update_result or MoodState(0.5, -0.3, 0.2)
        self.signal_calls: list[object] = []
        self.update_calls: list[tuple] = []
        self.tone_calls: list[tuple] = []

    def signal_from_comprehension(self, comprehension):
        self.signal_calls.append(comprehension)
        if isinstance(self._signal, Exception):
            raise self._signal
        return self._signal

    def update(self, current, signal):
        self.update_calls.append((current, signal))
        if isinstance(self._update_result, Exception):
            raise self._update_result
        return self._update_result

    def tone_distance(self, mood, emotion) -> float:
        self.tone_calls.append((mood, emotion))
        return 0.1234

    def fork(self, *, seed: int | None = None):
        """The hook forks per-VIP for deterministic noise; the fake is a
        single-value stub, so it returns itself."""
        return self


def _classification(
    category: str = "fatico", confidence: float = 1.0, reason: str = "x"
) -> TurnClassification:
    return TurnClassification(category=category, confidence=confidence, reason=reason)


def _signal_detected(signal_type: str = "angustia") -> object:
    from diana.application.ports import EmotionalSignalRecord

    return EmotionalSignalRecord(
        signal_detected=True,
        signal_type=signal_type,
        intensity=0.85,
        should_trigger_synthesis=True,
        should_escalate_to_owner=True,
        pipeline_would_have_escalated=False,
    )


@pytest.mark.asyncio
async def test_emotional_detector_not_called_flag_off() -> None:
    """Flag OFF → emotional_detector None → hook no-op, turn flows normally."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    detector = _FakeEmotionalDetector(_signal_detected())
    signal_log = _FakeEmotionalSignalLog()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "triste"}, "vip_id": None}
        ),
        # no emotional_detector → None → hook early-returns
    )
    turn_id = await g["orch"].handle_vip_message(_vip())
    assert detector.calls == []
    assert signal_log.inserted == []
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"


@pytest.mark.asyncio
async def test_emotional_detector_writes_signal_after_turn() -> None:
    """Flag ON + signal → insert with correct turn_id; decision routing unchanged."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    detector = _FakeEmotionalDetector(_signal_detected())
    signal_log = _FakeEmotionalSignalLog()
    trace = {"comprehension": {"emotion": "triste"}, "vip_id": None}
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(trace),
        emotional_detector=detector,
        emotional_signal_log=signal_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip())
    # Detector ran after handle_turn with the trace comprehension.
    assert len(detector.calls) == 1
    assert detector.calls[0][0] == {"emotion": "triste"}
    assert detector.calls[0][2] == "approve"
    # Signal row written for the correct turn.
    assert len(signal_log.inserted) == 1
    assert signal_log.inserted[0][0] == turn_id
    # Routing unchanged: same pending_approval outcome as without the detector.
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"
    assert len(g["notifier"].drafts) == 1


@pytest.mark.asyncio
async def test_emotional_detector_error_does_not_break_turn() -> None:
    """Detector raising → the turn still completes its normal route."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    detector = _FakeEmotionalDetector(RuntimeError("detector boom"))
    signal_log = _FakeEmotionalSignalLog()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "triste"}, "vip_id": None}
        ),
        emotional_detector=detector,
        emotional_signal_log=signal_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip())
    assert signal_log.inserted == []
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"


@pytest.mark.asyncio
async def test_emotional_detector_skipped_when_no_comprehension() -> None:
    """Trace without comprehension → detector not called, no insert."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    detector = _FakeEmotionalDetector(_signal_detected())
    signal_log = _FakeEmotionalSignalLog()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader({"comprehension": None}),
        emotional_detector=detector,
        emotional_signal_log=signal_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip())
    assert detector.calls == []
    assert signal_log.inserted == []
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"


@pytest.mark.asyncio
async def test_emotional_detector_no_insert_when_signal_detected_false() -> None:
    """signal_detected=False → detector runs but NO row is inserted."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    from diana.application.ports import EmotionalSignalRecord

    no_signal = EmotionalSignalRecord(
        signal_detected=False,
        signal_type=None,
        intensity=0.0,
        pipeline_would_have_escalated=None,
    )
    detector = _FakeEmotionalDetector(no_signal)
    signal_log = _FakeEmotionalSignalLog()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "triste"}, "vip_id": None}
        ),
        emotional_detector=detector,
        emotional_signal_log=signal_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip())
    # Detector ran (guard path exercised) but nothing was written.
    assert len(detector.calls) == 1
    assert signal_log.inserted == []
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"


@pytest.mark.asyncio
async def test_emotional_detector_passes_exclude_turn_id_and_limit_to_baseline() -> None:
    """HIGH invariant: baseline is read with exclude_turn_id + limit=min_turns."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    detector = _FakeEmotionalDetector(_signal_detected(), min_baseline_turns=3)
    signal_log = _FakeEmotionalSignalLog()
    trace_reader = _FakeEmotionalTraceReader(
        {"comprehension": {"emotion": "triste"}, "vip_id": None}
    )
    g = _build(
        FakeDirector(decision),
        trace_reader=trace_reader,
        emotional_detector=detector,
        emotional_signal_log=signal_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip())
    assert len(trace_reader.get_baseline_calls) == 1
    chat_id, limit, exclude = trace_reader.get_baseline_calls[0]
    assert chat_id == 100
    assert limit == 3  # the detector's min_baseline_turns
    assert exclude == turn_id  # current turn excluded from its own baseline


@pytest.mark.asyncio
async def test_emotional_detector_skipped_when_turn_already_terminal() -> None:
    """Read-back gate: a superseded/terminal turn never gets a shadow signal."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    detector = _FakeEmotionalDetector(_signal_detected())
    signal_log = _FakeEmotionalSignalLog()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "triste"}, "vip_id": None}
        ),
        emotional_detector=detector,
        emotional_signal_log=signal_log,
    )
    turn_id = uuid4()
    await g["turns"].create(
        TurnRecord(id=turn_id, chat_id=100, status="superseded")
    )
    await g["orch"]._run_emotional_detector(turn_id, 100, decision)
    assert detector.calls == []
    assert signal_log.inserted == []


@pytest.mark.asyncio
async def test_emotional_detector_skipped_when_epoch_stale() -> None:
    """Deterministic stale-epoch gap: a superseded-by-newer-message turn is skipped.

    The read-back terminal gate only covers turns ALREADY terminal at hook
    time. A turn whose VIP epoch is no longer current (a newer message will
    supersede it via ``_apply_decision_after_director``'s epoch check right
    after the call-site) must not be logged either — the epoch gate covers
    the case the terminal read-back cannot see yet (review round 2).
    """
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    detector = _FakeEmotionalDetector(_signal_detected())
    signal_log = _FakeEmotionalSignalLog()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "triste"}, "vip_id": None}
        ),
        emotional_detector=detector,
        emotional_signal_log=signal_log,
    )
    # Advance the chat twice: the first epoch token is now stale.
    stale_epoch = g["coordinator"].bump_vip_epoch(100)
    g["coordinator"].bump_vip_epoch(100)
    assert not g["coordinator"].is_vip_epoch_current(100, stale_epoch)
    # Non-terminal turn (epoch stale is what makes it about to be superseded).
    turn_id = uuid4()
    await g["turns"].create(
        TurnRecord(id=turn_id, chat_id=100, status="deciding")
    )
    await g["orch"]._run_emotional_detector(
        turn_id, 100, decision, stale_epoch
    )
    assert detector.calls == []
    assert signal_log.inserted == []


@pytest.mark.asyncio
async def test_emotional_detector_real_detector_pipeline_escalation() -> None:
    """Real detector + hook e2e: escalate decision → angustia + p_w_h_escalated."""
    from diana.application.emotional_signal_detector import EmotionalSignalDetector

    decision = Decision(
        action="escalate", reason="risk", evaluation=_eval(), draft_text="draft A"
    )
    detector = EmotionalSignalDetector()
    signal_log = _FakeEmotionalSignalLog()
    trace = {
        "comprehension": {
            "emotion": "ansiosa",
            "urgency": "alta",
            "risk": "alto",
            "intent": "otro",
        },
        "vip_id": None,
    }
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(trace),
        emotional_detector=detector,
        emotional_signal_log=signal_log,
    )
    turn_id = uuid4()
    await g["turns"].create(TurnRecord(id=turn_id, chat_id=100, status="deciding"))
    await g["orch"]._run_emotional_detector(turn_id, 100, decision)
    assert len(signal_log.inserted) == 1
    _t, _v, sig = signal_log.inserted[0]
    assert sig.signal_type == "angustia"
    assert sig.pipeline_would_have_escalated is True
    assert sig.should_escalate_to_owner is True


# ---------------------------------------------------------------------------
# Evo-Agente Fase 1: profile-synthesis trigger hook (single call-site, A4)
# ---------------------------------------------------------------------------


class _FakeProfileSynthesisTrigger:
    """Injected trigger: records evaluate_and_maybe_enqueue calls; may raise."""

    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc
        self.calls: list[tuple] = []

    async def evaluate_and_maybe_enqueue(self, vip_id, *, text=None, signal=None):
        self.calls.append((vip_id, text, signal))
        if self._exc is not None:
            raise self._exc
        return "volume"


@pytest.mark.asyncio
async def test_profile_synthesis_trigger_not_called_flag_off() -> None:
    """Flag OFF → the orchestrator has NO trigger wired (None), so the hook
    early-returns on the guard without touching a would-be caller.

    Fix round nit: the assertion on ``g["orch"]._profile_synthesis_trigger is
    None`` makes the guard observable — it distinguishes the None wiring (flag
    OFF, byte-identical) from a swallowed AttributeError. When the fake IS
    wired (the enqueue tests below) it is genuinely invoked, so the empty
    ``calls`` here is not tautological.
    """
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    trigger = _FakeProfileSynthesisTrigger()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "triste"}, "vip_id": None}
        ),
        emotional_detector=_FakeEmotionalDetector(_signal_detected()),
        emotional_signal_log=_FakeEmotionalSignalLog(),
        # flag OFF → profile_synthesis_trigger stays None (default)
    )
    # The wiring leaves the guard None — THIS is what makes the hook inert.
    assert g["orch"]._profile_synthesis_trigger is None  # noqa: SLF001
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    assert trigger.calls == []
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"


@pytest.mark.asyncio
async def test_profile_synthesis_trigger_enqueues_on_emotional_signal() -> None:
    """Detector returns a signal → the trigger is called with it; routing unchanged."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    detector = _FakeEmotionalDetector(_signal_detected())
    signal_log = _FakeEmotionalSignalLog()
    trigger = _FakeProfileSynthesisTrigger()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "triste"}, "vip_id": str(vip_id)}
        ),
        emotional_detector=detector,
        emotional_signal_log=signal_log,
        profile_synthesis_trigger=trigger,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    # The trigger was called with the signal + the message text.
    assert len(trigger.calls) == 1
    called_vip, text, signal = trigger.calls[0]
    assert called_vip == vip_id
    assert text == "hola diana"
    assert signal is not None and signal.should_trigger_synthesis is True
    # The emotional detector also wrote its row (unchanged behavior).
    assert len(signal_log.inserted) == 1
    # Decision routing unchanged.
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"
    assert len(g["notifier"].drafts) == 1


@pytest.mark.asyncio
async def test_profile_synthesis_trigger_enqueues_on_volume_or_strong() -> None:
    """No emotional signal → trigger called with signal=None and the text."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    detector = _FakeEmotionalDetector(
        EmotionalSignalRecord(
            signal_detected=False,
            signal_type=None,
            intensity=0.0,
            should_trigger_synthesis=False,
            should_escalate_to_owner=False,
            pipeline_would_have_escalated=False,
        )
    )
    signal_log = _FakeEmotionalSignalLog()
    trigger = _FakeProfileSynthesisTrigger()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": str(vip_id)}
        ),
        emotional_detector=detector,
        emotional_signal_log=signal_log,
        profile_synthesis_trigger=trigger,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    assert len(trigger.calls) == 1
    called_vip, text, signal = trigger.calls[0]
    assert called_vip == vip_id
    assert text == "hola diana"  # volume/strong-signal share the text
    assert signal is None  # no signal to pass through
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"


@pytest.mark.asyncio
async def test_profile_synthesis_trigger_error_does_not_break_turn() -> None:
    """Trigger raising → the turn still completes its normal route."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    trigger = _FakeProfileSynthesisTrigger(exc=RuntimeError("trigger boom"))
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": None}
        ),
        profile_synthesis_trigger=trigger,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    assert len(trigger.calls) == 1  # the trigger DID run and raised
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"


# ---------------------------------------------------------------------------
# Fase 2/3 shadow hooks: turn classifier + mood engine (flag-gated, guarded)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_classifier_not_called_flag_off() -> None:
    """turn_classifier None (flag off) → no turn_category_log insert; byte-identical."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    cat_log = _FakeTurnCategoryLog()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": str(vip_id)}
        ),
        # turn_classifier stays None → the hook early-returns before any insert.
        turn_category_log=cat_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    assert g["orch"]._turn_classifier is None  # noqa: SLF001
    assert cat_log.inserted == []
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"


@pytest.mark.asyncio
async def test_mood_engine_not_called_flag_off() -> None:
    """mood_engine None (flag off) → no vip_mood_state upsert; byte-identical."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    mood_state = _FakeVipMoodState()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": str(vip_id)}
        ),
        vip_mood_state=mood_state,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    assert g["orch"]._mood_engine is None  # noqa: SLF001
    assert mood_state.upsert_calls == []
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"


@pytest.mark.asyncio
async def test_turn_classifier_logs_one_row() -> None:
    """Flag on → exactly 1 turn_category_log insert; decision routing unchanged."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    classifier = _FakeTurnClassifier(_classification("fatico", 1.0))
    cat_log = _FakeTurnCategoryLog()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": str(vip_id)}
        ),
        turn_classifier=classifier,
        turn_category_log=cat_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    assert len(cat_log.inserted) == 1
    rec = cat_log.inserted[0]
    assert rec.turn_id == turn_id
    assert rec.vip_id == vip_id
    assert rec.category == "fatico"
    assert rec.confidence == 1.0
    assert rec.would_autonomous is True
    assert len(classifier.calls) == 1
    # The classifier hook NEVER writes emotional_signal_log (no detector here).
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"
    assert len(g["notifier"].drafts) == 1


@pytest.mark.asyncio
async def test_mood_engine_upserts_state() -> None:
    """Flag on → exactly 1 vip_mood_state upsert with the 3 axes."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    mood_engine = _FakeMoodEngine()
    mood_state = _FakeVipMoodState()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": str(vip_id)}
        ),
        mood_engine=mood_engine,
        vip_mood_state=mood_state,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    assert len(mood_state.upsert_calls) == 1
    rec = mood_state.upsert_calls[0]
    assert rec.vip_id == vip_id
    assert (rec.axis_playful_serious, rec.axis_warm_distant, rec.axis_energy) == (
        0.5,
        -0.3,
        0.2,
    )
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"


@pytest.mark.asyncio
async def test_emotional_signal_log_one_row_per_turn() -> None:
    """CRITICAL anti-doble-conteo: ONE detector evaluation per turn.

    The detector fake is evaluated once (single detect() call); the classifier
    hook REUSES the same record and never writes emotional_signal_log. The same
    turn yields 1 emotional_signal_log + 1 turn_category_log, never 2 of the
    former (UNIQUE turn_id)."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    detector = _FakeEmotionalDetector(_signal_detected())
    signal_log = _FakeEmotionalSignalLog()
    classifier = _FakeTurnClassifier(_classification("fatico", 1.0))
    cat_log = _FakeTurnCategoryLog()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "triste"}, "vip_id": str(vip_id)}
        ),
        emotional_detector=detector,
        emotional_signal_log=signal_log,
        turn_classifier=classifier,
        turn_category_log=cat_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    assert len(detector.calls) == 1
    assert len(signal_log.inserted) == 1
    assert len(cat_log.inserted) == 1
    assert signal_log.inserted[0][0] == turn_id
    assert cat_log.inserted[0].turn_id == turn_id


@pytest.mark.asyncio
async def test_detector_reclassifies_phatic_to_emocional() -> None:
    """Signal (synthesis, no escalation) pulls a confident phatic → emocional."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    signal = EmotionalSignalRecord(
        signal_detected=True,
        signal_type="revelacion_de_vida",
        intensity=0.5,
        should_trigger_synthesis=True,
        should_escalate_to_owner=False,
        pipeline_would_have_escalated=False,
    )
    detector = _FakeEmotionalDetector(signal)
    signal_log = _FakeEmotionalSignalLog()
    classifier = _FakeTurnClassifier(_classification("fatico", 1.0))
    cat_log = _FakeTurnCategoryLog()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "triste"}, "vip_id": str(vip_id)}
        ),
        emotional_detector=detector,
        emotional_signal_log=signal_log,
        turn_classifier=classifier,
        turn_category_log=cat_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    rec = cat_log.inserted[0]
    assert rec.turn_id == turn_id
    assert rec.category == "emocional"
    assert rec.would_autonomous is False
    assert len(signal_log.inserted) == 1  # detector still writes exactly one row


@pytest.mark.asyncio
async def test_detector_reclassifies_to_sensitive_never_fastlane() -> None:
    """EA-03: escalation signal → sensitive, would_autonomous never True."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    detector = _FakeEmotionalDetector(_signal_detected())  # escalates to owner
    signal_log = _FakeEmotionalSignalLog()
    classifier = _FakeTurnClassifier(_classification("fatico", 1.0))
    cat_log = _FakeTurnCategoryLog()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "triste"}, "vip_id": str(vip_id)}
        ),
        emotional_detector=detector,
        emotional_signal_log=signal_log,
        turn_classifier=classifier,
        turn_category_log=cat_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    rec = cat_log.inserted[0]
    assert rec.category == "sensible"
    assert rec.would_autonomous is False


@pytest.mark.asyncio
async def test_sensitive_never_autonomous() -> None:
    """EA-03: a classifier-produced sensitive is never fast-lane."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    classifier = _FakeTurnClassifier(_classification("sensible", 1.0))
    cat_log = _FakeTurnCategoryLog()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "triste"}, "vip_id": str(vip_id)}
        ),
        turn_classifier=classifier,
        turn_category_log=cat_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    rec = cat_log.inserted[0]
    assert rec.category == "sensible"
    assert rec.would_autonomous is False


@pytest.mark.asyncio
async def test_would_autonomous_independent_of_flag() -> None:
    """A confident phatic is measured would_autonomous=True with the flag OFF.

    The orchestrator holds no feature_phatic_autonomy flag — the wiring gates
    the hook by injecting the classifier or None. would_autonomous derives only
    from (final_category == fatico) AND is_confident, so the measurement does
    not depend on the flag."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    classifier = _FakeTurnClassifier(_classification("fatico", 1.0))
    cat_log = _FakeTurnCategoryLog()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": str(vip_id)}
        ),
        turn_classifier=classifier,
        turn_category_log=cat_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    rec = cat_log.inserted[0]
    assert rec.category == "fatico"
    assert rec.confidence == 1.0
    assert rec.would_autonomous is True


@pytest.mark.asyncio
async def test_classifier_error_does_not_break_turn() -> None:
    """Classifier raising → the turn completes its normal route (pending_approval)."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    classifier = _FakeTurnClassifier(RuntimeError("classifier boom"))
    cat_log = _FakeTurnCategoryLog()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": str(vip_id)}
        ),
        turn_classifier=classifier,
        turn_category_log=cat_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    assert cat_log.inserted == []
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"
    assert len(g["notifier"].drafts) == 1


@pytest.mark.asyncio
async def test_mood_error_does_not_break_turn() -> None:
    """Mood engine raising → the turn completes its normal route."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    mood_engine = _FakeMoodEngine(update_result=RuntimeError("mood boom"))
    mood_state = _FakeVipMoodState()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": str(vip_id)}
        ),
        mood_engine=mood_engine,
        vip_mood_state=mood_state,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    assert mood_state.upsert_calls == []
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"
    assert len(g["notifier"].drafts) == 1


@pytest.mark.asyncio
async def test_non_vip_turn_skipped() -> None:
    """vip_id None (atencion channel) → no category insert nor mood upsert."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    classifier = _FakeTurnClassifier(_classification("fatico", 1.0))
    cat_log = _FakeTurnCategoryLog()
    mood_engine = _FakeMoodEngine()
    mood_state = _FakeVipMoodState()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": None}
        ),
        turn_classifier=classifier,
        turn_category_log=cat_log,
        mood_engine=mood_engine,
        vip_mood_state=mood_state,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=None))
    assert cat_log.inserted == []
    assert mood_state.upsert_calls == []
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"


# ---------------------------------------------------------------------------
# Review round 1 fixes (B1, B2, S3, S5, S6, S8, S9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sensitive_not_degraded_by_non_escalating_signal() -> None:
    """B1: an already-classified sensible is NEVER degraded to emotional by a
    non-escalating detector signal (the signal only ADDS sensibility/escalation)."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    signal = EmotionalSignalRecord(
        signal_detected=True,
        signal_type="revelacion_de_vida",
        intensity=0.5,
        should_trigger_synthesis=True,
        should_escalate_to_owner=False,
        pipeline_would_have_escalated=False,
    )
    detector = _FakeEmotionalDetector(signal)
    signal_log = _FakeEmotionalSignalLog()
    classifier = _FakeTurnClassifier(_classification("sensible", 1.0))
    cat_log = _FakeTurnCategoryLog()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "triste"}, "vip_id": str(vip_id)}
        ),
        emotional_detector=detector,
        emotional_signal_log=signal_log,
        turn_classifier=classifier,
        turn_category_log=cat_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    rec = cat_log.inserted[0]
    assert rec.turn_id == turn_id
    assert rec.category == "sensible"
    assert rec.would_autonomous is False
    assert len(signal_log.inserted) == 1  # detector still writes exactly one row


@pytest.mark.asyncio
async def test_mood_engine_skipped_when_epoch_stale() -> None:
    """B2: a non-terminal turn whose VIP epoch is stale never nudges the mood.

    The upsert being idempotent per VIP does NOT justify nudging the mood with a
    superseded turn's signal — the stale-epoch gate mirrors the classifier."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    mood_engine = _FakeMoodEngine()
    mood_state = _FakeVipMoodState()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": str(vip_id)}
        ),
        mood_engine=mood_engine,
        vip_mood_state=mood_state,
    )
    stale_epoch = g["coordinator"].bump_vip_epoch(100)
    g["coordinator"].bump_vip_epoch(100)
    assert not g["coordinator"].is_vip_epoch_current(100, stale_epoch)
    # Non-terminal turn: the epoch being stale is what makes it about to be
    # superseded (the terminal read-back cannot see that yet).
    turn_id = uuid4()
    await g["turns"].create(TurnRecord(id=turn_id, chat_id=100, status="deciding"))
    await g["orch"]._run_mood_engine(turn_id, 100, _vip(vip_id=vip_id), stale_epoch)
    assert mood_engine.signal_calls == []
    assert mood_state.upsert_calls == []


@pytest.mark.asyncio
async def test_mood_engine_skipped_when_turn_already_terminal() -> None:
    """S6: a terminal turn never nudges the mood (read-back gate)."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    mood_engine = _FakeMoodEngine()
    mood_state = _FakeVipMoodState()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": str(vip_id)}
        ),
        mood_engine=mood_engine,
        vip_mood_state=mood_state,
    )
    turn_id = uuid4()
    await g["turns"].create(TurnRecord(id=turn_id, chat_id=100, status="superseded"))
    await g["orch"]._run_mood_engine(turn_id, 100, _vip(vip_id=vip_id))
    assert mood_engine.signal_calls == []
    assert mood_state.upsert_calls == []


@pytest.mark.asyncio
async def test_mood_engine_skipped_when_no_comprehension() -> None:
    """S6: no comprehension in the trace → no mood upsert."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    mood_engine = _FakeMoodEngine()
    mood_state = _FakeVipMoodState()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader({"comprehension": None}),
        mood_engine=mood_engine,
        vip_mood_state=mood_state,
    )
    await g["orch"]._run_mood_engine(uuid4(), 100, _vip(vip_id=vip_id))
    assert mood_engine.signal_calls == []
    assert mood_state.upsert_calls == []


@pytest.mark.asyncio
async def test_turn_classifier_skipped_when_turn_already_terminal() -> None:
    """S6: a terminal turn never gets a turn_category_log row."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    classifier = _FakeTurnClassifier(_classification("fatico", 1.0))
    cat_log = _FakeTurnCategoryLog()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": str(vip_id)}
        ),
        turn_classifier=classifier,
        turn_category_log=cat_log,
    )
    turn_id = uuid4()
    await g["turns"].create(TurnRecord(id=turn_id, chat_id=100, status="superseded"))
    await g["orch"]._run_turn_classifier(
        turn_id, 100, _vip(vip_id=vip_id), None
    )
    assert classifier.calls == []
    assert cat_log.inserted == []


@pytest.mark.asyncio
async def test_turn_classifier_skipped_when_epoch_stale() -> None:
    """S6: a stale-epoch turn never gets a turn_category_log row."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    classifier = _FakeTurnClassifier(_classification("fatico", 1.0))
    cat_log = _FakeTurnCategoryLog()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": str(vip_id)}
        ),
        turn_classifier=classifier,
        turn_category_log=cat_log,
    )
    stale_epoch = g["coordinator"].bump_vip_epoch(100)
    g["coordinator"].bump_vip_epoch(100)
    assert not g["coordinator"].is_vip_epoch_current(100, stale_epoch)
    turn_id = uuid4()
    await g["turns"].create(TurnRecord(id=turn_id, chat_id=100, status="deciding"))
    await g["orch"]._run_turn_classifier(
        turn_id, 100, _vip(vip_id=vip_id), None, stale_epoch
    )
    assert classifier.calls == []
    assert cat_log.inserted == []


@pytest.mark.asyncio
async def test_turn_classifier_skipped_when_no_comprehension() -> None:
    """S6: no comprehension in the trace → no turn_category_log row."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    classifier = _FakeTurnClassifier(_classification("fatico", 1.0))
    cat_log = _FakeTurnCategoryLog()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader({"comprehension": None}),
        turn_classifier=classifier,
        turn_category_log=cat_log,
    )
    await g["orch"]._run_turn_classifier(
        uuid4(), 100, _vip(vip_id=vip_id), None
    )
    assert classifier.calls == []
    assert cat_log.inserted == []


@pytest.mark.asyncio
async def test_phatic_not_confident_not_autonomous() -> None:
    """S8: a fático no-confident (0.3) → would_autonomous=False at hook level
    (the classifier gate and the is_confident check are both exercised)."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    classifier = _FakeTurnClassifier(_classification("fatico", 0.3))
    cat_log = _FakeTurnCategoryLog()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "neutral"}, "vip_id": str(vip_id)}
        ),
        turn_classifier=classifier,
        turn_category_log=cat_log,
    )
    turn_id = await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
    rec = cat_log.inserted[0]
    assert rec.turn_id == turn_id
    assert rec.category == "fatico"
    assert rec.confidence == 0.3
    assert rec.would_autonomous is False


@pytest.mark.asyncio
async def test_mood_engine_continuity_across_two_turns() -> None:
    """S9: moving-average continuity — the 2nd update receives the 1st result
    as ``current`` (the fake repo stores the upserted row, and the hook reads it
    back before the next update)."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    mood_engine = _FakeMoodEngine(update_result=MoodState(0.5, -0.3, 0.2))
    mood_state = _FakeVipMoodState()
    vip_id = uuid4()
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "positiva"}, "vip_id": str(vip_id)}
        ),
        mood_engine=mood_engine,
        vip_mood_state=mood_state,
    )
    incoming = _vip(vip_id=vip_id)
    await g["orch"]._run_mood_engine(uuid4(), 100, incoming)
    await g["orch"]._run_mood_engine(uuid4(), 100, incoming)
    assert len(mood_engine.signal_calls) == 2
    assert len(mood_engine.update_calls) == 2
    # First update ran from base (no prior state).
    assert mood_engine.update_calls[0][0] is None
    # Second update received the FIRST result (stored by the fake repo) as current.
    second_current = mood_engine.update_calls[1][0]
    assert second_current is not None
    assert second_current.axis_playful_serious == 0.5
    assert second_current.axis_warm_distant == -0.3
    assert second_current.axis_energy == 0.2


@pytest.mark.asyncio
async def test_mood_tone_distance_uses_pre_update_state() -> None:
    """S3: tone_distance is measured against the PRE-update mood (current), not
    the just-computed ``updated`` state — tone deviation from where the mood
    already was."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    mood_engine = _FakeMoodEngine(update_result=MoodState(0.5, -0.3, 0.2))
    mood_state = _FakeVipMoodState()
    vip_id = uuid4()
    # Pre-existing mood distinct from the update result.
    mood_state.rows[vip_id] = VipMoodStateRecord(
        vip_id=vip_id,
        axis_playful_serious=0.9,
        axis_warm_distant=0.9,
        axis_energy=0.9,
        updated_at=None,
    )
    g = _build(
        FakeDirector(decision),
        trace_reader=_FakeEmotionalTraceReader(
            {"comprehension": {"emotion": "triste"}, "vip_id": str(vip_id)}
        ),
        mood_engine=mood_engine,
        vip_mood_state=mood_state,
    )
    await g["orch"]._run_mood_engine(uuid4(), 100, _vip(vip_id=vip_id))
    assert len(mood_engine.tone_calls) == 1
    measured = mood_engine.tone_calls[0][0]
    assert measured.axis_playful_serious == 0.9
    assert measured.axis_warm_distant == 0.9
    assert measured.axis_energy == 0.9


@pytest.mark.asyncio
async def test_mood_engine_per_vip_deterministic_seed() -> None:
    """S5: two separately-built orchestrators (each with an UNSEEDED prototype
    mood engine) reproduce the SAME mood for the same VIP — the hook forks a
    stable per-VIP seed, so the bounded noise is deterministic (F3 stable axes).
    Without the fork this fails: two ``random.Random(None)`` diverge."""
    decision = Decision(
        action="approve", reason="good", evaluation=_eval(), draft_text="draft A"
    )
    vip_id = uuid4()

    async def run_once() -> tuple[float, float, float]:
        mood_engine = MoodEngine(return_rate=0.1, signal_weight=0.5, noise=0.05)
        mood_state = _FakeVipMoodState()
        g = _build(
            FakeDirector(decision),
            trace_reader=_FakeEmotionalTraceReader(
                {"comprehension": {"emotion": "positiva"}, "vip_id": str(vip_id)}
            ),
            mood_engine=mood_engine,
            vip_mood_state=mood_state,
        )
        await g["orch"].handle_vip_message(_vip(vip_id=vip_id))
        rec = mood_state.upsert_calls[-1]
        return (
            rec.axis_playful_serious,
            rec.axis_warm_distant,
            rec.axis_energy,
        )

    first = await run_once()
    second = await run_once()
    assert first == second
