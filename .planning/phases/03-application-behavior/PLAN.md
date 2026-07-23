---
phase: 03
plan: application-behavior
type: auto
item: 3/4
effort: 5-6
stack: python>=3.12, pydantic-v2, pytest-asyncio
depends_on: 01-foundation, 02-cognitive-core
strict_tdd: true
delivery_note: prefer work-unit commits; chained-PR if changed LOC >400
---

## Objective

Materialize the **application shell** around the pure cognitive core: turn lifecycle (`TurnCoordinator`), VIP use-case wiring (`TurnOrchestrator`), owner approval queue (`AdminService`), human-like delivery (`BehaviorEngine` + FakeDelivery for tests), post-turn learning (trace completeness only), and `pending_deliveries` recovery **helpers**. No aiogram handlers, no `main` polling, no Staging, no gray zone, no autonomous `send`.

## Context

@`.grok/agent-memory/impact-analyzer/03-application-behavior.md`
@`.planning/phases/02-cognitive-core/PLAN.md`
@`.planning/phases/02-cognitive-core/SUMMARY.md`
@`docs/MVP_COMPONENT_DESIGN.md` (§5.2–5.3, §5.12–5.14, §7)
@`AGENTS.md` (§3–6: module limits, Behavior outside cognition, Learning post-turn)
@`src/diana/cognitive/director.py` (ITEM 3 contract: single-arg `handle_turn(IncomingTurn)`)
@`src/diana/cognitive/models.py` (`TurnStatus`, `TERMINAL_TURN_STATUSES`, `Decision` approve|escalate)
@`src/diana/cognitive/ports.py` (`TRACE_KEYS`, `TurnStatusSink`, `TraceStore`, `MessageHistoryPort`)
@`src/diana/infrastructure/db/models.py` (ORM: turns, pending_*, pipeline_traces, message_history, escalations)
@`tests/unit/cognitive/test_import_purity.py` (must stay green; extend with behavior purity)

**Repo state:** foundation + cognitive DONE (**150** unit tests). Packages `application/`, `behavior/`, `learning/` **do not exist**. No repositories yet. Zero production callers outside tests.

**Locked decisions (NON-NEGOTIABLE):**

| ID | Decision |
|----|----------|
| L1 | **Mint `turn_id` before `handle_turn`.** Application creates UUID + persists turn row (`received`) then builds `IncomingTurn(turn_id=..., ...)`. Director stays single-arg. **Ignore** MVP two-arg sketch. |
| L2 | **`approve` → `pending_approval` only.** Orchestrator must **never** call `BehaviorEngine.deliver` on approve. Delivery only from Admin resolve (`handle_approve` / `handle_correct`). |
| L3 | **Supersede cascade:** `begin_turn` marks prior non-terminal turns `superseded` + `superseded_by`, calls `behavior.cancel_pending(chat_id)`, cancels waiting `pending_approvals`, then creates new turn `received`. |
| L4 | **Behavior ↛ LLM / cognition.** No Decider/Analyst/Generator/Evaluator/llm/openai. Only sequences actuator ports + delay/cancel. |
| L5 | **Learning post-turn only.** `run_post_turn(turn_id)` after application decision branch (approve path → pending_approval; escalate path → escalated). Never inside Director. F1 = TRACE_KEYS completeness check; **no Staging**. |
| L6 | **Admin API is domain-shaped.** `handle_approve(turn_id, *, actor_id=None)`, `handle_correct(turn_id, corrected_text, ...)`. **No** `aiogram` types under `application/` or `behavior/`. |
| L7 | **Behavior deliver signature (MVP preferred):** `deliver(texts, ctx, turn_id, decision=None) -> DeliveryResult`. `turn_id` required for FK + cancel scope. |
| L8 | **Approve-after-supersede = no-op.** If turn status is terminal (`superseded`/`escalated`/`delivered`/`failed`), Admin does not deliver. |
| L9 | **Unit tests = pure fakes.** No live Telegram, no Postgres required for the item gate. In-memory stores implement repository ports. |
| L10 | **Do not edit** Decider matrix, EvaluationProfile, Director control flow, F1 schema migration, or create F2 tables. Cognitive purity remains: cognitive ↛ application/behavior/learning/telegram/aiogram. |
| L11 | **Status ownership:** Coordinator is the durable `TurnStatusSink` injected into Director (cognitive states analyzing…deciding). Orchestrator/Admin call coordinator for `received` / `pending_approval` / `escalated` / `delivered` / `superseded` / `failed`. |
| L12 | **`delivery_result` is not a TRACE_KEY.** Separate write after successful deliver (Admin/Behavior path). Learning checks TRACE_KEYS; may optionally note delivery_result when present. |

