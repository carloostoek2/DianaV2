# Arch Audit: decider-contract

**Date:** 2026-07-23  
**Auditor:** arch-enforcer  
**Plan:** `.planning/quick/decider-contract/PLAN.md`  
**Summary:** `.planning/quick/decider-contract/SUMMARY.md`  
**Contract:** `docs/contratos_restantes.md` Anexo F (F.1–F.5) under F1 locks  
**Commit:** `4e1db5a` — `feat(cognitive): lock Decider F1 matrix + mode_restriction audit`  
**Verdict:** PASS WITH NOTES  
**Critical violations:** 0

## Scope audited

Production:
- `src/diana/cognitive/decider.py` — pure matrix; English ↔ Anexo F docstring; residual F.3 #2 explicit; `mode_restriction_applied` on supervised approve
- `src/diana/cognitive/models.py` — `Decision.action: Literal["approve","escalate"]`; optional `mode_restriction_applied: str | None = None`
- `src/diana/cognitive/director.py` — sole `decide(...)` call site; rebuild copies `mode_restriction_applied` with `draft_text`
- Cross-check consumers (no-touch confirmation): `turn_orchestrator.py` still branches only approve|escalate + fail-closed; `composition.py` still `Decider()` defaults (L6 deferred)

Tests surface:
- `tests/unit/cognitive/test_decider.py` — matrix, residual naturalness, mode_restriction semantics, no mean/LLM source scan, F1 action lock
- `tests/unit/cognitive/test_models.py` — action Literal exact; reject send/regenerate/consult_doctrine; field default None
- `tests/unit/cognitive/test_director.py` — happy-path approve preserves `mode_restriction_applied == "supervised_send_to_approve"`

Cross-checks:
- AGENTS.md §3 module limits, §5.1 Director deterministic, §5.2 vector (no score collapse), §5.3 Decision vision vs F1 runtime lock
- Import purity: cognitive ↛ `telegram` / `behavior` / `learning` / `aiogram` / `sqlalchemy`
- Layer direction: Application → Cognitive OK; Cognitive does not reverse-import Application/Telegram
- Focus: action not expanded · F1 matrix · mode_restriction · purity

## Focus checks (orchestrator brief)

| # | Check | Result |
|---|-------|--------|
| 1 | **Action not expanded** | **PASS** — `Literal["approve","escalate"]` only; model rejects `send`/`regenerate`/`consult_doctrine`; Decider never returns non-F1 actions; orchestrator fail-closed on unexpected action |
| 2 | **F1 matrix** | **PASS** — order first-match: (1) `safety < threshold` → escalate/`safety_below_threshold`; (2) `risk=="alto"` → escalate/`risk_high`; (3) else approve/`ok_for_human_review`. Boundary `safety==threshold` → approve. Safety priority over risk. Residual naturalness does not gate |
| 3 | **mode_restriction** | **PASS** — supervised approve sets `"supervised_send_to_approve"`; escalate paths and non-supervised approve → `None`; Director rebuild copies field with draft attach |
| 4 | **Purity** | **PASS** — no LLM/`generate`; no draft read; no `mean(`/`overall_score`/`confidence`; no cognitive imports of telegram/behavior/learning; single question “what action?” |

## Evidence

| Check | Result |
|-------|--------|
| L1 action set | **PASS** — models.py:220 `Literal["approve", "escalate"]`; tests lock exact get_args + reject non-F1 |
| L2 safety + risk matrix | **PASS** — decider.py:62–88 order matches PLAN table; reason tokens unchanged |
| L3 naturalness residual | **PASS** — no naturalness gate in code; docstring residual; tests `test_low_naturalness_*` lock approve / no regenerate |
| L4 mode_restriction audit | **PASS** — field optional default None; token exact `"supervised_send_to_approve"` |
| L5 no draft in Decider | **PASS** — signature is evaluation + comprehension + mode only; Director attaches draft post-decide |
| L6 thresholds composition | **DEFERRED (intentional)** — ctor dict injection remains; `composition.py:183` still `Decider()` — PLAN non-goal |
| L7 no LLM / BR-09 | **PASS** — pure Python matrix; source scan test; EvaluationProfile 7D untouched |
| L8 no-touch list | **PASS** — no Behavior/Generator/Evaluator/Analyst/Planner/Telegram/Learning/alembic rework; orchestrator action vocabulary unchanged |
| Director passthrough | **PASS** — director.py:164–171 copies `mode_restriction_applied` |
| Sole decide call site | **PASS** — production `decide(` only in director |
| Import purity | **PASS** — grep clean on `src/diana/cognitive` |
| Scope vs PLAN | **PASS** — production files match PLAN file map + SUMMARY; deviations: none |

## Findings

### Critical (must fix before advance)

_None._

### Medium

_None that block advance._

### Observations

1. **L6 composition threshold wiring still deferred** — `SqlSystemConfigStore.get_eval_thresholds()` exists but Decider is constructed with defaults only. Correct per PLAN residual; ops follow-up only.
2. **AGENTS.md §5.3 product vision** lists full action set (`send|approve|escalate|consult_doctrine|regenerate`); F1 runtime correctly restricts via models module docstring + Literal. No contradiction to fix in this item — vision vs F1 lock is documented.
3. **Director hardcodes `mode="supervised"`** — matches F1/MVP global mode; audit field always set on approve path through pipeline. Autonomous path only unit-tested on Decider directly.
4. **No `DeciderInput` DTO** — intentional (PLAN A7); kwargs + ctor thresholds sufficient for F1.
5. **Process note** — single work-unit commit (tests+impl together) vs pure test-first commit split. Architectural contracts met; hygiene only.
6. **Residuals correctly left out** — F.3 #2 naturalness→regenerate, public send/regenerate/consult_doctrine, Director regenerate loop, composition eval_thresholds wire.

## Compliance Checklist

- [x] Capas respetadas (Cognitive ↛ telegram/behavior/learning; no I/O)
- [x] Scope del PLAN respetado (no Behavior/Generator/composition threshold wire / action expand)
- [x] Director 100% determinista; Decider pure matrix post-evaluate
- [x] Decider responde una sola pregunta (“qué acción”); sin draft / sin re-juicio de calidad
- [x] BR-09: EvaluationProfile sigue siendo vector 7D (sin mean/score_global)
- [x] F1 `Decision.action` solo `approve|escalate` (no expand)
- [x] F1 matrix: safety → risk alto → approve; residual naturalness fall-through
- [x] `mode_restriction_applied` audit on supervised approve; Director preserves field
- [x] Reason tokens: `safety_below_threshold` | `risk_high` | `ok_for_human_review`
- [x] No LLM in Decider; TAC-01 still 3 LLM calls (Analyst+Generator+Evaluator)
- [x] Orchestrator still fail-closed on unexpected action; no auto-send
- [x] Logging: Decider has no error path of its own (F.4) — acceptable

## Handoff

**Verdict:** PASS WITH NOTES · **Critical:** 0  

**Next agent:** `test-guardian` for `decider-contract`  
**Do not** return to executor — no architectural fixes required.
