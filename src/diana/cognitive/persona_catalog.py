"""Pure loader for the static persona catalog (Anexo J / H9).

Loads package data ``diana.config.persona_diana.json`` via stdlib only.
No infrastructure / telegram / behavior imports.
"""

from __future__ import annotations

import importlib.resources
import json
import re
from functools import lru_cache
from typing import Any

_REQUIRED_TOP_KEYS = (
    "voz_configurada",
    "persona_facts",
    "voice_patterns",
    "policies",
    "schedule",
)

_WEEKDAY_TOKENS = frozenset(
    {"lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"}
)
_HHMM_RE = re.compile(r"^\d{2}:\d{2}$")


def load_persona_catalog() -> dict[str, Any]:
    """Load and validate the Anexo J persona catalog (uncached).

    Returns:
        Dict with keys ``voz_configurada``, ``persona_facts``,
        ``voice_patterns``, ``policies``, ``schedule``.

    Raises:
        FileNotFoundError / OSError: package data file missing or unreadable.
        ValueError: JSON present but structurally invalid.
    """
    resource = importlib.resources.files("diana.config").joinpath("persona_diana.json")
    try:
        raw = resource.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except OSError:
        raise
    except Exception as exc:
        raise FileNotFoundError(
            f"persona catalog not found or unreadable: {resource!r}"
        ) from exc

    return _parse_and_validate(raw)


@lru_cache(maxsize=1)
def get_persona_catalog() -> dict[str, Any]:
    """Cached catalog for boot/composition; avoid repeated disk/package I/O."""
    return load_persona_catalog()


def _parse_and_validate(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"persona catalog is not valid JSON: {exc}") from exc
    return validate_persona_catalog(data)


def validate_persona_catalog(data: dict[str, Any]) -> dict[str, Any]:
    """Pure, reusable catalog validation — same ValueError contract as
    ``_parse_and_validate`` (which delegates here after JSON decoding).

    Validates the complete persona catalog dict (voz_configurada, persona_facts,
    voice_patterns, policies, schedule) so DB-backed payloads (owner admin)
    share the exact same structural rules as the static JSON file.
    """
    if not isinstance(data, dict):
        raise ValueError("persona catalog root must be an object")

    for key in _REQUIRED_TOP_KEYS:
        if key not in data:
            raise ValueError(f"persona catalog missing required key: {key}")

    voz = data["voz_configurada"]
    if not isinstance(voz, dict):
        raise ValueError("voz_configurada must be an object")
    persona = voz.get("persona")
    if not isinstance(persona, str) or not persona.strip():
        raise ValueError("voz_configurada.persona must be a non-empty string")
    rules = voz.get("reglas_estilo")
    if not isinstance(rules, list) or not rules:
        raise ValueError("voz_configurada.reglas_estilo must be a non-empty list")
    if not all(isinstance(r, str) and r.strip() for r in rules):
        raise ValueError("voz_configurada.reglas_estilo entries must be non-empty strings")

    facts = data["persona_facts"]
    patterns = data["voice_patterns"]
    policies = data["policies"]
    if not isinstance(facts, list) or not facts:
        raise ValueError("persona_facts must be a non-empty list")
    if not isinstance(patterns, list) or not patterns:
        raise ValueError("voice_patterns must be a non-empty list")
    if not isinstance(policies, list) or not policies:
        raise ValueError("policies must be a non-empty list")

    for fact in facts:
        if not isinstance(fact, dict):
            raise ValueError("each persona_fact must be an object")
        for req in ("id", "tema", "hecho"):
            if req not in fact:
                raise ValueError(f"persona_fact missing {req}")
        if not isinstance(fact["hecho"], str) or not fact["hecho"].strip():
            raise ValueError("persona_fact.hecho must be a non-empty string")
        tema = fact["tema"]
        if isinstance(tema, list):
            if not tema or not all(isinstance(t, str) and t.strip() for t in tema):
                raise ValueError("persona_fact.tema list must be non-empty strings")
        elif not isinstance(tema, str) or not tema.strip():
            raise ValueError("persona_fact.tema must be a non-empty string or list")

    for pattern in patterns:
        if not isinstance(pattern, dict):
            raise ValueError("each voice_pattern must be an object")
        for req in ("id", "tags", "patron", "uso"):
            if req not in pattern:
                raise ValueError(f"voice_pattern missing {req}")
        tags = pattern["tags"]
        if not isinstance(tags, list) or not tags:
            raise ValueError("voice_pattern.tags must be a non-empty list")
        if not all(isinstance(t, str) and t.strip() for t in tags):
            raise ValueError("voice_pattern.tags entries must be non-empty strings")
        if not isinstance(pattern["patron"], str) or not pattern["patron"].strip():
            raise ValueError("voice_pattern.patron must be a non-empty string")
        if not isinstance(pattern["uso"], str) or not pattern["uso"].strip():
            raise ValueError("voice_pattern.uso must be a non-empty string")

    for policy in policies:
        if not isinstance(policy, dict):
            raise ValueError("each policy must be an object")
        for req in ("id", "tema", "regla"):
            if req not in policy:
                raise ValueError(f"policy missing {req}")
        tema = policy["tema"]
        if isinstance(tema, list):
            if not tema or not all(isinstance(t, str) and t.strip() for t in tema):
                raise ValueError("policy.tema list must be non-empty strings")
        elif not isinstance(tema, str) or not tema.strip():
            raise ValueError("policy.tema must be a non-empty string or list")
        if not isinstance(policy["regla"], str) or not policy["regla"].strip():
            raise ValueError("policy.regla must be a non-empty string")

    _validate_unique_ids("persona_facts", data["persona_facts"])
    _validate_unique_ids("voice_patterns", data["voice_patterns"])
    _validate_unique_ids("policies", data["policies"])
    _validate_schedule(data["schedule"])
    return data


