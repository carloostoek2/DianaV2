---
phase: quick
plan: behavior-engine-contract
type: auto
item: behavior-engine-contract (Pool remaining-contracts-app · Anexo I · ITEM 3/3)
effort: 4
stack: python>=3.12, asyncio, pytest-asyncio, pydantic-v2
depends_on: turn-coordinator-contract (G); registry-retrievers-contract (H); Admin single deliver path
source_of_truth: docs/contratos_restantes.md Anexo I (I.1–I.5) under F1 locks
impact: .grok/agent-memory/impact-analyzer/behavior-engine-contract.md
decisions: .planning/quick/behavior-engine-contract/decisions.md
mode: standard
alignment: partial — sequence delay→read→typing→send + cancel_pending green; gaps = I.4 pre-send, I.4 retries, I.2 mode enum, I.5 failed+notify, prod never-zero delay
---

## Objective

Align **BehaviorEngine** to Anexo I as the **only VIP write path**: act already-approved `texts` via fixed human-like sequence **delay → read → typing → send**, with **I.4 last-mile pre-send supersede abort**, **bounded retries on transient send errors**, **mode enum** including `fake_delivery` (F1 record-only), and **I.5** failure surface (`success=False` + reason) completed by **Admin** (`Turn.status=failed` + owner `notify_info`). Behavior stays pure actuation — **never** generates text, never imports cognitive/LLM/aiogram.

## Scope

- **In:**
  - Widen `DeliveryContext.mode` to `supervised | autonomous | fake_delivery` (+ Settings `global_mode`)
  - Inject `TurnStatusReader`; check **immediately before each send** (and before fake virtual send); abort → `cancelled=True`, no network send, delivery `cancelled`
  - Bounded per-bubble send retries on `TransientSendError` only; config knobs + backoff sleep
  - `fake_delivery`: no-network record-only success path (no actuator I/O for read/typing/send)
  - Production `RandomDelayPolicy` / settings: initial delay **never zero** (REQ-NFR-01)
  - Admin `_resolve_and_deliver`: pass `mode`; on permanent fail → `mark_failed` + `notify_info` + approval not silently reopened as waiting
  - Composition wires reader + retry/mode settings
  - Unit tests: I.3 order, I.4 pre-send, I.4 retries, I.2 mode, I.5 Admin surface, purity, cancel/CAS regressions
- **Out / Non-goals:**
  - Full sandbox FakeDelivery product UX (REQ-COG-14 body) — residual beyond enum + record-only
  - Multi-worker durable cancel / Postgres last-mile (**G.4 residual**)
  - Telegram partial multi-text idempotency after partial success
  - Cognitive Director / LLM / Learning / Registry changes
  - Alembic / schema migrations
  - Reordering `deliver` kwargs to match AGENTS.md §5.4 literally (doc residual)
  - Forcing `telegram_message_id` mandatory
  - Recovery auto-deliver (must remain absent)
  - Dirty-tree unrelated WIP
- **Constraints:**
  - Strict TDD Mode **active** — red → green → refactor per task
  - Behavior package **must not** import `diana.cognitive.*` decision modules, `diana.llm`, `aiogram`
  - Behavior never decides content/action; modes only select I/O strategy (real vs fake)
  - Code/identifiers/comments **English**; PLAN English; Spanish map in docstring/decisions only
  - Keep CAS delivery transitions; cancel_pending + TimerManager still required
  - `turn_id` remains required on `deliver`

## Assumptions

