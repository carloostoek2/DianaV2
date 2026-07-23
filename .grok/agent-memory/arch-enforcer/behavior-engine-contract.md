# Arch Audit: behavior-engine-contract

**Date:** 2026-07-23  
**Auditor:** arch-enforcer  
**Plan:** `.planning/quick/behavior-engine-contract/PLAN.md`  
**Summary:** `.planning/quick/behavior-engine-contract/behavior-engine-contract-SUMMARY.md`  
**Decisions:** `.planning/quick/behavior-engine-contract/decisions.md`  
**Impact:** `.grok/agent-memory/impact-analyzer/behavior-engine-contract.md`  
**Contract:** `docs/contratos_restantes.md` Anexo I (I.1–I.5)  
**Commits:** `b54b310`, `1430ada`, `464f4e7`  
**Verdict:** PASS WITH NOTES  
**Critical violations:** 0

## Scope audited

Production:
- `src/diana/behavior/ports.py` — `DeliveryMode`, `TransientSendError`, `TurnStatusReader`, `DeliveryContext.mode`
- `src/diana/behavior/engine.py` — I.4 pre-send gate, bounded retries, `fake_delivery`, sequence delay→read→typing→send, `cancel_pending`
- `src/diana/behavior/fake.py` — AlwaysLive / Sequence readers, `FlakySendActuator`, clocks/policies
- `src/diana/application/admin_service.py` — mode pass-through; I.5 permanent-fail path; cancelled reopen; terminal latch
- `src/diana/composition.py` — `TurnStoreStatusReader`, `RandomDelayPolicy` never-zero, engine + admin wiring
- `src/diana/config.py` — `global_mode` tri-state; retry/delay knobs (`gt=0`)

Tests (contract surface):
- `tests/unit/behavior/test_engine.py` — I.2 mode, I.3 order, I.4 pre-send/retries, fake_delivery
- `tests/unit/behavior/test_behavior_import_purity.py` — no llm/cognitive decision/aiogram
- `tests/unit/application/test_admin_service.py` — I.5 failed+notify; supersede no false failed
- `tests/unit/test_config.py` — modes + delay/retry defaults + RandomDelayPolicy clamp

Cross-checks:
- AGENTS.md §3.1 Behavior (act only), §3.2 Behavior ↛ cognitive/LLM; Application → Behavior OK; §4.1 deliver path; §4.5 cancel; §5.4 BehaviorEngine; §6.3 delivery status paths
- Focus gates: **I.4 pre-send**, **no cognitive import**, **I.5 admin fail path**
- No `src/diana/cognitive/**`, `llm/**`, `learning/**`, `alembic/**` edits (SUMMARY + package import scan)
- Residuals left as documented (full FakeDelivery UX, multi-process last-mile, partial multi-text, AGENTS §5.4 signature doc)

## Evidence

| Check | Result |
|-------|--------|
| I.1 sole VIP write / no content decision | **PASS** — engine actuates `texts` only; no LLM/generate; Admin sole production deliver call site |
| I.2 mode enum | **PASS** — `supervised\|autonomous\|fake_delivery` on `DeliveryContext` + Settings `global_mode`; invalid rejected |
| I.2 output mapping | **PASS** — `DeliveryResult.success` ↔ `ok`; error/cancelled/message_ids present |
| I.3 sequence | **PASS** — delay → optional read → typing action+sleep → send loop; happy-path test locks order |
| I.3 never-zero delay (prod) | **PASS** — `RandomDelayPolicy(initial_min<=0)` raises; Settings delay mins `gt=0`; FixedDelay free for tests |
| **I.4 pre-send** | **PASS** — `_presend_abort_if_not_live` immediately before each `send_message` and before fake virtual completion; missing/terminal → `cancelled=True`, delivery `cancelled`, **zero send** |
| I.4 terminal set local strings | **PASS** — `_TERMINAL_SEND_ABORT = {superseded,delivered,failed,escalated}` in engine; **no** `diana.cognitive` import (L3) |
| I.4 bounded retries | **PASS** — only `TransientSendError`; permanent `Exception` single attempt; max attempts + backoff via `Clock.sleep` |
| I.2/I.4 fake_delivery | **PASS** — record-only, no actuator I/O; still honors pre-send + initial delay |
| **No cognitive import** | **PASS** — `behavior/` imports: `application.ports` (store DTO only), `behavior.ports`, `timer_manager`. Zero `cognitive` / `llm` / `aiogram`. Purity AST green for decision modules + llm + aiogram |
| **I.5 Admin fail path** | **PASS** — permanent fail: approval `cancelled` + `coordinator.mark_failed` + `notify_info` + delivery trace; **not** silent `waiting` reopen |
| I.5 cancelled live | **PASS** — `result.cancelled` + still non-terminal → reopen `waiting` (L8) |
| I.5 terminal latch | **PASS** — post-deliver terminal → cancel approval, no `mark_failed`/no revive; supersede test asserts status `superseded` and no `delivery_failed` notify |
| Engine never writes Turn | **PASS** — engine only pending_deliveries + actuator; Turn.failed owned by Admin/Coordinator |
| Composition wiring | **PASS** — `turn_status=TurnStoreStatusReader(turns)`, retry knobs from Settings, `delivery_mode=settings.global_mode` |
| cancel_pending / CAS | **PASS** — TimerManager + cancel_for_chat retained; done-reject on cancelled preserved |
| Scope vs PLAN | **PASS** — production files match PLAN file map; no cognitive/LLM/learning/alembic |
| Logging | **PASS** — `delivery_presend_abort`, `delivery_send_retry`, `delivery_fake`, `delivery_done`/`cancelled`, `admin_deliver_failed` with turn_id/chat_id |
| Tests vs PLAN | **PASS** — required I.3/I.4/I.2/I.5 cases present; FlakySend/Sequence readers; no network |

