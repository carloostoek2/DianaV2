# POOL: f3-pool2-proactivity

**CLARIFY:** inherits `.planning/quick/f3-pool1-autonomous-core/CLARIFY.md`  
**SPEC:** docs/SPEC-FASE3.md F3-03, F3-04, F3-09  
**Effort:** 5  
**After this pool:** auto-start Pool 3 (calibration + metrics + dashboard)

## Locked decisions (from clarify)
- Promo re-send: **full sequence** with friendly **re-intro** on first message only (not silence)
- User-facing copy: 1st person, friendly feminine Spanish
- Feature flags default **false**
- No LLM in recontact templates or promo
- Recontact: reduced pipeline (no Analyst/Planner); templates + placeholders

## Items (≤4)

| # | Title | DoD | Status |
|---|-------|-----|--------|
| 1 | Schema + repos: recontact_schedules, promo_triggers, promo_executions | Migration 008 (short revision id), ORM, repos, seeds for templates/triggers with first+repeat intro | **done** |
| 2 | RecontactService + job + is_blocked | schedule/cancel/get_due/execute with templates; job hourly-ready; FEATURE_RECONTACT_ENABLED | **done** |
| 3 | TurnCoordinator cancel hook (BR-07) | On VIP business message, cancel pending recontact when flag on | **done** |
| 4 | PromoService + auth middleware | exact match, re-intro sequence, deliver_with_sequence, promo_executions, FEATURE_PROMO_ENABLED | **done** |

## Out of this pool
Calibration, metrics dashboard, autonomous changes (pool1 done)

## Residuals (follow-up / next)
- `is_blocked` claimed approvals not covered by `list_waiting` (in-scope-followup)
- Auto-`schedule_recontact` on VIP message (out-of-scope; cancel only)
- Pool 3: calibration + metrics + drift + dashboard DM

## Estado
```
POOL: f3-pool2-proactivity
All 4 items done (schema, recontact, BR-07 cancel, promo)
Status: CLOSED 2026-07-26
Arch: PASS WITH NOTES (0 critical)
Test-guardian: suite protege adecuadamente
Docs: POOL-SUMMARY.md + documentador/f3-pool2-proactivity.md
Paso: commit gate pool (orchestrator)
```
