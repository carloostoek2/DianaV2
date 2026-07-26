# POOL-SUMMARY — f3-pool2-proactivity

**Pool:** f3-pool2-proactivity  
**Phase:** Fase 3 — Producto Completo (SPEC-FASE3.md)  
**Mode:** hardener-agile · Strict TDD · effort 5  
**Date closed:** 2026-07-26  
**Status:** **COMPLETE** — items 1–4; arch 0 critical; test-guardian suite adequate  

**Sources:** item SUMMARYs under this directory · `POOL.md` · inherits pool1 `CLARIFY.md` · arch-enforcer `f3-pool2-proactivity.md` · test-guardian `f3-pool2-proactivity.md` · git commits listed below.

---

## Objective

Ship the **proactivity surface** for Fase 3: recontact-by-silence, promo for non-VIP, and BR-07 cancel of pending recontact on VIP message — without LLM, without breaking Fase 2 when flags are off.

| SPEC / roadmap | Scope covered |
|----------------|---------------|
| H3.3 | RecontactService + `is_blocked` + scheduled job + `recontact_schedules` |
| H3.4 | PromoService + exact match + re-intro + `promo_triggers` / `promo_executions` |
| H3.8 | TurnCoordinator cancel hook on VIP business message |

Out of scope (deferred pools): H3.5/H3.7 calibration + metrics · H3.9 admin dashboard DM · H3.10 integration activation.

---

## Items

| # | Title | Status | Primary evidence (executor SUMMARY) |
|---|--------|--------|-------------------------------------|
| 1 | Schema + repos (migration 008) | done | schema/repos/metadata/seeds package → **68 passed** |
| 2 | RecontactService + job + `is_blocked` | done | task package **79** · Task4 regression **133** (26 service + 5 job) |
| 3 | TC cancel hook (BR-07) | done | TC + recontact + composition + related → **113 passed** (7 BR-07 tests) |
| 4 | PromoService + AuthMiddleware | done | promo + auth + composition + purity → **139 passed** (22 promo + 11 auth) |

**Aggregate gates:** arch-enforcer **PASS WITH NOTES** (0 critical) · test-guardian **suite protege adecuadamente** (0 blocking GAPS, 0 mocks prohibidos).

---

## Commit themes (by item)

### Item 1 — schema + repos

| Commit | Message |
|--------|---------|
| `b87c82e` | `feat(db): add recontact/promo schema migration 008 and ORM models` |
| `96a5f88` | `feat(db): add recontact/promo ports and thin SQL repos` |

Themes: Alembic `008_recontact_promo` (id ≤32), three tables + indexes, seeds (`system_config.recontact`/`promo`, feminine 1st-person ES triggers), ORM table count **19**, thin CRUD repos + application ports. No services/jobs/middleware.

### Item 2 — recontact

| Commit | Message |
|--------|---------|
| `795ceba` | `feat(recontact): add RecontactService schedule/eligibility core` |
| `909032e` | `feat(recontact): execute AMS deliver or supervised skip` |
| `2eb2b20` | `feat(recontact): wire RecontactJob, composition, and main loop` |
| `7004248` | `test(recontact): lock composition wiring for RecontactService` |

Themes: schedule/cancel/`is_blocked`/get_due; template render `{nombre}`/`{producto}`; AMS L2 → Behavior.deliver else `notify_info` + skip; job loop hourly-ready; flag kill-switch; composition + `main` gate. Product composition also co-landed in concurrent promo composition `57ebf15`.

### Item 3 — cancel hook (BR-07)

| Commit | Message |
|--------|---------|
| `7955ee7` | `feat(recontact): cancel pending schedule on VIP turn coordinate` |
| `1c6c680` | `feat(recontact): wire cancel hook into TurnCoordinator composition` |

Themes: `RecontactCanceller` Protocol on TC; VIP path cancel before create/replace; fail-soft; flag/None/owner parity; composition builds `RecontactService` **before** `TurnCoordinator`.

### Item 4 — promo

| Commit | Message |
|--------|---------|
| `79e5def` | `feat(promo): add PromoService exact-match re-intro delivery` |
| `d297212` | `feat(telegram): wire non-VIP promo path into AuthMiddleware` |
| `57ebf15` | `feat(composition): wire PromoService into AuthMiddleware` |

Themes: exact case-insensitive match; first-send full sequence vs re-intro first line when recent; `deliver_with_sequence`; always record `promo_executions` after deliver attempt; Auth non-VIP short-circuit behind `FEATURE_PROMO_ENABLED`; VIP path untouched.

---

## Architecture decisions (locked this pool)

### 1. No LLM in recontact or promo

- Recontact messages = fixed templates + placeholders.
- Promo sequences = stored trigger sequences; re-intro is stored `repeat_first_message`.
- Jobs call Application only; Application never imports cognitive/llm.
- Source: POOL locked decisions · arch-enforcer PASS · item2/item4 SUMMARYs.

