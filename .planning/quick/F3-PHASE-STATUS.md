# Fase 3 — Phase Status (master)

**Project:** DianaV2  
**SPEC:** `docs/SPEC-FASE3.md` · limits: `AGENTS.md` v1.2  
**Last updated:** 2026-07-26  
**Status:** **Implementation pools CLOSED** (Pool1 + Pool2 + Pool3) · production flags still **off by default**

**Sources:**  
- `.planning/quick/f3-pool1-autonomous-core/POOL-SUMMARY.md`  
- `.planning/quick/f3-pool2-proactivity/POOL-SUMMARY.md`  
- `.planning/quick/f3-pool3-metrics/POOL-SUMMARY.md`  
- Item SUMMARYs under each pool · migration chain **006–010** (F3 product; **011** = index-only) · `src/diana/config/settings.py` defaults  

---

## Executive summary

Fase 3 product surface is **implemented behind feature flags**. With all F3 flags at default `false`, boot behavior remains **Fase 2–compatible**. Enabling production behavior is an **ops decision**: turn flags on gradually (env + VIP settings), not a new coding pool by default.

**Deploy assumption:** single active bot process — process-local locks, CorrectSession, dedup, rate-limit inventory in [`docs/OPS_SINGLE_INSTANCE.md`](../../docs/OPS_SINGLE_INSTANCE.md).

| Pool | Scope (roadmap) | Status | Closed |
|------|-----------------|--------|--------|
| **Pool1** `f3-pool1-autonomous-core` | H3.1 Decider send · H3.2 AMS+orch · H3.6 advanced behavior | **DONE** | 2026-07-26 |
| **Pool2** `f3-pool2-proactivity` | H3.3 recontact · H3.4 promo · H3.8 BR-07 cancel | **DONE** | 2026-07-26 |
| **Pool3** `f3-pool3-metrics` | H3.5 calibration · H3.7 metrics/drift · H3.9 `/resumen` | **DONE** | 2026-07-26 |

---

## What has been done

### Pool1 — Autonomous core

- `Decision.action="send"` + dual supervised/autonomous thresholds (migration **006**).
- Decider rule: `FEATURE_AUTONOMOUS_MODE` sole unlock → `send` when dims ≥ autonomous mins; else approve fallback.
- AMS L1 (flag) / L2 (global_mode \| `vip.auto_send` migration **007**) + orchestrator deliver **outside chat lock**.
- Behavior: freeze hard-check, dual-gate split + rich quirks (pause \| natural_split \| typo_correct), `deliver_with_sequence`.
- **Docs:** `f3-pool1-autonomous-core/POOL-SUMMARY.md`

### Pool2 — Proactivity

- Schema migration **008**: `recontact_schedules`, `promo_triggers`, `promo_executions` + thin repos.
- RecontactService (templates, no LLM) + RecontactJob; AMS L2 deliver vs supervised skip.
- TurnCoordinator BR-07: cancel pending recontact on VIP message (cancel-only, not schedule).
- PromoService: exact case-insensitive match; re-intro first line on recent execution; AuthMiddleware non-VIP path.
- **Docs:** `f3-pool2-proactivity/POOL-SUMMARY.md`

### Pool3 — Calibration, metrics, dashboard

- CalibrationService + pure math + SQL data source + migration **009** (calibration JSON seed).
- Margin invariant: autonomous ≥ supervised + **0.05**; smooth 50/50; style drift via **EmbeddingService**.
- MetricsAggregationService + EAV `learning_metrics` + MetricsJob (observational; can run with calibration flag off).
- AdminMetricsService + owner `/resumen` / `/metricas` + JSON export keyboard.
- Composition + main: metrics job always when built; calibration job **only if** `feature_calibration_enabled`.
- A2: `detect_drift` observational when flag off; threshold writes + owner alerts still gated.
- **Docs:** `f3-pool3-metrics/POOL-SUMMARY.md`

---

## Feature flags (defaults)

All Fase 3 flags default **`false`** in Settings (`src/diana/config/settings.py`) and migration **006** seeds:

| Flag (Settings field / env var) | Default | Gates |
|---------------------------------|---------|--------|
| `feature_autonomous_mode` / `FEATURE_AUTONOMOUS_MODE` | **false** | Decider may emit `send`; AMS L1; auto-deliver path (L2 = global autonomous or VIP `auto_send`) |
| `feature_recontact_enabled` / `FEATURE_RECONTACT_ENABLED` | **false** | Recontact job + BR-07 cancel path |
| `feature_promo_enabled` / `FEATURE_PROMO_ENABLED` | **false** | Non-VIP promo Auth path |
| `feature_calibration_enabled` / `FEATURE_CALIBRATION_ENABLED` | **false** | Threshold writes + calibration job + drift alerts |
| `feature_advanced_behavior` / `FEATURE_ADVANCED_BEHAVIOR` | **false** | Split + human quirks dual-gate |

**Runtime SoT = process Settings/env.** Migration seeds write `FEATURE_*` into `system_config` for inventory/future merge; **DB keys are not live overrides** today (composition wires `settings.feature_*` only).

**Invariant:** flag off ⇒ no new F3 side effects on that surface (metrics aggregation may still run as observational telemetry without writing thresholds).

---

## Migration chain (F3)

| Rev | Purpose |
|-----|---------|
| `006_f3_flags_thresholds` | F3 flags false + dual threshold seeds |
| `007_vip_auto_send` | VIP `auto_send` column |
| `008_recontact_promo` | recontact/promo tables + seeds |
| `009_f3_calibration` | calibration config JSON seed |
| `010_owner_marks` | owner false-positive marks (`owner_marks`) |

