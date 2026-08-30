"""Owner admin for the persona catalog (Item 3) — menu category 'personalidad'.

This module is consumed by the menu router (``handlers/menu.py``): it implements
the ``m:personalidad:*`` dispatch branch, the section views, the item
detail/edit/delete flows, and the text wizards that capture the new values.
Every mutation rebuilds the FULL catalog (deep-copied slices, never mutating
the shared static catalog) and calls ``PersonaAdminService.save_persona`` —
which validates, versions, activates, and hot-applies (provider invalidation).

Standalone by design (no import of ``handlers/menu.py``) to avoid a module
cycle; it duck-types the session store and session objects.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any
from uuid import UUID

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from diana.application.persona_admin_service import PersonaAdminService
from diana.cognitive.persona_catalog import (
    get_persona_atencion_catalog,
    get_persona_catalog,
)
from diana.telegram.keyboards import (
    MENU_CATEGORY_TEXT,
    encode_menu,
    encode_menu_persona,
    menu_back_keyboard,
    menu_persona_confirm_restore_keyboard,
    menu_persona_list_keyboard,
    menu_personalidad_keyboard,
)

logger = logging.getLogger("diana.telegram")

_PERSONA_BACK = encode_menu("personalidad")

# Item sections → (prompt hint when a wizard captures text).
_ADD_PROMPTS: dict[str, str] = {
    "persona": (
        "📝 Envíame la nueva descripción de Diana (cómo habla, quién es).\n\n"
        "Usa /cancelar para abortar."
    ),
    "rule": (
        "✍️ Envíame la regla de tono/estilo nueva.\n\n"
        "Ej: \"Máximo 2-3 líneas por mensaje\".\nUsa /cancelar para abortar."
    ),
    "rule_edit": (
        "✍️ Envíame el texto nuevo de la regla.\n\nUsa /cancelar para abortar."
    ),
    "fact": (
        "👤 Envíame el dato nuevo con este formato:\n"
        "id | tema1, tema2 | hecho\n"
        "Ej: estudios | psicologia, trayectoria | Termino la carrera de psicología.\n"
        "Usa /cancelar para abortar."
    ),
    "fact_edit": (
        "👤 Envíame el dato con este formato (puedes cambiar id, temas o hecho):\n"
        "id | tema1, tema2 | hecho\nUsa /cancelar para abortar."
    ),
    "pattern": (
        "🗣️ Envíame el patrón de voz con este formato:\n"
        "id | tag1, tag2 | patron | uso\n"
        "Ej: conector_o_sea | conector, explicacion | o sea | Conector natural.\n"
        "Usa /cancelar para abortar."
    ),
    "pattern_edit": (
        "🗣️ Envíame el patrón con este formato:\n"
        "id | tag1, tag2 | patron | uso\nUsa /cancelar para abortar."
    ),
    "policy": (
        "📜 Envíame la política con este formato:\n"
        "id | tema1, tema2 | regla\n"
        "Ej: no_consultas | psicologia | No doy consultas clínicas.\n"
        "Usa /cancelar para abortar."
    ),
    "policy_edit": (
        "📜 Envíame la política con este formato:\n"
        "id | tema1, tema2 | regla\nUsa /cancelar para abortar."
    ),
    "bloque": (
        "🗓️ Envíame el bloque de agenda con este formato:\n"
        "dias1, dias2 | inicio | fin | actividad\n"
        "Ej: lunes, martes | 09:00 | 12:00 | en el servicio social\n"
        "Usa /cancelar para abortar."
    ),
    "bloque_edit": (
        "🗓️ Envíame el bloque con este formato:\n"
        "dias1, dias2 | inicio | fin | actividad\nUsa /cancelar para abortar."
    ),
    "default": (
        "🗓️ Envíame la respuesta libre nueva (para cuando no hay actividad).\n"
        "Usa /cancelar para abortar."
    ),
    "default_edit": (
        "🗓️ Envíame el texto nuevo de la respuesta libre.\nUsa /cancelar para abortar."
    ),
    "timezone": (
        "🗓️ Envíame la zona horaria nueva (ej: America/Mexico_City).\n"
        "Usa /cancelar para abortar."
    ),
}

# Sections whose items have ids (fact/pattern/policy) vs indexed (rule/bloque/default).


def _section_op(section: str) -> str | None:
    """Map a plural list section to its singular op name (rules→rule, facts→fact…)."""
    return {
        "rules": "rule",
        "facts": "fact",
        "patterns": "pattern",
        "policies": "policy",
        "bloques": "bloque",
        "defaults": "default",
    }.get(section)


# ---------------------------------------------------------------------------
# Small UI helpers (mirror menu.py's _show/_edit_or_answer without importing it)
# ---------------------------------------------------------------------------


async def _show(message: Message, text: str, keyboard: Any) -> None:
    try:
        await message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await message.answer(text, reply_markup=keyboard)


async def _edit_or_answer(
    bot: Bot,
    text: str,
    *,
    session: Any | None = None,
    fallback: Message | None = None,
    keyboard: Any = None,
) -> None:
    if session and session.last_chat_id and session.last_bot_message_id:
        try:
            await bot.edit_message_text(
                chat_id=session.last_chat_id,
                message_id=session.last_bot_message_id,
                text=text,
                reply_markup=keyboard,
            )
            return
        except Exception:
            pass
    if fallback is not None:
        await fallback.answer(text, reply_markup=keyboard)


def _truncate(text: str, limit: int = 2800) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _split_topics(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


# ---------------------------------------------------------------------------
# Catalog access + pure edit application
# ---------------------------------------------------------------------------


def _current_channel(sessions: Any, actor_id: int | None) -> str:
    """Active persona channel from the session (default ``"vip"``).

    REQ-ATN-06: the personalidad panel shows whichever channel was last
    selected; a fresh session (or no session) resolves to VIP, preserving
    flag-OFF behavior.
    """
    if sessions is None or actor_id is None:
        return "vip"
    try:
        sess = sessions.get(actor_id)
        if sess is None:
            return "vip"
        return getattr(sess, "persona_channel", "vip") or "vip"
    except Exception:
        return "vip"


async def load_current(
    persona_admin: PersonaAdminService, channel_type: str = "vip"
) -> dict[str, Any]:
    """Active DB catalog when flag on + active version; else the channel's
    static catalog (atencion → ``persona_atencion.json``, VIP → ``persona_diana.json``)."""
    catalog = await persona_admin.get_current_persona(channel_type=channel_type)
    if catalog is not None:
        return catalog
    if channel_type == "atencion":
        try:
            return get_persona_atencion_catalog()
        except Exception:
            # Missing/corrupt persona_atencion.json → VIP static (never crash a callback).
            return get_persona_catalog()
    return get_persona_catalog()


def _replace_item(
    items: list[Any],
    extra: str | None,
    new_item: dict[str, Any],
    *,
    by_id: bool,
) -> list[Any]:
    """Replace an item by id (or index) or append when extra is None."""
    if extra is None:
        return [*items, new_item]
    if by_id:
        if not any(str(item.get("id")) == extra for item in items):
            raise ValueError("no se encontró el elemento")
        return [
            item if str(item.get("id")) != extra else new_item
            for item in items
        ]
    idx = int(extra)
    if not (0 <= idx < len(items)):
        raise ValueError("elemento inválido")
    out = list(items)
    out[idx] = new_item
    return out


def _delete_item(
    items: list[Any],
    extra: str,
    *,
    by_id: bool,
) -> list[Any]:
    if len(items) <= 1:
        raise ValueError("no se puede borrar el último elemento de una lista")
    if by_id:
        if not any(str(item.get("id")) == extra for item in items):
            raise ValueError("no se encontró el elemento")
        return [item for item in items if str(item.get("id")) != extra]
    idx = int(extra)
    if not (0 <= idx < len(items)):
        raise ValueError("elemento inválido")
    return [item for i, item in enumerate(items) if i != idx]


def apply_persona_edit(
    base: dict[str, Any],
    op: str,
    extra: str | None,
    text: str | None,
) -> dict[str, Any]:
    """Return a NEW full catalog dict with the edit applied (base is not mutated).

    ``op`` is the section operation: persona | rule | rule_del | fact | fact_del |
    pattern | pattern_del | policy | policy_del | bloque | bloque_del |
    default | default_del | timezone.
    """
    nuevo = dict(base)

    if op == "persona":
        voz = deepcopy(nuevo.get("voz_configurada") or {})
        persona = (text or "").strip()
        if not persona:
            raise ValueError("la descripción no puede estar vacía")
        voz["persona"] = persona
        nuevo["voz_configurada"] = voz
        return nuevo

    if op in ("rule", "rule_del"):
        voz = deepcopy(nuevo.get("voz_configurada") or {})
        rules = list(voz.get("reglas_estilo") or [])
        if op == "rule":
            new_text = (text or "").strip()
            if not new_text:
                raise ValueError("la regla no puede estar vacía")
            voz["reglas_estilo"] = _replace_item(rules, extra, new_text, by_id=False)
        else:
            if extra is None:
                raise ValueError("elemento inválido")
            voz["reglas_estilo"] = _delete_item(rules, extra, by_id=False)
        nuevo["voz_configurada"] = voz
        return nuevo

    if op == "timezone":
        from zoneinfo import ZoneInfo

        schedule = deepcopy(nuevo.get("schedule") or {})
        tz = (text or "").strip()
        if not tz:
            raise ValueError("la zona horaria no puede estar vacía")
        try:
            ZoneInfo(tz)
        except Exception as exc:
            raise ValueError(f"zona horaria inválida: {tz!r}") from exc
        schedule["timezone"] = tz
        nuevo["schedule"] = schedule
        return nuevo

    if op in ("default", "default_del"):
        schedule = deepcopy(nuevo.get("schedule") or {})
        defaults = list(schedule.get("default_responses") or [])
        if op == "default":
            new_text = (text or "").strip()
            if not new_text:
                raise ValueError("la respuesta no puede estar vacía")
            schedule["default_responses"] = _replace_item(
                defaults, extra, new_text, by_id=False
            )
        else:
            if extra is None:
                raise ValueError("elemento inválido")
            schedule["default_responses"] = _delete_item(
                defaults, extra, by_id=False
            )
        nuevo["schedule"] = schedule
        return nuevo

    if op == "bloque":
        schedule = deepcopy(nuevo.get("schedule") or {})
        bloques = list(schedule.get("bloques") or [])
        parts = [p.strip() for p in (text or "").split("|")]
        if len(parts) < 4:
            raise ValueError("formato: dias1, dias2 | inicio | fin | actividad")
        dias, inicio, fin, actividad = parts[:4]
        if not dias or not inicio or not fin or not actividad:
            raise ValueError("ningún campo puede estar vacío")
        schedule["bloques"] = _replace_item(
            bloques,
            extra,
            {"dias": _split_topics(dias), "inicio": inicio, "fin": fin, "actividad": actividad},
            by_id=False,
        )
        nuevo["schedule"] = schedule
        return nuevo

    if op == "bloque_del":
        schedule = deepcopy(nuevo.get("schedule") or {})
        bloques = list(schedule.get("bloques") or [])
        if len(bloques) <= 1:
            raise ValueError("no se puede borrar el último bloque de agenda")
        if extra is None:
            raise ValueError("elemento inválido")
        schedule["bloques"] = _delete_item(bloques, extra, by_id=False)
        nuevo["schedule"] = schedule
        return nuevo

    if op in ("fact", "fact_del"):
        key = "persona_facts"
        nuevo[key] = _apply_typed_item(
            nuevo.get(key) or [], op, extra, text,
            parser=_parse_fact, by_id=True,
        )
        return nuevo

    if op in ("pattern", "pattern_del"):
        key = "voice_patterns"
        nuevo[key] = _apply_typed_item(
            nuevo.get(key) or [], op, extra, text,
            parser=_parse_pattern, by_id=True,
        )
        return nuevo

    if op in ("policy", "policy_del"):
        key = "policies"
        nuevo[key] = _apply_typed_item(
            nuevo.get(key) or [], op, extra, text,
            parser=_parse_policy, by_id=True,
        )
        return nuevo

    raise ValueError(f"operación de personalidad desconocida: {op}")


def _apply_typed_item(
    items: list[Any],
    op: str,
    extra: str | None,
    text: str | None,
    *,
    parser: Any,
    by_id: bool,
) -> list[Any]:
    if op.endswith("_del"):
        return _delete_item(items, extra or "", by_id=by_id)
    new_item = parser(text)
    new_id = str(new_item.get("id"))
    if any(str(item.get("id")) == new_id for item in items):
        # Add with an existing id, or a rename (extra != None) colliding with
        # another item — both would create duplicate ids.
        if extra is None or str(extra) != new_id:
            raise ValueError("ya existe un elemento con ese id")
    return _replace_item(items, extra, new_item, by_id=by_id)


def _parse_fact(text: str | None) -> dict[str, Any]:
    parts = [p.strip() for p in (text or "").split("|")]
    if len(parts) < 3:
        raise ValueError("formato: id | tema1, tema2 | hecho")
    fact_id, temas, hecho = parts[:3]
    if not fact_id or not temas or not hecho:
        raise ValueError("id, temas y hecho no pueden estar vacíos")
    if len(fact_id.encode("utf-8")) > 24:
        raise ValueError("el id es demasiado largo (máximo 24 bytes)")
    item: dict[str, Any] = {"id": fact_id, "tema": _split_topics(temas), "hecho": hecho}
    if len(parts) > 3 and parts[3].strip():
        item["nota_privada"] = parts[3].strip()
    return item


def _parse_pattern(text: str | None) -> dict[str, Any]:
    parts = [p.strip() for p in (text or "").split("|")]
    if len(parts) < 4:
        raise ValueError("formato: id | tag1, tag2 | patron | uso")
    pattern_id, tags, patron, uso = parts[:4]
    if not pattern_id or not tags or not patron or not uso:
        raise ValueError("ningún campo puede estar vacío")
    if len(pattern_id.encode("utf-8")) > 24:
        raise ValueError("el id es demasiado largo (máximo 24 bytes)")
    return {"id": pattern_id, "tags": _split_topics(tags), "patron": patron, "uso": uso}


def _parse_policy(text: str | None) -> dict[str, Any]:
    parts = [p.strip() for p in (text or "").split("|")]
    if len(parts) < 3:
        raise ValueError("formato: id | tema1, tema2 | regla")
    policy_id, temas, regla = parts[:3]
    if not policy_id or not temas or not regla:
        raise ValueError("id, temas y regla no pueden estar vacíos")
    if len(policy_id.encode("utf-8")) > 24:
        raise ValueError("el id es demasiado largo (máximo 24 bytes)")
    return {"id": policy_id, "tema": _split_topics(temas), "regla": regla}


# ---------------------------------------------------------------------------
# Section renderers → (extra, label) item lists
# ---------------------------------------------------------------------------


def _section_items(catalog: dict[str, Any], section: str) -> list[tuple[str, str]]:
    voz = catalog.get("voz_configurada") or {}
    if section == "rules":
        rules = voz.get("reglas_estilo") or []
        return [(str(i), f"✍️ {_truncate(r, 70)}") for i, r in enumerate(rules)]
    if section == "facts":
        facts = catalog.get("persona_facts") or []
        return [
            (str(f.get("id")), f"👤 {f.get('id')} — {_truncate(f.get('hecho', ''), 70)}")
            for f in facts
        ]
    if section == "patterns":
        patterns = catalog.get("voice_patterns") or []
        return [
            (str(p.get("id")), f"🗣️ {p.get('patron')} — {_truncate(p.get('uso', ''), 60)}")
            for p in patterns
        ]
    if section == "policies":
        policies = catalog.get("policies") or []
        return [
            (str(p.get("id")), f"📜 {p.get('id')} — {_truncate(p.get('regla', ''), 60)}")
            for p in policies
        ]
    if section == "bloques":
        bloques = (catalog.get("schedule") or {}).get("bloques") or []
        out: list[tuple[str, str]] = []
        for i, b in enumerate(bloques):
            dias = ", ".join(b.get("dias") or [])
            out.append(
                (
                    str(i),
                    f"🗓️ {dias} {b.get('inicio')}-{b.get('fin')}: {_truncate(b.get('actividad', ''), 50)}",
                )
            )
        return out
    if section == "defaults":
        defaults = (catalog.get("schedule") or {}).get("default_responses") or []
        return [(str(i), f"💬 {_truncate(d, 70)}") for i, d in enumerate(defaults)]
    return []


def _item_full_text(catalog: dict[str, Any], section: str, key: str) -> str | None:
    """Render the FULL content of one item (no truncation) for detail/edit views.

    Returns None when the item does not exist.
    """
    voz = catalog.get("voz_configurada") or {}

    if section == "rules":
        rules = voz.get("reglas_estilo") or []
        try:
            idx = int(key)
        except (TypeError, ValueError):
            return None
        if not (0 <= idx < len(rules)):
            return None
        return f"✍️ Regla #{idx + 1}\n\n{rules[idx]}"

    if section == "facts":
        for f in catalog.get("persona_facts") or []:
            if str(f.get("id")) == key:
                temas = ", ".join(f.get("tema") or [])
                lines = [
                    f"👤 {f.get('id')}",
                    f"Temas: {temas}",
                    f"Hecho: {f.get('hecho')}",
                ]
                if f.get("nota_privada"):
                    lines.append(f"Nota privada: {f.get('nota_privada')}")
                return "\n".join(lines)
        return None

    if section == "patterns":
        for p in catalog.get("voice_patterns") or []:
            if str(p.get("id")) == key:
                tags = ", ".join(p.get("tags") or [])
                return (
                    f"🗣️ {p.get('patron')}\n"
                    f"id: {p.get('id')}\n"
                    f"tags: {tags}\n"
                    f"uso: {p.get('uso')}"
                )
        return None

    if section == "policies":
        for p in catalog.get("policies") or []:
            if str(p.get("id")) == key:
                temas = ", ".join(p.get("tema") or [])
                return f"📜 {p.get('id')}\nTemas: {temas}\nRegla: {p.get('regla')}"
        return None

    if section == "bloques":
        bloques = (catalog.get("schedule") or {}).get("bloques") or []
        try:
            idx = int(key)
        except (TypeError, ValueError):
            return None
        if not (0 <= idx < len(bloques)):
            return None
        b = bloques[idx]
        dias = ", ".join(b.get("dias") or [])
        return (
            f"🗓️ Bloque #{idx + 1}\n"
            f"Días: {dias}\n"
            f"Horario: {b.get('inicio')}–{b.get('fin')}\n"
            f"Actividad: {b.get('actividad')}"
        )

    if section == "defaults":
        defaults = (catalog.get("schedule") or {}).get("default_responses") or []
        try:
            idx = int(key)
        except (TypeError, ValueError):
            return None
        if not (0 <= idx < len(defaults)):
            return None
        return f"💬 Respuesta libre #{idx + 1}\n\n{defaults[idx]}"

    return None


def _edit_current_value(
    catalog: dict[str, Any], section: str, extra: str | None
) -> str | None:
    """Current value to show inside an edit prompt (full text; None = new item)."""
    voz = catalog.get("voz_configurada") or {}
    if section == "persona":
        return _truncate(str(voz.get("persona") or ""), 3500)  # message-size safety only
    if section == "timezone":
        return str((catalog.get("schedule") or {}).get("timezone") or "")
    if section in ("rule", "fact", "pattern", "policy", "bloque", "default"):
        # _item_full_text keys on the PLURAL list-section name (rules/facts/…)
        return _item_full_text(catalog, _section_list_action(section), extra or "")
    return None


def _item_detail(catalog: dict[str, Any], section: str, extra: str) -> str:
    """Full-content detail view for a tapped item (review round fix: no truncation)."""
    full = _item_full_text(catalog, section, extra)
    return full if full is not None else "(no se encontró el elemento)"


# ---------------------------------------------------------------------------
# Dispatch — m:personalidad:* actions
# ---------------------------------------------------------------------------


async def dispatch_personalidad(
    message: Message,
    *,
    parsed: Any,
    actor_id: int,
    persona_admin: PersonaAdminService | None,
    sessions: Any,
) -> None:
    back = menu_back_keyboard(_PERSONA_BACK)
    if persona_admin is None:
        await _show(message, "Personalidad y reglas no disponible.", back)
        return

    action = parsed.action or ""
    extra = parsed.extra
    channel = _current_channel(sessions, actor_id)

    if action == "channel" and extra in ("vip", "atencion"):
        # REQ-ATN-06: switch the persona channel and re-render the panel root.
        if sessions is not None:
            sess = sessions.get(actor_id)
            if sess is not None:
                sess.persona_channel = extra
            else:
                sessions.start(actor_id, "persona_edit", persona_channel=extra)
        logger.info(
            "persona_channel_switched",
            extra={"actor_id": actor_id, "channel_type": extra},
        )
        await _show(
            message,
            MENU_CATEGORY_TEXT["personalidad"],
            menu_personalidad_keyboard(active_channel=extra),
        )
        return

    if action == "persona":
        catalog = await load_current(persona_admin, channel_type=channel)
        persona = _truncate(
            (catalog.get("voz_configurada") or {}).get("persona", ""),
            3900,  # Telegram message-size safety only; not a display truncation
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ Editar",
                        callback_data=encode_menu_persona("persona_edit"),
                    )
                ],
                [InlineKeyboardButton(text="🔙 Volver", callback_data=_PERSONA_BACK)],
            ]
        )
        await _show(message, f"📝 Cómo habla Diana\n\n{persona}", kb)
        return

    if action == "schedule":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🗓️ Bloques de agenda", callback_data=encode_menu_persona("bloques"))],
                [InlineKeyboardButton(text="💬 Respuestas libres", callback_data=encode_menu_persona("defaults"))],
                [InlineKeyboardButton(text="🕐 Zona horaria", callback_data=encode_menu_persona("timezone"))],
                [InlineKeyboardButton(text="🔙 Volver", callback_data=_PERSONA_BACK)],
            ]
        )
        await _show(message, "🗓️ Agenda", kb)
        return

    if action == "timezone":
        catalog = await load_current(persona_admin, channel_type=channel)
        tz = (catalog.get("schedule") or {}).get("timezone", "")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ Editar",
                        callback_data=encode_menu_persona("timezone_edit"),
                    )
                ],
                [InlineKeyboardButton(text="🔙 Volver", callback_data=encode_menu_persona("schedule"))],
            ]
        )
        await _show(message, f"🕐 Zona horaria\n\n{tz}", kb)
        return

    if action == "history":
        try:
            versions = await persona_admin.list_versions(
                actor_id, channel_type=channel
            )
        except Exception as exc:
            logger.warning(
                "persona_history_failed",
                extra={"actor_id": actor_id, "error": type(exc).__name__},
                exc_info=True,
            )
            await _show(message, "No se pudo leer el historial.", back)
            return
        if not versions:
            await _show(message, "Todavía no hay versiones guardadas.", back)
            return
        lines = []
        items: list[tuple[str, str]] = []
        for v in versions[:30]:
            fecha = v.created_at.strftime("%d/%m %H:%M")
            marker = " · ✅ activa" if v.is_active else ""
            lines.append(f"v{v.version} · {fecha} · {v.source}{marker}")
            items.append((str(v.id), f"v{v.version} · {fecha} · {v.source}{marker}"))
        header = "🕘 Historial de versiones\n\n" + "\n".join(lines[:5]) + (
            "\n…" if len(lines) > 5 else ""
        )
        await _show(
            message,
            header + "\n\nToca una versión para restaurarla.",
            menu_persona_list_keyboard(items, add_action=None, item_action="restore"),
        )
        return

    if action == "restore":
        if not extra:
            await _show(message, "Versión inválida.", back)
            return
        await _show(
            message,
            "¿Restaurar esta versión? La versión actual quedará en el historial "
            "y podrás volver a ella.",
            menu_persona_confirm_restore_keyboard(extra),
        )
        return

    if action == "restore_ok":
        if not extra:
            await _show(message, "Versión inválida.", back)
            return
        try:
            version_uuid = UUID(extra)
        except ValueError:
            await _show(message, "Versión inválida.", back)
            return
        try:
            restored = await persona_admin.restore(
                actor_id, version_uuid, channel_type=channel
            )
        except Exception as exc:
            logger.warning(
                "persona_restore_failed",
                extra={"actor_id": actor_id, "error": type(exc).__name__},
                exc_info=True,
            )
            await _show(message, "No se pudo restaurar la versión.", back)
            return
        if restored is None:
            await _show(message, "No se encontró esa versión.", back)
            return
        await _show(
            message,
            f"✅ Versión v{restored.version} restaurada y activa.",
            back,
        )
        return

    # ---- item lists (rules, facts, patterns, policies, bloques, defaults) ----
    if action in ("rules", "facts", "patterns", "policies", "bloques", "defaults"):
        section = {
            "rules": "rules", "facts": "facts", "patterns": "patterns",
            "policies": "policies", "bloques": "bloques", "defaults": "defaults",
        }[action]
        catalog = await load_current(persona_admin, channel_type=channel)
        raw_items = _section_items(catalog, section)
        # Item callbacks carry section|key so the detail view knows the context.
        # Cap at 40 rows: Telegram inline keyboards allow at most 100 buttons
        # and the add/back rows consume 2 — a huge section must stay renderable.
        raw_items = raw_items[:40]
        items = [(f"{section}|{key}", label) for key, label in raw_items]
        add_action = {
            "rules": "rule_add", "facts": "fact_add", "patterns": "pattern_add",
            "policies": "policy_add", "bloques": "bloque_add", "defaults": "default_add",
        }[action]
        if not items:
            await _show(
                message,
                f"La sección está vacía. Toca «Agregar» para crear el primer elemento.",
                menu_persona_list_keyboard([], add_action),
            )
            return
        titles = {
            "rules": "✍️ Reglas de tono y estilo",
            "facts": "👤 Datos personales",
            "patterns": "🗣️ Patrones de voz",
            "policies": "📜 Políticas de conducta",
            "bloques": "🗓️ Bloques de agenda",
            "defaults": "💬 Respuestas libres",
        }
        try:
            keyboard = menu_persona_list_keyboard(items, add_action)
        except ValueError:
            await _show(
                message,
                "No se pudo mostrar la lista (algún elemento excede el límite de "
                "tamaño). Edítalo o elimínalo con otra herramienta.",
                back,
            )
            return
        await _show(
            message,
            titles[action] + "\n\nToca un elemento para verlo.",
            keyboard,
        )
        return

    if action == "item":
        if not extra or "|" not in extra:
            await _show(message, "Elemento inválido.", back)
            return
        section, item_key = extra.split("|", 1)
        op = _section_op(section)  # plural list section → singular op (rules→rule…)
        if op is None:
            await _show(message, "Elemento inválido.", back)
            return
        catalog = await load_current(persona_admin, channel_type=channel)
        detail = _item_detail(catalog, section, item_key)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✏️ Editar", callback_data=encode_menu_persona(f"{op}_edit", item_key)),
                    InlineKeyboardButton(text="🗑️ Eliminar", callback_data=encode_menu_persona(f"{op}_del", item_key)),
                ],
                [InlineKeyboardButton(text="🔙 Volver", callback_data=encode_menu_persona(_section_list_action(op)))],
            ]
        )
        await _show(message, detail, kb)
        return

    # ---- immediate deletes ----
    if action in ("rule_del", "fact_del", "pattern_del", "policy_del", "bloque_del", "default_del"):
        section = action[: -len("_del")]
        catalog = await load_current(persona_admin, channel_type=channel)
        try:
            nuevo = apply_persona_edit(catalog, action, extra, None)
        except ValueError as exc:
            await _show(message, f"❌ No se pudo eliminar: {exc}", back)
            return
        try:
            record = await persona_admin.save_persona(
                actor_id, nuevo, channel_type=channel
            )
        except ValueError as exc:
            await _show(message, f"❌ No se guardó: {exc}", back)
            return
        except Exception as exc:
            logger.warning(
                "persona_save_failed",
                extra={"actor_id": actor_id, "error": type(exc).__name__},
                exc_info=True,
            )
            await _show(message, "❌ Error inesperado al guardar.", back)
            return
        await _show(
            message,
            f"✅ Eliminado y guardado como versión v{record.version}.",
            menu_back_keyboard(encode_menu_persona(_section_list_action(section))),
        )
        return

    # ---- wizard starts (add / edit) ----
    if action in ("persona_edit", "rule_add", "rule_edit", "fact_add", "fact_edit",
                  "pattern_add", "pattern_edit", "policy_add", "policy_edit",
                  "bloque_add", "bloque_edit", "default_add", "default_edit",
                  "timezone_edit"):
        section = _wizard_section(action, extra)
        sessions.start(
            actor_id,
            "persona_edit",
            persona_section=section,
            persona_target=extra,
            persona_channel=channel,
            last_bot_message_id=message.message_id,
            last_chat_id=message.chat.id,
        )
        prompt = _ADD_PROMPTS.get(action) or _ADD_PROMPTS.get(
            section, "Envíame el valor nuevo."
        )
        # For EDIT actions, show the CURRENT full value so the owner can
        # review it before fine-tuning (product requirement: no truncation).
        if action.endswith("_edit") or action == "persona_edit" or action == "timezone_edit":
            catalog = await load_current(persona_admin, channel_type=channel)
            current = _edit_current_value(catalog, section, extra)
            if current is not None:
                prompt = f"{prompt}\n\n📄 Actual:\n{current}"
        await _show(message, prompt, None)
        return

    await _show(message, "Esa opción de personalidad no está disponible.", back)


def _section_list_action(op: str) -> str:
    """Map a SINGULAR op name to its plural section-list action (rule→rules…)."""
    return {
        "rule": "rules",
        "fact": "facts",
        "pattern": "patterns",
        "policy": "policies",
        "bloque": "bloques",
        "default": "defaults",
    }.get(op, "personalidad")


def _wizard_section(action: str, extra: str | None) -> str:
    """Map a wizard-start action to its session section id."""
    if action == "persona_edit":
        return "persona"
    if action == "timezone_edit":
        return "timezone"
    if action.endswith("_add"):
        return action[: -len("_add")]
    if action.endswith("_edit"):
        return action[: -len("_edit")]  # rule_edit → rule, fact_edit → fact, ...
    return action


# ---------------------------------------------------------------------------
# Wizard text handling (session kind "persona_edit")
# ---------------------------------------------------------------------------


async def handle_persona_edit_text(
    message: Message,
    bot: Bot,
    session: Any,
    persona_admin: PersonaAdminService | None,
    sessions: Any,
) -> None:
    back = menu_back_keyboard(_PERSONA_BACK)
    if persona_admin is None:
        await _edit_or_answer(
            bot, "Personalidad y reglas no disponible.",
            session=session, fallback=message, keyboard=back,
        )
        return
    section = session.persona_section or ""
    extra = session.persona_target
    channel = getattr(session, "persona_channel", "vip") or "vip"
    text = (message.text or "").strip()

    # The session section is the base op name (persona | rule | fact | pattern |
    # policy | bloque | default | timezone); extra == None means "append new",
    # extra == key/index means "replace that item".
    if section not in (
        "persona", "rule", "fact", "pattern", "policy", "bloque", "default", "timezone",
    ):
        # REQ-ATN-06: a bare persona_edit session can exist without a section
        # (e.g. right after a channel toggle). Typed free text has no target op,
        # so re-show the panel root for the active channel instead of a dead-end
        # invalid-op error on the next message.
        # Re-persist the session with the channel: on_menu_session_text pops it
        # before this handler runs, so without the re-start the next tap would
        # resolve the channel via _current_channel → None → "vip" (mismatch).
        sessions.start(message.from_user.id, "persona_edit", persona_channel=channel)
        await _edit_or_answer(
            bot,
            MENU_CATEGORY_TEXT["personalidad"],
            session=session, fallback=message,
            keyboard=menu_personalidad_keyboard(active_channel=channel),
        )
        return
    op = section

    base = await load_current(persona_admin, channel_type=channel)
    try:
        nuevo = apply_persona_edit(base, op, extra, text)
    except ValueError as exc:
        await _restart_persona_wizard(sessions, message, section, extra, channel)
        await _edit_or_answer(
            bot, f"❌ {exc}\n\nEnvíame el texto corregido o usa /cancelar.",
            session=session, fallback=message, keyboard=None,
        )
        return
    try:
        record = await persona_admin.save_persona(
            actor_id=message.from_user.id,
            payload=nuevo,
            channel_type=channel,
        )
    except Exception as exc:
        logger.warning(
            "persona_save_failed",
            extra={"actor_id": message.from_user.id, "error": type(exc).__name__},
            exc_info=True,
        )
        await _restart_persona_wizard(sessions, message, section, extra, channel)
        await _edit_or_answer(
            bot, "❌ No se pudo guardar. Reenviame el texto o usa /cancelar.",
            session=session, fallback=message, keyboard=None,
        )
        return
    await _edit_or_answer(
        bot,
        f"✅ Guardado como versión v{record.version}. Los cambios ya están activos.",
        session=session, fallback=message, keyboard=back,
    )


async def _restart_persona_wizard(
    sessions: Any,
    message: Message,
    section: str,
    extra: str | None,
    channel: str = "vip",
) -> None:
    """Keep the wizard alive after an error so the owner can retry the text."""
    sessions.start(
        message.from_user.id,
        "persona_edit",
        persona_section=section,
        persona_target=extra,
        persona_channel=channel,
        last_bot_message_id=message.message_id,
        last_chat_id=message.chat.id,
    )


__all__ = [
    "apply_persona_edit",
    "dispatch_personalidad",
    "handle_persona_edit_text",
    "load_current",
]
