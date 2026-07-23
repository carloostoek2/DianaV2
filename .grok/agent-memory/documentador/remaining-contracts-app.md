# Pool Documentation: remaining-contracts-app

**Items:** 3  
**Date:** 2026-07-23  
**Project:** DianaV2  
**Pool:** remaining-contracts-app (hardener-agile · Pool 2 of 2)  
**Source contracts:** `docs/contratos_restantes.md` Anexos G–I  
**Mode:** docs-only close (documentador)  
**Prior pool:** `remaining-contracts-cognitive` (Anexos C–F) — closed `5f5c052`

## Overall C–I status

| Pool | Anexos | Items | Status |
|------|--------|-------|--------|
| 1 remaining-contracts-cognitive | C–F | planner, context-builder, generator, decider | **CLOSED** |
| 2 remaining-contracts-app | G–I | turn-coordinator, registry-retrievers, behavior-engine | **CLOSED** (this pool) |

**All remaining-contract anexos C–I are complete** across both pools (tests green, HARD CLEAN, self-checks PASSED, reviews 0 open).

## Consolidated Outcomes

### Item 1 — turn-coordinator-contract (Anexo G)

| Field | Value |
|-------|--------|
| Outcome | `TurnCoordinator.coordinate` G.3 matrix under per-`chat_id` lock: VIP create/replace; owner always `discard_owner_message` (never creates); cascade via `BehaviorCanceller` + approvals; G.5 lock timeout + bounded retry + loud `ChatLockTimeoutError`; owner business MW wires through coordinator |
| HARD_ID | `44bcfb3e` CLEAN |
| Commits | `87165ed`, `37b996a`, `d504231` |
| Tests | Coordinator **17 passed**; related cluster **70 passed**; full unit **414 passed** (SUMMARY) |
| Arch | **PASS WITH NOTES** · 0 critical |
| Guardian | Suite protects · 0 prohibited mocks · G.3 matrix + owner supersede + G.5 timeout + concurrency locked |
| Review | Effort 4 · Round 1: **CLEAN · 0 open** |
| Self-check | PASSED |
| Decisions | `.planning/quick/turn-coordinator-contract/decisions.md` (L1–L8) |

**Sources:** `.planning/quick/turn-coordinator-contract/{SUMMARY,decisions}.md`,  
`.grok/agent-memory/{arch-enforcer,test-guardian,review,impact-analyzer}/turn-coordinator-contract.md`

### Item 2 — registry-retrievers-contract (Anexo H)

| Field | Value |
|-------|--------|
| Outcome | History bare `list[{autor,texto,timestamp}]` empty `[]` never `None`; Context English H.3 keys only (always object); Schedule half-registered (`fuente=no_implementado`, fetch `None`); stubs Memory/Policy/Examples stay registered→`None`; boot fail-fast planner universe; H.4 AST no cross-retriever + read-only; D.5 empty history omit intact |
| HARD_ID | `1dab3c8b` CLEAN |
| Commits | `5cc909a`, `f49bfb3`, `163dc5a` |
| Tests | Primary cognitive cluster **81 passed**; wiring **26 passed**; full unit **425 passed** (SUMMARY) |
| Arch | **PASS WITH NOTES** · 0 critical |
| Guardian | Suite protects · 0 prohibited mocks · H.1–H.4 + schedule half-register + AST gates locked |
| Review | Effort 4 · Round 1: **CLEAN · 0 open** |
| Self-check | PASSED |

**Sources:** `.planning/quick/registry-retrievers-contract/SUMMARY.md`,  
`.grok/agent-memory/{arch-enforcer,test-guardian,review,impact-analyzer}/registry-retrievers-contract.md`

### Item 3 — behavior-engine-contract (Anexo I)

| Field | Value |
|-------|--------|
| Outcome | I.2 mode tri-state `supervised\|autonomous\|fake_delivery`; I.4 pre-send live check before each send (and fake virtual send) → abort `cancelled` zero send; bounded retries only on `TransientSendError`; fake_delivery record-only; I.5 Admin permanent fail → approval cancelled + `mark_failed` + `notify_info` (no silent waiting reopen); REQ-NFR-01 never-zero prod delay |
| HARD_ID | `15962a15` CLEAN |
| Commits | `b54b310`, `1430ada`, `464f4e7` |
| Tests | Behavior **23 passed**; core regression **94 passed**; full unit **443 passed**; TAC **8 passed** (SUMMARY) |
| Arch | **PASS WITH NOTES** · 0 critical |
| Guardian | Suite protects · 0 prohibited mocks · I.4 pre-send/retries + fake + I.5 fail path locked |
| Review | Effort 4 · Round 1: **CLEAN · 0 open** |
| Self-check | PASSED |
| Decisions | `.planning/quick/behavior-engine-contract/decisions.md` (L1–L13) |

**Sources:** `.planning/quick/behavior-engine-contract/{behavior-engine-contract-SUMMARY,decisions}.md`,  
`.grok/agent-memory/{arch-enforcer,test-guardian,review,impact-analyzer}/behavior-engine-contract.md`

## Pool metrics

| Metric | Value |
|--------|--------|
| Items closed | 3 / 3 |
| Critical arch violations | **0** (all three PASS WITH NOTES) |
| Final review open issues | **0** per item |
| Self-checks | 3 × PASSED |
| Full unit (post-pool terminal) | **443 passed** (behavior-engine SUMMARY) |
| Cognitive import purity | Green (registry/retrievers + behavior purity AST) |
| Behavior ↛ cognitive/LLM/aiogram | Locked |
| Dirty-tree alembic residual | **Not staged** (explicit no-touch all items) |

