---
phase: 04
plan: telegram-wiring
type: auto
item: 4/4
effort: 6-7
stack: python>=3.12, aiogram>=3,<4, sqlalchemy[asyncio], asyncpg, pydantic-v2, pytest-asyncio
depends_on: 01-foundation, 02-cognitive-core, 03-application-behavior
strict_tdd: true
delivery_note: prefer work-unit commits; optional chained-PR if LOC >400 (repos → telegram → acceptance)
---

## Objective

Close F1 by wiring the pure application/behavior/cognitive shell to **real Telegram I/O** (aiogram 3.x long-polling) and **Postgres-backed stores**: middleware stack F1, business/admin/callback handlers, SQLAlchemy adapters with CAS parity to InMemory, composition root, and **safe** startup recovery (re-notify waiting approvals; **never** silent VIP re-send / auto-approve). No FreezeCheck, Staging, gray zone, or autonomous `send`.

## Context

@`.grok/agent-memory/impact-analyzer/04-telegram-wiring.md`
@`.planning/phases/03-application-behavior/PLAN.md`
@`.planning/phases/03-application-behavior/SUMMARY.md`
@`docs/MVP_COMPONENT_DESIGN.md` (§5.1 middleware order F1; §9 package tree)
@`AGENTS.md` (§3–6 module limits; §4.1–4.2 VIP + forbidden short-circuit)
@`src/diana/application/ports.py` (DTOs + store protocols; CAS `claim_waiting`)
@`src/diana/application/admin_service.py` (`handle_approve` / `handle_correct` / `OwnerAuthError`; sole deliver gate)
@`src/diana/application/turn_orchestrator.py` (`handle_vip_message(VipInboundMessage) -> UUID`; never deliver on approve)
@`src/diana/application/recovery.py` (`classify_pending_deliveries`, `list_waiting_approvals` — classify only)
@`src/diana/application/memory.py` (gold CAS + delivery transition table + terminal latch)
@`src/diana/behavior/ports.py` (`TelegramActuatorPort`, `DeliveryContext`)
@`src/diana/cognitive/director.py` (single-arg `handle_turn(IncomingTurn)`)
@`src/diana/infrastructure/db/models.py` (8 ORM tables; no `turns.error` / `pending_approvals.trigger_message_id` columns)
@`src/diana/config.py` (`Settings`: token, owner_telegram_id, database_url, LLM keys)
@`tests/unit/cognitive/test_import_purity.py`
@`tests/unit/application/test_application_import_purity.py`
@`tests/unit/behavior/test_behavior_import_purity.py`

**Repo state:** foundation + cognitive + application/behavior/learning DONE (**209** unit tests). Packages `telegram/` and `main.py` **absent**. SQL repository adapters **deferred** from item 3. Recovery helpers classify only.

**Locked decisions (NON-NEGOTIABLE):**

