# SUMMARY — Phase 04 Telegram + wiring + recovery

**Date:** 2026-07-22  
**Item:** 4/4 F1 close  
**Status:** DONE  
**Unit gate:** **287 passed** (baseline 209 + item-4 tests)

## Objective

Wire pure application/behavior/cognitive shell to real Telegram I/O (aiogram 3.x)
and Postgres-backed stores: F1 middleware stack, handlers, SQL CAS adapters,
composition root, safe startup recovery.

## Tasks completed

| Task | Commit | Result |
|------|--------|--------|
| 1. VipStore + deterministic escalate + owner escalate | `feat(application): vip store + deterministic escalate + owner escalate` | PASS |
| 2. SQLAlchemy adapters with CAS | `feat(infrastructure): sql repository adapters with CAS` | PASS |
| 3. Telegram middlewares/handlers/actuator/notifier | `feat(telegram): middlewares handlers actuator notifier` | PASS |
| 4. Composition + main + recovery + acceptance | `feat(app): composition main recovery startup + acceptance` | PASS |

## Key files

### Application
- `src/diana/application/ports.py` — `VipRecord` / `VipStore`
- `src/diana/application/memory.py` — `InMemoryVipStore`, exported `DELIVERY_TRANSITIONS`
- `src/diana/application/deterministic_escalate.py` — forbidden path, no Director
- `src/diana/application/admin_service.py` — `handle_owner_escalate`
- `src/diana/application/recovery_startup.py` — safe boot recovery

### Infrastructure
- `src/diana/infrastructure/db/repositories/*` — SqlTurnStore, SqlPendingApprovalStore (CAS),
  SqlPendingDeliveryStore, SqlEscalationStore, SqlMessageHistoryRepo, SqlTraceStore,
  SqlVipStore, SqlSystemConfigStore

### Telegram
- `src/diana/telegram/setup.py` — F1 middleware order registration
- Middlewares: Logging → BC → Owner → Forbidden → Auth (no Freeze)
- Handlers: business / callbacks / admin
- `actuator.py`, `notifier.py`, `keyboards.py`

### Composition
- `src/diana/composition.py` — `build_app`
- `src/diana/main.py` — long-polling entry + recovery

## Locked decisions honored

| ID | How |
|----|-----|
| L1 | Middleware order F1; Freeze absent |
| L2 | VIP path → orchestrator only; deliver only Admin approve/correct |
| L3 | Recovery expires delivering + recoverable; re-notify waiting; no auto-approve |
| L4 | No aiogram under application/cognitive/behavior |
| L5 | SQL CAS claim + delivery transitions + terminal latch |
| L6 | Forbidden → `handle_deterministic_escalation` zero Director |
| L8 | Callbacks pass `actor_id`; OwnerAuthError handled |
| L11 | Schema gaps: join `turns.trigger_message_id`; no error column; no rewrite 001 |

## Deviations

- None architectural. Schema gap policy: no `002` migration; join trigger_message_id;
  `TurnRecord.error` not persisted (logged at call sites).
- Forbidden keywords list on middleware is a shared mutable list updated at boot via
  dispatcher walk after `system_config` load.

## Verifications run

```bash
.venv/bin/pytest tests/unit -q
# 287 passed

.venv/bin/pytest tests/unit/cognitive/test_import_purity.py \
  tests/unit/application/test_application_import_purity.py \
  tests/unit/behavior/test_behavior_import_purity.py -q
# 3 passed

.venv/bin/pytest tests/unit/telegram tests/unit/infrastructure tests/unit/acceptance -q
```

## Gold assertions covered

- TAC-06 forbidden short-circuit (0 Director, notify escalation)
- Auth allowlist drop
- Owner callback authZ
- MVP-01 no send without approve
- MVP-06/TAC-08 recovery no auto-approve / no silent re-send
- MVP-08 purity trio
- Middleware order F1

## Hardener fix round `26941e4f` (post SUMMARY)

Commit: `fix(telegram): hardener round — forbidden scope, honest UX, FSM`

| Fix | Detail |
|-----|--------|
| Forbidden scope | Business-only (`business_connection_id` required); owner private correct OK |
| vip_id | VipStore resolve by `from_user.id` before Auth |
| Honest UX | approve/correct/escalate map domain no-ops → `stale` / `deliver_failed` |
| Correct FSM | 15m TTL + `cancel_turn` supersede |
| MW order tests | Live `build_dispatcher` MiddlewareManager chain |
| Auth private | Drop non-owner private DMs |
| Polling | `allowed_updates=[message, business_message, callback_query]` |
| Keywords boot | `set_keywords` via wiring (no Dispatcher walk) |

**Unit gate after hardener:** **297 passed**

## Self-Check: PASSED

- [x] Todas las tareas completadas
- [x] Tests del PLAN corridos
- [x] 0 regresiones atribuibles (209 baseline ⊂ 297)
- [x] Convenciones del proyecto respetadas (English code, purity, F1 scope)
- [x] Hardener MUST FIX applied

## Out of scope (confirmed not implemented)

FreezeCheck, Staging, gray zone, autonomous `send`, product sandbox, live Telegram CI

## Review loop
- effort 5, rounds 2, 0 open final
- tests: 297 passed
