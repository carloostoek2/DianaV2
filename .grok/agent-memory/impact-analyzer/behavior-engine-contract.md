# Impact Analysis: Align Behavior Engine contract to Anexo I (`docs/contratos_restantes.md`)

**Date:** 2026-07-23  
**Change:** Align BehaviorEngine runtime + ports to Anexo I (I.1–I.5)  
**Analysis only** — no implementación  
**Source of truth:** `/home/ubuntu/repos/DianaV2/docs/contratos_restantes.md` § Anexo I only  
**Also bound by:** `AGENTS.md` §3.1/4.1/4.5/5.4 (Behavior outside cognition; cancel_pending; deliver contract), SPEC-1.1 §4.9, REQ-HUM-01/02/03, REQ-NFR-01/04, REQ-VIP-06, REQ-COG-13/14  
**Pool:** remaining-contracts-app (Pool 2/2) · ITEM 3/3 · effort 4  
**Prior items same pool:** turn-coordinator-contract (G), registry-retrievers-contract (H)

---

## Executive Summary

Anexo I defines the Behavior Engine as the **only node allowed to write to the VIP**: pure actuation of an already-approved text via a **fixed human-like sequence** (delay → read → typing → send), with **pre-send supersede abort**, **bounded retries** on transient channel errors, and a **mode enum** that includes `fake_delivery` for future sandbox without signature thrash.

**Current code is a solid F1 skeleton of the sequence + cancel path, not full I.1–I.5.**  
`BehaviorEngine.deliver` already runs delay → optional read → typing action + sleep → send loop; registers the current asyncio task in `TimerManager`; marks `pending_deliveries` with CAS transitions; and `cancel_pending` cancels in-flight tasks + DB rows. `AdminService._resolve_and_deliver` is the sole production deliver call site (approve/correct). Import purity tests keep LLM/cognitive decision modules out of `behavior/`. Fake doubles (`FakeTelegramActuator`, `ImmediateClock`, `FixedDelayPolicy`) power unit and acceptance tests without network.

**Confirmed contract gaps (must close for I.1–I.5):**

1. **I.4 supersede check immediately before send** — Engine relies only on `asyncio.Task.cancel` + post-deliver terminal latch in Admin. There is **no Turn-status read just before step 4**. Race: cancel after last await before/during `send_message` can still deliver to Telegram, then mark delivery cancelled/done-rejected. Closes G.4 invariant only through task cancel, not through the last-mile check Anexo I requires.
2. **I.4 / I.5 bounded retries + owner notify + Turn.failed** — Single send attempt; any exception → `status=error` + `DeliveryResult(success=False)`. No retry budget, no transient/permanent classification, no owner notification from this path, no `Turn.status=failed` on exhausted retries (Admin reopens approval as `waiting`).
3. **I.2 mode enum** — `DeliveryContext.mode: Literal["supervised"]` only. Missing `autonomo` / `fake_delivery`. Settings `global_mode` likewise supervised-only. Contract allows stubbing fake path; **enum presence is mandatory**.
4. **I.3 “never zero” delay (REQ-NFR-01)** — Production `RandomDelayPolicy` defaults 4–14s (OK), but engine does **not** enforce `initial > 0`. Test `FixedDelayPolicy(initial=0)` is legal; no production clamp/config keys for typing formula / max retries.
5. **I.3 step 2 always mark read** — Read is skipped when `telegram_message_id is None`. Contract lists read as fixed step 2; F1 should document optional-skip when trigger id unknown **or** require id at deliver gate.

**Global risk: medium (delivery correctness + anti-zombie send), not cognitive.** Wrong last-mile supersede handling can message VIP after a newer turn; missing retries/notify can drop failures silently from the owner’s POV; mode enum is low risk if additive. Director / LLM / EvaluationProfile / Registry stay **out of scope**. Behavior must remain free of LLM and cognitive decision imports.

**Scope is valid and tight enough for effort 4** if planner treats full sandbox FakeDelivery *implementation*, multi-message quirks (F3), and multi-process durable cancel as **explicit residuals**, and focuses on: pre-send supersede gate, bounded send retries + failure surface, mode enum (+ no-op or record-only fake branch), delay/retry config, and tests. No re-partition required.

---

## Gap verification (contract vs code)

