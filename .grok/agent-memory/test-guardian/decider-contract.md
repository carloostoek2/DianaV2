# Test-Guardian Report: decider-contract

**Date:** 2026-07-23  
**Auditor:** test-guardian  
**Plan:** `.planning/quick/decider-contract/PLAN.md`  
**Summary:** `.planning/quick/decider-contract/SUMMARY.md`  
**Arch:** `.grok/agent-memory/arch-enforcer/decider-contract.md` (PASS WITH NOTES, 0 critical)  
**Impact:** `.grok/agent-memory/impact-analyzer/decider-contract.md`  
**Commit:** `4e1db5a` — `feat(cognitive): lock Decider F1 matrix + mode_restriction audit`  
**Verdict:** suite protege adecuadamente  

## Coverage Audit

### Focus map (orchestrator brief + PLAN L1–L5)

| Focus / DoD item | Protected by | Status |
|------------------|--------------|--------|
| **Residual naturalness → approve** (F.3 #2 fall-through) | `test_low_naturalness_still_approves_when_safety_ok` (`naturalness=0.1`, `safety=0.9`, risk not alto → `approve` / `ok_for_human_review`) | OK |
| **No regenerate from naturalness** | `test_low_naturalness_does_not_produce_regenerate` | OK |
| **mode_restriction supervised approve** | `test_mode_restriction_set_on_supervised_approve` → `"supervised_send_to_approve"` | OK |
| **mode_restriction None on escalate safety** | `test_mode_restriction_none_on_escalate_safety` | OK |
| **mode_restriction None on escalate risk** | `test_mode_restriction_none_on_escalate_risk` | OK |
| **mode_restriction None when not supervised** | `test_mode_restriction_none_when_mode_not_supervised` | OK |
| **Decision field default None** | `test_decision_mode_restriction_defaults_none` | OK |
| **Action set lock `approve\|escalate` only** | `test_never_returns_non_f1_actions`, `test_mode_never_produces_send_action`, `test_decision_action_literal_is_exactly_approve_escalate`, `test_decision_rejects_non_f1_actions` | OK |
| **Matrix order: safety → risk → approve** | `test_safety_takes_priority_over_risk`, escalate safety/risk, approve happy path | OK |
| **Boundary `safety == threshold` → approve** | `test_safety_equal_threshold_approves`, `test_custom_safety_threshold` | OK |
| **No mean/LLM in Decider** | `test_decider_source_has_no_mean_or_llm` | OK |
| **Director preserves mode_restriction + draft** | `test_happy_path_approve` asserts `mode_restriction_applied == "supervised_send_to_approve"` + draft | OK |
| **TAC-01: Decider adds 0 LLM calls** | `test_tac01_llm_calls_only_analyst_generator_evaluator` | OK |
| **Import purity cognitive ↛ telegram/behavior/learning** | `test_import_purity.py` | OK |
| **BR-09 EvaluationProfile 7D** | `test_evaluation_profile_invariants.py` | OK |

### Required PLAN Task-1 test names

| Test name | Present |
|-----------|---------|
| `test_low_naturalness_still_approves_when_safety_ok` | yes |
| `test_low_naturalness_does_not_produce_regenerate` | yes |
| `test_mode_restriction_set_on_supervised_approve` | yes |
| `test_mode_restriction_none_on_escalate_safety` | yes |
| `test_mode_restriction_none_on_escalate_risk` | yes |
| `test_mode_restriction_none_when_mode_not_supervised` | yes |
| `test_decision_mode_restriction_defaults_none` | yes |
| Keep existing F1 locks (never non-F1, mode never send, source no mean/LLM, threshold/priority) | yes |

**17 tests in `test_decider.py`** (all pure real `Decider` + real `Decision`/`EvaluationProfile`/`Comprehension`).

### Soft notes (not GAPS — do not block)

1. **Director escalate paths** do not re-assert `mode_restriction_applied is None` (only draft + reason). Field-None on escalate is fully locked at Decider unit level; Director rebuild always copies the field (including `None`). Optional strengthen only.
2. **Low naturalness not re-tested through full Director pipeline** — pure matrix unit is sufficient; evaluation is passed through unchanged.
3. **L6 composition threshold wiring** deferred per PLAN residual — no test required this slice.

### Residuals outside DoD (do not inflate)

- F.3 #2 naturalness→regenerate (F2+)
- Composition `eval_thresholds` wire (L6)
- Public `send` / `regenerate` / `consult_doctrine`
- Director regenerate loop

## Mock Audit

Inventory command on item-touched tests:

```bash
rg -nE '@patch|patch\(|MagicMock|AsyncMock|Mock\(|monkeypatch|mocker\.' \
  tests/unit/cognitive/test_decider.py \
  tests/unit/cognitive/test_models.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/cognitive/test_evaluation_profile_invariants.py
```

| Archivo | Mock / patch | Clasificación | Path de negocio | Acción |
|---------|--------------|---------------|-----------------|--------|
| `test_decider.py` | none | — | real `Decider.decide` matrix | ninguna |
| `test_models.py` (Decision) | none | — | real Pydantic `Decision` | ninguna |
| `test_evaluation_profile_invariants.py` | none | — | real `EvaluationProfile` | ninguna |
| `test_import_purity.py` | none (AST scan) | — | import graph purity | ninguna |
| `test_director.py` (approve/escalate/TAC-01) | `FakeLLM` + InMemory ports; **real** `Decider`/`CognitiveDirector` | **PERMITIDO** | LLM edge only; Decider path is real pure matrix | ninguna |
| `test_turn_orchestrator.py` (safety net) | FakeLLM / FakeOwnerNotifier / FakeTelegramActuator + **real** `Decider()` | **PERMITIDO** | Telegram/notify/delivery edges | ninguna |
| Item tests | `@patch` / `MagicMock` / `AsyncMock` / `monkeypatch` on Decider | **0 found** | — | — |

Acceptance TAC mocks (`MagicMock` bot/handler) are **outside item production path** for Decider matrix (Telegram wiring doubles); not used to stub Decider logic.

**Resumen mocks:** 0 mocks on pure Decider/Decision unit path; FakeLLM/InMemory on director edge only (**PERMITIDO**); **0 mocks prohibidos** en scope del ítem.  
**Confianza de realidad:** **alta** — PLAN mock policy honored (“none — pure unit”); asserts on real matrix outputs, reason tokens, action Literal, source text, Director draft+audit field passthrough.

## Re-run Results

```text
# Executor SUMMARY (commit 4e1db5a) — primary + safety net
.venv/bin/python -m pytest -q tests/unit/cognitive/test_decider.py
→ 21 passed

.venv/bin/python -m pytest -q tests/unit/cognitive/test_models.py -k Decision
→ 10 passed

.venv/bin/python -m pytest -q tests/unit/cognitive/test_director.py \
  -k "escalate or approve or tac01 or safety or risk"
→ 4 passed

.venv/bin/python -m pytest -q tests/unit/cognitive/test_import_purity.py
→ 1 passed

.venv/bin/python -m pytest -q tests/unit/cognitive/test_evaluation_profile_invariants.py
→ 11 passed

.venv/bin/python -m pytest -q tests/unit/application/test_turn_orchestrator.py -k "approve or escalate"
→ 5 passed

.venv/bin/python -m pytest -q tests/unit/acceptance/test_tac_mvp_f1.py
→ 8 passed
```

Static re-audit this guardian run:
- Production `decider.py` matrix order + tokens match PLAN exact algorithm (safety → risk → approve; residual naturalness fall-through; supervised audit token).
- `Decision.mode_restriction_applied: str | None = None` + action Literal still `approve|escalate`.
- Director rebuild copies `mode_restriction_applied` with `draft_text`.
- All PLAN-named tests present; zero `@patch`/`MagicMock` on Decider unit suite.
- Arch-enforcer: PASS WITH NOTES, 0 critical — no executor return required.

## Pre-existing vs Attributable

- **0 failures** attributable to decider-contract.
- Residuals (regenerate, L6 threshold composition wire) intentional out-of-scope — not regressions.
- Dirty-tree WIP unrelated modules left untouched per PLAN L8.

## Tests added/changed this guardian run

None. Suite already locks residual naturalness, mode_restriction, action set, and matrix order with real Decider (no prohibited mocks). No rewrite required.

## Handoff

**Listo para cierre** → **step-6** (final tests / Commit Gate).  
**Do not** return to executor — coverage + mock audit clean.
