"""Anti-regression guard: the calibration modules never touch trust (incident).

The calibration incident (safety_min auto-tuned to 0.95 → mass escalations) is
the precedent that forbids recalibrating security/confidence gates. The trust
budget is updated ONLY by events; thresholds ONLY by manual ``apply_overrides``.
This scan-style guard (mirroring the F5 anti-contamination scans) pins that the
calibration code stays free of any ``trust`` reference — today it has 0 matches.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from diana.application import calibration_math, calibration_service

# Word-boundary guard: matches the standalone word "trust" but NOT substrings
# like "trusted" / "distrust" / "vip_trust_budget" (review round 1 nit).
_TRUST_WORD = re.compile(r"\btrust\b")


def _source_text(module) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


def test_calibration_service_has_no_trust_reference() -> None:
    src = _source_text(calibration_service)
    assert _TRUST_WORD.search(src) is None
    assert "vip_trust_budget" not in src


def test_calibration_math_has_no_trust_reference() -> None:
    src = _source_text(calibration_math)
    assert _TRUST_WORD.search(src) is None
    assert "vip_trust_budget" not in src


def test_trust_service_never_imports_calibration_or_decider() -> None:
    """The trust service stays decoupled from calibration AND from the Decider
    (AGENTS.md §2.2/§4.1 — the double gate composes at the application layer)."""
    import ast

    from diana.application import trust_budget_service

    tree = ast.parse(_source_text(trust_budget_service))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for module in imported:
        assert "calibration" not in module, module
        assert "decider" not in module, module


def test_no_send_call_site_uses_trust_gate() -> None:
    """S12: the trust gates stay EXPOSED-PURE — no sending call-site under
    ``src/diana`` (outside the service module itself) may CALL ``can_autonomous``
    / ``would_autonomous_with_trust`` / ``dispersion_ok``. F2 is still in
    shadow; the real auto-send composition is future Fase 5. This scan-style
    guard (mirroring the F5 anti-contamination scans) pins the no-wiring
    invariant that today is only verified by manual ``rg``."""
    import diana

    root = Path(diana.__file__).resolve().parent
    gates = {"can_autonomous", "would_autonomous_with_trust", "dispersion_ok"}
    offenders: list[tuple[str, int]] = []
    for py in sorted(root.rglob("*.py")):
        if py.name == "trust_budget_service.py":
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in gates
            ):
                offenders.append((str(py), node.lineno))
    assert not offenders, offenders
