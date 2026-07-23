---
phase: quick
plan: turn-coordinator-contract
type: auto
item: turn-coordinator-contract (Pool remaining-contracts-app · Anexo G · ITEM 1/3)
effort: 4
stack: python>=3.12, asyncio, pytest, aiogram-middleware
depends_on: remaining-contracts-cognitive closed (Anexos C–F); application TurnCoordinator already exists
source_of_truth: docs/contratos_restantes.md Anexo G (G.1–G.5) under F1 locks
impact: .grok/agent-memory/impact-analyzer/turn-coordinator-contract.md
decisions: .planning/quick/turn-coordinator-contract/decisions.md
mode: standard
alignment: partial — VIP supersede+create + in-process lock already green; gaps = G.2 action surface, G.3.1 owner discard, G.5 timeout, owner MW wire
---

## Objective

Align **TurnCoordinator** to Anexo G as a **concurrency guard** (not reasoning): under a per-`chat_id` lock, given `(chat_id, autor, event)`, decide **`create | replace | discard_owner_message`**, keep **at most one non-terminal Turn per chat**, and wire the **owner business-message** path so live turns (including `pending_approval`) are **superseded + cascade-cancelled** instead of only `cancel_pending`.

After this item, VIP and owner entry paths share the same G.3 matrix under the same lock; G.5 fails loud on lock timeout (no silent drop). Multi-process DB locking and durable requeue remain documented residuals.

## Scope

- **In:**
  - Unified entry `coordinate` / `coordinate_unlocked` → `CoordinateResult` with English `action` + optional `turn_id`
  - G.3 decision matrix under lock (VIP create/replace; owner discard always — never creates)
  - Reuse existing supersede cascade (`cancel_pending` + `cancel_waiting_for_chat`) on **replace** and **owner discard**
  - Keep `begin_turn` / `begin_turn_unlocked` as thin **VIP-only wrappers** (return `TurnRecord` for call-site compatibility)
  - Wire `OwnerDetectionMiddleware` business branch through coordinator (shared `chat_scope`)
  - DI: `build_dispatcher` / `setup.py` passes `coordinator` into owner middleware
  - G.5 F1: lock acquire timeout + bounded retries + raise `ChatLockTimeoutError` (log error; never drop)
  - Module docstring: English ↔ Anexo G map + residual notes
  - Unit tests: G.3 matrix, concurrent VIP, owner discard + idle owner, G.5 timeout, owner MW integration
- **Out / Non-goals:**
  - Multi-worker Postgres `FOR UPDATE` / advisory locks (**L5 residual**)
  - Durable message outbox / requeue after lock timeout (**L5 residual**)
  - Shortening orchestrator full-pipeline lock (keep zombie guard — impact R5)
  - Cognitive Director / Analyst / Planner / Generator / Evaluator / Decider changes (**L7**)
  - BehaviorEngine.deliver sequence (Anexo I)
  - Capability Registry / Retrievers (Anexo H)
  - Learning post-turn
  - Alembic / schema migrations (**L7**)
  - Private owner DM / admin approve path must **not** call discard (only business_connection owner traffic)
  - Dirty-tree unrelated WIP
- **Constraints:**
  - Strict TDD Mode **active** — red → green → refactor per task
  - Application layer owns Turn entry; telegram middleware only **calls** coordinator (no store transitions in MW)
  - Cognitive **must not** import telegram/behavior; Coordinator stays in `application/`
  - Code/identifiers/comments in **English**; PLAN English; Spanish map in docstring only (**L8**)
  - F1 single-worker: `asyncio.Lock` per chat is sufficient (**L3**)
  - No silent message drop on lock failure (**G.5**)

## Assumptions

- A1: Additive `coordinate` + VIP wrappers is preferred over renaming all call sites in one shot (**L4**). Existing `begin_turn` tests keep working by routing to VIP branch.
- A2: Owner never creates Turns even when chat is idle — F1 refinement of literal G.3.3 catch-all (**L1b** / impact F1 decision).
- A3: `autor` runtime values are `"vip" | "owner"` (not Spanish `"dueña"`); map in docstring.
- A4: `CoordinateResult.turn_id` is `UUID` for `create`/`replace`; **`None`** for `discard_owner_message` (no new turn; no ghost id).
- A5: Owner discard sets `superseded_by=None` on priors (no successor turn) (**R8**).
- A6: Cascade reason: VIP → `"new_message"`; owner discard → `"owner_message"` (matches current owner MW cancel reason).
- A7: Lock timeout defaults as module constants are enough (no settings/config wiring required unless already trivial). Suggested: `LOCK_ACQUIRE_TIMEOUT_S = 5.0`, `LOCK_ACQUIRE_RETRIES = 2`, short backoff (e.g. 0.05s * attempt).
- A8: Orchestrator continues to hold full `chat_scope` and may keep calling `begin_turn_unlocked` (VIP wrapper) — no need to switch to `coordinate_unlocked` if wrapper is equivalent; optional one-line switch OK.
- A9: Deterministic escalate keeps `begin_turn` (VIP create/replace path) — still creates escalated turn after coordinate-equivalent mint.
- A10: `evento` stays thin: `trigger_message_id` (+ existing kwargs); Coordinator never reasons on message text.

