"""Pure loader for the static persona catalog (Anexo J).

Loads package data ``diana.config.persona_diana.json`` via stdlib only.
No infrastructure / telegram / behavior imports.
"""

from __future__ import annotations

import importlib.resources
import json
from typing import Any

_REQUIRED_TOP_KEYS = (
    "voz_configurada",
    "persona_facts",
    "voice_patterns",
    "policies",
)


def load_persona_catalog() -> dict[str, Any]:
    """Load and validate the Anexo J persona catalog.

    Returns:
        Dict with keys ``voz_configurada``, ``persona_facts``,
        ``voice_patterns``, ``policies``.

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
        # Non-path Traversable missing file may surface as other errors.
        raise FileNotFoundError(
            f"persona catalog not found or unreadable: {resource!r}"
        ) from exc

    return _parse_and_validate(raw)


def _parse_and_validate(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"persona catalog is not valid JSON: {exc}") from exc

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

    for pattern in patterns:
        if not isinstance(pattern, dict):
            raise ValueError("each voice_pattern must be an object")
        for req in ("id", "tags", "patron", "uso"):
            if req not in pattern:
                raise ValueError(f"voice_pattern missing {req}")
        if not isinstance(pattern["tags"], list):
            raise ValueError("voice_pattern.tags must be a list")

    for policy in policies:
        if not isinstance(policy, dict):
            raise ValueError("each policy must be an object")
        for req in ("id", "tema", "regla"):
            if req not in policy:
                raise ValueError(f"policy missing {req}")
        if not isinstance(policy["regla"], str) or not policy["regla"].strip():
            raise ValueError("policy.regla must be a non-empty string")

    return data


__all__ = ["load_persona_catalog"]
