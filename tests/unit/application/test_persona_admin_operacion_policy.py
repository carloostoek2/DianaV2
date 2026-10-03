"""PersonaAdminService.save_persona + política de alias de Operación (ítem 2, G2).

La política estricta (B3/B5) se aplica solo a los alias NUEVOS respecto de la
versión activa DEL MISMO canal: un alias legacy que ya no cumple la regla no
bloquea guardar otra sección (se ignora al leer y el panel lo avisa).
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from diana.application.persona_admin_service import PersonaAdminService
from diana.cognitive.persona_catalog import get_persona_atencion_catalog, get_persona_catalog

OWNER = 1


class _Store:
    """Channel-aware in-memory PersonaAdminStore that counts get_active calls."""

    def __init__(self) -> None:
        self.rows: list[Any] = []
        self.get_active_calls: list[str] = []

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
        self.get_active_calls.append(channel_type)
        return next((r for r in self.rows if r.is_active and r.channel_type == channel_type), None)

    async def seed_legacy(self, payload: dict, channel_type: str) -> None:
        """Active version stored under an older, looser alias policy (no validation)."""
        rec = await self.insert_version(version=len(self.rows) + 1, source="db", payload=payload,
                                        created_by=OWNER, channel_type=channel_type)
        await self.activate_version(rec.id, now=None, channel_type=channel_type)


def _svc(store: _Store) -> PersonaAdminService:
    return PersonaAdminService(payload_store=store, feature_persona_admin_enabled=True,
                               owner_telegram_id=OWNER)


def _with_op(base: dict, *items: dict) -> dict:
    cat = deepcopy(base)
    cat["operacion"] = deepcopy(list(items))
    return cat


LEGACY = {"id": "lucien", "hecho": "Lucien es el bot.", "alias": ["Lucien", "mi familia", "Sol"]}


async def test_legacy_invalid_alias_does_not_block_saving_another_section() -> None:
    store = _Store()
    legacy = _with_op(get_persona_catalog(), LEGACY)
    await store.seed_legacy(legacy, "vip")
    edited = deepcopy(legacy)
    edited["persona_facts"][0]["hecho"] = "Hecho editado desde el panel."
    record = await _svc(store).save_persona(OWNER, edited)
    assert record.payload["persona_facts"][0]["hecho"] == "Hecho editado desde el panel."
    assert record.payload["operacion"][0]["alias"] == ["Lucien", "mi familia", "Sol"]  # intacto
    assert store.get_active_calls == ["vip"]


async def test_new_invalid_alias_is_still_rejected_next_to_legacy_ones() -> None:
    store = _Store()
    legacy = _with_op(get_persona_catalog(), LEGACY)
    await store.seed_legacy(legacy, "vip")
    added = deepcopy(legacy)
    added["operacion"].append({"id": "x", "hecho": "h", "alias": ["la familia"]})
    with pytest.raises(ValueError, match="Datos personales"):
        await _svc(store).save_persona(OWNER, added)
    more = deepcopy(legacy)
    more["operacion"][0]["alias"].append("Mar")
    with pytest.raises(ValueError, match="común"):
        await _svc(store).save_persona(OWNER, more)
    assert len(store.rows) == 1  # nada se guardó


async def test_first_save_without_active_version_validates_everything() -> None:
    store = _Store()
    with pytest.raises(ValueError, match="Datos personales"):
        await _svc(store).save_persona(OWNER, _with_op(get_persona_catalog(), LEGACY))
    assert store.rows == []


async def test_no_operacion_items_skip_the_extra_read() -> None:
    store = _Store()
    await _svc(store).save_persona(OWNER, deepcopy(get_persona_catalog()))
    await _svc(store).save_persona(OWNER, _with_op(get_persona_catalog()))  # lista vacía
    assert store.get_active_calls == []


async def test_validation_is_isolated_per_channel() -> None:
    # VIP tiene "Sol" guardado (legacy); en atención "Sol" es nuevo → se rechaza.
    store = _Store()
    await store.seed_legacy(_with_op(get_persona_catalog(), LEGACY), "vip")
    atn = _with_op(get_persona_atencion_catalog(),
                   {"id": "lucien", "hecho": "h", "alias": ["Lucien", "Sol"]})
    with pytest.raises(ValueError, match="común"):
        await _svc(store).save_persona(OWNER, atn, channel_type="atencion")
    assert store.get_active_calls == ["atencion"]
    # Y al revés: lo guardado en atención no habilita el mismo alias en VIP.
    store2 = _Store()
    await store2.seed_legacy(atn, "atencion")
    vip = _with_op(get_persona_catalog(), {"id": "lucien", "hecho": "h", "alias": ["Lucien", "Sol"]})
    with pytest.raises(ValueError, match="común"):
        await _svc(store2).save_persona(OWNER, vip, channel_type="vip")
    edited_atn = deepcopy(atn)
    edited_atn["operacion"][0]["hecho"] = "Otro hecho."
    record = await _svc(store2).save_persona(OWNER, edited_atn, channel_type="atencion")
    assert record.channel_type == "atencion"


async def test_proper_name_alias_is_saved_with_its_capitalization() -> None:
    store = _Store()
    record = await _svc(store).save_persona(
        OWNER, _with_op(get_persona_catalog(), {"id": "ana", "hecho": "Ana lleva la agenda.",
                                                "alias": ["Ana", "El Diván"]})
    )
    assert record.payload["operacion"][0]["alias"] == ["Ana", "El Diván"]  # sin normalizar



# Review round 1 (G1): a new Dato tema must not silently disable a stored alias.


def _with_lucien(payload: dict) -> dict:
    out = deepcopy(payload)
    out["operacion"] = [{"id": "lucien", "alias": ["Lucien", "el mayordomo"],
                         "hecho": "Lucien es el bot administrador del canal VIP."}]
    return out


def test_new_fact_tema_disabling_a_stored_alias_is_rejected():
    from diana.application.persona_admin_service import prepare_persona_payload

    previous = _with_lucien(get_persona_catalog())
    nuevo = deepcopy(previous)
    nuevo["persona_facts"].append({"id": "casa", "tema": ["mayordomo"], "hecho": "h"})
    with pytest.raises(ValueError, match="desactivaría el alias «el mayordomo».*«lucien»"):
        prepare_persona_payload(nuevo, previous=previous)


def test_alias_already_disabled_before_the_save_does_not_block():
    from diana.application.persona_admin_service import prepare_persona_payload

    previous = _with_lucien(get_persona_catalog())
    previous["persona_facts"].append({"id": "casa", "tema": ["mayordomo"], "hecho": "h"})
    nuevo = deepcopy(previous)
    nuevo["policies"].append({"id": "otra", "tema": ["precios"], "regla": "r"})
    prepare_persona_payload(nuevo, previous=previous)  # legacy collision: no raise