## Locked decisions (NON-NEGOTIABLE)

| ID | Decision |
|----|----------|
| L1 | Owner never creates a Turn; G.3.1 supersede nonterminal + discard from pipeline |
| L1b | Owner + idle (no nonterminal) → `discard_owner_message`, not `create` |
| L2 | VIP nonterminal → replace; none → create |
| L3 | Serialize by `chat_id` (`chat_scope` / `asyncio.Lock`) |
| L4 | Unified `coordinate` API; keep `begin_turn*` VIP wrappers |
| L5 | G.5: timeout + retry + loud fail; multi-process FOR UPDATE + durable enqueue residual |
| L6 | Owner business MW → coordinator supersede (not cancel_pending alone) |
| L7 | No cognitive rewrite; no alembic |
| L8 | English identifiers; Spanish map in docs |

### English ↔ Anexo G mapping (docstring only)

| Runtime (English) | Anexo G (Spanish) |
|-------------------|-------------------|
| `autor="vip"` | `autor: "vip"` |
| `autor="owner"` | `autor: "dueña"` |
| `action="create"` | `accion: "crear"` |
| `action="replace"` | `accion: "reemplazar"` |
| `action="discard_owner_message"` | `accion: "descartar_mensaje_dueña"` |
| `CoordinateResult` | `CoordinatorOutput` |
| `coordinate` / `coordinate_unlocked` | G.2 entry under G.4 lock |
| `ChatLockTimeoutError` | G.5 lock failure (F1: raise, no enqueue yet) |

### G.3 matrix (locked — evaluated under `chat_scope`)

| # | Condition | Action | Side effects |
|---|-----------|--------|--------------|
| 1 | `autor=owner` + nonterminal priors | `discard_owner_message` | Supersede all priors (`superseded_by=None`); `cancel_pending(..., "owner_message")`; cancel waiting approvals; **no create** |
| 2 | `autor=owner` + no nonterminal | `discard_owner_message` | No-op store; still no create; cancel_pending optional no-op OK |
| 3 | `autor=vip` + nonterminal priors | `replace` | Supersede all with `superseded_by=new_id`; cascade cancel reason `"new_message"`; create `received` turn |
| 4 | `autor=vip` + no nonterminal | `create` | Create `received` turn only |

Invalid `autor` → raise `ValueError` (loud; not silent).

## Architecture Approach

### QUÉ (behavior / contracts)

| Contract | Runtime truth after this item |
|----------|-------------------------------|
| G.1 | Coordinator answers only “new turn or affect existing?”; no LLM; no draft; no action of cognitive Decision |
| G.2 in | `coordinate(chat_id, autor, *, trigger_message_id=None, vip_id=None, turn_id=None)` |
| G.2 out | `CoordinateResult(action, turn_id)` with English action literals |
| G.3.1 | Owner + live turn → supersede + discard (no new turn) |
| G.3.2 | VIP + live → replace |
| G.3.3 VIP | VIP + idle → create |
| G.3.3 owner (F1) | Owner + idle → discard (refinement; never create) |
| G.4 in-process | Same `ChatLockProvider`; concurrent VIP still one nonterminal |
| G.5 F1 | Timeout/retry then `ChatLockTimeoutError`; no silent drop |
| REQ-VIP-06 | Owner business traffic invalidates in-flight turn + delivery + waiting approval |

### CÓMO (structure / patterns)

- **Placement:** Application layer only for decision + cascade; Telegram middleware is a thin caller.
- **Pattern to copy:**
  - Supersede cascade body: existing `begin_turn_unlocked` in `src/diana/application/turn_coordinator.py` (~80–129)
  - Thin middleware → application: `ForbiddenKeywordsMiddleware` → `handle_deterministic_escalation` (inject coordinator)
  - Contract PLAN shape: `.planning/quick/decider-contract/PLAN.md` (TDD tasks + English map)
  - Owner MW tests: `tests/unit/telegram/test_owner_mw.py` — extend to real coordinator + in-memory stores
