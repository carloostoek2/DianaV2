# POOL-SUMMARY — owner-admin-sandbox

**Pool:** owner-admin-sandbox  
**Mode:** hardener-agile · Strict TDD · effort 5  
**Date closed:** 2026-07-27  
**Status:** **COMPLETE** — items 1–4; arch 0 critical ×4; test-guardian suite adequate ×4  

**Sources:** item SUMMARYs under this directory · `POOL.md` · `CLARIFY.md` · `docs/PRODUCT_OWNER_ADMIN_SANDBOX.md` · arch-enforcer / test-guardian `owner-admin-sandbox-item*.md` · git commits listed below.

---

## Objective

Ship the **owner admin slice** for real VIP enrichable profiles + VIP CRUD gaps + sandbox fixtures/session/isolation, under product lock in `docs/PRODUCT_OWNER_ADMIN_SANDBOX.md`.

| Product area | Scope covered |
|--------------|---------------|
| Real VIP profile write | facts/notes only; owner `/vip_*`; hollow Option A; length caps; prompt fence |
| Real VIP CRUD gaps | `/list_vips`, `/rename_vip`, `/remove_vip` + best-effort profile purge; private DM gate |
| Sandbox core | Package catalog (6 keys) + in-process `SandboxService` session model |
| Sandbox admin | Commands + auth bypass + knowledge inject + `fake_delivery` + learning skip + recontact skip |

Out of scope (documented residuals): multi-replica sandbox, live fixture catalog edit, VIP hard-delete CASCADE, naturalness multi-retry, Schedule REAL.

---

## Items

| # | Title | Status | Primary evidence (executor SUMMARY + gates) |
|---|--------|--------|-----------------------------------------------|
| 1 | profile-write | done | schema/repo/service/telegram + fix hollow/caps/integrity + fence `1064dcb` · arch PASS WITH NOTES · TG OK · unit post-fix 1279 |
| 2 | vip-crud | done | list/rename/purge cascade + private gate `bd96939` · arch 0 crit · TG focused 94 · unit 1300+ |
| 3 | sandbox-core | done | 6-key catalog + session API · arch 0 crit · TG 16 sandbox / 45 wiring+purity |
| 4 | sandbox-admin | done | commands + pipeline isolation + composition + recontact skip `a0b4b12` · arch 0 crit · TG 288 |

**Aggregate gates:** arch-enforcer **PASS WITH NOTES** (0 critical) ×4 · test-guardian **suite protege adecuadamente** (0 mocks prohibidos) ×4.

---

## Commit themes (by item)

### Item 1 — profile-write

| Commit | Message |
|--------|---------|
| `5546b61` | `feat(profile): content schema helpers and hollow read` |
| `34fa463` | `feat(profile): ProfilesRepo fact/note writers` |
| `9b6acf0` | `feat(profile): ProfileAdminService owner gate` |
| `efa9d09` | `feat(telegram): vip profile admin commands` |
| `13d4401` | `test(profile): harden profile-write coverage after guardian` |
| `fa14727` | `fix(profile): shared hollow helper, length caps, IntegrityError map` |
| `9d9fb35` | `test(profile): cover hollow parity, caps, integrity, format body` |
| `1064dcb` | `fix(cognitive): fence owner profile knowledge in prompt` |

Themes: pure `profile_content` schema; VIP-scoped writers; owner fail-closed service; English `/vip_*`; hollow Option A; length caps; ContextBuilder fence for `knowledge.profile`.

### Item 2 — vip-crud

| Commit | Message |
|--------|---------|
| `5346565` | `feat(vip): list_active and rename on VipStore` |
| `cc120d2` | `feat(profile): delete_by_vip_id and purge on remove` |
| `9cd1107` | `feat(telegram): list_vips rename_vip and remove cascade` |
| `bd96939` | `fix(telegram): private-chat admin gate and best-effort purge` |

Themes: list active ASC; rename without reactivate; soft deactivate + best-effort profile purge; `is_private_owner_message` (owner + private DM).

### Item 3 — sandbox-core

| Commit | Message |
|--------|---------|
| `07952ce` | `feat(sandbox): v1 session core + package fixture catalog` |

Themes: `src/diana/config/sandbox_profiles.json` (6 keys); rewritten pure `SandboxService`; hatch force-include; composition builds iff flag.

### Item 4 — sandbox-admin

| Commit | Message |
|--------|---------|
| `6c1a0ff` | `feat(sandbox): auth bypass and pipeline isolation` |
| `462fea4` | `feat(telegram): sandbox owner commands and session reset` |
| `610d9a4` | `feat(sandbox): wire composition for admin surface` |
| `a0b4b12` | `fix(sandbox): skip recontact for sandbox-active chats` |

Themes: Auth sandbox bypass; `SandboxKnowledgeAugmenter` + Director Protocol hook; orch learning skip + `fake_delivery`; Admin SANDBOX marker; `/sandbox` commands; composition wire; recontact `is_sandbox_vip` via `sandbox.is_active(telegram_user_id)`.

---

## Architecture decisions (locked this pool)

### 1. Real VIP enrichable content = facts + notes only

- Schema: `{ "facts": {str: str}, "notes": [{ "date": "YYYY-MM-DD", "text": str }] }` in `diana.profile_content`.
- Fixed identity (tg id, display name, freeze, auto_send) not edited via profile writers.
- Source: PRODUCT §3 · item1 SUMMARY · CLARIFY P1.

### 2. Hollow Option A + prompt fence

- Empty/whitespace facts+notes shell → hollow (`None` / `profile_empty`).
- Owner profile knowledge fenced in ContextBuilder as non-instruction data (SEC-INJ-01).
- Source: item1 SUMMARY fix-round · `1064dcb`.

