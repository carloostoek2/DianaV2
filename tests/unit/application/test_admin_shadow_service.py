"""Unit tests for AdminShadowService (owner consult surface, read-only)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aiogram.types import Chat, Message
from unittest.mock import AsyncMock

from diana.application.admin_shadow_service import AdminShadowService
from diana.telegram.handlers.menu import _dispatch_action
from diana.telegram.keyboards import MenuCallback, menu_shadow_keyboard


def _vip(vip_id, name: str = "María", user_id: int = 123):
    return SimpleNamespace(
        id=vip_id, telegram_user_id=user_id, display_name=name
    )


def _trust(vip_id, *, category="fatico", score=0.30, auton=2, corr=0):
    return SimpleNamespace(
        vip_id=vip_id,
        turn_category=category,
        trust_score=score,
        correction_count=corr,
        autonomous_count=auton,
        last_correction_at=None,
    )


def _turn(vip_id, *, confidence=0.70, when=None):
    return SimpleNamespace(
        turn_id=uuid4(),
        vip_id=vip_id,
        category="fatico",
        chat_id=42,
        confidence=confidence,
        would_autonomous=True,
        created_at=when or datetime(2026, 8, 22, 15, 42, tzinfo=UTC),
    )


class _FakeTurnCategories:
    def __init__(self, would=None, counts=None, *, fail=False):
        self._would = would or []
        self._counts = counts or []
        self._fail = fail

    async def list_would_autonomous(self, limit: int):
        if self._fail:
            raise RuntimeError("boom")
        return self._would[:limit]

    async def daily_counts(self, days: int):
        if self._fail:
            raise RuntimeError("boom")
        return self._counts


class _FakeTrust:
    def __init__(self, rows=None, *, fail=False):
        self._rows = rows or []
        self._fail = fail

    async def list_all(self):
        if self._fail:
            raise RuntimeError("boom")
        return self._rows


class _FakeVips:
    def __init__(self, vips=None):
        self._vips = vips or []

    async def list_active(self):
        return self._vips


def _build(
    turns=None,
    trust=None,
    vips=None,
    counts=None,
    *,
    thresholds=None,
    fail=False,
):
    return AdminShadowService(
        turn_categories=_FakeTurnCategories(would=turns, counts=counts, fail=fail),
        trust_budget=_FakeTrust(rows=trust, fail=fail),
        vips=_FakeVips(vips=vips),
        thresholds=thresholds,
    )


# ---------------------------------------------------------------------------
# render_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_shows_totals_trend_and_thresholds() -> None:
    vip_id = uuid4()
    service = _build(
        counts=[
            {"day": date(2026, 8, 20), "total": 5, "autonomous": 1},
            {"day": date(2026, 8, 21), "total": 3, "autonomous": 0},
        ],
        trust=[_trust(vip_id)],
    )
    body = await service.render_summary()
    assert "Totales: 8 turnos medidos · 1 habría enviado sola · 0 correcciones de la dueña" in body
    assert "20/08 — 5 turnos · 1 habría enviado" in body
    assert "21/08 — 3 turnos" in body
    assert "🎚 Umbrales actuales:" in body
    assert "Confianza para enviar sola: 0.90" in body
    assert "Confianza del clasificador: 0.70" in body
    assert 'Mensaje que habría enviado: "Holis 😁"' in body
    assert "Última medición: 21/08" in body


@pytest.mark.asyncio
async def test_summary_empty_is_honest() -> None:
    service = _build()
    body = await service.render_summary()
    assert "Totales: 0 turnos medidos" in body
    assert "Última medición: —" in body


@pytest.mark.asyncio
async def test_summary_read_failure_is_fail_soft() -> None:
    service = _build(fail=True)
    body = await service.render_summary()
    assert "No se pudo leer la información" in body


# ---------------------------------------------------------------------------
# render_by_vip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_by_vip_shows_score_autonomous_and_threshold_mark() -> None:
    vip_id = uuid4()
    service = _build(
        trust=[
            _trust(vip_id, category="fatico", score=0.30, auton=2),
            _trust(vip_id, category="informativo", score=0.95, auton=5),
        ],
        vips=[_vip(vip_id, name="María")],
    )
    body = await service.render_by_vip()
    assert "👤 María" in body
    assert "[fatico] 0.30 · autónomos 2 · correcciones 0 · ⏳ en camino" in body
    assert "[informativo] 0.95 · autónomos 5 · correcciones 0 · ✅ cumple" in body


@pytest.mark.asyncio
async def test_by_vip_empty() -> None:
    service = _build()
    body = await service.render_by_vip()
    assert "Todavía no hay confianza medida para ningún VIP." in body


# ---------------------------------------------------------------------------
# render_drafts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drafts_shows_would_be_message() -> None:
    vip_id = uuid4()
    service = _build(
        turns=[_turn(vip_id, confidence=0.70)],
        vips=[_vip(vip_id, name="María")],
    )
    body = await service.render_drafts()
    assert "1. 22/08 · María · fatico (conf. 0.70)" in body
    assert 'Habría enviado: "Holis 😁"' in body


@pytest.mark.asyncio
async def test_drafts_empty() -> None:
    service = _build()
    body = await service.render_drafts()
    assert "Todavía no hay turnos donde habría enviado sola." in body


# ---------------------------------------------------------------------------
# keyboard + dispatch
# ---------------------------------------------------------------------------


def test_shadow_keyboard_actions_and_back() -> None:
    kb = menu_shadow_keyboard()
    rows = kb.inline_keyboard
    assert len(rows) == 4
    assert rows[0][0].callback_data == "m:sombra:summary"
    assert rows[1][0].callback_data == "m:sombra:vips"
    assert rows[2][0].callback_data == "m:sombra:drafts"
    assert rows[3][0].callback_data == "m:root"


def test_parse_sombra_callbacks() -> None:
    from diana.telegram.keyboards import parse_menu_callback

    parsed = parse_menu_callback("m:sombra:summary")
    assert parsed is not None and parsed.category == "sombra"
    assert parsed.action == "summary"
    parsed = parse_menu_callback("m:sombra")
    assert parsed is not None and parsed.category == "sombra"
    assert parsed.action is None


@pytest.mark.asyncio
async def test_dispatch_sombra_renders_summary() -> None:
    vip_id = uuid4()
    service = _build(
        counts=[{"day": date(2026, 8, 22), "total": 4, "autonomous": 1}],
        trust=[_trust(vip_id)],
        vips=[_vip(vip_id)],
    )
    msg = AsyncMock(spec=Message)
    msg.message_id = 1
    msg.chat = AsyncMock(spec=Chat)
    msg.chat.id = 42
    msg.edit_text = AsyncMock()
    msg.answer = AsyncMock()

    await _dispatch_action(
        msg,
        parsed=MenuCallback(category="sombra", action="summary"),
        actor_id=999,
        vips=_FakeVips(),
        admin_trace=None,
        admin_metrics=None,
        shadow_admin=service,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=None,
    )
    call_args = msg.edit_text.call_args
    assert call_args is not None
    assert "Modo sombra — Resumen" in call_args[0][0]
    assert "Totales: 4 turnos medidos · 1 habría enviado sola" in call_args[0][0]
