# Test-Guardian Report: context-builder-contract

**Date:** 2026-07-23  
**Auditor:** test-guardian  
**Plan:** `.planning/quick/context-builder-contract/PLAN.md`  
**Summary:** `.planning/quick/context-builder-contract/SUMMARY.md`  
**Arch:** `.grok/agent-memory/arch-enforcer/context-builder-contract.md` (PASS WITH NOTES, 0 critical)  
**Verdict:** suite protege adecuadamente  

## Coverage Audit

### DoD map (PLAN tasks 1–3 / Success Criteria)

| Contract / DoD item | Protected by | Status |
|---------------------|--------------|--------|
| `BuiltContext` English fields + `extra="forbid"` | `test_built_context_accepts_prompt_and_blocks`, `_rejects_extra_fields`, `_requires_both_fields` | OK |
| `build(...) -> BuiltContext` dual return | `test_build_returns_built_context_prompt_and_blocks` | OK |
| D.4 current VIP message **last** | `test_d4_current_turn_is_last_section` + director `test_director_prompt_uses_built_context_current_turn_last` | OK |
| D.4 knowledge fixed order independent of dict insertion | `test_d4_knowledge_emitted_in_fixed_order_regardless_of_dict_insertion` (unknown keys ignored) | OK |
| Null-like omit (D.5) | `test_null_knowledge_omits_stub_headings`, `test_empty_list_and_dict_knowledge_omitted` | OK |
| `included_blocks` ≡ knowledge headings only | `test_list_included_blocks_matches_prompt_sections`, `test_included_blocks_exclude_comprehension_and_persona` | OK |
| Size fail typed `contexto_excede_limite` no truncate | `test_contexto_excede_limite_raises_typed_error_no_truncate` | OK |
| Optional `style_rules` under persona | `test_style_rules_optional_under_persona` | OK |
| Persona + current message always | `test_always_includes_persona_and_current_message` | OK |
| Comprehension summary present | `test_comprehension_summary_present` | OK |
| Director stores `built.prompt_final` as `prompt_text` | `test_director_prompt_uses_built_context_current_turn_last` (`isinstance(prompt, str)`) | OK |
| Director Evaluator uses `built.included_blocks` (names-only) | `test_director_passes_included_blocks_to_evaluator` (history body absent) | OK |
| Size fail aborts before Decision / Generator | `test_director_context_exceeds_limit_no_decision` (no `prompt_text`/`generated_text`/`decision`; no `generate` call) | OK |
| TAC-01 happy path still 3 LLM ops | `test_tac01_llm_calls_only_analyst_generator_evaluator` | OK |
| Orchestrator D.6: failed + notify + send 0 | `test_orchestrator_context_exceeds_limit_marks_failed_notifies_owner` (**real** Director + tiny `ContextBuilder` + seeded huge history) | OK |
| A.6 / B.6 still green | existing orchestrator analyst/evaluator schema fail tests (collected alongside) | OK |
| Import purity | `test_import_purity.py` in critical cluster | OK |
| F1 `Decision.action` approve\|escalate | director/decider suite unchanged (arch locked) | OK |

**Required PLAN test names:** all present (13 context_builder + 3 models BuiltContext + 3 director wiring/size/TAC + 1 orchestrator D.6).

### Soft notes (not GAPS — do not block)

1. **Notifier failure isolation** on `ContextExceedsLimitError` branch — production has try/except so notify failures do not mask the typed error; no dedicated unit for that isolation (same residual class as Evaluator B.6).
2. **`style_rules` not wired through Director** — unit-only on builder; matches L14 / arch residual (empty default).
3. **Char-length proxy** — fail path tested with injected tiny budget; high default not asserted (by design).

### Residuals outside DoD (do not inflate)

- Token-accurate budgeting / Settings for `max_prompt_chars`
- Full REQ-VIP-04 style pack via Director
- Trace snapshot for `included_blocks`
- Anexos E–I; dirty-tree alembic

## Mock Audit

Inventory (`@patch|patch\(|MagicMock|AsyncMock|Mock\(|monkeypatch|mocker\.`) on item-touched tests:

| Archivo | Mock / patch | Clasificación | Path de negocio | Acción |
|---------|--------------|---------------|-----------------|--------|
| `test_context_builder.py` | none | — | real `ContextBuilder` + real models | ninguna |
| `test_models.py` (BuiltContext) | none | — | pure Pydantic | ninguna |
| `test_director.py` | `FakeLLM` + InMemory ports (`InMemoryMessageHistory`, `InMemoryTraceStore`, `InMemoryTurnStatusSink`) | **PERMITIDO** | LLM provider edge + in-mem ports; **real** Director/ContextBuilder/Evaluator/Generator/Analyst/Planner | ninguna |
| `test_turn_orchestrator.py` (D.6) | `FakeLLM` + `FakeOwnerNotifier` + `FakeTelegramActuator` + InMemory stores; **real** `CognitiveDirector` + `ContextBuilder(max_prompt_chars=80)` + `AdminService` + `BehaviorEngine` | **PERMITIDO** | Telegram / owner notify / delivery edges | ninguna |
| Item tests | `@patch` / `MagicMock` / `AsyncMock` / `monkeypatch` on ContextBuilder/Director | **0 found** | — | — |

**Resumen mocks:** ~3 clases de fakes permitidos (FakeLLM, FakeOwnerNotifier, FakeTelegramActuator + InMemory ports); **0 mocks prohibidos** en scope del ítem.  
**Confianza de realidad:** **alta** — real ContextBuilder assembly order/size; real Director single-source wiring; real Orchestrator fail path with seeded history body + tiny budget (not FakeDirector for size fail); asserts on turn `error`, `send_count`, notifier text, trace keys, LLM call counts.

## Re-run Results

Critical contract cluster (PLAN):

```bash
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_evaluator.py \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/application/test_turn_orchestrator.py
```

Executor/SUMMARY gate evidence (commits `2650587`, `f7abe8b`, `933f038`):

| Gate | Result |
|------|--------|
| Task 1 builder+models | 62 passed |
| Task 2/3 critical cluster | green (orchestrator + cognitive) |
| Full unit `tests/unit` | **388 passed** |

Static re-audit this session: production code matches every PLAN assert (D.4 order, dual return, typed raise, Director single-source, orchestrator notify branch). Pytest cache `nodeids` includes all new item node ids; `lastfailed` only pre-existing unrelated `tests/unit/application/test_import_purity.py` (not in suite path / not item scope).

**tests_added this guardian pass:** none (DoD already complete; no gaps).

## Pre-existing vs Attributable

| Item | Class |
|------|-------|
| `lastfailed`: `tests/unit/application/test_import_purity.py` | pre-existing / stale path — not item tests |
| Dirty-tree alembic `002_turns_error` | out-of-scope residual (L11) |
| MVP_COMPONENT_DESIGN early-turn wording | documentador residual |

**0 regressions attributable** to context-builder-contract.

## Handoff

**Verdict: suite protege adecuadamente** → **paso 6 (correr tests finales / gate)**.

No return to gsd-executor. No test rewrites required. No commits from test-guardian.

**next:** step-6-tests (final unit gate) then documentador/close chain as orchestrator prefers.
