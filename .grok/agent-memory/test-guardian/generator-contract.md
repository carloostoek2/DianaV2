# Test-Guardian Report: generator-contract

**Date:** 2026-07-23  
**Auditor:** test-guardian  
**Plan:** `.planning/quick/generator-contract/PLAN.md`  
**Summary:** `.planning/quick/generator-contract/SUMMARY.md`  
**Arch:** `.grok/agent-memory/arch-enforcer/generator-contract.md` (PASS WITH NOTES, 0 critical)  
**Verdict:** suite protege adecuadamente  

## Coverage Audit

### DoD map (PLAN tasks 1–3 / Success Criteria)

| Contract / DoD item | Protected by | Status |
|---------------------|--------------|--------|
| E.1 owner-reply single question; forbid classify/search/score/action | `test_generate_system_prompt_is_owner_reply_question` (tightened: explicit forbid tokens) | OK |
| E.2 plain `generate(prompt) -> str`; prompt unmodified as user content | `test_generate_returns_draft_text`, `_passes_prompt_to_llm`, system-prompt user content assert | OK |
| Only `generate`, never `generate_structured` | `test_generate_uses_only_generate_not_structured` | OK |
| E.4 empty → one retry → success | `test_generate_empty_then_success_retries_once` (2 calls, same user prompt) | OK |
| E.4 whitespace → one retry → success | `test_generate_whitespace_then_success_retries_once` | OK |
| E.4 permanent empty → typed error after exactly 2 calls | `test_generate_double_empty_raises_generador_salida_vacia` | OK |
| Transport errors not swallowed as empty-retry | `test_generate_transport_error_does_not_count_as_empty_retry` (1 call, RuntimeError) | OK |
| Exception `str` / `reason` = `generador_salida_vacia` | `test_generator_empty_output_error_str_and_reason` | OK |
| Director: gen fail before Evaluator/Decider; no eval/decision/generated_text | `test_generator_empty_fails_before_evaluator` | OK |
| Director status: GENERATING present; EVALUATING/DECIDING absent; last FAILED | same | OK |
| Only Analyst structured on gen fail (no EvaluationProfile call) | same (`len(structured)==1`, schema ≠ EvaluationProfile) | OK |
| No `empty_draft` escalate path | repo: zero production `empty_draft`; old test replaced | OK |
| Orchestrator: `mark_failed(error=generador_salida_vacia)` + `notify_info` | `test_orchestrator_generator_empty_marks_failed_notifies_owner` | OK |
| No VIP send / no approval / no draft-escalation notify / no learn on gen fail | same (`send_count==0`, `drafts==[]`, `escalations==[]`, `approvals` empty, `learn.calls==[]`) | OK |
| Import purity cognitive ↛ telegram/behavior/learning | `test_import_purity.py` (primary cluster) | OK |
| F1 `Decision.action` still approve\|escalate | production models + director suite; arch locked | OK |

**Required PLAN test names:** all present (9 generator + 1 director empty-fail + 1 orchestrator notify + import purity in primary gate).

### Soft notes (not GAPS — do not block)

1. **Notifier failure isolation** on Generator branch — production wraps `notify_info` so secondary fail does not mask typed error (same residual class as A.6/B.6/D.6); no dedicated unit for that isolation.
2. **Stale pytest cache** — `lastfailed` still lists removed `test_empty_draft_escalates` and missing `test_import_purity.py` path; noise only, not a live failure.

### Residuals outside DoD (do not inflate)

- SPEC/documentador empty-draft wording → failed semantics
- Dirty-tree alembic `turns.error` WIP
- Optional `GeneratorInput` DTO
- Temperature product tuning
- F2 regenerate

## Mock Audit

Inventory (`@patch|patch\(|MagicMock|AsyncMock|Mock\(|monkeypatch|mocker\.`) on item-touched tests:

| Archivo | Mock / patch | Clasificación | Path de negocio | Acción |
|---------|--------------|---------------|-----------------|--------|
| `test_generator.py` | `FakeLLM` text queue | **PERMITIDO** | LLM provider edge; real `Generator` + real exception | ninguna |
| `test_director.py` (gen empty) | `FakeLLM` + InMemory ports (`InMemoryTraceStore`, `InMemoryTurnStatusSink`, …) | **PERMITIDO** | External LLM + ports; **real** Director/Generator/Evaluator/Decider | ninguna |
| `test_turn_orchestrator.py` (E.4) | `FakeLLM` + `FakeOwnerNotifier` + `FakeTelegramActuator` + InMemory stores; **real** `CognitiveDirector`/`Generator`/`AdminService`/`BehaviorEngine` | **PERMITIDO** | Telegram / owner notify / delivery edges | ninguna |
| Item tests | `@patch` / `MagicMock` / `AsyncMock` / `monkeypatch` on Generator/Director | **0 found** | — | — |

**Resumen mocks:** ~3 clases de fakes permitidos (FakeLLM, FakeOwnerNotifier, FakeTelegramActuator + InMemory ports); **0 mocks prohibidos** en scope del ítem.  
**Confianza de realidad:** **alta** — real Generator/Director/Orchestrator paths; only external edges faked; asserts on call counts, trace keys, turn status/`error`, send_count, notifier surfaces, approval store.

PLAN mock policy honored: FakeLLM at port only; no mocking Generator internals when testing Director fail path.

## Re-run Results

```text
# Executor SUMMARY (commits 49dc4d9, 3d60877, ef4f43d) — primary + full unit
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_generator.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/cognitive/test_import_purity.py
→ 54 passed

.venv/bin/python -m pytest -q tests/unit
→ 396 passed
```

Static re-audit this guardian run:
- Production `generator.py` / `exceptions.py` / `director.py` / `turn_orchestrator.py` match all PLAN asserts (retry×2, reason token, no empty escalate, typed notify branch).
- Guardian tightened E.1 system-prompt forbid asserts against production `_SYSTEM` substrings (`do not classify`, `search knowledge`, `score`, `choose system actions`) — must stay green without production change.
- pytest nodeids include all item tests; lastfailed only stale unrelated paths.

## Pre-existing vs Attributable

- **0 failures** attributable to generator-contract.
- Stale `lastfailed` entry for removed `test_empty_draft_escalates` — cache noise from flip; not a regression.
- Dirty-tree alembic residual left untouched per PLAN — not exercised as failure.

## Tests added/changed this guardian run

| File | Change |
|------|--------|
| `tests/unit/cognitive/test_generator.py` | Tightened `test_generate_system_prompt_is_owner_reply_question`: replace no-op forbidden loop with real asserts on E.1 forbid tokens + unmodified user prompt (arch-enforcer observation #1) |

No new test files. No prohibited-mock rewrites required.

## Handoff

**Listo para cierre** → **step-6** (final tests / Commit Gate).

- Verdict positive + Mock Audit clean (0 prohibidos) → advance past test-guardian gate.
- No return to executor for test/mock fixes.
- Optional residuals only (notify isolation unit, SPEC wording, alembic dirty tree) — do **not** inflate item.