- **Interfaces first:**
  ```python
  # In turn_coordinator.py (or ports.py if preferred colocated)
  Autor = Literal["vip", "owner"]
  CoordinateAction = Literal["create", "replace", "discard_owner_message"]

  @dataclass(frozen=True, slots=True)
  class CoordinateResult:
      action: CoordinateAction
      turn_id: UUID | None  # set for create/replace; None for discard_owner_message

  class ChatLockTimeoutError(TimeoutError):
      """Raised when per-chat lock cannot be acquired (G.5 F1 loud fail)."""
  ```
- **API shape (exact):**
  ```python
  async def coordinate(
      self,
      chat_id: int,
      autor: Autor,
      *,
      trigger_message_id: int | None = None,
      vip_id: UUID | None = None,
      turn_id: UUID | None = None,
  ) -> CoordinateResult:
      async with self.chat_scope(chat_id):
          return await self.coordinate_unlocked(
              chat_id, autor,
              trigger_message_id=trigger_message_id,
              vip_id=vip_id,
              turn_id=turn_id,
          )

  async def coordinate_unlocked(...) -> CoordinateResult:
      # Caller MUST already hold chat_scope(chat_id)
      # implement G.3 matrix; extract shared _supersede_nonterminal(...)

  async def begin_turn(...) -> TurnRecord:
      result = await self.coordinate(chat_id, "vip", ...)
      assert result.turn_id is not None
      return await self.get_turn(result.turn_id)  # or return record from create path

  async def begin_turn_unlocked(...) -> TurnRecord:
      result = await self.coordinate_unlocked(chat_id, "vip", ...)
      # return created TurnRecord (prefer return record from internal create to avoid extra get)
  ```
- **Extract helper (required):** `_supersede_nonterminal(chat_id, *, superseded_by: UUID | None, cancel_reason: str) -> list[TurnRecord]` used by replace and owner discard.
- **Lock timeout (G.5 F1):** Change `chat_scope` to acquire via `asyncio.wait_for(lock.acquire(), timeout=...)` with bounded retries + sleep backoff; on exhaustion log `chat_lock_timeout` and raise `ChatLockTimeoutError`. Use try/finally `lock.release()`. Do **not** enqueue (residual).
- **Owner middleware:**
  ```python
  class OwnerDetectionMiddleware:
      def __init__(self, *, owner_telegram_id: int, coordinator: TurnCoordinator): ...
      # business branch:
      await self._coordinator.coordinate(
          chat_id, "owner",
          trigger_message_id=getattr(event, "message_id", None),
      )
      # do NOT call behavior.cancel_pending directly — cascade owns it
  ```
  Drop direct `BehaviorCanceller` dependency from owner MW (cascade inside coordinator still uses behavior).
- **Wiring:**
  - `build_dispatcher(...): OwnerDetectionMiddleware(owner_telegram_id=..., coordinator=coordinator)`
  - `behavior=` may remain on `build_dispatcher` signature for Forbidden/other but owner MW no longer needs it
  - `composition.py` already builds coordinator before telegram wiring — likely **no change** unless constructor gains timeout kwargs (prefer constants)
- **Orchestrator / escalate:** Keep calling `begin_turn` / `begin_turn_unlocked` (VIP wrappers). No cognitive touch.
- **Mock policy:** Unit tests use `InMemoryTurnStore`, `InMemoryPendingApprovalStore`, `FakeCanceller` — do **not** mock internal lock matrix logic; real `ChatLockProvider` for concurrency tests. For G.5: hold lock externally then call `coordinate` with short timeout (inject timeout via ctor optional params for testability).

### Ctor for testability (minimal)

```python
def __init__(
    self,
    turns: TurnStore,
    approvals: PendingApprovalStore,
    behavior: BehaviorCanceller,
    *,
    locks: ChatLockProvider | None = None,
    lock_acquire_timeout_s: float = 5.0,
    lock_acquire_retries: int = 2,
) -> None: ...
```

Production composition keeps defaults. Tests may pass `lock_acquire_timeout_s=0.05`, `lock_acquire_retries=0|1`.

## Context

