"""Auth allowlist — non-VIP never reaches next handler; promo path optional."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiogram.types import Chat, Message, User

from diana.application.memory import InMemoryVipStore
from diana.application.ports import PromoTriggerRecord
from diana.telegram.middlewares.auth import AuthMiddleware


def _biz_msg(
    user_id: int,
    *,
    text: str = "hola",
    chat_id: int = 42,
    caption: str | None = None,
) -> Message:
    return Message(
        message_id=1,
        date=0,
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="U"),
        text=text,
        caption=caption,
        business_connection_id="bc-1",
    )


def _promo_mock(*, trigger: PromoTriggerRecord | None = None) -> MagicMock:
    promo = MagicMock()
    promo.match_trigger = AsyncMock(return_value=trigger)
    promo.execute_promo = AsyncMock(return_value="sent")
    return promo


def _trigger(text: str = "promos") -> PromoTriggerRecord:
    return PromoTriggerRecord(
        id=uuid4(),
        trigger_text=text,
        response_sequence=["a", "b"],
        repeat_first_message="reintro",
        is_active=True,
    )


class _CyclesStore:
    """In-memory AtencionCycleStore double for auth middleware tests."""

    def __init__(self, active: bool = True) -> None:
        self._active = active
        self.starts: list[int] = []

    async def start_if_absent(self, chat_id: int, *, now) -> None:
        self.starts.append(chat_id)

    async def is_active(self, chat_id: int, *, since, now) -> bool:
        return self._active

    async def close_payment(self, chat_id: int, *, now) -> None:
        pass


@pytest.mark.asyncio
async def test_non_vip_dropped() -> None:
    vips = InMemoryVipStore()
    mw = AuthMiddleware(vips=vips)
    handler = AsyncMock(return_value="orch")
    result = await mw(handler, _biz_msg(111), {"business_connection_id": "bc-1"})
    assert result is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_vip_passes_with_vip_id() -> None:
    vips = InMemoryVipStore()
    rec = await vips.add(222, display_name="Vip")
    mw = AuthMiddleware(vips=vips)
    handler = AsyncMock(return_value="ok")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(222), data)
    assert result == "ok"
    handler.assert_awaited_once()
    assert data["vip_id"] == rec.id


@pytest.mark.asyncio
async def test_deactivated_vip_dropped() -> None:
    vips = InMemoryVipStore()
    await vips.add(333)
    await vips.deactivate(333)
    mw = AuthMiddleware(vips=vips)
    handler = AsyncMock(return_value="ok")
    result = await mw(handler, _biz_msg(333), {"business_connection_id": "bc-1"})
    assert result is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_owner_private_dm_dropped() -> None:
    vips = InMemoryVipStore()
    mw = AuthMiddleware(vips=vips)
    event = Message(
        message_id=2,
        date=0,
        chat=Chat(id=111, type="private"),
        from_user=User(id=111, is_bot=False, first_name="X"),
        text="spam keyword encuentro",
        business_connection_id=None,
    )
    handler = AsyncMock(return_value="should-not-run")
    result = await mw(handler, event, {})
    assert result is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_private_passes() -> None:
    vips = InMemoryVipStore()
    mw = AuthMiddleware(vips=vips)
    event = Message(
        message_id=3,
        date=0,
        chat=Chat(id=999001, type="private"),
        from_user=User(id=999001, is_bot=False, first_name="Owner"),
        text="/start",
        business_connection_id=None,
    )
    handler = AsyncMock(return_value="admin")
    result = await mw(handler, event, {"is_owner": True})
    assert result == "admin"
    handler.assert_awaited_once()


# ---------------------------------------------------------------------------
# F3 promo path (non-VIP business + FEATURE_PROMO_ENABLED)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_vip_flag_on_match_executes_promo_handler_not_called() -> None:
    vips = InMemoryVipStore()
    trig = _trigger("promos")
    promo = _promo_mock(trigger=trig)
    mw = AuthMiddleware(
        vips=vips, promo=promo, feature_promo_enabled=True
    )
    handler = AsyncMock(return_value="should-not-run")
    result = await mw(
        handler,
        _biz_msg(111, text="PROMOS", chat_id=555),
        {"business_connection_id": "bc-1"},
    )
    assert result is None
    handler.assert_not_awaited()
    promo.match_trigger.assert_awaited_once_with("PROMOS")
    promo.execute_promo.assert_awaited_once()
    args, kwargs = promo.execute_promo.await_args
    assert args[0] == 555
    assert args[1] is trig
    assert kwargs["business_connection_id"] == "bc-1"
    assert kwargs["telegram_message_id"] == 1


@pytest.mark.asyncio
async def test_non_vip_flag_on_no_match_drops_no_execute() -> None:
    vips = InMemoryVipStore()
    promo = _promo_mock(trigger=None)
    mw = AuthMiddleware(
        vips=vips, promo=promo, feature_promo_enabled=True
    )
    handler = AsyncMock(return_value="should-not-run")
    result = await mw(
        handler,
        _biz_msg(111, text="random chatter"),
        {"business_connection_id": "bc-1"},
    )
    assert result is None
    handler.assert_not_awaited()
    promo.match_trigger.assert_awaited_once_with("random chatter")
    promo.execute_promo.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_vip_flag_off_legacy_drop_no_promo_calls() -> None:
    vips = InMemoryVipStore()
    promo = _promo_mock(trigger=_trigger())
    mw = AuthMiddleware(
        vips=vips, promo=promo, feature_promo_enabled=False
    )
    handler = AsyncMock(return_value="orch")
    result = await mw(
        handler,
        _biz_msg(111, text="promos"),
        {"business_connection_id": "bc-1"},
    )
    assert result is None
    handler.assert_not_awaited()
    promo.match_trigger.assert_not_awaited()
    promo.execute_promo.assert_not_awaited()


@pytest.mark.asyncio
async def test_vip_allowed_does_not_consult_promo() -> None:
    vips = InMemoryVipStore()
    await vips.add(222, display_name="Vip")
    promo = _promo_mock(trigger=_trigger())
    mw = AuthMiddleware(
        vips=vips, promo=promo, feature_promo_enabled=True
    )
    handler = AsyncMock(return_value="ok")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(222, text="promos"), data)
    assert result == "ok"
    handler.assert_awaited_once()
    promo.match_trigger.assert_not_awaited()
    promo.execute_promo.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_non_owner_no_promo_without_business_bc() -> None:
    vips = InMemoryVipStore()
    promo = _promo_mock(trigger=_trigger())
    mw = AuthMiddleware(
        vips=vips, promo=promo, feature_promo_enabled=True
    )
    event = Message(
        message_id=2,
        date=0,
        chat=Chat(id=111, type="private"),
        from_user=User(id=111, is_bot=False, first_name="X"),
        text="promos",
        business_connection_id=None,
    )
    handler = AsyncMock(return_value="should-not-run")
    result = await mw(handler, event, {})
    assert result is None
    handler.assert_not_awaited()
    promo.match_trigger.assert_not_awaited()
    promo.execute_promo.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_vip_flag_on_uses_caption_when_text_missing() -> None:
    vips = InMemoryVipStore()
    trig = _trigger("promos")
    promo = _promo_mock(trigger=trig)
    mw = AuthMiddleware(
        vips=vips, promo=promo, feature_promo_enabled=True
    )
    handler = AsyncMock()
    msg = Message(
        message_id=1,
        date=0,
        chat=Chat(id=77, type="private"),
        from_user=User(id=111, is_bot=False, first_name="U"),
        text=None,
        caption="promos",
        business_connection_id="bc-1",
    )
    result = await mw(handler, msg, {"business_connection_id": "bc-1"})
    assert result is None
    promo.match_trigger.assert_awaited_once_with("promos")
    promo.execute_promo.assert_awaited_once()


# ---------------------------------------------------------------------------
# Sandbox auth bypass (item4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sandbox_active_non_vip_passes() -> None:

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

    vips = InMemoryVipStore()
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    sandbox.activate(42, "cercano")
    mw = AuthMiddleware(vips=vips, sandbox=sandbox)
    handler = AsyncMock(return_value="orch")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111, chat_id=42), data)
    assert result == "orch"
    handler.assert_awaited_once()
    assert data.get("sandbox_active") is True
    assert "vip_id" not in data
    # S6: no VIP record → sandbox previews the atencion persona.
    assert data.get("channel_type") == "atencion"


@pytest.mark.asyncio
async def test_sandbox_active_vip_still_sets_vip_id() -> None:

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

    vips = InMemoryVipStore()
    rec = await vips.add(222, display_name="Vip")
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    sandbox.activate(42, "nuevo")
    mw = AuthMiddleware(vips=vips, sandbox=sandbox)
    handler = AsyncMock(return_value="ok")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(222, chat_id=42), data)
    assert result == "ok"
    handler.assert_awaited_once()
    assert data["vip_id"] == rec.id
    assert data.get("sandbox_active") is True
    # S6: VIP record exists → VIP channel is kept (never forced to atencion).
    assert data.get("channel_type") != "atencion"


# ---------------------------------------------------------------------------
# Training mode tests (F3 training mode gate — non-VIP passes through)
# ---------------------------------------------------------------------------


class _TrainingModeStore:
    """In-memory TrainingModeStore protocol mock (no DB)."""

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    async def is_enabled(self) -> bool:
        return self._enabled

    async def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled


@pytest.mark.asyncio
async def test_training_mode_on_non_vip_passes() -> None:
    """Non-VIP business message with training ON passes without vip_id."""
    vips = InMemoryVipStore()
    training = _TrainingModeStore(enabled=True)
    mw = AuthMiddleware(vips=vips, training_mode=training)
    handler = AsyncMock(return_value="orch")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111), data)
    assert result == "orch"
    handler.assert_awaited_once()
    assert "vip_id" not in data
    assert "vip_record" not in data
    assert data.get("channel_type") == "atencion"


@pytest.mark.asyncio
async def test_training_mode_on_vip_still_works_normally() -> None:
    """VIP still gets vip_id when training ON."""
    vips = InMemoryVipStore()
    rec = await vips.add(222, display_name="Vip")
    training = _TrainingModeStore(enabled=True)
    mw = AuthMiddleware(vips=vips, training_mode=training)
    handler = AsyncMock(return_value="ok")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(222), data)
    assert result == "ok"
    handler.assert_awaited_once()
    assert data["vip_id"] == rec.id


@pytest.mark.asyncio
async def test_training_mode_off_legacy_drop() -> None:
    """Non-VIP dropped when training OFF."""
    vips = InMemoryVipStore()
    training = _TrainingModeStore(enabled=False)
    mw = AuthMiddleware(vips=vips, training_mode=training)
    handler = AsyncMock(return_value="orch")
    result = await mw(handler, _biz_msg(111), {"business_connection_id": "bc-1"})
    assert result is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_training_mode_none() -> None:
    """AuthMiddleware without training_mode drops non-VIP (legacy behavior)."""
    vips = InMemoryVipStore()
    mw = AuthMiddleware(vips=vips)  # no training_mode arg
    handler = AsyncMock(return_value="orch")
    result = await mw(handler, _biz_msg(111), {"business_connection_id": "bc-1"})
    assert result is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_training_mode_on_private_non_owner_still_dropped() -> None:
    """Private DM from non-owner still dropped with training ON."""
    vips = InMemoryVipStore()
    training = _TrainingModeStore(enabled=True)
    mw = AuthMiddleware(vips=vips, training_mode=training)
    event = Message(
        message_id=2,
        date=0,
        chat=Chat(id=111, type="private"),
        from_user=User(id=111, is_bot=False, first_name="X"),
        text="hola",
        business_connection_id=None,
    )
    handler = AsyncMock(return_value="should-not-run")
    result = await mw(handler, event, {})
    assert result is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_sandbox_inactive_non_vip_still_dropped() -> None:

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

    vips = InMemoryVipStore()
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    # no activate
    mw = AuthMiddleware(vips=vips, sandbox=sandbox)
    handler = AsyncMock(return_value="orch")
    result = await mw(handler, _biz_msg(111, chat_id=42), {"business_connection_id": "bc-1"})
    assert result is None
    handler.assert_not_awaited()


# ---------------------------------------------------------------------------
# F4 general mode gate (non-VIP + FEATURE_GENERAL_MODE_ENABLED → atencion)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_general_mode_bypass_no_vip_flag_on() -> None:
    """Non-VIP + general flag ON + open atencion cycle → channel atencion, no vip_id."""
    vips = InMemoryVipStore()
    cycles = _CyclesStore(active=True)
    mw = AuthMiddleware(
        vips=vips,
        feature_general_mode_enabled=True,
        atencion_cycles=cycles,
    )
    handler = AsyncMock(return_value="orch")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111), data)
    assert result == "orch"
    handler.assert_awaited_once()
    assert data.get("channel_type") == "atencion"
    assert data.get("vip_id") is None
    assert "vip_record" not in data
    assert data.get("atencion_limit_counted") is True


@pytest.mark.asyncio
async def test_general_mode_flag_off_drops_to_promo_or_none() -> None:
    """Non-VIP + flag OFF → legacy behavior (promo/drop), handler not called."""
    vips = InMemoryVipStore()
    promo = _promo_mock(trigger=None)
    mw = AuthMiddleware(
        vips=vips,
        promo=promo,
        feature_promo_enabled=True,
        feature_general_mode_enabled=False,
    )
    handler = AsyncMock(return_value="should-not-run")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111), data)
    assert result is None
    handler.assert_not_awaited()
    promo.match_trigger.assert_awaited_once()


@pytest.mark.asyncio
async def test_general_mode_promo_wins_on_trigger_match() -> None:
    """N5a: flag ON + promo enabled + trigger text → promo runs, pipeline NOT entered."""
    vips = InMemoryVipStore()
    trig = _trigger("promos")
    promo = _promo_mock(trigger=trig)
    mw = AuthMiddleware(
        vips=vips,
        promo=promo,
        feature_promo_enabled=True,
        feature_general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="should-not-run")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111, text="PROMOS", chat_id=555), data)
    assert result is None
    handler.assert_not_awaited()
    promo.execute_promo.assert_awaited_once()
    assert data.get("channel_type") != "atencion"


@pytest.mark.asyncio
async def test_general_mode_wins_on_promo_non_match() -> None:
    """N5b: flag ON + promo enabled + non-trigger text + OPEN cycle → atencion channel,
    match_trigger awaited but promo never runs."""
    vips = InMemoryVipStore()
    promo = _promo_mock(trigger=None)
    mw = AuthMiddleware(
        vips=vips,
        promo=promo,
        feature_promo_enabled=True,
        feature_general_mode_enabled=True,
        atencion_cycles=_CyclesStore(active=True),
    )
    handler = AsyncMock(return_value="orch")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111, text="hola quiero información"), data)
    assert result == "orch"
    handler.assert_awaited_once()
    promo.match_trigger.assert_awaited_once()
    promo.execute_promo.assert_not_awaited()
    assert data.get("channel_type") == "atencion"
    assert data.get("vip_id") is None


@pytest.mark.asyncio
async def test_general_mode_vip_still_normal_vip_path() -> None:
    """N5c: active VIP + flag ON → normal VIP path (vip_id set, no atencion)."""
    vips = InMemoryVipStore()
    rec = await vips.add(222, display_name="Vip")
    promo = _promo_mock(trigger=_trigger())
    mw = AuthMiddleware(
        vips=vips,
        promo=promo,
        feature_promo_enabled=True,
        feature_general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="ok")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(222, text="promos"), data)
    assert result == "ok"
    handler.assert_awaited_once()
    assert data["vip_id"] == rec.id
    assert data.get("channel_type") != "atencion"
    promo.match_trigger.assert_not_awaited()


@pytest.mark.asyncio
async def test_general_mode_deactivated_vip_not_routed_to_atencion() -> None:
    """S4: a deactivated VIP with flag ON is dropped, never routed to atencion."""
    vips = InMemoryVipStore()
    await vips.add(333)
    await vips.deactivate(333)
    mw = AuthMiddleware(vips=vips, feature_general_mode_enabled=True)
    handler = AsyncMock(return_value="should-not-run")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(333), data)
    assert result is None
    handler.assert_not_awaited()
    assert data.get("channel_type") != "atencion"
    assert "vip_id" not in data


@pytest.mark.asyncio
async def test_sandbox_wins() -> None:
    """Sandbox active + flag ON → sandbox wins, handler runs with sandbox_active."""
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
    vips = InMemoryVipStore()
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    sandbox.activate(42, "nuevo")
    mw = AuthMiddleware(
        vips=vips, sandbox=sandbox, feature_general_mode_enabled=True
    )
    handler = AsyncMock(return_value="orch")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111, chat_id=42), data)
    assert result == "orch"
    handler.assert_awaited_once()
    assert data.get("sandbox_active") is True


@pytest.mark.asyncio
async def test_general_mode_training_wins() -> None:
    """Training ON + flag ON → handler called with channel_type atencion (training bypass)."""
    vips = InMemoryVipStore()
    training = _TrainingModeStore(enabled=True)
    mw = AuthMiddleware(
        vips=vips,
        training_mode=training,
        feature_general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="orch")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111), data)
    assert result == "orch"
    handler.assert_awaited_once()
    assert data.get("channel_type") == "atencion"
    assert data.get("vip_id") is None


# ---------------------------------------------------------------------------
# F4-02 daily limit marker (general-mode atencion only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_general_mode_sets_limit_counted_marker() -> None:
    """F4-02: the general-mode gate (with open cycle) sets the marker."""
    vips = InMemoryVipStore()
    mw = AuthMiddleware(
        vips=vips,
        feature_general_mode_enabled=True,
        atencion_cycles=_CyclesStore(active=True),
    )
    handler = AsyncMock(return_value="orch")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111), data)
    assert result == "orch"
    handler.assert_awaited_once()
    assert data.get("channel_type") == "atencion"
    assert data.get("atencion_limit_counted") is True


@pytest.mark.asyncio
async def test_training_and_sandbox_do_not_set_marker() -> None:
    """F4-02: training and sandbox atencion never set the limit-counted marker."""
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

    vips = InMemoryVipStore()
    handler = AsyncMock(return_value="orch")

    # Training-mode bypass: atencion channel, marker absent.
    training = _TrainingModeStore(enabled=True)
    mw = AuthMiddleware(vips=vips, training_mode=training)
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111), data)
    assert result == "orch"
    assert data.get("channel_type") == "atencion"
    assert data.get("atencion_limit_counted") is None

    # Sandbox-atencion (non-VIP preview): atencion channel, marker absent.
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    sandbox.activate(42, "cercano")
    mw2 = AuthMiddleware(vips=vips, sandbox=sandbox)
    data2: dict = {"business_connection_id": "bc-1"}
    await mw2(handler, _biz_msg(111, chat_id=42), data2)
    assert data2.get("channel_type") == "atencion"
    assert data2.get("atencion_limit_counted") is None


# ---------------------------------------------------------------------------
# F4 atencion cycle lifecycle (first promo opens 30d window; payment closes)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_general_mode_cycle_inactive_drops() -> None:
    """F4: flag ON but the chat never received the promo (cycle closed/absent)
    → dropped, handler NOT called, no atencion channel."""
    vips = InMemoryVipStore()
    promo = _promo_mock(trigger=None)
    mw = AuthMiddleware(
        vips=vips,
        promo=promo,
        feature_promo_enabled=True,
        feature_general_mode_enabled=True,
        atencion_cycles=_CyclesStore(active=False),
    )
    handler = AsyncMock(return_value="should-not-run")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111, text="hola"), data)
    assert result is None
    handler.assert_not_awaited()
    assert data.get("channel_type") is None


@pytest.mark.asyncio
async def test_general_mode_no_cycle_store_drops() -> None:
    """F4: flag ON but no cycle store wired → fail-closed drop (no pipeline)."""
    vips = InMemoryVipStore()
    promo = _promo_mock(trigger=None)
    mw = AuthMiddleware(
        vips=vips,
        promo=promo,
        feature_promo_enabled=True,
        feature_general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="should-not-run")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111, text="hola"), data)
    assert result is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_promo_sent_opens_atencion_cycle() -> None:
    """F4: successful promo delivery opens the chat's atencion cycle."""
    vips = InMemoryVipStore()
    trig = _trigger("promos")
    promo = _promo_mock(trigger=trig)
    cycles = _CyclesStore(active=False)
    mw = AuthMiddleware(
        vips=vips,
        promo=promo,
        feature_promo_enabled=True,
        feature_general_mode_enabled=True,
        atencion_cycles=cycles,
    )
    handler = AsyncMock(return_value="should-not-run")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111, text="PROMOS", chat_id=555), data)
    assert result is None
    handler.assert_not_awaited()
    promo.execute_promo.assert_awaited_once()
    assert 555 in cycles.starts


