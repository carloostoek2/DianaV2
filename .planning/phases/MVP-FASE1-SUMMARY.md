# SUMMARY — MVP Fase 1 Pool Close

**Pool:** hardener-agile MVP “primer valor seguro” Fase 1  
**Date:** 2026-07-22  
**Status:** CLOSED  
**Items:** 4/4 complete (self-check PASSED each)  
**Final unit gate:** **297 passed**  
**Review:** effort 5; all items closed with **0 open** issues  

**Source of truth (product/architecture):** `docs/SPEC-1.1.md`, `docs/REQUERIMIENTOS.md`, `docs/MVP_COMPONENT_DESIGN.md`, `AGENTS.md`  
**Source of truth (this pool):** per-item SUMMARYs + hardener reviews + arch/test-guardian reports (cited below). Do **not** treat this file as a rewrite of SPEC.

---

## Pool objective

Deliver supervised VIP chat automation end-to-end: schema + pure cognitive decision pipeline + application shell (orchestrator, admin approval gate, races) + Behavior Engine + post-turn Learning (TRACE only) + Telegram long-polling wiring with SQL adapters and safe restart recovery.

F1 product fence: **no** Freeze / Staging / gray zone / autonomous `send` / product sandbox.

---

## Items completed

| # | Item | SUMMARY | Unit gate (post-hardener) | Review | Arch | Test-guardian |
|---|------|---------|---------------------------|--------|------|---------------|
| 1 | Foundation — schema, config, models | [01-foundation/SUMMARY.md](01-foundation/SUMMARY.md) | 58 passed | a075917f · rounds 2 · 0 open (28 fixed / 1 wontfix) | PASS_WITH_NOTES · 0 critical | suite OK (31 at guardian pass) |
| 2 | Cognitive Core — Director + LLM ports | [02-cognitive-core/SUMMARY.md](02-cognitive-core/SUMMARY.md) | 150 passed | 73113e69 · rounds 3 · 0 open | PASS_WITH_NOTES · 0 critical | suite OK (122 at guardian; post-fix 150) |
| 3 | Application + Behavior + Learning | [03-application-behavior/SUMMARY.md](03-application-behavior/SUMMARY.md) | 209 passed | ddd81931 · 0 open (races/auth fixed) | PASS_WITH_NOTES · 0 critical | suite OK (200 at guardian; post-fix 209) |
| 4 | Telegram + wiring + recovery | [04-telegram-wiring/SUMMARY.md](04-telegram-wiring/SUMMARY.md) | **297 passed** | 26941e4f · rounds 2 · 0 open | PASS_WITH_NOTES · 0 critical | suite OK (289 at guardian; post-fix 297) |

### 1 — Foundation

- Installable `src/diana` (hatchling), pytest, env-driven Settings (no unsafe secret defaults).
- Cognitive domain contracts: `EvaluationProfile` 7D (no score/mean), `Decision.action` ∈ {`approve`, `escalate`}.
- ORM + Alembic: **exactly 8 F1 tables**; seed non-secret `system_config` only; owner id env-only.
- Hardener: SecretStr, alembic fail-loud, `.gitignore`, FKs, purity/schema freezes.
- **Wontfix:** `pgcrypto` retained on downgrade (shared DB extension).

### 2 — Cognitive Core

- Pipeline: Director → Analyst → Planner → Registry/Retrievers → ContextBuilder → Generator → Evaluator → Decider.
- Ports + DI; `FakeLLM` + DeepSeek (`httpx` MockTransport in unit tests).
- history/context REAL; memory/profile/policy/examples/schedule STUB → None.
- Hardener: eval [0,1] finite, fence strip JSON, empty draft → escalate, FAILED path, `llm_base_url` https + no private hosts.
- Architecture golds: import purity, 7D invariants, Decider matrix, Director TAC-01 call log.

### 3 — Application + Behavior + Learning

