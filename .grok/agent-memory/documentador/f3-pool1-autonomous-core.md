# Pool Documentation: f3-pool1-autonomous-core

**Items:** 5 (1–4 + item4b rich quirks)  
**Date:** 2026-07-26  
**Project:** DianaV2  
**Pool:** f3-pool1-autonomous-core  
**Mode:** hardener-agile · Fase 3 autonomous core · effort 5  
**SPEC:** docs/SPEC-FASE3.md (H3.1, H3.2, H3.6)

## Consolidated Outcomes

### Item 1 — Foundation (`HARD 15fa8330`)

| Field | Value |
|-------|--------|
| Outcome | `Decision.action` accepts `"send"`; five F3 flags default false; dual supervised/autonomous threshold constants + Alembic 006 seeds. Zero runtime path change (Decider still no-send until item2). |
| Commits theme | test+feat models/config/db; review harden landmines + migration locks |
| Tests | item suite 162 after review; full unit 630 (+3 pre-existing embedding env) |
| Review | 3 rounds · final open **0** |

### Item 2 — Decider autonomous (`HARD e78885f2`)

| Field | Value |
|-------|--------|
| Outcome | Pure Decider rule 5: flag on + all dims ≥ autonomous mins → `send`/`autonomous_ok`; short dims → approve with `autonomous_below_threshold` (no restriction rewrite). Priority order preserved. Unit-inject only (no composition yet). |
| Commits theme | red matrix → green gate → fix flag sole enablement / partial merge / policy edges |
| Tests | 45 decider · 660 full unit |
| Review | 2 rounds · final open **0** |

### Item 3 — AMS + orchestrator send (`HARD b3ee6a75`)

| Field | Value |
|-------|--------|
| Outcome | `AutonomousModeService` L1/L2; VIP `auto_send` + migration 007; orch send: deliver **outside chat lock**, freeze/empty fail-closed, AMS-off demotes to approve, single post-turn learning; composition wires Decider + AMS. |
| Commits theme | AMS · orch send matrix · composition · freeze/notify harden · residual nits |
| Tests | primary 171 · full unit 686 |
| Review | final open **0** |

### Item 4 — Behavior advanced base (`HARD 74d2f5d5`)

| Field | Value |
|-------|--------|
| Outcome | Engine `is_frozen` hard-check; dual-gate split + light quirk pause; `deliver_with_sequence`; orch/admin/composition wire `FEATURE_ADVANCED_BEHAVIOR`. |
| Commits theme | frozen · split/quirks dual gate · sequence · builder wiring · admin freeze gate |
| Tests | primary 135 · full unit 713 |
| Review | final open **0** |

### Item 4b — Rich quirks (`HARD e4a192c5`)

| Field | Value |
|-------|--------|
| Outcome | Full AGENTS §4.12 quirks under dual gate: pure helpers + engine select one of pause / natural_split / typo_correct; no LLM. |
| Commits theme | pure quirks · engine integrate · harden typo/dual-gate/Spanish |
| Tests | behavior 65 · primary 131 post-fix |
| Review | final open **0** |

### Pool aggregate

| Metric | Value |
|--------|--------|
| HARD_IDs | 15fa8330 · e78885f2 · b3ee6a75 · 74d2f5d5 · e4a192c5 |
| Critical arch | 0 all items |
| Final review open | 0 all items |
| Flags default | false (F2-compatible) |
| Roadmap slice | H3.1 + H3.2 + H3.6 done |

## Learnings / Patterns

1. **Flag sole enablement** — Decider `send` unlocks only from `FEATURE_AUTONOMOUS_MODE`, not Director mode string rewrite. Locks production fail-closed when flag off even if VIP `auto_send` is true (AMS L2 still requires L1).
2. **Three-layer autonomous gate** — L1 flag · L2 AMS (global_mode \| vip.auto_send) · L3 score thresholds. Orchestrator demotes `send`→approve when L2 false rather than delivering.
3. **Deliver outside lock** — Long Behavior delays must not hold chat_scope; CAS + terminal latch handle supersede. Engine freeze hard-check is defense-in-depth on top of application freeze gates.
4. **Dual-gate advanced behavior** — Both global flag and per-ctx `allow_*` required; composition only sets allow when flag on. Rich quirks remain pure + probabilistic with test force hooks.
5. **CLARIFY product tone** — End-user copy = 1st person friendly feminine Spanish; owner ops DMs stay operational. Enforce at template pools, not by rewriting Generator in Pool 1.

## Residuals

### Auto-items / Deferred (next pools)

| Residual | Target pool | Source |
|----------|-------------|--------|
| RecontactService + job + freeze/pause guards | Pool 2 | CLARIFY · POOL.md · SPEC H3.3 |
| Cancel recontact hook on new message | Pool 2 | SPEC H3.8 |
| PromoService + executions + exact match sequences | Pool 2 | SPEC H3.4 |
| Promo re-intro amigable on re-send (full sequence, not silence) | Pool 2 | CLARIFY decision 2 |
| CalibrationService + autonomous margin | Pool 3 | SPEC H3.5 |
| Weekly metrics + style drift | Pool 3 | SPEC H3.7 |
| Admin DM dashboard §7.3 | Pool 3 | SPEC H3.9 · CLARIFY |

### Out of scope (documented only)

| Residual | Reason |
|----------|--------|
| Regenerate / naturalness re-draft action | AGENTS residual; low naturalness only blocks send |
| `TurnStatus.delivering` | wontfix; terminal latch sufficient |
| Multi-worker durable claim for autonomous deliver | out-of-scope; Admin single-process parity |
| History append after autonomous send | admin parity; not claimed |
| Near-threshold notify rate-limit | deferred |
| Runtime `system_config.behavior` JSON merge | deferred post-item4 |
| Mid-delay FreezePort re-query in engine | deferred |
| sentence_transformers env for embedding tests | pre-existing |

## Roadmap Updates

- No `HARDENING_ROADMAP.md` in repo — no separate hardening roadmap edit.
- Wrote `.planning/quick/f3-pool1-autonomous-core/POOL-SUMMARY.md` (pool truth).
- Updated `.planning/quick/f3-pool1-autonomous-core/POOL.md` closed state.
- Created this report: `.grok/agent-memory/documentador/f3-pool1-autonomous-core.md`.
- Updated `.grok/agent-memory/MEMORY.md` Documentador index.
- SPEC-FASE3 H3 table left as product roadmap (implementation status lives in planning SUMMARYs).

## Docs commit

`6bad8f7` — `docs(f3): close pool1 autonomous-core summary`

## Next Steps

1. Orchestrator: **Commit Gate de pool** for `f3-pool1-autonomous-core`.
2. Start **Pool 2** (proactivity): recontact + cancel hook + promo with re-intro amigable; apply CLARIFY tone rules to templates.
3. Then **Pool 3**: calibration + metrics + dashboard DM.
4. Keep all F3 flags default **false** until integration/activation (H3.10).

## Pool close phrase

> Pool `f3-pool1-autonomous-core` cerrado — 5 ítems completados (foundation, decider, AMS+orch, behavior advanced, rich quirks), tests passing, commits hechos, documentación actualizada. Quedan pools: recontact/promo y calibration/metrics/dashboard.
