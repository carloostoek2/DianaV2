"""Guard for the "conocerse" panel policy (scripts/add_conocerse_policy.py).

Panel policies are matched by tema only — no similarity floor — so a broadly
tagged rule would also fire on turns that need a DIFFERENT doctrine and the
Decisor would stop consulting (Astra review, finding 1). The rule must stay on
a single specific tema that the Analyst actually emits.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "add_conocerse_policy.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "add_conocerse_policy", _SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_policy_uses_only_the_specific_conocerse_tema() -> None:
    policy = _load().POLICY
    assert policy["id"] == "conocerse_sin_confirmar"
    assert policy["tema"] == ["conocerse"]


def test_policy_does_not_use_generic_topics() -> None:
    temas = set(_load().POLICY["tema"])
    # "conexion"/"reencuentro" are emitted for many unrelated turns; tagging the
    # rule with them would suppress legitimate gray-zone consults.
    assert "conexion" not in temas
    assert "reencuentro" not in temas


def test_policy_rule_keeps_the_never_confirm_never_deny_contract() -> None:
    rule = _load().POLICY["regla"].lower()
    assert "no negarlo" in rule
    assert "confirmarlo" in rule
    assert "tal vez" in rule