---

## Roadmap coverage map

| ID | Capability | Pool | State |
|----|------------|------|-------|
| H3.1 | Decider autonomous send + dual thresholds | 1 | **done** |
| H3.2 | AMS + orchestrator send path | 1 | **done** |
| H3.3 | Recontact by silence | 2 | **done** |
| H3.4 | Promo non-VIP | 2 | **done** |
| H3.5 | CalibrationService | 3 | **done** |
| H3.6 | Advanced behavior (split + quirks) | 1 | **done** |
| H3.7 | Weekly metrics + style drift | 3 | **done** |
| H3.8 | Cancel recontact on VIP message (BR-07) | 2 | **done** |
| H3.9 | Admin metrics DM `/resumen` | 3 | **done** |
| H3.10 | Integration activation / gradual enable | ops | **pending ops** (not a code pool by default) |

---

## Residuals (consolidated)

### Hardening residual pack `f3-residuals` — **DONE** (2026-07-26)

Plan: `.planning/quick/f3-residuals/PLAN.md` · Summary: `.planning/quick/f3-residuals/SUMMARY.md` · Log: `.planning/quick/gsd-f3-residuals.log`

| Residual | Status | Notes |
|----------|--------|-------|
| **R1** `list_open` / `is_blocked` claimed approvals | **done** | `PendingApprovalStore.list_open` (waiting+claimed); recontact + route resolver |
| **R2** Runtime thresholds after calibration | **done** | `RuntimeThresholds` shared; Decider re-reads mins each `decide()`; calibration applies live |
| **R3** VIP activity seeds recontact clock | **done** | TC: cancel then `schedule_recontact` (fail-soft both) when flag on |
| **R4** MetricsJob durable last-success week | **done** | `system_config` key `metrics.last_success_week` |
| **R5** Owner false-positive marks | **done** | `owner_marks` migration **010**, `AdminService.mark_false_positive`, metrics `fp/escalate` rate |

### Closed follow-ups (docs-verified)

| Residual | Status | Evidence |
|----------|--------|----------|
| Load calibrated thresholds from DB at boot (`RuntimeThresholds`) | **done** | `src/diana/composition.py` — `load_runtime_thresholds`; `src/diana/main.py` — boot `await load_runtime_thresholds(app)`; tests: `tests/unit/application/test_load_runtime_thresholds.py` |

### Follow-ups still open (not in residual pack)

| Residual | Priority | Origin |
|----------|----------|--------|
| Exact Sunday 03:00 UTC cron (v1 = hourly + internal gates) | low | Pool3 |
| Telegram `/fp <turn_id>` UI (API exists) | low | R5 · pool `residuals-polish` item 2 |

Polish pool `residuals-polish` in progress (item1 docs-sync **done**; remaining open: `/fp`, naturalness MVP, profile REAL) — see `.planning/quick/residuals-polish/`.

### Documented out-of-scope (do not expand without product ask)

| Residual | Origin |
|----------|--------|
| Naturalness `Decision.action=regenerate` or >1 retry (full loop). **1× re-draft MVP** is in-scope under `residuals-polish` item 3 | Pool1 / CLARIFY |
| Promo hard rate-limit silence | Pool2 / CLARIFY |
| Gray-zone trigger name list in `/resumen` | Pool3 |
| Multi-worker durable CAS / claim token — process-local inventory: [`docs/OPS_SINGLE_INSTANCE.md`](../../docs/OPS_SINGLE_INSTANCE.md) | Pool1 |
| `system_config.behavior` runtime merge | Pool1 |

---

## Next operations (enable flags gradually)

**Single-instance only** — see [`docs/OPS_SINGLE_INSTANCE.md`](../../docs/OPS_SINGLE_INSTANCE.md) before enabling jobs/autonomous on any host with more than one bot process.

Recommended order for non-prod → prod (one surface at a time; verify; then next):

1. **Observability first (safe):** leave `FEATURE_CALIBRATION_ENABLED=false`; ensure MetricsJob + `/resumen` run against real data; confirm EAV rows and owner DM layout.
2. **Advanced behavior (low risk):** `FEATURE_ADVANCED_BEHAVIOR=true` for split/quirks only when the delivery context enables those options.
3. **Promo (isolated):** `FEATURE_PROMO_ENABLED=true`; validate exact triggers + re-intro; no VIP path impact.
4. **Recontact:** `FEATURE_RECONTACT_ENABLED=true`; verify freeze/pause/`is_blocked` (waiting+claimed), BR-07 cancel+schedule on VIP msg, job cadence.
5. **Autonomous:** `FEATURE_AUTONOMOUS_MODE=true` + per-VIP `auto_send` / global mode; start with high thresholds; confirm demote-to-approve when VIP/global auto-send path is off; deliver outside chat lock + freeze checks.
6. **Calibration last:** `FEATURE_CALIBRATION_ENABLED=true` after enough traces exist; verify margin 0.05, smooth, owner drift alerts; live `RuntimeThresholds` updates Decider without restart.

Rollback = set flag false (no redeploy required for kill-switch surfaces).

---

## Close note

> Pool `f3-pool3-metrics` closed — 4 items completed, tests passing, commits done, documentation updated.  
> Residual pack `f3-residuals` (R1–R5) closed 2026-07-26.  
> **Fase 3 implementation (Pools 1–3) + residual hardening complete.** All F3 feature flags remain **default false**. Next: gradual ops enablement.
