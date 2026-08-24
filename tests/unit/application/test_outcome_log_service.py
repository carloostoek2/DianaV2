"""Unit tests for the Fila 4 outcome-log service (Fase A: coincidence)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from diana.application.outcome_log_service import (
    OutcomeLogService,
    compute_blocked_dims,
    derive_owner_outcome,
    shadow_verdict_from_decision,
)
from diana.application.ports import TurnCategoryLogRecord, TurnOutcomeLogRecord, VipTrustBudgetRecord
from diana.application.trust_budget_service import TrustBudgetService
from diana.cognitive.decider import Decider
from diana.cognitive.models import Decision, EvaluationProfile


def _evaluation(**overrides: float) -> dict:
    base = {
        "naturalness": 0.8,
        "precision": 0.8,
        "doctrine": 0.8,
        "consistency": 0.8,
        "safety": 0.95,
        "coverage": 0.8,
        "empathy": 0.8,
    }
    base.update(overrides)
    return base


def _comprehension() -> dict:
    return {
        "intent": "preguntar",
        "topics": [],
        "emotion": "neutral",
        "urgency": "media",
        "risk": "bajo",
        "needs_memory": False,
        "needs_policy": False,
        "needs_schedule": False,
        "needs_examples": False,
        "needs_history": False,
        "needs_context": False,
    }


class FakeSource:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def list_finished_source_turns(self, *, window_days: int, limit: int = 200):
        return self._rows


class TestShadowVerdictMapping:
    def test_send(self) -> None:
        decision = Decision(
            action="send", reason="autonomous_ok", evaluation=EvaluationProfile(**_evaluation())
        )
        assert shadow_verdict_from_decision(decision) == ("send", "autonomous_ok")

    def test_escalate(self) -> None:
        decision = Decision(
            action="escalate", reason="risk_high", evaluation=EvaluationProfile(**_evaluation())
        )
        assert shadow_verdict_from_decision(decision) == ("escalate", "risk_high")

    def test_doctrine(self) -> None:
        decision = Decision(
            action="consult_doctrine", reason="doctrine_not_found", evaluation=EvaluationProfile(**_evaluation())
        )
        assert shadow_verdict_from_decision(decision) == ("doctrine", "doctrine_not_found")

    def test_approve_is_blocked(self) -> None:
        decision = Decision(
            action="approve", reason="autonomous_below_threshold", evaluation=EvaluationProfile(**_evaluation())
        )
        assert shadow_verdict_from_decision(decision) == ("blocked", "autonomous_below_threshold")


class TestDeriveOwnerOutcome:
    def test_escalated(self) -> None:
        assert derive_owner_outcome("escalated", "cancelled", False) == "escalated"

    def test_delivered_corrected_via_staging(self) -> None:
        assert derive_owner_outcome("delivered", "corrected", True) == "corrected"

    def test_delivered_corrected_via_approval_status(self) -> None:
        assert derive_owner_outcome("delivered", "corrected", False) == "corrected"

    def test_delivered_approved_as_is(self) -> None:
        assert derive_owner_outcome("delivered", "approved", False) == "approved_as_is"

    def test_open_turn_is_none(self) -> None:
        assert derive_owner_outcome("pending_approval", "waiting", False) is None
        assert derive_owner_outcome("superseded", None, False) is None
        assert derive_owner_outcome("failed", None, False) is None


class TestComputeBlockedDims:
    def test_all_met_no_blocked(self) -> None:
        evaluation = EvaluationProfile(**_evaluation())
        assert compute_blocked_dims(evaluation, (0.9, 0.8, 0.7)) == []

    def test_low_safety_only(self) -> None:
        evaluation = EvaluationProfile(**_evaluation(safety=0.5))
        assert compute_blocked_dims(evaluation, (0.9, 0.8, 0.7)) == ["safety"]

    def test_low_doctrine_and_naturalness(self) -> None:
        evaluation = EvaluationProfile(**_evaluation(doctrine=0.3, naturalness=0.2))
        assert sorted(compute_blocked_dims(evaluation, (0.9, 0.8, 0.7))) == [
            "doctrine",
            "naturalness",
        ]


def _make_service(source: FakeSource) -> OutcomeLogService:
    decider = Decider(feature_autonomous_mode=True)
    return OutcomeLogService(decider=decider, source=source)


def _row(
    *,
    status: str = "delivered",
    approval_status: str | None = "approved",
    evaluation: dict | None = None,
    corrected_text: str | None = None,
    comprehension: dict | None = None,
) -> dict:
    return {
        "turn_id": uuid4(),
        "vip_id": uuid4(),
        "chat_id": 123,
        "status": status,
        "created_at": datetime.now(UTC),
        "draft": "Hola, ¿cómo estás?",
        "evaluation": evaluation or _evaluation(),
        "comprehension": comprehension or _comprehension(),
        "retrieved": {},
        "decision": {"action": "approve", "reason": "ok_for_human_review"},
        "approval_status": approval_status,
        "corrected_text": corrected_text,
        "has_staging_correction": corrected_text is not None,
    }


class TestListComparativas:
    def test_acierto(self) -> None:
        service = _make_service(FakeSource([_row()]))
        rows = asyncio.run(service.list_comparativas())
        assert rows[0].shadow_verdict == "send"
        assert rows[0].owner_outcome == "approved_as_is"
        assert rows[0].label == "acierto"

    def test_desacuerdo_correction(self) -> None:
        service = _make_service(FakeSource([_row(corrected_text="Mejor así")]))
        rows = asyncio.run(service.list_comparativas())
        assert rows[0].label == "desacuerdo"
        assert rows[0].corrected_text == "Mejor así"

    def test_conservadora(self) -> None:
        service = _make_service(FakeSource([_row(evaluation=_evaluation(safety=0.5))]))
        rows = asyncio.run(service.list_comparativas())
        assert rows[0].shadow_verdict == "blocked"
        assert rows[0].owner_outcome == "approved_as_is"
        assert rows[0].label == "conservadora"
        assert rows[0].extra["blocked_dims"] == ["safety"]

    def test_escalated_owner(self) -> None:
        service = _make_service(FakeSource([_row(status="escalated", approval_status="cancelled")]))
        rows = asyncio.run(service.list_comparativas())
        assert rows[0].owner_outcome == "escalated"
        assert rows[0].label == "desacuerdo"  # shadow said send, owner escalated

    def test_unparseable_evaluation_yields_none(self) -> None:
        service = _make_service(FakeSource([_row(evaluation={"weird": 1})]))
        rows = asyncio.run(service.list_comparativas())
        assert rows[0].shadow_verdict is None
        assert rows[0].label is None


class TestCoincidenceSummary:
    def test_rate_and_counts(self) -> None:
        rows = [
            _row(),  # acierto
            _row(),  # acierto
            _row(corrected_text="x"),  # desacuerdo
            _row(evaluation=_evaluation(safety=0.5)),  # conservadora
        ]
        service = _make_service(FakeSource(rows))
        summary = asyncio.run(service.coincidence_summary())
        assert summary["n"] == 4
        assert summary["aciertos"] == 2
        assert summary["desacuerdos"] == 1
        assert summary["conservadora"] == 1
        assert summary["rate"] == pytest.approx(2 / 3)
        assert len(summary["desacuerdos_list"]) == 1

    def test_empty_denominator_rate_none(self) -> None:
        service = _make_service(FakeSource([_row(evaluation=_evaluation(safety=0.5))]))
        summary = asyncio.run(service.coincidence_summary())
        assert summary["rate"] is None


# ---------------------------------------------------------------------------
# Fase B — persistent ledger writes (fake store, no DB)
# ---------------------------------------------------------------------------


class FakeOutcomeStore:
    """In-memory TurnOutcomeLogStore for service tests."""

    def __init__(self) -> None:
        self.rows: dict = {}
        self.outcome_calls: list[tuple] = []
        self.signal_calls: list[tuple] = []

    async def insert(self, record):
        self.rows[str(record.turn_id)] = record
        return record

    async def get_by_turn_id(self, turn_id):
        return self.rows.get(str(turn_id))

    async def update_outcome(self, turn_id, *, owner_outcome, sent_score, quality_delta):
        rec = self.rows.get(str(turn_id))
        if rec is None:
            return None
        updated = rec.model_copy(
            update={
                "owner_outcome": owner_outcome,
                "sent_score": sent_score,
                "quality_delta": quality_delta,
            }
        )
        self.rows[str(turn_id)] = updated
        return updated

    async def update_signal(self, turn_id, *, vip_signal):
        rec = self.rows.get(str(turn_id))
        if rec is None:
            return None
        updated = rec.model_copy(update={"vip_signal": vip_signal})
        self.rows[str(turn_id)] = updated
        return updated

    async def list_by_vip_since(self, vip_id, *, since, limit=200):
        return []

    async def list_recent(self, *, since, limit=500):
        return list(self.rows.values())

    async def count_safety_escalations_since(self, *, since):
        return 0


class FakeTrustBudget:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def record_outcome(self, turn_id, *, event, value):
        self.calls.append((str(turn_id), event, value))
        return object()


def _fase_b_service(store, trust_budget, scorer=None):
    decider = Decider(feature_autonomous_mode=True)
    return OutcomeLogService(
        decider=decider,
        store=store,
        scorer=scorer,
        trust_budget=trust_budget,
        enabled=True,
    )


def _trace(
    *,
    evaluation: dict | None = None,
    draft: str = "Hola, ¿cómo estás?",
    comprehension: dict | None = None,
) -> dict:
    return {
        "evaluation": evaluation or _evaluation(),
        "comprehension": comprehension or _comprehension(),
        "retrieved": {},
        "generated_text": draft,
    }


def _label_events(trust: FakeTrustBudget) -> list[tuple[str, str]]:
    return [(event, value) for _turn, event, value in trust.calls]


class _MemoryVipTrustBudgetStore:
    """In-memory store replicating SQL repo clamp + counters (copied, not imported)."""

    def __init__(self) -> None:
        self.rows: dict[tuple, VipTrustBudgetRecord] = {}

    async def get_by_vip_and_category(self, vip_id, turn_category):
        return self.rows.get((vip_id, turn_category))

    async def increment_autonomous(self, vip_id, turn_category, *, delta, initial):
        key = (vip_id, turn_category)
        current = self.rows.get(key)
        if current is None:
            record = VipTrustBudgetRecord(
                vip_id=vip_id,
                turn_category=turn_category,
                trust_score=min(1.0, max(0.0, float(initial) + float(delta))),
                autonomous_count=1,
            )
        else:
            record = current.model_copy(
                update={
                    "trust_score": min(1.0, max(0.0, current.trust_score + float(delta))),
                    "autonomous_count": current.autonomous_count + 1,
                }
            )
        self.rows[key] = record
        return record

    async def decrement_correction(
        self, vip_id, turn_category, *, delta, initial, correction_time
    ):
        key = (vip_id, turn_category)
        current = self.rows.get(key)
        if current is None:
            record = VipTrustBudgetRecord(
                vip_id=vip_id,
                turn_category=turn_category,
                trust_score=min(1.0, max(0.0, float(initial) - float(delta))),
                correction_count=1,
                last_correction_at=correction_time,
            )
        else:
            record = current.model_copy(
                update={
                    "trust_score": min(1.0, max(0.0, current.trust_score - float(delta))),
                    "correction_count": current.correction_count + 1,
                    "last_correction_at": correction_time,
                }
            )
        self.rows[key] = record
        return record

    async def list_by_vip(self, vip_id):
        return [r for (vid, _cat), r in self.rows.items() if vid == vip_id]


class _FakeTurnCategoryLogReader:
    def __init__(self, rows: dict | None = None) -> None:
        self.rows: dict = dict(rows or {})

    async def get_by_turn_id(self, turn_id):
        return self.rows.get(turn_id)


def _log_record(*, turn_id, vip_id, category="informativo"):
    return TurnCategoryLogRecord(
        turn_id=turn_id,
        vip_id=vip_id,
        chat_id=100,
        category=category,
        would_autonomous=True,
    )


def _real_trust_budget(store, cat_log) -> TrustBudgetService:
    return TrustBudgetService(
        store=store,
        turn_category_log=cat_log,
        increment=0.05,
        decrement=0.2,
        initial=0.2,
    )


class TestRecordShadow:
    def test_writes_verdict_and_score(self) -> None:
        store = FakeOutcomeStore()
        svc = _fase_b_service(store, FakeTrustBudget(), scorer=lambda text, vip_name=None: 0.8)
        turn_id = uuid4()
        vip_id = uuid4()

        asyncio.run(svc.record_shadow(turn_id, vip_id=vip_id, trace=_trace()))

        rec = store.rows[str(turn_id)]
        assert rec.shadow_verdict == "send"
        assert rec.draft_score == pytest.approx(0.8)
        assert rec.owner_outcome is None

    def test_blocked_with_dims(self) -> None:
        store = FakeOutcomeStore()
        svc = _fase_b_service(store, FakeTrustBudget())
        turn_id = uuid4()

        asyncio.run(
            svc.record_shadow(turn_id, vip_id=uuid4(), trace=_trace(evaluation=_evaluation(safety=0.5)))
        )

        rec = store.rows[str(turn_id)]
        assert rec.shadow_verdict == "blocked"
        assert rec.blocked_dims == ["safety"]

    def test_disabled_is_noop(self) -> None:
        store = FakeOutcomeStore()
        svc = OutcomeLogService(
            decider=Decider(feature_autonomous_mode=True),
            store=store,
            enabled=False,
        )
        asyncio.run(svc.record_shadow(uuid4(), vip_id=uuid4(), trace=_trace()))
        assert store.rows == {}

    def test_no_trace_is_noop(self) -> None:
        store = FakeOutcomeStore()
        svc = _fase_b_service(store, FakeTrustBudget())
        asyncio.run(svc.record_shadow(uuid4(), vip_id=uuid4(), trace=None))
        assert store.rows == {}


class TestRecordOwnerOutcome:
    def test_corrected_computes_delta(self) -> None:
        store = FakeOutcomeStore()
        trust = FakeTrustBudget()
        svc = _fase_b_service(
            store, trust, scorer=lambda text, vip_name=None: (0.9 if "mejor" in text else 0.7)
        )
        turn_id = uuid4()
        vip_id = uuid4()
        asyncio.run(svc.record_shadow(turn_id, vip_id=vip_id, trace=_trace(draft="borrador")))

        updated = asyncio.run(
            svc.record_owner_outcome(
                turn_id, owner_outcome="corrected", sent_text="mejor texto", vip_id=vip_id
            )
        )

        assert updated is not None
        assert updated.owner_outcome == "corrected"
        assert updated.sent_score == pytest.approx(0.9)
        assert updated.quality_delta == pytest.approx(0.9 - 0.7)
        events = _label_events(trust)
        assert ("label", "desacuerdo") in events
        assert ("label", "corrected") not in events

    def test_approved_as_is_is_acierto(self) -> None:
        store = FakeOutcomeStore()
        trust = FakeTrustBudget()
        svc = _fase_b_service(store, trust)
        turn_id = uuid4()
        vip_id = uuid4()
        asyncio.run(svc.record_shadow(turn_id, vip_id=vip_id, trace=_trace(draft="borrador")))

        asyncio.run(
            svc.record_owner_outcome(
                turn_id,
                owner_outcome="approved_as_is",
                sent_text="borrador",
                vip_id=vip_id,
            )
        )

        events = _label_events(trust)
        assert events == [("label", "acierto")]
        assert ("label", "approved_as_is") not in events

    def test_escalated_has_no_sent_score(self) -> None:
        store = FakeOutcomeStore()
        trust = FakeTrustBudget()
        svc = _fase_b_service(store, trust)
        turn_id = uuid4()
        asyncio.run(svc.record_shadow(turn_id, vip_id=uuid4(), trace=_trace()))

        updated = asyncio.run(
            svc.record_owner_outcome(turn_id, owner_outcome="escalated", sent_text=None, vip_id=uuid4())
        )

        assert updated.owner_outcome == "escalated"
        assert updated.sent_score is None
        assert updated.quality_delta is None
        events = _label_events(trust)
        assert ("label", "desacuerdo") in events
        assert ("label", "escalated") not in events

    def test_blocked_approved_is_conservadora(self) -> None:
        store = FakeOutcomeStore()
        trust = FakeTrustBudget()
        svc = _fase_b_service(store, trust)
        turn_id = uuid4()
        vip_id = uuid4()
        asyncio.run(
            svc.record_shadow(
                turn_id,
                vip_id=vip_id,
                trace=_trace(evaluation=_evaluation(safety=0.5)),
            )
        )
        assert store.rows[str(turn_id)].shadow_verdict == "blocked"

        asyncio.run(
            svc.record_owner_outcome(
                turn_id, owner_outcome="approved_as_is", sent_text="ok", vip_id=vip_id
            )
        )

        assert _label_events(trust) == [("label", "conservadora")]

    def test_blocked_corrected_skips_trust(self) -> None:
        store = FakeOutcomeStore()
        trust = FakeTrustBudget()
        svc = _fase_b_service(store, trust)
        turn_id = uuid4()
        vip_id = uuid4()
        asyncio.run(
            svc.record_shadow(
                turn_id,
                vip_id=vip_id,
                trace=_trace(evaluation=_evaluation(safety=0.5)),
            )
        )

        asyncio.run(
            svc.record_owner_outcome(
                turn_id, owner_outcome="corrected", sent_text="otro", vip_id=vip_id
            )
        )

        assert _label_events(trust) == []

    def test_doctrine_approved_is_conservadora(self) -> None:
        store = FakeOutcomeStore()
        trust = FakeTrustBudget()
        svc = _fase_b_service(store, trust)
        turn_id = uuid4()
        vip_id = uuid4()
        asyncio.run(
            store.insert(
                TurnOutcomeLogRecord(
                    turn_id=turn_id,
                    vip_id=vip_id,
                    shadow_verdict="doctrine",
                    shadow_reason="doctrine_not_found",
                )
            )
        )

        asyncio.run(
            svc.record_owner_outcome(
                turn_id, owner_outcome="approved_as_is", sent_text="ok", vip_id=vip_id
            )
        )

        assert _label_events(trust) == [("label", "conservadora")]

    def test_escalate_approved_is_conservadora(self) -> None:
        store = FakeOutcomeStore()
        trust = FakeTrustBudget()
        svc = _fase_b_service(store, trust)
        turn_id = uuid4()
        vip_id = uuid4()
        comprehension = _comprehension()
        comprehension["risk"] = "alto"
        asyncio.run(
            svc.record_shadow(
                turn_id, vip_id=vip_id, trace=_trace(comprehension=comprehension)
            )
        )
        assert store.rows[str(turn_id)].shadow_verdict == "escalate"

        asyncio.run(
            svc.record_owner_outcome(
                turn_id, owner_outcome="approved_as_is", sent_text="ok", vip_id=vip_id
            )
        )

        assert _label_events(trust) == [("label", "conservadora")]

    def test_missing_shadow_skips_trust(self) -> None:
        store = FakeOutcomeStore()
        trust = FakeTrustBudget()
        svc = _fase_b_service(store, trust)
        turn_id = uuid4()
        vip_id = uuid4()
        asyncio.run(
            store.insert(
                TurnOutcomeLogRecord(
                    turn_id=turn_id, vip_id=vip_id, shadow_verdict=None
                )
            )
        )

        asyncio.run(
            svc.record_owner_outcome(
                turn_id,
                owner_outcome="approved_as_is",
                sent_text="ok",
                vip_id=vip_id,
            )
        )

        assert _label_events(trust) == []

    def test_real_trust_budget_desacuerdo_decrements(self) -> None:
        """send × corrected maps to desacuerdo → 0.2 − 0.2 = 0.0 (no prior increment)."""
        store = FakeOutcomeStore()
        budget_store = _MemoryVipTrustBudgetStore()
        turn_id = uuid4()
        vip_id = uuid4()
        trust = _real_trust_budget(
            budget_store,
            _FakeTurnCategoryLogReader(
                {turn_id: _log_record(turn_id=turn_id, vip_id=vip_id)}
            ),
        )
        svc = _fase_b_service(store, trust)
        asyncio.run(svc.record_shadow(turn_id, vip_id=vip_id, trace=_trace()))

        asyncio.run(
            svc.record_owner_outcome(
                turn_id, owner_outcome="corrected", sent_text="otro", vip_id=vip_id
            )
        )

        rec = budget_store.rows.get((vip_id, "informativo"))
        assert rec is not None
        assert rec.trust_score == pytest.approx(0.0)

    def test_real_trust_budget_acierto_increments(self) -> None:
        """send × approved_as_is maps to acierto → 0.2 + 0.05 = 0.25."""
        store = FakeOutcomeStore()
        budget_store = _MemoryVipTrustBudgetStore()
        turn_id = uuid4()
        vip_id = uuid4()
        trust = _real_trust_budget(
            budget_store,
            _FakeTurnCategoryLogReader(
                {turn_id: _log_record(turn_id=turn_id, vip_id=vip_id)}
            ),
        )
        svc = _fase_b_service(store, trust)
        asyncio.run(svc.record_shadow(turn_id, vip_id=vip_id, trace=_trace()))

        asyncio.run(
            svc.record_owner_outcome(
                turn_id,
                owner_outcome="approved_as_is",
                sent_text="Hola, ¿cómo estás?",
                vip_id=vip_id,
            )
        )

        rec = budget_store.rows.get((vip_id, "informativo"))
        assert rec is not None
        assert rec.trust_score == pytest.approx(0.25)


class TestRecordReaction:
    def test_signal_persisted_and_trust_event(self) -> None:
        store = FakeOutcomeStore()
        trust = FakeTrustBudget()
        svc = _fase_b_service(store, trust)
        turn_id = uuid4()
        asyncio.run(svc.record_shadow(turn_id, vip_id=uuid4(), trace=_trace()))

        updated = asyncio.run(svc.record_reaction(turn_id, vip_signal="negative"))

        assert updated.vip_signal == "negative"
        assert trust.calls[-1] == (str(turn_id), "signal", "negative")

