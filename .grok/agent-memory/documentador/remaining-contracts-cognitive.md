# Pool Documentation: remaining-contracts-cognitive

**Items:** 4  
**Date:** 2026-07-23  
**Project:** DianaV2  
**Pool:** remaining-contracts-cognitive (hardener-agile · Pool 1 of 2)  
**Source contracts:** `docs/contratos_restantes.md` Anexos C–F  
**Mode:** docs-only close (documentador)

## Consolidated Outcomes

### Item 1 — planner-contract (Anexo C)

| Field | Value |
|-------|--------|
| Outcome | Force-history removed; pure `_NEED_TO_CAPABILITY` map; empty plan `[]` legal; Director blast omits `knowledge.history` when `needs_history=false` |
| HARD_ID | `bab3bdb6` |
| Commits | `396fbcb`, `66d3124`, `56ab8d9` |
| Tests | Post-fix cognitive slice **100 passed**; full unit **376 passed** (SUMMARY) |
| Arch | **PASS WITH NOTES** · 0 critical |
| Guardian | Suite protects · 0 prohibited mocks |
| Review | Effort 4 · Round 1: 7 open → all fixed · final **0 open** |
| Self-check | PASSED |

**Sources:** `.planning/quick/planner-contract/SUMMARY.md`,  
`.grok/agent-memory/{arch-enforcer,test-guardian,review,impact-analyzer}/planner-contract.md`

### Item 2 — context-builder-contract (Anexo D)

| Field | Value |
|-------|--------|
| Outcome | Dual `BuiltContext { prompt_final, included_blocks }`; D.4 order (Persona → knowledge → Comprehension → **Current VIP last**); typed size fail `contexto_excede_limite` (no truncate/retry); Orchestrator notify + no VIP send |
| HARD_ID | `438d8c31` |
| Commits | `2650587`, `f7abe8b`, `933f038`, `037ad96` |
| Tests | Full unit **388 passed** (SUMMARY); fix-round cluster green |
| Arch | **PASS WITH NOTES** · 0 critical |
| Guardian | Suite protects · 0 prohibited mocks · D.4 + dual return + size-fail notify locked |
| Review | Effort 4 · Round 1: 3 issues (1 bug fixed, 1 suggestion fixed, 1 style_rules **wontfix**/residual) · final open blockers **0** |
| Self-check | PASSED |

**Sources:** `.planning/quick/context-builder-contract/SUMMARY.md`,  
`.grok/agent-memory/{arch-enforcer,test-guardian,review,impact-analyzer}/context-builder-contract.md`

### Item 3 — generator-contract (Anexo E)

| Field | Value |
|-------|--------|
| Outcome | Empty/whitespace retry once inside Generator → `GeneratorEmptyOutputError` / `generador_salida_vacia`; Director removes `empty_draft` escalate; Orchestrator mark `failed` + owner `notify_info`; no VIP send / no approval |
| HARD_ID | `ddcf928c` |
| Commits | `49dc4d9`, `3d60877`, `ef4f43d`, `1308d08` |
| Tests | Primary cluster **54 passed**; full unit **396 passed** (SUMMARY) |
| Arch | **PASS WITH NOTES** · 0 critical |
| Guardian | Suite protects · 0 prohibited mocks · E.1 prompt assert tightened |
| Review | Effort 4 · Round 1: **ALL CLEAN · 0 open** |
| Self-check | PASSED |

**Sources:** `.planning/quick/generator-contract/SUMMARY.md`,  
`.grok/agent-memory/{arch-enforcer,test-guardian,review,impact-analyzer}/generator-contract.md`

### Item 4 — decider-contract (Anexo F · F1-safe)

| Field | Value |
|-------|--------|
| Outcome | F1 matrix locked (safety → risk alto → approve); residual naturalness fall-through approve; optional `mode_restriction_applied` (`supervised_send_to_approve`); `Decision.action` still `approve\|escalate` only |
| HARD_ID | `348ea349` |
| Commits | `4e1db5a` |
| Tests | Primary suites green (decider 21 + Decision models 10 + director slice 4 + import purity 1 + eval invariants 11 + orchestrator/TAC slices) |
| Arch | **PASS WITH NOTES** · 0 critical |
| Guardian | Suite protects · 0 prohibited mocks · residual naturalness + mode_restriction locked |
| Review | Effort 4 · Round 1: **ALL CLEAN · 0 open** |
| Self-check | PASSED |
| Decisions | `.planning/quick/decider-contract/decisions.md` (L1–L8) |

**Sources:** `.planning/quick/decider-contract/{SUMMARY,decisions}.md`,  
`.grok/agent-memory/{arch-enforcer,test-guardian,review,impact-analyzer}/decider-contract.md`

## Pool metrics

| Metric | Value |
|--------|--------|
| Items closed | 4 / 4 |
| Critical arch violations | **0** (all four PASS WITH NOTES) |
| Final review open issues | **0** per item |
| Self-checks | 4 × PASSED |
| F1 `Decision.action` | Still `approve \| escalate` only (locked across pool) |
| Cognitive import purity | Green across all items |
| Dirty-tree alembic residual | **Not staged** (explicit no-touch) |

