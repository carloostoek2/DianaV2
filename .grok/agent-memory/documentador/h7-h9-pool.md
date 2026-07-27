# Pool Documentation: H7 + H9

**Items:** 2  
**Date:** 2026-07-27  
**Project:** DianaV2  
**Pool:** h7-h9 (hardener-agile)  
**Mode:** hardener-agile · Strict TDD · effort 5  

## Consolidated Outcomes

### ITEM 1 — H7 corrections + owner history

| Field | Value |
|-------|--------|
| Outcome | `handle_correct` → `StagingService.save_correction` (timing A); owner history `role="owner"` on supervised approve/correct and autonomous delivery success; sandbox `should_persist` gate; composition wires StagingService when `feature_staging_enabled`. |
| Commits (4) | `b7b61da` · `3ee7607` · `f149665` · `212213e` |
| Tests | Primary pack green (132+); fix-round 124 (admin+orch+composition); TG suite OK |
| Gates | arch PASS WITH NOTES **0 critical** · TG OK · self-check PASSED · review **0 open** after 2 rounds |

**Evidence sources:** `.planning/quick/h7-corrections-history/SUMMARY.md`, `gsd-h7-corrections-history.log`, `.grok/agent-memory/review/h7-corrections-history.md`, arch-enforcer/test-guardian H7 reports.

### ITEM 2 — H9 knowledge.schedule real

| Field | Value |
|-------|--------|
| Outcome | Real `ScheduleRetriever` (`fuente=agenda_semanal_fija`), catalog `schedule` block + validation, cognitive `ClockPort`, typed ContextBuilder render, ContextRetriever day/time (CDMX), Analyst current-activity → `needs_schedule`, empty `UNIMPLEMENTED_CAPABILITIES`. |
| Commits (5) | `e6aaf47` · `08be3d4` · `d217e0e` · `0f4aa69` · `410ab74` |
| Tests | Primary H9 pack green · full unit **1406** · gold half-open windows (inicio inclusive + fin exclusive) |
| Gates | arch PASS WITH NOTES **0 critical** · TG OK · self-check PASSED · review **0 open** after 2 rounds |

**Evidence sources:** `.planning/quick/h9-schedule/SUMMARY.md`, `gsd-h9-schedule.log`, `.grok/agent-memory/review/h9-schedule.md`, arch-enforcer/test-guardian H9 reports.

### Pool aggregate

| Metric | Value |
|--------|--------|
| Items | **2** complete |
| Review effort / rounds | **5** / **2** per item |
| Final open issues | **0** |
| Arch critical | **0** |
| Anexo H milestones | **10/10** (H0–H9) |

## Learnings / Patterns

1. **Staging capture is admin-layer, post-decision** — `save_correction` from `handle_correct` (timing A before deliver) keeps Learning out of the cognitive pipeline (AGENTS.md).
2. **Owner history belongs on success paths only** — supervised resolve + autonomous finalize; fail/freeze/claim-lost skip; I/O failures log-and-continue.
3. **Sandbox persist gate must cover history and staging** — without `should_persist`, sandbox success polluted durable `message_history` (fix-round C).
4. **Cognitive ClockPort must live in cognitive/ports** — do not import application `ClockPort` (layer purity); duplicate Protocol is intentional.
5. **Half-open schedule windows need both bounds in suite** — `inicio <= hora < fin`; gold both 16:00 inclusive and 23:59 exclusive avoids false green.
6. **ANEXO gold times can disagree with catalog blocks** — lock suite to catalog reality (practicas 16–21, not annex-stale 14:30), document deviation in SUMMARY.

## Residuals

### Auto-items / Deferred

| Residual | Class | Source |
|----------|-------|--------|
| Multi-segment history linking (all `message_ids`, not only `[0]`) | in-scope-followup deferred | H7 SUMMARY / pool residual |
| VIP inbound history under sandbox | out-of-scope (pre-H7) | H7 review residual |

### Out of scope (documented only)

| Residual | Class | Source |
|----------|-------|--------|
| Promote UI for staging candidates (REQ-ADM-08) | out-of-scope | H7 SUMMARY |
| Recontact / Promo owner history parity | out-of-scope | H7 PLAN non-goal |
| H9.5 `is_first_message_of_day` UTC `.date()` vs CDMX `dia_semana` | out-of-scope / polish | H9 review accepted residual |
| `contratos_restantes.md` half-seat schedule wording | out-of-scope docs | H9 SUMMARY residual |
| Ops: enable `FEATURE_STAGING_ENABLED` when ready | ops | H7 next |

Full residual index: `.grok/agent-memory/residuals/h7-h9-pool.md`.

## Roadmap Updates

- `docs/ANEXO-H.md` status table: **H7** and **H9** → ✅ implemented with commit evidence; resumen **10/10**; verification date pool close 2026-07-27.
- `.planning/quick/h7-corrections-history/SUMMARY.md` — review stats + next.
- `.planning/quick/h9-schedule/SUMMARY.md` — fix-round `410ab74` + review stats.
- Documentador report: this file.
- Residuals consolidated under `.grok/agent-memory/residuals/h7-h9-pool.md`.
- No `HARDENING_ROADMAP.md` in repo — close recorded here + ANEXO-H.

## Docs commit

`docs(anexo-h): mark H7 and H9 complete after hardener pool` (see `git log -1 --oneline` for hash)

## Next Steps

1. Orchestrator **Commit Gate de pool** after this docs commit.
2. Product/ops: decide when to enable `FEATURE_STAGING_ENABLED`.
3. Deferred candidates: multi-segment history ids; Promote UI (REQ-ADM-08).
4. Optional polish: recontact/promo history parity; H9.5 day boundary UTC vs CDMX.
5. Diagnostic still open: production `needs_examples` not firing (post-H7 staging feed may help once promote path exists).
