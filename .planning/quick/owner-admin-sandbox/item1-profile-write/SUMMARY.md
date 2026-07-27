# SUMMARY — owner-admin-sandbox / item1-profile-write

**Date:** 2026-07-27  
**Status:** COMPLETE (+ fix round)  
**Self-Check:** PASSED

## Objective

Owner-only write path for real VIP enrichable profiles (`facts` + `notes` under `profiles.content`), with VIP-scoped repo writers, thin `ProfileAdminService`, and English Telegram `/vip_*` admin commands.

## Tasks completed

| Task | Result | Commit |
|------|--------|--------|
| 1. Pure content schema + hollow read (Option A) | DONE | `5546b61` feat(profile): content schema helpers and hollow read |
| 2. ProfilesRepo writers (VIP-scoped) | DONE | `34fa463` feat(profile): ProfilesRepo fact/note writers |
| 3. ProfileAdminService owner gate | DONE | `9b6acf0` feat(profile): ProfileAdminService owner gate |
| 4. Telegram `/vip_*` + composition wiring | DONE | `efa9d09` feat(telegram): vip profile admin commands |
| Guardian tests | DONE | `13d4401` test(profile): harden profile-write coverage after guardian |
| Fix round (hollow/caps/integrity) | DONE | `fa14727` + `9d9fb35` |

## What shipped

- **Schema lock:** `{ "facts": {str: str}, "notes": [{ "date": "YYYY-MM-DD", "text": str }] }` with pure helpers in `diana.profile_content` (infra re-exports).
- **Option A hollow:** shared `is_hollow_content` — empty/whitespace facts+notes shell → `None` / `profile_empty`; legacy flat `{"fact": ...}` still hits.
- **Writers:** `set_fact` / `delete_fact` / `add_note` / `delete_note` — BR-15 `vip_id` scoped; insert uses `tipo="summary"` + zero embedding 384; `flag_modified` for JSONB.
- **Service:** `ProfileAdminService` (not on `AdminService`); owner fail-closed; inactive/missing VIP → `vip_not_found`; note index 1-based public API.
- **Telegram:** `/vip_profile`, `/vip_fact`, `/vip_fact_del`, `/vip_note`, `/vip_note_del` English UX; menu updated; composition + `build_dispatcher` wired.

## Fix round (hardener 7869e868)

| Must-fix | Result |
|----------|--------|
| Hollow parity (H1/H2/F4) | Shared `diana.profile_content`; cognitive imports pure module only |
| IntegrityError → domain status (F3) | Service maps to `vip_not_found` |
| Length caps (SEC) | key 64 / value 500 / note 1000 → `invalid` |
| Multi-word keys (F5) | Documented + tested (first token = key) |
| Cheap tests | `format_profile_body`, invalid/oversize, integrity, whitespace hollow |

**Wontfix (documented in review):** concurrent RMW (F1/F2), full prompt fencing, staging promote context, wiring-test depth nit, double show_profile.

## Deviations

None material. Task order and TDD followed. Writers not committed in Task 1 (pure helpers only). Fix round moved pure helpers to package-root `profile_content` so cognitive can share hollow without importing infrastructure.

## Verifications

```text
# Post fix-round focused suite
131 passed

# Full unit suite
1279 passed
```

Import purity (application no aiogram; cognitive no infrastructure) holds.

## Self-Check: PASSED

- [x] All plan tasks completed
- [x] PLAN tests run and green
- [x] 0 regressions attributable (full `tests/unit` green)
- [x] Project conventions / AGENTS purity respected
  - No sandbox / decider / behavior / learning / migration / ORM schema edits
  - Cognitive remains read-only (hollow check pure only)
  - Application has no aiogram import
  - BR-15 vip_id scoping on all profile SQL paths

## Residuals

- **title:** VIP list / rename / cascade profile on remove  
  **clase_sugerida:** out-of-scope (item2-vip-crud)  
  **por_qué:** Explicit non-goal of item 1; product next slice.  
  **archivos:** admin VIP CRUD handlers, VipStore

- **title:** Sandbox catalog + session + admin commands  
  **clase_sugerida:** out-of-scope (item3/item4)  
  **por_qué:** Explicit NO-TOUCH; FEATURE_SANDBOX_ENABLED surface.  
  **archivos:** sandbox.py, fixture catalog

- **title:** Embedding recompute on profile write  
  **clase_sugerida:** out-of-scope  
  **por_qué:** Plan uses zero vector on insert only; re-embed deferred.  
  **archivos:** ProfilesRepo, EmbeddingService

- **title:** Concurrent RMW races on profile content  
  **clase_sugerida:** out-of-scope  
  **por_qué:** Accepted single-instance ops; no row lock this item.  
  **archivos:** profiles.py writers

- **title:** Full prompt fencing of owner facts/notes  
  **clase_sugerida:** out-of-scope  
  **por_qué:** Product knowledge intentional; length caps only this round.  
  **archivos:** ContextBuilder / Generator

- **title:** Staging promote context sanitization  
  **clase_sugerida:** out-of-scope  
  **por_qué:** BR-13 bridge residual, not item1 write path.  
  **archivos:** staging_service.py

## Files touched

| Action | Path |
|--------|------|
| Create | `src/diana/profile_content.py` |
| Create | `src/diana/application/profile_admin_service.py` |
| Create | `tests/unit/application/test_profile_admin_service.py` |
| Create | `tests/unit/infrastructure/test_profile_content_schema.py` |
| Create | `tests/unit/infrastructure/test_profiles_repo_write.py` |
| Edit | `src/diana/infrastructure/db/repositories/profiles.py` |
| Edit | `src/diana/cognitive/retrievers/profile.py` |
| Edit | `src/diana/telegram/handlers/admin.py` |
| Edit | `src/diana/telegram/handlers/callbacks.py` |
| Edit | `src/diana/telegram/setup.py` |
| Edit | `src/diana/composition.py` |
| Edit | `tests/unit/telegram/test_admin_commands.py` |
| Edit | `tests/unit/cognitive/test_retrievers.py` |
| Edit | `tests/unit/infrastructure/test_sql_repo_shapes.py` |
| Edit | `tests/unit/test_composition_wiring.py` |

## SEC-INJ-01 (post fix-round)

- **Status:** fixed (`1064dcb`)
- ContextBuilder fences `knowledge.profile` with disclaimer + OWNER_PROFILE_DATA delimiters.
- Test: `test_profile_knowledge_section_fenced_as_non_instruction_data` (16 context_builder tests passed).