## Learnings / Patterns

1. **Fail-closed twin family grows** — A.6 / B.6 / D.6 / E.4 share the same shape: component owns retry/check → typed reason → Director fails before later stages → Orchestrator `mark_failed` + owner `notify_info` + zero VIP send. Prefer local typed exceptions until a third shared helper is justified.
2. **Force-history was a product lie** — Anexo C supersedes MVP design prose that forced `knowledge.history`. Runtime pure map + Director blast tests are the lock; design docs lag as documentador residual.
3. **Dual BuiltContext is single-source anti-drift** — Director must not re-call `list_included_blocks`; Evaluator names must match Generator-visible knowledge via one build result.
4. **Strip after “current turn last” is a landmine** — full `prompt.strip()` corrupts trailing VIP whitespace; preserve turn body (fix: `lstrip("\n")` + trailing newline only).
5. **F1 Decider ≠ full Anexo F vision** — naturalness→regenerate and public `send|regenerate|consult_doctrine` stay residual; document residual + test fall-through approve rather than half-implement regenerate.
6. **mode_restriction is audit, not a new action** — supervised still returns `approve`; token records the external mode filter. Composition threshold wiring remains a separate ops residual.

## Residuals

### Pool 2 queue (Anexos G–I) — next pool

| Residual / item | Class | Notes |
|-----------------|-------|-------|
| **turn-coordinator-contract** (Anexo G) | **Pool 2** | Concurrency lock per `chat_id`; supersede/new-turn rules; only node that may touch Turn state outside Director linear flow |
| **registry-retrievers-contract** (Anexo H) | **Pool 2** | Registry.resolve → Retriever; per-retriever contracts; schedule as recognized-but-unimplemented null; anti-contamination invariants |
| **behavior-engine-contract** (Anexo I) | **Pool 2** | Fixed humanize sequence; supersede check before send; FakeDelivery sandbox; cancel_pending |

### Auto-items / deferred (in-scope follow-ups, not this pool’s DoD)

| Residual | Class | Origin |
|----------|-------|--------|
| Composition wire of `eval_thresholds` into Decider | deferred / in-scope-followup ops | decider L6 |
| TraceStore snapshot of `included_blocks` | observation / optional reconstructability | context-builder / evaluator family |
| Shared schema/empty-fail helper (A.6/B.6/D.6/E.4) | observation | optional DRY |

### Out of scope (documented only)

| Residual | Class | Origin |
|----------|-------|--------|
| MVP force-history docs still in `docs/MVP_COMPONENT_DESIGN.md` §5.6 | out-of-scope | planner-contract; Anexo C supersedes |
| SPEC / design wording: empty-draft escalate → failed semantics | out-of-scope | generator-contract |
| SPEC / MVP design: early current-turn vs D.4 last | out-of-scope | context-builder-contract |
| F.3 #2 naturalness→**regenerate** (+ Director regenerate loop / action expand) | out-of-scope F2+ | decider-contract |
| Full REQ-VIP-04 **style_rules** wire through Director/Settings | out-of-scope | context-builder L14 / review wontfix |
| Token-accurate prompt budgeting (`max_prompt_chars` proxy) | out-of-scope | context-builder residual |
| `needs_profile` / `knowledge.profile` F2 | out-of-scope | planner non-goal |
| Pre-existing dirty tree **alembic `turns.error`** (002 + infra models/repos/tests) | out-of-scope | L10/L11 no-touch all items; **do not stage** |

## Roadmap Updates

- No `HARDENING_ROADMAP.md` in repo — no roadmap file edit.
- Added this consolidado under `.grok/agent-memory/documentador/`.
- Updated `.grok/agent-memory/MEMORY.md` Documentador index.
- Pool item SUMMARYs / PLANs / agent reports (impact, arch, guardian, review) are source of truth and included in docs commit when present.
- Decider locked decisions already in `.planning/quick/decider-contract/decisions.md`.
- Production code: **0 changes** by documentador.

## Docs commit

`5f5c052` — `docs(cognitive): close remaining-contracts-cognitive pool (C–F)`

## Next Steps

1. Orchestrator: **Commit Gate de pool** for `remaining-contracts-cognitive`.
2. Start **Pool 2** of remaining contracts: Anexos **G–I** (Turn Coordinator, Capability Registry + Retrievers, Behavior Engine).
3. Keep deferred residuals (eval_thresholds wire, style_rules productization, regenerate F2) out of Pool 2 unless explicitly re-scoped.
4. Leave alembic `turns.error` dirty tree for a dedicated infra item — do not mix into contract pools.
5. Optional later docs hygiene: MVP_COMPONENT_DESIGN force-history + SPEC empty-draft / D.4 wording.

## Pool close

> Pool `remaining-contracts-cognitive` cerrado — 4 ítems completados (Anexos C–F), tests passing, commits hechos, documentación actualizada.

> Pool anterior de 4 cerrado (tests passing, commits hechos). Nuevo pool de 4 iniciado. Quedan clusters pendientes (Anexos G–I).