- A1: Sole production `deliver` call site is `AdminService._resolve_and_deliver` (impact confirmed). Pre-send gate in engine still protects future callers.
- A2: Terminal abort statuses as English strings: `superseded`, `delivered`, `failed`, `escalated`. Live statuses (e.g. `pending_approval`) allow send.
- A3: Missing turn (`get_status` → `None`) aborts send (fail-closed) — treat as non-live.
- A4: `DeliveryResult.success` maps contract `ok`; no parallel `ok` field needed.
- A5: Multi-text: pre-send check + retry **per text** before each `send_message`; do not restart full delay→read→typing after a successful partial bubble.
- A6: Retry budget default `max_send_attempts=3` (total attempts per text); backoff `0.05s` via `Clock.sleep` (testable with `ImmediateClock`).
- A7: Permanent errors = any non-`TransientSendError` / non-`CancelledError` from send; no retry.
- A8: `fake_delivery` still honors pre-send live check and may honor initial delay (policy); skips actuator I/O; marks delivery `done`.
- A9: Admin permanent-fail path: `coordinator.mark_failed(turn_id, error=...)` + `notifier.notify_info(...)` + approval `cancelled` (not `waiting`).
- A10: Admin cancelled path with turn still live: keep reopen `waiting` (existing); cancelled with terminal turn: post-latch no-revive (existing).
- A11: `FixedDelayPolicy(initial=0)` remains legal for tests; production clamp only in `RandomDelayPolicy` / Settings validation.
- A12: `autonomous` mode uses the **same real send path** as `supervised` for F1 (mode is an external product filter; Behavior does not re-decide approve). Difference is record-keeping / future sandbox only — no extra branch required beyond accepting the enum value.
- A13: Optional ctor defaults for new engine deps keep test call sites compiling if defaults are safe: prefer explicit `AlwaysLiveTurnStatusReader` helper in `behavior/fake.py` and update primary fixtures; composition always injects real reader.

## Locked decisions (NON-NEGOTIABLE)

| ID | Decision |
|----|----------|
| L1 | Pre-send Turn live check inside engine before each send (I.4 critical) |
| L2 | `TurnStatusReader` port; no cognitive imports |
| L3 | Abort on missing/terminal status; no send |
| L4 | Bounded retries for `TransientSendError` only |
| L5 | `TransientSendError` in behavior; no aiogram in behavior |
| L6 | Admin owns `Turn.failed` + owner notify on permanent fail |
| L7 | Permanent fail: do not reopen approval as waiting |
| L8 | Cancelled: keep post-latch; no false failed on superseded |
| L9 | Mode enum `supervised\|autonomous\|fake_delivery` |
| L10 | `fake_delivery` = record-only no-network F1 |
| L11 | Sequence delay→read→typing→send preserved |
| L12 | Prod never-zero initial delay; test FixedDelay free |
| L13 | No text generation; no cognitive/LLM/aiogram; no alembic |
| L14 | Keep `(texts, ctx, turn_id, decision=)` signature |
| L15 | Strict TDD |

Full table + residuals: `.planning/quick/behavior-engine-contract/decisions.md`.

### English ↔ Anexo I (docstring)

| Runtime | Contract |
|---------|----------|
| `mode="supervised"` | `supervisado` |
| `mode="autonomous"` | `autonomo` |
| `mode="fake_delivery"` | `fake_delivery` |
| `DeliveryResult.success` | `ok` |
| Pre-send status gate | I.4 supersede abort |
| Bounded retries | I.4 / REQ-NFR-04 |
| Admin failed + notify | I.5 |

## Architecture Approach

### QUÉ (behavior / contracts)

| Contract | Runtime truth after this item |
|----------|-------------------------------|
| I.1 | Engine answers only “how is the approved message acted?”; sole VIP write path; no content decision |
| I.2 in | `deliver(texts, DeliveryContext(mode=…), turn_id, decision=)` |
| I.2 mode | Enum accepts supervised / autonomous / fake_delivery; invalid rejected by Pydantic |
| I.2 out | `DeliveryResult(success, error, message_ids, cancelled, delays…)` |
| I.3 | Order: initial sleep → optional read → typing action+sleep → send(s) |
| I.3 delay | Prod policy initial > 0 (REQ-NFR-01) |
| I.4 pre-send | Before each send: if turn missing/terminal → abort, no send, cancelled result |
| I.4 retries | Transient only, bounded attempts, then permanent fail |
| I.4 fake | Enum + record-only path; no network |
| I.5 | `success=False` + `error`; Admin → Turn `failed` + owner notify (permanent fail) |
| REQ-VIP-06 | `cancel_pending` still cancels tasks + DB rows (complement to I.4) |
| AGENTS | Behavior ↛ cognitive/LLM; Application → Behavior OK |

### CÓMO (structure / patterns)

