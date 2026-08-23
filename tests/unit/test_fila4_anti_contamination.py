"""Fila 4 anti-contamination (SPEC-AUTONOMIA-CALIBRACION §10).

The ``turn_outcome_log`` and ``profile_synthesis_queue`` are pure calibration /
infrastructure metrics: they must NEVER write to ``memories``, ``examples`` or
``vip_profile``. Structural scan (F5 style) over the Fila 4 modules — the set
is walked by fragment so a module added later cannot silently escape.
"""

from __future__ import annotations

from pathlib import Path

import diana


def _walk(pkg: str) -> list[Path]:
    root = Path(diana.__file__).resolve().parent
    return sorted((root / pkg).rglob("*.py"))


def _fila4_modules() -> list[Path]:
    """Every Fila 4 module (walked by fragment, not hard-coded).

    Only the DEDICATED Fila 4 modules are scanned: shared carriers
    (``turn_orchestrator`` / ``admin_service``) legitimately host many flows
    and would produce false positives — the invariant is that the ledger
    modules themselves never write to memory/examples/profile.
    """
    modules: list[Path] = []
    for rel in ("application", "jobs", "infrastructure/db/repositories"):
        for path in _walk(rel):
            if any(
                frag in path.name
                for frag in (
                    "turn_outcome",
                    "coincidence",
                    "reaction_signal",
                    "text_quality",
                    "autonomy_readiness",
                    "synthesis_queue",
                    "profile_synthesis_trigger",
                )
            ):
                modules.append(path)
    return sorted(set(modules))


def test_fila4_ledger_never_feeds_memories_examples_or_profile() -> None:
    """turn_outcome_log / readiness / reaction modules never touch the VIP
    memory, the example bank or the synthesized profile (anti-contamination)."""
    forbidden = (
        "repositories.memories",
        "MemoriesRepo",
        "repositories.examples",
        "ExamplesRepo",
        "vip_profile_repo",
        "VipProfileRepo",
        "insert_gold_example",
        "promote_to_example",
        "stable_traits",
        "sensitivities",
    )
    modules = _fila4_modules()
    assert modules, "Fila 4 scan found no modules to check"
    hits: list[str] = []
    for path in modules:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                hits.append(f"{path.name}:{token}")
    assert hits == [], f"Fila 4 modules touching memory/examples/profile: {hits}"


def test_memory_layers_never_import_turn_outcome() -> None:
    """Reverse: the memory / examples / profile writers never import the Fila 4
    ledger (a one-way street — calibration metrics never become memory)."""
    forbidden = (
        "repositories.turn_outcome",
        "turn_outcome_log",
        "TurnOutcomeLog",
        "outcome_log_service",
    )
    hits: list[str] = []
    for rel in ("learning", "cognitive/retrievers"):
        for path in _walk(rel):
            if "outcome" in path.name:
                continue  # the ledger itself is exempt from its own scan
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    hits.append(f"{path.name}:{token}")
    assert hits == [], f"Memory/example layers importing Fila 4 ledger: {hits}"
