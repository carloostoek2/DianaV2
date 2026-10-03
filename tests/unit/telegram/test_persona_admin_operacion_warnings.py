"""Panel ⚙️ Operación: avisos de alias que Diana no usa (B7) y G2 en el panel.

Los avisos se calculan con el catálogo del canal de la sesión (VIP vs
atención aislados) y nunca bloquean un guardado; los alias nuevos sí pasan la
regla estricta.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import inspect

from diana.application.persona_admin_service import PersonaAdminService, prepare_persona_payload
from diana.cognitive.operacion import alias_issues
from diana.cognitive.persona_catalog import get_persona_atencion_catalog, get_persona_catalog
from diana.telegram.handlers.menu import MenuCallback, MenuSession, MenuSessionStore
from diana.telegram.handlers import persona_admin as persona_admin_module
from diana.telegram.handlers.persona_admin import (
    _ADD_PROMPTS,
    _edit_current_value,
    _item_full_text,
    _section_items,
    apply_persona_edit,
    dispatch_personalidad,
    handle_persona_edit_text,
)

_OWNER_ID = 999
# Mismos alias en los dos canales: "mi familia" choca con un tema de VIP,
# "mi negocio" con uno de atención.
ITEMS = [
    {"id": "lucien", "hecho": "Lucien es el bot.", "alias": ["Lucien", "mi familia", "mi negocio"]},
    {"id": "canal_vip", "hecho": "El canal VIP se llama El Diván.", "alias": ["canal vip"]},
]


def _cat(base: dict, items: list[dict] | None = None) -> dict:
    cat = deepcopy(base)
    cat["operacion"] = deepcopy(ITEMS if items is None else items)
    return cat


def _vip() -> dict:
    return _cat(get_persona_catalog())


def _atn() -> dict:
    return _cat(get_persona_atencion_catalog())


def _msg() -> AsyncMock:
    msg = AsyncMock()
    msg.message_id = 1
    msg.chat = AsyncMock()
    msg.chat.id = 42
    msg.edit_text = AsyncMock()
    msg.answer = AsyncMock()
    return msg


def _shown(msg: AsyncMock) -> str:
    call = msg.edit_text.call_args
    return str(call.args[0] if call.args else call.kwargs.get("text", ""))


class _Admin:
    """Read-only PersonaAdminService double with one catalog per channel."""

    def __init__(self, by_channel: dict[str, dict]) -> None:
        self.by_channel = by_channel
        self.requested: list[str] = []

    async def get_current_persona(self, channel_type: str = "vip") -> dict | None:
        self.requested.append(channel_type)
        return self.by_channel.get(channel_type)

    def operacion_alias_issues(self, catalog: dict) -> list[Any]:
        return alias_issues(catalog)


def _sessions(channel: str) -> MenuSessionStore:
    sessions = MenuSessionStore()
    sessions.start(_OWNER_ID, "persona_edit", persona_channel=channel)
    return sessions


async def _dispatch(admin: _Admin, channel: str, action: str, extra: str | None = None) -> str:
    msg = _msg()
    await dispatch_personalidad(
        msg, parsed=MenuCallback(category="personalidad", action=action, extra=extra),
        actor_id=_OWNER_ID, persona_admin=admin, sessions=_sessions(channel),  # type: ignore[arg-type]
    )
    return _shown(msg)


# --- render puro -----------------------------------------------------------------


def test_list_marks_items_with_ignored_aliases() -> None:
    labels = dict(_section_items(_vip(), "operacion", issues=alias_issues(_vip())))
    assert labels["lucien"].startswith("⚠️ lucien")
    assert labels["canal_vip"].startswith("⚙️ canal_vip")


def test_detail_explains_each_ignored_alias_in_product_language() -> None:
    detail = _item_full_text(_vip(), "operacion", "lucien", issues=alias_issues(_vip()))
    assert detail is not None
    assert "Alias: Lucien, mi familia, mi negocio" in detail
    assert "⚠️ Alias que Diana no usa" in detail
    assert "• el alias «mi familia» choca con un tema de Datos personales" in detail
    assert "mi negocio»" not in detail.split("⚠️", 1)[1]  # en VIP "negocio" no es tema
    clean = _item_full_text(_vip(), "operacion", "canal_vip", issues=alias_issues(_vip()))
    assert clean is not None and "⚠️" not in clean


def test_edit_prompt_current_value_also_shows_the_warning() -> None:
    current = _edit_current_value(_vip(), "operacion", "lucien", issues=alias_issues(_vip()))
    assert current is not None and "«mi familia»" in current and "⚠️" in current


def test_add_prompt_explains_the_new_rules() -> None:
    prompt = _ADD_PROMPTS["operacion"]
    assert "3 si es un nombre propio con mayúscula" in prompt
    assert "«mayordomo»" in prompt
    assert "Lucien, el mayordomo" in prompt  # el ejemplo se conserva


# --- aislamiento VIP / atención en los avisos -------------------------------------


async def test_warnings_use_the_session_channel_catalog_only() -> None:
    admin = _Admin({"vip": _vip(), "atencion": _atn()})
    vip = await _dispatch(admin, "vip", "item", "operacion|lucien")
    atn = await _dispatch(admin, "atencion", "item", "operacion|lucien")
    assert "«mi familia»" in vip.split("⚠️", 1)[1] and "«mi negocio»" not in vip.split("⚠️", 1)[1]
    assert "«mi negocio»" in atn.split("⚠️", 1)[1] and "«mi familia»" not in atn.split("⚠️", 1)[1]
    assert admin.requested == ["vip", "atencion"]


async def test_list_note_only_when_the_channel_has_ignored_aliases() -> None:
    clean = [{"id": "canal_vip", "hecho": "h", "alias": ["canal vip"]}]
    admin = _Admin({"vip": _vip(), "atencion": _cat(get_persona_atencion_catalog(), clean)})
    assert "Los elementos marcados tienen alias que Diana no usa" in await _dispatch(
        admin, "vip", "operacion"
    )
    assert "alias que Diana no usa" not in await _dispatch(admin, "atencion", "operacion")


# --- G2 en el panel -------------------------------------------------------------------


def _edit_and_prepare(base: dict, op: str, extra: str | None, text: str) -> dict:
    """Panel edit + the single write-path validation (R-1, same as the service)."""
    return prepare_persona_payload(apply_persona_edit(base, op, extra, text), previous=base)


def test_editing_an_item_keeps_legacy_aliases_but_rejects_new_bad_ones() -> None:
    base = _vip()
    edited = _edit_and_prepare(
        base, "operacion", "lucien", "lucien | Lucien, mi familia, mi negocio | Lucien administra el VIP."
    )
    assert edited["operacion"][0]["hecho"] == "Lucien administra el VIP."
    with pytest.raises(ValueError, match="común"):
        _edit_and_prepare(base, "operacion", "lucien", "lucien | Lucien, mi familia, Sol | hecho")
    with pytest.raises(ValueError, match="Datos personales"):
        _edit_and_prepare(base, "operacion", None, "otro | mi familia | hecho")


@pytest.mark.parametrize(("alias", "ok"), [("Ana", True), ("ana", False), ("Leo", False)])
def test_panel_three_letter_aliases(alias: str, ok: bool) -> None:
    text = f"ana | {alias} | Ana lleva la agenda."
    base = get_persona_catalog()
    if ok:
        added = _edit_and_prepare(base, "operacion", None, text)
        assert added["operacion"][-1]["alias"] == ["Ana"]  # se guarda tal cual
    else:
        with pytest.raises(ValueError):
            _edit_and_prepare(base, "operacion", None, text)


def test_panel_no_longer_validates_operacion_semantics() -> None:
    # R-1: the panel only parses; the alias policy lives in the service path.
    edited = apply_persona_edit(_vip(), "operacion", None, "otro | mi familia | hecho")
    assert edited["operacion"][-1]["alias"] == ["mi familia"]
    assert "validate_operacion_semantics" not in inspect.getsource(persona_admin_module)


class _SpyAdmin(_Admin):
    def __init__(self, by_channel: dict[str, dict]) -> None:
        super().__init__(by_channel)
        self.issue_calls = 0

    def operacion_alias_issues(self, catalog: dict) -> list[Any]:
        self.issue_calls += 1
        return alias_issues(catalog)


async def test_alias_issues_computed_once_per_render() -> None:
    admin = _SpyAdmin({"vip": _vip()})
    listing = await _dispatch(admin, "vip", "operacion")
    assert admin.issue_calls == 1
    assert "⚠️ lucien" in str(listing) or "alias que Diana no usa" in listing
    admin.issue_calls = 0
    detail = await _dispatch(admin, "vip", "item", "operacion|lucien")
    assert admin.issue_calls == 1
    assert "«mi familia»" in detail


class _Store:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def list_versions(self, channel_type: str | None = None) -> list[Any]:
        return list(self.rows)

    async def insert_version(self, *, version, source, payload, created_by, channel_type):
        rec = SimpleNamespace(id=uuid4(), version=version, payload=deepcopy(payload),
                              is_active=False, channel_type=channel_type)
        self.rows.append(rec)
        return rec

    async def activate_version(self, record_id, *, now, channel_type="vip"):
        found = None
        for r in self.rows:
            if r.channel_type == channel_type:
                r.is_active = r.id == record_id
                if r.is_active:
                    found = r
        return found

    async def get_active(self, *, channel_type: str = "vip") -> Any:
        return next((r for r in self.rows if r.is_active and r.channel_type == channel_type), None)


async def test_wizard_edits_a_dato_personal_despite_legacy_operacion_alias() -> None:
    # Panel real + servicio real: el alias legacy "mi familia" no bloquea editar un Dato.
    store = _Store()
    legacy = _vip()
    rec = await store.insert_version(version=1, source="db", payload=legacy,
                                     created_by=_OWNER_ID, channel_type="vip")
    await store.activate_version(rec.id, now=None, channel_type="vip")
    svc = PersonaAdminService(payload_store=store, feature_persona_admin_enabled=True,
                              owner_telegram_id=_OWNER_ID)
    fact = legacy["persona_facts"][0]
    msg = AsyncMock()
    msg.text = f"{fact['id']} | {', '.join(fact['tema'])} | Hecho editado."
    msg.from_user = AsyncMock()
    msg.from_user.id = _OWNER_ID
    msg.answer = AsyncMock()
    bot = AsyncMock()
    bot.edit_message_text = AsyncMock()
    session = MenuSession(kind="persona_edit", persona_section="fact", persona_target=fact["id"],
                          last_bot_message_id=1, last_chat_id=42, persona_channel="vip")
    sessions = MenuSessionStore()
    await handle_persona_edit_text(msg, bot, session, svc, sessions)
    assert sessions.get(_OWNER_ID).persona_draft is not None  # C3: preview first
    tap = _msg()
    await dispatch_personalidad(
        tap, parsed=MenuCallback(category="personalidad", action="draft_save",
                                 extra=sessions.get(_OWNER_ID).persona_draft["token"]),
        actor_id=_OWNER_ID, persona_admin=svc, sessions=sessions,
    )
    assert "✅ Guardado como versión v2" in _shown(tap)
    active = await store.get_active(channel_type="vip")
    assert active.payload["persona_facts"][0]["hecho"] == "Hecho editado."
    assert active.payload["operacion"] == legacy["operacion"]
