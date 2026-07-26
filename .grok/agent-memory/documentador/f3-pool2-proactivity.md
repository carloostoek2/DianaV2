# Pool Documentation: f3-pool2-proactivity

**Items:** 4  
**Date:** 2026-07-26  
**Project:** DianaV2  
**Pool:** f3-pool2-proactivity  
**Mode:** hardener-agile · Fase 3 proactivity · effort 5  
**SPEC:** docs/SPEC-FASE3.md (H3.3, H3.4, H3.8)

## Consolidated Outcomes

### Item 1 — Schema + repos (008)

| Field | Value |
|-------|--------|
| Outcome | Migration `008_recontact_promo` + ORM (19 tables) + ports + thin SQL repos for schedules/triggers/executions; seeds recontact/promo config + 2 feminine ES triggers with `repeat_first_message`. Zero runtime path. |
| Commits theme | `b87c82e` schema/ORM · `96a5f88` ports/repos |
| Tests | **68 passed** (schema + repos + metadata + seeds + config + purity) |
| Arch / TG | item1 PASS WITH NOTES · suite OK |

### Item 2 — RecontactService + job

| Field | Value |
|-------|--------|
| Outcome | `RecontactService`: schedule/cancel/`is_blocked`/get_due/execute; templates no LLM; AMS L2 deliver vs supervised skip+notify; `RecontactJob` hourly-ready; composition + main flag gate. |
| Commits theme | `795ceba` core · `909032e` execute · `2eb2b20` job/main · `7004248` composition test lock · co-wire `57ebf15` |
| Tests | task package **79** · regression **133** (26 service + 5 job) |
| Arch / TG | PASS WITH NOTES · suite OK |

### Item 3 — TC cancel hook (BR-07)

| Field | Value |
|-------|--------|
| Outcome | VIP coordinate path cancels pending recontact when flag on; fail-soft; owner/flag-off/None parity; composition builds recontact before TC. |
| Commits theme | `7955ee7` hook · `1c6c680` composition |
| Tests | **113 passed** (7 BR-07 + TC matrix) |
| Arch / TG | PASS · suite OK |

### Item 4 — PromoService + Auth

| Field | Value |
|-------|--------|
| Outcome | Exact case-insensitive match; first-send full sequence vs re-intro on recent; `deliver_with_sequence`; record `promo_executions` after attempt; Auth non-VIP path behind `FEATURE_PROMO_ENABLED`. |
| Commits theme | `79e5def` service · `d297212` auth MW · `57ebf15` composition |
| Tests | **139 passed** (22 promo + 11 auth) |
| Arch / TG | PASS WITH NOTES · suite OK |

### Pool aggregate

| Metric | Value |
|--------|--------|
| Critical arch | **0** |
| Test-guardian | suite protege adecuadamente · 0 mocks prohibidos |
| Flags default | false (F2-compatible) |
| Roadmap slice | **H3.3 + H3.4 + H3.8 done** |

## Learnings / Patterns

1. **No-LLM proactivity** — Recontact and promo stay pure application: templates/sequences in, Behavior acts only. Jobs never call cognitive.
2. **AMS gate for recontact send** — Pool intentionally skips full reduced Director; AMS L2 decides deliver vs supervised skip. Hard AGENTS §4.3 still holds.
3. **Promo never silences** — CLARIFY product lock: `repeat_days` only swaps first line to re-intro; spam rate-limit remains OOS residual.
4. **BR-07 cancel-only** — TC hooks cancel, not schedule; schedule API reserved for later post-message / orchestrator callers.
5. **Parallel composition race** — Item2/4 concurrent composition co-commit (`57ebf15`); restored with explicit composition tests (`7004248`, item3 `1c6c680`). Prefer single composition owner when parallelizing pool items that share DI root.
6. **`is_blocked` Protocol gap** — `list_waiting()` ≠ all open approvals; claimed status is a medium product edge for follow-up.

## Residuals

### Auto-items / Deferred

| Residual | Class | Target |
|----------|--------|--------|
| `is_blocked` claimed approvals not covered by `list_waiting` | in-scope-followup (medium) | next hardening / small fix item |
| Extend PendingApprovalStore / `has_open_for_vip` | same | same |

### Out of scope (documented only)

| Residual | Class |
|----------|--------|
| Auto-`schedule_recontact` on VIP message | out-of-scope (BR-07 cancel only) |
| Promo rate-limit beyond re-intro copy | out-of-scope (CLARIFY) |
| `vips.is_sandbox` column | out-of-scope |
| Calibration / metrics / dashboard | Pool 3 (H3.5 / H3.7 / H3.9) |

## Roadmap Updates

- **POOL-SUMMARY** written: `.planning/quick/f3-pool2-proactivity/POOL-SUMMARY.md`
- **POOL.md** marked CLOSED
- No SPEC-FASE3.md edit (roadmap table H3.3/H3.4/H3.8 treated complete by this pool close)
- MEMORY index Documentador entry added

## Docs commit

`(pending commit hash)` — `docs(f3): close pool2 proactivity summary`

## Next Steps

1. Orchestrator **Commit Gate de pool** after this docs commit.
2. Start **Pool 3** — calibration + metrics + drift + dashboard DM.
3. Optional follow-up: claimed-approval coverage in `is_blocked`.
