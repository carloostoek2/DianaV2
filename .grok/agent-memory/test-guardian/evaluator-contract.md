# Test-Guardian Report: evaluator-contract

**Date:** 2026-07-23  
**Auditor:** test-guardian  
**Plan:** `.planning/quick/evaluator-contract/PLAN.md`  
**Summary:** `.planning/quick/evaluator-contract/SUMMARY.md`  
**Arch:** `.grok/agent-memory/arch-enforcer/evaluator-contract.md` (PASS WITH NOTES)  
**Verdict:** suite protege adecuadamente  

## Coverage Audit

### DoD map (PLAN tasks 1–4)

| Contract / DoD item | Protected by | Status |
|---------------------|--------------|--------|
| `EvaluatorInput` English fields + `extra="forbid"` | `test_evaluator_input_accepts_full_payload`, `_rejects_extra_fields`, `_requires_all_fields` | OK |
| `list_included_blocks` null-like parity with `build` headings | `test_list_included_blocks_matches_prompt_sections`, `_empty_when_all_null_like` | OK |
| `evaluate(EvaluatorInput) → EvaluationProfile` | `test_evaluate_accepts_evaluator_input`, `_returns_seven_dimension_profile` | OK |
| Messages: draft + turn + emotion | `test_evaluate_messages_include_draft_and_turno_and_emotion` | OK |
| Anti-contamination names-only (B.2 / L13) | Unit: names present + marker absent; **Director:** real history body planted, absent from Evaluator messages | OK |
| Doctrine ~0.7 prompt guidance when policy absent (L7) | `test_evaluate_system_prompt_doctrine_guidance_when_policy_absent` | OK |
| B.6 one retry then typed error (L8–L9) | `test_evaluate_retries_once_on_validation_error`, `_double_fail_raises_…`, `_incomplete_dims…`, `_value_error_is_schema_class…` | OK |
| No synthetic profile on fail (L9) | Double-fail / incomplete raise `EvaluatorSchemaInvalidError`; director asserts no `evaluation` / `decision` trace | OK |
| English dims only / no score_global (L1, BR-09) | `test_evaluator_field_names_are_english_only` + `test_evaluation_profile_invariants.py` | OK |
| Director wires `included_blocks` from same retrieved map (L3–L5) | `test_director_passes_included_blocks_to_evaluator` | OK |
| Schema fail stops before Decision (L11 cognitive) | `test_director_evaluator_schema_fail_no_decision_trace` | OK |
| TAC-01 happy path still 3 LLM calls | `test_tac01_llm_calls_only_analyst_generator_evaluator` | OK |
| Orchestrator notify + `mark_failed` + no VIP send (L10–L11) | `test_orchestrator_evaluator_schema_fail_marks_failed_notifies_owner` | OK |
| Import purity cognitive ↛ telegram/behavior/learning | `test_import_purity.py` (in primary slice) | OK |
| Analyst A.6 path still green | `test_orchestrator_analyst_schema_fail_…` + director analyst fail | OK |

**Required PLAN test names:** 17/17 present (see inventory in log).

### Soft notes (not GAPS — do not block)

1. **Unit anti-contamination is marker-only** (`SECRET-HISTORY-BODY` never injected into DTO). Real body exclusion is covered at Director with planted history text — same observation as arch-enforcer #3. Suite still protects L13.
2. **Full public comprehension + `raw_llm_output` exclusion** — implementation serializes explicit public fields only; unit test asserts emotion (PLAN-named minimum). No named PLAN test for `raw_llm_output` absence; residual confidence only.
3. **Doctrine guidance when policy present** — no negative assert that `_DOCTRINE_NO_POLICY` is omitted when `"knowledge.policy" in included_blocks`. Out of explicit PLAN test list; optional follow-up.
4. **Notifier failure isolation** on Evaluator branch (must not mask typed error) — mirrored in production code; not a dedicated test for Evaluator (Analyst path has the same pattern). Residual optional.

### Residuals outside DoD (do not inflate)

- Trace snapshot for `included_blocks`
- Doctrine hard-clamp
- SPEC/REQ full sync, B.8 schema version, F2 regenerate
- Dirty-tree alembic residual

## Mock Audit

Inventory command on item-touched tests (`test_models`, `test_context_builder`, `test_evaluator`, `test_director`, `test_turn_orchestrator` relevant cases):

| Archivo | Mock / patch | Clasificación | Path de negocio | Acción |
|---------|--------------|---------------|-----------------|--------|
| `test_evaluator.py` | `FakeLLM` / `BoomLLM(FakeLLM)` | **PERMITIDO** | LLM provider edge; real `Evaluator` + real `EvaluatorInput` | ninguna |
| `test_director.py` | `FakeLLM` + InMemory ports (`InMemoryMessageHistory`, `InMemoryTurnStatusSink`, …) | **PERMITIDO** | External LLM + ports; real Director/Evaluator/ContextBuilder | ninguna |
| `test_turn_orchestrator.py` (B.6 eval) | `FakeLLM` + `FakeOwnerNotifier` + `FakeTelegramActuator` + InMemory stores; **real** Director/Evaluator/AdminService/BehaviorEngine | **PERMITIDO** | Telegram / owner notify / delivery edges | ninguna |
| `test_models.py` / `test_context_builder.py` | none | — | pure model / builder | ninguna |
| Item tests | `@patch` / `MagicMock` / `AsyncMock` / `monkeypatch` on Evaluator/Director | **0 found** | — | — |

**Resumen mocks:** ~3 clases de fakes permitidos (FakeLLM, FakeOwnerNotifier, FakeTelegramActuator + InMemory ports); **0 mocks prohibidos** en scope del ítem.  
**Confianza de realidad:** **alta** — real Evaluator/Director/ContextBuilder/Orchestrator paths; only external edges faked; DB/state asserted via InMemory stores (`error`, `send_count`, learning not called, trace keys).

## Re-run Results

```text
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_models.py \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_evaluator.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_evaluation_profile_invariants.py \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/llm/test_fake_llm.py
→ 123 passed

.venv/bin/python -m pytest -q tests/unit
→ 355 passed in 5.43s
```

## Pre-existing vs Attributable

- **0 failures** in primary slice or full `tests/unit`.
- No attributable regressions from this item.
- Unrelated dirty-tree residual (alembic 002 / turns.error) left untouched per PLAN — not exercised as failure here.

## Tests added/changed this guardian run

**None.** Coverage already matches PLAN DoD; no prohibited mocks to rewrite; no red gaps inside scope.

## Handoff

**Listo para cierre** (Commit Gate / step 6 final tests already green).

- Verdict positive + Mock Audit clean → advance past test-guardian gate.
- No return to executor for test/mock fixes.
- Optional residuals only (marker-only unit anti-contam; raw_llm_output absence assert; doctrine-when-policy-present negative) — do **not** inflate item.