- TurnCoordinator (supersede cascade), TurnOrchestrator (mint `turn_id` before Director), AdminService (approve/correct only deliver), BehaviorEngine, Learning TRACE_KEYS post-turn.
- **Never auto-send** on cognitive `approve`; deliver only from Admin resolve.
- Hardener races: zombie pipeline + terminal latch, approve TOCTOU CAS, cancelled↛done delivery machine, owner authZ, mark-as-read, recovery expires mid-flight `delivering`.

### 4 — Telegram + wiring + recovery

- F1 middleware: Logging → BC → Owner → Forbidden → Auth (**no Freeze**).
- SQL repository adapters (CAS claim, delivery transitions, terminal latch); composition root; `python -m diana.main` long-polling.
- Safe recovery: expire mid-flight + recoverable; re-notify waiting drafts; **never** silent VIP re-send / auto-approve.
- Hardener: forbidden business-only scope, honest approve UX statuses, correct FSM 15m TTL, live middleware chain tests, `allowed_updates`.

---

## AC / TAC coverage mapping (F1)

Mapping sources: `docs/SPEC-1.1.md` TAC table, `docs/MVP_COMPONENT_DESIGN.md` §MVP criteria, item SUMMARYs, test-guardian 04 report, hardener 26941e4f plan matrix.

| ID | Requirement (short) | F1 status | Primary evidence |
|----|---------------------|-----------|------------------|
| **TAC-01** / MVP-08 | Director pure (no LLM control flow) | **Covered** | `test_import_purity`, Director unit, acceptance purity trio |
| **TAC-02** / MVP-10 | Registry resolves all retrievers (real or stub) | **Covered** | registry/retriever/director unit suite |
| **TAC-03** / MVP-09 | EvaluationProfile 7D, no single score | **Covered** | model invariants + evaluator tests |
| **TAC-04** / MVP-07 | Intermediate objects persisted (trace keys) | **Covered (unit)** | InMemoryTraceStore 7 keys; SQL TraceStore adapter wired; no live PG integration in unit gate |
| **TAC-05** / MVP-11 | Behavior Engine outside Cognitive Core | **Covered** | behavior import purity; Admin-only deliver path |
| **TAC-06** / MVP-05 | Forbidden escalate before Analyst | **Covered** | forbidden MW + deterministic escalate; `FakeDirector.calls==0` |
| **TAC-07** / MVP-04 | Cancel delivery on new VIP message | **Covered** | item-3 coordinator/orchestrator supersede + cancel golds |
| **TAC-08** / MVP-06 | Restart recovers pending deliveries safely | **Covered (policy)** | recovery helpers + startup path; no auto-approve / no silent re-send; unit InMemory |
| **TAC-09** | Anti-contamination memory ↔ examples | **F2** | Not in F1 schema/retrievers (stubs only) |
| **TAC-10** | Staging + explicit promotion on correct | **F2** | Correct delivers text only; no Staging module |
| **TAC-11** | Gray zone freeze + policy distill | **F2** | No Freeze middleware / gray tables |
| **TAC-12** | Hot-swap LLM | **F2** | Composition picks Fake/DeepSeek at boot |
| **TAC-13** | Approval/gray metrics | **F3** | Out of scope |
| **MVP-01** | No VIP send without owner approve | **Covered** | orchestrator deliver count 0; acceptance MVP-01 |
| **MVP-02** | Send with `business_connection_id` | **Covered** | actuator fail-closed + BC kwargs tests |
| **MVP-03** | Delay + mark-as-read + typing | **Covered (unit)** | BehaviorEngine + DeliveryContext message id; FakeActuator |
| **MVP-12** | Decider F1 only approve \| escalate | **Covered** | Decision Literal + Decider matrix |
| **MVP-13** | ≤1 non-terminal turn per chat_id | **Covered** | TurnCoordinator supersede invariant tests |

---

## Metrics

| Metric | Value | Source |
|--------|-------|--------|
| Items closed | 4/4 | SUMMARYs |
| Final unit tests | **297 passed** | item-4 hardener SUMMARY / gsd-04 log |
| Critical arch violations | **0** (all 4 items) | arch-enforcer reports |
| Review open (final) | **0** per item | hardener reviews |
| F1 tables | 8 | foundation SUMMARY + schema tests |
| Decision actions F1 | `approve` \| `escalate` | models freeze |
| Live Telegram / live PG in unit CI | No | PLAN L10 / test-guardian |