## Learnings / Patterns

1. **G.4 last-mile is two layers** — Coordinator serializes create/replace under `chat_id` lock; Behavior I.4 pre-send aborts if the turn went terminal during humanize delay. Both are required; cancel_pending alone is not enough.
2. **Owner never opens a turn** — Owner business messages always `discard_owner_message` and supersede nonterminals without creating. Keep private DM pass-through separate so VIP chats are not discarded from owner private traffic.
3. **Schedule half-register is intentional** — Anexo H prose “no registrado” vs “reconocida pero sin implementación” resolves to: still registered + `fuente=no_implementado` + fetch `None`, so Planner may request it without boot/mid-turn KeyError.
4. **Bare resultado, not H.2 envelope DTO** — Director knowledge map stays `cap → bare`; Protocol docstring documents the conceptual envelope. Avoids unwrap churn and preserves ContextBuilder D.5 (`[]` null-like omit).
5. **I.5 permanent fail must not reopen waiting** — Fail-closed twin of cognitive empty/size fails: mark Turn failed, cancel approval, notify owner, leave delivery trace. Supersede mid-flight stays cancelled/live reopen, not `failed`.
6. **In-process lock ≠ multi-worker safety** — F1 documents multi-process `FOR UPDATE` / durable requeue as residuals; do not treat unit concurrent tests as cross-worker proof.

## Residuals

### Auto-items / Deferred

None created by this pool as auto-items. No next remaining-contracts pool (C–I complete).

### Out of scope (documented only)

| Residual | Class | Origin |
|----------|-------|--------|
| Multi-process G.4 — Postgres `FOR UPDATE` / advisory lock across workers | out-of-scope | turn-coordinator L5 / behavior G.4 residual |
| G.5 durable message requeue/outbox after lock timeout | out-of-scope | turn-coordinator L5 |
| Shortening orchestrator full-pipeline lock | out-of-scope | turn-coordinator R5 (intentional keep) |
| Doc refresh `MVP_COMPONENT_DESIGN` begin_turn-only / owner cancel_pending wording | out-of-scope | turn-coordinator documentador residual |
| `MVP_COMPONENT_DESIGN.md` §5.7 schedule=STUB without half-register nuance | out-of-scope | registry-retrievers R10 |
| Full sandbox FakeDelivery UX (REQ-COG-14 body) beyond enum + record-only | out-of-scope | behavior-engine L10 |
| Telegram partial multi-text idempotency after partial success | out-of-scope | behavior-engine |
| AGENTS.md §5.4 signature doc sync | out-of-scope | behavior-engine |
| Mandatory `telegram_message_id` at deliver gate | out-of-scope | behavior-engine L11 note |
| Dual `get_recent` History+Context shared snapshot | out-of-scope | registry R7 |
| H.2 full envelope in traces (`fuente` in knowledge map) | out-of-scope / F2 | registry arch obs |
| Pre-existing dirty tree **alembic `turns.error`** (`002_turns_error.py` + infra models/repos/tests) | out-of-scope | L10 no-touch all items; **do not stage** |

### Carry-forward from Pool 1 (still open, not this pool)

| Residual | Class | Origin |
|----------|-------|--------|
| Composition wire of `eval_thresholds` into Decider | deferred | decider L6 |
| F.3 #2 naturalness→**regenerate** + action expand | out-of-scope F2+ | decider |
| Full REQ-VIP-04 **style_rules** wire | out-of-scope | context-builder |
| MVP force-history / SPEC empty-draft / D.4 wording docs | out-of-scope | Pool 1 documentador |

## Roadmap Updates

- No `HARDENING_ROADMAP.md` in repo — no roadmap file edit.
- Added this consolidado under `.grok/agent-memory/documentador/remaining-contracts-app.md`.
- Updated `.grok/agent-memory/MEMORY.md` Documentador index.
- Pool item SUMMARYs / PLANs / decisions / agent reports (impact, arch, guardian, review) are source of truth and included in docs commit when present and untracked.
- Production code: **0 changes** by documentador.
- **Note:** remaining-contracts C–I (both pools) are closed.

## Docs commit

`bb3df05` — `docs(application): close remaining-contracts-app pool (G–I)`

## Next Steps

1. Orchestrator: **Commit Gate de pool** for `remaining-contracts-app`.
2. No further remaining-contracts pool — Anexos **C–I complete**.
3. Optional next work (out of contract pools): multi-process G.4 locks; durable G.5 requeue; FakeDelivery sandbox UX; regenerate F2; eval_thresholds composition; dedicated infra item for alembic `turns.error` dirty tree.
4. Optional docs hygiene: `MVP_COMPONENT_DESIGN` schedule half-register + begin_turn/owner wording; AGENTS.md §5.4 signature; SPEC empty-draft / D.4 lag from Pool 1.

## Pool close

> Pool `remaining-contracts-app` cerrado — 3 ítems completados (Anexos G–I), tests passing, commits hechos, documentación actualizada.

> Pool anterior de 4 cerrado (tests passing, commits hechos). Pool 2 de 3 cerrado. **Contratos restantes C–I completos** en ambos pools. Quedan residuals out-of-scope / F2, no clusters de anexo pendientes.
