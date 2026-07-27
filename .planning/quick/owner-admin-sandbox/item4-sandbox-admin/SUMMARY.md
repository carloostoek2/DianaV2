# SUMMARY — item4-sandbox-admin

**Status:** DONE  
**Phase:** quick / owner-admin-sandbox  
**Item:** 4/4 — owner sandbox admin surface + turn-path isolation  

## Objective

Wire owner `/sandbox` commands and turn-path isolation on top of item3 `SandboxService`: Auth allowlist bypass, fixture profile inject, `fake_delivery`, skip learning/staging, SANDBOX markers, composition wiring.

## Tasks completed

| Task | Result | Commit |
|------|--------|--------|
| 1. Auth + knowledge inject + orch/admin isolation | DONE | `6c1a0ff` `feat(sandbox): auth bypass and pipeline isolation` |
| 2. Owner `/sandbox` commands + menu + reset | DONE | `462fea4` `feat(telegram): sandbox owner commands and session reset` |
| 3. Composition end-to-end wiring | DONE | `610d9a4` `feat(sandbox): wire composition for admin surface` |

## What shipped

### Task 1 — pipeline isolation
- `KnowledgeAugmenter` Protocol in `cognitive/ports.py`; Director optional hook after retrieval.
- `SandboxKnowledgeAugmenter` in `application/sandbox_knowledge.py` (no cognitive → sandbox import).
- AuthMiddleware sandbox bypass (non-VIP chat passes; VIP still sets `vip_id`).
- TurnOrchestrator: `_maybe_post_turn` skips learning; `_effective_delivery_mode` → `fake_delivery`; consult_doctrine demotes to approve when sandbox + no vip_id.
- AdminService: SANDBOX reason prefix; fake_delivery on approve/correct.
- StagingService: optional `chat_id` + sandbox gate on `save_correction`.

### Task 2 — owner commands
- Pure tokens: `sandbox_help|on|off|perfil|perfiles|estado|reset|usage|error|unavailable|not_active`.
- `TurnCoordinator.reset_chat_session` supersedes non-terminal turns; session stays ON.
- Menu lines under VIP profile block.
- English UX strings; help body per PLAN.

### Task 3 — composition
- Flag on → SandboxService + augmenter + sandbox into Admin, Orch, Auth, admin router.
- Flag off → all `None` (pre-item4 behavior).

## Deviations

- None material. StagingService not constructed at composition root (pre-existing); defensive gate lives on the service API for callers.
- Test catalogs duplicated inline (no `tests` package import path) instead of cross-importing `MINIMAL_SIX`.

## Verifications run

```bash
.venv/bin/pytest \
  tests/unit/application/test_sandbox_service.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/telegram/test_admin_commands.py \
  tests/unit/telegram/test_auth_mw.py \
  tests/unit/test_composition_wiring.py \
  tests/unit/application/test_application_import_purity.py \
  tests/unit/behavior/test_engine.py \
  tests/unit/application/test_sandbox_knowledge.py \
  tests/unit/cognitive/test_director_knowledge_augmenter.py \
  tests/unit/application/test_staging_service.py \
  tests/unit/cognitive/test_import_purity.py \
  -q
```

**Result:** all green (226+ tests in item suite).

## Success criteria

- [x] Owner `/sandbox` help/on/off/perfil/perfiles/estado/reset (private owner only)
- [x] `FEATURE_SANDBOX_ENABLED=false` → unavailable; no bypass
- [x] Sandbox-active chat without VIP row enters pipeline (Auth bypass)
- [x] Fixture profile as `knowledge.profile` when active
- [x] `fake_delivery` for sandbox (orch + admin approve)
- [x] `run_post_turn` not called when sandbox active
- [x] Staging `save_correction` no-ops when gated
- [x] Owner draft/escalation reason includes `SANDBOX — profile: {key}`
- [x] Reset supersedes live turns; sandbox remains active
- [x] No SandboxService API rewrite; no real VIP CRUD changes
- [x] Import purity green (application no aiogram; cognitive no application/sandbox)

## Residuals

- **RAM-only history for sandbox multi-turn without SQL rows**  
  clase_sugerida: out-of-scope  
  por_qué: PLAN non-goal; SQL history append allowed for continuity  
  archivos: history writers / orch

- **`pipeline_traces` metadata `sandbox: true`**  
  clase_sugerida: out-of-scope  
  por_qué: optional residual in PLAN; traces still write for reconstructability  
  archivos: TraceStore / pipeline_traces

- **Recontact `is_sandbox_vip` hook wiring**  
  clase_sugerida: ~~fixed in fix-round~~  
  por_qué: fixed — vip.telegram_user_id → sandbox.is_active  
  archivos: `src/diana/composition.py`

- **StagingService not constructed in composition root**  
  clase_sugerida: in-scope-followup  
  por_qué: gate is defensive on service API; no production caller path wires sandbox into StagingService yet  
  archivos: `src/diana/composition.py`, `staging_service.py`

- **Gray-zone doctrine full path under sandbox with real vip_id**  
  clase_sugerida: out-of-scope  
  por_qué: PLAN residual; demote path covered for vip_id=None only  
  archivos: orch gray zone branch

## Self-Check: PASSED

- [x] Todas las tareas completadas
- [x] Tests del PLAN corridos
- [x] 0 regresiones atribuibles
- [x] Convenciones del proyecto respetadas (AGENTS cognitive purity, application owns sandbox, English UX)

## Log

`.planning/quick/gsd-owner-admin-sandbox-item4-sandbox-admin.log`
