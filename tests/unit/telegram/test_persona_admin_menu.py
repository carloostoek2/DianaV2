"""Unit tests for the Personalidad y reglas admin (Item 3)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from diana.application.ports import PersonaVersionRecord
from diana.cognitive.persona_catalog import get_persona_catalog
from diana.telegram.handlers.menu import MenuSession, MenuSessionStore
from diana.telegram.handlers.persona_admin import (
    apply_persona_edit,
    dispatch_personalidad,
    handle_persona_edit_text,
    load_current,
)
from diana.telegram.keyboards import (
    MenuCallback,
    encode_menu,
    encode_menu_persona,
    menu_persona_confirm_restore_keyboard,
    menu_persona_list_keyboard,
    menu_personalidad_keyboard,
    menu_root_keyboard,
    parse_menu_callback,
)

_OWNER_ID = 999


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakePersonaAdmin:
    """In-memory PersonaAdminService double (channel_type-aware for REQ-ATN-06)."""

    def __init__(self, current: dict | None = None) -> None:
        self.current = current
        self.channel_currents: dict[str, dict] = {}
        self.records: list[PersonaVersionRecord] = []
        self.saved: list[dict] = []
        self.version_counter = 0
        self.last_channel_type: str | None = None
        self.last_save_channel_type: str | None = None
        self.last_restore_channel_type: str | None = None
        self.last_list_channel_type: str | None = None

    async def get_current_persona(self, channel_type: str = "vip") -> dict | None:
        self.last_channel_type = channel_type
        if channel_type in self.channel_currents:
            return self.channel_currents[channel_type]
        if channel_type == "vip":
            return self.current
        return None

    async def save_persona(
        self, actor_id, payload: dict, channel_type: str = "vip"
    ) -> PersonaVersionRecord:
        import copy

        snapshot = copy.deepcopy(payload)
        self.version_counter += 1
        self.saved.append(snapshot)
        self.last_save_channel_type = channel_type
        record = PersonaVersionRecord(
            id=uuid4(),
            version=self.version_counter,
            source="db",
            payload=snapshot,
            created_by=actor_id,
            created_at=datetime.now(UTC),
        )
        self.records.append(record)
        self.current = snapshot
        self.channel_currents[channel_type] = snapshot
        return record

    async def list_versions(
        self, actor_id, channel_type: str | None = None
    ) -> list[PersonaVersionRecord]:
        self.last_list_channel_type = channel_type
        return list(reversed(self.records))

    async def restore(
        self, actor_id, persona_version_id, channel_type: str = "vip"
    ) -> PersonaVersionRecord | None:
        import copy

        self.last_restore_channel_type = channel_type
        for record in self.records:
            if str(record.id) == str(persona_version_id):
                self.current = copy.deepcopy(record.payload)
                self.channel_currents[channel_type] = copy.deepcopy(record.payload)
                return record
        return None


def _msg() -> AsyncMock:
    msg = AsyncMock()
    msg.message_id = 1
    msg.chat = AsyncMock()
    msg.chat.id = 42
    msg.edit_text = AsyncMock()
    msg.answer = AsyncMock()
    return msg


def _parsed(action: str | None, extra: str | None = None) -> MenuCallback:
    return MenuCallback(category="personalidad", action=action, extra=extra)


def _sessions() -> MenuSessionStore:
    return MenuSessionStore()


def _base_catalog() -> dict:
    return get_persona_catalog()


# ---------------------------------------------------------------------------
# apply_persona_edit — pure edit application
# ---------------------------------------------------------------------------


def test_apply_edit_persona_and_does_not_mutate_base() -> None:
    base = _base_catalog()
    nuevo = apply_persona_edit(base, "persona", None, "Nueva descripción de Diana")
    assert nuevo["voz_configurada"]["persona"] == "Nueva descripción de Diana"
    # base untouched (deep-copied slices)
    assert base["voz_configurada"]["persona"] != "Nueva descripción de Diana"


def test_apply_edit_rule_add_replace_delete() -> None:
    base = _base_catalog()
    rules = base["voz_configurada"]["reglas_estilo"]

    # add
    n1 = apply_persona_edit(base, "rule", None, "Regla nueva")
    assert n1["voz_configurada"]["reglas_estilo"][-1] == "Regla nueva"
    assert len(n1["voz_configurada"]["reglas_estilo"]) == len(rules) + 1

    # replace index 0
    n2 = apply_persona_edit(n1, "rule", "0", "Regla reemplazada")
    assert n2["voz_configurada"]["reglas_estilo"][0] == "Regla reemplazada"

    # delete index 1
    n3 = apply_persona_edit(n2, "rule_del", "1", None)
    assert len(n3["voz_configurada"]["reglas_estilo"]) == len(n2["voz_configurada"]["reglas_estilo"]) - 1

    # guard: cannot delete the last rule
    solo = {"voz_configurada": {"persona": "x", "reglas_estilo": ["única"]},
            "persona_facts": [{"id": "f", "tema": ["t"], "hecho": "h"}],
            "voice_patterns": [{"id": "p", "tags": ["a"], "patron": "x", "uso": "y"}],
            "policies": [{"id": "pol", "tema": ["t"], "regla": "r"}],
            "schedule": {"timezone": "America/Mexico_City", "default_responses": ["d"], "bloques": []}}
    with pytest.raises(ValueError, match="último"):
        apply_persona_edit(solo, "rule_del", "0", None)


def test_apply_edit_fact_add_edit_delete() -> None:
    base = _base_catalog()
    n1 = apply_persona_edit(base, "fact", None, "nuevo_id | estudios, familia | Hecho nuevo")
    assert n1["persona_facts"][-1]["id"] == "nuevo_id"
    assert n1["persona_facts"][-1]["tema"] == ["estudios", "familia"]

    target_id = base["persona_facts"][0]["id"]
    n2 = apply_persona_edit(n1, "fact", target_id, f"{target_id} | familia | Hecho editado")
    edited = next(f for f in n2["persona_facts"] if f["id"] == target_id)
    assert edited["hecho"] == "Hecho editado"

    n3 = apply_persona_edit(n2, "fact_del", target_id, None)
    assert all(f["id"] != target_id for f in n3["persona_facts"])


def test_apply_edit_parsers_validation() -> None:
    base = _base_catalog()
    with pytest.raises(ValueError, match="formato"):
        apply_persona_edit(base, "fact", None, "sin separadores")
    with pytest.raises(ValueError, match="formato"):
        apply_persona_edit(base, "pattern", None, "id | tags | solo3")
    with pytest.raises(ValueError, match="formato"):
        apply_persona_edit(base, "policy", None, "id | tema")
    with pytest.raises(ValueError, match="formato"):
        apply_persona_edit(base, "bloque", None, "lunes | 09:00 | 12:00")
    with pytest.raises(ValueError):
        apply_persona_edit(base, "unknown_op", None, "x")


def test_apply_edit_schedule_blocks_defaults_timezone() -> None:
    base = _base_catalog()
    n1 = apply_persona_edit(base, "bloque", None, "lunes, martes | 09:00 | 12:00 | servicio social")
    assert n1["schedule"]["bloques"][-1] == {
        "dias": ["lunes", "martes"], "inicio": "09:00", "fin": "12:00", "actividad": "servicio social",
    }
    n2 = apply_persona_edit(n1, "default", None, "Respuesta libre nueva")
    assert n2["schedule"]["default_responses"][-1] == "Respuesta libre nueva"
    n3 = apply_persona_edit(n2, "timezone", None, "America/Argentina/Buenos_Aires")
    assert n3["schedule"]["timezone"] == "America/Argentina/Buenos_Aires"
    # guard: cannot delete last bloque
    solo = {"voz_configurada": {"persona": "x", "reglas_estilo": ["r"]},
            "persona_facts": [{"id": "f", "tema": ["t"], "hecho": "h"}],
            "voice_patterns": [{"id": "p", "tags": ["a"], "patron": "x", "uso": "y"}],
            "policies": [{"id": "pol", "tema": ["t"], "regla": "r"}],
            "schedule": {"timezone": "America/Mexico_City", "default_responses": ["d"],
                         "bloques": [{"dias": ["lunes"], "inicio": "09:00", "fin": "12:00", "actividad": "x"}]}}
    with pytest.raises(ValueError, match="último bloque"):
        apply_persona_edit(solo, "bloque_del", "0", None)


# ---------------------------------------------------------------------------
# Callbacks / keyboards
# ---------------------------------------------------------------------------


def test_personalidad_keyboard_channel_row() -> None:
    """REQ-ATN-06: the channel selector row renders both channel callbacks."""
    kb = menu_personalidad_keyboard()
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert encode_menu_persona("channel", "vip") in datas
    assert encode_menu_persona("channel", "atencion") in datas
    # section rows are still present (backward compat)
    assert encode_menu_persona("persona") in datas


def test_encode_menu_persona_under_64_bytes_and_parse_roundtrip() -> None:
    data = encode_menu_persona("restore", str(uuid4()))
    assert len(data.encode("utf-8")) <= 64
    parsed = parse_menu_callback(data)
    assert parsed is not None
    assert parsed.category == "personalidad"
    assert parsed.action == "restore"
    assert parsed.extra is not None

    data2 = encode_menu_persona("item", "facts|familia_hermana")
    parsed2 = parse_menu_callback(data2)
    assert parsed2 is not None
    assert parsed2.action == "item"
    assert parsed2.extra == "facts|familia_hermana"


def test_menu_root_keyboard_show_persona() -> None:
    default = menu_root_keyboard()
    assert len(default.inline_keyboard) == 6

    with_persona = menu_root_keyboard(show_persona=True)
    assert len(with_persona.inline_keyboard) == 7
    assert any(
        b.callback_data == encode_menu("personalidad")
        for row in with_persona.inline_keyboard
        for b in row
    )


def test_personalidad_keyboards_shape() -> None:
    kb = menu_personalidad_keyboard()
    actions = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert encode_menu_persona("persona") in actions
    assert encode_menu_persona("rules") in actions
    assert encode_menu_persona("history") in actions
    assert encode_menu("root") in actions

    list_kb = menu_persona_list_keyboard(
        [("facts|f1", "👤 f1"), ("facts|f2", "👤 f2")], add_action="fact_add"
    )
    datas = [b.callback_data for row in list_kb.inline_keyboard for b in row]
    assert encode_menu_persona("item", "facts|f1") in datas
    assert encode_menu_persona("fact_add") in datas

    hist_kb = menu_persona_list_keyboard(
        [("abc", "v1 · 01/01 10:00")], add_action=None, item_action="restore"
    )
    datas = [b.callback_data for row in hist_kb.inline_keyboard for b in row]
    assert encode_menu_persona("restore", "abc") in datas
    assert "➕ Agregar" not in datas

    confirm = menu_persona_confirm_restore_keyboard("abc")
    datas = [b.callback_data for row in confirm.inline_keyboard for b in row]
    assert encode_menu_persona("restore_ok", "abc") in datas


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_personalidad_no_service() -> None:
    msg = _msg()
    await dispatch_personalidad(
        msg, parsed=_parsed("persona"), actor_id=_OWNER_ID, persona_admin=None, sessions=_sessions()
    )
    msg.edit_text.assert_awaited_once()
    assert "no disponible" in str(msg.edit_text.call_args.args[0])


@pytest.mark.asyncio
async def test_dispatch_persona_view() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    msg = _msg()
    await dispatch_personalidad(
        msg, parsed=_parsed("persona"), actor_id=_OWNER_ID, persona_admin=service, sessions=_sessions()
    )
    msg.edit_text.assert_awaited_once()
    text = str(msg.edit_text.call_args.args[0])
    assert "Cómo habla Diana" in text
    assert "Eres Diana" in text


@pytest.mark.asyncio
async def test_dispatch_rules_list_and_item_detail() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    msg = _msg()
    await dispatch_personalidad(
        msg, parsed=_parsed("rules"), actor_id=_OWNER_ID, persona_admin=service, sessions=_sessions()
    )
    msg.edit_text.assert_awaited_once()
    # item detail — buttons must use SINGULAR ops (rule_edit/rule_del), so the
    # tap→dispatch round-trip actually works (review round 1 bug).
    msg2 = _msg()
    await dispatch_personalidad(
        msg2, parsed=_parsed("item", "rules|0"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=_sessions(),
    )
    msg2.edit_text.assert_awaited_once()
    # FULL rule text in the detail view (product fix: no truncation)
    detail_text = str(msg2.edit_text.call_args.args[0])
    assert "Regla #1" in detail_text
    assert service.current["voz_configurada"]["reglas_estilo"][0] in detail_text
    markup_obj = msg2.edit_text.call_args.kwargs.get("reply_markup")
    datas = [b.callback_data for row in markup_obj.inline_keyboard for b in row]
    assert encode_menu_persona("rule_edit", "0") in datas
    assert encode_menu_persona("rule_del", "0") in datas
    assert "rules_edit" not in datas  # plural actions are dead — regression guard
    # Volver must go back to the section LIST (r2 bug: plural section → dead callback)
    assert encode_menu_persona("rules") in datas

    # round-trip for an id-based section (facts) + edit wizard start
    fact_id = service.current["persona_facts"][0]["id"]
    msg3 = _msg()
    await dispatch_personalidad(
        msg3, parsed=_parsed("item", f"facts|{fact_id}"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=_sessions(),
    )
    markup3 = msg3.edit_text.call_args.kwargs.get("reply_markup")
    datas3 = [b.callback_data for row in markup3.inline_keyboard for b in row]
    assert encode_menu_persona("fact_edit", fact_id) in datas3
    assert encode_menu_persona("facts") in datas3

    sessions = _sessions()
    msg4 = _msg()
    await dispatch_personalidad(
        msg4, parsed=_parsed("fact_edit", fact_id), actor_id=_OWNER_ID,
        persona_admin=service, sessions=sessions,
    )
    session = sessions.get(_OWNER_ID)
    assert session is not None
    assert session.persona_section == "fact"
    assert session.persona_target == fact_id


@pytest.mark.asyncio
async def test_dispatch_immediate_delete_saves() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    msg = _msg()
    await dispatch_personalidad(
        msg, parsed=_parsed("rule_del", "0"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=_sessions(),
    )
    assert len(service.saved) == 1
    saved_rules = service.saved[0]["voz_configurada"]["reglas_estilo"]
    assert len(saved_rules) == len(_base_catalog()["voz_configurada"]["reglas_estilo"]) - 1


@pytest.mark.asyncio
async def test_dispatch_wizard_start_creates_session() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    sessions = _sessions()
    msg = _msg()
    await dispatch_personalidad(
        msg, parsed=_parsed("rule_add"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=sessions,
    )
    session = sessions.get(_OWNER_ID)
    assert session is not None
    assert session.kind == "persona_edit"
    assert session.persona_section == "rule"
    assert session.persona_target is None


@pytest.mark.asyncio
async def test_dispatch_history_and_restore_flow() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    v1 = await service.save_persona(_OWNER_ID, _base_catalog())

    msg = _msg()
    await dispatch_personalidad(
        msg, parsed=_parsed("history"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=_sessions(),
    )
    msg.edit_text.assert_awaited_once()

    msg2 = _msg()
    await dispatch_personalidad(
        msg2, parsed=_parsed("restore", str(v1.id)), actor_id=_OWNER_ID,
        persona_admin=service, sessions=_sessions(),
    )
    assert "restaurar" in str(msg2.edit_text.call_args.args[0]).lower()

    import copy

    modified = copy.deepcopy(_base_catalog())
    modified["voz_configurada"]["reglas_estilo"].append("regla v2")
    v2 = await service.save_persona(_OWNER_ID, modified)
    assert service.current["voz_configurada"]["reglas_estilo"][-1] == "regla v2"

    msg3 = _msg()
    await dispatch_personalidad(
        msg3, parsed=_parsed("restore_ok", str(v1.id)), actor_id=_OWNER_ID,
        persona_admin=service, sessions=_sessions(),
    )
    text3 = str(msg3.edit_text.call_args.args[0])
    assert "restaurada" in text3
    assert f"v{v1.version}" in text3
    # restore actually re-activated v1's payload over v2 (deepcopy: no tautology)
    assert "regla v2" not in service.current["voz_configurada"]["reglas_estilo"]
    assert service.current["voz_configurada"]["reglas_estilo"] == copy.deepcopy(
        _base_catalog()
    )["voz_configurada"]["reglas_estilo"]


# ---------------------------------------------------------------------------
# Wizard text handling
# ---------------------------------------------------------------------------


def _session(section: str, target: str | None = None) -> MenuSession:
    return MenuSession(
        kind="persona_edit",
        persona_section=section,
        persona_target=target,
        last_bot_message_id=1,
        last_chat_id=42,
    )


def _bot() -> AsyncMock:
    bot = AsyncMock()
    bot.edit_message_text = AsyncMock()
    return bot


@pytest.mark.asyncio
async def test_wizard_append_rule_saves_version() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    msg = AsyncMock()
    msg.text = "Regla capturada por wizard"
    msg.from_user = AsyncMock()
    msg.from_user.id = _OWNER_ID
    msg.answer = AsyncMock()
    bot = _bot()

    await handle_persona_edit_text(
        msg, bot, _session("rule"), service, _sessions()
    )
    assert len(service.saved) == 1
    rules = service.saved[0]["voz_configurada"]["reglas_estilo"]
    assert rules[-1] == "Regla capturada por wizard"
    # success feedback via edit_or_answer (bot.edit_message_text attempted)
    bot.edit_message_text.assert_awaited()
    assert "versión v1" in str(bot.edit_message_text.call_args.kwargs.get("text", ""))


@pytest.mark.asyncio
async def test_wizard_invalid_format_does_not_save() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    msg = AsyncMock()
    msg.text = "mal formato sin pipes"
    msg.from_user = AsyncMock()
    msg.from_user.id = _OWNER_ID
    msg.answer = AsyncMock()
    bot = _bot()

    await handle_persona_edit_text(msg, bot, _session("fact"), service, _sessions())
    assert service.saved == []
    # error feedback shown (strict)
    assert bot.edit_message_text.await_count == 1
    assert "formato" in str(bot.edit_message_text.call_args.kwargs.get("text", ""))


@pytest.mark.asyncio
async def test_load_current_falls_back_to_static() -> None:
    service = _FakePersonaAdmin(None)  # flag off / no active version
    catalog = await load_current(service)  # type: ignore[arg-type]
    assert catalog is get_persona_catalog()


@pytest.mark.asyncio
async def test_load_current_atencion_static_failure_falls_back_to_vip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R1-4: a missing/corrupt persona_atencion.json must not crash load_current."""
    import diana.telegram.handlers.persona_admin as persona_admin_mod

    def _boom() -> dict:
        raise FileNotFoundError("persona_atencion.json missing")

    monkeypatch.setattr(persona_admin_mod, "get_persona_atencion_catalog", _boom)
    service = _FakePersonaAdmin(None)  # no DB row → static fallback path
    catalog = await load_current(service, channel_type="atencion")  # type: ignore[arg-type]
    assert catalog is get_persona_catalog()