## Constraints

- **Strict TDD Mode active:** for each task surface, write **failing** unit tests first, then minimal implementation until green. Do **not** implement production code before the red tests exist for that task.
- **0 aiogram handlers / middlewares / main polling** (item 4).
- **0 Staging / gray zone / autonomous send / product sandbox.**
- **No schema migration rewrites** unless a hard FK gap forces it (none expected).
- Code/comments/identifiers: **English**.
- Prefer **work-unit commits** per task; if total diff > ~400 LOC, flag chained PR for item 4 boundary (handlers separate).
- Do not mock internal pure logic where Fake* doubles suffice.

## Tasks

### Task 1: Ports, in-memory stores, purity gates
**type:** auto  
**Objective:** Freeze I/O boundaries so application/behavior/learning stay free of aiogram and SQL in unit tests, and architecture edges are enforceable.

**TDD order:** purity + port-shape tests first (red) → implement modules → green.

**Files (create):**
- `src/diana/application/__init__.py`
- `src/diana/application/ports.py`
- `src/diana/application/memory.py` — in-memory repo doubles used by unit tests
- `src/diana/behavior/__init__.py`
- `src/diana/behavior/ports.py`
- `src/diana/behavior/fake.py` — `FakeTelegramActuator` / FakeDelivery recorder
- `src/diana/learning/__init__.py`
- `tests/unit/behavior/test_import_purity.py`
- `tests/unit/application/test_import_purity.py` (optional but recommended)
- `tests/unit/behavior/test_fake_delivery.py`
- `tests/unit/application/test_memory_stores.py` (thin: create/get/transition/cancel semantics of in-memory ports)

**Optional create (mechanical, only if needed for composition later; unit gate does not require Postgres):**
- `src/diana/infrastructure/db/repositories/__init__.py`
- Thin SQL adapters implementing the **same** ports as in-memory (defer full SQL coverage to item 4 if review budget tight). Prefer **not** expanding unit tests to need asyncpg.

**`application/ports.py` protocols (exact intent):**

```python
# OwnerNotifierPort — never aiogram types
async def notify_draft(payload: DraftNotification) -> int | None: ...  # returns owner_message_id optional
async def notify_escalation(payload: EscalationNotification) -> None: ...
async def notify_info(text: str, *, chat_id: int | None = None) -> None: ...

# TurnStore / TurnRepository
async def create(turn: TurnRecord) -> TurnRecord: ...
async def get(turn_id: UUID) -> TurnRecord | None: ...
async def list_non_terminal(chat_id: int) -> list[TurnRecord]: ...
async def transition(turn_id: UUID, status: str, *, superseded_by: UUID | None = None) -> TurnRecord: ...

# PendingApprovalStore
async def create_waiting(...) -> ApprovalRecord: ...
async def get_by_turn(turn_id: UUID) -> ApprovalRecord | None: ...
async def mark_status(turn_id: UUID, status: str) -> None: ...
async def cancel_waiting_for_chat(chat_id: int) -> int: ...  # count cancelled

# PendingDeliveryStore
async def insert_pending(...) -> DeliveryRecord: ...
async def update_status(delivery_id: UUID, status: str, **meta) -> None: ...
async def cancel_for_chat(chat_id: int) -> int: ...
async def list_pending() -> list[DeliveryRecord]: ...

# EscalationStore
async def create(turn_id: UUID, *, tipo: str, motivo: str | None) -> None: ...
async def mark_notified(turn_id: UUID) -> None: ...

# MessageHistoryWriter (or extend cognitive MessageHistoryPort carefully)
async def append(chat_id: int, *, role: str, text: str, telegram_message_id: int | None = None, timestamp: datetime | None = None) -> None: ...

# DeliveryResultWriter / Trace extension
async def set_delivery_result(turn_id: UUID, result: dict) -> None: ...
async def get_trace_keys(turn_id: UUID) -> set[str]: ...  # for Learning
```

