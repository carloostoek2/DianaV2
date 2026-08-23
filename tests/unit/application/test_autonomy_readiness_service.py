"""Unit tests for AutonomyReadinessService (C5 panel + C6 gate, no DB)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4


from diana.application.autonomy_readiness_service import AutonomyReadinessService
from diana.application.outcome_log_service import OutcomeLogService
from diana.application.ports import VipRecord
from diana.cognitive.decider import Decider


class FakeSource:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def list_finished_source_turns(self, *, window_days: int, limit: int = 200):
        return self._rows


class FakeStore:
    """Minimal outcome store for the readiness service reads."""

    def __init__(self, rows: list | None = None) -> None:
        self.rows = list(rows or [])

    async def list_recent(self, *, since, limit=500):
        return self.rows

    async def count_safety_escalations_since(self, *, since):
        return sum(
            1 for r in self.rows if r.shadow_reason == "safety_below_threshold"
        )

    async def list_by_vip_since(self, vip_id, *, since, limit=200):
        return [r for r in self.rows if r.vip_id == vip_id]


class FakeTrustReader:
    def __init__(self, rows: list) -> None:
        self.rows = rows

    async def list_all(self):
        return self.rows


class FakeVipStore:
    def __init__(self, vips: list[VipRecord]) -> None:
        self.vips = {v.id: v for v in vips}
        self.auto_send: dict[UUID, bool] = {}

    async def list_active(self):
        return list(self.vips.values())

    async def get_by_id(self, vip_id):
        return self.vips.get(vip_id)

    async def set_auto_send(self, vip_id, enabled):
        if vip_id not in self.vips:
            return False
        self.auto_send[vip_id] = bool(enabled)
        return True


def _vip(vip_id: UUID, name: str = "Ana") -> VipRecord:
    return VipRecord(id=vip_id, telegram_user_id=123, display_name=name)


def _eval(**overrides) -> dict:
    base = {
        "naturalness": 0.8, "precision": 0.8, "doctrine": 0.8, "consistency": 0.8,
        "safety": 0.95, "coverage": 0.8, "empathy": 0.8,
    }
    base.update(overrides)
    return base


def _comp() -> dict:
    return {
        "intent": "preguntar", "topics": [], "emotion": "neutral", "urgency": "media",
        "risk": "bajo", "needs_memory": False, "needs_policy": False,
        "needs_schedule": False, "needs_examples": False, "needs_history": False,
        "needs_context": False,
    }


def _finished_row(*, status="delivered", approval_status="approved", evaluation=None,
                  corrected_text=None) -> dict:
    return {
        "turn_id": uuid4(), "vip_id": uuid4(), "chat_id": 1, "status": status,
        "created_at": datetime.now(UTC), "draft": "Hola",
        "evaluation": evaluation or _eval(), "comprehension": _comp(),
        "retrieved": {}, "decision": {"action": "approve"},
        "approval_status": approval_status, "corrected_text": corrected_text,
        "has_staging_correction": corrected_text is not None,
    }


def _make_service(source_rows, trust_rows, vips, *, recommendation_enabled=False):
    outcome = OutcomeLogService(
        decider=Decider(feature_autonomous_mode=True),
        store=FakeStore(),
        source=FakeSource(source_rows),
    )
    return AutonomyReadinessService(
        outcome=outcome,
        trust=FakeTrustReader(trust_rows),
        vips=vips,
        recommendation_enabled=recommendation_enabled,
    ), outcome, vips


class TestGlobalAndComparativas:
    def test_global_render_with_data(self) -> None:
        source = [
            _finished_row(),  # acierto (send × approved_as_is)
            _finished_row(),  # acierto
            _finished_row(corrected_text="mejor"),  # desacuerdo
            _finished_row(evaluation=_eval(safety=0.5)),  # conservadora (blocked)
        ]
        service, _, _ = _make_service(source, [], FakeVipStore([]))
        body = asyncio.run(service.render_global())
        assert "Coincidencia" in body
        assert "67%" in body  # 2/3

    def test_comparativas_lists_disagreements(self) -> None:
        source = [
            _finished_row(corrected_text="Mejor así"),
            _finished_row(),
        ]
        service, _, _ = _make_service(source, [], FakeVipStore([]))
        body = asyncio.run(service.render_comparativas())
        assert "Mejor así" in body
        assert "aciertos" in body


class TestRecommendationGate:
    def test_ready_when_all_conditions_met(self) -> None:
        vip = uuid4()
        # 19 aciertos + 1 desacuerdo → rate 19/20 = 0.95 (meta alcanzada).
        source = [{**_finished_row(), "vip_id": vip} for _ in range(19)]
        source.append({**_finished_row(corrected_text="x"), "vip_id": vip})
        trust = [type("R", (), {"vip_id": vip, "turn_category": "informativo",
                                "trust_score": 0.95, "autonomous_count": 3,
                                "correction_count": 0})()]
        service, _, vips = _make_service(
            source, trust, FakeVipStore([_vip(vip)]), recommendation_enabled=True
        )
        readiness = asyncio.run(service.recommendation(vip))
        assert readiness is not None
        assert readiness.ready is True

    def test_not_ready_low_trust(self) -> None:
        vip = uuid4()
        source = [_finished_row(), _finished_row()]
        trust = [type("R", (), {"vip_id": vip, "turn_category": "informativo",
                                "trust_score": 0.4, "autonomous_count": 0,
                                "correction_count": 1})()]
        service, _, _ = _make_service(source, trust, FakeVipStore([_vip(vip)]))
        readiness = asyncio.run(service.recommendation(vip))
        assert readiness is not None
        assert readiness.ready is False
        assert "confianza" in service._not_ready_reason(readiness)

    def test_not_ready_low_coincidence(self) -> None:
        vip = uuid4()
        source = [
            {**_finished_row(corrected_text="x"), "vip_id": vip},
            {**_finished_row(corrected_text="y"), "vip_id": vip},
        ]  # 0 aciertos / 2 desacuerdos → rate 0
        trust = [type("R", (), {"vip_id": vip, "turn_category": "informativo",
                                "trust_score": 0.95, "autonomous_count": 5,
                                "correction_count": 0})()]
        service, _, _ = _make_service(source, trust, FakeVipStore([_vip(vip)]))
        readiness = asyncio.run(service.recommendation(vip))
        assert readiness is not None
        assert readiness.ready is False

    def test_not_ready_safety_escalation(self) -> None:
        vip = uuid4()
        source = [
            {**_finished_row(evaluation=_eval(safety=0.1)), "vip_id": vip},
            _finished_row(),
        ]
        trust = [type("R", (), {"vip_id": vip, "turn_category": "informativo",
                                "trust_score": 0.95, "autonomous_count": 5,
                                "correction_count": 0})()]
        service, _, _ = _make_service(source, trust, FakeVipStore([_vip(vip)]))
        readiness = asyncio.run(service.recommendation(vip))
        assert readiness is not None
        assert readiness.ready is False


class TestActivation:
    def test_activate_only_when_ready_and_flag_on(self) -> None:
        vip = uuid4()
        source = [{**_finished_row(), "vip_id": vip} for _ in range(19)]
        source.append({**_finished_row(corrected_text="x"), "vip_id": vip})
        trust = [type("R", (), {"vip_id": vip, "turn_category": "informativo",
                                "trust_score": 0.95, "autonomous_count": 3,
                                "correction_count": 0})()]
        service, _, vips = _make_service(
            source, trust, FakeVipStore([_vip(vip)]), recommendation_enabled=True
        )
        ok, text = asyncio.run(service.activate(vip))
        assert ok is True
        assert vips.auto_send.get(vip) is True

    def test_activate_blocked_when_flag_off(self) -> None:
        vip = uuid4()
        source = [_finished_row(), _finished_row(), _finished_row()]
        trust = [type("R", (), {"vip_id": vip, "turn_category": "informativo",
                                "trust_score": 0.95, "autonomous_count": 3,
                                "correction_count": 0})()]
        service, _, vips = _make_service(source, trust, FakeVipStore([_vip(vip)]))
        ok, text = asyncio.run(service.activate(vip))
        assert ok is False
        assert "desactivada" in text

    def test_activate_blocked_when_not_ready(self) -> None:
        vip = uuid4()
        source = [_finished_row(corrected_text="x")]
        trust = [type("R", (), {"vip_id": vip, "turn_category": "informativo",
                                "trust_score": 0.4, "autonomous_count": 0,
                                "correction_count": 1})()]
        service, _, vips = _make_service(
            source, trust, FakeVipStore([_vip(vip)]), recommendation_enabled=True
        )
        ok, text = asyncio.run(service.activate(vip))
        assert ok is False
        assert "Faltan" in text

    def test_deactivate_always_works(self) -> None:
        vip = uuid4()
        service, _, vips = _make_service(
            [], [], FakeVipStore([_vip(vip)]), recommendation_enabled=True
        )
        ok, _ = asyncio.run(service.deactivate(vip))
        assert ok is True
        assert vips.auto_send.get(vip) is False


class TestByVipRender:
    def test_render_by_vip_shows_ready_and_missing(self) -> None:
        vip_ready = uuid4()
        vip_waiting = uuid4()
        source = [_finished_row(), _finished_row(), _finished_row()]
        trust = [
            type("R", (), {"vip_id": vip_ready, "turn_category": "informativo",
                           "trust_score": 0.95, "autonomous_count": 3,
                           "correction_count": 0})(),
            type("R", (), {"vip_id": vip_waiting, "turn_category": "informativo",
                           "trust_score": 0.4, "autonomous_count": 0,
                           "correction_count": 1})(),
        ]
        service, _, _ = _make_service(
            source, trust, FakeVipStore([_vip(vip_ready, "Ana"), _vip(vip_waiting, "Beto")])
        )
        body = asyncio.run(service.render_by_vip())
        assert "Ana" in body and "Beto" in body
        assert "LISTO" in body
        assert "en camino" in body