def test_apply_edit_pattern_policy_positive() -> None:
    """Positive paths protect _parse_pattern/_parse_policy field mapping."""
    base = _base_catalog()

    n1 = apply_persona_edit(base, "pattern", None, "nuevo_patron | risa, casual | jsjs | Reemplaza jaja")
    last = n1["voice_patterns"][-1]
    assert last == {"id": "nuevo_patron", "tags": ["risa", "casual"], "patron": "jsjs", "uso": "Reemplaza jaja"}

    n2 = apply_persona_edit(base, "policy", None, "nueva_pol | contenido, limites | No prometo nada")
    last = n2["policies"][-1]
    assert last == {"id": "nueva_pol", "tema": ["contenido", "limites"], "regla": "No prometo nada"}

    # replace + delete by id
    target_id = base["voice_patterns"][0]["id"]
    n3 = apply_persona_edit(n2, "pattern", target_id, f"{target_id} | risa | jsjs | editado")
    edited = next(p_ for p_ in n3["voice_patterns"] if p_["id"] == target_id)
    assert edited["uso"] == "editado"
    n4 = apply_persona_edit(n3, "policy_del", "nueva_pol", None)
    assert all(p_["id"] != "nueva_pol" for p_ in n4["policies"])


def test_apply_edit_never_mutates_base_other_ops() -> None:
    """Deep-copied slices: base stays intact across all edit ops."""
    import copy

    base = _base_catalog()
    snapshot = copy.deepcopy(base)

    ops = [
        ("rule", None, "r nueva"),
        ("fact", None, "fid | tema | hecho"),
        ("pattern", None, "pid | tag | patron | uso"),
        ("policy", None, "polid | tema | regla"),
        ("bloque", None, "lunes | 09:00 | 12:00 | actividad"),
        ("default", None, "respuesta"),
        ("timezone", None, "America/Mexico_City"),
    ]
    for op, extra, text in ops:
        apply_persona_edit(base, op, extra, text)

    assert base["voz_configurada"]["persona"] == snapshot["voz_configurada"]["persona"]
    assert base["voz_configurada"]["reglas_estilo"] == snapshot["voz_configurada"]["reglas_estilo"]
    assert base["persona_facts"] == snapshot["persona_facts"]
    assert base["voice_patterns"] == snapshot["voice_patterns"]
    assert base["policies"] == snapshot["policies"]
    assert base["schedule"] == snapshot["schedule"]


