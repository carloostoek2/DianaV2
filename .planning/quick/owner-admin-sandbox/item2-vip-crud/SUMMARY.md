# SUMMARY — item2-vip-crud

**Phase:** quick / owner-admin-sandbox  
**Plan:** item2-vip-crud  
**Status:** COMPLETE  
**Date:** 2026-07-27

## Objective (done)

Real-VIP allowlist CRUD gaps closed for the owner: list active VIPs, rename `display_name`, purge `profiles` row on `/remove_vip`, admin menu updated.

## Tasks completed

| Task | Commit | Message |
|------|--------|---------|
| 1. VipStore `list_active` + `rename` | `5346565` | `feat(vip): list_active and rename on VipStore` |
| 2. ProfilesRepo delete + purge service | `cc120d2` | `feat(profile): delete_by_vip_id and purge on remove` |
| 3. Telegram list/rename/remove cascade + menu | `9cd1107` | `feat(telegram): list_vips rename_vip and remove cascade` |

## Behavior delivered

- **`VipStore.list_active()`** — active only, `telegram_user_id` ASC (Protocol + InMemory + Sql).
- **`VipStore.rename(tg_id, name)`** — active only; never reactivates; missing/inactive → `None`.
- **`ProfilesRepo.delete_by_vip_id(vip_id) -> bool`** — VIP-scoped row delete (BR-15).
- **`ProfileAdminService.purge_profile_for_telegram_user`** — owner-gated; resolves **inactive** VIP; statuses `profile_purged` | `profile_absent` | `vip_not_found`.
- **Telegram**
  - `/list_vips` → `vips_list` / `vips_empty` → UX list body / `No active VIPs.`
  - `/rename_vip <tg_id> <name…>` → `vip_renamed` / `vip_not_found` / `rename_vip_usage` (empty/missing/oversize >64).
  - `/remove_vip` → deactivate then best-effort purge when `profile_admin` wired; UX remains `VIP deactivated`.
  - `on_remove_vip` / `on_add_vip` use `_dispatch_token` so `profile_admin` is not dropped.
- **`ADMIN_MENU_TEXT`** includes `/list_vips` and `/rename_vip …`.

## Deviations

None material. Strict TDD red→green per task.

Minor: `AsyncSession.delete` is awaitable (SA 2.0.49); tests use `AsyncMock` for session.delete.

## Verifications

```bash
python3 -m pytest tests/unit/application/test_vip_store.py -q  # 18 passed
python3 -m pytest tests/unit/infrastructure/test_profiles_repo_write.py \
  tests/unit/application/test_profile_admin_service.py -q  # 33 passed
python3 -m pytest tests/unit/telegram/test_admin_commands.py \
  tests/unit/application/test_vip_store.py \
  tests/unit/application/test_profile_admin_service.py \
  tests/unit/infrastructure/test_profiles_repo_write.py -q  # 94 passed
python3 -m pytest tests/unit -q  # 1300 passed, 3 failed (env)
```

**Env-only failures (not attributable):**  
`tests/unit/cognitive/test_embedding.py` ×3 — `ModuleNotFoundError: sentence_transformers`. Cognitive no-touch; pre-existing env gap.

## Files touched

- `src/diana/application/ports.py`
- `src/diana/application/memory.py`
- `src/diana/infrastructure/db/repositories/vips.py`
- `src/diana/infrastructure/db/repositories/profiles.py`
- `src/diana/application/profile_admin_service.py`
- `src/diana/telegram/handlers/admin.py`
- `src/diana/telegram/handlers/callbacks.py`
- `tests/unit/application/test_vip_store.py`
- `tests/unit/infrastructure/test_profiles_repo_write.py`
- `tests/unit/application/test_profile_admin_service.py`
- `tests/unit/telegram/test_admin_commands.py`

## No-touch respected

- cognitive / behavior / learning / sandbox
- no Alembic migration / no VIP hard-delete
- no memories/examples/policies cascade
- no profile content schema changes

## Residuals

- **title:** Hard-delete VIP row + DB `ON DELETE CASCADE` on profiles  
  **clase_sugerida:** out-of-scope  
  **por_qué:** Product lock keeps soft deactivate; FK has no CASCADE; migration deferred  
  **archivos:** `models.Profile`, alembic

- **title:** Cascade memories / examples / policies / recontact on VIP remove  
  **clase_sugerida:** out-of-scope  
  **por_qué:** Explicit non-goal of this item (C1 purge profiles only)  
  **archivos:** knowledge repos, recontact

- **title:** Orphan profiles if VIP deactivated outside `/remove_vip`  
  **clase_sugerida:** in-scope-followup  
  **por_qué:** Only admin remove path purges; freeze/other paths do not call purge  
  **archivos:** `admin.py`, optional maintenance job

- **title:** freeze / pause / auto_send admin commands  
  **clase_sugerida:** out-of-scope  
  **por_qué:** Product residual / later admin surface  
  **archivos:** telegram admin handlers

- **title:** `sentence_transformers` missing in unit env (embedding tests)  
  **clase_sugerida:** out-of-scope  
  **por_qué:** Env dependency; not introduced by item2  
  **archivos:** `tests/unit/cognitive/test_embedding.py`

## Self-Check: PASSED

- [x] Todas las tareas completadas
- [x] Tests del PLAN corridos (focused 94 green)
- [x] 0 regresiones atribuibles (3 embedding = env only)
- [x] Convenciones del proyecto respetadas (AGENTS.md layers, Strict TDD, English UX)
