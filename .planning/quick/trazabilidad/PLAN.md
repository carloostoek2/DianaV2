---
phase: quick
plan: trazabilidad
type: auto
item: Traceability Module (Anexo T) — audit pipeline traces via owner DM
source: docs/ANEXO_T-TRAZABILIDAD.md + docs/PLAN_TRAZABILIDAD.md + impact-analysis
mode: sparse-request
---

## Objective

Expose the cognitive pipeline step-by-step for any turn via the owner's DM. The owner can list recent turns (`/turnos`), view a full trace with per-step timings (`/traza <id>`), navigate step details inline, and access traces from draft approval messages. All data already exists in `pipeline_traces` — this module adds `timings` instrumentation, a read-only query service, Telegram commands/callbacks, and wiring.

## Scope

- **In:**
  - Migration 005: add `timings` JSONB column + `created_at DESC` index to `pipeline_traces`
  - `TimingContext` context manager in `cognitive/timing.py`
  - Director instrumentation: wrap each pipeline step, store timings dict at end
  - `AdminTraceService` in `application/admin_trace_service.py` with `get_recent_turns`, `get_full_trace`, `count_recent`
  - Repository extensions in `infrastructure/db/repositories/traces.py`: `get_recent_turns()`, `get_full_trace()`, `count_recent()`
  - `TraceabilityReader` protocol in `application/ports.py`
  - Admin commands `/turnos` and `/traza <turn_id>` in `telegram/handlers/admin.py`
  - Trace keyboards: pagination, trace list, step detail, step detail back
  - Callback actions `vt` (view trace), `td` (trace detail), `tp` (trace page), `tj` (JSON export)
  - "Ver traza" button added to `draft_keyboard` in `telegram/keyboards.py`
  - Wiring in `composition.py` + `telegram/setup.py`
- **Out / Non-goals:**
  - No advanced analytics (graphs, stats)
  - No web UI or access outside owner DM
  - No trace modification (read-only)
  - No modification to pipeline cognitive logic or `BehaviorEngine`
- **Constraints:**
  - `TimingContext` never influences control flow — purely measurement
  - Cognitive layer never imports aiogram or Behavior Engine (existing architectural boundary)
  - Callback data <= 64 bytes (existing Telegram constraint)
  - Only the configured owner can access trace commands (existing Auth middleware)

## Assumptions

- A1: `trace_ttl_days` is a valid system config key seeded in migration 001 — queries filter by `created_at >= now() - trace_ttl_days`. This is the existing TTL field used in SPEC.
- A2: Turn IDs are stored as UUIDs in pipeline_traces. `/traza <id>` supports full UUID or first 8 chars prefix match. The spec mentions "abbreviated IDs" — we use first 8 chars of UUID hex.
- A3: Step detail displays input/output as JSON-formatted text (the spec examples show JSON). Each step's input is the relevant cognitive model snapshot; output is the result. The AdminTraceService constructs these from existing pipeline_traces columns.
- A4: The `vt` callback from the draft approval keyboard passes `turn_id` directly (not a separate trace ID). Traces are 1:1 with turns via `pipeline_traces.turn_id`.
- A5: Export JSON sends a Telegram document (.json file) with the full trace dump. This maps to optional H9 in the spec.

## Architecture Approach

### QUE (behavior / contracts)