def test_apply_edit_last_item_guards_typed_sections() -> None:
    """Cannot delete the last fact/pattern/policy/default_response."""
    solo = {
        "voz_configurada": {"persona": "x", "reglas_estilo": ["r"]},
        "persona_facts": [{"id": "f", "tema": ["t"], "hecho": "h"}],
        "voice_patterns": [{"id": "p", "tags": ["a"], "patron": "x", "uso": "y"}],
        "policies": [{"id": "pol", "tema": ["t"], "regla": "r"}],
        "schedule": {"timezone": "America/Mexico_City", "default_responses": ["d"], "bloques": []},
    }
    with pytest.raises(ValueError, match="último"):
        apply_persona_edit(solo, "fact_del", "f", None)
    with pytest.raises(ValueError, match="último"):
        apply_persona_edit(solo, "pattern_del", "p", None)
    with pytest.raises(ValueError, match="último"):
        apply_persona_edit(solo, "policy_del", "pol", None)
    with pytest.raises(ValueError, match="último"):
        apply_persona_edit(solo, "default_del", "0", None)


# ---------------------------------------------------------------------------
# Review-round fixes: subviews, edge cases, wizard edit-replace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_subviews_schedule_timezone() -> None:
    service = _FakePersonaAdmin(_base_catalog())

    msg = _msg()
    await dispatch_personalidad(msg, parsed=_parsed("schedule"), actor_id=_OWNER_ID,
                                persona_admin=service, sessions=_sessions())
    text = str(msg.edit_text.call_args.args[0])
    assert "Agenda" in text

    msg2 = _msg()
    await dispatch_personalidad(msg2, parsed=_parsed("timezone"), actor_id=_OWNER_ID,
                                persona_admin=service, sessions=_sessions())
    assert "America/Mexico_City" in str(msg2.edit_text.call_args.args[0])


