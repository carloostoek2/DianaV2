# Arch Audit: planner-contract

**Date:** 2026-07-23  
**Auditor:** arch-enforcer  
**Plan:** `.planning/quick/planner-contract/PLAN.md`  
**Summary:** `.planning/quick/planner-contract/SUMMARY.md`  
**Impact:** `.grok/agent-memory/impact-analyzer/planner-contract.md`  
**Contract:** `docs/contratos_restantes.md` Anexo C (C.1–C.4)  
**Verdict:** PASS WITH NOTES  
**Critical violations:** 0

## Scope audited

Production:
- `src/diana/cognitive/planner.py` — pure `_NEED_TO_CAPABILITY` map; force-history insert **removed**
- `src/diana/cognitive/models.py` — `Plan` docstring (`capabilities` ← `capacidades_solicitadas`; empty legal); `Decision.action` still `approve|escalate`
- `src/diana/cognitive/director.py` — **no production change**; `for cap in plan.capabilities` tolerates omit/empty
- `src/diana/cognitive/registry.py` — resolves requested caps only (no auto-add history) — verify only

Tests:
- `tests/unit/cognitive/test_planner.py` — C.2 map, C.3 omit/empty/parametrize/determinism, C.4 set + stable order, no LLM
- `tests/unit/cognitive/test_director.py` — `test_director_plan_omits_history_when_needs_history_false`

Cross-checks:
- AGENTS.md §3 Cognitive Core single-question Planner; §5.1 Director deterministic; dependency direction
- Import purity: cognitive ↛ `telegram` / `behavior` / `learning` / `aiogram`
- No Decision.action expansion; no Anexos D–I production edits; dirty-tree residual not staged

Commits: `396fbcb`, `66d3124`

## Evidence

| Check | Result |
|-------|--------|
| C.1 single question / pure / no LLM | **PASS** — module docstring + `plan()` only maps flags; source has no `LLM`/`generate`; no try/except |
| C.2 signature | **PASS** — `plan(self, comprehension: Comprehension) -> Plan`; no multi-field DTO |
| C.2 mapping table (6→6) | **PASS** — `_NEED_TO_CAPABILITY` matches history/context/memory/policy/examples/schedule |
| C.2 English field | **PASS** — `Plan.capabilities`; Spanish only in docstring map |
| C.3 minimum knowledge | **PASS** — no `_HISTORY_CAP`; no insert-when-missing; cap only if `needs_*=true` |
| C.3 empty plan | **PASS** — all false → `[]`; Director loop tolerates |
| C.3 determinism | **PASS** — pure ordered loop; unit locks equal plans |
| C.3 no Planner error path | **PASS** — no try/except, no typed Planner error, no orchestrator notify |
| C.4 set + stable order | **PASS** — set equality + list order history→context→memory→examples→schedule (policy absent) |
| Force-history removed | **PASS** — grep production cognitive: only mapping tuple entry for `knowledge.history` |
| Compensating force elsewhere | **PASS** — Director/Registry/ContextBuilder do not re-insert history |
| Director blast path | **PASS** — plan/retrieved omit `knowledge.history` when `needs_history=false`; TAC-style 3 LLM calls |
| F1 Decision.action | **PASS** — still `Literal["approve","escalate"]` |
| No `needs_profile` / no planned profile | **PASS** — comment only; registry F2 hook untouched |
| Cognitive layer purity | **PASS** — planner imports only `Comprehension`/`Plan`; no telegram/behavior |
| Director remains deterministic sequencer | **PASS** — still fixed pipeline; Planner stays pure map (no LLM control) |
| Scope vs PLAN | **PASS** — production: planner + Plan docstring; tests: planner + director; no D–I / telegram / behavior / learning / alembic |
| Dirty-tree residual | **PASS** — SUMMARY/log assert not staged; no alembic/infra in this item |

## Findings

### Critical (must fix before advance)

_None._

### Medium

_None that block advance._

### Observations

1. **`getattr(comprehension, attr, False)` default is dead after analyst-contract** — all six `needs_*` are required on `Comprehension`. Default does not reintroduce force-history; optional tighten to bare `getattr(comprehension, attr)` for clarity only.
2. **`docs/MVP_COMPONENT_DESIGN.md` §5.6 still documents force-history** (“Siempre asegurar history como mínimo operativo”) — Anexo C supersedes; documentador residual, not scope creep.
3. **Thinner Generator knowledge when `needs_history=false`** — contract-intended (C.3 / R1). Analyst short `historial_reciente` (limit 8) remains a separate path; not a layer violation.
4. **Anexos D–I, F2 profile, dirty alembic residual** correctly left out of scope.

## Compliance Checklist

- [x] Capas respetadas (Cognitive ↛ telegram/behavior/learning; Planner pure)
- [x] Scope del PLAN respetado (no D–I / Decider / Telegram / Behavior / alembic)
- [x] Director 100% determinista en control de flujo
- [x] Planner responde una sola pregunta (qué conocimiento recuperar)
- [x] C.3 mínimo conocimiento: sin force-history
- [x] Empty plan legal; Registry no auto-añade caps
- [x] Sin path de error propio del Planner
- [x] F1 `Decision.action` solo `approve|escalate`
- [x] Sin `needs_profile` / sin request de `knowledge.profile` en F1
- [x] Tests reflejan contrato (omit/empty/parametrize/determinism/C.4/Director blast)
- [x] Dirty-tree residual no tocado
- [x] Dependencias de capa en dirección permitida

## Residuals (not item scope inflation)

| Residual | Class | Notes |
|----------|-------|-------|
| MVP_COMPONENT_DESIGN §5.6 force-history wording | out-of-scope | documentador; Anexo C wins |
| Anexos D–I contract alignment | out-of-scope | separate pool items |
| `needs_profile` / `knowledge.profile` F2 | out-of-scope | registry hook only |
| Dirty-tree turns.error alembic residual | out-of-scope | L10 do-not-touch |
| `getattr(..., False)` → direct attr | observation | optional clarity |

## Handoff

**Verdict PASS WITH NOTES (0 critical) → advance to test-guardian.**

No executor rework required for architecture gate. Test-guardian should re-verify:
- `tests/unit/cognitive/test_planner.py` (13) + director omit-history blast
- cognitive purity + full `tests/unit` green (reported 369)
- no reassertion of forced history in remaining suite
- TAC-01 still 3 structured/text ops on happy path
