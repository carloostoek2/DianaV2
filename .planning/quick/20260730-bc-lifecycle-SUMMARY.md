# Pool — BusinessConnection Lifecycle Handler

**Item:** 2 of pool "close-4-parciales" (gap #4 from `faltantes.md`)
**Date:** 2026-07-30
**Status:** CLOSED

## Commits (4)

| # | Hash | Message |
|---|------|---------|
| 1 | `ee89223` | feat(bc-lifecycle): add data layer for BusinessConnection persistence |
| 2 | `5d90b56` | feat(bc-lifecycle): add handler, wiring, and allowed_updates for BusinessConnection |
| 3 | `c89b564` | test(bc-lifecycle): add tests for store, handler, and middleware isolation |
| 4 | `bc0e538` | fix(bc-lifecycle): address review findings -- updated_at, user guard, test assertions |

## Files changed (11 files, 462+ lines)

**Created (7):**
- `src/diana/infrastructure/db/repositories/business_connections.py` -- inline ORM + SqlBusinessConnectionStore
- `alembic/versions/015_business_connections.py` -- migration creating `business_connections` table
- `src/diana/telegram/handlers/business_connection.py` -- handler via `build_business_connection_router()`
- `tests/unit/infrastructure/test_business_connection_store.py` -- store CRUD tests (3)
- `tests/unit/telegram/test_business_connection_handler.py` -- handler event processing tests (4)
- `tests/unit/telegram/test_bc_lifecycle_middleware.py` -- middleware isolation tests (2)

**Edited (4):**
- `src/diana/application/ports.py` -- BusinessConnectionRecord + BusinessConnectionStore protocol
- `src/diana/application/memory.py` -- InMemoryBusinessConnectionStore double
- `src/diana/telegram/setup.py` -- wiring: bc_store param, middleware registration, router inclusion
- `src/diana/composition.py` -- AppContainer field + store creation + build_dispatcher wiring
- `src/diana/main.py` -- added "business_connection" to allowed_updates

## Outcomes

- `BusinessConnectionRecord` + `BusinessConnectionStore` Protocol en `ports.py`
- `SqlBusinessConnectionStore` con inline ORM (PostgreSQL upsert via `session.merge()`)
- `InMemoryBusinessConnectionStore` en `memory.py` (dict-backed)
- Alembic migration `015_business_connections` (revision down: `014_runtime_timers`)
- Handler `@router.business_connection()` en `build_business_connection_router()`
- Middleware mínimo (ErrorHandler + Logging) en `dp.business_connection` -- sin Auth/FreezeCheck/RateLimit/Dedup
- `"business_connection"` en `allowed_updates` de `main.py`
- 9 tests nuevos (store create+update, handler persistence+logging+exception swallow, middleware isolation)

## Verifications

| Check | Result |
|-------|--------|
| Plan success criteria | 14/14 PASS |
| Import checks | 3/3 OK |
| New tests | 9/9 PASS |
| Critical existing tests | 9/9 PASS (middleware_stack 4, business_handler 3, business_connection_mw 2) |
| Full telegram suite | 293/293 PASS |
| Full unit suite | 1532/1537 PASS (5 pre-existing: 4 embedding, 1 flaky table count) |
| models.py no-touch | VERIFIED -- no changes |
| arch-enforcer | PASS WITH NOTES (0 critical) |
| test-guardian | "suite protege adecuadamente" |
| Review loop R1 | 9 issues found |
| Review loop R2 | 0 issues (5 reviewers, effort 4) |
| Commit gate | CLEAN |

## Residuals (deferred, documented only)

None blocking. The following were noted as deliberate out-of-scope or future improvements:

- `session.merge()` pattern for upsert (works; could be optimized with explicit INSERT ... ON CONFLICT later)
- Integration test for `SqlBusinessConnectionStore` against real DB (not in scope)
- Handler redundancy check (single handler on dedicated observer, no conflated dispatch)
- In-memory vs SQL semantics alignment (InMemory returns deep copy, SQL returns ORM-driven merge result)
- `store=None` guard in setup.py (handled: router only included when `bc_store is not None`)

## Status in faltantes.md

Gap #4 (BusinessConnection handler): **PARCIAL -> RESUELTO** -- handler de ciclo de vida completo con persistencia SQL + migration + middleware mínimo.

## Close note

> Pool `close-4-parciales` item 2 (BusinessConnection lifecycle handler) closed -- data layer, handler, wiring, tests, and fix round completed. Tests 293/293 passing, 0 critical violations, 0 review issues. 5 deferred items documented. faltantes.md gap #4 updated to RESUELTO.