@pytest.mark.asyncio
async def test_dispatch_section_lists_use_singular_item_actions() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    for action in ("facts", "patterns", "policies", "bloques", "defaults"):
        msg = _msg()
        await dispatch_personalidad(msg, parsed=_parsed(action), actor_id=_OWNER_ID,
                                    persona_admin=service, sessions=_sessions())
        msg.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_history_empty_and_restore_unknown() -> None:
    service = _FakePersonaAdmin(None)
    msg = _msg()
    await dispatch_personalidad(msg, parsed=_parsed("history"), actor_id=_OWNER_ID,
                                persona_admin=service, sessions=_sessions())
    assert "Todavía no hay versiones" in str(msg.edit_text.call_args.args[0])

    msg2 = _msg()
    await dispatch_personalidad(msg2, parsed=_parsed("restore_ok", str(uuid4())), actor_id=_OWNER_ID,
                                persona_admin=service, sessions=_sessions())
    assert "No se encontró" in str(msg2.edit_text.call_args.args[0])

    msg3 = _msg()
    await dispatch_personalidad(msg3, parsed=_parsed("restore_ok"), actor_id=_OWNER_ID,
                                persona_admin=service, sessions=_sessions())
    assert "Versión inválida" in str(msg3.edit_text.call_args.args[0])


