# Impact Analysis: Align TurnCoordinator contract to Anexo G (`docs/contratos_restantes.md`)

**Date:** 2026-07-23  
**Change:** Align TurnCoordinator runtime + entry API to Anexo G (G.1–G.5)  
**Analysis only** — no implementación  
**Source of truth:** `/home/ubuntu/repos/DianaV2/docs/contratos_restantes.md` § Anexo G only  
**Also bound by:** `AGENTS.md` §4.1/4.5 (cancel on new message; owner observe), REQ-VIP-06, REQ-NFR-02  
**Pool:** remaining-contracts-app (Pool 2/2) · ITEM 1/3 · effort 4  
**Prior pool closed:** remaining-contracts-cognitive (Anexos C–F)

---

## Executive Summary

Anexo G defines TurnCoordinator as a **concurrency guard**, not reasoning: given `(chat_id, autor, evento)` under a per-`chat_id` lock, decide `crear | reemplazar | descartar_mensaje_dueña` and keep **at most one non-terminal Turn per chat**.

**Current code is a strong partial implementation of the VIP half of G.** `TurnCoordinator.begin_turn` (under `chat_scope`) supersedes all non-terminal priors, cascades `cancel_pending` + waiting-approval cancel, and creates a new `received` turn. `TurnOrchestrator` holds the same lock for the full VIP use-case (zombie-pipeline guard). Unit tests already lock concurrent `begin_turn` and concurrent VIP orchestrator paths to a single non-terminal turn. That covers **G.3.2 / G.3.3 (VIP)** and **in-process G.4**.

**Confirmed contract gaps (must close for G.1–G.5):**

1. **G.2 API surface** — No unified input with `autor: vip|dueña`, no output `accion`. Call sites always assume “create a new turn.”
2. **G.3.1 owner discard** — Owner business messages only hit `BehaviorEngine.cancel_pending` in `OwnerDetectionMiddleware`; they do **not** mark live turns `superseded` nor cancel waiting approvals via the coordinator cascade. A live `pending_approval` turn can remain non-terminal after owner traffic on that chat — **violates G.3.1** and leaves REQ-VIP-06 incomplete for owner-triggered invalidation of in-flight cognitive work.
3. **G.5 lock failure policy** — `asyncio.Lock` waits forever; no timeout, backoff, or enqueue. Contract forbids silent drop; today there is also no explicit failure path when contention is pathological.
4. **G.4 multi-process residual** — Serialization is **in-process only**. `SqlTurnStore.list_non_terminal` + `create` are separate sessions without `SELECT … FOR UPDATE` / advisory lock. F1 single-worker is fine; multi-worker would break G.4. Design docs mention FOR UPDATE; code does not.

**Global risk: medium–high (concurrency + lifecycle), not cognitive.** Wrong owner path leaves zombie approvals; weak multi-process lock is a production footgun if scaled; API reshape touches orchestrator, deterministic escalate, telegram owner middleware, and composition wiring. Director / LLM / EvaluationProfile are out of scope.

**Scope is valid and tight enough for effort 4** if planner treats multi-worker DB locking and full durable message-requeue as **explicit residuals** and focuses on: unified coordinate API + G.3 table under lock + owner wire-up + in-process lock timeout policy + tests. No re-partition of the item required unless G.5 is interpreted as full durable outbox (that would be a second item).

---

## Gap verification (contract vs code)