| ID | Decision |
|----|----------|
| L1 | **Middleware order F1 only:** Logging → BusinessConnection → OwnerDetection → ForbiddenKeywords → Auth → handlers. **No FreezeCheck** (F2). Prefer MVP §5.1 over AGENTS §6.5 Freeze slot. |
| L2 | **No auto-send.** VIP path → `TurnOrchestrator.handle_vip_message` only. Deliver **only** via Admin `handle_approve` / `handle_correct`. Handlers never invent `Decision.action` or call Behavior.deliver. |
| L3 | **Recovery: no silent re-send without owner.** Startup: expire `delivering` + stale pending via `classify_pending_deliveries`; for recoverable pending → **expire + owner `notify_info`** (or leave expired only). Re-notify `list_waiting_approvals` via `notify_draft` / info. **Never** auto-approve, never call Director on startup, never resume Behavior.deliver without a fresh owner action. |
| L4 | **Purity:** `application/`, `cognitive/`, `behavior/`, `learning/` **never** import `aiogram` or (except composition root) depend on `diana.telegram`. Adapters live under `telegram/` + `infrastructure/db/repositories/`. |
| L5 | **SQL adapters with CAS.** `claim_waiting` = `UPDATE … SET status='claimed' WHERE turn_id=? AND status='waiting' RETURNING *` (or equivalent). Delivery `update_status` respects `_DELIVERY_TRANSITIONS`. Turn `transition` has **terminal latch** (mirror `InMemoryTurnStore`). |
| L6 | **Deterministic forbidden escalate without Director.** Forbidden middleware match → application helper creates escalated turn + EscalationStore + owner notify; **zero** Director/LLM calls. |
| L7 | **F1 Decision.action ∈ {approve, escalate}** only. Telegram must not invent `send` / `consult_doctrine` / `regenerate`. |
| L8 | **Owner-only callbacks.** Always pass `callback.from_user.id` as `actor_id`; map `OwnerAuthError` to deny/ignore. |
| L9 | **business_connection_id required** on VIP Business I/O; missing BC → fail closed (orchestrator already raises). |
| L10 | **Unit gate = no live Telegram / no real network.** MagicMock Bot / FakeActuator / FakeOwnerNotifier. Postgres optional via `@pytest.mark.integration`; unit SQL tests use pure logic doubles or skip if no PG. |
| L11 | **Schema gaps without F2 tables:** do **not** rewrite `001_f1_foundation`. Prefer join `turns.trigger_message_id` for mark-as-read; store turn `error` in logs only (domain field may stay memory-only) **or** additive `002_item4_gaps.py` if executor chooses — either is OK if documented. No Staging/gray/freeze tables. |
| L12 | **Do not edit** Decider matrix, EvaluationProfile, Director control flow, BehaviorEngine deliver semantics, or Learning beyond wiring TraceReader. |

## Constraints

- **Strict TDD Mode active:** for each task, write **failing** unit tests first, then minimal implementation until green. No production code before red tests for that surface.
- **0 F2:** FreezeCheck, Staging, gray zone, autonomous `send`, product sandbox, REE/promo/recontact.
- Code/comments/identifiers: **English**.
- Prefer **work-unit commits** per task; if total diff > ~400 LOC, recommend chained PR: (A) app gaps + SQL, (B) telegram, (C) composition/acceptance.
- Do not mock internal cognitive pure logic; FakeLLM / FakeActuator / Fake Bot OK.
- Composition root (`composition.py` / `main.py`) may import all layers; cognitive/application/behavior purity tests must stay green.

## Tasks

### Task 1: Application gaps — VipStore, deterministic escalate, owner escalate
**type:** auto  
**Objective:** Close missing domain APIs so telegram middlewares/handlers never call Director for forbidden paths and can manage allowlist + owner discard-escalate without inventing decisions.

**TDD order:** red tests → minimal application changes → green. **No** aiogram in this task.

**Files (create/edit):**
- `src/diana/application/ports.py` — add `VipStore` protocol + thin VIP DTO if needed
- `src/diana/application/memory.py` — `InMemoryVipStore`
- `src/diana/application/admin_service.py` — `handle_owner_escalate(turn_id, *, actor_id)`
- `src/diana/application/deterministic_escalate.py` (or helper on orchestrator/admin — **outside** cognitive) — forbidden path entry
- `tests/unit/application/test_vip_store.py`
- `tests/unit/application/test_deterministic_escalate.py`
- `tests/unit/application/test_admin_owner_escalate.py` (or extend `test_admin_service.py`)

**VipStore protocol (exact intent):**

```python
class VipRecord(BaseModel):
    id: UUID
    telegram_user_id: int
    display_name: str | None = None
    is_active: bool = True
    paused_until: datetime | None = None

@runtime_checkable
class VipStore(Protocol):
    async def get_by_telegram_user_id(self, telegram_user_id: int) -> VipRecord | None: ...
    async def is_allowed(self, telegram_user_id: int, *, now: datetime | None = None) -> bool:
        """True iff VIP exists, is_active, and not paused (paused_until is None or < now)."""
        ...
    async def add(self, telegram_user_id: int, *, display_name: str | None = None) -> VipRecord: ...
    async def deactivate(self, telegram_user_id: int) -> bool: ...  # soft remove / is_active=False
```

**Deterministic escalate helper (lock — no Director):**

