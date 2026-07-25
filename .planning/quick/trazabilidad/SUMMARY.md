# Traceability Module (Anexo T) — SUMMARY

**Pool:** trazabilidad (single-item auto pool)
**Source:** `docs/ANEXO_T-TRAZABILIDAD.md` + `.planning/quick/trazabilidad/PLAN.md`
**Dates:** 2026-07-25
**Type:** Feature GSD -- read-only traceability system via owner DM
**Final unit gate:** 566 passed (non-infrastructure)

## What Was Built

A read-only traceability system that exposes the cognitive pipeline step-by-step for any turn via the owner's Telegram DM. All data already existed in `pipeline_traces` -- this module adds timing instrumentation, a read-only query service, Telegram commands/callbacks, and wiring.

### 10 commits across the full pipeline

| # | Commit | Area |
|---|--------|------|
| 1 | `b343686` feat(trace): add timings JSONB column and concurrent index to pipeline_traces | DB migration + model |
| 2 | `3c035bf` feat(trace): add TimingContext and instrument cognitive pipeline steps | TimingContext + Director |
| 3 | `5d24c99` feat(trace): add AdminTraceService, TraceabilityReader protocol, and SqlTraceStore reader methods | Service + protocol + repo |
| 4 | `6a7819c` feat(trace): add trace keyboards and Trace button to draft_keyboard | Keyboards |
| 5 | `ad60e50` feat(trace): add turnos/traza commands, trace callback dispatch, and setup wiring | Commands + callbacks + setup |
| 6 | `3026e4b` feat(trace): wire AdminTraceService in composition root | Composition |
| 7 | `1bd4afb` feat(trace): add trace unit tests, fix existing tests for timings | 43 new tests |
| 8 | `a6edef5` chore(trace): clean up imports in callbacks.py | Hygiene |
| 9 | 6 fix commits across 2 review rounds | Fix rounds |
| 10 | Total: 17 commits in branch | |

### Components

- **DB Migration 005** (`alembic/versions/005_trace_timings.py`): Adds `timings JSONB` column with `server_default="'{}'::jsonb"`. Concurrent DESC index `pipeline_traces_created_at_idx` via `autocommit_block`.
- **TimingContext** (`cognitive/timing.py`): Context manager, records wall-clock elapsed time, returns `None` from `__exit__` (does NOT suppress exceptions). Exposes `elapsed_ms` float.
- **Director instrumentation** (`cognitive/director.py`): 9 timing keys (analyst_ms, planner_ms, memory_retriever_ms, policy_retriever_ms, examples_retriever_ms, context_builder_ms, generator_ms, evaluator_ms, decider_ms). Stored via `_store("timings", timings)` at pipeline end.
- **TraceabilityReader protocol** (`application/ports.py`): `@runtime_checkable` protocol with `get_recent_turns`, `get_full_trace`, `count_recent`.
- **AdminTraceService** (`application/admin_trace_service.py`): Stateless read-only service. `TurnSummary` and `FullTrace` DTOs. `export_trace_json()` method.
- **SqlTraceStore reader methods** (`infrastructure/db/repositories/traces.py`): `get_recent_turns()` (JOIN Turn + Vip, TTL filter, DESC, limit/offset), `get_full_trace()` (all columns + Turn status/error), `count_recent()`.
- **Keyboards** (`telegram/keyboards.py`): `trace_list_keyboard()`, `trace_detail_keyboard()`, `step_detail_keyboard()`. Trace button in `draft_keyboard`.
- **Commands**: `/turnos` (list recent turns with pagination), `/traza <id>` (full trace with per-step buttons).
- **Callbacks**: `vt` (view trace), `td` (step detail), `tp` (pagination), `tj` (JSON export). `TraceCallbackData` typed dataclass. Owner auth on all.
- **Wiring**: Backward-compatible `admin_trace=None` signatures.

### 43 new unit tests

- `tests/unit/cognitive/test_timing.py` -- 8 tests
- `tests/unit/application/test_admin_trace_service.py` -- 5 tests
- `tests/unit/telegram/test_trace_keyboards.py` -- 9 tests
- `tests/unit/telegram/test_trace_callbacks.py` -- 21 tests

## Architecture Decisions

1. **`"timings"` NOT in `TRACE_KEYS`** -- Added to `TRACE_KEY_TO_COLUMN` only. Prevents `LearningService.run_post_turn()` completeness check from marking existing turns incomplete.
2. **Migration uses `autocommit_block`** -- `CREATE INDEX CONCURRENTLY` cannot run inside a transaction.
3. **`TimingContext.__exit__` returns `None`** -- Does NOT suppress exceptions.
4. **Backward-compatible router signatures** -- `build_admin_router()` and `build_callback_router()` accept optional `admin_trace=None`.
5. **TraceCallbackData typed dataclass** -- Replaced raw dict for callback parsing.
6. **Owner auth enforced on all trace callbacks** -- Via existing `dispatch_owner_callback` gate.

## Review Stats

| Metric | Value |
|--------|--------|
| Effort level | 5 |
| Reviewers | 6 (3 general + security + plan + tests) |
| Review rounds | 2 + wontfix resolution |
| Round 1 issues | 39 total (7 bugs, 5 suggestions, 5 nits, 22 deferred) |
| Round 2 issues | All fixed or wontfix -- 0 open |
| Final review state | CLEAN |

## Residuals (Deferred / Out-of-Scope)

| Residual | Class | Origin |
|----------|-------|--------|
| Per-retriever data filtering in step detail | deferred | Requires schema changes |
| Unique constraint on pipeline_traces.turn_id | deferred | Pre-existing F1 |
| ContextBuilder input/output display improvement | deferred | Beyond minimal viable trace |
| _ensure_row warning on missing turn | deferred | Edge case on concurrent deletion |
| Doctrine callbacks missing owner auth | out-of-scope | Pre-existing F2 issue |

## Verification

- 566 unit tests passing (non-infrastructure)
- 11 F1 schema metadata tests passing
- 43 new trace-specific tests passing
- 0 regressions attributed to this module
- Architectural enforcer: PASS WITH NOTES (0 critical)
- Test guardian: suite protege adecuadamente
- LearningService.run_post_turn() NOT broken
- CognitiveDirector control flow unchanged (TimingContext measures only)

## Key Files Changed

**7 new:** `cognitive/timing.py`, `application/admin_trace_service.py`, `alembic/versions/005_trace_timings.py`, 4 test files
**12 edited:** `models.py`, `cognitive/ports.py`, `director.py`, `application/ports.py`, `traces.py`, `keyboards.py`, `admin.py`, `callbacks.py`, `setup.py`, `composition.py`, `test_director.py`, `test_f1_schema_metadata.py`
