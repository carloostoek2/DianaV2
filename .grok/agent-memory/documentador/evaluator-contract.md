# Pool Documentation: evaluator-contract

**Items:** 1  
**Date:** 2026-07-23  
**Project:** DianaV2  
**Pool:** evaluator-contract (hardener-agile)  
**Effort:** 4  
**Review rounds:** 2  
**Round 1 open:** 5 (0 bug, 3 suggestion, 2 nit) — all fixed  
**Final open issues:** 0  
**HARD_ID:** `c71950cb`

## Consolidated Outcomes

### Item 1 — Align Evaluator to `contrato_evaluador.md` (Anexo B.1–B.7)

| Field | Value |
|-------|--------|
| Outcome | `EvaluatorInput` + `list_included_blocks`; B.1 pure prompt; doctrine ~0.7 prompt-only; B.6 one retry + `evaluador_schema_invalido`; Director names-only blocks; orchestrator notify + no VIP send |
| Production | models, context_builder, exceptions, evaluator, director, turn_orchestrator |
| Commits | `97eb6fe`, `e14993f`, `ce95f51`, `a07be80` + hardener test-only `8de5069` |
| Tests | Full unit **355 passed**; post-fix primary slice **135 passed**; guardian primary **123 passed** (pre-hardener) |
| Arch | **PASS WITH NOTES** · 0 critical |
| Guardian | Suite protects · 0 prohibited mocks · high reality confidence |
| Review | 2 rounds; **0** final open; CLEAN on General / General-2 / General-3 / Tests / Plan |
| Key hardener fixes | B.6 Timeout/non-schema locks; doctrine inverse (no guidance when policy included); notify `== 1`; structural raw_llm exclusion; ValueError recover + raw attach |
| Wontfix / deferred | doctrine hard-clamp; SPEC/REQ sync; B.8 schema version; F2 regenerate; Decider system_config; alembic/turns.error dirty tree; optional TraceStore included_blocks snapshot |

**Sources:**  
`.planning/quick/evaluator-contract/{PLAN,SUMMARY,decisions}.md`,  
`.planning/quick/gsd-evaluator-contract.log`,  
`.grok/agent-memory/{impact-analyzer,arch-enforcer,test-guardian,review}/evaluator-contract.md`,  
`contrato_evaluador.md`

## Learnings / Patterns

1. **A.6/B.6 twin pattern** — Analyst and Evaluator share the same fail-closed shape (schema-class retry once → typed reason → orchestrator mark_failed + notify + no VIP send). Prefer local duplicate helpers until a third component needs them.
2. **Names, not bodies, for Evaluator context** — `included_blocks` must mirror ContextBuilder null-like rules so Evaluator sees the same capability set the Generator saw, without anti-contamination leaks.
3. **Doctrine guidance is prompt-only** — F1 policy stubs are usually null; ≈0.7 doctrine is instruction, not a post-LLM hard-clamp. Inverse test (policy present → no neutral guidance) is as important as the positive path.
4. **Schema-class set must match production LLM shapes** — `ValidationError` alone misses ValueError (JSON parse) and Timeout*; non-schema provider errors must not be washed into typed schema reasons.
5. **Notify exactness** — soft `>= 1` hides double-notify regressions; gold path asserts `== 1` and reason token in info text.
6. **Test-only hardener rounds are valid closes** — when production already meets L1–L15, fix-round commits that only harden locks still complete the gate (0 open) without production churn.

## Residuals

### Auto-items / Deferred

| Residual | Class | Notes |
|----------|-------|-------|
| Trace snapshot for `included_blocks` | **in-scope-followup** | Optional reconstructability in TraceStore |
| Shared schema-fail helper (A.6/B.6) | observation | Optional DRY; not DoD |

### Out of scope (documented only)

| Residual | Class | Notes |
|----------|-------|-------|
| Doctrine hard-clamp to 0.7 | out-of-scope | Only if prompt guidance fails calibration (L7) |
| SPEC.md / REQUERIMIENTOS.md sync to Anexo B | out-of-scope | Docs lag |
| B.8 `evaluacion_schema_version` | out-of-scope | When dims change |
| F2 regenerate from scratch | out-of-scope | F1 Decision.action unchanged |
| Decider `system_config` thresholds | out-of-scope | AGENTS §6.2 separate |
| alembic 002 / turns.error dirty tree | out-of-scope | Pre-existing uncommitted residual; not this pool |

## Roadmap Updates

- Updated: `.planning/quick/evaluator-contract/SUMMARY.md` (hardener review loop stats, key fixes, classified residuals, pool close).
- Added: `.planning/quick/evaluator-contract/decisions.md` (locked English IDs, full capability names, doctrine prompt-only 0.7, B.6 path).
- Added: this file under `.grok/agent-memory/documentador/`.
- Updated: `.grok/agent-memory/MEMORY.md` documentador index.
- No changes to `SPEC.md`, `REQUERIMIENTOS.md`, `HARDENING_ROADMAP.md`, or production code (documentador scope).

## Docs commit

`6a82af9` — `docs(cognitive): evaluator-contract hardener pool close`

## Next Steps

- Optional follow-up: TraceStore snapshot of `included_blocks` for reconstructability.
- Out-of-scope residual queue remains for SPEC/REQ Anexo B sync, B.8 versioning, doctrine hard-clamp (if calibration fails), Decider system_config, and pre-existing alembic/turns.error dirty tree.
- Pool complete — no further evaluator-contract items queued in this pool.
- Handoff: orchestrator may run Commit Gate de pool; next hardener/contract pool when scheduled.

## Pool close

> Pool `evaluator-contract` cerrado — 1 ítem completado, hardener effort 4 / 2 rounds / 0 open, tests passing (full unit 355), commits hechos, documentación actualizada.
