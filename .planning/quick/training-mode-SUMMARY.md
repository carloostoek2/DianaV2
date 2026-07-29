# training-mode -- Implementation Summary

## What Was Built

A "Modo Entrenamiento" toggle in the admin menu that, when enabled, lets ALL incoming business messages (including non-VIP) flow through the full cognitive pipeline without registering the sender as a VIP.

## Architecture Decisions

- **TrainingModeStore protocol** in `ports.py` with `is_enabled() -> bool` and `set_enabled(enabled: bool) -> None` -- follows existing protocol pattern (VipStore, OwnerNotifierPort) for Clean Architecture
- **SqlSystemConfigStore** implements the protocol with `training_mode_enabled` key in `system_config` table
- **AuthMiddleware** receives `training_mode: TrainingModeStore | None` -- the gate activates after VIP check fails and before promo check, so a non-VIP message with training ON bypasses the promo/block gate
- **Menu UI** -- 6th root category "Configuracion" with toggle button rendering current state (ON/OFF)
- **build_dispatcher** / **composition.py** wiring follows existing injection pattern (same shape as `feature_promo_enabled` + `promo`)

## Key Design Properties

- Training mode is PERSISTENT (DB-backed via `system_config`), not in-memory
- Training mode and sandbox are INDEPENDENT and do not interfere
- Non-VIP users processed in training mode are NOT registered as VIPs, no `vip_id`/`vip_record` is set
- Generated responses DO feed staging, doctrina, and learning normally
- Owner business messages are still discarded (unchanged)
- Private DMs from non-owners are still discarded (training mode only applies to business messages)

## Review Stats

- Effort level: 4 (5 reviewers: 2 general + security + tests + plan)
- Rounds: 2 (8 fixes round 1, 1 typo round 2)
- Final: 0 open issues
- All findings resolved or accepted as wontfix

## Test Coverage

- 11 new test cases across 3 files (5 auth middleware, 4 menu, 2 system config)
- 1503 total tests passing (3 unrelated embedding failures pre-existing)
- All 57 training-mode-relevant tests pass

## Files Changed (10)

| File | Change |
|------|--------|
| `src/diana/application/ports.py` | Added `TrainingModeStore` protocol with `is_enabled()`, `set_enabled()` |
| `src/diana/composition.py` | Wiring: pass config_store as training_mode + config_store |
| `src/diana/infrastructure/db/repositories/system_config.py` | `get_training_mode_enabled()`, `set_training_mode_enabled()`, `set_enabled()` |
| `src/diana/telegram/handlers/menu.py` | Config category dispatch + toggle handler |
| `src/diana/telegram/keyboards.py` | 6th root category + `menu_config_keyboard()` |
| `src/diana/telegram/middlewares/auth.py` | Training mode gate in `AuthMiddleware.__call__()` |
| `src/diana/telegram/setup.py` | `training_mode` + `config_store` params to `build_dispatcher()` |
| `tests/unit/telegram/test_auth_mw.py` | 5 new training mode auth tests |
| `tests/unit/telegram/test_menu.py` | 4 new config menu tests |
| `tests/unit/infrastructure/test_system_config_set.py` | 2 new system config tests |

## Deviations from Plan

- Original PLAN specified `TrainingModeReader` (read-only protocol); during review, this was upgraded to `TrainingModeStore` with `set_enabled()` to fix a layer violation in menu.py (which was importing from infrastructure instead of ports).
- All other tasks implemented exactly per PLAN.

## Commits (4)

```
285e770 fix(architecture): replace TrainingModeReader with TrainingModeStore protocol
2d59af7 test(training-mode): add 11 test cases for training mode feature
f12f1ff fix(training-mode): address review findings -- bool coercion, actor_id logging, dead code, test gap
48828b2 fix(training-mode): add missing accent in Configuracion UI string
```

## Pool Close

**Pool:** training-mode
**Status:** COMPLETED -- no residuals, no open issues.
**Next step:** Feature is ready for production use.
