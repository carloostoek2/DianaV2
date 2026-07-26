# POOL-SUMMARY — f3-pool3-metrics

**Pool:** f3-pool3-metrics  
**Phase:** Fase 3 — Producto Completo (SPEC-FASE3.md)  
**Mode:** hardener-agile · Strict TDD  
**Date closed:** 2026-07-26  
**Status:** **COMPLETE** — items 1–4; tests green per item packages; self-checks PASSED  

**Sources:** item SUMMARYs under this directory · `POOL.md` · inherits pool1 `CLARIFY.md` · git commits listed below.

---

## Objective

Ship the **calibration + metrics + dashboard** surface for Fase 3: post-hoc threshold calibration with dual-margin invariant, weekly `learning_metrics` aggregation with optional style drift via `EmbeddingService`, and owner DM `/resumen` — without writing thresholds from the turn pipeline and without enabling calibration by default.

| SPEC / roadmap | Scope covered |
|----------------|---------------|
| H3.5 / F3-05 | CalibrationService: windowed percentiles, smooth, margin autonomous ≥ supervised + 0.05, detect_drift |
| H3.7 / F3-07 | Weekly metrics job + EAV `learning_metrics` + style drift score |
| H3.9 / F3-08 | Admin DM dashboard `/resumen` (+ `/metricas`) §7.3 |

Out of scope (post-F3 ops / residual hardening): H3.10 gradual flag enablement in production · exact Sunday 03:00 cron · Decider live threshold reload · FP escalation owner-mark model.

---

## Items

| # | Title | Status | Primary evidence (executor SUMMARY) |
|---|--------|--------|-------------------------------------|
| 1 | CalibrationService + math + SQL + migration 009 | done | math + service + system_config + migration → **38** primary / **90** related |
| 2 | MetricsAggregationService + EAV repo + MetricsJob | done | service + job + repo → **24 passed** |
| 3 | AdminMetricsService + `/resumen` + export callbacks | done | admin metrics **20** + telegram related **127** |
| 4 | Composition + jobs + main wiring + A2 drift patch | done | wiring pack → **113 passed** |

**Aggregate gates:** executor self-checks **PASSED** all items · no pipeline / Director / Decider mutation for calibration writes · flags remain default **false**.

---

## Commit themes (by item)

### Item 1 — calibration

| Commit | Message |
|--------|---------|
| `8c72f2a` | `feat(calibration): pure math for percentile, margin, smooth, drift` |
| `81d41ac` | `feat(calibration): CalibrationService calibrate_thresholds + detect_drift` |
| `83e9867` | `feat(calibration): system_config writers, SQL data source, migration 009` |

Themes: numpy-free math; flag-gated threshold writes; full style drift via `EmbeddingService`; baseline freeze key; audit `calibration.last_run`; migration 009 seeds calibration JSON only (revises 008).

### Item 2 — metrics job

| Commit | Message |
|--------|---------|
| `179be4b` | `feat(metrics): add MetricsAggregationService for weekly §7.1 fields` |
| `a17bddd` | `feat(metrics): add SqlLearningMetricsRepo EAV replace/get week` |
| `c0d0910` | `feat(metrics): add MetricsJob weekly aggregation loop` |
| `7133e14` | `feat(metrics): add SqlMetricsDataSource week readers` |

Themes: observational weekly job; EAV replace-week idempotent; optional `DriftDetector`; no composition yet; independent of `FEATURE_CALIBRATION_ENABLED`.

### Item 3 — dashboard

| Commit | Message |
|--------|---------|
| `7eb79ec` | `feat(admin): add AdminMetricsService weekly summary formatter` |
| `2b02060` | `feat(telegram): add /resumen and /metricas owner commands` |
| `12223b8` | `feat(telegram): metrics export and back callbacks` |

Themes: §7.3 Spanish layout; empty week honest; JSON export via keyboard `mx:e`/`mx:b`; application free of aiogram; composition deferred to item4.

### Item 4 — wiring

| Commit | Message |
|--------|---------|
| `5bec0b9` | `feat(jobs): add CalibrationJob cycle wrapper` |
| `14b793a` | `feat(composition): wire calibration, metrics, and /resumen dashboard` |
| `70129ec` | `feat(main): schedule metrics and flag-gated calibration jobs` |

Themes: AppContainer fields; metrics job always (when built); calibration job only if `feature_calibration_enabled`; A2 patch: `detect_drift` observational even when flag off, threshold writes + owner alerts still gated; shutdown order calibration → metrics → recontact → purge → expiration.

---

## Architecture decisions (locked this pool)

### 1. Calibration never in the turn pipeline

- Jobs → Application only; no hooks from Director / Decider / post_turn.
- Source: POOL locked decisions · item1 SUMMARY · AGENTS §4.5 / §5.4.

### 2. Dual thresholds margin ≥ 0.05