```python
async def handle_deterministic_escalation(
    *,
    coordinator: TurnCoordinator,
    escalations: EscalationStore,
    notifier: OwnerNotifierPort,
    chat_id: int,
    text: str,
    vip_id: UUID | None,
    business_connection_id: str | None,
    message_id: int | None,
    keywords_hit: list[str],
) -> UUID:
    """
    1. begin_turn (mint turn_id; supersede cascade OK)
    2. transition → escalated (no Director)
    3. EscalationStore.create(tipo='palabra_prohibida' or 'forbidden', motivo=keywords)
    4. notifier.notify_escalation(...)
    5. mark_notified
    6. return turn_id
    Never call CognitiveDirector or LLM.
    """
```

**AdminService.handle_owner_escalate (lock):**

```python
async def handle_owner_escalate(self, turn_id: UUID, *, actor_id: int | None = None) -> None:
    # _assert_owner
    # under chat_scope: if turn missing/terminal → no-op
    # claim or cancel waiting approval (mark cancelled); do NOT deliver
    # coordinator.transition(escalated); optional notify_info
```

**Required tests:**
1. VipStore: add → is_allowed True; deactivate → False; paused_until future → False.
2. Deterministic escalate: creates escalated turn; EscalationStore event; notifier called; **Director never invoked** (no director in helper deps).
3. Owner escalate: waiting approval → cancelled; turn escalated; Behavior.deliver call count == 0.
4. Owner escalate non-owner → OwnerAuthError.
5. `test_application_import_purity` still forbids aiogram.

**Do NOT:**
- Create telegram package or SQL adapters yet.
- Call Behavior.deliver from forbidden path.
- Add FreezeCheck / Staging.

**Verification:**
```bash
.venv/bin/pytest tests/unit/application/test_vip_store.py \
  tests/unit/application/test_deterministic_escalate.py \
  tests/unit/application/test_admin_owner_escalate.py \
  tests/unit/application/test_application_import_purity.py -q
.venv/bin/pytest tests/unit/application tests/unit/behavior tests/unit/learning -q
```

---

### Task 2: SQLAlchemy adapters with CAS (+ schema-gap policy)
**type:** auto  
**Objective:** Implement production stores behind the **same** application/cognitive ports used by item 3 InMemory doubles, with atomic CAS and terminal/delivery machines.

**TDD order:** contract/parity tests first (red) → implement repos → green. Prefer testing transition/CAS logic without requiring live Postgres in the unit gate; optional `@pytest.mark.integration` for real asyncpg.

**Files (create):**
- `src/diana/infrastructure/db/repositories/__init__.py`
- `src/diana/infrastructure/db/repositories/turns.py` — `SqlTurnStore`
- `src/diana/infrastructure/db/repositories/approvals.py` — `SqlPendingApprovalStore`
- `src/diana/infrastructure/db/repositories/deliveries.py` — `SqlPendingDeliveryStore`
- `src/diana/infrastructure/db/repositories/escalations.py` — `SqlEscalationStore`
- `src/diana/infrastructure/db/repositories/history.py` — `SqlMessageHistoryRepo` (append + get_recent)
- `src/diana/infrastructure/db/repositories/traces.py` — TraceStore + DeliveryResultWriter + TraceReader
- `src/diana/infrastructure/db/repositories/vips.py` — `SqlVipStore`
- `src/diana/infrastructure/db/repositories/system_config.py` — read `forbidden_keywords` (+ optional eval thresholds)
- `tests/unit/infrastructure/test_delivery_transitions.py` — pure table parity (can import shared transition constants)
- `tests/unit/infrastructure/test_approval_cas_semantics.py` — CAS semantics tests (InMemory gold + SQL logic helpers)
- Optional: `tests/unit/infrastructure/test_sql_repo_shapes.py` — session factory wiring smoke with mocks
- Optional only if chosen: `alembic/versions/002_item4_gaps.py` — additive `turns.error` / `pending_approvals.trigger_message_id`

**CAS / machine requirements (mirror memory.py):**