| Gap | Contract (Anexo I) | Current code | Status |
|-----|--------------------|--------------|--------|
| I.1 single question | “how is the approved message acted?” — execute only | Docstring + ports; no LLM; no content decision | **OK intent** |
| I.1 only VIP write path | sole node with send permission | Only `BehaviorEngine` → `TelegramActuatorPort`; Admin/Orchestrator never call bot send for VIP body | **OK** |
| I.2 input shape | `{chat_id, texto_final, modo}` | `deliver(texts: list[str], ctx: DeliveryContext, turn_id, decision?)` | **Partial** — multi-text OK extension; mode incomplete |
| I.2 modo enum | `supervisado \| autonomo \| fake_delivery` | `mode: Literal["supervised"] = "supervised"` | **CONFIRMED gap** |
| I.2 output | `{ok, error, resultado_entrega}` | `DeliveryResult(success, message_ids, delays, error, cancelled)` | **OK mapping** (English names) |
| I.3.1 prior delay never zero | configurable, never 0 (REQ-NFR-01) | `RandomDelayPolicy` 4–14s; no engine clamp; tests allow 0 | **Partial / residual clamp** |
| I.3.2 mark read | always step 2 | only if `telegram_message_id is not None` | **Partial** |
| I.3.3 typing proportional | formula config, e.g. min(max, base+chars/v) | `RandomDelayPolicy`: `min(len*0.03, 5.0)`; hardcoded ctor defaults | **Partial** (works; not config-driven) |
| I.3.4 send via business channel | official business path only | `business_connection_id` required fail-closed; actuator enforces | **OK** |
| I.3 fixed order | delay → read → typing → send | engine lines 92–118 in that order | **OK** for happy path |
| I.4 pre-send supersede abort | check Turn not `superseded` before send | task cancel only; Admin checks **after** deliver | **CONFIRMED gap** |
| I.4 bounded retries | config-limited; only transient net/API | no retry loop | **CONFIRMED gap** |
| I.4 fake_delivery in enum | reserved for sandbox; MVP may not implement body | enum missing | **CONFIRMED gap** (enum) |
| I.5 fail → ok=false, error, Turn.failed, notify owner | after retries exhausted | engine returns error; Admin reopens `waiting`; no owner notify; turn not failed | **CONFIRMED gap** (failure surface shared with Admin) |
| Cancel mid-flight (AGENTS/REQ-VIP-06) | cancel_pending aborts delivery | TimerManager + CancelledError + store cancel | **OK** (complement, not substitute for I.4 check) |
| No LLM / no cognitive imports | AGENTS §3.2 | purity test + ports | **OK — keep** |

### Naming / language (pool pattern)

- Keep English identifiers: `mode: Literal["supervised","autonomous","fake_delivery"]` with docstring mapping to Spanish contract (`supervisado|autonomo|fake_delivery`).
- Prefer existing `DeliveryResult.success` over inventing parallel `ok` unless a thin adapter is needed.
- `chat_id: int` (Telegram) stays; contract’s `string` is not binding for F1 types.
- `texts: list[str]` may remain (multi-bubble future / F3); contract’s `texto_final` maps to `texts[0]` or single-element list at Admin gate — **do not break multi-text tests**.

### Evidence — sequence exists; no pre-send turn check

```86:118:src/diana/behavior/engine.py
        try:
            if not await self._deliveries.update_status(delivery_id, "delivering"):
                return DeliveryResult(
                    success=False, cancelled=True, error="cancelled_before_start"
                )

            initial = self._delay.initial_delay_seconds()
            await self._clock.sleep(initial)

            if ctx.telegram_message_id is not None:
                await self._actuator.read_business_message(...)

            ...
            await self._actuator.send_chat_action(..., "typing", ...)
            await self._clock.sleep(typing_secs)

            message_ids: list[int] = []
            for text in texts:
                mid = await self._actuator.send_message(...)  # no turn status gate
```

No `TurnStore` / status port injected into `BehaviorEngine`.

### Evidence — mode enum too narrow

```12:21:src/diana/behavior/ports.py
class DeliveryContext(BaseModel):
    ...
    mode: Literal["supervised"] = "supervised"
```

### Evidence — Admin post-deliver latch (not pre-send)

```292:313:src/diana/application/admin_service.py
        result = await self._behavior.deliver([text], ctx, turn_id, decision=...)
        async with self._coordinator.chat_scope(chat_id):
            turn_after = await self._turns.get(turn_id)
            if turn_after is None or _is_terminal(turn_after.status):
                # Superseded mid-flight — do not revive.
                ...
```

If Telegram already accepted the message, latch only prevents turning status to `delivered` — VIP still saw the text.

### Evidence — cancel cascade on supersede (partial mitigation)

```241:242:src/diana/application/turn_coordinator.py
            await self._behavior.cancel_pending(chat_id, cancel_reason)
```

Best-effort interrupt; does not replace I.4 last-mile check.

---