@`.grok/agent-memory/impact-analyzer/turn-coordinator-contract.md`
@`.planning/quick/turn-coordinator-contract/decisions.md`
@`docs/contratos_restantes.md` (Anexo G only)
@`AGENTS.md` (§4.1 turn pipeline, §4.5 cancel on new message, §4.4 owner observe, middleware order §6.5)
@`src/diana/application/turn_coordinator.py`
@`src/diana/application/turn_orchestrator.py`
@`src/diana/application/deterministic_escalate.py`
@`src/diana/application/ports.py` (`TurnRecord`, `BehaviorCanceller`, `TurnStore`)
@`src/diana/telegram/middlewares/owner.py`
@`src/diana/telegram/setup.py`
@`src/diana/composition.py` (coordinator construction ~152)
@`tests/unit/application/test_turn_coordinator.py`
@`tests/unit/application/test_turn_orchestrator.py`
@`tests/unit/telegram/test_owner_mw.py`
@`tests/unit/telegram/test_middleware_stack.py`
@`tests/unit/application/test_deterministic_escalate.py`
@`tests/unit/acceptance/test_tac_mvp_f1.py`
@`.planning/quick/decider-contract/PLAN.md` (TDD contract pattern)

## Tasks

### Task 1: TDD — G.3 matrix + action surface + owner discard + G.5 (red)
**type:** auto  
**Objective:** Failing/new tests lock Anexo G behavior before production edits: `CoordinateResult` actions, owner never creates, VIP create/replace, concurrent invariant, lock timeout raises, owner MW supersedes.

**TDD order:**
1. Write tests first in coordinator + owner MW suites (expect **red** for new APIs / owner supersede).
2. Do **not** implement production code in this task beyond the minimum needed to import names if you prefer defining types in Task 2 (prefer Task 2 for types+impl; Task 1 may use string names that fail import — OK red).
3. Keep existing `begin_turn` tests intact (they must stay green after Task 2 wrappers).

**Files (edit):**
- `tests/unit/application/test_turn_coordinator.py`
- `tests/unit/telegram/test_owner_mw.py`

**Tests to add (must exist after task; go green with Task 2–3):**

| Test name | Intent |
|-----------|--------|
| `test_coordinate_vip_idle_creates` | No nonterminal + `autor=vip` → `action=="create"`, `turn_id` set, one nonterminal `received` |
| `test_coordinate_vip_nonterminal_replaces` | Prior live + vip → `action=="replace"`, old superseded, `old.superseded_by == new.id`, one nonterminal |
| `test_coordinate_owner_nonterminal_discards` | Prior live + owner → `action=="discard_owner_message"`, `turn_id is None`, zero nonterminal, old status superseded, `superseded_by is None` |
| `test_coordinate_owner_idle_discards_no_create` | No nonterminal + owner → discard, still zero turns / no new row |
| `test_coordinate_owner_discards_cancels_approvals_and_pending` | pending_approval + waiting approval + owner → approvals cancelled, canceller called with `(chat_id, "owner_message")` |
| `test_coordinate_vip_replace_cancel_reason_new_message` | VIP replace still uses `"new_message"` (regression of existing cascade reason) |
| `test_concurrent_coordinate_vip_one_non_terminal` | Parallel `coordinate(..., "vip")` → one nonterminal (G.4) |
| `test_begin_turn_still_vip_create_replace` | Existing begin_turn tests remain; add one assert that second begin still supersedes (wrapper) |
| `test_chat_scope_lock_timeout_raises` | Hold lock in background; `coordinate` with tiny timeout/retries → raises `ChatLockTimeoutError`; no silent success |
| `test_owner_mw_business_supersedes_pending_approval` | Integration: create pending_approval turn via coordinator; owner business event → list_non_terminal empty; handler not called |
| `test_owner_mw_private_does_not_coordinate_discard` | Owner private (no bc) → handler continues; no supersede of VIP chat (use separate chat with live turn — still nonterminal after) |
| Keep existing | concurrent begin_turn, transition/sink, explicit turn_id, supersede cancel once |

**Do NOT:**
- Touch cognitive modules
- Implement multi-process SQL locks
- Assert durable enqueue on timeout
- Call `cancel_pending` from owner MW tests as the sole invalidation (assert store supersede)

**Verification:**
```bash
.venv/bin/python -m pytest -q \
  tests/unit/application/test_turn_coordinator.py \
  tests/unit/telegram/test_owner_mw.py
```
(Expect red on new coordinate/owner-supersede/timeout tests until Task 2–3.)

**Done:**
- [ ] G.3 matrix tests present (create/replace/discard/idle owner)
- [ ] G.5 timeout test present
- [ ] Owner MW supersede test present
- [ ] Existing begin_turn tests still in file