**`behavior/ports.py` (exact intent):**

```python
class DeliveryContext(BaseModel):  # may live in behavior/models.py thin module
    chat_id: int
    business_connection_id: str
    vip_id: UUID | None = None
    mode: Literal["supervised"] = "supervised"
    telegram_message_id: int | None = None  # for read receipt target if needed

class DeliveryResult(BaseModel):
    success: bool
    message_ids: list[int] = []
    actual_delay_seconds: float = 0.0
    typing_duration_seconds: float = 0.0
    error: str | None = None
    cancelled: bool = False

class TelegramActuatorPort(Protocol):
    async def read_business_message(self, chat_id: int, message_id: int | None, *, business_connection_id: str) -> None: ...
    async def send_chat_action(self, chat_id: int, action: str, *, business_connection_id: str) -> None: ...
    async def send_message(self, chat_id: int, text: str, *, business_connection_id: str) -> int: ...  # returns message_id

class Clock(Protocol):
    def now(self) -> datetime: ...
    async def sleep(self, seconds: float) -> None: ...

class DelayPolicy(Protocol):
    def initial_delay_seconds(self) -> float: ...
    def typing_duration_seconds(self, text: str) -> float: ...
```

**Fake requirements:**
- `FakeTelegramActuator` records ordered call log; returns synthetic message ids; no network.
- `FixedDelayPolicy` / `ImmediateClock` (sleep no-op or virtual) for non-flaky tests.
- In-memory stores hold dicts; support supersede/cancel list operations used by Coordinator/Admin.

**MessageHistory append lock:**
- Prefer **additive** `append` on a writer protocol in `application/ports.py` **or** extend `InMemoryMessageHistory` in tests without breaking `get_recent`.
- If extending `MessageHistoryPort` in `cognitive/ports.py`, keep it Protocol-compatible and update `InMemoryMessageHistory` — **do not** put SQL into cognitive.

**Purity tests:**
- `behavior/**` forbids: `diana.llm`, `openai`, `diana.cognitive.analyst|generator|evaluator|decider|director`, `aiogram` (prefer).
- `application/**` forbids: `aiogram` (if policy: no handlers leak).
- Cognitive purity test **must remain green** (already forbids application/behavior/learning).

**Do NOT:**
- Implement Coordinator/Orchestrator/Admin/Engine logic in this task beyond store helpers.
- Create telegram package handlers.
- Call live network.

**Verification:**
```bash
pytest tests/unit/behavior/test_import_purity.py tests/unit/behavior/test_fake_delivery.py -q
pytest tests/unit/application/test_memory_stores.py -q
pytest tests/unit/cognitive/test_import_purity.py -q
pytest tests/unit -q   # 150 baseline still green
```

---

### Task 2: TurnCoordinator (lifecycle + supersede cascade)
**type:** auto  
**Objective:** Guarantee **exactly one non-terminal turn per `chat_id`** and own durable status transitions including Director sink + supersede cancel hooks.

**TDD order:** `test_turn_coordinator.py` failing cases first → implement `turn_coordinator.py`.

**Files (create):**
- `src/diana/application/turn_coordinator.py`
- `tests/unit/application/test_turn_coordinator.py`

**API (lock):**

```python
class TurnCoordinator:
    def __init__(
        self,
        turns: TurnStore,
        approvals: PendingApprovalStore,
        behavior: BehaviorCanceller,  # Protocol with cancel_pending only — avoid circular import
        *,
        locks: ChatLockProvider | None = None,  # per-chat asyncio.Lock
    ): ...

    async def begin_turn(
        self,
        *,
        chat_id: int,
        trigger_message_id: int | None = None,
        vip_id: UUID | None = None,
        turn_id: UUID | None = None,  # mint inside if None
    ) -> TurnRecord:
        """
        Atomic sequence (in-process lock per chat_id):
        1. list_non_terminal(chat_id)
        2. for each: transition → SUPERSEDED with superseded_by=new_id
        3. await behavior.cancel_pending(chat_id)
        4. approvals.cancel_waiting_for_chat(chat_id)
        5. create Turn(status=received, id=new_id)
        6. return TurnRecord
        """

    async def transition(self, turn_id: UUID, status: str | TurnStatus, **meta) -> TurnRecord: ...
    async def mark_failed(self, turn_id: UUID, error: str | None = None) -> TurnRecord: ...

    # TurnStatusSink adapter for Director injection
    async def transition_sink(self, turn_id: UUID, status: str | TurnStatus) -> None:
        await self.transition(turn_id, status)
```

