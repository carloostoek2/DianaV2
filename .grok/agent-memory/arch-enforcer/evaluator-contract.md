# Arch Audit: evaluator-contract

**Date:** 2026-07-23  
**Auditor:** arch-enforcer  
**Plan:** `.planning/quick/evaluator-contract/PLAN.md`  
**Summary:** `.planning/quick/evaluator-contract/SUMMARY.md`  
**Contract:** `contrato_evaluador.md` (Anexo B.1–B.7)  
**Verdict:** PASS WITH NOTES  
**Critical violations:** 0

## Scope audited

Production:
- `src/diana/cognitive/models.py` — `EvaluatorInput` (English fields, `extra="forbid"`); `EvaluationProfile` 7D English unchanged; `Decision.action` still `approve|escalate`
- `src/diana/cognitive/context_builder.py` — `list_included_blocks` shares `_is_null_like` with `build`
- `src/diana/cognitive/exceptions.py` — `EvaluatorSchemaInvalidError` (`reason` / `str` = `evaluador_schema_invalido`)
- `src/diana/cognitive/evaluator.py` — `evaluate(EvaluatorInput)`; B.1 pure prompt; doctrine ~0.7 guidance when policy absent; `_MAX_ATTEMPTS=2`; no default profile
- `src/diana/cognitive/director.py` — sole production `evaluate` call site; blocks from same `retrieved` map; no evaluation/decision store on schema fail
- `src/diana/application/turn_orchestrator.py` — typed branch + `admin.notify_info`; re-raise; mark_failed reason token
- `src/diana/cognitive/decider.py` — safety/risk matrix on vector; no mean/score_global (unchanged by this item)

Cross-checks:
- AGENTS.md §3 module limits, §5.1 Director, §5.2 EvaluationProfile vector, §5.5 anti-contamination, §5.6 learning post-turn
- Import purity: cognitive ↛ `telegram` / `behavior` / `learning` / `aiogram` / `sqlalchemy` / `application`
- Layer direction: Application → Cognitive OK; Cognitive does not reverse-import Application/Telegram
- Focus checks 1–9 from orchestrator brief

Commits: `97eb6fe`, `e14993f`, `ce95f51`, `a07be80`

## Evidence

| Check | Result |
|-------|--------|
| Cognitive → telegram/behavior/learning/aiogram/sqlalchemy | **PASS** — grep on `src/diana/cognitive` clean |
| Director deterministic | **PASS** — fixed pipeline; Evaluator retry fixed max 2 structured calls (not LLM-chosen control) |
| Evaluator single question (B.1 / B.7) | **PASS** — prompt: trust draft? score 7 dims; forbid action / rewrite / mode / score_global; returns `EvaluationProfile` only |
| BR-09 no score collapse | **PASS** — no `mean`/`score_global`/`overall_score`/`confidence` in Evaluator or Decider path; model docstring + prompt forbid aggregate |
| Anti-contamination (B.2 / L13) | **PASS** — messages carry capability **names** in `included_blocks` + draft/turn/public comprehension; no knowledge bodies; Director test asserts history body absent from Evaluator messages |
| `included_blocks` null-like parity (L3–L4) | **PASS** — `list_included_blocks` uses same `_is_null_like` as `build` headings; full capability names (`knowledge.history`, …) |
| Sole evaluate call site + DTO (L5) | **PASS** — production `evaluate(` only in `director.py` with `EvaluatorInput` |
| B.6 retry then typed error (L8–L9) | **PASS** — `_MAX_ATTEMPTS=2`; schema-class = ValidationError/ValueError/Timeout*; raise `EvaluatorSchemaInvalidError`; no synthetic profile |
| Owner notify in application (L10) | **PASS** — orchestrator `isinstance(EvaluatorSchemaInvalidError)` → `mark_failed(..., evaluador_schema_invalido)` + `notify_info`; notifier failures do not mask typed error |
| No VIP send on fail (L11) | **PASS** — exception before Decider usable Decision / deliver; orchestrator test `send_count()==0`, learning not invoked |
| F1 Decision.action (L12) | **PASS** — still `Literal["approve","escalate"]`; Decider unchanged |
| Doctrine guidance prompt-only (L7) | **PASS** — `_DOCTRINE_NO_POLICY` appended to system prompt when `"knowledge.policy" not in included_blocks`; no post-LLM hard-clamp |
| Full public comprehension in prompt (L6) | **PASS** — intent/topics/emotion/urgency/risk + all needs_*; `raw_llm_output` excluded from LLM payload |
| Scope vs PLAN | **PASS** — production files match SUMMARY; no Decider rewrite, Telegram/Behavior/Learning redesign, Spanish field rename |
| Layer dependency direction | **PASS** — Application imports cognitive exceptions (allowed); Cognitive stays pure |