@pytest.mark.asyncio
async def test_dispatch_delete_last_item_shows_error_and_does_not_save() -> None:
    import copy

    solo = copy.deepcopy(_base_catalog())
    solo["voz_configurada"]["reglas_estilo"] = ["única regla"]
    service = _FakePersonaAdmin(solo)
    msg = _msg()
    await dispatch_personalidad(msg, parsed=_parsed("rule_del", "0"), actor_id=_OWNER_ID,
                                persona_admin=service, sessions=_sessions())
    assert service.saved == []
    assert "No se pudo eliminar" in str(msg.edit_text.call_args.args[0])


@pytest.mark.asyncio
async def test_wizard_edit_replace_by_index_and_by_id() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    msg = AsyncMock()
    msg.text = "Regla reemplazada por wizard"
    msg.from_user = AsyncMock()
    msg.from_user.id = _OWNER_ID
    msg.answer = AsyncMock()
    msg.message_id = 7
    msg.chat = AsyncMock()
    msg.chat.id = 42
    bot = _bot()

    await handle_persona_edit_text(msg, bot, _session("rule", target="0"), service, _sessions())
    assert len(service.saved) == 1
    assert service.saved[0]["voz_configurada"]["reglas_estilo"][0] == "Regla reemplazada por wizard"
    assert service.records[0].created_by == _OWNER_ID

    # by id (fact)
    target_id = _base_catalog()["persona_facts"][0]["id"]
    msg2 = AsyncMock()
    msg2.text = f"{target_id} | familia | Hecho editado por wizard"
    msg2.from_user = AsyncMock()
    msg2.from_user.id = _OWNER_ID
    msg2.answer = AsyncMock()
    await handle_persona_edit_text(msg2, bot, _session("fact", target=target_id), service, _sessions())
    edited = next(f for f in service.saved[1]["persona_facts"] if f["id"] == target_id)
    assert edited["hecho"] == "Hecho editado por wizard"


@pytest.mark.asyncio
async def test_wizard_invalid_index_rejects_and_keeps_session() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    sessions = _sessions()
    sessions.start(_OWNER_ID, "persona_edit", persona_section="rule", persona_target="999",
                   last_bot_message_id=1, last_chat_id=42)
    session = sessions.pop(_OWNER_ID)
    msg = AsyncMock()
    msg.text = "texto"
    msg.from_user = AsyncMock()
    msg.from_user.id = _OWNER_ID
    msg.answer = AsyncMock()
    bot = _bot()

    await handle_persona_edit_text(msg, bot, session, service, sessions)
    assert service.saved == []
    # session re-started so the owner can retry
    restarted = sessions.get(_OWNER_ID)
    assert restarted is not None and restarted.persona_section == "rule"
    assert restarted.persona_target == "999"