## Consumers / Call Sites Map

### Production — must touch or carefully verify

| Location | Role | Impact |
|----------|------|--------|
| `src/diana/behavior/engine.py` | Sequence + cancel | **EDIT** — pre-send supersede gate; bounded send retries; optional fake branch; optional delay clamp |
| `src/diana/behavior/ports.py` | `DeliveryContext` / result / ports | **EDIT** — widen `mode` enum; optional `TurnStatusReader` / retry config port; maybe transient error type |
| `src/diana/behavior/fake.py` | Test doubles | **EDIT/extend** — flaky actuator for retries; mode-aware fake if needed |
| `src/diana/behavior/timer_manager.py` | In-flight tasks | **Likely keep** — still required with supersede gate |
| `src/diana/application/admin_service.py` `_resolve_and_deliver` | Sole deliver caller | **EDIT** — pass mode; on permanent fail after retries: owner notify + Turn.failed (or accept engine callback/port); keep post-latch |
| `src/diana/application/ports.py` | `BehaviorDeliverer` protocol | **EDIT if** deliver signature gains turn-status reader deps (prefer ctor inject, not call-site) |
| `src/diana/application/turn_coordinator.py` | supersede → `cancel_pending` | **Verify only** — cascade must remain; no cognitive import |
| `src/diana/composition.py` | wires BehaviorEngine + `RandomDelayPolicy` | **EDIT** — inject turn reader, retry/delay settings, mode from settings |
| `src/diana/config.py` | Settings | **EDIT** — `global_mode` widen; delay/retry knobs (or system_config keys) |
| `src/diana/telegram/actuator.py` | Real I/O | **Verify** — may surface errors for retry classification; no content logic |

### Production — consumers of cancel only (tolerate; verify no deliver)

| Location | Role | Impact |
|----------|------|--------|
| `src/diana/telegram/middlewares/owner.py` | owner cancel_pending / coordinate | **No behavior contract change** unless mode |
| `src/diana/application/recovery.py` / `recovery_startup.py` | expire mid-flight; never deliver | **No touch** — must keep “never auto-deliver” |
| `src/diana/application/turn_orchestrator.py` | approve path → Admin, not direct deliver | **Verify** R1 still holds |
| `src/diana/infrastructure/db/repositories/deliveries.py` | CAS transitions | **Keep** matrix; retries must not invent illegal transitions |

### Test consumers

| Location | Role |
|----------|------|
| `tests/unit/behavior/test_engine.py` | happy path order, multi-text, cancel mid-delay, CAS done-after-cancel, bc fail-closed |
| `tests/unit/behavior/test_fake_delivery.py` | fake actuator order; FixedDelayPolicy zeros |
| `tests/unit/behavior/test_behavior_import_purity.py` | no llm/cognitive/aiogram in behavior package |
| `tests/unit/application/test_admin_service.py` | approve/correct deliver; supersede no deliver; concurrent double approve |
| `tests/unit/application/test_turn_orchestrator.py` | R1 no auto-deliver; R2 cancel; R5 approve after supersede |
| `tests/unit/application/test_turn_coordinator.py` | supersede calls cancel_pending |
| `tests/unit/application/test_recovery*.py` | never deliver on startup |
| `tests/unit/infrastructure/test_delivery_transitions.py` | transition matrix |
| `tests/unit/acceptance/test_tac_mvp_f1.py` | wiring + BehaviorEngine with FixedDelayPolicy |
| `tests/unit/telegram/test_*` | graphs construct BehaviorEngine |

### Line-level call sites (deliver / cancel)

| Path | Symbol |
|------|--------|
| `src/diana/application/admin_service.py:293` | `self._behavior.deliver(...)` — **only production deliver** |
| `src/diana/application/turn_coordinator.py:242` | `self._behavior.cancel_pending` on supersede |
| `src/diana/application/turn_coordinator.py` (owner/VIP coordinate paths) | cascade cancel |
| `src/diana/telegram/middlewares/owner.py` | may cancel or coordinate (post-G item) |
| `src/diana/composition.py:149-151` | `BehaviorEngine(actuator, deliveries, clock, delay_policy)` |

---

## Risks

### Critical

| Risk | Why | Mitigation |
|------|-----|------------|
| **Send-after-supersede race** | I.4 last-mile check missing; cancel is best-effort at await points | Inject narrow `TurnStatusPort.get_status(turn_id)` (or `is_live`); **check immediately before each `send_message`**; if superseded/terminal → abort without send, mark delivery cancelled, return `cancelled=True`. Keep task cancel as fast-path. |
| **Silent delivery failure** | I.5: owner must learn VIP got no reply | After bounded retries exhausted: engine returns structured error; Admin (or notify port) messages owner + `Turn.status=failed` (do not leave forever-waiting approval without signal). Prefer Admin owns Turn transition (keeps Behavior free of full TurnStore write surface if desired). |

