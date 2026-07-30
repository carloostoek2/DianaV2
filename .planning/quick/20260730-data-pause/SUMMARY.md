# Pool — Data Pause Admin UI

**Item:** 3 of pool "close-4-parciales" (gap #6 from `faltantes.md`)
**Date:** 2026-07-30
**Status:** CLOSED

## Commits (6)

| # | Hash | Message |
|---|------|---------|
| 1 | `e113adb` | feat(data-pause): add pause_vip/unpause_vip to VipStore protocol and both implementations |
| 2 | `362d634` | feat(data-pause): rewire freeze keyboard and handlers to use pause/unpause |
| 3 | `95bb506` | feat(data-pause): add store tests and update menu tests for pause/unpause |
| 4 | `97bba52` | fix(data-pause): add missing accents in Spanish duration labels |
| 5 | `442ce4c` | fix(tests): correct Spanish accent in pause duration keyboard test assertions |
| 6 | `d29a38e` | docs: mark data pause admin UI as resolved (gap #6) |

## Files Changed (5 implementation files, no new files)

**Edited (7):**
- `src/diana/application/ports.py` -- `pause_vip`/`unpause_vip` added to `VipStore` protocol
- `src/diana/infrastructure/db/repositories/vips.py` -- `pause_vip`/`unpause_vip` in `SqlVipStore`
- `src/diana/application/memory.py` -- `pause_vip`/`unpause_vip` in `InMemoryVipStore`
- `src/diana/telegram/keyboards.py` -- `menu_vip_detail_keyboard` param renamed, `menu_freeze_duration_keyboard` -> `menu_pause_duration_keyboard`, 3d/1m duration buttons added (6 rows)
- `src/diana/telegram/handlers/menu.py` -- freeze/unfreeze handlers rewired to pause/unpause, `_is_vip_frozen` -> `_is_vip_paused`, callback actions `freeze:*` -> `pause:*`
- `tests/unit/application/test_vip_store.py` -- 4 new tests for pause_vip/unpause_vip
- `tests/unit/telegram/test_menu.py` -- full freeze->pause migration, 3d/1m handler tests, callback size tests

## Outcomes

- `pause_vip`/`unpause_vip` methods in `VipStore` protocol, `SqlVipStore`, and `InMemoryVipStore` -- write to `paused_until` column
- `freeze_vip`/`unfreeze_vip` preserved untouched in all three implementations (GrayZone freeze path intact)
- `set_paused_until` test helper retained in `InMemoryVipStore`
- Duration keyboard: 5 duration options (1d, 3d, 7d, 1m, indef) + back button = 6 rows
- Callback actions renamed: `freeze:*` -> `pause:*`, `unfreeze` -> `unpause`
- VIP detail card toggle shows "Pausar"/"Reanudar" based on `paused_until`
- `_is_vip_frozen` helper completely removed (dead code elimination)
- 4 new store tests (set, clear, unknown raises for both pause and unpause)
- 2 new duration handler tests (3d, 1m) with delta assertions
- 2 new callback size tests (pause:3d, pause:1m) -- all under 64 bytes
- 7 parametrized parse callback variants (was 5)

## Verifications

| Check | Result |
|-------|--------|
| Plan success criteria | 16/16 PASS |
| Store + menu + middleware + SQL shape tests | 76/76 PASS |
| Full unit suite | 1542 PASS (4 pre-existing: embedding + schema count) |
| Freeze middleware tests | all pass (GrayZone freeze path intact) |
| Existing freeze/unfreeze store tests | all pass (regression guard) |
| models.py no-touch | VERIFIED -- no changes |
| FreezeCheckMiddleware no-touch | VERIFIED -- no changes |
| GrayZoneService no-touch | VERIFIED -- no changes |
| DeliveryContext no-touch | VERIFIED -- no changes |
| New callback data under 64 bytes | VERIFIED -- all 7 variants tested |
| arch-enforcer | PASS WITH NOTES (0 critical) |
| test-guardian | PASS |
| Review loop | 1 ronda, unico issue = accents (97bba52 + 442ce4c), 0 open |
| Commit gate | CLEAN |

## Residuals (deferred, documented only)

None blocking. The following were noted as deliberate out-of-scope or future improvements:

- **GrayZone freeze path untouched** -- `freeze_vip`/`unfreeze_vip` remain active for GrayZoneService, not replaced by pause
- **In-memory state cleanup on pause** -- v1 cleared runtime state (timers, pending approval) on pause; v2 does not (scope-split for a follow-up)
- **FreezeCheckMiddleware** still reads `frozen_until` -- freeze and pause remain two independent mechanisms
- **No Alembic migration** -- `paused_until` column already existed

## Status in faltantes.md

Gap #6 (Data Pause por VIP): **PARCIAL -> RESUELTO** -- admin UI completa con teclado de duraciones, pause/unpause en DB, toggles en perfil VIP. Verificado con 76/76 tests plan-specific, suite completa 1542 passed.

## Close note

> Pool `close-4-parciales` item 3 (Data Pause admin UI) closed -- store methods, UI rewire, and full test migration completed. 5 feat/fix commits + 1 docs commit. 76 plan tests passing, 1542 full suite, 0 critical violations, 0 review issues. faltantes.md gap #6 updated to RESUELTO. GrayZone freeze path untouched. No new files created; 5 source files edited in-place.