- **Placement:**
  - Actuation + retries + pre-send gate → `diana.behavior`
  - Turn write + owner notify on fail → `diana.application.admin_service` (existing Admin path)
  - Wiring → `composition.py` + `config.py`
- **Pattern to copy:**
  - Engine sequence + cancel: `src/diana/behavior/engine.py` (keep structure; insert gate/retries)
  - Typed fail + owner notify: `src/diana/application/turn_orchestrator.py` fail branches (`mark_failed` + `notify_info`)
  - Admin post-deliver latch: `src/diana/application/admin_service.py` `_resolve_and_deliver` (~292–343)
  - Test doubles: `src/diana/behavior/fake.py` (`FakeTelegramActuator`, `ImmediateClock`, `FixedDelayPolicy`)
  - Import purity: `tests/unit/behavior/test_behavior_import_purity.py`
  - Contract PLAN shape: `.planning/quick/turn-coordinator-contract/PLAN.md`
- **Interfaces first (Task 1):**

```python
# behavior/ports.py
DeliveryMode = Literal["supervised", "autonomous", "fake_delivery"]

class DeliveryContext(BaseModel):
    ...
    mode: DeliveryMode = "supervised"

class TransientSendError(Exception):
    """Transient channel/API failure eligible for bounded retry (I.4)."""

@runtime_checkable
class TurnStatusReader(Protocol):
    async def get_status(self, turn_id: UUID) -> str | None:
        """Return current turn status string, or None if missing."""
        ...
```

```python
# behavior/engine.py constants (local strings — no cognitive import)
_TERMINAL_SEND_ABORT: frozenset[str] = frozenset(
    {"superseded", "delivered", "failed", "escalated"}
)

# ctor additions (defaults for gradual test updates)
def __init__(
    self,
    actuator: TelegramActuatorPort,
    deliveries: PendingDeliveryStore,
    *,
    clock: Clock,
    delay_policy: DelayPolicy,
    timers: TimerManager | None = None,
    turn_status: TurnStatusReader | None = None,
    max_send_attempts: int = 3,
    retry_backoff_seconds: float = 0.05,
) -> None: ...
```

```python
# behavior/fake.py helpers
class AlwaysLiveTurnStatusReader:
    async def get_status(self, turn_id: UUID) -> str | None:
        return "pending_approval"

class SequenceTurnStatusReader:
    """Returns successive statuses for race-oriented tests (no wall clock)."""
    def __init__(self, statuses: list[str | None]) -> None: ...
    async def get_status(self, turn_id: UUID) -> str | None: ...

class FlakySendActuator(FakeTelegramActuator):
    """Fails first N send_message with TransientSendError, then succeeds."""
```

```python
# composition: thin adapter (may live in composition.py or application helper)
class TurnStoreStatusReader:
    def __init__(self, turns: TurnStore) -> None: ...
    async def get_status(self, turn_id: UUID) -> str | None:
        row = await self._turns.get(turn_id)
        return None if row is None else row.status
```

- **Pre-send algorithm (exact):**
  1. After typing sleep (or at fake virtual-send boundary), for each `text` in `texts`:
  2. `status = await turn_status.get_status(turn_id)` if reader present; if reader is `None`, **treat as always live only in unit fixtures that intentionally omit it — production composition MUST inject reader**. Prefer tests always inject `AlwaysLiveTurnStatusReader`.
  3. If `status is None` or `status in _TERMINAL_SEND_ABORT`: mark delivery `cancelled`, return `DeliveryResult(success=False, cancelled=True, error="superseded_before_send"|f"turn_not_live:{status}")`, **send_count unchanged**.
  4. Else attempt send with retry loop.

- **Retry algorithm (exact):**
  ```
  for attempt in 1..max_send_attempts:
      try:
          mid = await actuator.send_message(...)
          break success
      except TransientSendError:
          if attempt == max: mark delivery error; return success=False, error=...
          await clock.sleep(retry_backoff_seconds)
      except asyncio.CancelledError:
          re-raise / existing cancel path
      except Exception:
          permanent → mark error; return success=False (no retry)
  ```