def test_encode_menu_persona_rejects_overlong_extra() -> None:
    with pytest.raises(ValueError):
        encode_menu_persona("item", "facts|" + "x" * 60)


def test_parse_fact_id_length_capped() -> None:
    base = _base_catalog()
    with pytest.raises(ValueError, match="demasiado largo"):
        apply_persona_edit(base, "fact", None, "x" * 40 + " | tema | hecho")


@pytest.mark.asyncio
async def test_wizard_pattern_via_handler_saves() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    msg = AsyncMock()
    msg.text = "nuevo_patron | risa, casual | jsjs | Reemplaza jaja"
    msg.from_user = AsyncMock()
    msg.from_user.id = _OWNER_ID
    msg.answer = AsyncMock()
    msg.message_id = 1
    msg.chat = AsyncMock()
    msg.chat.id = 42
    bot = _bot()

    await handle_persona_edit_text(msg, bot, _session("pattern"), service, _sessions())
    assert len(service.saved) == 1
    last = service.saved[0]["voice_patterns"][-1]
    assert last == {"id": "nuevo_patron", "tags": ["risa", "casual"], "patron": "jsjs", "uso": "Reemplaza jaja"}


def test_parse_id_caps_pattern_and_policy() -> None:
    base = _base_catalog()
    with pytest.raises(ValueError, match="demasiado largo"):
        apply_persona_edit(base, "pattern", None, "x" * 40 + " | tag | patron | uso")
    with pytest.raises(ValueError, match="demasiado largo"):
        apply_persona_edit(base, "policy", None, "x" * 40 + " | tema | regla")


def test_apply_edit_empty_text_guards() -> None:
    base = _base_catalog()
    with pytest.raises(ValueError, match="descripción no puede estar vacía"):
        apply_persona_edit(base, "persona", None, "   ")
    with pytest.raises(ValueError, match="la regla no puede estar vacía"):
        apply_persona_edit(base, "rule", None, "  ")
    with pytest.raises(ValueError, match="elemento inválido"):
        apply_persona_edit(base, "rule_del", None, None)


@pytest.mark.asyncio
async def test_wizard_no_service_shows_unavailable() -> None:
    msg = AsyncMock()
    msg.text = "cualquier cosa"
    msg.from_user = AsyncMock()
    msg.from_user.id = _OWNER_ID
    msg.answer = AsyncMock()
    bot = _bot()
    await handle_persona_edit_text(msg, bot, _session("rule"), None, _sessions())
    assert bot.edit_message_text.await_count == 1
    assert "no disponible" in str(bot.edit_message_text.call_args.kwargs.get("text", ""))


def test_apply_edit_duplicate_id_rejected_on_add() -> None:
    base = _base_catalog()
    existing = base["persona_facts"][0]["id"]
    with pytest.raises(ValueError, match="ya existe"):
        apply_persona_edit(base, "fact", None, f"{existing} | otro_tema | otro hecho")


def test_apply_edit_invalid_timezone_rejected() -> None:
    base = _base_catalog()
    with pytest.raises(ValueError, match="zona horaria inválida"):
        apply_persona_edit(base, "timezone", None, "America/Mexico_Citt")
    ok = apply_persona_edit(base, "timezone", None, "America/Argentina/Buenos_Aires")
    assert ok["schedule"]["timezone"] == "America/Argentina/Buenos_Aires"


def test_apply_edit_rename_collision_rejected() -> None:
    base = _base_catalog()
    first, second = base["persona_facts"][0], base["persona_facts"][1]
    # rename second to first's id -> collision
    with pytest.raises(ValueError, match="ya existe"):
        apply_persona_edit(
            base, "fact", second["id"],
            f"{first['id']} | otro_tema | otro hecho",
        )
    # rename to its own id (no-op) is allowed
    ok = apply_persona_edit(
        base, "fact", second["id"],
        f"{second['id']} | otro_tema | hecho editado",
    )
    edited = next(f for f in ok["persona_facts"] if f["id"] == second["id"])
    assert edited["hecho"] == "hecho editado"


@pytest.mark.asyncio
async def test_dispatch_section_list_capped_at_40() -> None:
    import copy

    base = copy.deepcopy(_base_catalog())
    base["voz_configurada"]["reglas_estilo"] = [f"regla {i}" for i in range(45)]
    service = _FakePersonaAdmin(base)
    msg = _msg()
    await dispatch_personalidad(msg, parsed=_parsed("rules"), actor_id=_OWNER_ID,
                                persona_admin=service, sessions=_sessions())
    kb = msg.edit_text.call_args.kwargs.get("reply_markup")
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    item_buttons = [d for d in datas if d.startswith(encode_menu_persona("item", "rules|"))]
    assert len(item_buttons) == 40  # capped


@pytest.mark.asyncio
async def test_dispatch_owner_auth_error_shown_to_user() -> None:
    from diana.application.admin_service import OwnerAuthError

    class _ExplodingOwner(_FakePersonaAdmin):
        async def save_persona(self, actor_id, payload):
            raise OwnerAuthError("not owner")

    service = _ExplodingOwner(_base_catalog())
    msg = _msg()
    await dispatch_personalidad(msg, parsed=_parsed("rule_del", "0"), actor_id=1,
                                persona_admin=service, sessions=_sessions())
    assert "Error inesperado" in str(msg.edit_text.call_args.args[0])


