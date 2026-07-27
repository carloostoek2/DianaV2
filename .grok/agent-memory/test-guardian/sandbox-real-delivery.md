# Test-Guardian Report: sandbox-real-delivery

**Verdict:** suite protege adecuadamente  
**Date:** 2026-07-27  
**Commits audited:** `273912e`, `cc486d2`, `00d51dd`  
**Sources:** PLAN/SUMMARY, arch-enforcer PASS WITH NOTES, impact-analyzer, locked CLARIFY D1–D7  
**Tests added this guardian pass:** 0 (executor already inverted + optional ops-mode gold; no gaps)

---

## Coverage Audit

| Must-verify (orchestrator) | Protected by | Status |
|----------------------------|--------------|--------|
| 1. Sandbox + configured delivery_mode → mode ≠ forced fake (orch autonomous + admin approve) | `test_sandbox_autonomous_uses_configured_delivery_mode` (`mode == "supervised"`, `!= "fake_delivery"`); `test_sandbox_approve_uses_configured_delivery_mode` (admin default supervised) | COVERED |
| 2. Sandbox + delivery_mode=fake_delivery still works (ops mode D6) | `test_sandbox_respects_global_fake_delivery_mode` | COVERED |
| 3. Learning skip / staging skip / doctrine demote / recontact skip | `test_sandbox_skips_learning_post_turn`, `test_sandbox_inactive_still_runs_learning`, `test_save_correction_skips_when_sandbox_active`, `test_sandbox_consult_doctrine_demotes_when_no_vip`, recontact `test_is_blocked_sandbox_*` + `test_get_due_vips_skips_sandbox_active_vip` | COVERED (golds not weakened) |
| 4. BehaviorEngine fake_delivery path still green | `test_fake_delivery_*` in `test_engine.py`; AMS `test_fake_delivery_mode_does_not_enable_l2` | COVERED |
| 5. Mock audit — no prohibited mocks on path under test | See Mock Audit | PASS (0 prohibited) |

**Production contract checked in tree:**

```python
# turn_orchestrator.py + admin_service.py
def _effective_delivery_mode(self, _chat_id: int) -> DeliveryMode:
    return self._delivery_mode  # no sandbox → fake_delivery branch
```

**Coverage confidence:** high for application delivery-mode contract under sandbox. Tests exercise real `TurnOrchestrator` / `AdminService` + real `SandboxService.activate` and capture the `DeliveryContext` that reaches Behavior (via CaptureBehavior at the actuator edge).

**Optional residual (non-blocking, not a gap vs PLAN):** no separate admin-path test with explicit `delivery_mode="fake_delivery"` under sandbox — orch already locks D6; admin uses identity helper same as orch. PLAN optional covered at orch level.

---

## Mock Audit

### Inventory (item tests new/modified)

| Archivo | Mock / double | Clasificación | Path de negocio | Acción |
|---------|---------------|---------------|-----------------|--------|
| `test_turn_orchestrator.py` L1783–1791, L1860–1868 | `CaptureBehavior` (records `ctx`, returns success) | **PERMITIDO** | External Behavior/Telegram edge — captures mode without network | ninguna |
| `test_admin_service.py` L759–765 | `CaptureBehavior` same pattern | **PERMITIDO** | Admin approve → deliver edge | ninguna |
| `test_turn_orchestrator.py` (helpers) | `FakeDirector(fixed Decision)` | **PERMITIDO** | Fixes Decision so orch delivery path runs; does **not** stub `_effective_delivery_mode` | ninguna |
| Item delivery tests | **Real** `SandboxService` + `activate` | N/A (real collaborator) | Session active gate | ninguna |
| Item test files overall | **0** `@patch` / `MagicMock` / `AsyncMock` / `monkeypatch` on production helpers | — | — | — |

**No mocks of:** `_effective_delivery_mode`, `SandboxService.is_active` (for delivery asserts), DB session for mode logic, Admin/Orch methods under test.

**Resumen mocks:** 3 permitidos (CaptureBehavior ×3 sites; FakeDirector fixed Decision), **0 prohibidos** en scope del ítem.  
**Confianza de realidad:** **alta** — asserts depend on production helper return value flowing into `DeliveryContext.mode`, not on mock-injected mode.

Legacy isolation tests (learning/staging/recontact) use the same Capture/Fake pattern or real SandboxService — debt none for this item.

---

## Re-run Results

```bash
# Primary inverted + ops-mode
python -m pytest \
  tests/unit/application/test_turn_orchestrator.py::test_sandbox_autonomous_uses_configured_delivery_mode \
  tests/unit/application/test_turn_orchestrator.py::test_sandbox_respects_global_fake_delivery_mode \
  tests/unit/application/test_admin_service.py::test_sandbox_approve_uses_configured_delivery_mode \
  -v
# → 3 passed

# Isolation pack (PLAN)
python -m pytest \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/application/test_admin_service.py \
  tests/unit/application/test_staging_service.py \
  tests/unit/application/test_sandbox_service.py \
  tests/unit/application/test_sandbox_knowledge.py \
  tests/unit/application/test_recontact_service.py \
  tests/unit/behavior/test_engine.py \
  tests/unit/application/test_autonomous_mode_service.py \
  -k "sandbox or fake_delivery" -v
# → 36 passed, 160 deselected
```

Executor SUMMARY also reported full `tests/unit` **1372 passed** after Task 3 (not re-run here; isolation pack is the item gate).

---

## Pre-existing vs Attributable

- **Attributable failures:** none. All item-scoped re-runs green.
- **Pre-existing:** none observed in isolation pack.
- **Superseded contract:** item4 tests that asserted forced `fake_delivery` under sandbox were correctly inverted in `273912e` (not deleted isolation golds).

---

## Handoff

**next_recommended:** run-tests  
**reason:** suite protege adecuadamente; Mock Audit 0 prohibidos; isolation 36 green; ready for orchestrator final suite / close gate  
**skill_resolution:** none  
**listo para cierre:** yes (no return to executor for test/mock fixes)