### Medium

| Risk | Why | Mitigation |
|------|-----|------------|
| **Retry storms / double send** | Naïve retry after partial multi-text send | Retry **per send_message** only on classified transient errors; do not restart full sequence after a successful partial send without policy; cap with config (e.g. max_attempts=2–3). Idempotency not provided by Telegram — document residual. |
| **Turn reader dependency direction** | Behavior currently depends on `PendingDeliveryStore` (application ports); adding Turn read is OK if port is thin and Behavior still never imports cognitive/LLM/aiogram | Put `TurnStatusReader` Protocol in `application.ports` or `behavior.ports`; implement via existing TurnStore adapter; purity test stays green |
| **Mode enum break** | Pydantic `extra=forbid` + Literal widen is additive for readers; writers default supervised | Expand Literal; default `"supervised"`; Admin passes settings.global_mode; tests for invalid mode rejected |
| **fake_delivery accidental use in prod** | Enum present, body stub | Explicit branch: if mode==fake_delivery → record-only / Fake path without network **or** raise NotImplemented for F1 with test documenting residual — prefer **record-only no-network** if easy, else hard fail-closed with clear error (planner choice; document in decisions.md) |
| **Delay never-zero vs unit tests** | Tests use 0 delay for speed | Clamp only in production policy / Settings; keep FixedDelayPolicy free for tests; optionally engine rejects only when `enforce_min_delay=True` |

### Low

| Risk | Why | Mitigation |
|------|-----|------------|
| Signature vs AGENTS.md §5.4 | Doc shows `deliver(decision, texts, ctx)`; code is `(texts, ctx, turn_id, decision=)` | Keep code signature (turn_id required for FK); update AGENTS only if doc drift in scope — **prefer residual doc** over reorder kwargs |
| Import purity regression | aiogram must stay in telegram/ | Never import Bot in behavior/; retries use exceptions from port |
| Recovery still never auto-delivers | Startup expires mid-flight | Do not wire recovery → deliver when adding retries |

### Architecture boundaries (must not break)

- Behavior **never** calls Analyst/Generator/Evaluator/Decider/Director/LLM.
- Behavior **never** decides content or action — only actuates given texts.
- Modes remain external filters; Behavior may **branch I/O strategy** by mode (real vs fake), not decide approve/send at cognitive level.
- Learning still post-turn only; no staging from engine.
- Cognitive Core must not import behavior.

---

## Affected Tests

### Primary (must pass / extend)

```bash
# Behavior package
PYTHONPATH=src python -m pytest tests/unit/behavior/ -q

# Deliver path + supersede
PYTHONPATH=src python -m pytest \
  tests/unit/application/test_admin_service.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/application/test_turn_coordinator.py \
  -q

# Delivery transitions + recovery never-deliver
PYTHONPATH=src python -m pytest \
  tests/unit/infrastructure/test_delivery_transitions.py \
  tests/unit/application/test_recovery.py \
  tests/unit/application/test_recovery_startup.py \
  -q
```

### New / extended cases planner must schedule

| Case | Contract |
|------|----------|
| Sequence ops order still `read → typing → send` (with delay sleeps recorded) | I.3 |
| **Pre-send**: turn flipped to `superseded` after delay, **before** send → `cancelled`, `send_count==0` | I.4 |
| **Pre-send**: status already terminal when about to send → no send | I.4 |
| Transient send error then success within budget → `success`, attempts==2 | I.4 |
| Exhaust retries → `success=False`, delivery `error`, **no further silent drop**; Admin/Turn.failed + owner notify (or documented handoff) | I.5 |
| `mode` accepts supervised / autonomous / fake_delivery; invalid rejected | I.2 |
| `fake_delivery`: no network send (record-only or NotImplemented with explicit test) | I.4 / REQ-COG-14 residual |
| Import purity still forbids llm/cognitive/aiogram | AGENTS |
| Existing cancel mid-delay + CAS cancelled sticky | REQ-VIP-06 |
| Admin approve after supersede still no send | regression |
| Concurrent double approve single send | regression |

### Full regression

```bash
PYTHONPATH=src python -m pytest tests/unit/ -q
```

### Golds / critical acceptance

```bash
PYTHONPATH=src python -m pytest tests/unit/acceptance/test_tac_mvp_f1.py -q
```

