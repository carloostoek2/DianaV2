# generator-contract SUMMARY

**Phase:** quick  
**Plan:** generator-contract (Anexo E)  
**Status:** COMPLETE  
**Date:** 2026-07-23  

## Objective

Align Generator empty-output path + single-question surface to `docs/contratos_restantes.md` Anexo E (E.1–E.4): empty/whitespace retries once inside Generator, then typed `GeneratorEmptyOutputError` / `generador_salida_vacia`; Director no longer escalates `empty_draft`; Orchestrator marks turn `failed` + `notify_info` (no VIP send, no approval).

## Tasks completed

| Task | Result | Commit |
|------|--------|--------|
| 1. Generator E.1 prompt + E.4 empty retry + typed error | DONE | `49dc4d9` `test(cognitive): generator empty retry + typed error (Anexo E.4)` |
| 2. Director remove empty_draft; fail before Evaluator | DONE | `3d60877` `fix(cognitive): remove empty_draft escalate; fail before evaluator` |
| 3. Orchestrator typed fail + owner notify | DONE | `ef4f43d` `fix(application): notify owner on generador_salida_vacia` |
| Commit gate: tighten E.1 system prompt assert | DONE | `1308d08` `test(cognitive): tighten generator owner-reply system prompt assert` |

## Review

**Status:** CLEAN  
**HARD_ID:** `ddcf928c`  
**Effort:** 4  
**Rounds:** 1  
**Open issues:** 0  

## Files changed

- `src/diana/cognitive/exceptions.py` — `GeneratorEmptyOutputError`
- `src/diana/cognitive/generator.py` — owner-reply system prompt; `_MAX_ATTEMPTS=2` empty-only retry
- `src/diana/cognitive/director.py` — deleted empty→escalate branch; document gen-fail trace policy
- `src/diana/application/turn_orchestrator.py` — typed branch + `notify_info`
- `tests/unit/cognitive/test_generator.py` — E.1/E.4 coverage
- `tests/unit/cognitive/test_director.py` — `test_generator_empty_fails_before_evaluator`
- `tests/unit/application/test_turn_orchestrator.py` — `test_orchestrator_generator_empty_marks_failed_notifies_owner`

## Deviations

None. Scope held to PLAN; dirty-tree alembic residual left untouched; no Anexos C/D/F rework.

## Verifications

```bash
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_generator.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/cognitive/test_import_purity.py
# 54 passed

.venv/bin/python -m pytest -q tests/unit
# 396 passed
```

- `empty_draft` absent from `src/` and production tests
- Import purity green
- F1 `Decision.action` still `approve|escalate` only

## Residuals

None blocking. Optional follow-ups (out-of-scope):

- título: documentador SPEC mention of empty-draft escalate → failed semantics  
  clase_sugerida: out-of-scope  
  por_qué: PLAN non-goal SPEC rewrite; runtime aligned  
  archivos: docs / SPEC if present

- título: pre-existing dirty tree `turns.error` alembic WIP  
  clase_sugerida: out-of-scope  
  por_qué: explicit PLAN no-touch; not committed by this item  
  archivos: `alembic/versions/002_turns_error.py`, infrastructure models/repos/tests

## Self-Check: PASSED

- [x] Todas las tareas completadas
- [x] Tests del PLAN corridos
- [x] 0 regresiones atribuibles (396 unit green)
- [x] Convenciones del proyecto respetadas (AGENTS.md purity, deterministic Director, English artifacts)
- [x] Commits atómicos por work unit
- [x] No dirty-tree alembic residual committed

## Next

**gsd-arch-enforcer** for generator-contract (Anexo E fail path + purity + no VIP send on gen fail).