- **fake_delivery branch:**
  - After initial delay (+ optional read/typing **skipped** — no actuator calls), run pre-send check once; if live, mark delivery `done`, return `success=True, message_ids=[]` without calling actuator.
  - Log `delivery_fake` with turn_id/chat_id.

- **Admin permanent fail (exact change to else branch):**
  ```python
  if result.success:
      ... existing delivered path ...
  elif result.cancelled:
      await self._approvals.mark_status(turn_id, "waiting")  # rare live+cancel
      # if turn already terminal, outer latch already handled
  else:
      # I.5 permanent deliver failure after retries
      await self._approvals.mark_status(turn_id, "cancelled")
      await self._coordinator.mark_failed(turn_id, error=result.error or "delivery_failed")
      await self._notifier.notify_info(
          f"Turn {turn_id} failed: delivery_failed ({result.error})",
          chat_id=claimed.chat_id,
      )
      await self._traces.set_delivery_result(turn_id, result.to_trace_dict())
  ```
  Note: when post-deliver latch sees terminal turn first, keep existing no-revive path (do not mark_failed on superseded).

- **Admin mode pass-through:**
  ```python
  # AdminService.__init__ add: delivery_mode: DeliveryMode = "supervised"
  ctx = DeliveryContext(..., mode=self._delivery_mode)
  ```
  composition: `delivery_mode=settings.global_mode`.

- **Config:**
  ```python
  global_mode: Literal["supervised", "autonomous", "fake_delivery"] = "supervised"
  delivery_max_send_attempts: Annotated[int, Field(ge=1, le=10)] = 3
  delivery_retry_backoff_seconds: Annotated[float, Field(gt=0)] = 0.05
  # optional delay knobs if trivial:
  delivery_initial_delay_min: Annotated[float, Field(gt=0)] = 4.0
  delivery_initial_delay_max: Annotated[float, Field(gt=0)] = 14.0
  ```
  `RandomDelayPolicy`: validate `initial_min > 0` and `initial_max >= initial_min` in `__init__` (raise `ValueError`).

- **Wiring:**
  ```python
  behavior = BehaviorEngine(
      actuator,
      deliveries,
      clock=clock,
      delay_policy=policy,  # RandomDelayPolicy from settings mins/maxes
      turn_status=TurnStoreStatusReader(turns),
      max_send_attempts=settings.delivery_max_send_attempts,
      retry_backoff_seconds=settings.delivery_retry_backoff_seconds,
  )
  admin = AdminService(..., delivery_mode=settings.global_mode)
  ```

- **Mock policy:** Real `BehaviorEngine` + `FakeTelegramActuator` / `FlakySendActuator` + `ImmediateClock` + `FixedDelayPolicy` + in-memory stores + `SequenceTurnStatusReader`. Do **not** mock internal sequence order. No network. No cognitive mocks.

### File map

| Action | Path |
|--------|------|
| EDIT | `src/diana/behavior/ports.py` — mode enum, `TransientSendError`, `TurnStatusReader`, exports |
| EDIT | `src/diana/behavior/engine.py` — pre-send gate, retries, fake branch, ctor knobs |
| EDIT | `src/diana/behavior/fake.py` — AlwaysLive / Sequence readers; FlakySendActuator |
| EDIT | `src/diana/application/admin_service.py` — mode; I.5 fail path |
| EDIT | `src/diana/composition.py` — wire reader, settings, policy mins; `TurnStoreStatusReader` |
| EDIT | `src/diana/config.py` — widen `global_mode`; retry/delay settings |
| EDIT | `tests/unit/behavior/test_engine.py` — I.3/I.4/I.2 cases |
| EDIT | `tests/unit/behavior/test_fake_delivery.py` — mode fake if needed |
| EDIT | `tests/unit/application/test_admin_service.py` — I.5 failed + notify; fixtures inject reader |
| EDIT | `tests/unit/test_config.py` — mode + new settings defaults |
| VERIFY | `tests/unit/behavior/test_behavior_import_purity.py` |
| VERIFY | `tests/unit/application/test_turn_orchestrator.py`, `test_turn_coordinator.py`, recovery, delivery transitions, TAC |
| NO TOUCH | `src/diana/cognitive/**`, `src/diana/llm/**`, `src/diana/learning/**`, `alembic/**` |

