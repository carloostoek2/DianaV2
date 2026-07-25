---
phase: quick
plan: trazabilidad-polish
type: auto
item: 3 mejoras de pulido en trazabilidad (fechas relativas, filtro VIP, job purge)
source: user-request
mode: sparse-request
---

## Objective

Apply 3 traceability polish improvements to the completed Anexo T module: (1) replace ISO timestamps with human-friendly relative dates in /turnos and trace detail views, (2) add optional `chat_id` filter parameter to `/turnos` for VIP-specific queries, (3) add a TTL-based background purge job that physically deletes expired pipeline_traces rows.

## Scope

- **In:**
  - Relative date formatting at 4 call sites (2 in admin.py, 2 in callbacks.py)
  - New shared helper `_format_relative_time()` in `telegram/helpers.py`
  - `chat_id: int | None = None` parameter on `get_recent_turns()` and `count_recent()` across all 5 implementors (protocol, SqlTraceStore, AdminTraceService, 2 FakeTraceabilityReaders)
  - Conditional SQL `WHERE chat_id = :chat_id` in SqlTraceStore when provided
  - `/turnos <chat_id>` parsing in the admin command handler
  - New `jobs/trace_purge.py` — `TracePurgeJob` class following `GrayZoneExpirationJob` pattern
  - New `SqlTraceStore.purge_expired(ttl_days=None) -> int` — batched DELETE (LIMIT 1000 per batch)
  - Wiring in `main.py` and `composition.py`
- **Out / Non-goals:**
  - No schema migration (Change 3 is pure DELETE, no DDL)
  - No cognitive/behavior/learning module changes
  - No changes to the callback dispatch mechanism or keyboard encoding
  - No changes to `TraceReader` (the write-side protocol) or trace storage
- **Constraints:**
  - `trace_ttl_days` already exists in `config.py` line 46 (`int, ge=1, default=30`)
  - Clean layer separation: telegram -> application -> infrastructure
  - Jobs use `asyncio.Event` for stop signaling
  - No 0-behavior changes: all 566 existing tests must stay green

## Assumptions

- A1: The chat user's timezone is local (we use `datetime.now()` without tz conversion for relative computation — acceptable because these are owner-only DM commands and the relative labels are "hace X horas/minutos" which don't require precision beyond a few days).
- A2: The `/turnos <chat_id>` syntax uses a bare int after the command (e.g., `/turnos 123456789`). No `--chat-id` flag or other CLI convention — the user request says `/turnos 12345`.
- A3: The purge job uses `settings.trace_ttl_days` (already 30) and runs every 3600 seconds (1 hour) — reasonable cadence for a cleanup job that does not need real-time precision.
- A4: `purge_expired()` returns the total count of deleted rows across all batches. Tests will verify the return value and that expired rows are gone.
- A5: The FakeTraceabilityReader for VIP filter: filtering is done in-memory by matching `chat_id` in each dict's `"chat_id"` key, keeping the fake simple without SQL simulation.

## Architecture Approach

### Change 1: Relative date formatting

**QUÉ:** Replace 4 `strftime()` call sites with a shared helper that produces Spanish relative-time labels. Labels follow: "hace X minutos" (< 60 min), "hace X horas" (< 24h), "ayer a las HH:MM" (< 48h), "hace X dias" (< 7d), "DD/MM/AAAA" (7d+).

**CÓMO:** Create new file `src/diana/telegram/helpers.py` with `_format_relative_time(dt: datetime) -> str`. Import and use at:
- `admin.py` line 183 (turnos list row): replace `t.created_at.strftime("%Y-%m-%d %H:%M")`
- `admin.py` line 221 (/traza detail): replace `trace.created_at.strftime("%Y-%m-%d %H:%M:%S")`
- `callbacks.py` line 246 (vt callback): replace `trace.created_at.strftime("%Y-%m-%d %H:%M:%S")`
- `callbacks.py` line 307 (tp pagination): replace `t.created_at.strftime("%Y-%m-%d %H:%M")`

The helper handles `created_at is None` by returning `""` (matching existing guard pattern).

**Placement:** `telegram/helpers.py` is a new presentation-layer utility. Both `admin.py` and `callbacks.py` are already in `telegram/handlers/`, so importing from `telegram.helpers` is intra-layer and valid.

### Change 2: VIP filter for /turnos

