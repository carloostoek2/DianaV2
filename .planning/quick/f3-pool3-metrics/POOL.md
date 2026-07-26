# POOL: f3-pool3-metrics

**Status:** **CLOSED** 2026-07-26 — see `POOL-SUMMARY.md`  
**SPEC:** docs/SPEC-FASE3.md §5.5, §6.4, §7.1–7.3  
**CLARIFY:** full SPEC metrics + style drift via EmbeddingService; FEATURE_CALIBRATION_ENABLED default false  
**AGENTS:** calibration only in jobs; dual thresholds margin 0.05  
**After:** Pool 3 closes F3-05 / F3-07 / F3-08 · master status `.planning/quick/F3-PHASE-STATUS.md`

## Locked decisions

- Full style drift via existing `EmbeddingService` (not stub)
- Feature flags default **false** (`FEATURE_CALIBRATION_ENABLED`)
- Margin: autonomous ≥ supervised + **0.05**
- `learning_metrics` stays **EAV** (003 schema); no `style_drift_score` column ALTER
- Calibration never in turn pipeline
- Metrics job observational (can run with calibration flag off); threshold writes gated

## Items (≤4)

| # | Path | Title | Depends |
|---|------|-------|---------|
| 1 | `item1-calibration/PLAN.md` | CalibrationService + margin + detect_drift | — |
| 2 | `item2-metrics-job/PLAN.md` | Weekly learning_metrics aggregation job | drift optional from 1 |
| 3 | `item3-dashboard/PLAN.md` | Admin `/resumen` DM §7.3 | store from 2 |
| 4 | `item4-wiring/PLAN.md` | composition + jobs + flags | 1–3 |

## Order

1 → 2 → 3 → 4 (2 can TDD in parallel with fakes; 4 last)
