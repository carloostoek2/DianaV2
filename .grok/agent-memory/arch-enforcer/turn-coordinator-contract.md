# Arch Audit: turn-coordinator-contract

**Date:** 2026-07-23  
**Auditor:** arch-enforcer  
**Plan:** `.planning/quick/turn-coordinator-contract/PLAN.md`  
**Summary:** `.planning/quick/turn-coordinator-contract/SUMMARY.md`  
**Decisions:** `.planning/quick/turn-coordinator-contract/decisions.md`  
**Impact:** `.grok/agent-memory/impact-analyzer/turn-coordinator-contract.md`  
**Contract:** `docs/contratos_restantes.md` Anexo G (G.1–G.5)  
**Commits:** `87165ed`, `37b996a`, `d504231`  
**Verdict:** PASS WITH NOTES  
**Critical violations:** 0

## Scope audited

Production:
- `src/diana/application/turn_coordinator.py` — `CoordinateResult` / `coordinate` / `coordinate_unlocked` / `_supersede_nonterminal` / G.5 `chat_scope` / VIP wrappers `begin_turn*`
- `src/diana/telegram/middlewares/owner.py` — inject `TurnCoordinator`; business branch `coordinate(..., "owner")`; drop direct `BehaviorCanceller`
- `src/diana/telegram/setup.py` — DI `coordinator=` into `OwnerDetectionMiddleware`

Tests (contract surface):
- `tests/unit/application/test_turn_coordinator.py` — G.3 matrix, concurrent VIP, G.5 timeout, `begin_turn` wrappers
- `tests/unit/telegram/test_owner_mw.py` — business supersede + private no discard

Cross-checks:
- AGENTS.md §3 Application owns turn entry; Telegram thin I/O; §4.1 / §4.5 cancel on new message; §4.4 owner observe; §5.4 BehaviorCanceller only; §6.5 middleware order
- Application import purity (no aiogram)
- No `src/diana/cognitive/**` edits; no alembic versions from this item
- Dirty-tree residual left untouched (SUMMARY)

## Evidence

| Check | Result |
|-------|--------|
| G.1 single question / no LLM / no draft / no Decision | **PASS** — module docstring + coordinate only supersede/create/discard; no LLM/generate imports |
| G.2 English surface | **PASS** — `coordinate(chat_id, autor, …) → CoordinateResult(action, turn_id)`; actions `create\|replace\|discard_owner_message`; Spanish map in docstring only |
| G.3.1 owner + nonterminal | **PASS** — supersede all, `superseded_by=None`, cancel_pending `"owner_message"`, cancel waiting approvals, no create |
| G.3 owner idle (L1b) | **PASS** — always `discard_owner_message`; zero turn rows |
| G.3.2 VIP replace | **PASS** — prior nonterminal → replace + `superseded_by=new_id` + cancel reason `"new_message"` |
| G.3.3 VIP create | **PASS** — idle → create `received` |
| Invalid `autor` | **PASS** — `ValueError` (loud); no silent path |
| G.4 in-process | **PASS** — same `ChatLockProvider` / `chat_scope`; concurrent VIP tests keep one nonterminal |
| G.5 F1 lock timeout | **PASS** — timeout + retries + `logger.error("chat_lock_timeout")` + raise `ChatLockTimeoutError`; no enqueue (residual); no silent success |
| L4 VIP wrappers | **PASS** — `begin_turn` / `begin_turn_unlocked` route to VIP `coordinate*` and return `TurnRecord` |
| Owner MW (L6) | **PASS** — business + owner → `coordinate(..., "owner")` then stop; no direct `cancel_pending` |
| Private owner (R6) | **PASS** — no business_connection → pass-through; no supersede of VIP chat |
| Cascade via BehaviorCanceller port only | **PASS** — coordinator owns cascade; Behavior never generates/decides |
| Layers | **PASS** — application owns entry; telegram thin caller; cognitive untouched; learning not invoked from coordinator |
| Middleware order §6.5 | **PASS** — Logging → BC → Owner → Forbidden → Auth; setup registration order unchanged |
| Orchestrator full-pipeline lock | **PASS (residual R5)** — not shortened; still `async with chat_scope` for VIP use-case |
| Scope vs PLAN | **PASS** — production files = coordinator + owner MW + setup; no Behavior deliver / Registry / Learning / cognitive / alembic |
| Logging | **PASS** — `coordinate_result`, `turn_begun`, `turn_superseded`, `supersede_cascade`, `chat_lock_timeout`, `owner_business_observed` (+ action) |
| Tests vs PLAN contracts | **PASS** — required G.3 / G.5 / owner MW cases present; FakeCanceller + InMemory stores (no mocked matrix) |

## Findings

### Critical (must fix before advance)

_None._

### Medium

_None that block advance._

### Observations

1. **Multi-process G.4 + durable G.5 requeue remain residuals** — correctly documented in module docstring and decisions.md; F1 single-worker OK. Do not treat in-process lock as multi-worker safety.
2. **Owner MW with `chat_id is None`** — still stops pipeline (`return None`) without calling `coordinate`. Edge Telegram payload; not a contract matrix hole; optional harden later.
3. **`begin_turn` re-fetches after create** — wrapper does `coordinate` then `_turns.get`; correct but redundant vs returning the create record. Style/perf only.
4. **Invalid `autor` raises but no dedicated unit test** — production path is correct; test-guardian may optionally add assert.
5. **`docs/MVP_COMPONENT_DESIGN` still may describe owner cancel_pending-only / begin_turn-only** — documentador residual (SUMMARY); not scope creep.
6. **Orchestrator full critical-section retained** — intentional zombie-pipeline guard (impact R5 / PLAN out); not a violation.

## Compliance Checklist

- [x] Capas respetadas (Application owns turn entry; Telegram thin; Cognitive ↛ telegram/behavior; Behavior only cancel port)
- [x] Scope del PLAN respetado (no cognitive / alembic / deliver / Registry / Learning / multi-process FOR UPDATE)
- [x] Logging adecuado (coordinate_result, supersede cascade, chat_lock_timeout, owner_business_observed)
- [x] G.1 concurrency guard only (no LLM / no draft / no Decision.action)
- [x] G.2 English `create|replace|discard_owner_message` + optional `turn_id`
- [x] G.3 matrix under lock (owner never creates; VIP create/replace; superseded_by rules)
- [x] G.4 in-process one nonterminal per chat
- [x] G.5 loud fail on lock timeout (no silent drop)
- [x] REQ-VIP-06 / §4.5 cascade on replace + owner discard
- [x] Owner private path does not discard VIP turns
- [x] Middleware order unchanged (Freeze absent F1)
- [x] `begin_turn*` VIP wrappers preserve call-site compatibility
- [x] No Decision score collapse / Director non-determinism introduced (cognitive untouched)

## Handoff

**Verdict:** PASS WITH NOTES · **Critical:** 0  

**Next agent:** `test-guardian` for `turn-coordinator-contract`  

**Do not** return to executor — no architectural fixes required.