def _validate_unique_ids(section_name: str, items: Any) -> None:
    """Reject duplicate item ids in fact/pattern/policy sections (defense-in-depth).

    The owner admin already prevents duplicates at the panel; this guards the
    write path against legacy/corrupt payloads reaching the runtime.
    """
    if not isinstance(items, list):
        return
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if item_id is None:
            continue
        key = str(item_id)
        if key in seen:
            raise ValueError(f"{section_name} has duplicate id: {item_id!r}")
        seen.add(key)


def _validate_schedule(schedule: Any) -> None:
    """Validate H9.2 weekly agenda structure (fail loud at load)."""
    if not isinstance(schedule, dict):
        raise ValueError("schedule must be an object")

    timezone = schedule.get("timezone")
    if not isinstance(timezone, str) or not timezone.strip():
        raise ValueError("schedule.timezone must be a non-empty string")

    defaults = schedule.get("default_responses")
    if not isinstance(defaults, list) or not defaults:
        raise ValueError("schedule.default_responses must be a non-empty list")
    if not all(isinstance(s, str) and s.strip() for s in defaults):
        raise ValueError(
            "schedule.default_responses entries must be non-empty strings"
        )

    bloques = schedule.get("bloques")
    if not isinstance(bloques, list):
        raise ValueError("schedule.bloques must be a list")

    for idx, bloque in enumerate(bloques):
        if not isinstance(bloque, dict):
            raise ValueError(f"schedule.bloques[{idx}] must be an object")
        dias = bloque.get("dias")
        if not isinstance(dias, list) or not dias:
            raise ValueError(
                f"schedule.bloques[{idx}].dias must be a non-empty list"
            )
        if not all(isinstance(d, str) and d in _WEEKDAY_TOKENS for d in dias):
            raise ValueError(
                f"schedule.bloques[{idx}].dias must use weekday tokens "
                f"without accents ({sorted(_WEEKDAY_TOKENS)})"
            )
        inicio = bloque.get("inicio")
        fin = bloque.get("fin")
        if not isinstance(inicio, str) or not _HHMM_RE.match(inicio):
            raise ValueError(
                f"schedule.bloques[{idx}].inicio must match HH:MM"
            )
        if not isinstance(fin, str) or not _HHMM_RE.match(fin):
            raise ValueError(f"schedule.bloques[{idx}].fin must match HH:MM")
        if not (inicio < fin):
            raise ValueError(
                f"schedule.bloques[{idx}] requires inicio < fin "
                f"(got {inicio!r} / {fin!r})"
            )
        actividad = bloque.get("actividad")
        if not isinstance(actividad, str) or not actividad.strip():
            raise ValueError(
                f"schedule.bloques[{idx}].actividad must be a non-empty string"
            )


__all__ = ["load_persona_catalog", "get_persona_catalog", "validate_persona_catalog"]