@pytest.mark.asyncio
async def test_dispatch_restore_ok_non_uuid_extra() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    msg = _msg()
    await dispatch_personalidad(msg, parsed=_parsed("restore_ok", "not-a-uuid"),
                                actor_id=_OWNER_ID, persona_admin=service,
                                sessions=_sessions())
    assert "Versión inválida" in str(msg.edit_text.call_args.args[0])


def test_item_full_text_all_sections_no_truncation() -> None:
    """Detail renderers show FULL content (rules/facts/patterns/policies/bloques/defaults)."""
    from diana.telegram.handlers.persona_admin import _item_full_text

    import copy

    base = copy.deepcopy(_base_catalog())
    # long texts that would previously be truncated by _section_items
    base["voz_configurada"]["reglas_estilo"] = [
        "Regla de ejemplo MUY larga: nunca usar más de dos oraciones cuando el "
        "cliente está molesto, y siempre ofrecer una alternativa concreta."
    ]
    base["persona_facts"][0]["nota_privada"] = "dato privado que no se repite"
    base["voice_patterns"][0]["uso"] = "Uso MUY largo para verificar que el texto del patrón sale completo en el detalle."
    base["policies"][0]["regla"] = "Política MUY larga: nunca prometer contenido exclusivo sin aprobación previa del negocio."
    base["schedule"]["default_responses"] = [
        "Respuesta libre MUY larga para confirmar que no se recorta en el detalle del elemento."
    ]

    rules = _item_full_text(base, "rules", "0")
    assert base["voz_configurada"]["reglas_estilo"][0] in rules

    facts = _item_full_text(base, "facts", base["persona_facts"][0]["id"])
    assert "dato privado que no se repite" in facts
    assert base["persona_facts"][0]["hecho"] in facts

    patterns = _item_full_text(base, "patterns", base["voice_patterns"][0]["id"])
    assert base["voice_patterns"][0]["uso"] in patterns

    policies = _item_full_text(base, "policies", base["policies"][0]["id"])
    assert base["policies"][0]["regla"] in policies

    bloques = _item_full_text(base, "bloques", "0")
    assert bloques is None or "Actividad" in bloques  # static catalog has bloques

    defaults = _item_full_text(base, "defaults", "0")
    assert base["schedule"]["default_responses"][0] in defaults

    assert _item_full_text(base, "rules", "99") is None
    assert _item_full_text(base, "facts", "no-existe") is None
    assert _item_full_text(base, "rules", "abc") is None


