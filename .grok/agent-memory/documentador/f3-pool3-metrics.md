# Pool Documentation: f3-pool3-metrics

**Items:** 4  
**Date:** 2026-07-26  
**Project:** DianaV2  
**Pool:** f3-pool3-metrics  
**Mode:** hardener-agile · Fase 3 calibration + metrics + dashboard  
**SPEC:** docs/SPEC-FASE3.md (H3.5, H3.7, H3.9 / F3-05, F3-07, F3-08)

## Consolidated Outcomes

### Item 1 — CalibrationService

| Field | Value |
|-------|--------|
| Outcome | Pure math (percentile/margin/smooth/cosine drift) + `CalibrationService.calibrate_thresholds` / `detect_drift`; margin autonomous ≥ supervised + 0.05; SQL data source + system_config writers; migration **009** calibration JSON seed. Jobs-only; no pipeline hooks. |
| Commits | `8c72f2a` math · `81d41ac` service · `83e9867` SQL/migration |
| Tests | **38** primary · **90** related (SUMMARY) |
| Self-check | PASSED |

### Item 2 — Weekly metrics job

| Field | Value |
|-------|--------|
| Outcome | `MetricsAggregationService` §7.1 fields; EAV `SqlLearningMetricsRepo` replace_week; `MetricsJob` loop; SQL trace/side sources; optional DriftDetector; independent of calibration flag. |
| Commits | `179be4b` service · `a17bddd` repo · `c0d0910` job · `7133e14` SQL readers |
| Tests | **24 passed** |
| Self-check | PASSED |

### Item 3 — Admin dashboard DM

| Field | Value |
|-------|--------|
| Outcome | `AdminMetricsService` Spanish §7.3 summary + export JSON; owner `/resumen` + `/metricas`; keyboard `mx:e`/`mx:b` callbacks. Application free of aiogram. |
| Commits | `7eb79ec` service · `2b02060` commands · `12223b8` callbacks |
| Tests | admin metrics **20** · telegram related **127** |
| Self-check | PASSED |

### Item 4 — Wiring

| Field | Value |
|-------|--------|
| Outcome | `CalibrationJob`; composition wires calibration/metrics/admin_metrics + dispatcher; main schedules metrics always (when built), calibration only if flag on; A2: detect_drift observational when flag off; threshold writes + alerts still gated. |
| Commits | `5bec0b9` job · `14b793a` composition · `70129ec` main |
| Tests | wiring pack **113 passed** |
| Self-check | PASSED |

### Pool aggregate

| Metric | Value |
|--------|--------|
| Items | **4** complete |
| Pipeline violations | **0** (calibration post-hoc jobs only) |
| Flags default | **false** (F2-compatible) |
| Roadmap slice | **H3.5 + H3.7 + H3.9 done** |
| Master status | `.planning/quick/F3-PHASE-STATUS.md` (Pool1+2+3) |

## Learnings / Patterns

1. **Jobs-only calibration** — Threshold mutation never enters Director/Decider/post_turn; AGENTS residual “reload after calibrate” is explicit follow-up, not silent mid-turn rewrite.
2. **A2 dual use of CalibrationService** — Split observational drift (metrics) from gated writes/alerts so MetricsJob can run with `FEATURE_CALIBRATION_ENABLED=false`.
3. **EAV metrics stay schema-stable** — `learning_metrics` EAV (003) absorbs style_drift and week fields without ALTER for score columns.
4. **Margin invariant is product safety** — autonomous ≥ supervised + 0.05 prevents autonomous from becoming looser than supervised after calibrate.
5. **Owner UX operational Spanish** — `/resumen` is ops register (pool1 CLARIFY), not VIP brand voice.

## Residuals

### Auto-items / Deferred

| Residual | Class | Target |
|----------|--------|--------|
| Decider/process threshold reload after calibrate | in-scope-followup | small hardening / boot merge |
| MetricsJob last-success week durable marker | in-scope-followup | metrics job v2 |
| `is_blocked` claimed approvals (from Pool2) | in-scope-followup (medium) | recontact hardening |

### Out of scope (documented only)

| Residual | Class |
|----------|--------|
| Exact Sunday 03:00 UTC cron | out-of-scope (hourly+gates v1) |
| FP escalation rate / owner mark model | out-of-scope |
| Gray-zone trigger names in summary | out-of-scope |
| Baseline embedding cache write when flag off | out-of-scope (not threshold write) |

## Roadmap Updates

- **POOL-SUMMARY** written: `.planning/quick/f3-pool3-metrics/POOL-SUMMARY.md`
- **POOL.md** marked CLOSED
- **Master F3 status** created: `.planning/quick/F3-PHASE-STATUS.md` (Pool1+2+3 done, residuals, flags default false, gradual enable ops)
- MEMORY index Documentador entry added

## Docs commit

_(filled after git commit)_

## Next Steps

1. Orchestrator **Commit Gate de pool** after this docs commit.
2. **Ops:** enable F3 flags gradually per `F3-PHASE-STATUS.md` (metrics observability → advanced behavior → promo → recontact → autonomous → calibration last).
3. Optional hardening: claimed-approval `is_blocked`, threshold reload, durable metrics week cursor.
