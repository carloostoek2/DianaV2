# SUMMARY — evaluator-contract

**Phase:** quick  
**Plan:** evaluator-contract  
**Status:** DONE  
**Date:** 2026-07-23  
**Source of truth:** `contrato_evaluador.md` (Anexo B.1–B.7)  
**Depends on:** analyst-contract (A.6 retry + typed fail path pattern)

## Objective achieved

Aligned Evaluator runtime + `EvaluatorInput` + B.6 schema fail path to `contrato_evaluador.md` without renaming English `EvaluationProfile` 7D fields, without expanding F1 `Decision.action`, without inventing a default profile on fail, and without feeding raw knowledge bodies into the Evaluator.

## Tasks completed

| Task | Result | Commit |
|------|--------|--------|
| 1. EvaluatorInput + list_included_blocks | DONE | `97eb6fe` feat(cognitive): add EvaluatorInput and list_included_blocks |
| 2. Evaluator B.1–B.6 retry + typed error | DONE | `e14993f` feat(cognitive): Evaluator schema retry and EvaluatorSchemaInvalidError |
| 3. Director wiring | DONE | `ce95f51` feat(cognitive): Director passes included_blocks to Evaluator |
| 4. Orchestrator notify | DONE | `a07be80` feat(application): notify owner on evaluador_schema_invalido |

## What changed

### Production
- `src/diana/cognitive/models.py` — `EvaluatorInput` (draft, comprehension, included_blocks, current_turn; `extra="forbid"`).
- `src/diana/cognitive/context_builder.py` — `list_included_blocks(knowledge)` shares `_is_null_like` with `build` headings.
- `src/diana/cognitive/exceptions.py` — `EvaluatorSchemaInvalidError` with `str` / `.reason` == `evaluador_schema_invalido`.
- `src/diana/cognitive/evaluator.py` — `evaluate(EvaluatorInput)`; B.1 pure “trust this draft?” prompt; doctrine ~0.7 guidance when `knowledge.policy` absent; one schema-class retry then typed error; no synthetic profile.
- `src/diana/cognitive/director.py` — sole production caller; builds `EvaluatorInput` from same `retrieved` map as Generator prompt; no evaluation/decision store on schema fail.
- `src/diana/application/turn_orchestrator.py` — typed branch: `mark_failed(error="evaluador_schema_invalido")` + `admin.notify_info` + re-raise; no VIP send.

### Tests
- Models: full payload, extra forbid, required fields.
- ContextBuilder: `list_included_blocks` parity with `## Knowledge:` headings; all-null-like → `[]`.
- Evaluator: DTO accept; 7D English; doctrine present/absent; B.6 ValidationError/ValueError/Timeout + non-schema no-retry; anti-contamination; raw_llm attach.
- Director: included_blocks names only (history body absent); schema fail no decision/eval + FAILED; TAC-01 still 3 LLM calls.
- Orchestrator: failed + notify `== 1` + `send_count==0` + learning not run.

## Deviations

None material. Commit messages are one work-unit per PLAN task (tests+impl together) rather than splitting pure-test commits. Architectural contracts still met (arch-enforcer process note only).

## Locked decisions preserved

| ID | Decision |
|----|----------|
| L1 | English EvaluationProfile dims unchanged |
| L2 | English EvaluatorInput identifiers (Anexo B map in docstring only) |
| L3 | `included_blocks` = full capability names (`knowledge.history`, …) that entered Generator prompt |
| L7 | doctrine ~0.7 is **prompt guidance only** (no hard-clamp) |
| L9 | no default EvaluationProfile on fail |
| L12 | F1 Decision.action still `approve\|escalate` |
| L13 | names-only included_blocks (no knowledge bodies) |
| TAC-01 | happy path still 3 LLM calls (Analyst + Generator + Evaluator) |

Full locked table: `.planning/quick/evaluator-contract/decisions.md`.

## Hardener review loop

| Field | Value |
|-------|--------|
| HARD_ID | `c71950cb` |
| Effort | **4** |
| Review rounds | **2** |
| Round 1 open | **5** (0 bug, 3 suggestion, 2 nit) — all fixed |
| Final open issues | **0** (CLEAN: General, General-2, General-3, Tests, Plan) |
| Fix commit | `8de5069` — `test(cognitive): harden Evaluator B.6 and doctrine guidance coverage` (**tests only**) |
| Primary slice post-fix | **135 passed** (evaluator+orch+director+purity+invariants) |
| Full unit gate | **355 passed** (`.venv/bin/python -m pytest -q tests/unit`) |
| Arch | **PASS WITH NOTES** · 0 critical |
| Guardian | suite protege · 0 prohibited mocks · high reality confidence |
| Sources | `.grok/agent-memory/review/evaluator-contract.md`, arch-enforcer + test-guardian + impact-analyzer |

