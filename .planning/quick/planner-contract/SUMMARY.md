# SUMMARY — planner-contract

**Status:** done  
**Item:** planner-contract (Pool remaining-contracts-cognitive · 1/4)  
**Source of truth:** `docs/contratos_restantes.md` Anexo C (C.1–C.4)  
**Date:** 2026-07-23  

## Executive summary

Planner runtime aligned to Anexo C.3: pure deterministic map from `Comprehension.needs_*` → ordered `Plan.capabilities`. **Force-history insert removed.** Capabilities appear iff the corresponding `needs_*` is true; all-false → `[]`. Director blast path proves plan/retrieved omit `knowledge.history` when `needs_history=false`. Full unit suite green (369 passed).

## Tasks completed

| Task | Outcome | Commit |
|------|---------|--------|
| 1. C.3 unit contract + remove force-history | GREEN: inverted force tests; pure map; Plan docstring | `396fbcb` `fix(cognitive): Planner omits caps when needs_* is false (Anexo C.3)` |
| 2. Director blast path + full unit gate | GREEN: no production Director change needed | `66d3124` `test(cognitive): Director omits knowledge.history when needs_history is false` |

## Changes

### Production
- `src/diana/cognitive/planner.py` — deleted `_HISTORY_CAP` force-insert; pure `_NEED_TO_CAPABILITY` loop; C.1–C.3 module docstring
- `src/diana/cognitive/models.py` — `Plan` docstring maps `capabilities` ← `capacidades_solicitadas`; empty list legal

### Tests
- `tests/unit/cognitive/test_planner.py` — replaced force-history tests; added omit-when-false (parametrize), empty plan, determinism, C.4 set+stable order
- `tests/unit/cognitive/test_director.py` — `test_director_plan_omits_history_when_needs_history_false`

## Deviations

None. Optional Plan docstring included in WU1. No production Director/Registry change required (A1 confirmed).

## Verifications

```text
.venv/bin/python -m pytest -q tests/unit/cognitive/test_planner.py
→ 13 passed

.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_models.py \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/cognitive/test_registry.py \
  tests/unit/cognitive/test_context_builder.py
→ 93 passed

.venv/bin/python -m pytest -q tests/unit
→ 369 passed
```

TDD: RED (3 force-history failures) → GREEN after delete force-insert.

## Locked decisions respected

- L1–L11: English `capabilities`; no force-history; empty `[]` legal; stable order; no Planner error path; no `needs_profile`; no Decision.action expansion; dirty WIP untouched

## Residuals

| título | clase_sugerida | por_qué | archivos |
|--------|----------------|---------|----------|
| MVP_COMPONENT_DESIGN still documents force-history | out-of-scope | Anexo C supersedes; documentador residual | `docs/MVP_COMPONENT_DESIGN.md` §5.6 |
| Anexos D–I contract alignment | out-of-scope | Separate pool items | ContextBuilder, Generator, Decider, … |
| needs_profile / knowledge.profile F2 | out-of-scope | Explicit F1 non-goal | registry F2 hook only |
| Dirty-tree turns.error alembic residual | out-of-scope | L10 do-not-touch | `alembic/versions/002_turns_error.py`, infra models/repos |

## Self-Check: PASSED

- [x] Todas las tareas completadas
- [x] Tests del PLAN corridos
- [x] 0 regresiones atribuibles
- [x] Convenciones del proyecto respetadas
- [x] Force-history code path removed
- [x] Dirty-tree WIP not staged
- [x] Conventional commits only (no AI attribution)

## Paths

- PLAN: `.planning/quick/planner-contract/PLAN.md`
- SUMMARY: `.planning/quick/planner-contract/SUMMARY.md`
- Log: `.planning/quick/gsd-planner-contract.log`

## Fix round 1 (review bab3bdb6)

All 7 open issues fixed:
1. Director empty-plan blast (`test_director_empty_plan_when_all_needs_false`)
2. Single-true flag parametrize
3. Exact ordered list equality on omit-one
4. Bare `getattr` (no soft `False` default)
5. Tests import production `_NEED_TO_CAPABILITY`
6. C.4 set+list kept with contract comments
7. Same as #1

Verification after fix round: cognitive slice **100 passed**; full unit **376 passed**.

## next_recommended

arch-enforcer (or re-review if orchestrator loops)
