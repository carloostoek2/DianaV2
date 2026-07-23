# turn-coordinator-contract — SUMMARY

## Objective

Align `TurnCoordinator` to Anexo G as a concurrency guard: under per-`chat_id` lock, decide `create | replace | discard_owner_message`, keep at most one non-terminal Turn per chat, wire owner business middleware through coordinator supersede.

## Tasks completed

| Task | Result | Commit |
|------|--------|--------|
| 1 TDD tests G.3 + G.5 + owner MW (red) | Tests locked matrix; collection red on missing symbols | `87165ed` `test(application): lock G.3 coordinate matrix for TurnCoordinator` |
| 2 Implement `coordinate` + cascade + G.5 + VIP wrappers | 17 coordinator unit tests green | `37b996a` `feat(application): coordinate G.3 matrix + lock timeout` |
| 3 Wire owner MW + setup DI + regression | Owner business → coordinate; 70 related tests green | `d504231` `fix(telegram): owner MW supersede via TurnCoordinator` |
| 4 Full unit gate | `tests/unit` green | (no extra code commit) |

## Files changed

- `src/diana/application/turn_coordinator.py` — `CoordinateResult`, `coordinate`/`coordinate_unlocked`, `_supersede_nonterminal`, G.5 lock timeout, VIP wrappers, docstring map + residuals
- `src/diana/telegram/middlewares/owner.py` — inject `TurnCoordinator`; business branch `coordinate(..., "owner")`
- `src/diana/telegram/setup.py` — DI `coordinator=` into owner MW
- `tests/unit/application/test_turn_coordinator.py` — G.3 matrix + concurrent + G.5
- `tests/unit/telegram/test_owner_mw.py` — supersede pending_approval; private no discard

## Deviations

None material. Owner idle still returns `discard_owner_message` without calling `cancel_pending` (cascade only when priors exist) — matches PLAN A6 optional no-op.

## Verifications

```text
.venv/bin/python -m pytest -q tests/unit/application/test_turn_coordinator.py
# 17 passed

.venv/bin/python -m pytest -q \
  tests/unit/application/test_turn_coordinator.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/telegram/test_owner_mw.py \
  tests/unit/telegram/test_middleware_stack.py \
  tests/unit/application/test_deterministic_escalate.py \
  tests/unit/application/test_admin_service.py \
  tests/unit/application/test_admin_owner_escalate.py \
  tests/unit/test_composition_wiring.py \
  tests/unit/acceptance/test_tac_mvp_f1.py
# 70 passed

.venv/bin/python -m pytest -q tests/unit
# 414 passed
```

- No files under `src/diana/cognitive/**` modified
- No alembic versions added by this item
- Dirty residual (`alembic/versions/002_turns_error.py`, infra turns WIP) left untouched

## Residuals (out of this PR — documented in coordinator docstring)

| Residual | class_sugerida |
|----------|----------------|
| Multi-process G.4 — Postgres `FOR UPDATE` / advisory lock across workers | out-of-scope |
| G.5 durable message requeue/outbox after lock timeout | out-of-scope |
| Shortening orchestrator full-pipeline lock | out-of-scope |
| Doc refresh of `MVP_COMPONENT_DESIGN` begin_turn-only / owner cancel_pending wording | out-of-scope (documentador) |

## Self-Check: PASSED

- [x] Todas las tareas completadas
- [x] Tests del PLAN corridos
- [x] 0 regresiones atribuibles
- [x] Convenciones del proyecto respetadas (application owns entry; telegram thin; English identifiers)

## Next

`arch-enforcer` → `test-guardian` for turn-coordinator-contract.

## Hardener review
- HARD_ID: 44bcfb3e
- Effort: 4
- Rounds: 1
- Open: 0 (CLEAN)
