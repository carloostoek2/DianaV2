# Decisions — evaluator-contract

**Date:** 2026-07-23  
**Plan:** `.planning/quick/evaluator-contract/PLAN.md`  
**Source of truth:** `contrato_evaluador.md` (Anexo B)  
**Status:** locked for F1 runtime  
**Pattern gold:** analyst-contract A.6 (`AnalystSchemaInvalidError` + orchestrator notify)

## D1 — English identifiers + EvaluationProfile 7D (locked)

| Field | Decision |
|-------|----------|
| Profile dims | English only: `naturalness`, `precision`, `doctrine`, `consistency`, `safety`, `coverage`, `empathy` |
| Spanish Anexo B names | Docs/prompt text only — **never** rename runtime profile fields |
| Aggregate score | Forbidden: no `score_global` / mean / overall confidence in Evaluator or Decider path (BR-09) |
| Extra fields | `extra="forbid"` on `EvaluationProfile` and `EvaluatorInput` |

**Why:** L1 + AGENTS §5.2. Spanish contract vocabulary must not drift into code identifiers.

**Where:** `src/diana/cognitive/models.py` (`EvaluationProfile`, `EvaluatorInput`).

## D2 — EvaluatorInput shape (B.2)

| Field | Decision |
|-------|----------|
| DTO | Flat `EvaluatorInput(draft, comprehension, included_blocks, current_turn)` |
| Map (docs only) | draft←borrador, comprehension←comprension, included_blocks←bloques_incluidos, current_turn←turno_actual |
| Nested `context_used` | **Not** required at runtime (flat list locked L2) |
| API | `async def evaluate(self, input: EvaluatorInput) -> EvaluationProfile` |
| Sole production caller | Director EVALUATING step |

**Why:** Contrato B.2 with English identifiers; keep surface minimal and forbid knowledge bodies on the DTO.

## D3 — included_blocks = full capability names (L3–L4 / L13)

| Field | Decision |
|-------|----------|
| Semantics | Registry capability **names** whose values passed ContextBuilder **non-null-like** filter and appear as `## Knowledge: {name}` |
| Name form | Full names: `knowledge.history`, `knowledge.policy`, … — **not** short labels (`historial`) |
| Null-like rules | `None`; empty list/dict/tuple/set; empty/whitespace `str` — single source of truth with `ContextBuilder.build` |
| API | `ContextBuilder.list_included_blocks(knowledge)` shares `_is_null_like` |
| Anti-contamination | Messages may carry **names** + draft/turn/public comprehension; **must not** carry knowledge body text or `raw_llm_output` in LLM payload |
| Order | Preserve knowledge-map insertion order (no forced sort) |

**Why:** Evaluator judges draft coherence with what the Generator was given, not raw knowledge correctness. F1 stubs return `None` → typically empty blocks set.

## D4 — Doctrine ~0.7 prompt-only (L7)

| Field | Decision |
|-------|----------|
| When | `"knowledge.policy" not in included_blocks` |
| How | System/user prompt instructs LLM to score **doctrine ≈ 0.7** (neutral-high) |
| Hard-clamp | **Forbidden** in this slice — no post-LLM rewrite of residual doctrine |
| When policy present | Do **not** append neutral-doctrine guidance |

**Why:** Contract B.3 guidance for F1 policy stub (usually null). Calibration failure is a future residual, not a runtime clamp here.

## D5 — B.6 failure path (locked)

| Field | Decision |
|-------|----------|
| Retry | Exactly one retry on schema-class failure (`_MAX_ATTEMPTS = 2`); same messages |
| Schema-class set | `ValidationError`, `ValueError`, `TimeoutError`, type name containing `"Timeout"` |
| Exhaustion | Raise `EvaluatorSchemaInvalidError` with stable reason `evaluador_schema_invalido` |
| Non-schema errors | Propagate immediately (no retry, no typed B.6 reason) |
| Synthetic profile | **Never** invent a conservative default `EvaluationProfile` on fail |
| Application | `mark_failed(error="evaluador_schema_invalido")` + owner `notify_info`; no VIP send; notify failures must not mask typed error |
| Cognitive purity | Cognitive Core never imports telegram / behavior / learning |

**Why:** Mirror Analyst A.6. Fail closed so Decider never runs on garbage vectors.

## D6 — Explicit non-decisions (out of scope / deferred)

- No F2 `regenerate` loop; `Decision.action` stays `approve \| escalate` only.
- No Decider matrix rewrite; no `system_config` thresholds in this pool.
- No doctrine hard-clamp (see D4).
- No B.8 `evaluacion_schema_version` until dimensions change.
- No SPEC.md / REQUERIMIENTOS.md full rewrite to Anexo B.
- No alembic / `turns.error` dirty-tree work in this pool (pre-existing residual).
- Optional follow-up: TraceStore snapshot of `included_blocks` for reconstructability.
- Optional DRY: shared `_is_schema_class_failure` helper (Analyst ↔ Evaluator still local copies by design).

## Traceability

- PLAN locked decisions L1–L15  
- Implementation commits: `97eb6fe`, `e14993f`, `ce95f51`, `a07be80`  
- Hardener test-only commit: `8de5069`  
- Final review: effort **4**, rounds **2**, r1 **5** open (all suggestions/nits fixed), r2 **0** open (HARD_ID `c71950cb`)