| Port method | SQL semantics |
|-------------|---------------|
| `PendingApprovalStore.claim_waiting` | `UPDATE pending_approvals SET status='claimed' WHERE turn_id=:id AND status='waiting' RETURNING *` → row or None |
| `PendingDeliveryStore.update_status` | Read current status; allow only `_DELIVERY_TRANSITIONS`; return False if forbidden (do not raise for illegal transition) |
| `TurnStore.transition` | Terminal latch: if current status ∈ TERMINAL and new ≠ current → return current unchanged |
| `list_non_terminal` | Filter statuses not in TERMINAL_TURN_STATUSES |
| `cancel_waiting_for_chat` | waiting + claimed → cancelled |
| `TraceStore.store` | Upsert cognitive TRACE_KEYS into `pipeline_traces` columns by turn_id |
| `set_delivery_result` | Separate UPDATE of `delivery_result` JSONB only |

**Schema-gap policy (lock default):**
1. `ApprovalRecord.trigger_message_id`: **join/read from `turns.trigger_message_id`** when loading approval if column absent — do not require migration.
2. `TurnRecord.error`: log + ignore column if absent; `mark_failed` still transitions status to `failed`.
3. Do **not** rewrite `001_f1_foundation.py`.

**Session pattern:** constructor takes `async_sessionmaker` or session factory; each method opens short-lived session, commit on success, rollback on error. Handlers/composition inject factory — **no** SQL in handlers.

**Required tests:**
1. Delivery transition matrix: legal pending→delivering/cancelled/expired; illegal done→pending returns False.
2. CAS claim: only first claim wins (InMemory gold; SQL unit with mocked execute returning row / empty).
3. Terminal latch: delivered turn cannot transition to analyzing.
4. VipStore SQL adapter maps ORM Vip → VipRecord (mock or pure mapper tests).
5. History get_recent ordered by timestamp DESC then reversed to chronological list (match cognitive HistoryRetriever expectations).
6. No aiogram imports under `infrastructure/`.

**Do NOT:**
- Implement telegram handlers in this task.
- Auto-promote Staging.
- Require live Postgres for the unit gate (mark integration separately if added).

**Verification:**
```bash
.venv/bin/pytest tests/unit/infrastructure -q
.venv/bin/pytest tests/unit/application/test_memory_stores.py -q
.venv/bin/pytest tests/unit -q   # 209 baseline still green + new
```

---

### Task 3: Telegram adapters + F1 middlewares + handlers
**type:** auto  
**Objective:** Map Telegram I/O to application domain APIs; enforce middleware order and short-circuits; keep handlers thin.

**TDD order (Strict TDD):**
1. Middleware order / registration tests red
2. Each middleware gold (BC, owner, forbidden, auth) red → implement
3. Actuator + notifier + keyboards red → implement
4. Handlers business/callbacks/admin red → implement

**Files (create):**
- `src/diana/telegram/__init__.py`
- `src/diana/telegram/actuator.py` — `AiogramTelegramActuator(TelegramActuatorPort)`
- `src/diana/telegram/notifier.py` — `AiogramOwnerNotifier(OwnerNotifierPort)`
- `src/diana/telegram/keyboards.py` — compact callback_data `a:{uuid}` / `c:{uuid}` / `e:{uuid}` (≤64 bytes)
- `src/diana/telegram/middlewares/logging.py`
- `src/diana/telegram/middlewares/business_connection.py`
- `src/diana/telegram/middlewares/owner.py`
- `src/diana/telegram/middlewares/forbidden.py`
- `src/diana/telegram/middlewares/auth.py`
- `src/diana/telegram/handlers/business.py`
- `src/diana/telegram/handlers/admin.py`
- `src/diana/telegram/handlers/callbacks.py`
- `src/diana/telegram/setup.py` (or `dispatcher.py`) — register order + routers
- `tests/unit/telegram/test_middleware_stack.py`
- `tests/unit/telegram/test_business_connection_mw.py`
- `tests/unit/telegram/test_owner_mw.py`
- `tests/unit/telegram/test_forbidden_mw.py`  **← gold TAC-06**
- `tests/unit/telegram/test_auth_mw.py`
- `tests/unit/telegram/test_actuator.py`
- `tests/unit/telegram/test_notifier.py`
- `tests/unit/telegram/test_business_handler.py`
- `tests/unit/telegram/test_callbacks.py`
- `tests/unit/telegram/test_admin_commands.py`
- Unique purity name if needed: `tests/unit/telegram/test_telegram_layer_scope.py` (telegram **may** import aiogram; application/behavior still must not)