**Required tests:**
1. First `begin_turn` → status `received`; only one non-terminal.
2. Second `begin_turn` same chat → previous `superseded` + `superseded_by` set; new `received`.
3. Supersede calls `cancel_pending` **once** for that chat.
4. Supersede cancels waiting approvals for that chat.
5. Concurrent `begin_turn` same chat (asyncio gather) → still **one** non-terminal at end.
6. `transition` to `pending_approval` / `escalated` / `delivered` / `failed` works; invalid free-text optional strictness OK if documented.
7. Coordinator implements usable sink: after `transition_sink(id, ANALYZING)` store shows analyzing.

**Behavior dependency for this task:** inject a **minimal cancel fake** (`AsyncMock` or tiny `FakeCanceller`) — full BehaviorEngine comes in Task 3. Coordinator must only need `cancel_pending`.

**Do NOT:**
- Call Director from Coordinator.
- Auto-deliver anything.
- Write Learning.

**Verification:**
```bash
pytest tests/unit/application/test_turn_coordinator.py -q
pytest tests/unit/cognitive/test_import_purity.py -q
```

---

### Task 3: BehaviorEngine deliver + cancel (ports only)
**type:** auto  
**Objective:** Act messages human-like via ports; support mid-flight cancel; never decide action or call LLM.

**TDD order:** `test_engine.py` red → implement `engine.py` (+ optional thin `timer_manager.py`).

**Files (create):**
- `src/diana/behavior/engine.py`
- `src/diana/behavior/timer_manager.py` (optional — may live inside engine if thin)
- `tests/unit/behavior/test_engine.py`

**API (lock — MVP shape):**

```python
class BehaviorEngine:
    def __init__(
        self,
        actuator: TelegramActuatorPort,
        deliveries: PendingDeliveryStore,
        *,
        clock: Clock,
        delay_policy: DelayPolicy,
        # optional: delivery_result writer callback/port
    ): ...

    async def deliver(
        self,
        texts: list[str],
        ctx: DeliveryContext,
        turn_id: UUID,
        decision: Decision | None = None,
    ) -> DeliveryResult:
        """
        1. Validate business_connection_id non-empty; else return success=False error
        2. insert pending_deliveries (status=pending, turn_id FK, texts, decision dump)
        3. Run sequence (awaitable; cancel-aware):
           - sleep(initial_delay)
           - read_business_message (if message id known)
           - typing action + sleep(typing_duration)
           - send_message for each text
           - mark delivery done
        4. On CancelledError: mark cancelled; return cancelled=True
        """

    async def cancel_pending(self, chat_id: int, reason: str = "new_message") -> None:
        """Cancel in-flight tasks for chat_id + mark pending/delivering rows cancelled. Idempotent."""
```

**Required tests:**
1. Happy path sequence order with FakeActuator + FixedDelay: delay → read → typing → send (one text).
2. Multi-text: one send per text; message_ids collected.
3. `cancel_pending` during sleep/delay → no send; delivery status `cancelled`; result cancelled or no orphan pending.
4. Idempotent double-cancel does not raise.
5. Missing `business_connection_id` → fail closed (no send).
6. Purity still green for behavior package.
7. **No** import of llm modules (static purity already).

**Delay flakiness:** FixedDelayPolicy returns `0` or tiny constants; Clock.sleep is awaitable no-op or records requested delays without wall-clock wait.

**Do NOT:**
- Import cognitive decision components or llm.
- Call Admin or Learning.
- Use real aiogram Bot.

**Verification:**
```bash
pytest tests/unit/behavior -q
pytest tests/unit/behavior/test_import_purity.py -q
```