## Context

@docs/contratos_restantes.md (Anexo I only)
@AGENTS.md (§3.1 Behavior, §4.1 deliver, §4.5 cancel, §5.4)
@.grok/agent-memory/impact-analyzer/behavior-engine-contract.md
@.planning/quick/behavior-engine-contract/decisions.md
@src/diana/behavior/engine.py
@src/diana/behavior/ports.py
@src/diana/behavior/fake.py
@src/diana/application/admin_service.py
@src/diana/application/ports.py
@src/diana/composition.py
@src/diana/config.py
@tests/unit/behavior/test_engine.py
@tests/unit/application/test_admin_service.py

## Tasks

### Task 1: Ports + test doubles + mode enum (interfaces first)
**type:** auto  
**Objective:** Mode enum, `TurnStatusReader`, `TransientSendError`, and fakes exist; DeliveryContext accepts three modes; invalid mode rejected.  
**Files:**
- `src/diana/behavior/ports.py`
- `src/diana/behavior/fake.py`
- `tests/unit/behavior/test_engine.py` (or small `test_ports` section)
- `tests/unit/test_config.py` (settings widen — can land Task 3 if preferred; prefer early if config tests independent)
**Action (TDD):**
1. **RED:** Test `DeliveryContext(mode="autonomous")` and `mode="fake_delivery"` construct; `mode="nope"` raises ValidationError; document English map in ports module docstring.
2. **GREEN:** Widen Literal; add `TransientSendError`; add `TurnStatusReader` Protocol; export all.
3. Add `AlwaysLiveTurnStatusReader`, `SequenceTurnStatusReader`, `FlakySendActuator` (fails first N sends with `TransientSendError`).
4. Do **not** change engine logic yet beyond what is needed for imports if any.
**Verification:**
```bash
PYTHONPATH=src python -m pytest tests/unit/behavior/test_engine.py -q -k "mode or DeliveryContext" --tb=short
```
**Done:** Three modes accepted; invalid rejected; fakes importable; purity still green for ports-only change.

---

### Task 2: Engine I.4 pre-send + retries + fake_delivery (core)
**type:** auto  
**Objective:** BehaviorEngine implements pre-send abort, bounded transient retries, and fake_delivery no-network path while preserving delay→read→typing→send order on real modes.  
**Files:**
- `src/diana/behavior/engine.py`
- `tests/unit/behavior/test_engine.py`
- `tests/unit/behavior/test_fake_delivery.py` (if sequence assertions live there)
- Update any fixture that constructs `BehaviorEngine` used by these tests to pass `turn_status=AlwaysLiveTurnStatusReader()`
**Action (TDD — write failing tests FIRST):**

| Test | Assert |
|------|--------|
| `test_happy_path_sequence_order` | Still `read → typing → send`; sleeps recorded (regression) |
| `test_presend_superseded_aborts_without_send` | `SequenceTurnStatusReader(["superseded"])` or flip after delay: `cancelled=True`, `send_count==0`, delivery status `cancelled` |
| `test_presend_terminal_failed_aborts` | status `failed` → no send |
| `test_presend_missing_turn_aborts` | `None` → no send |
| `test_transient_then_success_within_budget` | Flaky N=1, max_attempts=3 → success, send attempts recorded ≥2 |
| `test_transient_exhausted_returns_error` | Flaky always transient, max_attempts=2 → `success=False`, delivery `error`, no infinite loop |
| `test_permanent_error_no_retry` | raise `RuntimeError` once → single attempt, `success=False` |
| `test_fake_delivery_no_network_send` | `mode="fake_delivery"` → actuator calls empty (or no send/read/typing), `success=True` |
| `test_fake_delivery_presend_abort` | fake + superseded → cancelled, not marked done |
| Cancel mid-delay regression | existing still green |

Implementation notes:
- Insert pre-send check immediately before each `send_message` (and before fake virtual completion).
- Retry only around `send_message`, not around delay/read/typing.
- On pre-send abort: `_safe_mark(delivery_id, "cancelled")`.
- On exhausted/permanent: `_safe_mark(..., "error")`.
- Log structured events: `delivery_presend_abort`, `delivery_send_retry`, `delivery_fake`, keep `delivery_done` / `delivery_cancelled`.
- Module docstring: English ↔ Anexo I map + “never generates text”.