**Middleware order (register exactly):**

```
1. LoggingMiddleware
2. BusinessConnectionExtractor   # inject business_connection_id into data
3. OwnerDetectionMiddleware      # owner → cancel_pending + observe; stop VIP pipeline
4. ForbiddenKeywordsMiddleware   # match → handle_deterministic_escalation; stop
5. AuthMiddleware                # VipStore.is_allowed; inject vip_id; drop if false
6. → handlers
```

**Handler contracts:**
- **business:** build `VipInboundMessage(chat_id, text, telegram_message_id, business_connection_id, vip_id)` → `await orchestrator.handle_vip_message(...)`. No local decision logic.
- **callbacks:** parse action + turn_id; `admin.handle_approve` / start correct FSM or prompt / `handle_owner_escalate`; catch `OwnerAuthError`.
- **admin commands:** owner-only `/start`, `/menu`, add/remove VIP via VipStore; non-owner ignored.
- **correct UX:** minimal FSM (owner_id → awaiting turn_id) with timeout/supersede cancel; domain still `handle_correct(turn_id, text, actor_id=...)`.

**Actuator lock:** every Bot Business call passes `business_connection_id=`; missing → fail closed without send.

**Required tests (golds):**
1. Middleware registration order matches F1 list; Freeze absent.
2. Forbidden match → escalate helper once; **0** Director/LLM calls; orchestrator not called.
3. Auth non-VIP → orchestrator not called.
4. Owner message → cancel_pending; orchestrator not called.
5. Business handler maps DTO and calls orchestrator once.
6. Approve callback with FakeActuator: after approve, send_message count ≥ 1; **without** approve path from VIP-only, send == 0 (MVP-01 partial via composed fakes).
7. Non-owner callback → OwnerAuthError handled; no deliver.
8. Actuator tests assert `business_connection_id` kwarg on mock Bot.
9. Notifier draft markup includes turn_id action codes.

**Do NOT:**
- Import aiogram from application/behavior/cognitive.
- Auto-send on draft notification.
- Implement product Freeze middleware.
- Live Telegram network in unit tests.

**Verification:**
```bash
.venv/bin/pytest tests/unit/telegram -q
.venv/bin/pytest tests/unit/application/test_application_import_purity.py \
  tests/unit/behavior/test_behavior_import_purity.py \
  tests/unit/cognitive/test_import_purity.py -q
```

---

### Task 4: Composition + main + recovery startup + acceptance mapping
**type:** auto  
**Objective:** Wire Settings → SQL repos → Director → Orchestrator → Behavior → Admin → Dispatcher; run safe recovery on boot; codify automatable TAC/MVP checks; keep full unit suite green.

**TDD order:** recovery startup helper tests + acceptance mapping red → composition/main → green.

**Files (create/edit):**
- `src/diana/composition.py` (or `bootstrap.py`) — `build_app(settings) -> AppContainer`
- `src/diana/main.py` — logging, engine/session factory, build_app, `run_startup_recovery`, aiogram polling
- `src/diana/application/recovery_startup.py` (thin orchestration over existing recovery helpers) **or** function in composition
- `tests/unit/application/test_recovery_startup.py`
- `tests/unit/acceptance/test_tac_mvp_f1.py`
- Optional: `tests/unit/test_composition_import_boundaries.py` (import composition must not break cognitive purity tests when cognitive package scanned alone)
- Optional: `README.md` / `.env.example` run notes for long-polling
- Optional Settings: `recovery_stale_minutes` (default OK as constant)

**Composition wiring (lock intent):**