- Autonomous mins must stay ≥ supervised + `autonomous_margin_min` (default 0.05).
- Smooth 50/50 with previous store; defaults from `cognitive/thresholds.py` when empty.
- Source: POOL.md · item1 SUMMARY · AGENTS dual-threshold rule.

### 3. Full style drift via EmbeddingService (not stub)

- `detect_drift` uses real embeddings; baseline freeze key `calibration.style_baseline_embedding`.
- Drift score stored in EAV as observational metric; no `style_drift_score` column ALTER.
- Source: POOL locked decisions · item1/2 SUMMARYs.

### 4. A2 flag scope (item4)

- **`calibrate_thresholds`** (writes) + owner drift **alerts** gated by `FEATURE_CALIBRATION_ENABLED`.
- **`detect_drift`** may run for metrics aggregation when flag is false (observational).
- Baseline embedding cache write during detect_drift is not a threshold mutation.
- Source: item4 SUMMARY A2 patch.

### 5. Metrics job independent of calibration flag

- Weekly aggregation always schedulable when composition builds `app.metrics`.
- Drift optional via CalibrationService as `DriftDetector`.
- Source: POOL locked decisions · item2 SUMMARY A3 · item4 wiring.

### 6. Feature flags default false

- `FEATURE_CALIBRATION_ENABLED` / Settings `feature_calibration_enabled` default **false**.
- All other F3 flags remain false (F2-compatible boot).
- Source: config.py · migration 006 · item4 success criteria.

---

## Residuals

### In-scope follow-up (not pool-close blockers)

| Residual | Class | Why | Origin |
|----------|--------|-----|--------|
| Decider / process threshold reload after calibrate | in-scope-followup | Thresholds re-read on next boot / future reload; pure defaults at process start until restart | item1 residual · item4 residual |
| MetricsJob last-success week in-memory only | in-scope-followup | PLAN A6 v1; crash may re-aggregate same week (idempotent replace is safe) | item2 residual |

### Out of scope (documented only)

| Residual | Class | Why | Origin |
|----------|--------|-----|--------|
| Exact Sunday 03:00 UTC cron | out-of-scope | Hourly tick + internal week/calibrate gates in v1 | item4 residual |
| `false_positive_escalation_rate` always 0.0 | out-of-scope | No owner FP mark model (post-F3 UI) | item2 residual |
| Gray-zone trigger name list in `/resumen` | out-of-scope | Store only has count until later fields | item3 residual |
| FP integer when only rate stored | out-of-scope | No escalations denominator; rate always 0.0 today | item3 residual |
| Baseline cache write when calibration flag off | out-of-scope | Needed for consistent drift scoring; not threshold write | item4 residual |

### Carried from Pool 2 (still open)

| Residual | Class | Origin |
|----------|--------|--------|
| `is_blocked` claimed approvals not covered by `list_waiting` | in-scope-followup (medium) | pool2 item2 · arch medium |
| Auto-`schedule_recontact` on VIP message | out-of-scope (BR-07 cancel only) | pool2 |

---

## Metrics

| Metric | Value |
|--------|--------|
| Items completed | **4** (calibration, metrics job, dashboard, wiring) |
| Critical arch violations (executor claims) | **0** pipeline violations; jobs-only calibration |
| Feature flags default | **false** (F2-compatible) |
| Executor package snapshots | 38–90 / 24 / 20+127 / 113 |
| Migrations | **009** calibration JSON seed (chain 006→007→008→009) |

---

## Files / modules touched (pool aggregate)

| Area | Key paths |
|------|-----------|
| Application | `calibration_math.py`, `calibration_service.py`, `metrics_service.py`, `admin_metrics_service.py` |
| Infra / DB | `009_f3_calibration.py`, `SqlCalibrationDataSource`, `SqlLearningMetricsRepo`, `SqlMetricsDataSource`, system_config set/get calibration |
| Jobs | `jobs/calibration.py`, `jobs/metrics.py` |
| Telegram | `handlers/admin.py` (`/resumen`, `/metricas`), `keyboards.py` (`mx:*`), `handlers/callbacks.py` |
| Composition / main | `composition.py` (container + build), `main.py` (metrics always, calibration flag-gated) |
| Tests | calibration math/service, metrics service/job/repo, admin metrics, telegram resumen/callbacks, composition + main wiring |

---

## Pool close note

Pool `f3-pool3-metrics` closed — 4 items completed (CalibrationService+drift, weekly metrics EAV job, `/resumen` dashboard, composition/main wiring), tests green per item packages, commits done, documentation updated.

**Fase 3 implementation pools 1–3 complete** (autonomous core + proactivity + metrics).  
**Next ops:** enable feature flags **gradually** in non-prod first; residual hardening (`is_blocked` claimed approvals, threshold reload, optional Sunday cron, FP model).