**Verification:**
```bash
PYTHONPATH=src python -m pytest tests/unit/behavior/ -q --tb=short
```
**Done:** All new I.4/I.2 engine tests green; happy path + cancel regressions green; no cognitive/aiogram imports.

---

### Task 3: Admin I.5 + composition/config wiring
**type:** auto  
**Objective:** Permanent deliver failure marks Turn `failed`, notifies owner, does not silently reopen waiting; composition injects reader/settings; mode flows from Settings; prod delay never zero.  
**Files:**
- `src/diana/application/admin_service.py`
- `src/diana/composition.py`
- `src/diana/config.py`
- `tests/unit/application/test_admin_service.py`
- `tests/unit/test_config.py`
- Fix remaining `BehaviorEngine(...)` test constructors that break (pass AlwaysLive reader) in application/telegram/acceptance as needed for green suite
**Action (TDD):**
1. **RED:** Admin test: actuator raises permanent error (or Flaky exhausted) → after `handle_approve`: turn status `failed`, notifier received info containing delivery failure / turn id, approval **not** `waiting` (use `cancelled`), `send` may be 0 or failed attempts, success false.
2. **RED:** Admin test: supersede mid-flight still no revive (existing) + cancelled does **not** force `failed` when turn already `superseded`.
3. **GREEN:** Implement Admin else-branch per Architecture Approach; inject `delivery_mode`.
4. Settings: widen `global_mode`; add retry/delay fields with `gt=0` / bounds; tests for defaults + reject `global_mode` invalid + reject non-positive delay min if validated.
5. `RandomDelayPolicy`: reject `initial_min <= 0`.
6. composition: `TurnStoreStatusReader(turns)`, pass settings knobs into engine + admin.
7. Sweep test graphs: `admin_graph`, orchestrator fixtures, telegram stacks — inject `AlwaysLiveTurnStatusReader` (and mode default supervised).

**Verification:**
```bash
PYTHONPATH=src python -m pytest \
  tests/unit/application/test_admin_service.py \
  tests/unit/test_config.py \
  tests/unit/behavior/ \
  -q --tb=short
```
**Done:** I.5 observable; wiring complete; config accepts three modes; prod policy never-zero.

---

### Task 4: Purity + full regression (gate)
**type:** auto  
**Objective:** Architecture boundaries and full unit suite green.  
**Files:** verify-only; fix only breakages from ctor changes.  
**Action:**
1. Confirm purity forbids llm/cognitive decision modules/aiogram under `behavior/`.
2. Confirm recovery still never auto-delivers.
3. Confirm concurrent double-approve single send still holds.
4. Run full unit + TAC acceptance.

**Verification:**
```bash
PYTHONPATH=src python -m pytest tests/unit/behavior/test_behavior_import_purity.py -q
PYTHONPATH=src python -m pytest \
  tests/unit/behavior/ \
  tests/unit/application/test_admin_service.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/application/test_turn_coordinator.py \
  tests/unit/application/test_recovery.py \
  tests/unit/application/test_recovery_startup.py \
  tests/unit/infrastructure/test_delivery_transitions.py \
  -q --tb=short
PYTHONPATH=src python -m pytest tests/unit/ -q --tb=line
PYTHONPATH=src python -m pytest tests/unit/acceptance/test_tac_mvp_f1.py -q --tb=short
```
**Done:** All green; no alembic; no cognitive edits.

## Instrucciones para gsd-executor

- **Strict TDD:** For each task, write/adjust failing tests first, then implement, then refactor. Do not implement engine gate before Task 2 red tests exist.
- **Patterns to copy:** `engine.py` sequence; orchestrator `mark_failed`+`notify_info`; Admin post-latch; `behavior/fake.py` doubles.
- **Anti-patterns forbidden:**
  - Importing `diana.cognitive.*`, `diana.llm`, `aiogram` inside `behavior/`
  - Generating or rewriting message text in Behavior
  - Infinite retry loops
  - Relying only on `Task.cancel` for I.4 (must have pre-send status check)
  - Silently reopening approval `waiting` after permanent send failure
  - Auto-deliver from recovery/startup
  - Alembic migrations
  - Mocking internal engine sequence with over-mocked units that hide order bugs