| Gap | Contract (Anexo G) | Current code | Status |
|-----|--------------------|--------------|--------|
| G.1 single question | “new turn or affect existing?” concurrency guard only | Docstring + supersede/create; no LLM | **OK intent** — extend to owner decision |
| G.1 only node touching Turn outside Director linear flow | State machine owner | Also `transition` / `mark_failed` / `transition_sink` for pipeline statuses | **OK extension** — keep lifecycle API; G.2 is the *entry* decision |
| G.2 input | `{ chat_id, autor: vip\|dueña, evento }` | `begin_turn(chat_id, trigger_message_id, vip_id, turn_id?)` — no `autor` | **CONFIRMED gap** |
| G.2 output | `{ turn_id, accion: crear\|reemplazar\|descartar_mensaje_dueña }` | Returns `TurnRecord` only; always create | **CONFIRMED gap** |
| G.3.1 dueña + nonterminal | supersede, **no** new turn, discard message (`descartar_mensaje_dueña`) | Owner MW: `cancel_pending` only; turn stays non-terminal | **CONFIRMED gap** |
| G.3.2 vip + nonterminal | supersede + new turn (`reemplazar`) | `begin_turn` supersede cascade + create | **OK** (action not named) |
| G.3.3 no nonterminal | create (`crear`) | `begin_turn` create | **OK for VIP** |
| G.3.3 + autor=dueña (no nonterminal) | Literal G.3.3 says create | Owner MW: no-op stop (no create) | **Ambiguity** — see F1 decision below |
| G.4 serialized by chat_id | no two concurrent nonterminal same chat | `ChatLockProvider` + `chat_scope`; orchestrator holds full VIP CS | **OK in-process** |
| G.4 multi-instance | mechanism free but invariant absolute | No DB row lock / advisory lock | **Residual** (F1 single process) |
| G.5 lock timeout | retry/backoff; else enqueue; never silent drop | Infinite wait on `asyncio.Lock` | **CONFIRMED gap** |
| Cascade side-effects | implied by REQ-VIP-06 / design §7.5 | cancel_pending + cancel waiting approvals on supersede | **OK** (must reuse on G.3.1) |
| Terminal statuses | nonterminal definition | `TERMINAL = superseded\|delivered\|failed\|escalated` | **OK** — keep; do not change without separate decision |

### F1 product decision (for planner — not free invention)

**Dueña never creates a cognitive Turn via Coordinator.**  
- `autor=dueña` + nonterminal → G.3.1 as written.  
- `autor=dueña` + no nonterminal → `accion=descartar_mensaje_dueña` (or equivalent no-op discard), **not** `crear`.  

Literal G.3.3 catch-all would mint a `received` turn for owner chatter with no pipeline — contradicts AGENTS.md owner-observe short-circuit and current middleware. Document this as an explicit F1 refinement of G.3 in decisions.md; do not create ghost turns.

### Naming / language (pool pattern)

- Keep English identifiers: e.g. `CoordinateResult.action: Literal["create","replace","discard_owner_message"]` with docstring mapping to Spanish contract names (`crear|reemplazar|descartar_mensaje_dueña`).
- `chat_id: int` (Telegram) is fine vs contract’s `string` — same pattern as rest of F1.
- `evento` can remain thin (trigger_message_id, optional text metadata) — Coordinator must not reason on content.

### Evidence — owner path does not supersede

```49:62:src/diana/telegram/middlewares/owner.py
        # Business messages from owner (edge) — observe + cancel, no VIP pipeline.
        bc = data.get("business_connection_id") or getattr(
            event, "business_connection_id", None
        )
        if bc:
            chat = getattr(event, "chat", None)
            chat_id = getattr(chat, "id", None) if chat else None
            if chat_id is not None:
                await self._behavior.cancel_pending(chat_id, "owner_message")
            logger.info(
                "owner_business_observed",
                extra={"chat_id": chat_id},
            )
            return None
```

No `TurnCoordinator` call → non-terminal turns and waiting approvals survive.

### Evidence — VIP path always creates under lock

```59:129:src/diana/application/turn_coordinator.py
    async def begin_turn(...) -> TurnRecord:
        async with self.chat_scope(chat_id):
            return await self.begin_turn_unlocked(...)

    async def begin_turn_unlocked(...) -> TurnRecord:
        # list_non_terminal → supersede each → cancel_pending + cancel approvals
        # always create TurnRecord(status=received)
```

### Evidence — G.4 in-process only; SQL not atomic

`SqlTurnStore.list_non_terminal` and `create` open separate sessions; no `FOR UPDATE`. Under one process, `ChatLockProvider` serializes. Across processes, G.4 fails open.

---

## Consumers / Call Sites Map

### Production — must update for G.2/G.3.1