```
Settings
  → create_engine / create_session_factory
  → Sql* stores (Turn, Approval, Delivery, Escalation, History, Trace, Vip, SystemConfig)
  → TurnCoordinator(turns, approvals, behavior, locks)
  → BehaviorEngine(AiogramTelegramActuator, deliveries, clock, delay_policy)
  → AdminService(notifier=AiogramOwnerNotifier, ..., owner_telegram_id=settings.owner_telegram_id)
  → CognitiveDirector(..., trace=SqlTraceStore, status_sink=coordinator.transition_sink, persona=DEFAULT_PERSONA)
  → TurnOrchestrator(coordinator, director, admin, learning, history)
  → load forbidden_keywords from SystemConfig at boot
  → build Dispatcher + middleware order + routers
```

**Startup recovery policy (lock — implement exactly):**

```python
async def run_startup_recovery(*, deliveries, approvals, notifier, clock, stale_after) -> RecoveryStartupReport:
    plan = await classify_pending_deliveries(deliveries, now=clock.now(), stale_after=stale_after)
    # Safe F1: do NOT BehaviorEngine.deliver recoverable rows
    for row in plan.recoverable:
        await deliveries.update_status(row.id, "expired")  # or leave pending only if product later needs — default EXPIRE
        await notifier.notify_info(
            f"Startup: expired pending delivery {row.id} for chat {row.chat_id}; re-approve required"
        )
    waiting = await list_waiting_approvals(approvals)
    for approval in waiting:
        await notifier.notify_draft(...)  # or notify_info pointing to draft — re-notify only
    # Never: auto-approve, Director, silent VIP send
```

**Acceptance mapping tests (`test_tac_mvp_f1.py`) — automatable subset:**

| ID | Assert |
|----|--------|
| MVP-01 / no auto-send | VIP orchestrator path with FakeActuator: send count == 0 until admin approve |
| MVP-02 | Actuator/BusinessConnection tests: BC required on send |
| MVP-05 / TAC-06 | Forbidden middleware: 0 Director; escalation notified |
| MVP-06 / TAC-08 | Recovery startup: delivering expired; waiting re-notified; **no** approve/deliver |
| MVP-08 / TAC-01 | Purity trio still green (import or re-invoke) |
| Auth allowlist | Non-VIP never reaches orchestrator |

Manual-only (document in test module docstring; do not block unit gate): live Telegram Business smoke, kill -9 + real PG.

**Required tests:**
1. `run_startup_recovery` expires delivering (via classify) and recoverable pending; never calls deliver/approve.
2. Waiting approvals trigger notifier (draft or info) once each.
3. Acceptance mapping file covers golds above with fakes.
4. Full `tests/unit` green; purity trio green.

**Do NOT:**
- Auto-resume mid-flight deliveries.
- Call Director on startup.
- Introduce F2 features.
- Commit secrets; Settings SecretStr only at I/O boundary.

**Verification:**
```bash
.venv/bin/pytest tests/unit/application/test_recovery_startup.py tests/unit/acceptance -q
.venv/bin/pytest tests/unit/cognitive/test_import_purity.py \
  tests/unit/application/test_application_import_purity.py \
  tests/unit/behavior/test_behavior_import_purity.py -q
.venv/bin/pytest tests/unit -q
# expect: 209 + new item-4 tests all passed
```

## Instrucciones para gsd-executor

### Patterns to copy
- **InMemory gold:** CAS `claim_waiting`, `_DELIVERY_TRANSITIONS`, terminal latch in `application/memory.py` — SQL must match semantics.
- **Admin is sole deliver gate:** orchestrator on approve only queues draft; never `behavior.deliver`.
- **Purity tests:** AST-scan packages; unique test module basenames (`test_*_import_purity` style) to avoid pytest import clashes (item 3 lesson).
- **Fakes:** `FakeTelegramActuator`, `FakeOwnerNotifier`, `FixedDelayPolicy` for non-flaky tests.
- **Coordinator `chat_scope`:** keep full VIP path locked; Admin claim under lock, deliver outside (existing AdminService).

