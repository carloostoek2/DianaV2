"""Unit tests for AdminTraceService (mocks TraceabilityReader protocol)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from diana.application.admin_trace_service import AdminTraceService, FullTrace, TurnSummary


class FakeTraceabilityReader:
    """In-memory fake implementing TraceabilityReader protocol for tests."""

    def __init__(self) -> None:
        self._turns: list[dict] = []
        self._traces: dict[str, dict] = {}

    def seed_turns(self, rows: list[dict]) -> None:
        self._turns = list(rows)

    def seed_trace(self, turn_id: str, data: dict) -> None:
        self._traces[str(turn_id)] = dict(data)

    async def get_recent_turns(self, limit: int = 10, offset: int = 0, chat_id: int | None = None) -> list[dict]:
        if chat_id is not None:
            filtered = [r for r in self._turns if r.get("chat_id") == chat_id]
            return list(filtered[offset:offset + limit])
        return list(self._turns[offset:offset + limit])

    async def get_full_trace(self, turn_id) -> dict | None:
        return self._traces.get(str(turn_id))

    async def count_recent(self, chat_id: int | None = None) -> int:
        if chat_id is not None:
            return sum(1 for r in self._turns if r.get("chat_id") == chat_id)
        return len(self._turns)


@pytest.fixture
def reader() -> FakeTraceabilityReader:
    return FakeTraceabilityReader()


@pytest.fixture
def svc(reader: FakeTraceabilityReader) -> AdminTraceService:
    return AdminTraceService(traces=reader, trace_ttl_days=30)


class TestGetRecentTurns:
    async def test_get_recent_turns_returns_summaries(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        turn_id = uuid4()
        reader.seed_turns([
            {
                "turn_id": turn_id,
                "chat_id": 123,
                "display_name": "Ana",
                "message_text": "Hola, quiero saber el precio del paquete premium",
                "decision": "approve",
                "status": "delivered",
                "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
                "correction_applied": False,
            }
        ])
        results = await svc.get_recent_turns(limit=10, offset=0)
        assert len(results) == 1
        t = results[0]
        assert isinstance(t, TurnSummary)
        assert t.turn_id == turn_id
        assert t.chat_id == 123
        assert t.vip_name == "Ana"
        assert t.message_preview == "Hola, quiero saber el precio del paquete premium"
        assert t.decision == "approve"
        assert t.status == "delivered"
        assert t.created_at is not None
        assert t.correction_applied is False

    async def test_get_recent_turns_empty(
        self, svc: AdminTraceService, _unused_reader: object = None
    ) -> None:
        results = await svc.get_recent_turns(limit=10, offset=0)
        assert results == []

    async def test_message_preview_truncated(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        long_text = "X" * 100
        reader.seed_turns([
            {
                "turn_id": uuid4(),
                "chat_id": 1,
                "display_name": "Test",
                "message_text": long_text,
                "decision": "approve",
                "status": "delivered",
                "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
                "correction_applied": False,
            }
        ])
        results = await svc.get_recent_turns()
        assert len(results) == 1
        assert results[0].message_preview == "X" * 50 + "..."
        assert len(results[0].message_preview) == 53


class TestGetFullTrace:
    async def test_get_full_trace_found(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        turn_id = uuid4()
        reader.seed_trace(str(turn_id), {
            "turn_id": turn_id,
            "chat_id": 123,
            "vip_id": uuid4(),
            "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
            "comprehension": {"intent": "chat"},
            "plan": {"capabilities": []},
            "retrieved": {},
            "prompt_text": "Hello",
            "generated_text": "Hi there",
            "evaluation": {"naturalness": 0.9},
            "decision": {"action": "approve"},
            "delivery_result": {"success": True},
            "timings": {"analyst_ms": 100.0},
            "status": "delivered",
            "error": None,
        })
        trace = await svc.get_full_trace(turn_id)
        assert trace is not None
        assert isinstance(trace, FullTrace)
        assert trace.turn_id == turn_id
        assert trace.comprehension == {"intent": "chat"}
        assert trace.generated_text == "Hi there"
        assert trace.timings == {"analyst_ms": 100.0}
        assert trace.status == "delivered"

    async def test_get_full_trace_not_found(
        self, svc: AdminTraceService, _unused_reader: object = None
    ) -> None:
        trace = await svc.get_full_trace(uuid4())
        assert trace is None


class TestCountRecent:
    async def test_count_recent(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        reader.seed_turns([
            {
                "turn_id": uuid4(), "chat_id": 1, "display_name": "A",
                "message_text": "hi", "decision": "a", "status": "d",
                "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
                "correction_applied": False,
            },
            {
                "turn_id": uuid4(), "chat_id": 2, "display_name": "B",
                "message_text": "hey", "decision": "a", "status": "d",
                "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
                "correction_applied": False,
            },
        ])
        count = await svc.count_recent()
        assert count == 2

    async def test_count_recent_zero(
        self, svc: AdminTraceService, _unused_reader: object = None
    ) -> None:
        count = await svc.count_recent()
        assert count == 0


class TestExportTraceJson:
    async def test_export_trace_json_found(
        self, svc: AdminTraceService, reader: FakeTraceabilityReader
    ) -> None:
        turn_id = uuid4()
        reader.seed_trace(str(turn_id), {
            "turn_id": turn_id,
            "chat_id": 123,
            "vip_id": uuid4(),
            "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
            "comprehension": {"intent": "chat"},
            "plan": {"capabilities": []},
            "retrieved": {},
            "prompt_text": "Hello",
            "generated_text": "Hi there",
            "evaluation": {"naturalness": 0.9},
            "decision": {"action": "approve"},
            "delivery_result": None,
            "timings": {"analyst_ms": 100.0},
            "status": "delivered",
            "error": None,
        })
        json_str = await svc.export_trace_json(turn_id)
        import json
        data = json.loads(json_str)
        assert data["turn_id"] == str(turn_id)
        assert data["comprehension"]["intent"] == "chat"
        assert data["timings"]["analyst_ms"] == 100.0

    async def test_export_trace_json_not_found(
        self, svc: AdminTraceService, _unused_reader: object = None
    ) -> None:
        json_str = await svc.export_trace_json(uuid4())
        import json
        data = json.loads(json_str)
        assert "error" in data