## Findings

### Critical (must fix before advance)

_None._

### Medium

_None that block advance._

### Observations

1. **Duplicated schema-fail helpers** (`_SCHEMA_FAIL_TYPES` / `_is_schema_class_failure`) live in both `analyst.py` and `evaluator.py`. PLAN L8 explicitly preferred local duplicate for blast radius — acceptable; extract only if a third component needs the same loop.
2. **`included_blocks` not snapshotted in TraceStore** — reconstructability of “which names the Evaluator saw” relies on re-deriving from `retrieved` + null-like rules. Documented residual (SUMMARY: in-scope-followup); not DoD for this item.
3. **Unit anti-contamination test weakness is covered at Director** — `test_evaluate_messages_include_bloques_names_not_knowledge_bodies` only asserts a never-injected marker; Director test plants real history body text and proves it never reaches Evaluator messages. Suite still protects the invariant.
4. **Commit process deviation** — SUMMARY notes tests+impl co-committed per task vs pure-test-first commits. Architectural contracts still met; residual for process hygiene only.
5. **Residuals correctly left out of scope** — doctrine hard-clamp, B.8 schema version, SPEC/REQ full sync, F2 regenerate, Decider `system_config` thresholds, dirty-tree alembic — do not inflate this item.

## Compliance Checklist

- [x] Capas respetadas (Cognitive ↛ telegram/behavior/learning)
- [x] Scope del PLAN respetado (no Behavior/Learning/Telegram/Decider redesign)
- [x] Director 100% determinista en control de flujo
- [x] Evaluator responde una sola pregunta; sin action/mode/rewrite
- [x] BR-09: EvaluationProfile sigue siendo vector 7D (sin score_global/mean)
- [x] Anti-contaminación: `included_blocks` = nombres de capacidad, no cuerpos
- [x] B.6: un reintento → `evaluador_schema_invalido`; sin perfil sintético
- [x] Owner notify en application; Cognitive sin conocer Telegram
- [x] Fail path: sin VIP send; Learning no post-turno de éxito
- [x] F1 `Decision.action` solo `approve|escalate`
- [x] Logging: orchestrator `logger.exception` on director fail + notify-fail isolation
- [x] Dependencias de capa en dirección permitida

## Residuals (not item scope inflation)

| Residual | Class | Notes |
|----------|-------|-------|
| Trace snapshot for `included_blocks` | in-scope-followup | Reconstructability |
| Doctrine hard-clamp to 0.7 | out-of-scope | Only if prompt guidance fails calibration |
| SPEC.md / REQUERIMIENTOS.md sync to Anexo B | out-of-scope | Docs lag |
| B.8 `evaluacion_schema_version` | out-of-scope | When dims change |
| Spanish↔English field alias layer | out-of-scope | Provider mis-emit mitigation |
| F2 regenerate evaluates from scratch | out-of-scope | When F2 lands |
| Decider thresholds from `system_config` | out-of-scope | AGENTS 6.2 separate item |
| Shared `_is_schema_class_failure` util | observation | Optional DRY later |

## Handoff

**Verdict PASS WITH NOTES (0 critical) → advance to test-guardian.**

No executor rework required for architecture gate. Test-guardian should re-verify:
- primary slice + full `tests/unit` green
- import purity + evaluation profile invariants
- orchestrator evaluator schema-fail notify + `send_count==0`
- TAC-01 happy path still 3 LLM calls