**QUÉ:** Add `chat_id: int | None = None` kwarg to `get_recent_turns()` and `count_recent()` through the full call chain. When provided, filter results to that chat_id only.

**Lock-step implementors (all 5 must change together or tests break with TypeError):**

| # | Class/File | Methods |
|---|-----------|---------|
| 1 | `TraceabilityReader` protocol in `ports.py:381,383` | `get_recent_turns`, `count_recent` |
| 2 | `SqlTraceStore` in `traces.py:80,148` | `get_recent_turns`, `count_recent` |
| 3 | `AdminTraceService` in `admin_trace_service.py:73,89` | `get_recent_turns`, `count_recent` |
| 4 | `FakeTraceabilityReader` in `test_admin_trace_service.py:26,32` | `get_recent_turns`, `count_recent` |
| 5 | `FakeTraceabilityReader` in `test_trace_callbacks.py:36,42` | `get_recent_turns`, `count_recent` |

**SQL change (SqlTraceStore):** When `chat_id is not None`, add `PipelineTrace.chat_id == chat_id` to the WHERE clause. The parameter must be bound safely (SQLAlchemy handles this natively — use `== :chat_id` via `.where(PipelineTrace.chat_id == chat_id)`).

**Command handler change (admin.py):** In `on_turnos`, parse the message text: `parts = (message.text or "").strip().split()` — if `len(parts) >= 2`, attempt `int(parts[1])` to get `filter_chat_id`. Pass it to both `admin_trace.get_recent_turns()` and `admin_trace.count_recent()`. On `ValueError` from int conversion, reply "Usage: /turnos [chat_id]" and return.

**Protocol default values:** Both new params default to `None` — backward compatible, all existing callers work without changes.

### Change 3: TTL purge job

**QUÉ:** A background asyncio job that periodically calls `purge_expired()` on `SqlTraceStore` and physically DELETEs rows from `pipeline_traces` where `created_at < now() - ttl_days`.

**CÓMO — two new pieces + two wiring touchpoints:**

1. **`SqlTraceStore.purge_expired(ttl_days=None) -> int`** (new method in `traces.py`):
   - If `ttl_days` is None, use `self._ttl_days`
   - Compute cutoff: `func.now() - text(":ttl_days * INTERVAL '1 day'")`
   - Batched loop: `while True:` — DELETE with `.limit(1000)`, commit, count rows affected; if 0, break
   - Each batch uses its own session (`self._sf()` context manager) — critical to avoid holding a single session open across batches
   - Return total deleted across all batches

2. **`jobs/trace_purge.py`** — `TracePurgeJob` class:
   - Copy pattern from `jobs/gray_zone_expiration.py` verbatim
   - `__init__(self, trace_store, *, interval_seconds=3600)`: stores `_store` and `_stop_event = asyncio.Event()`
   - `start()`: loop until `_stop_event.is_set()`; call `self._store.purge_expired()`; if deleted > 0, log at INFO with count; else log at DEBUG; wait on `_stop_event.wait()` with timeout=interval_seconds; catch TimeoutError and continue; catch Exception and log
   - `stop()`: set `_stop_event`