---

### Task 4: AdminService + TurnOrchestrator + Learning + recovery helpers
**type:** auto  
**Objective:** Wire the F1 supervised use-case: VIP message → Director → approve queue or escalate notify; owner resolve → deliver; post-turn TRACE_KEYS check; recovery classification helpers for item 4 restart.

**TDD order (Strict TDD):**
1. `test_admin_service.py` red → Admin
2. `test_turn_orchestrator.py` red → Orchestrator
3. `test_post_turn.py` red → Learning
4. `test_recovery.py` red → recovery helpers
5. Implement each until green; then integration-style assertions across modules with fakes.

**Files (create):**
- `src/diana/application/admin_service.py`
- `src/diana/application/turn_orchestrator.py`
- `src/diana/application/recovery.py`
- `src/diana/learning/post_turn.py`
- `tests/unit/application/test_admin_service.py`
- `tests/unit/application/test_turn_orchestrator.py`
- `tests/unit/application/test_recovery.py`
- `tests/unit/learning/test_post_turn.py`

**AdminService API (lock):**

```python
class AdminService:
    def __init__(self, notifier: OwnerNotifierPort, approvals: PendingApprovalStore,
                 escalations: EscalationStore, coordinator: TurnCoordinator,
                 behavior: BehaviorEngine, traces: DeliveryResultWriter, ...): ...

    async def send_draft_for_approval(self, turn: IncomingTurn, decision: Decision, turn_id: UUID) -> None:
        # persist pending_approvals waiting; notify_draft with VIP text + draft + eval summary
        # require non-empty business_connection_id

    async def notify_escalation(self, turn: IncomingTurn, decision: Decision, turn_id: UUID) -> None:
        # escalation_events tipo=semantica (or from decision.reason); notify_escalation

    async def handle_approve(self, turn_id: UUID, *, actor_id: int | None = None) -> DeliveryResult | None:
        # reload turn; if terminal (superseded/escalated/delivered/failed) → None, no deliver
        # load approval draft_text; behavior.deliver([draft], ctx, turn_id, decision?)
        # mark approval approved; coordinator.transition delivered; set_delivery_result

    async def handle_correct(self, turn_id: UUID, corrected_text: str, *, actor_id: int | None = None) -> DeliveryResult | None:
        # same terminal guard; deliver corrected_text only; mark corrected; NO Staging
```

**TurnOrchestrator API (lock):**

```python
class TurnOrchestrator:
    def __init__(self, coordinator, director, admin, learning, history_writer, ...): ...

    async def handle_vip_message(self, incoming: VipMessageDTO | IncomingTurn-shaped) -> UUID:
        """
        1. begin_turn → TurnRecord (mint turn_id)
        2. history.append role=vip
        3. build IncomingTurn(turn_id=record.id, chat_id=..., text=..., business_connection_id=..., ...)
        4. try: decision = await director.handle_turn(incoming_turn)
           except: mark_failed; re-raise  (Learning NOT required on hard fail)
        5. if approve:
              coordinator.transition(pending_approval)
              admin.send_draft_for_approval(...)
              # ASSERT path: deliver NOT called
           elif escalate:
              coordinator.transition(escalated)
              admin.notify_escalation(...)
           else: raise ValueError unexpected F1 action
        6. await learning.run_post_turn(turn_id)
        7. return turn_id
        """
```

**Vip message input:** Prefer a small application DTO (`VipInboundMessage`) with fields needed to build `IncomingTurn` + history (chat_id, text, telegram_message_id, business_connection_id, vip_id optional). Orchestrator mints UUID — **never** call Director without turn_id.

**FakeDirector for tests:** simple object with `async def handle_turn(self, turn: IncomingTurn) -> Decision` returning scripted approve/escalate — **do not** require full cognitive stack for orchestrator unit tests. Optional one integration test with real CognitiveDirector + FakeLLM is nice-to-have, not required for DoD if orchestrator + admin golds pass.

**LearningService (lock):**

```python
class LearningService:
    def __init__(self, traces: TraceReader): ...  # get keys / get TRACE_KEYS presence

    async def run_post_turn(self, turn_id: UUID) -> PostTurnReport:
        # Ensure all TRACE_KEYS present; return report {complete: bool, missing: list[str]}
        # No Staging writes; no promotion; no examples table
```

