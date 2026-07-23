# decider-contract — SUMMARY

**Phase/plan:** quick / decider-contract  
**Status:** complete  
**Commit:** `4e1db5a` — `feat(cognitive): lock Decider F1 matrix + mode_restriction audit`

## Tasks completed

| Task | Result | Commit |
|------|--------|--------|
| Task 1 — TDD residual naturalness + mode_restriction locks | Tests added (red on field until Task 2) | same work-unit |
| Task 2 — Decision field + Decider matrix audit + Director passthrough + docstring | Green full primary suite | `4e1db5a` |

## What changed

- **`Decision.mode_restriction_applied: str | None = None`** — optional audit field (Anexo F `restriccion_de_modo_aplicada`)
- **Decider matrix** unchanged order: safety → risk alto → approve; sets `supervised_send_to_approve` only on supervised approve
- **Director** copies `mode_restriction_applied` when rebuilding Decision with draft
- **Docstring** maps English ↔ Anexo F; residual F.3 #2 explicit (naturalness fall-through approve)
- **Tests** lock residual naturalness, mode_restriction semantics, default None on Decision

## Deviations

None. Scope stayed inside PLAN locks L1–L8.

## Verifications run

```
tests/unit/cognitive/test_decider.py                              21 passed
tests/unit/cognitive/test_models.py -k Decision                   10 passed
tests/unit/cognitive/test_director.py -k escalate|approve|…        4 passed
tests/unit/cognitive/test_import_purity.py                         1 passed
tests/unit/cognitive/test_evaluation_profile_invariants.py        11 passed
tests/unit/application/test_turn_orchestrator.py -k approve|…      5 passed
tests/unit/acceptance/test_tac_mvp_f1.py                           8 passed
```

## Success criteria

- [x] Decider pure deterministic; zero LLM
- [x] `Decision.action` exactly `approve | escalate`
- [x] Safety / risk / approve matrix locked
- [x] Low naturalness alone does not change action
- [x] Supervised approve sets `mode_restriction_applied == "supervised_send_to_approve"`
- [x] Director preserves field with draft
- [x] Reason tokens unchanged
- [x] Primary pytest green
- [x] No-touch list respected
- [x] Import purity + evaluation profile invariants green

## Residuals (not implemented — intentional)

- **F.3 rule 2 naturalness→regenerate** deferred (F1 fall-through = approve). Class: out-of-scope / future F2+.
- **Composition wire of `eval_thresholds`** deferred (L6). Class: in-scope-followup ops later.

## Dirty tree

Pre-existing WIP left untouched (infra models/repos, alembic, agent-memory, etc.). No residual from this slice left uncommitted.

## Self-Check: PASSED

- [x] All tasks completed
- [x] Tests of PLAN run
- [x] 0 regressions attributable
- [x] Project conventions respected

## Next agent

**gsd-arch-enforcer** for `decider-contract` (post-implementation architecture lock / review).