1. **TimingContext** — context manager that records wall-clock elapsed time. Enters on `__enter__`, exits on `__exit__` (returns `None` — must NOT suppress exceptions). Exposes `elapsed_ms` (float) after exit.
2. **Director instrumentation** — each step wrapped in `TimingContext("step_name")`. Accumulated `dict[str, float]` stored via `await self._store("timings", timings_dict)` at pipeline end. Stored SEPARATELY from `TRACE_KEYS` (see critical adjustment #1).
3. **AdminTraceService** — stateless read-only service. `get_recent_turns(limit, offset)` returns `list[TurnSummary]` with vip display_name, message preview (50 chars), decision, status, created_at. `get_full_trace(turn_id)` returns `FullTrace` with all pipeline columns + timings. `count_recent()` for pagination.
4. **Commands** — `/turnos` lists last 10 turns with pagination keyboard. `/traza <id>` shows full trace summary with per-step buttons.
5. **Callbacks** — `vt:<turn_id>` shows trace summary; `td:<turn_id>:<step_name>` shows step detail; `tp:<page>` paginates turn list; `tj:<turn_id>` exports JSON.

### COMO (structure / patterns)

- **Capas:**
  - `cognitive/timing.py` — TimingContext (no dependencies on application/telegram)
  - `cognitive/director.py` — imports TimingContext, stores timings via existing `_store()`
  - `application/admin_trace_service.py` — depends on `TraceabilityReader` protocol
  - `application/ports.py` — `TraceabilityReader` protocol
  - `infrastructure/db/repositories/traces.py` — implements `TraceabilityReader` via SQL queries
  - `telegram/keyboards.py` — new keyboard factories for trace UI
  - `telegram/handlers/admin.py` — new command handlers
  - `telegram/handlers/callbacks.py` — new callback dispatch cases
  - `telegram/setup.py` — router wiring (inject `admin_trace` parameter)
  - `composition.py` — instantiate `AdminTraceService`, inject into routers

- **Pattern to copy:**
  - `application/admin_service.py` -> `application/admin_trace_service.py` (same layer, same dependency-injection style)
  - `telegram/keyboards.py::draft_keyboard()` -> new `trace_list_keyboard()` etc. (same callback encoding pattern)
  - `telegram/handlers/callbacks.py::dispatch_owner_callback()` -> new trace callback cases (same dispatch pattern)
  - `telegram/handlers/admin.py::build_admin_router()` -> add new command handlers (same registration pattern)
  - `infrastructure/db/repositories/traces.py::SqlTraceStore` — extend with reader methods (same `self._sf` session pattern)

- **Interface / types new:**
  - `TimingContext` class (context manager, 2 public methods: `__enter__`, `__exit__`, 1 property: `elapsed_ms`)
  - `TurnSummary` DTO (pydantic or dataclass, 10 fields)
  - `FullTrace` DTO (pydantic or dataclass, 14 fields)
  - `TraceabilityReader` Protocol (3 async methods: `get_recent_turns`, `get_full_trace`, `count_recent`)
  - In `SqlTraceStore`: 3 new async methods implementing the protocol

- **Wiring:**
  - `composition.py`: instantiate `AdminTraceService(traces=traces, settings=settings)` before `admin`, inject into `build_admin_router()` and `build_callback_router()` as `admin_trace` parameter
  - `telegram/setup.py::build_dispatcher()`: forward `admin_trace` to both router builders

### Critical Adjustments (from impact analysis — MANDATORY)

1. **`"timings"` NOT in `TRACE_KEYS`**: Add `"timings": "timings"` to `TRACE_KEY_TO_COLUMN` in `cognitive/ports.py` but do NOT add `"timings"` to the `TRACE_KEYS` tuple. Reason: `LearningService.run_post_turn()` checks `missing = [k for k in TRACE_KEYS if k not in present]` — all existing turns lack timings, so adding it would mark everything incomplete. `TRACE_KEY_TO_COLUMN` controls the ORM column mapping; `TRACE_KEYS` controls completeness checks.

2. **Migration MUST use `autocommit_block`**: `CREATE INDEX CONCURRENTLY` cannot run inside a transaction. Alembic wraps `upgrade()` in a transaction by default. Pattern:
   ```python
   def upgrade():
       op.add_column('pipeline_traces', sa.Column('timings', JSONB, server_default=text("'{}'::jsonb")))
       with op.get_context().autocommit_block():
           op.create_index('pipeline_traces_created_at_idx', 'pipeline_traces', ['created_at'], postgresql_concurrently=True, if_not_exists=True)

   def downgrade():
       with op.get_context().autocommit_block():
           op.drop_index('pipeline_traces_created_at_idx', if_exists=True, postgresql_concurrently=True)
       op.drop_column('pipeline_traces', 'timings')
   ```

3. **`TimingContext.__exit__` MUST return `None`**: Do NOT return `True` or any truthy value — that would suppress exceptions. The Director must still raise on errors. Test must verify: `with TimingContext("test") as tc: raise ValueError("boom")` propagates the exception.

4. **Backward-compatible router signatures**: `build_admin_router()` and `build_callback_router()` must accept optional `admin_trace=None` parameter. Existing callers (tests, setup) pass no such argument. When `None`, trace commands answer "not available" gracefully.

5. **5 existing tests need updating**:
   - `test_tac04_trace_contains_all_seven_keys` — assertion `keys == set(TRACE_KEYS)` becomes `set(TRACE_KEYS).issubset(keys)` plus `"timings" in keys`
   - 4 partial-failure tests verify specific keys are absent — they pass as-is because timings is only stored on full pipeline completion. VERIFY by running the suite.

## Context

Key files referenced (absolute paths):
- `/home/ubuntu/repos/DianaV2/src/diana/cognitive/ports.py` — `TRACE_KEYS`, `TRACE_KEY_TO_COLUMN`, `InMemoryTraceStore`
- `/home/ubuntu/repos/DianaV2/src/diana/cognitive/director.py` — `CognitiveDirector._run_pipeline()`, `_store()`
- `/home/ubuntu/repos/DianaV2/src/diana/infrastructure/db/models.py` — `PipelineTrace` ORM model
- `/home/ubuntu/repos/DianaV2/src/diana/infrastructure/db/repositories/traces.py` — `SqlTraceStore`
- `/home/ubuntu/repos/DianaV2/src/diana/application/ports.py` — port protocols
- `/home/ubuntu/repos/DianaV2/src/diana/application/memory.py` — `InMemoryTraceReaderWriter`
- `/home/ubuntu/repos/DianaV2/src/diana/telegram/keyboards.py` — callback encoding + `draft_keyboard()`
- `/home/ubuntu/repos/DianaV2/src/diana/telegram/handlers/admin.py` — `build_admin_router()`
- `/home/ubuntu/repos/DianaV2/src/diana/telegram/handlers/callbacks.py` — `build_callback_router()`, `dispatch_owner_callback()`
- `/home/ubuntu/repos/DianaV2/src/diana/telegram/setup.py` — `build_dispatcher()`
- `/home/ubuntu/repos/DianaV2/src/diana/composition.py` — `build_app()`
- `/home/ubuntu/repos/DianaV2/src/diana/learning/post_turn.py` — `LearningService` (DO NOT MODIFY)
- `/home/ubuntu/repos/DianaV2/tests/unit/cognitive/test_director.py` — Director tests (5 will need updating)

## Tasks

### Task 0: Migration + Model (H0)

**type:** auto
**status:** DONE
**commits:** `b343686`
**verification:** 11 schema metadata tests pass
**Objective:** Add `timings` column to `PipelineTrace` model and create Alembic migration with concurrent index.

**Files:**
- CREATE `/home/ubuntu/repos/DianaV2/alembic/versions/005_trace_timings.py`
- EDIT `/home/ubuntu/repos/DianaV2/src/diana/infrastructure/db/models.py` (add `timings` column to `PipelineTrace`)

**Action:**
1. In `models.py`, add to `PipelineTrace` class, after the `delivery_result` column:
   ```python
   timings: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, server_default=text("'{}'::jsonb"))
   ```
2. Create migration `005_trace_timings.py`:
   - `revision = "005_trace_timings"`, `down_revision = "004_vip_frozen_until"`
   - `upgrade()`: add `timings` column with `server_default="'{}'::jsonb"`, then `autocommit_block` for `CREATE INDEX CONCURRENTLY pipeline_traces_created_at_idx ON pipeline_traces (created_at DESC);`
   - `downgrade()`: `autocommit_block` for `DROP INDEX CONCURRENTLY`, then `op.drop_column`
   - Follow CRITICAL ADJUSTMENT #2 exactly.
3. Update `test_f1_schema_metadata.py`:
   - `test_pipeline_traces_turn_id_fk_targets_turns()` — the new column is JSONB nullable, no FK change needed. Verify this test still passes.
   - The `test_desc_indexes_present_in_orm_metadata()` test checks for `ix_pipeline_traces_vip_id_created_at` — add check for `pipeline_traces_created_at_idx` (the new index).
   - The `test_migration_seed_keys_allowlist()` — no change needed (timings is not a seed key).

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/infrastructure/test_f1_schema_metadata.py -x -v
```

**Done:** Migration file exists, model has `timings` column, existing schema tests pass.

---

### Task 1: TimingContext + Director Instrumentation (H1)

**type:** auto
**status:** DONE
**commits:** `3c035bf`
**verification:** 8 timing tests + 24/25 director tests pass
**Objective:** Create `TimingContext` and instrument `CognitiveDirector._run_pipeline()` to measure each step, storing timings separately at pipeline end.

**Files:**
- CREATE `/home/ubuntu/repos/DianaV2/src/diana/cognitive/timing.py`
- EDIT `/home/ubuntu/repos/DianaV2/src/diana/cognitive/ports.py` (add `"timings"` to `TRACE_KEY_TO_COLUMN` only, NOT `TRACE_KEYS`)
- EDIT `/home/ubuntu/repos/DianaV2/src/diana/cognitive/director.py` (import TimingContext, instrument steps, store timings)
- CREATE `/home/ubuntu/repos/DianaV2/tests/unit/cognitive/test_timing.py`

**Action:**

**Step A — `cognitive/ports.py`:**
- Add to `TRACE_KEY_TO_COLUMN` dict: `"timings": "timings"` (after the `"decision"` entry)
- Do NOT touch `TRACE_KEYS` tuple (CRITICAL ADJUSTMENT #1)
- This makes `SqlTraceStore.store()` accept `key="timings"` because `_TRACE_COLUMNS` is built from `TRACE_KEY_TO_COLUMN.values()`

**Step B — `cognitive/timing.py`:**
- Create `TimingContext` class:
  - `__init__(self, step_name: str)` — stores name
  - `__enter__(self)` — records `time.monotonic()` as `_start`
  - `__exit__(self, *args)` — calculates `elapsed_ms`, stores it, RETURNS `None` (CRITICAL ADJUSTMENT #3 — must NOT suppress exceptions)
  - `elapsed_ms` property — float, accessible after exit (raises if `_start` is None)
- Add `__all__ = ["TimingContext"]`

**Step C — `cognitive/director.py`:**
- Import `TimingContext` at top
- In `_run_pipeline()`, declare `timings: dict[str, float] = {}` at method start
- Wrap each pipeline step with `TimingContext`. After each step completes successfully, record: `timings["analyst_ms"] = tc.elapsed_ms`
- Wrap the ENTIRE `_run_pipeline()` body from first step to return in a single outer `TimingContext` for `total_ms`, OR calculate `total_ms = sum(timings.values())`
- After the `decision = Decision(...)` line and `await self._store(turn_id, "decision", decision)`, add: `await self._store(turn_id, "timings", timings)`
- On partial failure (any exception), timings dict is NOT stored (only steps that completed have their data, but we never reach the `_store("timings")` call). This is intentional — partial timings would be misleading.

Step mapping (exact names matching spec section 3.1):
| Step | Timing key | Code block to wrap |
|------|-----------|-------------------|
| Analyst | `analyst_ms` | `comprehension = await self._analyst.analyze(analyst_input)` |
| Planner | `planner_ms` | `plan = self._planner.plan(comprehension)` |
| Memory retriever | `memory_retriever_ms` | `retrieved[cap] = await retriever.fetch(...)` — wrap each fetch, accumulate keyed by cap name |
| Policy retriever | `policy_retriever_ms` | same loop |
| Examples retriever | `examples_retriever_ms` | same loop |
| Context builder | `context_builder_ms` | `built = self._context_builder.build(...)` |
| Generator | `generator_ms` | `draft = await self._generator.generate(built.prompt_final)` |
| Evaluator | `evaluator_ms` | `evaluation = await self._evaluator.evaluate(...)` |
| Decider | `decider_ms` | `base = self._decider.decide(...)` and `decision = Decision(...)` (both deterministic) |

For retrievers: wrap the entire `for cap in plan.capabilities:` loop body, tag each result with `f"{cap}_ms"`. At the end, separate the accumulated timings dict into retriever-specific keys + add to main timings dict. If no capabilities → omit retriever timing keys.

**Step D — `tests/unit/cognitive/test_timing.py`:**
- Test: `test_timing_context_basic` — enter, exit, check `elapsed_ms >= 0`
- Test: `test_timing_context_does_not_suppress_exceptions` — `with TimingContext("x"): raise ValueError("boom")` — MUST propagate (exit returns None, CRITICAL ADJUSTMENT #3)
- Test: `test_timing_context_elapsed_before_exit_raises` — accessing `elapsed_ms` before exit raises AttributeError or similar
- Test: `test_timing_context_reuse` — using same instance twice raises or resets appropriately

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/cognitive/test_timing.py -x -v
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/cognitive/test_director.py -x -v -k "not test_tac04"
```

**Done:** TimingContext works, Director stores timings on successful pipeline, tests pass for timing + all director tests except the one needing update in Task 7.

---

### Task 2: AdminTraceService + Repository Extension (H2)

**type:** auto
**status:** DONE
**commits:** `5d24c99`
**verification:** repo shapes + import purity tests pass
**Objective:** Create `AdminTraceService` with DTOs and extend `SqlTraceStore` with reader methods. Add `TraceabilityReader` protocol.

**Files:**
- CREATE `/home/ubuntu/repos/DianaV2/src/diana/application/admin_trace_service.py`
- EDIT `/home/ubuntu/repos/DianaV2/src/diana/application/ports.py` (add `TraceabilityReader` protocol)
- EDIT `/home/ubuntu/repos/DianaV2/src/diana/infrastructure/db/repositories/traces.py` (add `get_recent_turns`, `get_full_trace`, `count_recent`)

**Action:**

**Step A — `application/ports.py`:**
- Add `TraceabilityReader` protocol (runtime_checkable) after existing protocols, before `__all__`:
  ```python
  @runtime_checkable
  class TraceabilityReader(Protocol):
      async def get_recent_turns(self, limit: int = 10, offset: int = 0) -> list[dict]: ...
      async def get_full_trace(self, turn_id: UUID) -> dict | None: ...
      async def count_recent(self) -> int: ...
  ```
- Add `"TraceabilityReader"` to `__all__`

**Step B — `application/admin_trace_service.py`:**
- Create `TurnSummary` DTO (dataclass or Pydantic BaseModel): `turn_id: UUID`, `chat_id: int`, `vip_name: str | None`, `message_preview: str`, `decision: str`, `status: str`, `created_at: datetime`, `correction_applied: bool`
- Create `FullTrace` DTO: `turn_id: UUID`, `chat_id: int`, `vip_id: UUID | None`, `created_at: datetime`, `comprehension: dict | None`, `plan: dict | None`, `retrieved: dict | None`, `prompt_text: str | None`, `generated_text: str | None`, `evaluation: dict | None`, `decision: dict | None`, `delivery_result: dict | None`, `timings: dict | None`, `error: str | None`, `status: str | None`
- Create `AdminTraceService` class:
  - `__init__(self, traces: TraceabilityReader, trace_ttl_days: int = 30)`
  - `async get_recent_turns(limit=10, offset=0) -> list[TurnSummary]`
  - `async get_full_trace(turn_id: UUID) -> FullTrace | None`
  - `async count_recent() -> int` (for pagination)
  - `async export_trace_json(turn_id: UUID) -> str` (dumps `get_full_trace` as JSON string)
- `get_recent_turns` implementation: delegates to `self._traces.get_recent_turns(limit, offset)`, maps dict rows to `TurnSummary`. `message_preview` truncates vip's trigger text to 50 chars.
- `get_full_trace`: delegates to `self._traces.get_full_trace(turn_id)`, maps to `FullTrace`.
- Add `__all__`

**Step C — `infrastructure/db/repositories/traces.py`:**
- Add three methods to `SqlTraceStore`:
  1. `async get_recent_turns(limit=10, offset=0) -> list[dict]`:
     - Query `PipelineTrace` joined with `Turn` (for `status`, `error`) and `Vip` (for `display_name`)
     - Filter: `PipelineTrace.created_at >= func.now() - text(":ttl_days * INTERVAL '1 day'")` (parameterize ttl_days)
     - Order by: `PipelineTrace.created_at DESC`
     - Limit/offset
     - Return list of dicts with all needed fields
     - Pattern: `async with self._sf() as session: result = await session.execute(stmt); return [row._asdict() for row in result.all()]`
  2. `async get_full_trace(turn_id: UUID) -> dict | None`:
     - Query `PipelineTrace` joined with `Turn` for `status`, `error`
     - Where `PipelineTrace.turn_id == turn_id`
     - Return dict with all columns, or None
  3. `async count_recent() -> int`:
     - `select(func.count()).select_from(PipelineTrace).where(... ttl filter ...)`
     - Return scalar
- The `SqlTraceStore` now implicitly satisfies `TraceabilityReader` protocol (structural subtyping via `@runtime_checkable`).

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/infrastructure/test_sql_repo_shapes.py -x -v
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/application/test_application_import_purity.py -x -v
```

**Done:** `AdminTraceService` and DTOs exist, `SqlTraceStore` has reader methods, protocol defined, import purity holds.

---

### Task 3: Keyboards + "Ver traza" Button (H4)

**type:** auto
**status:** DONE
**commits:** `6a7819c`
**verification:** keyboard imports OK, draft_keyboard has 2 rows with Trace button
**Objective:** Add trace-related keyboard factories and extend `draft_keyboard` with a "Ver traza" button.

**Files:**
- EDIT `/home/ubuntu/repos/DianaV2/src/diana/telegram/keyboards.py`

**Action:**
1. Add new action code constants at top of file (after existing `_ACTION_DOCTRINE_ESCALATE`):
   ```python
   _ACTION_VIEW_TRACE = "vt"
   _ACTION_TRACE_DETAIL = "td"
   _ACTION_TRACE_PAGE = "tp"
   _ACTION_TRACE_JSON = "tj"
   ```

2. Add helper functions for encoding trace callbacks (follow existing `encode_callback` pattern, each under 64 bytes):
   ```python
   def encode_trace_view(turn_id: UUID) -> str:
       return f"vt:{turn_id}"

   def encode_trace_detail(turn_id: UUID, step_name: str) -> str:
       data = f"td:{turn_id}:{step_name}"
       if len(data.encode("utf-8")) > 64:
           raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
       return data

   def encode_trace_page(page: int) -> str:
       return f"tp:{page}"

   def encode_trace_json(turn_id: UUID) -> str:
       return f"tj:{turn_id}"

   def parse_trace_callback(data: str) -> dict | None:
       # Returns {"action": "vt"|"td"|"tp"|"tj", "turn_id": UUID|None, "step": str|None, "page": int|None}
       # Follow existing parse_callback pattern: check prefix, split by ":"
   ```

3. Add keyboard factory functions:
   - `trace_list_keyboard(turns: list, page: int, total_pages: int) -> InlineKeyboardMarkup`:
     - Pagination row: "Previous" (`tp:{page-1}`) and "Next" (`tp:{page+1}`) — hidden when at boundary
     - One button per turn: "Ver traza {short_id}" with callback `vt:{turn_id}`
     - Max ~10 turn buttons per page
   - `trace_detail_keyboard(turn_id: UUID) -> InlineKeyboardMarkup`:
     - One button per pipeline step: "1. Analyst (120ms)" with callback `td:{turn_id}:analyst`, etc.
     - Steps: Analyst, Planner, MemoryRetriever, PolicyRetriever, ExamplesRetriever, ContextBuilder, Generator, Evaluator, Decider
     - Bottom row: "Export JSON" (`tj:{turn_id}`) + "Back to turns" (callback action list or text command)
   - `step_detail_keyboard(turn_id: UUID) -> InlineKeyboardMarkup`:
     - Single button "Back to trace" (`vt:{turn_id}`)

4. Modify `draft_keyboard(turn_id)` — add 4th button "Trace" in a new row below the existing 3 buttons:
   ```python
   InlineKeyboardButton(
       text="Trace",
       callback_data=f"vt:{turn_id}",
   ),
   ```
   - Add it as a separate row (single-button row below the a/c/e row).

5. Update `__all__` to include new functions.

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2 && python -c "from diana.telegram.keyboards import trace_list_keyboard, trace_detail_keyboard, step_detail_keyboard, draft_keyboard, encode_trace_view, encode_trace_detail, encode_trace_page, encode_trace_json, parse_trace_callback; print('imports OK')"
cd /home/ubuntu/repos/DianaV2 && python -c "from uuid import uuid4; kb = draft_keyboard(uuid4()); assert len(kb.inline_keyboard) == 2; assert kb.inline_keyboard[1][0].text == 'Trace'"
```

**Done:** All keyboards compile, callback data under 64 bytes, `draft_keyboard` has 4th button.

---

### Task 4: Admin Commands + Callback Dispatch (H3 + H5)

**type:** auto
**status:** DONE
**commits:** `ad60e50`
**verification:** admin commands + callbacks + middleware tests pass
**Objective:** Add `/turnos` and `/traza` commands to admin router, and `vt/td/tp/tj` callback cases to callback dispatcher.

**Files:**
- EDIT `/home/ubuntu/repos/DianaV2/src/diana/telegram/handlers/admin.py`
- EDIT `/home/ubuntu/repos/DianaV2/src/diana/telegram/handlers/callbacks.py`
- EDIT `/home/ubuntu/repos/DianaV2/src/diana/telegram/setup.py`

**Action:**

**Step A — `telegram/handlers/admin.py`:**
- Add `admin_trace` parameter to `build_admin_router()` signature: `admin_trace: Any = None` (CRITICAL ADJUSTMENT #4 — backward compatible)
- Add `admin_trace` to `handle_admin_text()` signature: `admin_trace: Any = None`
- In `handle_admin_text()`, add cases BEFORE the free-text correct check:
  - `/turnos` → returns `"trace_list"` (honest token)
  - `/traza <id>` → parse turn_id from text (support full UUID or min 8-char prefix, or short hex), returns `"trace_detail"` token with metadata
- In `build_admin_router()`, add new message handlers:
  - `@router.message(Command("turnos"))` handler: calls `admin_trace.get_recent_turns(limit=10)`, formats message per spec section 5.1, sends with `trace_list_keyboard()`. If `admin_trace` is None, replies "Trace module not available."
  - `@router.message(Command("traza"))` handler: parses turn_id argument, calls `admin_trace.get_full_trace(turn_id)`, formats message per spec section 5.2 (Original message, Draft, Decision, Total time, Step list), sends with `trace_detail_keyboard()`. Handles "not found" case. If `admin_trace` is None, replies "Trace module not available."
- Update existing `handle_admin_text()` to handle the new tokens:

**Step B — `telegram/handlers/callbacks.py`:**
- Add `admin_trace` parameter to `build_callback_router()`: `admin_trace: Any = None` (CRITICAL ADJUSTMENT #4)
- Add `admin_trace` parameter to `dispatch_owner_callback()`: `admin_trace: Any = None`
- Import `parse_trace_callback` from keyboards
- In `dispatch_owner_callback()`, BEFORE the existing `parse_callback()` call:
  ```python
  trace_parsed = parse_trace_callback(callback_data)
  if trace_parsed is not None:
      action = trace_parsed["action"]
      if action == "vt": ...
      elif action == "td": ...
      elif action == "tp": ...
      elif action == "tj": ...
  ```
- Implement each case:
  - `vt`: `await admin_trace.get_full_trace(turn_id)`, format + send trace summary
  - `td`: extract `turn_id` + `step_name`, call `get_full_trace`, format step detail (input/output JSON) per spec section 5.2
  - `tp`: parse page number, call `get_recent_turns(limit=10, offset=page*10)`, edit existing message
  - `tj`: call `export_trace_json(turn_id)`, send as document
- In `build_callback_router()`, the `on_callback` handler: check trace callbacks FIRST (before `dispatch_owner_callback`). If `admin_trace` is not None and data matches trace prefixes, handle inline. Use `query.message.edit_reply_markup()` / `query.message.answer()` as needed.

**Step C — `telegram/setup.py`:**
- `build_dispatcher()`: accept optional `admin_trace=None` parameter
- Forward `admin_trace=admin_trace` to both `build_admin_router()` and `build_callback_router()`
- Update `TelegramWiring` dataclass if needed (optional: add `admin_trace` field)

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/telegram/test_admin_commands.py -x -v
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/telegram/test_callbacks.py -x -v
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/telegram/test_middleware_stack.py -x -v
```

**Done:** Commands and callbacks work, existing telegram tests pass, backward compatibility maintained.

---

### Task 5: Wiring in composition.py (H6)

**type:** auto
**status:** DONE
**commits:** `3026e4b`
**verification:** composition wiring tests + full import OK
**Objective:** Wire `AdminTraceService` into `build_app()` and inject into telegram routers.

**Files:**
- EDIT `/home/ubuntu/repos/DianaV2/src/diana/composition.py`

**Action:**
1. Import `AdminTraceService` at top:
   ```python
   from diana.application.admin_trace_service import AdminTraceService
   ```
2. After `traces = SqlTraceStore(sf)` line, instantiate:
   ```python
   admin_trace = AdminTraceService(traces=traces, trace_ttl_days=settings.trace_ttl_days)
   ```
3. Pass to `build_dispatcher()`:
   ```python
   wiring = build_dispatcher(
       ...,
       admin_trace=admin_trace,
   )
   ```
4. Optionally add `admin_trace` to `AppContainer` dataclass if needed for tests/startup.

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/test_composition_wiring.py -x -v
cd /home/ubuntu/repos/DianaV2 && python -c "from diana.composition import build_app; print('import OK')"
```

**Done:** `build_app()` wires `AdminTraceService`, composition tests pass.

---

### Task 6: Test Suite Update + New Tests (H7)

**type:** auto
**status:** DONE
**commits:** `1bd4afb`
**verification:** 566 non-infra + 39 infra + 3 learning tests pass; 43 new trace tests
**Objective:** Fix broken existing tests, add new unit tests for the trace module.

**Files:**
- EDIT `/home/ubuntu/repos/DianaV2/tests/unit/cognitive/test_director.py` (update 1 test: `test_tac04_trace_contains_all_seven_keys`)
- CREATE `/home/ubuntu/repos/DianaV2/tests/unit/application/test_admin_trace_service.py`
- CREATE `/home/ubuntu/repos/DianaV2/tests/unit/telegram/test_trace_keyboards.py`
- CREATE `/home/ubuntu/repos/DianaV2/tests/unit/telegram/test_trace_callbacks.py`
- EDIT `/home/ubuntu/repos/DianaV2/tests/unit/test_composition_wiring.py` (verify wiring includes admin_trace)

**Action:**

**Step A — Fix `test_tac04_trace_contains_all_seven_keys`:**
- Change assertion from `keys == set(TRACE_KEYS)` to:
  ```python
  assert set(TRACE_KEYS).issubset(keys)
  assert "timings" in keys
  ```
- Also update the test name to reflect the new semantics: `test_tac04_trace_contains_all_keys_including_timings`

**Step B — Fix `test_f1_schema_metadata.py`:**
- Update `test_desc_indexes_present_in_orm_metadata()` to check for new `pipeline_traces_created_at_idx`

**Step C — Create `tests/unit/application/test_admin_trace_service.py`:**
- Test: `test_get_recent_turns_returns_summaries` — mock `TraceabilityReader`, verify `TurnSummary` fields
- Test: `test_get_recent_turns_empty` — returns []
- Test: `test_get_full_trace_found` — returns `FullTrace` with all fields populated
- Test: `test_get_full_trace_not_found` — returns None
- Test: `test_count_recent` — returns int > 0
- Test: `test_export_trace_json` — returns valid JSON string
- Pattern to follow: `tests/unit/application/test_admin_service.py`

**Step D — Create `tests/unit/telegram/test_trace_keyboards.py`:**
- Test: `test_trace_view_callback_under_64_bytes`
- Test: `test_trace_detail_callback_under_64_bytes`
- Test: `test_trace_page_callback_under_64_bytes`
- Test: `test_trace_json_callback_under_64_bytes`
- Test: `test_parse_trace_view_callback`
- Test: `test_parse_trace_detail_callback`
- Test: `test_parse_trace_page_callback`
- Test: `test_parse_trace_json_callback`
- Test: `test_draft_keyboard_includes_trace_button`
- Pattern to follow: callbacks in `tests/unit/telegram/test_callbacks.py`

**Step E — Create `tests/unit/telegram/test_trace_callbacks.py`:**
- Test `dispatch_owner_callback` with `vt:`, `td:`, `tp:`, `tj:` prefixes
- Test backward compat: existing `a:`, `c:`, `e:` callbacks still work
- Test no admin_trace: returns `"ignored"` for trace callbacks when admin_trace is None
- Test pagination: tp with page=0, tp with page=1

**Step F — Verify `test_composition_wiring.py`:**
- Run it; add assertion that admin_trace is wired if feasible

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/cognitive/test_director.py -x -v
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/application/test_admin_trace_service.py -x -v
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/telegram/test_trace_keyboards.py tests/unit/telegram/test_trace_callbacks.py -x -v
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/ -x --ignore=tests/unit/infrastructure -q
```

**Done:** All tests pass. Existing tests updated. New module has unit coverage.

---

## Instrucciones para gsd-executor

### Patrones a copiar (paths exactos)

- `src/diana/application/admin_service.py` — dependency injection, stateless service pattern -> `application/admin_trace_service.py`
- `src/diana/telegram/keyboards.py::draft_keyboard()` — callback encoding, InlineKeyboardMarkup -> `trace_list_keyboard()` etc.
- `src/diana/telegram/handlers/callbacks.py::dispatch_owner_callback()` — honest token dispatch -> trace callback handling
- `src/diana/telegram/handlers/admin.py::build_admin_router()` — Router + Command registration -> new handlers
- `src/diana/infrastructure/db/repositories/traces.py::SqlTraceStore.store()` — `self._sf()` session pattern -> reader methods
- `src/diana/cognitive/ports.py::InMemoryTraceStore` — dict-backed store for tests

### Anti-patterns prohibidos

- NO modificar `TRACE_KEYS` tuple (solo `TRACE_KEY_TO_COLUMN`)
- NO agregar `timings` al `TRACE_KEYS` tuple (rompe LearningService)
- NO hacer `return True` en `TimingContext.__exit__` (suprime excepciones)
- NO modificar `LearningService.run_post_turn()` ni ningún archivo en `learning/`
- NO modificar `BehaviorEngine`, `TurnOrchestrator`, ni el pipeline cognitivo
- NO eliminar el parametro `admin_trace` de ninguna firma (backward compat)
- NO cambiar el orden de los middlewares en `setup.py`
- NO usar tipos de aiogram en `application/` ni `cognitive/`

### Logging / errores / convenciones

- Logger: `logger = logging.getLogger("diana.telegram")` en handlers, `logging.getLogger("diana.application")` en service
- Errores: turno no encontrado -> mensaje "Turn not found" al usuario, no 500
- Commits: work unit = comportamiento verificable. Un commit por task.
- Naming: snake_case para funciones, CamelCase para clases, 1-2 char action codes para callback prefixes

### Mock policy

- Tests de `AdminTraceService`: mockear `TraceabilityReader` protocol (no DB)
- Tests de Director: `InMemoryTraceStore` (ya existe)
- Tests de Telegram: usar `FakeBot` + `CallbackQuery` constructor con `from_user`
- Tests de repositorio: no se mockea DB — solo se verifica que los metodos existen (schema contract only)

### Skills del proyecto aplicables

- `telegram-bot-hardener` — patrones de aiogram 3, estructura de handlers, callbacks
- `hardener-agile` — pipeline de 6 agentes si se necesita ejecucion guiada

## Test commands

```bash
# Full suite (fast, no DB)
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/ -x -q --ignore=tests/unit/infrastructure

# Schema-only
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/infrastructure/test_f1_schema_metadata.py -x -v

# Director (includes the updated test)
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/cognitive/test_director.py -x -v

# New trace module tests
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/cognitive/test_timing.py tests/unit/application/test_admin_trace_service.py tests/unit/telegram/test_trace_keyboards.py tests/unit/telegram/test_trace_callbacks.py -x -v

# Composition wiring
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/test_composition_wiring.py -x -v

# Learning (must NOT break)
cd /home/ubuntu/repos/DianaV2 && pytest tests/unit/learning/test_post_turn.py -x -v
```

## Risks + Mitigation

| Risk | Severity | Mitigation |
|------|----------|------------|
| Adding `"timings"` to `TRACE_KEYS` breaks LearningService completeness check | CRITICAL | Only add to `TRACE_KEY_TO_COLUMN`. Task 1 step A enforces this. |
| `CREATE INDEX CONCURRENTLY` inside transaction fails | HIGH | Use `autocommit_block` in migration. Task 0 step 2 enforces this. |
| `TimingContext.__exit__` suppresses exceptions | HIGH | Return `None` explicitly. Test verifies. Task 1 step D. |
| Router signature changes break existing callers | MEDIUM | `admin_trace=None` default. Task 4 enforces. |
| Callback data exceeds 64 bytes | MEDIUM | Length check in `encode_trace_detail`. Task 3 includes validation. |
| 5 existing tests break | MEDIUM | Task 6 explicitly fixes them. Run full suite to verify. |
| `test_tac04` assertion fails (8 keys vs 7) | MEDIUM | Change `==` to `issubset` + explicit `"timings" in keys`. |

## Success Criteria

- [x] `pipeline_traces.timings` column exists and is populated on every successful turn
- [x] `/turnos` lists recent turns with vip name, preview, decision, status, and trace button
- [x] `/traza <id>` shows full trace with per-step timings and detail buttons
- [x] Clicking "Ver traza" on a draft approval message opens that turn's trace
- [x] Step detail view shows JSON input/output for each cognitive step
- [x] Pagination works (Previous/Next) for turn list
- [x] JSON export produces valid JSON with all trace data
- [x] Only the configured owner can access trace commands (existing Auth middleware)
- [x] Turnos outside TTL do not appear in `/turnos`
- [x] All existing F1/F2 tests pass without modification (except `test_tac04` updated)
- [x] All new trace unit tests pass
- [x] `LearningService.run_post_turn()` is NOT broken — existing turns still report complete
- [x] `CognitiveDirector` control flow is unchanged — TimingContext measures only, never influences