3. **Wiring in `main.py`:**
   - Import `TracePurgeJob`
   - Create `_setup_purge_job(app: AppContainer) -> asyncio.Task | None`:
     - Get `SqlTraceStore` from `app` (it's created in `composition.py` as `traces`)
     - BUT: the job needs the store directly. The cleanest way: add `trace_store` to `AppContainer` in composition.py.
   - Actually, looking at the pattern: `GrayZoneExpirationJob` takes a `GrayZoneServicePort` which is available via `app.gray_zone`. For the purge job, `SqlTraceStore` is constructed as `traces = SqlTraceStore(sf, ttl_days=settings.trace_ttl_days)` in composition.py but is NOT stored as a field on AppContainer directly. It's only consumed to build `admin_trace` and `director`.
   - **Solution:** Add `trace_store: SqlTraceStore` field to `AppContainer` dataclass (line 148 area), and set it in `build_app` return (`trace_store=traces`). This is the same pattern as `vips`, `deliveries`, `approvals`, etc.
   - Then `_setup_purge_job(app: AppContainer)` creates `TracePurgeJob(app.trace_store, interval_seconds=3600)` and returns `asyncio.create_task(job.start())`.
   - In `async_main()`: add `purge_job = _setup_purge_job(app)` alongside `expiration_job`; add `purge_job.cancel()` in the finally block.

4. **Wiring in `composition.py`:**
   - `AppContainer` dataclass: add `trace_store: SqlTraceStore` field
   - `build_app()` return statement: add `trace_store=traces` (or whatever the local variable is named — currently it is `traces`)

**Pattern to copy:** `jobs/gray_zone_expiration.py` line-for-line — replace `gray_zone` with `trace_store`, replace `expire_old_queries()` with `purge_expired()`, remove the escalation/notify logic (purge is fire-and-forget; just log the count).

## Context

@files:
- `src/diana/telegram/handlers/admin.py` — /turnos and /traza command handlers (call sites for changes 1 and 2)
- `src/diana/telegram/handlers/callbacks.py` — vt and tp callback handlers (call sites for change 1)
- `src/diana/telegram/helpers.py` — NEW: shared `_format_relative_time()` helper
- `src/diana/application/ports.py` — TraceabilityReader protocol (lines 373-383, change 2)
- `src/diana/application/admin_trace_service.py` — AdminTraceService forwarder (change 2)
- `src/diana/infrastructure/db/repositories/traces.py` — SqlTraceStore (changes 2 and 3)
- `src/diana/jobs/trace_purge.py` — NEW: TracePurgeJob (change 3)
- `src/diana/jobs/gray_zone_expiration.py` — pattern to copy for change 3
- `src/diana/main.py` — wiring for purge job (change 3)
- `src/diana/composition.py` — AppContainer + build_app (change 3)
- `src/diana/config.py` — `trace_ttl_days` already at line 46 (read-only reference)
- `tests/unit/application/test_admin_trace_service.py` — FakeTraceabilityReader #1 (change 2)
- `tests/unit/telegram/test_trace_callbacks.py` — FakeTraceabilityReader #2 (change 2)

## Tasks

### Task 1: Relative date formatting + shared helper

**type:** auto
**Objective:** Replace all 4 ISO strftime() calls with a shared `_format_relative_time()` helper that produces Spanish relative-time labels.

**Files:**
- CREATE `src/diana/telegram/helpers.py`
- EDIT `src/diana/telegram/handlers/admin.py`
- EDIT `src/diana/telegram/handlers/callbacks.py`

**Action:**

1. **Create `src/diana/telegram/helpers.py`:**

```python
"""Shared presentation-layer helpers for Telegram handlers."""

from __future__ import annotations

from datetime import datetime, timezone


def _format_relative_time(dt: datetime | None) -> str:
    """Return a human-friendly relative time label in Spanish.

    Labels:
    - ``hace X minutos``  (< 60 minutes)
    - ``hace X horas``    (< 24 hours)
    - ``ayer a las HH:MM`` (< 48 hours)
    - ``hace X días``     (< 7 days)
    - ``DD/MM/AAAA``      (7+ days, or future/missing)
    """
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = delta.total_seconds()
    if seconds < 0:
        return dt.strftime("%d/%m/%Y")
    minutes = int(seconds // 60)
    if minutes < 1:
        return "hace menos de un minuto"
    if minutes < 60:
        return f"hace {minutes} minuto{'s' if minutes != 1 else ''}"
    hours = minutes // 60
    if hours < 24:
        return f"hace {hours} hora{'s' if hours != 1 else ''}"
    days = hours // 24
    if days == 1:
        return f"ayer a las {dt.strftime('%H:%M')}"
    if days < 7:
        return f"hace {days} días"
    return dt.strftime("%d/%m/%Y")
```

2. **Edit `admin.py`:**
   - Add import: `from diana.telegram.helpers import _format_relative_time`
   - Line 183: Replace `ts = t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else ""` with `ts = _format_relative_time(t.created_at)`
   - Line 221: Replace `ts = trace.created_at.strftime("%Y-%m-%d %H:%M:%S") if trace.created_at else ""` with `ts = _format_relative_time(trace.created_at)`

3. **Edit `callbacks.py`:**
   - Add import: `from diana.telegram.helpers import _format_relative_time`
   - Line 246: Replace `ts = trace.created_at.strftime("%Y-%m-%d %H:%M:%S") if trace.created_at else ""` with `ts = _format_relative_time(trace.created_at)`
   - Line 307: Replace `ts = t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else ""` with `ts = _format_relative_time(t.created_at)`

**Verification:** `cd /home/ubuntu/repos/DianaV2 && python -m pytest tests/unit/telegram/test_admin_commands.py tests/unit/telegram/test_trace_callbacks.py -x -q`

**Done:** All 4 call sites use `_format_relative_time(dt)` instead of `dt.strftime(...)`. Existing tests pass (no test checks timestamp string content).

---

### Task 2: VIP chat_id filter on /turnos

**type:** auto
**Objective:** Add `chat_id: int | None = None` parameter to `get_recent_turns()` and `count_recent()` across all 5 implementors, with conditional SQL filtering, and parse `/turnos <chat_id>` in the command handler.

**Files:**
- EDIT `src/diana/application/ports.py`
- EDIT `src/diana/infrastructure/db/repositories/traces.py`
- EDIT `src/diana/application/admin_trace_service.py`
- EDIT `src/diana/telegram/handlers/admin.py`
- EDIT `tests/unit/application/test_admin_trace_service.py`
- EDIT `tests/unit/telegram/test_trace_callbacks.py`

**Action:**

1. **`ports.py` (TraceabilityReader protocol):**
   - Line 381: Change `async def get_recent_turns(self, limit: int = 10, offset: int = 0) -> list[dict]: ...` to `async def get_recent_turns(self, limit: int = 10, offset: int = 0, chat_id: int | None = None) -> list[dict]: ...`
   - Line 383: Change `async def count_recent(self) -> int: ...` to `async def count_recent(self, chat_id: int | None = None) -> int: ...`

2. **`traces.py` (SqlTraceStore):**
   - `get_recent_turns`: Add `chat_id: int | None = None` parameter. Inside, after `.where(PipelineTrace.created_at >= cutoff)`, add:
     ```python
     if chat_id is not None:
         stmt = stmt.where(PipelineTrace.chat_id == chat_id)
     ```
   - `count_recent`: Add `chat_id: int | None = None` parameter. Same conditional `.where(PipelineTrace.chat_id == chat_id)` after the existing cutoff where clause.

3. **`admin_trace_service.py` (AdminTraceService):**
   - `get_recent_turns`: Add `chat_id: int | None = None` parameter. Pass through to `self._traces.get_recent_turns(limit=limit, offset=offset, chat_id=chat_id)`.
   - `count_recent`: Add `chat_id: int | None = None` parameter. Pass through to `self._traces.count_recent(chat_id=chat_id)`.

4. **`admin.py` (on_turnos handler):**
   - Parse `chat_id` from message text:
     ```python
     filter_chat_id: int | None = None
     parts = (message.text or "").strip().split()
     if len(parts) >= 2:
         try:
             filter_chat_id = int(parts[1])
         except ValueError:
             await message.answer("Usage: /turnos [chat_id]")
             return
     ```
   - Pass `chat_id=filter_chat_id` to both `admin_trace.get_recent_turns(limit=10, offset=0, chat_id=filter_chat_id)` and `admin_trace.count_recent(chat_id=filter_chat_id)`.

5. **`test_admin_trace_service.py` (FakeTraceabilityReader #1):**
   - `get_recent_turns`: Add `chat_id: int | None = None` parameter. If `chat_id is not None`, filter `self._turns` by `r.get("chat_id") == chat_id` before slicing.
   - `count_recent`: Add `chat_id: int | None = None` parameter. If not None, count only rows where `r.get("chat_id") == chat_id`.

6. **`test_trace_callbacks.py` (FakeTraceabilityReader #2):**
   - Same changes as Fake #1: add `chat_id` param to `get_recent_turns` and `count_recent`, with in-memory filtering logic.

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2 && python -m pytest tests/unit/application/test_admin_trace_service.py tests/unit/telegram/test_trace_callbacks.py tests/unit/telegram/test_admin_commands.py -x -q
```

**Done:** All 5 implementors accept `chat_id: int | None = None` on both methods. `/turnos` without args works as before. `/turnos 12345` filters. `/turnos notanumber` shows usage. All existing tests pass.

---

### Task 3: TTL purge method on SqlTraceStore

**type:** auto
**Objective:** Add `purge_expired(ttl_days=None) -> int` to `SqlTraceStore` that deletes expired `pipeline_traces` rows in batches of 1000.

**Files:**
- EDIT `src/diana/infrastructure/db/repositories/traces.py`

**Action:**
Add this method to `SqlTraceStore` (after `count_recent`, before `__all__`):

```python
async def purge_expired(self, ttl_days: int | None = None) -> int:
    """Delete pipeline_traces rows older than TTL, batched.

    Uses LIMIT 1000 per batch with separate sessions to avoid long-lived
    transactions and table locks. Returns total rows deleted.
    """
    days = ttl_days if ttl_days is not None else self._ttl_days
    from sqlalchemy import delete

    cutoff = func.now() - text(":ttl_days * INTERVAL '1 day'")
    total_deleted = 0

    while True:
        async with self._sf() as session:
            stmt = (
                delete(PipelineTrace)
                .where(PipelineTrace.created_at < cutoff)
                .limit(1000)
            )
            stmt = stmt.params(ttl_days=days)
            result = await session.execute(stmt)
            await session.commit()
            batch_count = result.rowcount
            total_deleted += batch_count
            if batch_count < 1000:
                break

    if total_deleted:
        import logging
        _log = logging.getLogger("diana.infrastructure")
        _log.info("purge_expired_complete", extra={"deleted": total_deleted, "ttl_days": days})

    return total_deleted
```

**Verification:** `cd /home/ubuntu/repos/DianaV2 && python -c "from diana.infrastructure.db.repositories.traces import SqlTraceStore; print('import ok')"`

**Done:** `SqlTraceStore` has `purge_expired()` method. Import works.

---

### Task 4: TracePurgeJob + wiring in main.py and composition.py

**type:** auto
**Objective:** Create the background job, wire it into AppContainer and the startup/shutdown lifecycle.

**Files:**
- CREATE `src/diana/jobs/trace_purge.py`
- EDIT `src/diana/composition.py`
- EDIT `src/diana/main.py`

**Action:**

1. **Create `src/diana/jobs/trace_purge.py`:**
   Copy the exact structure of `src/diana/jobs/gray_zone_expiration.py`. Differences:
   - Class name: `TracePurgeJob`
   - Constructor: `__init__(self, trace_store: Any, *, interval_seconds: int = 3600)` — stores `_store`, creates `_stop_event`
   - `start()` method: same loop structure, but call `deleted = await self._store.purge_expired()` instead of `expire_old_queries()`. No escalation/notification logic — just log the deleted count at INFO if > 0, DEBUG if 0.
   - `stop()` method: identical pattern (`self._stop_event.set()`)
   - Keep the same logging, timeout handling, and exception catching patterns.
   - `__all__ = ["TracePurgeJob"]`

2. **Edit `composition.py`:**
   - Add `trace_store: SqlTraceStore` field to `AppContainer` dataclass (after `sandbox`, before or after `admin_trace` — conventional place).
   - In `build_app()` return statement (`AppContainer(...)`): add `trace_store=traces`.
   - Import is already present (`SqlTraceStore` is imported at line 48).

3. **Edit `main.py`:**
   - Add import: `from diana.jobs.trace_purge import TracePurgeJob`
   - Add `_setup_purge_job(app: AppContainer) -> asyncio.Task` function (after `_setup_expiration_job`):
     ```python
     def _setup_purge_job(app: AppContainer) -> asyncio.Task:
         """Start the trace TTL purge background job."""
         job = TracePurgeJob(app.trace_store, interval_seconds=3600)
         task = asyncio.create_task(job.start())
         logger.info("purge_job_started", extra={"interval_seconds": 3600})
         return task
     ```
   - In `async_main()`:
     - Add `purge_job = _setup_purge_job(app)` after `expiration_job = _setup_expiration_job(app)`
     - In the `finally` block, add matching cleanup for `purge_job` (same pattern as `expiration_job` — `.cancel()`, then `asyncio.wait_for` with timeout)

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2 && python -m pytest tests/unit/jobs/ -x -q && python -m pytest tests/unit/telegram/test_telegram_layer_scope.py -x -q
```

**Done:** TracePurgeJob exists, AppContainer carries `trace_store`, main.py starts/stops the purge job. All existing tests pass.

---

## Instrucciones para gsd-executor

### Patrones a copiar (paths)

- **Job pattern:** `src/diana/jobs/gray_zone_expiration.py` — copy the class structure (`__init__`, `start()`, `stop()`) exactly for `trace_purge.py`. The `asyncio.Event` loop, `asyncio.wait_for` on `_stop_event.wait()`, and try/except structure are canon.
- **Wiring pattern (main.py):** `_setup_expiration_job()` at lines 63-77 — copy the `asyncio.create_task(job.start())` + try/finally `cancel()` pattern.
- **Repository pattern:** `SqlTraceStore.get_recent_turns()` (lines 80-110) — copy the `self._sf()` session context, `.params(ttl_days=...)`, and `func.now() - text(...)` cutoff pattern for `purge_expired()`.
- **Fake pattern:** `FakeTraceabilityReader` in `test_admin_trace_service.py` lines 13-33 — copy the in-memory filtering approach for `chat_id`.

### Anti-patterns prohibidos

- **NO** single-session multi-batch: `purge_expired()` MUST use `async with self._sf() as session:` INSIDE the while loop, one session per batch. Holding a session across batches causes table locks.
- **NO** `DELETE FROM ... LIMIT` without WHERE: always filter by `created_at < cutoff` first, then LIMIT.
- **NO** string interpolation in SQL: always use SQLAlchemy parameter binding (`:ttl_days`) or native `.where(PipelineTrace.chat_id == chat_id)`.
- **NO** protocol-breaking changes: do NOT add `chat_id` as required (must be `= None` default everywhere).
- **NO** touching `cognitive/`, `behavior/`, or `learning/` modules.

### Logging / errores / convenciones del proyecto

- Logger: `logging.getLogger("diana.jobs")` for the purge job; `logging.getLogger("diana.infrastructure")` for `purge_expired()`.
- Use `logger.info(..., extra={...})` for structured logging with dict values, matching existing style.
- Error handling: catch exceptions at the job-loop level (per `gray_zone_expiration.py`), never let a single batch failure kill the loop.
- Never use bare `print()` — always `logging` module.

### Commits

- Work unit = behaviorally verifiable change.
- Commit after each task completes + tests pass.
- Format: `feat(trace): <description>` or `fix(trace): <description>`.

### Mock policy

- No mocking needed for Changes 1 and 2 (tests use real AdminTraceService + FakeTraceabilityReader).
- For Change 3 tests: follow the `test_gray_zone_expiration.py` pattern — fake the store, not asyncio.

### Skills del proyecto aplicables

- `telegram-bot-hardener` — architectural guidance for Telegram handlers and aiogram 3 patterns.

---

## Test commands

```bash
# Full trace module test suite (run after every task):
cd /home/ubuntu/repos/DianaV2 && python -m pytest tests/unit/application/test_admin_trace_service.py tests/unit/telegram/test_trace_callbacks.py tests/unit/telegram/test_admin_commands.py -x -q

# Jobs tests (run after Task 4):
cd /home/ubuntu/repos/DianaV2 && python -m pytest tests/unit/jobs/ -x -q

# Layer purity guard (run after wiring changes):
cd /home/ubuntu/repos/DianaV2 && python -m pytest tests/unit/telegram/test_telegram_layer_scope.py -x -q

# Complete unit suite (final gate):
cd /home/ubuntu/repos/DianaV2 && python -m pytest tests/unit/ -x -q
```

---

## Risks + Mitigation

| Risk | Mitigation |
|------|-----------|
| Protocol signature change breaks unmodified implementors (TypeError) | Task 2 updates ALL 5 implementors in lock-step; verifies with test command immediately |
| Batched DELETE causes table lock on production | LIMIT 1000 + separate session per batch ensures no long-held locks |
| Import cycle from `telegram.helpers` | `helpers.py` imports only stdlib `datetime`; `admin.py`/`callbacks.py` already import from application layer — no cycle risk |
| `created_at` is naive (no tzinfo) | `_format_relative_time` handles both naive and aware datetimes with the `dt.tzinfo is None` guard |
| AppContainer size grows | Adding one field (`trace_store`) is within existing pattern; the container already has ~20 fields |

## Success Criteria

- [x] All 4 strftime call sites replaced with `_format_relative_time(dt)`
- [x] `/turnos` without args works (unchanged behavior)
- [x] `/turnos 12345` filters by chat_id (only that VIP's turns shown)
- [x] `/turnos notanumber` shows usage message
- [x] `/traza <id>` shows relative date in detail view
- [x] Trace callbacks (vt, tp) show relative dates
- [x] `SqlTraceStore.purge_expired()` exists and returns deleted count
- [x] `TracePurgeJob` starts/stops via main.py lifecycle
- [x] All 628 existing tests pass (no regressions)
- [x] `test_telegram_layer_scope.py` passes (no layer violations)