### 3. Soft remove + best-effort profile purge (C1 only)

- `/remove_vip` deactivates VIP; purges `profiles` row when `ProfileAdminService` wired; no memories/examples/policies/recontact cascade; no hard-delete migration.
- Source: item2 SUMMARY · arch-enforcer item2.

### 4. Sandbox = frozen catalog + in-process session (no real VIP rows)

- Six fixtures versioned in package JSON; session maps `chat_id → profile_key`; `should_persist` inverse of active.
- No `insert_sandbox` into real `profiles` PK space.
- Source: PRODUCT §4 · item3 SUMMARY · CLARIFY S1/S2.

### 5. Sandbox isolation on turn path

- Auth allowlist bypass when sandbox active; fixture inject as `knowledge.profile`; `fake_delivery`; skip `run_post_turn`; staging gate defensive; recontact skip when chat sandbox-active; owner marker `SANDBOX — profile: {key}`.
- Feature flag `FEATURE_SANDBOX_ENABLED` fail-closed when off.
- Source: PRODUCT §4.4 · item4 SUMMARY · arch-enforcer item4 · `a0b4b12`.

### 6. Owner private DM gate

- Admin commands require owner **and** `chat.type == private` (`is_private_owner_message`).
- Source: item2 fix `bd96939` · arch item2/item4 owner gate PASS.

---

## Residuals

### In-scope follow-up (not pool-close blockers)

| Residual | Class | Why | Origin |
|----------|--------|-----|--------|
| Orphan profiles if VIP deactivated outside `/remove_vip` | in-scope-followup | Only admin remove path purges | item2 SUMMARY |
| StagingService not constructed at composition root with sandbox | in-scope-followup | Gate is defensive on service API; production correct path may not pass chat_id yet | item4 SUMMARY · arch medium |
| ProfilesRepo `load_only` exclude embedding | in-scope-followup | perf nit when QPS/writers scale | residuals-polish item4 (carried) |

### Out of scope (documented only)

| Residual | Class | Why | Origin |
|----------|--------|-----|--------|
| Multi-replica shared sandbox session | out-of-scope | CLARIFY / PRODUCT non-goal | CLARIFY · PRODUCT §7 |
| Live fixture catalog edit via Telegram | out-of-scope | Frozen catalog; change via deploy | CLARIFY · PRODUCT §7 |
| VIP hard-delete + DB ON DELETE CASCADE | out-of-scope | Soft deactivate product lock | item2 |
| Cascade memories/examples/policies/recontact on remove | out-of-scope | C1 profiles only | item2 |
| Embedding recompute on profile write | out-of-scope | Zero vector on insert only | item1 |
| Concurrent RMW row locks on profile content | out-of-scope | Single-instance ops | item1 · OPS |
| `pipeline_traces` metadata `sandbox: true` | out-of-scope | Traces still write; optional flag | item4 · PRODUCT §8.2 default “trace allowed” |
| Gray-zone full path under sandbox + real vip_id | out-of-scope | Demote covered for vip_id=None; ops caution | item4 · arch medium |
| RAM-only history for sandbox multi-turn | out-of-scope | SQL history append allowed | item4 |
| freeze/pause/auto_send admin commands | out-of-scope | Later admin surface | item2 |

---

## Metrics

| Metric | Value |
|--------|--------|
| Items completed | **4** |
| Critical arch violations | **0** ×4 |
| Test-guardian | suite protects adequately · 0 mocks prohibidos ×4 |
| Feature flag sandbox default | **false** |
| Item4 focused suite | **288** passed |
| Item2 full unit (guardian env) | **1303** passed |
| Product code dirty at documentador | **none** |

---

## Files / modules touched (pool aggregate)

| Area | Key paths |
|------|-----------|
| Profile pure | `src/diana/profile_content.py` (NEW) |
| Application | `profile_admin_service.py` (NEW), `sandbox.py` rewrite, `sandbox_knowledge.py` (NEW), ports/memory VipStore, staging gate, orch/admin isolation, TC reset |
| Infrastructure | `ProfilesRepo` writers + delete, SqlVipStore list/rename |
| Cognitive | ProfileRetriever hollow share; ContextBuilder profile fence; Director KnowledgeAugmenter Protocol hook |
| Telegram | admin `/vip_*`, `/list_vips`, `/rename_vip`, `/sandbox`, private gate, Auth bypass |
| Config / package | `src/diana/config/sandbox_profiles.json`, hatch force-include |
| Composition | sandbox + augmenter + recontact `is_sandbox_vip` |
| Tests | profile write/admin, vip store, sandbox service/knowledge, orch/admin/auth/staging, composition, purity |

---

## Acceptance vs product (PRODUCT §9)

| # | Acceptance | Result |
|---|------------|--------|
| 1 | Zero real VIPs → sandbox activate fixture path without production subscriber | **met** (auth bypass + inject) |
| 2 | Sandbox does not write learning/staging as real | **met** (`should_persist` / skip post-turn / staging gate) |
| 3 | Owner edits facts/notes only; identity outside editor | **met** |
| 4 | Fixture list = 6 v1 keys | **met** |
| 5 | Owner-only Telegram commands | **met** (+ private DM) |
| 6 | `FEATURE_SANDBOX_ENABLED=false` hides/no-ops sandbox | **met** |

---

## Pool close note

Pool `owner-admin-sandbox` closed — 4 items completed (profile-write, vip-crud, sandbox-core, sandbox-admin), tests green per item packages, commits done, documentation updated.

**Next:** Orchestrator Commit Gate de pool. Residual follow-ups optional; default next = ops gradual flag enablement (incl. sandbox when ready) or product-driven freeze/pause admin surface.
