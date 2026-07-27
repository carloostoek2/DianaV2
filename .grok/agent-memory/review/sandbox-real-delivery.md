# Merged hardener review sandbox-real-delivery HARD_ID=351a11fc Round 2 — 0 open

## [General]
# Review: sandbox-real-delivery [General]
# Round: 2

## Summary

Re-verified production helpers, isolation, logs, docs, and Round 1 fix (plus test-strengthening from merged hardener fixes).

| Focus | Round 2 status |
|-------|----------------|
| `_effective_delivery_mode` (orch + admin) | Identity over `_delivery_mode`; no sandbox → fake branch |
| Product isolation | `should_persist` / `_maybe_post_turn` skip / staging gate unchanged |
| Log rename | `delivery_mode_fake` only; no `sandbox_fake_delivery` leftovers |
| Tests | Configured mode asserts (supervised / autonomous / fake ops); learning co-assert on autonomous send; banners cleaned |
| Docs | README + PRODUCT_OWNER match CLARIFY (real delivery + product non-persist) |

**Verdict:** APPROVE — 0 open issues. Round 1 nit fixed; no new general issues from fix commits.

## Issues

### Issue 1: Stale test section header still mentions fake_delivery as sandbox feature
- Severity: nit
- File: tests/unit/application/test_admin_service.py:663
- Description: Section banner previously said `# ── Sandbox marker + fake_delivery (item4)`. Now `# ── Sandbox marker + configured delivery_mode`. Orch banner is `# ── Sandbox isolation + configured delivery_mode`. No remaining forced-fake framing in section headers.
- Suggestion: (done)
- Status: fixed

## Open issue count

0 open

## [Tests]
# Review: sandbox-real-delivery [Tests]
# Round: 2

## Summary

Round 1 residuals are **resolved** in `ac38fd1`. Suite now fully protects the item contract: sandbox does not force `fake_delivery`; configured `delivery_mode` reaches Behavior on both orch and admin paths; ops-mode fake is locked on both surfaces; product isolation co-holds with real delivery on autonomous send.

| Round 1 issue | Resolution |
|---------------|------------|
| Admin D6 ops-mode gold missing | `test_sandbox_admin_respects_fake_delivery_mode` + `_admin_graph(delivery_mode=...)` |
| Learning not co-asserted on real-delivery path | `RecordingLearning` + `assert learn.calls == []` in configured orch test |
| Only `supervised` non-fake matrix | `test_sandbox_autonomous_uses_autonomous_delivery_mode` |
| Stale section banners | Orch + admin headers → “configured delivery_mode” |
| Redundant `!= fake_delivery` | Dropped; equality + CLARIFY comment |

**Isolation golds:** still present and not weakened (`skips_learning`, `inactive_still_runs_learning`, doctrine demote, staging skip, recontact sandbox hooks, engine/AMS fake).

**Mock audit: PASS.** CaptureBehavior at Behavior edge; FakeDirector for fixed Decision; real SandboxService.activate. No mocks of `_effective_delivery_mode`.

**Verdict:** suite protects adequately. Ready for hardener close on the tests axis.

## Coverage checklist

1. **Orch + admin under sandbox, real delivery** — COVERED  
   - `test_sandbox_autonomous_uses_configured_delivery_mode` (`supervised` + learning skip)  
   - `test_sandbox_autonomous_uses_autonomous_delivery_mode` (`autonomous`)  
   - `test_sandbox_approve_uses_configured_delivery_mode` (admin default supervised)
2. **Ops mode: sandbox + `fake_delivery`** — COVERED orch + admin  
   - `test_sandbox_respects_global_fake_delivery_mode`  
   - `test_sandbox_admin_respects_fake_delivery_mode`
3. **Isolation golds not weakened** — PASS
4. **Mock policy** — PASS (edges only)
5. **Prior edge residuals** — closed

## Issues

None.

## Open issue count

0 open

## [Plan]
# Review: sandbox-real-delivery [Plan]
# Round: 2

## Summary

Round 2 re-check after strengthen commit `ac38fd1`: still plan-aligned. Production helpers unchanged (`_effective_delivery_mode` identity on orch + admin). Delta is **test-only** and strengthens DoD coverage without scope creep:

| Change (tests only) | Plan alignment |
|---------------------|----------------|
| Orch: co-assert `learn.calls == []` on configured-mode autonomous path | Tightens D5 isolation gold on the same delivery path (PLAN isolation pack / success criteria) |
| Orch: `test_sandbox_autonomous_uses_autonomous_delivery_mode` | Covers Success Criterion “configured delivery_mode (supervised\|**autonomous**\|fake_delivery)” under sandbox |
| Admin: `test_sandbox_admin_respects_fake_delivery_mode` | Mirrors optional D6/D7 ops-mode proof on admin approve path |
| Comments/docstrings cite CLARIFY | Non-behavioral |

**CLARIFY D1–D7:** all still honored (real delivery, full pipeline, fixtures, `should_persist` / demote / recontact untouched, global `fake_delivery` preserved + now dual-path tested).

**DoD:** complete. No production no-touch surface edited in `ac38fd1`. Docs from Task 3 remain correct. Non-goals not implemented.

## Issues

None.
