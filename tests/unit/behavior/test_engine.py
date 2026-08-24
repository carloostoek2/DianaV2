"""BehaviorEngine: human-like delivery sequence + mid-flight cancel."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from diana.application.memory import InMemoryPendingDeliveryStore
from diana.application.ports import RuntimeTimerRecord
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import (
    AlwaysLiveTurnStatusReader,
    FakeTelegramActuator,
    FixedDelayPolicy,
    FlakySendActuator,
    ImmediateClock,
    SequenceTurnStatusReader,
)
from diana.behavior.ports import DeliveryContext, DeliveryProgress, TransientSendError


@pytest.fixture
def engine_bundle() -> tuple[BehaviorEngine, FakeTelegramActuator, InMemoryPendingDeliveryStore, ImmediateClock]:
    actuator = FakeTelegramActuator()
    store = InMemoryPendingDeliveryStore()
    clock = ImmediateClock()
    policy = FixedDelayPolicy(initial=0.05, typing=0.02)
    engine = BehaviorEngine(
        actuator,
        store,
        clock=clock,
        delay_policy=policy,
        turn_status=AlwaysLiveTurnStatusReader(),
    )
    return engine, actuator, store, clock


def _ctx(**overrides: object) -> DeliveryContext:
    data: dict = {
        "chat_id": 10,
        "business_connection_id": "bc-1",
        "telegram_message_id": 99,
    }
    data.update(overrides)
    return DeliveryContext(**data)  # type: ignore[arg-type]


# --- I.2 mode enum (Task 1) ---


def test_delivery_context_accepts_autonomous_mode() -> None:
    ctx = DeliveryContext(
        chat_id=1, business_connection_id="bc", mode="autonomous"
    )
    assert ctx.mode == "autonomous"


def test_delivery_context_accepts_fake_delivery_mode() -> None:
    ctx = DeliveryContext(
        chat_id=1, business_connection_id="bc", mode="fake_delivery"
    )
    assert ctx.mode == "fake_delivery"


def test_delivery_context_rejects_invalid_mode() -> None:
    with pytest.raises(ValidationError):
        DeliveryContext(chat_id=1, business_connection_id="bc", mode="nope")  # type: ignore[arg-type]


def test_task1_fakes_importable() -> None:
    assert AlwaysLiveTurnStatusReader is not None
    assert SequenceTurnStatusReader is not None
    assert FlakySendActuator is not None
    assert issubclass(TransientSendError, Exception)


@pytest.mark.asyncio
async def test_happy_path_sequence_order(
    engine_bundle: tuple,
) -> None:
    engine, actuator, store, clock = engine_bundle
    turn_id = uuid4()
    result = await engine.deliver(["hola"], _ctx(), turn_id)

    assert result.success is True
    assert result.cancelled is False
    assert result.message_ids == [1]
    assert result.texts == ["hola"]
    assert len(result.texts) == len(result.message_ids)
    assert [c["op"] for c in actuator.calls] == [
        "read_business_message",
        "send_chat_action",
        "send_message",
    ]
    assert clock.sleeps == [0.05, 0.02]
    pending = await store.list_pending()
    assert pending == []
    # delivery marked done
    all_rows = await store.list_all()
    assert len(all_rows) == 1
    assert all_rows[0].status == "done"


@pytest.mark.asyncio
async def test_instant_delivery_skips_all_human_like_waits(
    engine_bundle: tuple,
) -> None:
    """instant=True: no initial delay, no read simulation, no typing bubble."""
    engine, actuator, _, clock = engine_bundle
    ctx = _ctx(instant=True)
    result = await engine.deliver(["hola"], ctx, uuid4())

    assert result.success is True
    assert result.message_ids == [1]
    assert clock.sleeps == []
    # Only the message send happens — no read, no chat action.
    assert [c["op"] for c in actuator.calls] == ["send_message"]
    assert result.actual_delay_seconds == 0.0
    assert result.typing_duration_seconds == 0.0


@pytest.mark.asyncio
async def test_multi_text_sends_each(
    engine_bundle: tuple,
) -> None:
    engine, actuator, _, _ = engine_bundle
    result = await engine.deliver(["a", "b", "c"], _ctx(), uuid4())
    assert result.success is True
    assert result.message_ids == [1, 2, 3]
    assert result.texts == ["a", "b", "c"]
    assert len(result.texts) == len(result.message_ids)
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert [s["text"] for s in sends] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_cancel_pending_during_delay_no_send() -> None:
    actuator = FakeTelegramActuator()
    store = InMemoryPendingDeliveryStore()

    class SlowClock:
        def now(self):
            from datetime import UTC, datetime

            return datetime.now(UTC)

        async def sleep(self, seconds: float) -> None:
            await asyncio.sleep(0.2)

    engine = BehaviorEngine(
        actuator,
        store,
        clock=SlowClock(),
        delay_policy=FixedDelayPolicy(initial=10.0, typing=0.0),
    )
    turn_id = uuid4()
    task = asyncio.create_task(engine.deliver(["nope"], _ctx(), turn_id))
    await asyncio.sleep(0.05)
    await engine.cancel_pending(10)
    result = await task
    assert result.cancelled is True
    assert result.success is False
    assert actuator.send_count() == 0
    rows = await store.list_all()
    assert rows
    assert all(r.status == "cancelled" for r in rows)


@pytest.mark.asyncio
async def test_cancelled_status_not_overwritten_by_done() -> None:
    store = InMemoryPendingDeliveryStore()
    from datetime import UTC, datetime

    from diana.application.ports import DeliveryRecord

    rec = DeliveryRecord(
        id=uuid4(),
        chat_id=1,
        business_connection_id="bc",
        texts=["x"],
        decision={},
        scheduled_at=datetime.now(UTC),
        status="pending",
        turn_id=uuid4(),
    )
    await store.insert_pending(rec)
    assert await store.update_status(rec.id, "delivering") is True
    assert await store.update_status(rec.id, "cancelled") is True
    assert await store.update_status(rec.id, "done") is False
    got = await store.get(rec.id)
    assert got is not None and got.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_idempotent(
    engine_bundle: tuple,
) -> None:
    engine, _, _, _ = engine_bundle
    await engine.cancel_pending(123)
    await engine.cancel_pending(123)  # must not raise


@pytest.mark.asyncio
async def test_missing_business_connection_id_fail_closed(
    engine_bundle: tuple,
) -> None:
    engine, actuator, store, _ = engine_bundle
    result = await engine.deliver(
        ["x"],
        DeliveryContext(chat_id=1, business_connection_id=""),
        uuid4(),
    )
    assert result.success is False
    assert result.error
    assert actuator.send_count() == 0
    assert await store.list_all() == []


@pytest.mark.asyncio
async def test_whitespace_business_connection_id_fail_closed(
    engine_bundle: tuple,
) -> None:
    engine, actuator, _, _ = engine_bundle
    result = await engine.deliver(
        ["x"],
        DeliveryContext(chat_id=1, business_connection_id="   "),
        uuid4(),
    )
    assert result.success is False
    assert actuator.send_count() == 0


# --- Item4 Task1: DeliveryContext advanced fields + is_frozen hard-check ---


def test_delivery_context_advanced_defaults_fail_closed() -> None:
    ctx = DeliveryContext(chat_id=1, business_connection_id="bc")
    assert ctx.allow_split is False
    assert ctx.allow_human_quirks is False
    assert ctx.split_chars == 4096
    assert ctx.is_frozen is False


def test_delivery_context_split_chars_ge_one() -> None:
    with pytest.raises(ValidationError):
        DeliveryContext(chat_id=1, business_connection_id="bc", split_chars=0)
    with pytest.raises(ValidationError):
        DeliveryContext(chat_id=1, business_connection_id="bc", split_chars=-5)


@pytest.mark.asyncio
async def test_frozen_entry_aborts_without_send_or_insert(
    engine_bundle: tuple,
) -> None:
    engine, actuator, store, _ = engine_bundle
    result = await engine.deliver(["hola"], _ctx(is_frozen=True), uuid4())
    assert result.success is False
    assert result.cancelled is True
    assert result.error == "vip_frozen"
    assert actuator.send_count() == 0
    assert await store.list_all() == []


@pytest.mark.asyncio
async def test_fake_delivery_frozen_not_success(
    engine_bundle: tuple,
) -> None:
    engine, actuator, store, _ = engine_bundle
    result = await engine.deliver(
        ["hola"],
        _ctx(mode="fake_delivery", is_frozen=True),
        uuid4(),
    )
    assert result.success is False
    assert result.cancelled is True
    assert result.error == "vip_frozen"
    assert actuator.calls == []
    rows = await store.list_all()
    assert not any(r.status == "done" for r in rows)


@pytest.mark.asyncio
async def test_bc_empty_still_fails_when_not_frozen(
    engine_bundle: tuple,
) -> None:
    """BC check stays first; frozen false does not bypass empty BC."""
    engine, actuator, store, _ = engine_bundle
    result = await engine.deliver(
        ["x"],
        DeliveryContext(chat_id=1, business_connection_id="", is_frozen=False),
        uuid4(),
    )
    assert result.success is False
    assert result.error == "business_connection_id is required"
    assert actuator.send_count() == 0
    assert await store.list_all() == []


# --- I.4 pre-send gate / retries / I.2 fake_delivery (Task 2) ---


def _engine(
    actuator: FakeTelegramActuator | FlakySendActuator | None = None,
    *,
    turn_status: object | None = None,
    max_send_attempts: int = 3,
    retry_backoff_seconds: float = 0.05,
    store: InMemoryPendingDeliveryStore | None = None,
    clock: ImmediateClock | None = None,
    initial: float = 0.05,
    typing: float = 0.02,
    feature_advanced_behavior: bool = False,
    quirk_probability: float = 0.0,
    quirk_force: str | None = None,
) -> tuple[BehaviorEngine, FakeTelegramActuator | FlakySendActuator, InMemoryPendingDeliveryStore, ImmediateClock]:
    act = actuator or FakeTelegramActuator()
    st = store or InMemoryPendingDeliveryStore()
    ck = clock or ImmediateClock()
    engine = BehaviorEngine(
        act,
        st,
        clock=ck,
        delay_policy=FixedDelayPolicy(initial=initial, typing=typing),
        turn_status=turn_status if turn_status is not None else AlwaysLiveTurnStatusReader(),
        max_send_attempts=max_send_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        feature_advanced_behavior=feature_advanced_behavior,
        quirk_probability=quirk_probability,
        quirk_force=quirk_force,
    )
    return engine, act, st, ck


@pytest.mark.asyncio
async def test_presend_superseded_aborts_without_send() -> None:
    engine, actuator, store, _ = _engine(
        turn_status=SequenceTurnStatusReader(["superseded"]),
    )
    result = await engine.deliver(["hola"], _ctx(), uuid4())
    assert result.cancelled is True
    assert result.success is False
    assert actuator.send_count() == 0
    rows = await store.list_all()
    assert rows and rows[0].status == "cancelled"


@pytest.mark.asyncio
async def test_multiseg_presend_abort_after_first_segment() -> None:
    """D3: second segment aborts when turn becomes terminal; first may land."""
    engine, actuator, store, _ = _engine(
        turn_status=SequenceTurnStatusReader(
            ["pending_approval", "superseded"]
        ),
        initial=0.0,
        typing=0.0,
    )
    result = await engine.deliver(
        ["parte uno", "parte dos"],
        _ctx(allow_split=True, skip_initial_delay=True),
        uuid4(),
    )
    assert result.cancelled is True
    assert result.success is False
    assert actuator.send_count() == 1
    assert result.message_ids == [1]
    rows = await store.list_all()
    assert rows and rows[0].status == "cancelled"


@pytest.mark.asyncio
async def test_presend_terminal_failed_aborts() -> None:
    engine, actuator, store, _ = _engine(
        turn_status=SequenceTurnStatusReader(["failed"]),
    )
    result = await engine.deliver(["hola"], _ctx(), uuid4())
    assert result.success is False
    assert result.cancelled is True
    assert actuator.send_count() == 0
    rows = await store.list_all()
    assert rows and rows[0].status == "cancelled"


@pytest.mark.asyncio
async def test_presend_missing_turn_aborts() -> None:
    engine, actuator, store, _ = _engine(
        turn_status=SequenceTurnStatusReader([None]),
    )
    result = await engine.deliver(["hola"], _ctx(), uuid4())
    assert result.success is False
    assert result.cancelled is True
    assert actuator.send_count() == 0
    rows = await store.list_all()
    assert rows and rows[0].status == "cancelled"


@pytest.mark.asyncio
async def test_transient_then_success_within_budget() -> None:
    flaky = FlakySendActuator(fail_times=1)
    engine, _, _, clock = _engine(
        flaky, max_send_attempts=3, retry_backoff_seconds=0.05
    )
    result = await engine.deliver(["hola"], _ctx(), uuid4())
    assert result.success is True
    assert flaky.send_attempts >= 2
    assert flaky.send_count() == 1
    assert 0.05 in clock.sleeps  # retry backoff recorded


@pytest.mark.asyncio
async def test_transient_exhausted_returns_error() -> None:
    flaky = FlakySendActuator(always_fail=True)
    engine, _, store, _ = _engine(
        flaky, max_send_attempts=2, retry_backoff_seconds=0.01
    )
    result = await engine.deliver(["hola"], _ctx(), uuid4())
    assert result.success is False
    assert result.cancelled is False
    assert result.error
    assert flaky.send_attempts == 2
    rows = await store.list_all()
    assert rows and rows[0].status == "error"


@pytest.mark.asyncio
async def test_permanent_error_no_retry() -> None:
    class BoomActuator(FakeTelegramActuator):
        def __init__(self) -> None:
            super().__init__()
            self.send_attempts = 0

        async def send_message(
            self,
            chat_id: int,
            text: str,
            *,
            business_connection_id: str,
            parse_mode: str | None = None,
        ) -> int:
            self.send_attempts += 1
            raise RuntimeError("permanent boom")

    boom = BoomActuator()
    engine, _, store, _ = _engine(boom, max_send_attempts=3)
    result = await engine.deliver(["hola"], _ctx(), uuid4())
    assert result.success is False
    assert boom.send_attempts == 1
    rows = await store.list_all()
    assert rows and rows[0].status == "error"


@pytest.mark.asyncio
async def test_fake_delivery_no_network_send() -> None:
    engine, actuator, store, clock = _engine(initial=0.05, typing=0.02)
    result = await engine.deliver(
        ["hola"],
        _ctx(mode="fake_delivery"),
        uuid4(),
    )
    assert result.success is True
    assert result.message_ids == []
    assert actuator.calls == []  # no read/typing/send
    assert clock.sleeps == [0.05]  # initial delay may still apply
    rows = await store.list_all()
    assert rows and rows[0].status == "done"


@pytest.mark.asyncio
async def test_fake_delivery_presend_abort() -> None:
    engine, actuator, store, _ = _engine(
        turn_status=SequenceTurnStatusReader(["superseded"]),
    )
    result = await engine.deliver(
        ["hola"],
        _ctx(mode="fake_delivery"),
        uuid4(),
    )
    assert result.success is False
    assert result.cancelled is True
    assert actuator.calls == []
    rows = await store.list_all()
    assert rows and rows[0].status == "cancelled"


# --- Item4 Task2: split + light quirks dual advanced gate ---


def test_split_text_no_mid_word_on_long_token() -> None:
    from diana.behavior.split import split_text

    # Long token without punctuation/whitespace — hard cut at max_chars.
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    parts = split_text(text, max_chars=10)
    assert parts == ["ABCDEFGHIJ", "KLMNOPQRST", "UVWXYZ"]
    assert all(parts)
    # Whitespace fallback prefers last space inside window.
    spaced = "hello beautiful world and more"
    parts2 = split_text(spaced, max_chars=16)
    joined = " ".join(parts2)
    assert "beautiful" in joined
    assert all(" " not in p or p == p.strip() for p in parts2)
    for p in parts2:
        # No mid-word cut when whitespace is available inside window.
        assert p == p.strip()


@pytest.mark.asyncio
async def test_dual_gate_off_forged_allow_split_single_send() -> None:
    """Flag-off: forged allow_split=True must NOT split (C2)."""
    long_text = "Hello world. This is fine, really.\nMore here."
    engine, actuator, _, _ = _engine(
        feature_advanced_behavior=False,
        initial=0.0,
        typing=0.0,
    )
    result = await engine.deliver(
        [long_text],
        _ctx(allow_split=True, split_chars=20, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) == 1
    assert sends[0]["text"] == long_text


@pytest.mark.asyncio
async def test_dual_gate_allow_split_false_single_send() -> None:
    """SUG-1: advanced on + allow_split=False → no split (dual gate)."""
    long_text = "Hello world. This is fine, really.\nMore here."
    engine, actuator, _, _ = _engine(
        feature_advanced_behavior=True,
        initial=0.0,
        typing=0.0,
    )
    result = await engine.deliver(
        [long_text],
        _ctx(allow_split=False, split_chars=20, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) == 1
    assert sends[0]["text"] == long_text


@pytest.mark.asyncio
async def test_split_on_expands_long_text() -> None:
    text = "Hello world. This is fine, really.\nMore here."
    engine, actuator, store, _ = _engine(
        feature_advanced_behavior=True,
        initial=0.0,
        typing=0.0,
    )
    result = await engine.deliver(
        [text],
        _ctx(allow_split=True, split_chars=20, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) >= 2
    joined = "".join(s["text"] for s in sends)
    # Words preserved (no mid-word cuts of known tokens).
    for word in ("Hello", "world", "This", "fine", "really", "More", "here"):
        assert word in joined
    assert all(s["text"].strip() for s in sends)
    rows = await store.list_all()
    assert rows and len(rows[0].texts) >= 2


@pytest.mark.asyncio
async def test_split_short_text_still_one_send() -> None:
    engine, actuator, _, _ = _engine(
        feature_advanced_behavior=True,
        initial=0.0,
        typing=0.0,
    )
    result = await engine.deliver(
        ["short ok"],
        _ctx(allow_split=True, split_chars=20, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) == 1
    assert sends[0]["text"] == "short ok"


_THREE_PARAS = (
    "Oye, estuve pensando en lo que me contaste ayer en la noche.\n\n"
    "La verdad tiene mucho sentido, no lo había visto de esa forma.\n\n"
    "Cuando puedas cuéntame cómo te fue hoy, me da curiosidad."
)


@pytest.mark.asyncio
async def test_split_three_paragraphs_under_limit_three_sends() -> None:
    """Conversational 3-paragraph draft must become 3 Telegram bubbles."""
    assert len(_THREE_PARAS) < 4096
    engine, actuator, store, _ = _engine(
        feature_advanced_behavior=True,
        initial=0.0,
        typing=0.0,
    )
    result = await engine.deliver(
        [_THREE_PARAS],
        _ctx(allow_split=True, split_chars=4096, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert [s["text"] for s in sends] == [
        "Oye, estuve pensando en lo que me contaste ayer en la noche.",
        "La verdad tiene mucho sentido, no lo había visto de esa forma.",
        "Cuando puedas cuéntame cómo te fue hoy, me da curiosidad.",
    ]
    rows = await store.list_all()
    assert rows and len(rows[0].texts) == 3


@pytest.mark.asyncio
async def test_split_three_paragraphs_flag_off_single_send() -> None:
    engine, actuator, _, _ = _engine(
        feature_advanced_behavior=False,
        initial=0.0,
        typing=0.0,
    )
    result = await engine.deliver(
        [_THREE_PARAS],
        _ctx(allow_split=True, split_chars=4096, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) == 1
    assert sends[0]["text"] == _THREE_PARAS


@pytest.mark.asyncio
async def test_split_expand_adds_inter_message_gap() -> None:
    text = "Hello world. This is fine, really.\nMore here."
    engine, actuator, _, clock = _engine(
        feature_advanced_behavior=True,
        initial=0.05,
        typing=0.02,
    )
    result = await engine.deliver(
        [text],
        _ctx(allow_split=True, split_chars=20),
        uuid4(),
    )
    assert result.success is True
    typing_actions = [c for c in actuator.calls if c["op"] == "send_chat_action"]
    # Baseline single-text has 1 typing; split expand needs typing for subsequent bubbles.
    assert len(typing_actions) >= 2
    # More sleeps than baseline initial+one typing (0.05, 0.02).
    assert len(clock.sleeps) > 2


@pytest.mark.asyncio
async def test_quirks_off_no_extra_pause() -> None:
    engine, _, _, clock = _engine(
        feature_advanced_behavior=True,
        quirk_probability=1.0,
        quirk_force="pause",
        initial=0.05,
        typing=0.02,
    )
    result = await engine.deliver(
        ["hola"],
        _ctx(allow_human_quirks=False, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    # Baseline: initial + typing only (no quirk pause).
    assert clock.sleeps == [0.05, 0.02]


@pytest.mark.asyncio
async def test_quirks_on_extra_pause() -> None:
    engine, actuator, _, clock = _engine(
        feature_advanced_behavior=True,
        quirk_probability=1.0,
        quirk_force="pause",
        initial=0.05,
        typing=0.02,
    )
    text = "hola"
    result = await engine.deliver(
        [text],
        _ctx(allow_human_quirks=True, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    # Baseline [0.05, 0.02] plus fixed quirk pause 0.03 (C4).
    assert clock.sleeps == [0.05, 0.03, 0.02]
    # Pause quirk does not rewrite message content.
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) == 1
    assert sends[0]["text"] == text


@pytest.mark.asyncio
async def test_quirks_dual_gate_flag_off_no_extra() -> None:
    engine, _, _, clock = _engine(
        feature_advanced_behavior=False,
        quirk_probability=1.0,
        quirk_force="pause",
        initial=0.05,
        typing=0.02,
    )
    result = await engine.deliver(
        ["hola"],
        _ctx(allow_human_quirks=True, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    assert clock.sleeps == [0.05, 0.02]


@pytest.mark.asyncio
async def test_quirks_probability_zero_no_effect() -> None:
    engine, actuator, _, clock = _engine(
        feature_advanced_behavior=True,
        quirk_probability=0.0,
        initial=0.05,
        typing=0.02,
    )
    text = "Hello there friend. How are you doing today?"
    result = await engine.deliver(
        [text],
        _ctx(allow_human_quirks=True, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    assert clock.sleeps == [0.05, 0.02]
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) == 1
    assert sends[0]["text"] == text


@pytest.mark.asyncio
async def test_quirks_force_typo_sends_correction_bubble() -> None:
    engine, actuator, _, _ = _engine(
        feature_advanced_behavior=True,
        quirk_probability=1.0,
        quirk_force="typo_correct",
        initial=0.0,
        typing=0.0,
    )
    text = "Hello beautiful world"
    result = await engine.deliver(
        [text],
        _ctx(allow_human_quirks=True, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) >= 2
    assert sends[0]["text"] != text
    assert sends[1]["text"].startswith("*")
    fixed_word = sends[1]["text"][1:]
    assert fixed_word in text
    # Final corpus still carries original meaning (typo bubble + *word).
    corpus = " ".join(s["text"] for s in sends)
    assert fixed_word in corpus
    for word in ("beautiful", "world"):
        assert word in corpus


@pytest.mark.asyncio
async def test_quirks_force_natural_split_multi_bubble() -> None:
    engine, actuator, _, clock = _engine(
        feature_advanced_behavior=True,
        quirk_probability=1.0,
        quirk_force="natural_split",
        initial=0.05,
        typing=0.02,
    )
    text = "Hello there friend. How are you doing today?"
    result = await engine.deliver(
        [text],
        _ctx(
            allow_human_quirks=True,
            allow_split=False,
            telegram_message_id=None,
        ),
        uuid4(),
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) >= 2
    joined = " ".join(s["text"] for s in sends)
    for word in ("Hello", "there", "friend", "How", "are", "you", "doing", "today"):
        assert word in joined
    # Inter-message gap: more sleeps than single-bubble baseline.
    assert len(clock.sleeps) > 2


@pytest.mark.asyncio
async def test_quirks_force_blocked_when_flag_off() -> None:
    """Dual gate: forged force+ctx quirks with flag off must not typo/split."""
    engine, actuator, _, clock = _engine(
        feature_advanced_behavior=False,
        quirk_probability=1.0,
        quirk_force="typo_correct",
        initial=0.05,
        typing=0.02,
    )
    text = "Hello beautiful world"
    result = await engine.deliver(
        [text],
        _ctx(allow_human_quirks=True, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) == 1
    assert sends[0]["text"] == text
    assert clock.sleeps == [0.05, 0.02]


@pytest.mark.asyncio
async def test_quirks_typo_fallback_to_pause_when_no_candidate() -> None:
    engine, actuator, _, clock = _engine(
        feature_advanced_behavior=True,
        quirk_probability=1.0,
        quirk_force="typo_correct",
        initial=0.05,
        typing=0.02,
    )
    text = "hi ok me"
    result = await engine.deliver(
        [text],
        _ctx(allow_human_quirks=True, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) == 1
    assert sends[0]["text"] == text
    assert clock.sleeps == [0.05, 0.03, 0.02]


@pytest.mark.asyncio
async def test_quirks_dual_gate_ctx_off_blocks_force_typo() -> None:
    """Advanced on + allow_human_quirks=False + force typo → no effect."""
    engine, actuator, _, clock = _engine(
        feature_advanced_behavior=True,
        quirk_probability=1.0,
        quirk_force="typo_correct",
        initial=0.05,
        typing=0.02,
    )
    text = "Hello beautiful world"
    result = await engine.deliver(
        [text],
        _ctx(allow_human_quirks=False, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) == 1
    assert sends[0]["text"] == text
    assert clock.sleeps == [0.05, 0.02]


@pytest.mark.asyncio
async def test_quirks_dual_gate_ctx_off_blocks_force_natural_split() -> None:
    """Advanced on + allow_human_quirks=False + force natural_split → no effect."""
    engine, actuator, _, clock = _engine(
        feature_advanced_behavior=True,
        quirk_probability=1.0,
        quirk_force="natural_split",
        initial=0.05,
        typing=0.02,
    )
    text = "Hello there friend. How are you doing today?"
    result = await engine.deliver(
        [text],
        _ctx(allow_human_quirks=False, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) == 1
    assert sends[0]["text"] == text
    assert clock.sleeps == [0.05, 0.02]


@pytest.mark.asyncio
async def test_quirks_natural_split_fallback_to_pause_when_unsplittable() -> None:
    engine, actuator, _, clock = _engine(
        feature_advanced_behavior=True,
        quirk_probability=1.0,
        quirk_force="natural_split",
        initial=0.05,
        typing=0.02,
    )
    text = "short unsplittable"
    result = await engine.deliver(
        [text],
        _ctx(allow_human_quirks=True, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) == 1
    assert sends[0]["text"] == text
    # Fallback pause: baseline [0.05, 0.02] + 0.03 quirk pause.
    assert clock.sleeps == [0.05, 0.03, 0.02]


@pytest.mark.asyncio
async def test_quirks_invalid_force_fail_closed_pause() -> None:
    engine, actuator, _, clock = _engine(
        feature_advanced_behavior=True,
        quirk_probability=1.0,
        quirk_force="not-a-real-kind",
        initial=0.05,
        typing=0.02,
    )
    text = "hola mundo"
    result = await engine.deliver(
        [text],
        _ctx(allow_human_quirks=True, telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert len(sends) == 1
    assert sends[0]["text"] == text
    assert clock.sleeps == [0.05, 0.03, 0.02]


# --- Item4 Task3: deliver_with_sequence inter-message gaps ---


@pytest.mark.asyncio
async def test_deliver_with_sequence_three_texts_inter_gap() -> None:
    engine, actuator, _, clock = _engine(initial=0.05, typing=0.02)
    turn_id = uuid4()
    result = await engine.deliver_with_sequence(
        ["a", "b", "c"],
        _ctx(telegram_message_id=None),
        turn_id,
    )
    assert result.success is True
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert [s["text"] for s in sends] == ["a", "b", "c"]
    typing_actions = [c for c in actuator.calls if c["op"] == "send_chat_action"]
    assert len(typing_actions) >= 3
    # Initial delay + typing per bubble + inter delays between subsequent.
    assert len(clock.sleeps) > 2
    # Multi-text deliver (no sequence) keeps single typing baseline.
    engine2, actuator2, _, clock2 = _engine(initial=0.05, typing=0.02)
    await engine2.deliver(["a", "b", "c"], _ctx(telegram_message_id=None), uuid4())
    typing2 = [c for c in actuator2.calls if c["op"] == "send_chat_action"]
    assert len(typing2) == 1
    assert clock2.sleeps == [0.05, 0.02]


@pytest.mark.asyncio
async def test_typing_refresh_keeps_bubble_visible_for_long_texts() -> None:
    # duration 10s -> refresh every 4s: typing x3, sleeps chunked 4+4+2.
    engine, actuator, _, clock = _engine(initial=0.05, typing=10.0)
    result = await engine.deliver_with_sequence(
        ["hola"],
        _ctx(telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    typing_actions = [c for c in actuator.calls if c["op"] == "send_chat_action"]
    assert len(typing_actions) == 3
    assert clock.sleeps == [0.05, 4.0, 4.0, 2.0]


@pytest.mark.asyncio
async def test_typing_short_duration_sends_once() -> None:
    engine, actuator, _, clock = _engine(initial=0.05, typing=0.02)
    result = await engine.deliver_with_sequence(
        ["hola"],
        _ctx(telegram_message_id=None),
        uuid4(),
    )
    assert result.success is True
    typing_actions = [c for c in actuator.calls if c["op"] == "send_chat_action"]
    assert len(typing_actions) == 1
    assert clock.sleeps == [0.05, 0.02]


@pytest.mark.asyncio
async def test_deliver_with_sequence_frozen_zero_sends() -> None:
    engine, actuator, store, _ = _engine()
    result = await engine.deliver_with_sequence(
        ["a", "b"],
        _ctx(is_frozen=True),
        uuid4(),
    )
    assert result.success is False
    assert result.cancelled is True
    assert result.error == "vip_frozen"
    assert actuator.send_count() == 0
    assert await store.list_all() == []


@pytest.mark.asyncio
async def test_deliver_with_sequence_empty_fail_closed() -> None:
    engine, actuator, store, _ = _engine()
    for texts in ([], ["   ", "\n"], ["", "  "]):
        result = await engine.deliver_with_sequence(
            texts,
            _ctx(telegram_message_id=None),
            uuid4(),
        )
        assert result.success is False
        assert result.error == "empty_texts"
        assert actuator.send_count() == 0
    assert await store.list_all() == []


@pytest.mark.asyncio
async def test_deliver_with_sequence_cancel_mid_no_further_sends() -> None:
    actuator = FakeTelegramActuator()
    store = InMemoryPendingDeliveryStore()

    class SlowClock:
        def now(self):
            from datetime import UTC, datetime

            return datetime.now(UTC)

        async def sleep(self, seconds: float) -> None:
            await asyncio.sleep(0.15)

    engine = BehaviorEngine(
        actuator,
        store,
        clock=SlowClock(),
        delay_policy=FixedDelayPolicy(initial=10.0, typing=0.0),
        turn_status=AlwaysLiveTurnStatusReader(),
    )
    turn_id = uuid4()
    task = asyncio.create_task(
        engine.deliver_with_sequence(["a", "b", "c"], _ctx(telegram_message_id=None), turn_id)
    )
    await asyncio.sleep(0.05)
    await engine.cancel_pending(10)
    result = await task
    assert result.cancelled is True
    assert result.success is False
    # Cancel during first delay → zero sends.
    assert actuator.send_count() == 0
    rows = await store.list_all()
    assert rows
    assert all(r.status == "cancelled" for r in rows)


@pytest.mark.asyncio
async def test_timer_created_when_runtime_timer_store_injected() -> None:
    """When RuntimeTimerStore is injected, timer is created before delay and completed after."""
    from diana.application.memory import InMemoryRuntimeTimerStore

    actuator = FakeTelegramActuator()
    store = InMemoryPendingDeliveryStore()
    timer_store = InMemoryRuntimeTimerStore()
    clock = ImmediateClock()
    policy = FixedDelayPolicy(initial=0.05, typing=0.02)
    engine = BehaviorEngine(
        actuator,
        store,
        clock=clock,
        delay_policy=policy,
        turn_status=AlwaysLiveTurnStatusReader(),
        runtime_timer_store=timer_store,
    )
    turn_id = uuid4()
    result = await engine.deliver(["hola"], _ctx(), turn_id)
    assert result.success is True

    # Timer was created and then marked completed — no active timers remain.
    active = await timer_store.list_active()
    assert active == []

    # Positive assertion: manually create a timer; list_active must detect it.
    # This proves the empty result above is not because list_active is broken.
    second_timer_id = uuid4()
    await timer_store.create_active(RuntimeTimerRecord(
        id=second_timer_id,
        chat_id=1,
        turn_id=uuid4(),
        delivery_id=uuid4(),
        scheduled_at=datetime.now(UTC),
        initial_delay_seconds=60.0,
        status="active",
        created_at=datetime.now(UTC),
    ))
    active = await timer_store.list_active()
    assert len(active) == 1
    assert active[0].id == second_timer_id


@pytest.mark.asyncio
async def test_no_timer_without_runtime_timer_store() -> None:
    """Without RuntimeTimerStore injection, no timer is created (existing behavior)."""
    actuator = FakeTelegramActuator()
    store = InMemoryPendingDeliveryStore()
    clock = ImmediateClock()
    policy = FixedDelayPolicy(initial=0.05, typing=0.02)
    engine = BehaviorEngine(
        actuator,
        store,
        clock=clock,
        delay_policy=policy,
        turn_status=AlwaysLiveTurnStatusReader(),
        runtime_timer_store=None,
    )
    turn_id = uuid4()
    result = await engine.deliver(["hola"], _ctx(), turn_id)
    assert result.success is True


def test_deliver_with_sequence_not_on_behavior_deliverer_protocol() -> None:
    from diana.application.ports import BehaviorDeliverer

    assert not hasattr(BehaviorDeliverer, "deliver_with_sequence") or (
        "deliver_with_sequence" not in getattr(BehaviorDeliverer, "__protocol_attrs__", set())
        and "deliver_with_sequence" not in BehaviorDeliverer.__dict__
    )
    # Concrete engine exposes the method; protocol only requires deliver.
    assert hasattr(BehaviorEngine, "deliver_with_sequence")
    assert hasattr(BehaviorDeliverer, "deliver")


@pytest.mark.asyncio
async def test_deliver_reports_progress_reading_then_typing(
    engine_bundle: tuple,
) -> None:
    """Live progress callback fires reading → typing in order for an owner approve."""
    engine, _, _, _ = engine_bundle
    seen: list[str] = []

    async def on_progress(event: DeliveryProgress) -> None:
        seen.append(event.kind)

    result = await engine.deliver(["hola"], _ctx(), uuid4(), on_progress=on_progress)

    assert result.success is True
    assert seen == ["reading", "typing"]


@pytest.mark.asyncio
async def test_deliver_no_reading_progress_without_trigger_message(
    engine_bundle: tuple,
) -> None:
    """Without a VIP message to mark read, only the typing stage is reported."""
    engine, _, _, _ = engine_bundle
    seen: list[str] = []

    async def on_progress(event: DeliveryProgress) -> None:
        seen.append(event.kind)

    result = await engine.deliver(
        ["hola"], _ctx(telegram_message_id=None), uuid4(), on_progress=on_progress
    )

    assert result.success is True
    assert seen == ["typing"]


@pytest.mark.asyncio
async def test_deliver_progress_callback_fault_does_not_break_delivery(
    engine_bundle: tuple,
) -> None:
    """A fault inside the progress callback must never fail the delivery."""
    engine, actuator, _, _ = engine_bundle

    async def on_progress(event: DeliveryProgress) -> None:
        raise RuntimeError("edit failed")

    result = await engine.deliver(["hola"], _ctx(), uuid4(), on_progress=on_progress)

    assert result.success is True
    assert actuator.send_count() >= 1


@pytest.mark.asyncio
async def test_deliver_split_reports_sending_progress_with_fraction() -> None:
    """Split delivery surfaces ``sending`` events carrying 1-based index/total."""
    engine, _, _, _ = _engine(
        feature_advanced_behavior=True,
        initial=0.0,
        typing=0.0,
    )
    seen: list[tuple[str, int | None, int | None]] = []

    async def on_progress(event: DeliveryProgress) -> None:
        seen.append((event.kind, event.index, event.total))

    text = "Hello world. This is fine, really.\nMore here."
    result = await engine.deliver(
        [text],
        _ctx(allow_split=True, split_chars=20, telegram_message_id=None),
        uuid4(),
        on_progress=on_progress,
    )

    assert result.success is True
    sending = [e for e in seen if e[0] == "sending"]
    assert len(sending) >= 2
    assert sending[0] == ("sending", 1, len(sending))
    assert sending[-1] == ("sending", len(sending), len(sending))
    # No fraction payload on reading/typing stages.
    for kind, index, total in seen:
        if kind != "sending":
            assert index is None and total is None
