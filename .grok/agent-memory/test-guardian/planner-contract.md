# Test-Guardian Report: planner-contract

**Date:** 2026-07-23  
**Auditor:** test-guardian  
**Plan:** `.planning/quick/planner-contract/PLAN.md`  
**Summary:** `.planning/quick/planner-contract/SUMMARY.md`  
**Arch:** `.grok/agent-memory/arch-enforcer/planner-contract.md` (PASS WITH NOTES, 0 critical)  
**Impact:** `.grok/agent-memory/impact-analyzer/planner-contract.md`  
**Verdict:** suite protege adecuadamente  

## Coverage Audit

### DoD map (Anexo C + PLAN tasks 1–2)

| Contract / DoD item | Protected by | Status |
|---------------------|--------------|--------|
| C.1 pure / no LLM | `test_planner_has_no_llm_dependency` + source inspect; real `Planner.plan` only | OK |
| C.2 map default history+context | `test_planner_maps_default_needs_to_history_and_context` | OK |
| C.2 full 6→6 stable order | `test_planner_includes_all_needs_in_stable_order` | OK |
| C.3 never request when needs false | `test_planner_never_requests_cap_when_need_false` (parametrize ×6) | OK |
| C.3 omit history when false | `test_planner_omits_history_when_needs_history_false` | OK |
| C.3 empty plan all-false → `[]` | `test_planner_returns_empty_when_all_needs_false` | OK |
| C.3 determinism same comp → same plan | `test_planner_determinism_same_comprehension_same_plan` | OK |
| C.4 set equality + stable list order | `test_planner_c4_example_set` (set + list; policy absent) | OK |
| Force-history removed (no reassert) | Old `inserts_history` / `forces_history` **gone**; production no `_HISTORY_CAP` | OK |
| Director blast omit history | `test_director_plan_omits_history_when_needs_history_false` (plan + retrieved + TAC 3 LLM) | OK |
| Director uses real Planner | `make_director` → `planner=Planner()` (not mocked) | OK |
| Import purity cognitive | `test_import_purity.py` in regression slice | OK |

**PLAN-required test names:** all present (8 functions + 6 param cases = **13** collected in `test_planner.py`; +1 director blast).

### Production alignment (static)

- `src/diana/cognitive/planner.py`: pure `_NEED_TO_CAPABILITY` loop; **no** force-insert; no try/except; no LLM.
- `Plan` docstring maps `capabilities` ← `capacidades_solicitadas`; empty legal.
- Director `for cap in plan.capabilities` tolerates omit/empty without re-force.

### Soft notes (not GAPS — do not block)

1. Optional `Plan(capabilities=[])` model smoke in `test_models.py` — not in PLAN must-list; unit empty-plan covers behavior.
2. `getattr(comprehension, attr, False)` soft default — arch observation only; not a test gap for C.3.
3. Stale pytest cache still lists deleted force-history node ids — cache noise only.

### Residuals outside DoD (do not inflate)

- MVP_COMPONENT_DESIGN §5.6 force-history wording (documentador)
- Anexos D–I, F2 profile, dirty alembic residual

## Mock Audit

Inventory on item-touched tests:

```text
rg -nE '@patch|patch\(|MagicMock|AsyncMock|Mock\(|monkeypatch|mocker\.' \
  tests/unit/cognitive/test_planner.py
→ 0 matches
```

| Archivo | Mock / patch | Clasificación | Path de negocio | Acción |
|---------|--------------|---------------|-----------------|--------|
| `test_planner.py` | **none** — real `Planner()` + real `Comprehension`/`Plan` | — | Pure C.1–C.4 map | ninguna |
| `test_director.py` (`test_director_plan_omits_history_when_needs_history_false`) | `FakeLLM` structured/text queues | **PERMITIDO** | External LLM edge only; real Director + **real Planner()** + real Registry/ContextBuilder | ninguna |
| `test_director.py` | `InMemoryMessageHistory` / `InMemoryTraceStore` / `InMemoryTurnStatusSink` | **PERMITIDO** | In-memory ports (no network/DB) | ninguna |
| Item tests | `@patch` / `MagicMock` / `AsyncMock` on Planner or plan() | **0 found** | — | — |

**Resumen mocks:** 1 fake class boundary (`FakeLLM`) + InMemory ports; **0 mocks prohibidos** en scope del ítem.  
**Confianza de realidad:** **alta** — Planner is pure and unit-tested with zero doubles; Director blast uses real `Planner()` and only fakes the LLM edge (PLAN L9).

## Re-run Results

Commands (PLAN exact):

```bash
.venv/bin/python -m pytest -q tests/unit/cognitive/test_planner.py
# expected: 13 passed

.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_models.py \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/cognitive/test_registry.py \
  tests/unit/cognitive/test_context_builder.py
# expected: 93 passed

.venv/bin/python -m pytest -q tests/unit
# expected: 369 passed
```

**Evidence this gate uses:**

| Source | Result |
|--------|--------|
| Executor + SUMMARY after commits `396fbcb` / `66d3124` | planner **13**, cognitive slice **93**, full unit **369** passed |
| Static re-audit of sources | tests/production still match Anexo C; no force-history code or asserts |
| pytest `lastfailed` | only stale missing `tests/unit/application/test_import_purity.py` — **pre-existing / unrelated**, not attributable |

**Guardian note:** Coverage + mock audit are complete from source. Formal live re-run is the same command set as **paso 6**; orchestrator should run it for the final green stamp if not already green in this session.

## Pre-existing vs Attributable

| Issue | Classification |
|-------|----------------|
| Stale cache entry `application/test_import_purity.py` | **Pre-existing / noise** — file does not exist; not introduced by planner-contract |
| MVP design doc still mentions force-history | **Out-of-scope residual** (documentador) |
| Dirty-tree alembic `turns.error` | **Out-of-scope** L10 — not staged |

**0 attributable regressions** from planner-contract.

## Tests added/changed this guardian run

**None.** DoD already locked by executor under Strict TDD (RED force-history → GREEN remove insert + director blast). No prohibited mocks to rewrite. No coverage gaps inside PLAN scope.

## Handoff

**Listo para cierre → step-6-tests (final pytest gate).**

- Verdict: **suite protege adecuadamente**
- Mock audit: **pass** (0 prohibited)
- No return to gsd-executor for test/mock fixes
- Optional residuals only (docs force-history wording; model empty-list smoke) — do **not** inflate item

### Report paths

- This report: `.grok/agent-memory/test-guardian/planner-contract.md`
- Log: `.planning/quick/gsd-test-guardian-planner-contract.log`
