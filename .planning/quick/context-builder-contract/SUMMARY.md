# SUMMARY — context-builder-contract

**Status:** complete  
**Phase:** quick · pool remaining-contracts-cognitive · 2/4  
**Source:** `docs/contratos_restantes.md` Anexo D (D.1–D.6)  
**Mode:** Strict TDD (`.venv/bin/python -m pytest -q`)

## Executive summary

ContextBuilder now returns dual `BuiltContext { prompt_final, included_blocks }` with D.4 assembly order (Persona → fixed knowledge emission → Comprehension → **Current VIP message last**), null-like omit, and typed size fail `contexto_excede_limite` (no truncate, no retry). Director consumes a single build result for Generator prompt and Evaluator blocks. Orchestrator marks the turn failed, notifies the owner, and never sends to VIP on size fail.

## Tasks completed

| Task | Work unit | Commit | Result |
|------|-----------|--------|--------|
| 1. BuiltContext + D.4/D.5 builder | `feat(cognitive): ContextBuilder dual BuiltContext, D.4 order, size fail` | `2650587` | GREEN |
| 2. Director BuiltContext wiring | `feat(cognitive): Director consumes BuiltContext for prompt and blocks` | `f7abe8b` | GREEN |
| 3. Orchestrator D.6 notify + full unit | `feat(application): notify owner on contexto_excede_limite` | `933f038` | GREEN |

## Commits

1. `2650587` — `feat(cognitive): ContextBuilder dual BuiltContext, D.4 order, size fail`
2. `f7abe8b` — `feat(cognitive): Director consumes BuiltContext for prompt and blocks`
3. `933f038` — `feat(application): notify owner on contexto_excede_limite`

## Files touched (in scope)

- `src/diana/cognitive/context_builder.py` — dual return, emission order, size check, `style_rules`
- `src/diana/cognitive/models.py` — `BuiltContext`
- `src/diana/cognitive/exceptions.py` — `ContextExceedsLimitError`
- `src/diana/cognitive/director.py` — single-source `built.prompt_final` / `built.included_blocks`
- `src/diana/application/turn_orchestrator.py` — typed notify branch
- `tests/unit/cognitive/test_context_builder.py`
- `tests/unit/cognitive/test_models.py`
- `tests/unit/cognitive/test_director.py`
- `tests/unit/application/test_turn_orchestrator.py`

## Deviations

None. Locked decisions L1–L14 followed. No dirty-tree / Anexos E–I / A–C rework.

## Verifications

| Gate | Command | Result |
|------|---------|--------|
| Task 1 | `pytest -q tests/unit/cognitive/test_context_builder.py tests/unit/cognitive/test_models.py` | 62 passed |
| Task 2 cluster | context_builder + director + evaluator + import_purity | 56 passed |
| Task 3 cluster | orchestrator + cognitive cluster + planner | 93 passed |
| Full unit | `pytest -q tests/unit` | **388 passed** |

## Contract locks verified

- [x] `BuiltContext` English fields + `extra="forbid"`
- [x] `build(...) -> BuiltContext`; Director stores string under `prompt_text`
- [x] D.4: Persona → knowledge (fixed order) → Comprehension → current turn last
- [x] Knowledge emission independent of dict insertion; unknown keys ignored
- [x] Null-like omit; `included_blocks` ≡ knowledge headings only
- [x] Size excess → exact `contexto_excede_limite`; no truncate; no retry
- [x] On size fail: turn `failed`, owner notified, VIP send 0
- [x] Happy-path TAC still 3 LLM ops when build succeeds
- [x] Import purity / F1 Decision.action `approve|escalate` preserved

## Residuals

1. **title:** Token-accurate budgeting / Settings migration for `max_prompt_chars`  
   **clase_sugerida:** out-of-scope  
   **por_qué:** PLAN non-goal; constructor default is F1 approximation  
   **archivos:** `context_builder.py`, future settings

2. **title:** MVP_COMPONENT_DESIGN / SPEC wording still show early current-turn  
   **clase_sugerida:** out-of-scope  
   **por_qué:** documentador residual; not code DoD  
   **archivos:** `docs/MVP_COMPONENT_DESIGN.md`, SPEC

3. **title:** Full REQ-VIP-04 style pack beyond optional `style_rules`  
   **clase_sugerida:** out-of-scope  
   **por_qué:** empty default only in this item  
   **archivos:** ContextBuilder / Settings

4. **title:** Anexos E–I contract alignment  
   **clase_sugerida:** out-of-scope  
   **por_qué:** separate pool items  
   **archivos:** generator, decider, registry, …

5. **title:** Dirty-tree alembic `turns.error` residual  
   **clase_sugerida:** out-of-scope  
   **por_qué:** L11 — not staged; pre-existing WIP  
   **archivos:** `alembic/versions/002_turns_error.py`, infrastructure db models

## Fix round (review 438d8c31)

| Issue | Status | Action |
|-------|--------|--------|
| 1 strip corrupts turn.text | fixed | `lstrip("\n")` + trailing newline only; preserve VIP body |
| 2 style_rules not wired | wontfix | PLAN L14 / residual full REQ-VIP-04; empty default no-op |
| 3 full D.4 headings lock | fixed | exact headings equality in unit test |

## Self-Check: PASSED

- [x] Todas las tareas completadas
- [x] Tests del PLAN corridos
- [x] 0 regresiones atribuibles
- [x] Convenciones del proyecto respetadas
- [x] TDD RED→GREEN per surface
- [x] Conventional commits; no AI attribution
- [x] Dirty-tree residual not staged

## Log

`.planning/quick/gsd-context-builder-contract.log`

## Next

`arch-enforcer` for context-builder-contract.