---

## Residual known limitations (F2 / ops backlog)

Accepted residuals and explicit out-of-scope — **not** open F1 defects. Sources: item SUMMARYs “Out of scope”, hardener security 26941e4f residual backlog, arch-enforcer notes.

### Product / architecture (F2+)

| Residual | Notes |
|----------|--------|
| **FreezeCheck / VIP freeze** | AGENTS stack slot deferred; F1 middleware omits Freeze |
| **Staging** | Owner correct does not write `staging_candidates`; no promotion path |
| **Gray zone / `consult_doctrine`** | Not in `Decision.action`; no gray tables / distill |
| **Autonomous `send`** | Decider cannot emit `send`; modes remain supervised-only |
| **Regenerate loop** | Not in F1 action set |
| **REAL knowledge tables** | memories/examples/policies/profiles STUB; TAC-09 F2 |
| **Product sandbox / promo / recontact** | Out of F1 |
| **Prompt injection fencing / truncations** | Supervised human gate accepted residual (security review) |

### Operational / multi-process

| Residual | Notes |
|----------|--------|
| **Multi-process / multi-instance CAS** | Approval `claim_waiting` is SQL CAS; delivery/turn status often RMW — TOCTOU under multi-writer. F1 assumes **single active process** |
| **Multi-instance Telegram polling** | Document single replica; no `drop_pending_updates` policy hardened for multi-bot |
| **SQL adapters live PG** | Unit gate uses InMemory + pure mappers; optional integration tests not in F1 CI |
| **CorrectSessionStore in-process** | Restart loses “awaiting correct”; drafts re-notified with buttons |
| **Isolated deliver worker** | Cancel-aware current task OK; long deliver may block callback answer UX |
| **pgcrypto on downgrade** | Extension retained (wontfix foundation) |
| **Empty DeepSeek key → FakeLLM** | Ops residual with warning; not auth bypass |
| **Schema gaps without 002** | `TurnRecord.error` not persisted; mark-as-read joins `turns.trigger_message_id` |

---

## Package surface (F1 deliverable)

```
src/diana/
  config.py, composition.py, main.py
  cognitive/     # pure pipeline + models + ports + retrievers
  llm/           # FakeLLM, DeepSeekProvider
  application/   # orchestrator, admin, coordinator, recovery, escalate
  behavior/      # BehaviorEngine, delays, FakeActuator
  learning/      # post_turn TRACE_KEYS only
  telegram/      # aiogram middlewares, handlers, actuator, notifier
  infrastructure/db/  # ORM, session, SQL repositories
alembic/versions/001_f1_foundation.py
tests/unit/      # 297 tests — no live Telegram / no required Postgres
```

**Entry:** `python -m diana.main` (after `alembic upgrade head` + env secrets). See root `README.md`.

---

## Pool close note

> Pool `MVP Fase 1` cerrado — 4 ítems completados, **297 unit tests passing**, review loop 0 open, documentación consolidada.  
> Primer valor seguro supervisado: VIP → Director → owner approve/correct → Behavior deliver; forbidden short-circuit; safe recovery.  
> Siguiente: pool F2 (Freeze/Staging/gray/autonomous send / knowledge REAL / multi-process CAS) según roadmap de producto.

---

## Traceability index

| Artifact | Path |
|----------|------|
| Item SUMMARYs | `.planning/phases/0{1..4}-*/SUMMARY.md` |
| Executor logs | `.planning/quick/gsd-0{1..4}-*.log` |
| Impact | `.grok/agent-memory/impact-analyzer/0{1..4}-*.md` |
| Arch | `.grok/agent-memory/arch-enforcer/0{1..4}-*.md` |
| Test-guardian | `.grok/agent-memory/test-guardian/0{1..4}-*.md` |
| Hardener reviews | `.grok/agent-memory/review/grok-hardener-review-{a075917f,73113e69,ddd81931,26941e4f}*.md` |
| Documentador report | `.grok/agent-memory/documentador/mvp-fase1-pool.md` |