| Location | Role | Impact |
|----------|------|--------|
| `src/diana/application/turn_coordinator.py` | Lock + supersede + create | **EDIT** — unified coordinate entry; owner discard branch; optional lock timeout |
| `src/diana/application/turn_orchestrator.py:67-92` | VIP CS: `chat_scope` + `begin_turn_unlocked` | **EDIT** — call coordinate(autor=vip); interpret create/replace; still hold full CS |
| `src/diana/application/deterministic_escalate.py:43-48` | Forbidden path mints turn | **EDIT** — coordinate(vip) or keep thin wrapper that always creates |
| `src/diana/telegram/middlewares/owner.py` | Owner business short-circuit | **EDIT** — inject coordinator; under `chat_scope` run dueña discard path (supersede + cascade); keep no cognitive pipeline |
| `src/diana/telegram/setup.py:91-93` | Wires OwnerDetectionMiddleware(behavior=…) | **EDIT** — pass coordinator (and still behavior via cascade inside coordinator) |
| `src/diana/composition.py:152` | Constructs TurnCoordinator | Likely no change unless lock timeout config |

### Production — consumers of lock/transition only (tolerate; verify)

| Location | Role | Impact |
|----------|------|--------|
| `src/diana/application/admin_service.py:210,256,300` | `chat_scope` around claim/deliver/escalate | **Keep** — must still share same lock provider |
| `src/diana/cognitive/director.py` via `transition_sink` | Pipeline status updates | **No touch** — not G entry |
| `src/diana/telegram/middlewares/forbidden.py` | Calls `handle_deterministic_escalation` | Indirect via escalate helper |
| `src/diana/telegram/handlers/business.py` | VIP → orchestrator | No direct coordinator API if orch owns entry |
| `src/diana/application/ports.py` | `TurnStore`, `BehaviorCanceller` | Optional: new result DTO near ports or in turn_coordinator |

### Production — do NOT touch (out of scope)

| Location | Why |
|----------|-----|
| Cognitive Director / Analyst / Planner / ContextBuilder / Generator / Evaluator / Decider | Cognitive contracts C–F already closed; G is application concurrency |
| BehaviorEngine.deliver sequence (Anexo I) | Separate item; only cancel_pending surface used here |
| Capability Registry / Retrievers (Anexo H) | Pool item 2/3 or later |
| Learning post-turn | After decision |
| Alembic / schema | No migration required for G alignment |
| Multi-worker Postgres locking | Residual unless planner expands scope |
| Dirty-tree unrelated WIP | Leave alone |

### Tests — primary + regression

| Location | Role |
|----------|------|
| `tests/unit/application/test_turn_coordinator.py` | **Primary** — extend G.3 matrix + action output + owner discard; keep concurrent begin |
| `tests/unit/application/test_turn_orchestrator.py` | Concurrent VIP zombie guard — must stay green |
| `tests/unit/telegram/test_owner_mw.py` | **Rewrite/extend** — assert supersede + no new turn + approval cancel |
| `tests/unit/application/test_deterministic_escalate.py` | Still mints escalated turn after coordinate |
| `tests/unit/telegram/test_middleware_stack.py` | Wiring order; owner still before forbidden |
| `tests/unit/application/test_admin_service.py` | Shared lock + CAS approve — regression |
| `tests/unit/acceptance/test_tac_mvp_f1.py` | TAC concurrency / supersede acceptance |
| `tests/unit/test_composition_wiring.py` | DI if constructor args change |

---

## Risks

### Critical

| Risk | Why | Mitigation |
|------|-----|------------|
| **R1 — G.3.1 missing → zombie non-terminal after owner business traffic** | Owner cancel_pending without supersede leaves `pending_approval` + waiting approval; owner might still approve stale draft (admin terminal checks help, but invariant “one non-terminal” / REQ-VIP-06 is soft-broken) | Implement discard path: under lock, supersede all nonterminal, cascade cancel approvals + cancel_pending, **do not create**. Wire owner MW. Tests: owner after pending_approval → zero nonterminal; approve old id → no send. |
| **R2 — Race VIP vs owner without shared lock** | If owner path supersedes without `chat_scope`, interleaves with orchestrator `begin_turn_unlocked` | Owner path **must** use same `coordinator.chat_scope(chat_id)`. Never call store transitions from middleware without lock. |

### Medium

