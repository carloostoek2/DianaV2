# Arch Audit: sandbox-real-delivery

**Verdict:** PASS WITH NOTES  
**Critical violations:** 0  
**Commits:**
- `273912e` — `test(sandbox): invert delivery mode asserts under sandbox`
- `cc486d2` — `fix(sandbox): use configured delivery_mode under sandbox`
- `00d51dd` — `docs(sandbox): real delivery under sandbox; isolation via should_persist`  
**Date:** 2026-07-27  
**Sources:** `AGENTS.md`, locked `.planning/quick/sandbox-real-delivery/CLARIFY.md`, PLAN/SUMMARY, impact `sandbox-real-delivery.md`  
**Supersedes (delivery isolation only):** item4 claim that sandbox forces `fake_delivery` (arch-enforcer `owner-admin-sandbox-item4-sandbox-admin.md`)

---

## Findings

### Critical (must fix before advance)

_None._

### Medium

_None blocking._ Operator chat-targeting risk is **product residual**, documented in Task 3 (not a layer violation):

1. **Real Telegram to sandboxed chat_id**  
   After this change, approve/send under sandbox uses configured `delivery_mode`. If the owner runs `/sandbox on <real_vip_private_chat>`, real messages leave when mode ≠ `fake_delivery`.  
   **Mitigation in-scope:** PRODUCT_OWNER residual claim documents dedicated test chat. Soft warn on allowlisted VIP activate remains OOS (CLARIFY deferred).  
   **Classification:** residual / ops caution — expected product tradeoff per locked CLARIFY D1–D2.

### Observations

1. **`_effective_delivery_mode` is identity** — both orch and admin keep the helper (`return self._delivery_mode`) with `_chat_id` unused (call-site stability). PLAN preferred keep-helpers over inline; fine.

2. **Log rename `sandbox_fake_delivery` → `delivery_mode_fake`** — fires only when configured mode is already fake (global ops). Correct; no sandbox-gated misleading event name.

3. **Isolation pack untouched in logic** — learning skip, doctrine demote, staging skip, recontact skip, Behavior fake path: still present and not rewritten.

4. **Test contract match PLAN A4** — orch test builds `delivery_mode="supervised"` + `global_mode="autonomous"` and asserts `ctx.mode == "supervised"` (delivery field), not AMS mode. Admin default supervised inverted correctly. Optional D6 gold: `test_sandbox_respects_global_fake_delivery_mode` present.

5. **Historical docs/MEMORY** — item4 arch audit still records fake_delivery isolation historically; this report is the superseding truth for delivery mode under sandbox.

---

## Mandatory checks (orchestrator + AGENTS focus)

| Check | Result | Evidence |
|-------|--------|----------|
| **Behavior outside cognition** | **PASS** | No `behavior/` or `cognitive/` edits. Application only sets `DeliveryContext.mode` from `_delivery_mode`; BehaviorEngine still acts-only on `ctx.mode == "fake_delivery"`. |
| **Learning post-turn only** | **PASS** | `_maybe_post_turn` unchanged: sandbox + `!should_persist` → `post_turn_skipped_sandbox`, no `run_post_turn`. Learning never in Director path. |
| **Director deterministic** | **PASS** | No Director/Decider/cognitive changes. |
| **Anti-contamination Memoria ↔ ejemplos** | **PASS** | `SandboxService.should_persist` still `not is_active`; staging `correction_skipped_sandbox` retained; no learning promotion under sandbox. |
| **CLARIFY D1–D2 real delivery** | **PASS** | Both `_effective_delivery_mode` return only `self._delivery_mode`; no sandbox → `"fake_delivery"` branch remains in tree. |
| **CLARIFY D4 product non-persist** | **PASS** | `should_persist` / post-turn skip / staging gate unchanged. |
| **CLARIFY D5 doctrine demote** | **PASS** | Orch `consult_doctrine` + `vip_id is None` + sandbox active → demote approve + `sandbox_no_vip_doctrine` + log. |
| **CLARIFY D5 recontact skip** | **PASS** | `recontact_service` + composition `_is_sandbox_vip` no-touch. |
| **CLARIFY D6 global fake ops** | **PASS** | Behavior fake path intact; test asserts sandbox + `delivery_mode="fake_delivery"` still yields fake. |
| **No Behavior/cognitive/learning edits** | **PASS** | Diff surface = orch + admin helpers + tests + docs only. |
| **Scope vs PLAN** | **PASS** | Files match PLAN file map. No-touch list respected (`sandbox.py`, `sandbox_knowledge.py`, `staging_service.py`, `recontact_service.py`, `behavior/*`, `learning/*`, `cognitive/*`, settings, composition recontact hooks). |
| **Feature flag** | **PASS** | `FEATURE_SANDBOX_ENABLED` / session wiring unchanged. |
| **Logging critical ops** | **PASS** | `delivery_mode_fake` (when mode fake), `post_turn_skipped_sandbox`, `sandbox_consult_doctrine_demoted`, `correction_skipped_sandbox` retained. |
| **Tests reflect contracts** | **PASS** | Inverted delivery asserts + optional fake ops + isolation golds kept (not weakened). |
| **Docs match CLARIFY** | **PASS** | README sandbox row + PRODUCT_OWNER isolation/delivery + operator risk; no “sandbox forces fake_delivery”. |

---

## Architecture detail

### Effective delivery rule (locked)

```
mode_effective = self._delivery_mode   # supervised | autonomous | fake_delivery
# sandbox active MUST NOT override to fake_delivery
```

### Layers / dependency direction

```
Application (TurnOrchestrator / AdminService)
  → DeliveryContext.mode = configured delivery_mode (no sandbox force)
  → BehaviorEngine.deliver (acts only; fake path if mode == fake_delivery)
Application post-turn
  → Learning only via _maybe_post_turn, skipped when !should_persist
```

Forbidden directions respected:
- Cognitive does not import telegram/behavior
- Behavior does not decide action or generate text
- Learning not invoked inside decision pipeline
- No new cross-module coupling; helpers simplified

### Scope creep

None. Production delta is two identity helpers + log event rename; tests inverted; docs synced.

---

## Compliance Checklist

- [x] Capas respetadas (application only)
- [x] Scope del PLAN respetado (no-touch list intact)
- [x] Logging adecuado (`delivery_mode_fake`; isolation logs retained)
- [x] Behavior fuera de cognición
- [x] Learning solo post-turno + sandbox skip via should_persist
- [x] Director determinista (no cognitive touch)
- [x] Anti-contaminación product knowledge (should_persist / staging / recontact)
- [x] CLARIFY D1–D7 honored (delivery override only removed)
- [x] Tests reflejan contrato (configured mode + global fake ops + isolation golds)
- [x] Docs alineados (real Telegram + product non-persist + operator risk)

## Residuals (non-blocking)

- Soft warn when activating sandbox on allowlisted VIP chat (OOS / deferred)
- Multi-replica session store (OOS)
- Gray-zone full path without vip_id (OOS; demote retained)
- Historical item4 docs/audit text that claimed fake_delivery isolation (superseded here for delivery)

## Handoff

**next_recommended:** test-guardian  
**reason:** 0 critical; delivery-mode contract + isolation golds ready for test protection review  
**skill_resolution:** none