### Anti-patterns
- Calling Director/LLM from ForbiddenKeywords middleware.
- Silent VIP re-send on process restart.
- Importing `aiogram` under `application/`, `behavior/`, `cognitive/`, `learning/`.
- Handlers containing Decider-like if/else on evaluation vectors.
- Writing Staging on correct (F2).
- FreezeCheck middleware.
- Rewriting `001_f1_foundation` migration.
- Real 4–14s sleeps in unit tests.

### Logging
- Structured `extra={turn_id, chat_id}`; avoid full VIP text at INFO when possible.
- Logger names: `diana.telegram`, `diana.application`, `diana.composition`.

### Commits (conventional, no AI attribution)
Suggested work-unit commits:
1. `feat(application): vip store + deterministic escalate + owner escalate`
2. `feat(infrastructure): sql repository adapters with CAS`
3. `feat(telegram): middlewares handlers actuator notifier`
4. `feat(app): composition main recovery startup + acceptance`

### Skills / discipline
- STRICT TDD: red → green per task surface.
- After discoveries (aiogram Business event names, schema mapping), `mem_save` with project DianaV2.
- Artifacts English; do not broaden to F2.

## Test commands

```bash
cd /home/ubuntu/repos/DianaV2

# Full unit gate (item 4 exit)
.venv/bin/pytest tests/unit -q

# Item-4 focused
.venv/bin/pytest tests/unit/telegram tests/unit/infrastructure tests/unit/acceptance -q

# Purity gold
.venv/bin/pytest tests/unit/cognitive/test_import_purity.py \
  tests/unit/application/test_application_import_purity.py \
  tests/unit/behavior/test_behavior_import_purity.py -q

# Application/behavior regression (must stay green)
.venv/bin/pytest tests/unit/application tests/unit/behavior tests/unit/learning -q

# Optional integration (only if added; not required for unit gate)
.venv/bin/pytest tests/integration -q -m integration
```

## Risks + Mitigation

| ID | Risk | Mitigation (from impact-analyzer) |
|----|------|-----------------------------------|
| R1 | Layering break (aiogram in application/cognitive) | Adapters only in `telegram/`; purity trio gate |
| R2 | Forbidden path hits Director/LLM | Deterministic helper + gold TAC-06 test (0 Director) |
| R3 | Auth bypass | AuthMiddleware drops non-allowlist before handler |
| R4 | Non-owner approve/correct | `actor_id` + OwnerAuthError tests |
| R5 | Recovery double-send | Expire delivering + recoverable; re-notify only; no auto-approve |
| R6 | Missing business_connection_id | Middleware inject; actuator fail closed |
| R7 | SQL CAS / terminal latch drift | Port-level parity with InMemory transition tables |
| R8 | Handlers invent decisions | Thin I/O map only |
| R9 | Schema gaps | Join trigger_message_id; log error; optional additive migration only |
| R11 | Correct multi-step races | Owner FSM with supersede cancel |
| R22 | PR size >400 LOC | Work-unit commits; optional chained PRs |

## Success Criteria

- [ ] `VipStore` + `handle_deterministic_escalation` + `AdminService.handle_owner_escalate` exist with unit tests; forbidden path never calls Director
- [ ] SQL adapters implement ports with CAS claim + delivery transition table + terminal latch; unit/infrastructure tests green
- [ ] `telegram/` package: F1 middleware order registered (no Freeze); actuator/notifier/handlers thin
- [ ] Gold tests pass: TAC-06 forbidden, auth allowlist, owner callback authZ, MVP-01 no send without approve, recovery no auto-approve/auto-send
- [ ] `main.py` + composition wire full graph; startup recovery expires mid-flight/recoverable and re-notifies waiting only
- [ ] Purity trio green; `application`/`behavior`/`cognitive` still free of aiogram (cognitive still free of `diana.telegram`)
- [ ] `.venv/bin/pytest tests/unit -q` all green (209 baseline + new item-4 tests)
- [ ] No F2 features (Freeze/Staging/gray/autonomous send)

## Out of scope

- FreezeCheck middleware, gray zone, Staging promotion, autonomous `send`
- Live Telegram CI, multi-instance horizontal scale
- Product sandbox / FakeDelivery as production mode
- REE, promo, recontact
- Rewriting foundation migration or Decider matrix
