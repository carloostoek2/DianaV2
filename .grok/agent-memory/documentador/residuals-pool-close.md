# Pool Documentation: residuales H7/H9

**Items:** 5 (+ multi-segment pre-shipped verify-only)  
**Date:** 2026-07-28  
**Project:** DianaV2  
**Pool:** residuals-h7h9  
**Mode:** residuales post hardener H7+H9 · Strict TDD · effort 4 · CLARIFY override hasta 6 ítems  

## Consolidated Outcomes

### ITEM 1 — VIP sandbox history

| Field | Value |
|-------|--------|
| Outcome | VIP inbound `message_history` skipped when sandbox active (`should_persist` false); mirrors owner outbound gate. |
| Commits | `0cb21db` test · `a8212b1` fix |
| Tests | orch sandbox belt green (101 unit pack per SUMMARY) |
| Gates | arch PASS · TG OK · self-check PASSED · review **0** |

**Evidence:** `.planning/quick/residual-vip-sandbox-history/SUMMARY.md`, `gsd-residual-vip-sandbox-history.log`, review `residual-vip-sandbox-history.md`.

### ITEM 2 — Multi-segment owner history

| Field | Value |
|-------|--------|
| Outcome | One `role=owner` row per segment when `texts` 1:1 with `message_ids`; shared helper admin+orch. |
| Commits | pre-shipped `16773ee` · `d8b259b` · `252c62b` · `50178c4` (verify-only this pool) |
| Tests | owner_history / multi-seg suite green (15 + 6 per SUMMARY) |
| Gates | verify-only · no new production commits from residual executor |

**Evidence:** `.planning/quick/residual-multi-segment-history/SUMMARY.md`.

### ITEM 3 — H9.5 CDMX day boundary

| Field | Value |
|-------|--------|
| Outcome | `is_first_message_of_day` uses America/Mexico_City civil day; aligns with `dia_semana` / `hora_actual`. |
| Commits | `65dcc22` test · `5aae5be` fix |
| Tests | focus 9 + cognitive 390 passed |
| Gates | arch PASS · self-check PASSED · review **0** |

**Evidence:** `.planning/quick/residual-h95-cdmx/SUMMARY.md`, `gsd-residual-h95-cdmx.log`, review `residual-h95-cdmx.md`.

### ITEM 4 — Recontact owner history

| Field | Value |
|-------|--------|
| Outcome | After successful recontact deliver, append owner history via shared helper; sandbox `should_persist` gate. **Promo does not write history** (CLARIFY). |
| Commits | `84fcf69` test · `73eaea6` feat (+ composition inject) |
| Tests | 44 / 106 / 6 packs green per SUMMARY |
| Gates | arch PASS · TG OK · self-check PASSED · review **0** |

**Evidence:** `.planning/quick/residual-recontact-history/SUMMARY.md`, `gsd-residual-recontact-history.log`, review `residual-recontact-history.md`.

### ITEM 5 — Promote UI (REQ-ADM-08)

| Field | Value |
|-------|--------|
| Outcome | Owner `/staging` lists pending **example** candidates; Promote/Discard keyboards; StagingService list/promote/discard hardened; router wired before catch-all. No auto-promote. |
| Commits | `df0f5fc` · `1330dec` · `a18d68c` · `caa8cf4` |
| Tests | 218 passed (staging + admin + composition + related telegram) |
| Gates | arch PASS · TG OK · self-check PASSED · review **0** |

**Evidence:** `.planning/quick/residual-promote-ui/SUMMARY.md`, `gsd-residual-promote-ui.log`, review `residual-promote-ui.md`.

### Pool aggregate

| Metric | Value |
|--------|--------|
| Items | **5** complete (+ multi-seg verify-only) |
| Review | **0 open** per item (effort 4) |
| Arch critical | **0** |
| Promo history | **explicit NO** |
| CLARIFY | `.planning/quick/residuals-h7h9-CLARIFY.md` |

## Learnings / Patterns

1. **Sandbox isolation is a single gate** — `should_persist` covers VIP inbound, owner outbound, recontact, and staging; partial gates regress pollution.
2. **Multi-segment history needs `DeliveryResult.texts` 1:1 with `message_ids`** — ports first, then Behavior populate, then application append N rows.
3. **Civil-day TZ bugs hide until boundary cases** — UTC `.date()` vs CDMX needs Windows A/B tests (pre/post 00:00 CDMX).
4. **Recontact is Application-owned history** — Behavior acts-only; inject history+sandbox in composition like admin/orch.
5. **Promote UI is queue MVP, not notify-inline** — `/staging` + callback keyboards; example-only; flag-off → `staging=None`.
6. **Docs half-seat schedule was stale after H9** — documentador closes `contratos_restantes.md` wording at residuales pool close (CLARIFY §4).

## Residuals

### Auto-items / Deferred

None blocking. Optional backlog from Promote UI SUMMARY:

| Residual | Class |
|----------|-------|
| Embed on promote (zero vector) | out-of-scope backlog |
| CAS promote TOCTOU | out-of-scope backlog |
| Policy promote UI | out-of-scope (example-only) |
| Promote on correction notify | out-of-scope |

### Out of scope (documented only)

| Residual | Note |
|----------|------|
| Promo outbound history | CLARIFY: NO — anti-contaminación / no-VIP |
| Auto-promote | forbidden |
| H0–H9 rework | not reopened |

## Roadmap Updates

| Path | Change |
|------|--------|
| `docs/ANEXO-H.md` | Status table residuales 2026-07-28; H7/H9 residual notes; H9.5 CDMX state; Promote UI no longer open residual |
| `docs/contratos_restantes.md` | Schedule mapping + ScheduleRetriever row: real H9, not half-seat |
| `.grok/agent-memory/residuals/h7-h9-pool.md` | All residuales marked DONE / promo NO remaining |
| `README.md` | Staging flag **yes** + `/staging` promote UX note |
| This report | `.grok/agent-memory/documentador/residuals-pool-close.md` |

## Docs commit

`docs: close residuals pool H7-H9 (sandbox, schedule TZ, recontact history, promote UI)` (see `git log -1 --oneline` for hash)

## Next Steps

1. Orchestrator **Commit Gate de pool** after docs commit.
2. Ops: enable `FEATURE_STAGING_ENABLED` when ready to use `/staging` in production.
3. Optional backlog: example embed on promote; CAS; diagnostic `needs_examples` in production traces.
4. No new residuales pool required for H7/H9 history/UI/TZ scope.