TAC-05 (Behavior separated from Cognitive Core) must remain green via purity + no auto-send from Director.

---

## Files Map

### Edit (expected)

- `src/diana/behavior/engine.py` — pre-send gate; retries; mode branch
- `src/diana/behavior/ports.py` — mode enum; optional reader/retry types
- `src/diana/behavior/fake.py` — fail-injecting actuator; maybe FakeDelivery path
- `src/diana/application/admin_service.py` — mode pass-through; I.5 failure handling (notify + failed)
- `src/diana/composition.py` — wire new deps/settings
- `src/diana/config.py` — mode + delay/retry settings (minimal)
- `tests/unit/behavior/test_engine.py` — gap cases above
- `tests/unit/behavior/test_fake_delivery.py` — mode/fake if applicable
- `tests/unit/application/test_admin_service.py` — fail notify / failed turn
- Optional: `tests/unit/test_config.py` if settings widen

### Create (optional)

- `tests/unit/behavior/test_engine_retries.py` or fold into `test_engine.py`
- Thin `TurnStatusReader` protocol (prefer colocated in ports, not new package)

### No touch

- `src/diana/cognitive/**` (all)
- `src/diana/llm/**`
- `src/diana/learning/**`
- Alembic migrations (no schema required for I.1–I.5 if status/retry live in existing columns + config)
- Director / Decider / Evaluator contracts
- Recovery auto-deliver (must remain absent)

### Docs (planner residual / documentador)

- `AGENTS.md` §5.4 signature note if still divergent
- `docs/contratos_restantes.md` only if F1 refinements (read optional; fake stub semantics) need explicit decisions.md — do **not** silently weaken I.4

---

## DoD for downstream agents

### gsd-planner

1. Tight plan scoped to Anexo I gaps only (table above).
2. Explicit **decisions.md** candidates:
   - Where pre-send status is read (engine port vs Admin wrapper) — **recommend engine port** so all future deliverers get I.4 free.
   - Who marks `Turn.failed` + owner notify on I.5 (Admin vs engine notify port) — **recommend Admin owns Turn write; engine returns terminal DeliveryResult**.
   - fake_delivery F1: record-only vs NotImplemented.
   - Delay clamp: production policy only vs engine enforce.
3. List exact pytest commands (primary + full unit).
4. Residuals: full sandbox FakeDelivery UX, multi-bubble quirks (F3), multi-process cancel durability, Telegram partial-send idempotency.
5. No production code in planner.

### executor

1. TDD: failing tests for I.4 pre-send abort + I.4 retries + I.2 mode enum **before** implementation.
2. Keep import purity.
3. Do not add LLM calls, Redis, or cognitive imports.
4. Preserve: cancel_pending semantics, CAS delivery transitions, Admin single-send on concurrent approve, recovery never-deliver.
5. `turn_id` remains required on deliver.

### arch-enforcer

1. Behavior package still answers only “how to act the message”.
2. No Director/LLM/aiogram imports under `behavior/`.
3. Pre-send supersede check present (evidence in engine).
4. Mode enum includes fake_delivery.
5. Retries bounded (constant or config); no infinite loop.
6. Failure path not silent (notify or Turn.failed owned somewhere with test).
7. Dependency direction: Behavior ↛ cognitive; Application → Behavior OK.

### test-guardian

1. Primary suite covers I.3 order, I.4 supersede-before-send, I.4 retry budget, I.2 mode, I.5 failure surface, purity, cancel regression.
2. No prohibited mocks of cognitive internals; FakeTelegramActuator / clock / delay policy OK.
3. Full unit green; TAC acceptance still passes.
4. Race-oriented test must not be flaky (use ImmediateClock + injected status sequence, not wall-clock sleeps where avoidable).

---

## Ready for chain

**Handoff → gsd-planner** with scope:

| In scope | Out of scope / residual |
|----------|-------------------------|
| I.2 mode enum `supervised\|autonomous\|fake_delivery` | Full sandbox product (REQ-COG-14 body beyond enum/stub) |
| I.3 sequence hardening (read policy + prod delay non-zero) | F3 multi-message quirks / split |
| I.4 pre-send Turn supersede/live check | Multi-worker durable cancel (G.4 residual) |
| I.4 bounded retries for transient send errors | Perfect Telegram idempotency |
| I.5 failure → structured result + owner-visible outcome + Turn.failed | Learning/staging on correct (already Admin/post-turn) |
| Tests + purity + composition/settings wiring | Cognitive contracts, alembic |

**Suggested effort:** 4  
**Risk global:** medium (delivery race + failure visibility)  
**Analysis only complete** — next agent: **gsd-planner**.