### 2. Promo re-send = full sequence with re-intro (never silence)

- CLARIFY: recent execution never silences; first message becomes friendly re-intro when `repeat_first_message` is set.
- `repeat_days` window only drives copy choice via `has_recent_execution`, **not** rate-limit.
- Source: POOL.md · item4 SUMMARY · CLARIFY (pool1).

### 3. Recontact execute matrix (AMS gate substitutes reduced Director)

- PLAN intentional simplification vs AGENTS §4.9 full reduced Director: template + AMS L2 → deliver; else supervised skip + owner notify.
- AGENTS §4.3 hard contract still met: no LLM, templates, freeze/pause/block checks, Behavior only acts.
- Source: item2 SUMMARY · arch-enforcer observation 1.

### 4. BR-07 cancel only on VIP message path

- Cancel pending schedule when flag on + recontact wired + `vip_id` set.
- Owner path zero cancel; fail-soft on cancel errors; flag off = F2 parity.
- Does **not** schedule recontact (API ready for later orchestrator caller).
- Source: item3 SUMMARY · POOL DoD.

### 5. Feature flags default false

- `FEATURE_RECONTACT_ENABLED` / `FEATURE_PROMO_ENABLED` default **false**.
- Migration 008 seeds config blobs/triggers, not FEATURE_* (006 ownership retained).
- Source: arch-enforcer checklist · item1/2/4 SUMMARYs.

---

## Residuals

### In-scope follow-up (not pool-close blockers)

| Residual | Class | Why | Origin |
|----------|--------|-----|--------|
| **`is_blocked` claimed approvals** | in-scope-followup (medium) | `list_waiting()` only returns `waiting`; claimed/in-progress owner approvals are invisible → recontact can fire while owner is handling a claimed approval | item2 SUMMARY · arch medium finding |
| Extend `PendingApprovalStore` / add `has_open_for_vip` | same | Fix path for claimed coverage | arch-enforcer |

### Out of scope (documented only)

| Residual | Class | Why | Origin |
|----------|--------|-----|--------|
| **Auto-`schedule_recontact` on VIP message** | out-of-scope | Pool DoD / BR-07 is **cancel only**; public `schedule_recontact` API ready for later orchestrator caller | item2 residual · item3 residual · arch note 6 |
| Promo rate-limit beyond re-intro copy swap | out-of-scope | Product choice: `repeat_days` changes copy only, never silences | item4 residual · CLARIFY |
| `vips.is_sandbox` column | out-of-scope | Optional `SandboxVipChecker` defaults False | item2 residual A7 |
| Empty-sequence / missing-bc skip `promo_executions` insert | intentional | Insert only after deliver attempt (PLAN algorithm) | item4 deviation · arch note 5 |
| Partial unique index one pending schedule per VIP | deferred | Application upsert; race edge at low volume | arch note 4 |
| DB trigger match does not strip stored `trigger_text` | hygiene | Input strip+lower; seeds clean | arch note 3 |

### Next pool — Pool 3 (calibration / metrics / dashboard)

| Residual | Notes | Origin |
|----------|--------|--------|
| CalibrationService | Windowed percentiles; autonomous margin > supervised | SPEC H3.5 |
| Weekly metrics + style drift job | EmbeddingService drift | SPEC H3.7 |
| Admin DM dashboard summary | SPEC §7.3 shape; promo/recontact config cmds | SPEC H3.9 · CLARIFY |

---

## Metrics

| Metric | Value |
|--------|--------|
| Items completed | **4** (schema, recontact, cancel hook, promo) |
| Critical arch violations | **0** |
| Test-guardian | suite protects adequately · 0 mocks prohibidos |
| Feature flags default | **false** (F2-compatible) |
| Executor package snapshots | 68 / 79–133 / 113 / 139 |
| Behavior purity | green (no LLM/cognitive/aiogram in application services) |

---

## Files / modules touched (pool aggregate)

| Area | Key paths |
|------|-----------|
| Infra / DB | `alembic/versions/008_recontact_promo.py`, ORM models, `recontact_schedules` / `promo_triggers` / `promo_executions` repos |
| Application | `recontact_service.py` (NEW), `promo_service.py` (NEW), `ports.py`, `turn_coordinator.py` (BR-07) |
| Jobs | `jobs/recontact.py` (NEW) |
| Telegram | `middlewares/auth.py` (non-VIP promo path), `setup.py` |
| Composition / main | `composition.py`, `main.py` (`_setup_recontact_job`), `config.py` |
| Tests | schema, repos, recontact service/job, TC BR-07, promo service, auth MW, composition, config, purity |

---

## Pool close note

Pool `f3-pool2-proactivity` closed — 4 items completed (schema 008, RecontactService+job, TC BR-07 cancel, PromoService+auth), tests green per item packages, commits done, documentation updated.

**Next:** Pool 3 — calibration + metrics + drift + dashboard DM. Follow-up residual: extend `is_blocked` for claimed approvals.