---

### Task 2: Implement `coordinate` + cascade extract + G.5 lock timeout + VIP wrappers
**type:** auto  
**Objective:** Green coordinator unit suite: G.2/G.3/G.5 F1 surface; `begin_turn*` become VIP wrappers over `coordinate*`.

**TDD order:** implement types + matrix + lock timeout → green `test_turn_coordinator.py` → refactor helpers if needed.

**Files (edit):**
- `src/diana/application/turn_coordinator.py` — primary
- `tests/unit/application/test_turn_coordinator.py` — only if tiny assert fixes needed after API settles

**Implementation checklist:**
1. Add `Autor`, `CoordinateAction`, `CoordinateResult`, `ChatLockTimeoutError`.
2. Add optional ctor `lock_acquire_timeout_s`, `lock_acquire_retries`.
3. Rewrite `chat_scope` to timeout-aware acquire + retries + raise; log `chat_lock_timeout` on final failure.
4. Extract `_supersede_nonterminal(chat_id, *, superseded_by, cancel_reason) -> list[TurnRecord]`.
5. Implement `coordinate_unlocked` G.3 matrix (owner never creates; vip create/replace).
6. Implement `coordinate` = `async with chat_scope: coordinate_unlocked`.
7. Rewrite `begin_turn` / `begin_turn_unlocked` as VIP wrappers returning `TurnRecord` (preserve kwargs: `chat_id`, `trigger_message_id`, `vip_id`, `turn_id`).
8. Module docstring: single question G.1; English↔Spanish map; residual multi-process + durable enqueue.
9. Export new symbols in `__all__` if the module defines one; otherwise leave as-is.

**Do NOT:**
- Change `transition` / `mark_failed` / `transition_sink` semantics
- Import telegram or cognitive Director
- Add alembic
- Change TERMINAL set

**Verification:**
```bash
.venv/bin/python -m pytest -q tests/unit/application/test_turn_coordinator.py
```

**Done:**
- [ ] All coordinator unit tests green (including new G.3 + G.5)
- [ ] `begin_turn` still works as VIP create/replace
- [ ] Owner coordinate never inserts a turn row
- [ ] Lock timeout raises `ChatLockTimeoutError`

---

### Task 3: Wire owner middleware + setup DI; regression escalate/orchestrator/admin/TAC
**type:** auto  
**Objective:** Production owner business path uses coordinator discard under shared lock; full related unit gate green.

**TDD order:** green owner MW tests from Task 1 → wire setup → run regression suites.

**Files (edit):**
- `src/diana/telegram/middlewares/owner.py` — inject `TurnCoordinator`; business branch calls `coordinate(chat_id, "owner", ...)`; remove direct `BehaviorCanceller` dependency
- `src/diana/telegram/setup.py` — `OwnerDetectionMiddleware(owner_telegram_id=..., coordinator=coordinator)`
- `tests/unit/telegram/test_owner_mw.py` — ensure constructors match new signature (fixtures with real coordinator)
- Possibly touch if constructors break fixtures:
  - `tests/unit/telegram/test_middleware_stack.py`
  - `tests/unit/test_composition_wiring.py` (only if composition signature changes — prefer no)
  - `tests/unit/application/test_turn_orchestrator.py` (should stay green via begin_turn wrapper)
  - `tests/unit/application/test_deterministic_escalate.py`
  - `tests/unit/application/test_admin_service.py` / `test_admin_owner_escalate.py`
  - `tests/unit/acceptance/test_tac_mvp_f1.py`

**Owner MW rules:**
- Business + owner → `coordinate(..., "owner")` then `return None` (stop pipeline)
- Private owner → **no** coordinate discard; pass through (`is_owner=True`)
- Non-owner → pass through
- Log `owner_business_observed` still OK (add `action` extra if cheap)

**Do NOT:**
- Supersede on private admin messages
- Invoke Director / orchestrator from owner MW
- Reorder middleware stack

**Verification:**
```bash
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
```

**Done:**
- [ ] Owner business message supersedes nonterminal turns + cancels approvals
- [ ] Owner MW does not call BehaviorEngine except via coordinator cascade
- [ ] Middleware order unchanged
- [ ] Escalation / orchestrator / admin / TAC suites green

---

### Task 4: Full unit gate + residual notes in code
**type:** auto  
**Objective:** Entire unit suite green; residuals documented once in coordinator docstring (no new markdown required beyond decisions.md already present).

**Files (edit if needed):** only fixes from full-suite failures; no scope expansion.

