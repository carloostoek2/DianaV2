# SUMMARY — item3-sandbox-core

**Phase:** quick / owner-admin-sandbox  
**Plan:** item3-sandbox-core  
**Status:** complete  
**Date:** 2026-07-27

## Tasks completed

| Task | Result | Commit |
|------|--------|--------|
| 1. Failing unit tests (v1-like contract) | Red (ImportError missing API) → green after Task 2 | (same work unit) |
| 2. Catalog JSON + SandboxService rewrite + hatch include | Green 16 sandbox tests | see below |
| 3. Composition wiring + purity/regression | Green; comment updated only | see below |

**Commit:** `feat(sandbox): v1 session core + package fixture catalog`

## What shipped

- `src/diana/config/sandbox_profiles.json` — 6 keys: `nuevo`, `cercano`, `distante`, `intenso`, `vip_largo`, `inyeccion_previa`
- `src/diana/application/sandbox.py` — rewritten pure session service:
  - `activate` / `deactivate` / `set_profile` / `set_focus_profile`
  - `is_active` / `should_persist` / `get_profile` / `get_focus_chat_id`
  - `list_profiles` / `format_estado`
  - `get_profile_content` / `get_context_block`
  - `load_sandbox_catalog` / `parse_sandbox_catalog` / `PROFILE_NAMES`
- `pyproject.toml` — hatch force-include for sandbox JSON
- `composition.py` — still `SandboxService() if feature_sandbox_enabled else None` (comment: v1 catalog, not insert_sandbox)
- Tests rewritten; F2 create_profile/isolate_trace cases removed

## Deviations

None. Scope held: no Telegram commands, no pipeline injection, no SQL fixture rows.

## Verifications

```text
.venv/bin/pytest tests/unit/application/test_sandbox_service.py -q
→ 16 passed

.venv/bin/pytest \
  tests/unit/application/test_sandbox_service.py \
  tests/unit/test_composition_wiring.py \
  tests/unit/application/test_application_import_purity.py -q
→ 45 passed

.venv/bin/pytest tests/unit/application/ -q --tb=no
→ 423 passed
```

## Success criteria

- [x] Package file with 6 keys + facts/notes shape
- [x] Hatch force-include ships JSON
- [x] SandboxService session + content API
- [x] In-process maps only; no SQL profile writes from sandbox
- [x] Composition builds service iff `feature_sandbox_enabled`
- [x] Unit tests green
- [x] No telegram handler changes
- [x] No multi-replica store

## Residuals → item4

- Owner commands `/sandbox on|off|perfil|perfiles|estado|reset`
- Call `should_persist` from learning/orchestrator paths
- Inject `get_profile_content` into cognitive profile path for sandbox chats
- Prefer fake_delivery for sandbox turns
- Optional `reset` clearing coordinator/pending for focused chat
- Menu section under owner admin

## Self-Check: PASSED

- [x] Todas las tareas completadas
- [x] Tests del PLAN corridos
- [x] 0 regresiones atribuibles
- [x] Convenciones del proyecto respetadas (application purity, English service errors, Spanish fixture labels)