**Recovery helpers (lock — classification only):**

```python
# recovery.py
async def classify_pending_deliveries(
    store: PendingDeliveryStore,
    *,
    now: datetime,
    stale_after: timedelta,
) -> RecoveryPlan:
    # pending rows:
    #   scheduled_at older than stale_after → mark expired (or list as to_expire)
    #   fresh → list as recoverable DTOs for item 4 to reschedule Tasks
    # ignore done/cancelled/expired

async def list_waiting_approvals(approvals: PendingApprovalStore) -> list[ApprovalRecord]:
    # for item 4 re-notify only — no auto-approve, no deliver
```

**Required tests (gold — map to risks R1–R5):**

| # | Assertion |
|---|-----------|
| R1 | After `handle_vip_message` with FakeDirector(approve): Admin notify_draft called; **Behavior.deliver call count == 0**; turn status `pending_approval`. |
| R2 | Turn A pending_approval; message B → A superseded; approval cancelled; cancel_pending called; B received. |
| R3 | behavior purity already; engine has no llm. |
| R4 | `run_post_turn` called once after orchestrator branch; Director source still free of learning imports. |
| R5 | After supersede A, `handle_approve(A)` → no deliver. |
| | Escalate path: status escalated; escalation notify; no deliver. |
| | `handle_correct` delivers corrected text; draft not sent; no staging module/side effect. |
| | Director exception → mark_failed + re-raise; deliver not called. |
| | Learning: TRACE_KEYS all present → complete; missing key → report missing (no crash required if documented). |
| | Recovery: stale pending → expired/classified; fresh → recoverable; cancelled ignored. |
| | Orchestrator validates missing business_connection_id before Admin/Behavior when needed (fail turn or raise — pick one, test it). |

**Do NOT:**
- Implement telegram handlers, keyboards as aiogram objects (payload specs as plain dicts/dataclasses OK).
- Write `staging_candidates` or import F2 concepts.
- Auto-send on approve.
- Call Learning from Director.

**Verification:**
```bash
pytest tests/unit/application tests/unit/behavior tests/unit/learning -q
pytest tests/unit/cognitive/test_import_purity.py tests/unit/behavior/test_import_purity.py -q
pytest tests/unit -q
# expect: ≥ 150 baseline + all new tests green
```

---

## Instrucciones para gsd-executor

### Patterns to copy
- **Ports + Fake doubles** from cognitive item 2 (`InMemoryTraceStore`, `FakeLLM`) — same style for Telegram/owner I/O.
- **Strict TDD:** red test file → minimal production → green → next surface.
- **Purity AST scan** pattern in `tests/unit/cognitive/test_import_purity.py` — replicate for `behavior/`.
- Director contract docstring in `director.py` — application **must** mint `turn_id` first.
- `Decision.action` only `approve` | `escalate` — branch exhaustively; never invent `send`.

### Anti-patterns (reject)
- Orchestrator calling `deliver` on approve.
- Admin methods accepting `CallbackQuery` / aiogram types.
- Behavior importing LLM or Decider.
- Learning inside Director pipeline.
- Staging writes on correct path.
- Two-arg `handle_turn(turn, incoming)`.
- Collapsing EvaluationProfile to a score for DM summary is OK as **display-only strings**, but never feed a mean into Decider (Decider already ran).
- Schema / Alembic rewrites for convenience.
- Live Telegram or live Postgres in unit gate.

### Logging
- Prefer structured `logging.getLogger("diana.application"|".behavior"|".learning")`.
- Log turn_id + chat_id on begin, supersede, approve, cancel — no secrets/tokens.

### DI / composition in tests
- Build graph manually in fixtures:
  - Fake actuator + FixedDelay + InMemory stores → BehaviorEngine
  - Coordinator(turns, approvals, behavior)
  - FakeDirector or full Director with FakeLLM + Coordinator as status_sink
  - Admin(notifier fake, …)
  - Orchestrator(coordinator, director, admin, learning, history)
- No global singletons.