**Verification:**
```bash
.venv/bin/python -m pytest -q tests/unit
```

**Done:**
- [ ] `tests/unit` green
- [ ] No files under `src/diana/cognitive/**` modified
- [ ] No alembic versions added
- [ ] Residuals (FOR UPDATE, durable enqueue) mentioned in module docstring

## Instrucciones para gsd-executor

- **Strict TDD:** Task 1 tests first (red) → Task 2 implement → Task 3 wire → Task 4 full gate.
- **Pattern to copy:** supersede cascade in current `begin_turn_unlocked`; forbidden MW’s thin call into application.
- **Anti-patterns (forbidden):**
  - Owner path that only `cancel_pending` without superseding turns
  - Creating Turns for `autor=owner`
  - Silent catch of lock timeout / drop message
  - Cognitive imports from telegram or coordinator calling Director/LLM
  - Mocking the G.3 matrix instead of using in-memory stores
  - Multi-process half-baked `FOR UPDATE` without tests
  - Shortening orchestrator full-pipeline lock in this PR
  - Spanish identifiers for `action` / `autor` values
- **Logging:** keep structured `logger.info` extras (`turn_id`, `chat_id`); add `coordinate_result` or include `action`/`autor` on coordinate; `chat_lock_timeout` on G.5 fail.
- **Commits:** work-unit = verifiable behavior (e.g. `feat(application): coordinate G.3 matrix + lock timeout`, `fix(telegram): owner MW supersede via TurnCoordinator`). Conventional commits; no AI attribution.
- **Mock policy:** FakeCanceller + InMemory* stores only; real locks for concurrency.
- **Compatibility:** keep `begin_turn` signature stable so escalate/orchestrator/TAC need zero or minimal edits.
- **Skills / project rules:** obey `AGENTS.md` module boundaries; Application owns turn entry; Behavior only cancel surface.

## Test commands

```bash
# Primary
.venv/bin/python -m pytest -q tests/unit/application/test_turn_coordinator.py

# Owner + stack
.venv/bin/python -m pytest -q \
  tests/unit/telegram/test_owner_mw.py \
  tests/unit/telegram/test_middleware_stack.py

# VIP concurrency / escalate / admin
.venv/bin/python -m pytest -q \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/application/test_deterministic_escalate.py \
  tests/unit/application/test_admin_service.py \
  tests/unit/application/test_admin_owner_escalate.py

# Composition + TAC
.venv/bin/python -m pytest -q \
  tests/unit/test_composition_wiring.py \
  tests/unit/acceptance/test_tac_mvp_f1.py

# Full unit gate (test-guardian)
.venv/bin/python -m pytest -q tests/unit
```

(`asyncio_mode = auto` in `pyproject.toml`; no extra asyncio flags.)

## Risks + Mitigation

| Risk | Mitigation in plan |
|------|--------------------|
| R1 zombie nonterminal after owner traffic | Task 1–3: G.3.1 + owner MW wire through cascade |
| R2 race VIP vs owner | Owner uses same `coordinate` → `chat_scope`; never raw store transitions in MW |
| R3 API reshape breaks call sites | Keep `begin_turn*` VIP wrappers (**L4**) |
| R4 G.5 scope creep | Timeout+retry+raise only; enqueue residual |
| R5 full-pipeline lock | Keep orchestrator CS; do not shorten |
| R6 private owner DM | Only business_connection branch coordinates discard |
| R7 multi-process false confidence | Residual + docstring; no half FOR UPDATE |
| R8 superseded_by on discard | `None` + log |

## Success Criteria

- [ ] `coordinate` exposes G.2 English actions: `create | replace | discard_owner_message`
- [ ] VIP: idle → create; nonterminal → replace with cascade + one nonterminal
- [ ] Owner: always discard; never creates; supersedes live turns; cancels approvals + pending delivery
- [ ] OwnerDetectionMiddleware business path uses coordinator under shared lock
- [ ] G.5: lock timeout after retries raises `ChatLockTimeoutError` (never silent drop)
- [ ] `begin_turn` / `begin_turn_unlocked` remain VIP-compatible wrappers
- [ ] Concurrent VIP paths still enforce one nonterminal (G.4 in-process)
- [ ] No cognitive / alembic / Behavior deliver changes
- [ ] All Test commands green; full `tests/unit` green
- [ ] Residuals documented: multi-process FOR UPDATE, durable requeue

## Next

`gsd-executor` (Strict TDD) → then arch-enforcer → test-guardian.
