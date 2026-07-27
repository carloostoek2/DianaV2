# SUMMARY — sandbox-real-delivery

**Item:** sandbox-real-delivery — real Telegram delivery under sandbox  
**Date:** 2026-07-27  
**Status:** COMPLETE  
**Self-Check:** PASSED  
**Pool close:** COMPLETE (documentador)  
**Executor:** gsd-executor  
**Source:** `.planning/quick/sandbox-real-delivery/PLAN.md` + locked `CLARIFY.md`

## Review stats (hardener-agile)

| Metric | Value | Source |
|--------|-------|--------|
| Effort | **3** (1 general + tests + plan) | orchestrator + `.grok/agent-memory/review/sandbox-real-delivery.md` |
| Review rounds | **2** | same |
| Round 1 open | **6** (nits/suggestions) → all fixed in `ac38fd1` | gsd log + review |
| Round 2 open | **0** all reviewers | review HARD_ID `351a11fc` |
| Final open issues | **0** | same |
| Arch critical | **0** (PASS WITH NOTES) | `arch-enforcer/sandbox-real-delivery.md` |
| Test-guardian | suite protege adecuadamente · 0 mocks prohibidos · primary 3 + isolation 36 (pre-fix); strengthened matrix in `ac38fd1` | `test-guardian/sandbox-real-delivery.md` |

## Objective met

Sandbox sessions no longer force `DeliveryContext.mode="fake_delivery"`. Delivery follows configured `delivery_mode` / `global_mode` so the owner gets real Telegram E2E. Product isolation (`should_persist`, doctrine demote, recontact skip) unchanged.

## Tasks + commits

| Task | Outcome | Commit |
|------|---------|--------|
| 1. Invert sandbox delivery tests (RED) | Renamed/inverted orch + admin asserts; added `test_sandbox_respects_global_fake_delivery_mode`. RED verified (2 fail on forced fake). | `273912e` |
| 2. Drop sandbox force in orch + admin (GREEN) | Both `_effective_delivery_mode` return only `_delivery_mode`; log event `sandbox_fake_delivery` → `delivery_mode_fake`. Isolation pack 36 passed. | `cc486d2` |
| 3. Docs sync | README + PRODUCT_OWNER: real delivery under sandbox; isolation = `should_persist`; operator chat-targeting risk. | `00d51dd` |
| Fix round 1 (tests) | Strengthen delivery matrix + isolation co-asserts (admin D6, autonomous mode, learning co-assert, banner cleanup). | `ac38fd1` |

**Pool commits (4):** `273912e` `cc486d2` `00d51dd` `ac38fd1`

```
ac38fd1 test(sandbox): strengthen delivery matrix and isolation co-asserts
00d51dd docs(sandbox): real delivery under sandbox; isolation via should_persist
cc486d2 fix(sandbox): use configured delivery_mode under sandbox
273912e test(sandbox): invert delivery mode asserts under sandbox
```

## Files changed

| Path | Change |
|------|--------|
| `src/diana/application/turn_orchestrator.py` | `_effective_delivery_mode` identity; log rename |
| `src/diana/application/admin_service.py` | same |
| `tests/unit/application/test_turn_orchestrator.py` | inverted + matrix (supervised/autonomous/fake ops) + learning co-assert |
| `tests/unit/application/test_admin_service.py` | inverted approve + admin D6 ops-mode gold |
| `README.md` | sandbox isolation wording |
| `docs/PRODUCT_OWNER_ADMIN_SANDBOX.md` | delivery section + residual claim + operator risk |

## Deviations

None. Optional log rename and optional ops-mode test both included within scope. Fix round was test-only strengthening (no production delta beyond Task 2).

## Verifications run

```bash
# Task 1 RED
pytest ...::test_sandbox_autonomous_uses_configured_delivery_mode \
       ...::test_sandbox_approve_uses_configured_delivery_mode  # FAIL (expected)

# Task 2 GREEN — sandbox filter
pytest tests/unit/application/test_turn_orchestrator.py \
       tests/unit/application/test_admin_service.py -k sandbox  # 7 passed

# Isolation pack
pytest ... -k "sandbox or fake_delivery"  # 36 passed (TG re-run)

# Full unit safety net (executor Task 3)
pytest tests/unit -q  # 1372 passed

# Fix round 1
# sandbox-focused suite 9 passed (gsd log)
```

## DoD gate

- [x] `_effective_delivery_mode` no longer forces fake when sandbox active (orch + admin)
- [x] Inverted / matrix tests green (configured supervised + autonomous + ops fake)
- [x] Isolation golds green (learning skip, doctrine demote, staging, recontact)
- [x] Docs updated (README + PRODUCT_OWNER; verified still correct at pool close)
- [x] Self-check PASSED in log
- [x] Arch PASS WITH NOTES, 0 critical
- [x] Test-guardian suite OK, 0 prohibited mocks
- [x] Review rounds 2, final 0 open
- [x] Commits made (not pushed)

## Residuals

None blocking DoD.

### Out of scope / deferred (documented only)

| Residual | Class | Source |
|----------|-------|--------|
| Soft warn when activating sandbox on allowlisted VIP chat | out-of-scope | CLARIFY deferred · arch NOTES · PRODUCT_OWNER operator risk |
| Multi-replica sandbox session store | out-of-scope | CLARIFY |
| Gray-zone full path without vip_id (demote retained) | out-of-scope | CLARIFY |
| Historical item4 docs/audit that claimed sandbox forces `fake_delivery` | superseded | arch-enforcer supersede note (delivery only) |

Index: `.grok/agent-memory/residuals/sandbox-real-delivery.md` · Pool close: documentador report.

## Self-Check: PASSED

- [x] All PLAN tasks completed
- [x] PLAN tests run (inverted delivery + isolation pack + full unit 1372)
- [x] 0 regressions attributable
- [x] Project conventions respected (AGENTS.md, English artifacts, conventional commits, no AI attribution)
- [x] Review: 2 rounds, final 0 open (R1 6 fixed in `ac38fd1` + R2 clean)
- [x] Pool documentador close recorded