### Commits
- Conventional commits, **no** AI co-authored trailers.
- Suggested work units:
  1. `test(application): ports, fakes, purity`
  2. `feat(application): turn coordinator supersede cascade`
  3. `feat(behavior): engine deliver cancel + fake actuator`
  4. `feat(application): admin orchestrator learning recovery`
- If LOC > 400 and review pressure: stop after Task 3 and open chained plan for Task 4 only (not preferred — supersede needs Admin cancel too; keep one PR if possible).

### Out of scope handoff to item 4
- aiogram handlers/middlewares, `main.py` polling, restart Task rehydration scheduler calling recovery helpers, owner keyboard builders as Telegram markup, ForbiddenKeywords middleware (may call a thin orchestrator helper if you add `handle_deterministic_escalation` — optional, not required).

## Test commands

```bash
cd /home/ubuntu/repos/DianaV2

# Full unit gate (regression + new)
pytest tests/unit -q

# Item 3 packages only
pytest tests/unit/application tests/unit/behavior tests/unit/learning -q

# Architecture golds
pytest tests/unit/cognitive/test_import_purity.py tests/unit/behavior/test_import_purity.py -q
pytest tests/unit/cognitive/test_models.py tests/unit/cognitive/test_evaluation_profile_invariants.py -q
pytest tests/unit/cognitive/test_director.py tests/unit/cognitive/test_decider.py -q
pytest tests/unit/infrastructure/test_f1_schema_metadata.py -q
```

Flags: project uses `asyncio_mode = auto` and `pythonpath = ["src"]` in `pyproject.toml`. No extra plugins required.

**No live network / no Telegram / no Postgres** for the unit gate.

## Risks + Mitigation

| ID | Risk | Mitigation in this plan |
|----|------|-------------------------|
| R1 | Auto-send on approve | Task 4 test: deliver count == 0 after orchestrator approve path |
| R2 | Supersede skips cancel | Task 2 cascade + Task 4 end-to-end supersede |
| R3 | Behavior LLM | Task 1 purity + Task 3 ports-only engine |
| R4 | Learning mid-pipeline | Task 4 only Orchestrator calls run_post_turn; cognitive purity |
| R5 | Approve after supersede | Admin terminal guard + test |
| R7 | Concurrent VIP msgs | per-chat asyncio.Lock in Coordinator + concurrent test |
| R8 | Null business_connection_id | validate before Admin/Behavior |
| R11 | Dual status writers | Coordinator sole durable sink |
| R14 | Recovery double-send | helpers classify only; no auto-send |
| R18 | Correct → Staging | handle_correct delivers text only; assert no staging |
| R19 | Flaky delays | FixedDelayPolicy + fake Clock |
| R24 | Review budget | work-unit commits; SQL repos optional/deferred |

## Success Criteria

- [ ] Packages `src/diana/application/`, `behavior/`, `learning/` exist with ports + implementations above.
- [ ] `TurnCoordinator.begin_turn` supersedes non-terminal, cancels deliveries + waiting approvals, creates `received`.
- [ ] `TurnOrchestrator.handle_vip_message` mints `turn_id` **before** `director.handle_turn`; approve → `pending_approval` + owner notify; **never** auto-deliver.
- [ ] `AdminService.handle_approve` / `handle_correct` are the only deliver gates; terminal/superseded → no-op.
- [ ] `BehaviorEngine` sequences via `TelegramActuatorPort`; FakeDelivery/FakeActuator used in tests; no LLM imports.
- [ ] `LearningService.run_post_turn` checks TRACE_KEYS only; no Staging.
- [ ] Recovery helpers classify stale vs recoverable pending deliveries without sending.
- [ ] Purity: cognitive + behavior import gates green.
- [ ] `pytest tests/unit -q` green with **≥ 150** prior tests + all new application/behavior/learning tests.
- [ ] No aiogram handlers, no F2 tables, no Decider/Director control-flow edits.

## DoD checklist for arch-enforcer / test-guardian

- [ ] TAC-05 Behavior outside cognition
- [ ] TAC-07 supersede + cancel covered
- [ ] TAC-04 traces + delivery_result path defined
- [ ] BR-11 Learning only post-turn
- [ ] F1 Decision actions unchanged (approve|escalate only)
- [ ] Dependency arrows match AGENTS §3.2
