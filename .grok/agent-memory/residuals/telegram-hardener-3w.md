# Residuals — telegram-hardener-3w

**Pool:** telegram-hardener-3w  
**Closed:** 2026-07-26  
**Status:** pool COMPLETE; residuals deferred / documented only  

**Sources:** item1–4 SUMMARYs under `.planning/quick/telegram-hardener-3w/` · impact/arch notes · user-declared OOS set.

---

## Deferred / out-of-scope (document only)

### Multi-replica shared store (Redis)

| Field | Value |
|-------|--------|
| **Class** | out-of-scope / deferred scale |
| **Why** | Pool locked process-local in-memory dedup, rate-limit, CorrectSession, chat locks, `log_swallowed`. Multi-replica invalidates that model. |
| **Where** | `dedup.py`, `rate_limit.py`, `turn_coordinator.py`, CorrectSession store, `docs/OPS_SINGLE_INSTANCE.md` |
| **Notes** | G.4 Postgres advisory locks also deferred; OPS doc inventories single-instance assumption. |
| **Source** | item2 residuals · item4 residuals A / G.4 |

### Optional health disable env flag

| Field | Value |
|-------|--------|
| **Class** | out-of-scope |
| **Why** | Item2 A8 always-on health with main lifecycle; no disable flag required for DoD. Soft-fail bind already avoids hard crash. |
| **Where** | `main.py`, `config.py`, `health.py` |
| **Source** | item2 SUMMARY residual |

### Full TurnOrchestrator action-branch / god-file split

| Field | Value |
|-------|--------|
| **Class** | out-of-scope |
| **Why** | Item4 PLAN capped extract at `_safe_notify_info` ± typed `_fail_director_typed`; full action-branch split is a larger refactor. |
| **Where** | `src/diana/application/turn_orchestrator.py` |
| **Source** | item4 SUMMARY residual |

### recontact_service fail-soft → `log_swallowed`

| Field | Value |
|-------|--------|
| **Class** | in-scope-followup |
| **Why** | Optional stretch under item4 LOC budget; only TC recontact sites were required. |
| **Where** | `src/diana/application/recontact_service.py` |
| **Source** | item4 SUMMARY residual |

---

## Additional OOS from items (kept for handoff)

| Residual | Class | Source |
|----------|--------|--------|
| CorrectSession cancel on TC supersede cascade | out-of-scope | item4 A11 |
| Health payload swallow counters | out-of-scope | item4 A10 |
| Multi-process chat locks (Postgres advisory) | out-of-scope | item4 / OPS |
| `tp` global pagination vs `/turnos` optional chat filter | out-of-scope (product A9) | item3 |
| `sentence_transformers` missing → embedding unit fails | out-of-scope (env) | item1 |

---

## Suggested next work (not auto-created tickets)

1. **Small follow-up:** wire `recontact_service` fail-soft paths through `log_swallowed`.
2. **Ops / scale pool (when needed):** Redis-backed dedup + rate-limit + distributed chat locks; revisit health bind/disable for multi-host.
3. **Orch maintainability:** full TurnOrchestrator split beyond notify helpers.
4. **Product:** unify `tp` pagination filter with `/turnos` chat filter if desired.

No auto-created implementation items were opened by this documentador pass.