### Key fixes from review (round 1 → green)

| # | Severity | Fix | Evidence |
|---|----------|-----|----------|
| 1 | suggestion | B.6 TimeoutError + non-schema RuntimeError coverage | `test_evaluate_timeout_maps_to_evaluador_schema_invalido`; `test_evaluate_non_schema_errors_propagate_without_retry` |
| 2 | suggestion | Doctrine guidance **absent** when `knowledge.policy` included | `test_evaluate_system_prompt_no_neutral_doctrine_when_policy_included` + distinctive tokens |
| 3 | suggestion | Orchestrator notify exact `== 1` (was soft `>= 1`) | `test_orchestrator_evaluator_schema_fail_marks_failed_notifies_owner` |
| 4 | nit | Structural anti-contam (exclude `raw_llm_output` secret from LLM payload) | `test_evaluate_messages_include_bloques_names_not_knowledge_bodies` |
| 5 | nit | raw_llm attach + ValueError recover + stronger doctrine tokens | `test_evaluate_attaches_raw_llm_output_when_missing`; `test_evaluate_retries_once_on_value_error_then_succeeds` |

### Production re-confirmed after hardener (unchanged by `8de5069`)

1. **B.1 / L9** — Evaluator scores only; raise `EvaluatorSchemaInvalidError` after 2 schema-class attempts; no synthetic profile.
2. **B.2 / L3–L4 / L13** — `list_included_blocks` shares `_is_null_like`; names only; no knowledge bodies / no `raw_llm_output` in LLM payload.
3. **B.6 / L8** — Analyst-parity schema-class set; non-schema re-raises immediately.
4. **L10–L11** — Orchestrator typed branch + notify + re-raise; VIP send 0; learning not invoked on fail.
5. **BR-09** — 7D English profile only; Decider uses vector dims, never mean/`score_global`.

## Residuals (classified — document only, do not implement here)

| Residual | Class | Why | Files |
|----------|-------|-----|-------|
| Doctrine hard-clamp to 0.7 when policy absent | **out-of-scope** | Locked L7 prompt-only; residual only if calibration fails | evaluator.py / future decider |
| SPEC.md / REQUERIMIENTOS.md sync to Anexo B | **out-of-scope** | PLAN residual list; docs lag | SPEC.md, REQUERIMIENTOS.md |
| B.8 `evaluacion_schema_version` | **out-of-scope** | When dimensions change | models.py |
| F2 regenerate evaluates from scratch | **out-of-scope** | F1 has no regenerate; L12 holds | — |
| Decider `system_config` thresholds | **out-of-scope** | AGENTS §6.2 separate item | decider.py |
| Unrelated dirty tree (alembic 002 / turns.error) | **out-of-scope** | Pre-existing residual; PLAN forbids touching this pool | `alembic/versions/002_turns_error.py`, infrastructure models/repos/tests |
| Trace snapshot for `included_blocks` | **in-scope-followup** | Reconstructability of which blocks entered Evaluator | director.py, ports TRACE_KEYS |
| Shared `_is_schema_class_failure` util (A.6/B.6) | observation | Optional DRY later; PLAN preferred local duplicate | analyst.py, evaluator.py |

## Verification

```bash
# Full unit gate (executor)
.venv/bin/python -m pytest -q tests/unit
# → 355 passed

# Guardian primary slice (pre-hardener baseline)
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_models.py \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_evaluator.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_evaluation_profile_invariants.py \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/llm/test_fake_llm.py
# → 123 passed

# Hardener fix-round primary slice
# → 135 passed (evaluator+orch+director+purity+invariants)
```

## Self-Check: PASSED

- [x] Todas las tareas completadas
- [x] Tests del PLAN corridos
- [x] 0 regresiones atribuibles
- [x] Convenciones del proyecto respetadas
- [x] Hardener 0 open (effort 4, rounds 2)
- [x] Residuales clasificados sin implementar

## Pool close

> Pool `evaluator-contract` cerrado — 1 ítem completado, hardener effort 4 / 2 rounds / 0 open, tests passing (full unit 355; post-fix primary 135), commits hechos, documentación actualizada.