@pytest.mark.asyncio
async def test_promo_failed_does_not_open_cycle() -> None:
    """F4: a failed promo delivery must NOT open the atencion cycle."""
    vips = InMemoryVipStore()
    trig = _trigger("promos")
    promo = _promo_mock(trigger=trig)
    promo.execute_promo = AsyncMock(return_value="failed")
    cycles = _CyclesStore(active=False)
    mw = AuthMiddleware(
        vips=vips,
        promo=promo,
        feature_promo_enabled=True,
        feature_general_mode_enabled=True,
        atencion_cycles=cycles,
    )
    handler = AsyncMock(return_value="should-not-run")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111, text="PROMOS", chat_id=555), data)
    assert result is None
    assert cycles.starts == []


@pytest.mark.asyncio
async def test_promo_retrigger_does_not_reset_cycle() -> None:
    """F4: a re-trigger of the promo runs again but start_if_absent keeps the
    original started_at (idempotent) — linear window, never extended."""
    vips = InMemoryVipStore()
    trig = _trigger("promos")
    promo = _promo_mock(trigger=trig)
    cycles = _CyclesStore(active=True)
    mw = AuthMiddleware(
        vips=vips,
        promo=promo,
        feature_promo_enabled=True,
        feature_general_mode_enabled=True,
        atencion_cycles=cycles,
    )
    handler = AsyncMock(return_value="should-not-run")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(111, text="PROMOS", chat_id=555), data)
    assert result is None
    promo.execute_promo.assert_awaited_once()
    # start_if_absent is called again (idempotent by SQL ON CONFLICT); the
    # store records the attempt but never overwrites started_at.
    assert 555 in cycles.starts