- **Logging:** `logging.getLogger("diana.behavior")` / `"diana.application"`; structured `extra=` with turn_id/chat_id; no secrets.
- **Commits:** One work unit per task (behavior ports → engine I.4 → admin I.5/wiring → if needed). Conventional commits, no AI attribution.
- **Mock policy:** FakeTelegramActuator / FlakySendActuator / ImmediateClock / FixedDelayPolicy / in-memory stores / SequenceTurnStatusReader only. No live Telegram.
- **Skills / project rules:** Obey `AGENTS.md` Behavior boundaries; English artifacts.
- **If discovery matters:** save to engram via mem_save project `DianaV2`.

## Test commands

```bash
# Primary — behavior
PYTHONPATH=src python -m pytest tests/unit/behavior/ -q --tb=short

# Deliver path + supersede + coordinator
PYTHONPATH=src python -m pytest \
  tests/unit/application/test_admin_service.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/application/test_turn_coordinator.py \
  -q --tb=short

# Recovery never-deliver + CAS matrix
PYTHONPATH=src python -m pytest \
  tests/unit/infrastructure/test_delivery_transitions.py \
  tests/unit/application/test_recovery.py \
  tests/unit/application/test_recovery_startup.py \
  -q --tb=short

# Config
PYTHONPATH=src python -m pytest tests/unit/test_config.py -q --tb=short

# Full unit
PYTHONPATH=src python -m pytest tests/unit/ -q --tb=line

# Gold acceptance
PYTHONPATH=src python -m pytest tests/unit/acceptance/test_tac_mvp_f1.py -q --tb=short
```

## Risks + Mitigation

| Risk | Mitigation (task) |
|------|-------------------|
| Send-after-supersede race | Task 2 pre-send gate + keep cancel_pending |
| Silent delivery failure | Task 3 Admin mark_failed + notify; no waiting reopen |
| Retry double-send storms | Retry only transient; per bubble; max attempts config |
| Cognitive import via TurnStatus | Local string terminal set; reader protocol only |
| fake_delivery in prod | Explicit branch; tests; default mode supervised |
| Delay-zero tests vs REQ-NFR-01 | Clamp RandomDelayPolicy only; FixedDelay free |
| Ctor blast radius in tests | AlwaysLive helper; optional reader default only if all production paths inject — prefer explicit fixture update |
| Partial multi-text after success then fail | Document residual; fail remaining; do not re-send successful bubbles |

## Success Criteria

- [ ] I.3 sequence delay→read→typing→send preserved on supervised/autonomous happy path
- [ ] I.4: turn superseded/terminal/missing immediately before send → **zero** `send_message`, `cancelled=True`
- [ ] I.4: transient fail then success within budget → `success=True`
- [ ] I.4: retries exhausted → `success=False` + delivery `error`
- [ ] I.2: mode accepts supervised/autonomous/fake_delivery; invalid rejected
- [ ] I.2/I.4: fake_delivery performs no network actuator send
- [ ] I.5: permanent fail → Turn `failed` + owner notify + not silent waiting reopen
- [ ] REQ-NFR-01: production delay policy rejects/never produces zero initial min
- [ ] Import purity green; cancel/CAS/concurrent approve regressions green
- [ ] No cognitive/LLM/learning/alembic edits
- [ ] Full `tests/unit/` + TAC acceptance green

## Residuals (document, do not implement)

1. Full sandbox FakeDelivery UX (REQ-COG-14)
2. Multi-process durable cancel last-mile
3. Telegram partial multi-text idempotency
4. AGENTS.md §5.4 signature doc sync
5. Mandatory `telegram_message_id` at deliver gate

## Handoff

**Next agent:** `gsd-executor`  
Execute Task 1 → 4 in order under Strict TDD. Read `decisions.md` locks before coding. Do not expand into cognitive or alembic.