| Risk | Why | Mitigation |
|------|-----|------------|
| **R3 — API reshape breaks many call sites** | `begin_turn` always returns new TurnRecord; escalate/orch/tests assume that | Prefer additive `coordinate(...)` + keep `begin_turn` as thin VIP wrapper (`autor=vip` only) for effort control; or single rename with mechanical updates. Do not break `begin_turn_unlocked` contract used under held lock. |
| **R4 — G.5 incomplete interpretation** | Full durable enqueue is large | F1: `asyncio.wait_for(lock.acquire(), timeout=T)` + bounded retries + log + raise (never drop). Durable requeue = residual. Config timeout via settings if easy; else module constant + docstring. |
| **R5 — Full-pipeline lock vs G.4 “only rules under lock”** | Orchestrator holds lock through Director (LLM latency) — serializes whole chat; owner/VIP wait | **Keep** as intentional stronger invariant (zombie guard already tested). Do not shorten lock to “mint only” without a separate design item — that re-opens mid-pipeline supersede races. |
| **R6 — Owner private DM (admin commands) must not supersede VIP chat** | Private owner messages are approval flow for a *specific* turn_id | Only business-connection owner messages (current MW branch) call discard. Do not supersede on private `/` or correct-text path. |
| **R7 — Multi-process G.4 false confidence** | Deploying 2 workers breaks invariant silently | Document residual; single-process F1 assumption. Optional hard fail note in module docstring. No half-baked FOR UPDATE in this item unless tests+SQL path included. |

### Low

| Risk | Why | Mitigation |
|------|-----|------------|
| **R8 — `superseded_by` on owner discard** | G.3.1 creates no new turn; prior code sets `superseded_by=new_id` | Use `superseded_by=None` or self-sentinel; document. Prefer null + log reason `owner_message`. |
| **R9 — Spanish/English action names in tests** | Contract Spanish | English enum values + docstring map (pool pattern). |
| **R10 — Lock map growth** | `ChatLockProvider` never evicts chat_id keys | Pre-existing; out of scope (dozens of VIPs per NFR-11). |
| **R11 — MVP_COMPONENT_DESIGN still documents begin_turn-only VIP shape** | Doc drift | Note for documentador; Anexo G is SoT for this item. |

### Non-risks (explicit)

- Cognitive purity / Director determinism — not changed if Coordinator stays in `application/`.
- EvaluationProfile vector / Decider F1 actions — untouched.
- Auto-send on approve — AdminService remains sole deliver gate.
- Learning promotion / staging — not in G.
- Schema migration — not required.

---

## Affected Tests

### Commands (exact)

```bash
# Primary — TurnCoordinator contract
PYTHONPATH=src python -m pytest tests/unit/application/test_turn_coordinator.py -q

# Orchestrator concurrency / zombie guard
PYTHONPATH=src python -m pytest tests/unit/application/test_turn_orchestrator.py -q

# Owner middleware + stack wiring
PYTHONPATH=src python -m pytest tests/unit/telegram/test_owner_mw.py tests/unit/telegram/test_middleware_stack.py -q

# Escalation + admin shared lock
PYTHONPATH=src python -m pytest tests/unit/application/test_deterministic_escalate.py tests/unit/application/test_admin_service.py tests/unit/application/test_admin_owner_escalate.py -q

# Composition + acceptance TAC
PYTHONPATH=src python -m pytest tests/unit/test_composition_wiring.py tests/unit/acceptance/test_tac_mvp_f1.py -q

# Full unit gate (test-guardian)
PYTHONPATH=src python -m pytest tests/unit -q
```

(`asyncio_mode = auto` in `pyproject.toml`; no extra asyncio flags required.)

### Tests to add / invert (planner checklist)

1. **G.3.1** — given nonterminal + `autor=dueña` → all prior `superseded`, **no** new row, action=discard; cancel_pending + approvals cancelled.
2. **G.3.1 idle** — dueña + no nonterminal → discard no-op; still no create.
3. **G.3.2** — vip + nonterminal → action=replace; one nonterminal = new id; old.superseded_by = new.
4. **G.3.3** — vip + none → action=create.
5. **G.4** — keep/strengthen concurrent vip coordinate (existing concurrent begin_turn).
6. **Owner MW integration** — pending_approval then owner business message → list_non_terminal empty; approve old → no send.
7. **G.5** (if implemented) — forced lock hold + timeout path raises/logs; message not silently dropped (assert exception or enqueue hook called).
8. **Regression** — deterministic escalate still creates escalated turn; orchestrator concurrent test green; middleware order unchanged.