@pytest.mark.asyncio
async def test_edit_wizard_prompt_shows_current_full_value() -> None:
    import copy

    service = _FakePersonaAdmin(copy.deepcopy(_base_catalog()))
    sessions = _sessions()
    msg = _msg()
    long_rule = (
        "Regla MUY larga que debe salir completa en el prompt de edición para "
        "que la dueña pueda verla antes de cambiarla."
    )
    service.current["voz_configurada"]["reglas_estilo"][0] = long_rule

    await dispatch_personalidad(
        msg, parsed=_parsed("rule_edit", "0"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=sessions,
    )
    prompt = str(msg.edit_text.call_args.args[0])
    assert "📄 Actual:" in prompt
    assert long_rule in prompt  # full text, not truncated

    session = sessions.get(_OWNER_ID)
    assert session is not None and session.persona_section == "rule" and session.persona_target == "0"


# ---------------------------------------------------------------------------
# REQ-ATN-06 — channel selector (VIP | Atención)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_selector_renders_both_channels() -> None:
    """The channel toggle row marks the active channel with a checkmark."""
    service = _FakePersonaAdmin(_base_catalog())
    msg = _msg()
    await dispatch_personalidad(
        msg, parsed=_parsed("channel", "vip"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=_sessions(),
    )
    kb = msg.edit_text.call_args.kwargs.get("reply_markup")
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert "👑 VIP ✅" in labels
    assert any(label.startswith("💼 Atención") for label in labels)


@pytest.mark.asyncio
async def test_channel_switch_sets_session() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    sessions = _sessions()
    msg = _msg()
    await dispatch_personalidad(
        msg, parsed=_parsed("channel", "atencion"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=sessions,
    )
    sess = sessions.get(_OWNER_ID)
    assert sess is not None and sess.persona_channel == "atencion"


@pytest.mark.asyncio
async def test_load_current_uses_session_channel() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    sessions = _sessions()
    sessions.start(_OWNER_ID, "persona_edit", persona_channel="atencion")
    msg = _msg()
    await dispatch_personalidad(
        msg, parsed=_parsed("persona"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=sessions,
    )
    assert service.last_channel_type == "atencion"


@pytest.mark.asyncio
async def test_save_persona_passes_channel_type() -> None:
    from diana.cognitive.persona_catalog import get_persona_atencion_catalog

    service = _FakePersonaAdmin()
    service.channel_currents["atencion"] = get_persona_atencion_catalog()
    sessions = _sessions()
    sessions.start(_OWNER_ID, "persona_edit", persona_channel="atencion")
    msg = _msg()
    await dispatch_personalidad(
        msg, parsed=_parsed("rule_del", "0"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=sessions,
    )
    assert service.last_save_channel_type == "atencion"


@pytest.mark.asyncio
async def test_restore_passes_channel_type() -> None:
    from diana.cognitive.persona_catalog import get_persona_atencion_catalog

    service = _FakePersonaAdmin()
    v1 = await service.save_persona(
        _OWNER_ID, get_persona_atencion_catalog(), channel_type="atencion"
    )
    sessions = _sessions()
    sessions.start(_OWNER_ID, "persona_edit", persona_channel="atencion")
    msg = _msg()
    await dispatch_personalidad(
        msg, parsed=_parsed("restore_ok", str(v1.id)), actor_id=_OWNER_ID,
        persona_admin=service, sessions=sessions,
    )
    assert service.last_restore_channel_type == "atencion"
    assert "restaurada" in str(msg.edit_text.call_args.args[0])


@pytest.mark.asyncio
async def test_list_versions_scoped_to_channel() -> None:
    service = _FakePersonaAdmin(_base_catalog())
    sessions = _sessions()
    sessions.start(_OWNER_ID, "persona_edit", persona_channel="atencion")
    msg = _msg()
    await dispatch_personalidad(
        msg, parsed=_parsed("history"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=sessions,
    )
    assert service.last_list_channel_type == "atencion"


def test_default_channel_is_vip() -> None:
    """Fresh / missing sessions resolve to vip (flag-OFF behavior identical)."""
    from diana.telegram.handlers.persona_admin import _current_channel

    assert _current_channel(_sessions(), _OWNER_ID) == "vip"
    assert _current_channel(None, _OWNER_ID) == "vip"
    # a session without persona_channel also resolves to vip
    s = _sessions()
    s.start(_OWNER_ID, "persona_edit", persona_section="rule")
    assert _current_channel(s, _OWNER_ID) == "vip"


def test_menu_persona_channel_back_path_resolves_session_channel() -> None:
    """REQ-ATN-06: the menu router's back re-render resolves the session channel.

    The ``Volver``/``Cancelar`` buttons dispatch to the personalidad root via
    ``build_menu_router``, which calls ``_current_channel`` (imported into menu
    from persona_admin) to re-render the keyboard with the active channel. If it
    regressed to VIP the admin would be silently bounced back after switching to
    atencion.
    """
    from diana.telegram.handlers.persona_admin import _current_channel

    # missing sessions / missing actor → vip
    assert _current_channel(None, _OWNER_ID) == "vip"
    assert _current_channel(_sessions(), None) == "vip"
    # no session for this actor → vip
    assert _current_channel(_sessions(), _OWNER_ID) == "vip"
    # fresh session (dataclass default) → vip
    s = _sessions()
    s.start(_OWNER_ID, "persona_edit", persona_section="rule")
    assert _current_channel(s, _OWNER_ID) == "vip"
    # switched channel survives the wizard / back navigation
    s.start(_OWNER_ID, "persona_edit", persona_section="rule",
            persona_channel="atencion")
    assert _current_channel(s, _OWNER_ID) == "atencion"


@pytest.mark.asyncio
async def test_atencion_round_trip() -> None:
    """REQ-ATN-06: load → edit → save → list → restore for the atencion channel."""
    from diana.cognitive.persona_catalog import get_persona_atencion_catalog

    service = _FakePersonaAdmin()
    sessions = _sessions()

    # 1) switch to atencion → session carries the channel
    await dispatch_personalidad(
        _msg(), parsed=_parsed("channel", "atencion"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=sessions,
    )
    assert sessions.get(_OWNER_ID).persona_channel == "atencion"

    # 2) load current atencion (static seed fallback since no DB row yet)
    msg2 = _msg()
    await dispatch_personalidad(
        msg2, parsed=_parsed("persona"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=sessions,
    )
    assert service.last_channel_type == "atencion"
    assert "Diana" in str(msg2.edit_text.call_args.args[0])

    # 3) edit a rule via the wizard on atencion
    sessions.start(
        _OWNER_ID, "persona_edit",
        persona_section="rule", persona_channel="atencion",
    )
    wmsg = AsyncMock()
    wmsg.text = "Nueva regla de atención"
    wmsg.from_user = AsyncMock()
    wmsg.from_user.id = _OWNER_ID
    wmsg.answer = AsyncMock()
    wmsg.message_id = 5
    wmsg.chat = AsyncMock()
    wmsg.chat.id = 42
    await handle_persona_edit_text(
        wmsg, _bot(), sessions.get(_OWNER_ID), service, sessions
    )
    assert service.last_save_channel_type == "atencion"
    assert service.channel_currents["atencion"]["voz_configurada"][
        "reglas_estilo"
    ][-1] == "Nueva regla de atención"

    # 4) history lists versions scoped to atencion
    msg4 = _msg()
    await dispatch_personalidad(
        msg4, parsed=_parsed("history"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=sessions,
    )
    assert service.last_list_channel_type == "atencion"

    # 5) restore the saved version on atencion
    saved_id = service.records[-1].id
    msg5 = _msg()
    await dispatch_personalidad(
        msg5, parsed=_parsed("restore_ok", str(saved_id)), actor_id=_OWNER_ID,
        persona_admin=service, sessions=sessions,
    )
    assert service.last_restore_channel_type == "atencion"
    assert "Nueva regla de atención" in service.channel_currents["atencion"][
        "voz_configurada"
    ]["reglas_estilo"]


@pytest.mark.asyncio
async def test_channel_switch_persists_across_wizard_start() -> None:
    """The channel survives a wizard restart (carried into the new session)."""
    service = _FakePersonaAdmin(_base_catalog())
    sessions = _sessions()
    await dispatch_personalidad(
        _msg(), parsed=_parsed("channel", "atencion"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=sessions,
    )
    msg = _msg()
    await dispatch_personalidad(
        msg, parsed=_parsed("rule_add"), actor_id=_OWNER_ID,
        persona_admin=service, sessions=sessions,
    )
    sess = sessions.get(_OWNER_ID)
    assert sess is not None and sess.persona_channel == "atencion"
    assert sess.persona_section == "rule"
