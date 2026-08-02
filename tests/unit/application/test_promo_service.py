"""PromoService — exact match, re-intro sequence, deliver + record (no LLM)."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from diana.application.memory import InMemoryTurnStore
from diana.application.ports import (
    DeliveryContext,
    DeliveryResult,
    PromoExecutionRecord,
    PromoTriggerRecord,
    TurnRecord,
)
from diana.application.promo_service import PromoService
from diana.behavior.fake import ImmediateClock

APPLICATION_ROOT = Path(__file__).resolve().parents[3] / "src" / "diana" / "application"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeTriggerStore:
    """Dict-backed PromoTriggerStore (exact strip+lower match, active only)."""

    def __init__(self, triggers: list[PromoTriggerRecord] | None = None) -> None:
        self._by_key: dict[str, PromoTriggerRecord] = {}
        for t in triggers or []:
            self._by_key[t.trigger_text.strip().lower()] = t

    async def get_active_by_trigger_text(
        self, text: str
    ) -> PromoTriggerRecord | None:
        key = text.strip().lower()
        rec = self._by_key.get(key)
        if rec is None or not rec.is_active:
            return None
        return rec

    async def list_active(self) -> list[PromoTriggerRecord]:
        return [t for t in self._by_key.values() if t.is_active]


class FakeExecutionStore:
    """List-backed PromoExecutionStore."""

    def __init__(self) -> None:
        self.rows: list[PromoExecutionRecord] = []

    async def insert(
        self,
        chat_id: int,
        trigger_id: UUID,
        sequence_sent: list[str] | None,
        status: str = "sent",
    ) -> PromoExecutionRecord:
        rec = PromoExecutionRecord(
            id=uuid4(),
            chat_id=chat_id,
            trigger_id=trigger_id,
            sent_at=datetime.now(UTC),
            sequence_sent=sequence_sent,
            status=status,
        )
        self.rows.append(rec)
        return rec

    async def latest_for_chat_trigger(
        self, chat_id: int, trigger_id: UUID
    ) -> PromoExecutionRecord | None:
        matches = [
            r
            for r in self.rows
            if r.chat_id == chat_id and r.trigger_id == trigger_id
        ]
        return matches[-1] if matches else None

    async def was_sent_since(
        self, chat_id: int, trigger_id: UUID, since: datetime
    ) -> bool:
        since_cmp = since if since.tzinfo else since.replace(tzinfo=UTC)
        for r in self.rows:
            if (
                r.chat_id == chat_id
                and r.trigger_id == trigger_id
                and r.status == "sent"
                and r.sent_at >= since_cmp
            ):
                return True
        return False


class FakePromoConfig:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = dict(data or {"repeat_days": 30})

    async def get_promo_config(self) -> dict[str, Any]:
        return dict(self._data)


class FakeSequenceDeliverer:
    def __init__(
        self,
        *,
        success: bool = True,
        raise_exc: Exception | None = None,
    ) -> None:
        self.success = success
        self.raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    async def deliver_with_sequence(
        self,
        texts: list[str],
        ctx: DeliveryContext,
        turn_id: UUID,
        decision: Any | None = None,
    ) -> DeliveryResult:
        self.calls.append(
            {
                "texts": list(texts),
                "ctx": ctx,
                "turn_id": turn_id,
                "decision": decision,
            }
        )
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.success:
            return DeliveryResult(success=True, message_ids=[1] * len(texts))
        return DeliveryResult(success=False, error="actuator_failed")


def _trigger(
    *,
    text: str = "promos",
    sequence: list[str] | None = None,
    repeat: str | None = "Holis de nuevo",
    active: bool = True,
    trigger_id: UUID | None = None,
) -> PromoTriggerRecord:
    return PromoTriggerRecord(
        id=trigger_id or uuid4(),
        trigger_text=text,
        response_sequence=sequence
        if sequence is not None
        else ["msg1", "msg2", "msg3"],
        repeat_first_message=repeat,
        is_active=active,
    )


def _svc(
    *,
    feature: bool = True,
    triggers: FakeTriggerStore | None = None,
    executions: FakeExecutionStore | None = None,
    config: FakePromoConfig | None = None,
    behavior: FakeSequenceDeliverer | None = None,
    turns: InMemoryTurnStore | None = None,
    clock: ImmediateClock | None = None,
    delivery_mode: str = "supervised",
) -> tuple[
    PromoService,
    FakeTriggerStore,
    FakeExecutionStore,
    FakeSequenceDeliverer,
    InMemoryTurnStore,
    ImmediateClock,
]:
    tstore = triggers or FakeTriggerStore()
    estore = executions or FakeExecutionStore()
    beh = behavior or FakeSequenceDeliverer()
    turn_store = turns or InMemoryTurnStore()
    ck = clock or ImmediateClock(now=datetime(2026, 7, 1, 12, 0, tzinfo=UTC))
    svc = PromoService(
        feature_promo_enabled=feature,
        triggers=tstore,
        executions=estore,
        config=config or FakePromoConfig(),
        behavior=beh,
        turns=turn_store,
        clock=ck,
        delivery_mode=delivery_mode,  # type: ignore[arg-type]
    )
    return svc, tstore, estore, beh, turn_store, ck


# ---------------------------------------------------------------------------
# match_trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_trigger_case_insensitive_exact() -> None:
    trig = _trigger(text="Quiero Info")
    svc, *_ = _svc(triggers=FakeTriggerStore([trig]))
    found = await svc.match_trigger("  QUIERO INFO  ")
    assert found is not None
    assert found.id == trig.id


@pytest.mark.asyncio
async def test_match_trigger_empty_or_whitespace_returns_none() -> None:
    trig = _trigger(text="promos")
    svc, *_ = _svc(triggers=FakeTriggerStore([trig]))
    assert await svc.match_trigger("") is None
    assert await svc.match_trigger("   ") is None


@pytest.mark.asyncio
async def test_match_trigger_inactive_ignored() -> None:
    trig = _trigger(text="promos", active=False)
    svc, *_ = _svc(triggers=FakeTriggerStore([trig]))
    assert await svc.match_trigger("promos") is None


@pytest.mark.asyncio
async def test_match_trigger_no_fuzzy() -> None:
    trig = _trigger(text="promos")
    svc, *_ = _svc(triggers=FakeTriggerStore([trig]))
    assert await svc.match_trigger("promo") is None
    assert await svc.match_trigger("mis promos por favor") is None


# ---------------------------------------------------------------------------
# has_recent_execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_has_recent_execution_true_within_window() -> None:
    trig = _trigger()
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    estore = FakeExecutionStore()
    estore.rows.append(
        PromoExecutionRecord(
            id=uuid4(),
            chat_id=99,
            trigger_id=trig.id,
            sent_at=now - timedelta(days=10),
            sequence_sent=["a"],
            status="sent",
        )
    )
    svc, *_rest = _svc(
        executions=estore,
        clock=ImmediateClock(now=now),
        config=FakePromoConfig({"repeat_days": 30}),
    )
    assert await svc.has_recent_execution(99, trig.id) is True


@pytest.mark.asyncio
async def test_has_recent_execution_false_outside_window() -> None:
    trig = _trigger()
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    estore = FakeExecutionStore()
    estore.rows.append(
        PromoExecutionRecord(
            id=uuid4(),
            chat_id=99,
            trigger_id=trig.id,
            sent_at=now - timedelta(days=45),
            sequence_sent=["a"],
            status="sent",
        )
    )
    svc, *_ = _svc(
        executions=estore,
        clock=ImmediateClock(now=now),
        config=FakePromoConfig({"repeat_days": 30}),
    )
    assert await svc.has_recent_execution(99, trig.id) is False


@pytest.mark.asyncio
async def test_has_recent_execution_uses_explicit_days() -> None:
    trig = _trigger()
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    estore = FakeExecutionStore()
    estore.rows.append(
        PromoExecutionRecord(
            id=uuid4(),
            chat_id=99,
            trigger_id=trig.id,
            sent_at=now - timedelta(days=5),
            sequence_sent=["a"],
            status="sent",
        )
    )
    svc, *_ = _svc(
        executions=estore,
        clock=ImmediateClock(now=now),
        config=FakePromoConfig({"repeat_days": 30}),
    )
    assert await svc.has_recent_execution(99, trig.id, days=3) is False
    assert await svc.has_recent_execution(99, trig.id, days=7) is True


@pytest.mark.asyncio
async def test_has_recent_execution_ignores_failed_status() -> None:
    trig = _trigger()
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    estore = FakeExecutionStore()
    estore.rows.append(
        PromoExecutionRecord(
            id=uuid4(),
            chat_id=99,
            trigger_id=trig.id,
            sent_at=now - timedelta(days=1),
            sequence_sent=["a"],
            status="failed",
        )
    )
    svc, *_ = _svc(executions=estore, clock=ImmediateClock(now=now))
    assert await svc.has_recent_execution(99, trig.id) is False


# ---------------------------------------------------------------------------
# build_sequence
# ---------------------------------------------------------------------------


def test_build_sequence_first_send_uses_full_response() -> None:
    trig = _trigger(sequence=["a", "b", "c"], repeat="reintro")
    svc, *_ = _svc()
    assert svc.build_sequence(trig, recent=False) == ["a", "b", "c"]


def test_build_sequence_recent_with_repeat_replaces_first() -> None:
    trig = _trigger(sequence=["a", "b", "c"], repeat="reintro")
    svc, *_ = _svc()
    assert svc.build_sequence(trig, recent=True) == ["reintro", "b", "c"]


def test_build_sequence_recent_null_repeat_uses_full() -> None:
    trig = _trigger(sequence=["a", "b"], repeat=None)
    svc, *_ = _svc()
    assert svc.build_sequence(trig, recent=True) == ["a", "b"]


def test_build_sequence_recent_empty_repeat_uses_full() -> None:
    trig = _trigger(sequence=["a", "b"], repeat="   ")
    svc, *_ = _svc()
    assert svc.build_sequence(trig, recent=True) == ["a", "b"]


# ---------------------------------------------------------------------------
# execute_promo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_flag_off_disabled_no_side_effects() -> None:
    trig = _trigger()
    svc, _, estore, beh, turns, _ = _svc(
        feature=False, triggers=FakeTriggerStore([trig])
    )
    status = await svc.execute_promo(42, trig, business_connection_id="bc-1")
    assert status == "disabled"
    assert beh.calls == []
    assert estore.rows == []
    assert turns._turns == {}  # noqa: SLF001


@pytest.mark.asyncio
async def test_execute_first_send_delivers_original_and_records_sent() -> None:
    trig = _trigger(sequence=["a", "b", "c"], repeat="reintro")
    svc, _, estore, beh, turns, _ = _svc(triggers=FakeTriggerStore([trig]))
    status = await svc.execute_promo(42, trig, business_connection_id="bc-1")
    assert status == "sent"
    assert len(beh.calls) == 1
    assert beh.calls[0]["texts"] == ["a", "b", "c"]
    ctx: DeliveryContext = beh.calls[0]["ctx"]
    assert ctx.chat_id == 42
    assert ctx.business_connection_id == "bc-1"
    assert ctx.vip_id is None
    assert ctx.mode == "supervised"
    assert ctx.is_frozen is False
    assert len(estore.rows) == 1
    assert estore.rows[0].status == "sent"
    assert estore.rows[0].sequence_sent == ["a", "b", "c"]
    assert estore.rows[0].chat_id == 42
    assert estore.rows[0].trigger_id == trig.id
    # synthetic turn ended delivered
    turn_id = beh.calls[0]["turn_id"]
    turn = await turns.get(turn_id)
    assert turn is not None
    assert turn.status == "delivered"
    assert turn.vip_id is None


@pytest.mark.asyncio
async def test_execute_forwards_telegram_message_id_to_context() -> None:
    trig = _trigger(sequence=["a", "b"], repeat=None)
    svc, _, _, beh, _, _ = _svc(triggers=FakeTriggerStore([trig]))
    status = await svc.execute_promo(
        42,
        trig,
        business_connection_id="bc-1",
        telegram_message_id=777,
    )
    assert status == "sent"
    ctx: DeliveryContext = beh.calls[0]["ctx"]
    assert ctx.telegram_message_id == 777


@pytest.mark.asyncio
async def test_execute_telegram_message_id_defaults_to_none() -> None:
    trig = _trigger(sequence=["a", "b"], repeat=None)
    svc, _, _, beh, _, _ = _svc(triggers=FakeTriggerStore([trig]))
    status = await svc.execute_promo(42, trig, business_connection_id="bc-1")
    assert status == "sent"
    ctx: DeliveryContext = beh.calls[0]["ctx"]
    assert ctx.telegram_message_id is None


@pytest.mark.asyncio
async def test_execute_recent_uses_reintro_first_message() -> None:
    trig = _trigger(sequence=["a", "b", "c"], repeat="reintro holis")
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    estore = FakeExecutionStore()
    estore.rows.append(
        PromoExecutionRecord(
            id=uuid4(),
            chat_id=42,
            trigger_id=trig.id,
            sent_at=now - timedelta(days=2),
            sequence_sent=["a"],
            status="sent",
        )
    )
    svc, _, new_estore, beh, _, _ = _svc(
        triggers=FakeTriggerStore([trig]),
        executions=estore,
        clock=ImmediateClock(now=now),
    )
    status = await svc.execute_promo(42, trig, business_connection_id="bc-1")
    assert status == "sent"
    assert beh.calls[0]["texts"] == ["reintro holis", "b", "c"]
    # second execution row appended
    assert len(new_estore.rows) == 2
    assert new_estore.rows[-1].status == "sent"
    assert new_estore.rows[-1].sequence_sent == ["reintro holis", "b", "c"]


@pytest.mark.asyncio
async def test_execute_deliver_fails_records_failed() -> None:
    trig = _trigger()
    beh = FakeSequenceDeliverer(success=False)
    svc, _, estore, _, turns, _ = _svc(
        triggers=FakeTriggerStore([trig]), behavior=beh
    )
    status = await svc.execute_promo(7, trig, business_connection_id="bc-1")
    assert status == "failed"
    assert len(estore.rows) == 1
    assert estore.rows[0].status == "failed"
    turn_id = beh.calls[0]["turn_id"]
    turn = await turns.get(turn_id)
    assert turn is not None
    assert turn.status == "failed"


@pytest.mark.asyncio
async def test_execute_deliver_raises_records_failed() -> None:
    trig = _trigger()
    beh = FakeSequenceDeliverer(raise_exc=RuntimeError("boom"))
    svc, _, estore, _, turns, _ = _svc(
        triggers=FakeTriggerStore([trig]), behavior=beh
    )
    status = await svc.execute_promo(7, trig, business_connection_id="bc-1")
    assert status == "failed"
    assert len(estore.rows) == 1
    assert estore.rows[0].status == "failed"
    # turn created and marked failed
    all_turns = list(turns._turns.values())  # noqa: SLF001
    assert len(all_turns) == 1
    assert all_turns[0].status == "failed"


@pytest.mark.asyncio
async def test_execute_empty_sequence_no_deliver() -> None:
    trig = _trigger(sequence=[], repeat=None)
    svc, _, estore, beh, _, _ = _svc(triggers=FakeTriggerStore([trig]))
    status = await svc.execute_promo(7, trig, business_connection_id="bc-1")
    assert status == "empty_sequence"
    assert beh.calls == []
    assert estore.rows == []


@pytest.mark.asyncio
async def test_execute_whitespace_only_sequence_empty() -> None:
    trig = _trigger(sequence=["  ", ""], repeat=None)
    svc, _, estore, beh, _, _ = _svc(triggers=FakeTriggerStore([trig]))
    status = await svc.execute_promo(7, trig, business_connection_id="bc-1")
    assert status == "empty_sequence"
    assert beh.calls == []
    assert estore.rows == []


@pytest.mark.asyncio
async def test_execute_missing_business_connection_failed() -> None:
    trig = _trigger()
    svc, _, estore, beh, _, _ = _svc(triggers=FakeTriggerStore([trig]))
    status = await svc.execute_promo(7, trig, business_connection_id="  ")
    assert status == "failed"
    assert beh.calls == []
    assert estore.rows == []


@pytest.mark.asyncio
async def test_execute_does_not_write_pipeline_traces() -> None:
    """Promo never touches trace writer — only deliver + executions + turns."""
    trig = _trigger()
    svc, _, estore, beh, turns, _ = _svc(triggers=FakeTriggerStore([trig]))
    await svc.execute_promo(1, trig, business_connection_id="bc")
    assert len(beh.calls) == 1
    assert len(estore.rows) == 1
    assert len(turns._turns) == 1  # noqa: SLF001


def test_promo_service_module_has_no_llm_imports() -> None:
    path = APPLICATION_ROOT / "promo_service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    forbidden = ("diana.llm", "openai", "httpx", "aiogram")
    for mod in modules:
        for prefix in forbidden:
            assert not (mod == prefix or mod.startswith(prefix + ".")), mod
