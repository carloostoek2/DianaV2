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