### Strict TDD

Project has Strict TDD Mode enabled. Executor must write failing G.3.1 / action-output tests **before** production edits.

---

## Files Map

### Edit (expected)

- `src/diana/application/turn_coordinator.py` — G.2/G.3/G.5 surface
- `src/diana/application/turn_orchestrator.py` — vip coordinate under existing `chat_scope`
- `src/diana/application/deterministic_escalate.py` — vip coordinate / begin_turn wrapper
- `src/diana/telegram/middlewares/owner.py` — coordinator discard path
- `src/diana/telegram/setup.py` — DI owner middleware
- `tests/unit/application/test_turn_coordinator.py`
- `tests/unit/telegram/test_owner_mw.py`
- Possibly: `tests/unit/application/test_turn_orchestrator.py`, `tests/unit/telegram/test_middleware_stack.py`, `tests/unit/test_composition_wiring.py`

### Optional small add

- Result DTO in `turn_coordinator.py` or `ports.py` (`CoordinateResult` / action literal)
- Config knob for lock timeout in `config.py` only if already trivial pattern exists

### Create

- None required for runtime (no migration)
- Planner artifacts under `.planning/quick/turn-coordinator-contract/` (downstream)

### No touch

- `src/diana/cognitive/**` (except accidental imports — forbid)
- `src/diana/behavior/engine.py` deliver path (Anexo I)
- `src/diana/learning/**`
- Alembic versions
- Anexos H–I implementation items

---

## Architecture / AGENTS.md checklist

| Check | Expected after change |
|-------|------------------------|
| Director remains deterministic | Yes — no new LLM / no action decision in Coordinator |
| Cognitive never imports telegram/behavior | Unchanged |
| Behavior never decides action | cancel_pending only from cascade |
| Learning only post-turn | Unchanged |
| One non-terminal turn per chat_id | Enforced for **both** vip and dueña entry paths |
| REQ-VIP-06 supersede cascade | Owner path joins cascade |
| Modes external filters | N/A to G |

---

## Ready for chain

**Handoff → gsd-planner** with tight scope:

1. **SoT:** Anexo G G.1–G.5; F1 refinement: dueña never creates turns.
2. **Implement:**
   - Unified entry (prefer additive `coordinate(chat_id, autor, …) -> CoordinateResult` under `chat_scope`).
   - G.3 matrix + existing supersede cascade reuse on replace **and** owner discard.
   - Wire `OwnerDetectionMiddleware` business branch through coordinator (shared lock).
   - VIP orchestrator + deterministic escalate use vip branch (create/replace).
   - G.5 F1: lock acquire timeout + bounded retry + fail loud (no silent drop); durable enqueue residual.
3. **Do not:** multi-worker DB locks; shorten orchestrator full-pipeline lock; cognitive/Behavior deliver/Anexo H–I; schema migrations.
4. **Tests:** commands listed above; red-first G.3.1 + action enum; full `tests/unit` green.
5. **DoD for downstream:**
   - **planner:** decisions.md for dueña-no-create + superseded_by on discard + G.5 residual boundary.
   - **executor:** TDD; keep `begin_turn` compatibility or update all call sites in one PR; no cognitive imports from application.
   - **arch-enforcer:** application owns Turn entry; telegram only calls application; one nonterminal invariant; no silent drop.
   - **test-guardian:** concurrent VIP + owner discard + escalate + admin CAS still pass; zero forbidden mocks of internal lock logic (fakes for stores/behavior OK).

**Effort 4 fit:** Yes if multi-process FOR UPDATE and durable requeue stay residual.  
**Re-partition only if** product insists on durable cross-process G.4+G.5 in the same PR → split “G API + owner discard” vs “distributed lock/outbox.”

---

## Next

`gsd-planner` — plan `turn-coordinator-contract` against this report; then arch-enforcer → executor (TDD) → test-guardian.