### I.4 pre-send (critical gate detail)

```246:289:src/diana/behavior/engine.py
    async def _presend_abort_if_not_live(...):
        ...
        status = await self._turn_status.get_status(turn_id)
        if status is not None and status not in _TERMINAL_SEND_ABORT:
            return None
        await self._safe_mark(delivery_id, "cancelled")
        ...
        return DeliveryResult(success=False, cancelled=True, ...)
```

Called from the multi-text loop **before** `_send_with_retries` and from `_deliver_fake` before marking `done`. Complements (does not replace) `cancel_pending` / task cancel — closes Anexo I last-mile supersede race.

### I.5 Admin permanent fail (critical gate detail)

```345:364:src/diana/application/admin_service.py
            else:
                # I.5 permanent deliver failure after retries — do not silent-wait.
                await self._approvals.mark_status(turn_id, "cancelled")
                await self._coordinator.mark_failed(
                    turn_id, error=result.error or "delivery_failed"
                )
                await self._notifier.notify_info(
                    f"Turn {turn_id} failed: delivery_failed ({result.error})",
                    chat_id=claimed.chat_id,
                )
                await self._traces.set_delivery_result(...)
```

## Findings

### Critical (must fix before advance)

_None._

### Medium

_None that block advance._

### Observations

1. **`turn_status=None` fail-open (always live)** — Documented intentional fixture default (SUMMARY/PLAN A13). Production composition **always** injects `TurnStoreStatusReader`. Risk: a future non-composition constructor that omits the reader silently disables I.4. Prefer fail-closed or a hard requirement in a later harden pass if new call sites appear.

2. **Pre-existing Behavior → `application.ports` coupling** — `engine.py` still imports `DeliveryRecord` / `PendingDeliveryStore` from `diana.application.ports` (noted in arch 03-application-behavior Medium #1). Not introduced by this item; extract to neutral ports remains residual.

3. **Production actuator does not raise `TransientSendError` yet** — `AiogramTelegramActuator` surfaces raw bot exceptions as permanent (no retry). Matches decisions L5 (“may wrap later”). Retries are ready; mapping Telegram network/timeout → `TransientSendError` is a residual for real I/O.

4. **I.3 read still optional** when `telegram_message_id is None` — PLAN residual; contract lists read as fixed step 2. F1 acceptable with residual note.

5. **AGENTS.md §5.4 deliver signature order** — code keeps `(texts, ctx, turn_id, decision=)` (L14); doc reorder is documentador residual.

6. **Purity AST bans decision modules not full `diana.cognitive`** — Gate is correct for “no cognitive decision modules”; current package has **zero** `diana.cognitive` imports either way. Local terminal string set avoids enum import temptation.

7. **Multi-text partial success / multi-process cancel** — documented residuals; not regressions.

## Compliance Checklist

- [x] Capas respetadas (Behavior acts only; Application owns Turn.failed + notify; Cognitive/LLM/Learning untouched)
- [x] Scope del PLAN respetado (no cognitive / llm / learning / alembic)
- [x] Logging adecuado (presend abort, send retry, fake, admin_deliver_failed)
- [x] I.4 pre-send gate inside engine before each send (+ fake)
- [x] No cognitive / LLM / aiogram imports under `behavior/`
- [x] I.5 permanent fail → Turn.failed + owner notify + approval not silent waiting
- [x] Cancelled supersede path does not force failed
- [x] Mode enum + fake_delivery record-only
- [x] Prod never-zero initial delay; FixedDelay free for tests
- [x] Bounded TransientSendError retries only
- [x] cancel_pending + CAS delivery transitions retained
- [x] Tests reflect I.2 / I.3 / I.4 / I.5 contracts
- [ ] (note) Optional reader default remains fail-open for unit fixtures only
- [ ] (note) Behavior → application.ports store coupling pre-existing residual

## Handoff

**Verdict allows advance:** YES (0 critical).

**Next step:** `test-guardian` for behavior-engine-contract (I.4 pre-send + retries + I.5 Admin surface + purity + regression suite).
