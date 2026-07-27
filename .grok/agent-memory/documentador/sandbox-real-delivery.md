# Pool Documentation: sandbox-real-delivery

**Items:** 1  
**Date:** 2026-07-27  
**Project:** DianaV2  
**Pool:** sandbox-real-delivery  
**Mode:** hardener-agile · Strict TDD · effort 3  

## Consolidated Outcomes

### Item 1 — sandbox-real-delivery

| Field | Value |
|-------|--------|
| Outcome | Drop sandbox-forced `fake_delivery` in orch + admin `_effective_delivery_mode` (identity over configured `delivery_mode`). Real Telegram under sandbox when mode is supervised\|autonomous. Product isolation intact via `should_persist` / doctrine demote / recontact skip. Docs synced (README + PRODUCT_OWNER). Fix-round strengthened delivery matrix + isolation co-asserts. |
| Commits (4) | `273912e` test invert · `cc486d2` fix helpers · `00d51dd` docs · `ac38fd1` test matrix |
| Tests | Isolation pack **36** (TG) · sandbox filter 7→9 post-fix · full unit **1372** (executor Task 3) |
| Gates | arch PASS WITH NOTES **0 critical** · TG suite OK **0 mocks prohibidos** · self-check PASSED · review **0 open** after 2 rounds |

### Pool aggregate

| Metric | Value |
|--------|--------|
| Items | **1** complete |
| Review effort / rounds | **3** / **2** |
| Round 1 open → fixed | **6** (nits/suggestions) in `ac38fd1` |
| Round 2 open | **0** (all reviewers) |
| Arch critical | **0** |
| TG mocks prohibidos | **0** |
| Product code dirty at documentador close | **unrelated only** (`.env.example`, `gray_zone.py`, `test_sql_repo_shapes.py` — not this pool; left uncommitted) |

## Learnings / Patterns

1. **Sandbox isolation ≠ delivery mode** — Product non-persist is `should_persist=false` (learning/staging skip), not forcing `fake_delivery`. Real E2E owner testing requires configured `delivery_mode` to reach Behavior.
2. **Keep helper as identity, not inline** — `_effective_delivery_mode(self, _chat_id)` remains for call-site stability; unused chat_id is intentional.
3. **Ops fake_delivery is orthogonal** — Global `global_mode` / `delivery_mode="fake_delivery"` still works under sandbox (D6); golds on orch **and** admin after fix round.
4. **Supersede historical isolation claim carefully** — item4 claimed sandbox→fake_delivery as isolation; this pool supersedes **delivery only**; learning/doctrine/recontact isolation stays.
5. **Operator chat-targeting risk is product residual** — Real send goes to the sandboxed `chat_id`; soft warn on allowlisted VIP activate remains OOS; docs point to dedicated test chat.

## Residuals

### Auto-items / Deferred

_None auto-created for this pool._

### Out of scope (documented only)

| Residual | Class |
|----------|--------|
| Soft warn when activating sandbox on allowlisted VIP chat | out-of-scope |
| Multi-replica sandbox session store | out-of-scope |
| Gray-zone full path without vip_id (demote retained) | out-of-scope |
| Historical item4 “sandbox forces fake_delivery” audit text | superseded (delivery contract only) |

Full residual log: `.grok/agent-memory/residuals/sandbox-real-delivery.md`.

## Roadmap Updates

- Updated `.planning/quick/sandbox-real-delivery/SUMMARY.md` — review stats, 4-commit table, residuals, pool close
- Created `.grok/agent-memory/documentador/sandbox-real-delivery.md` (this file)
- Created `.grok/agent-memory/residuals/sandbox-real-delivery.md`
- `MEMORY.md` documentador + residuals pointers
- PRODUCT_OWNER / README — already correct from `00d51dd` (no re-edit)
- No `HARDENING_ROADMAP.md` in repo — pool close recorded here + SUMMARY only

## Docs commit

`a94a51d` — `docs(sandbox-real-delivery): close hardener pool sandbox-real-delivery`

## Next Steps

1. Orchestrator **Commit Gate de pool** after this docs commit.
2. Optional product follow-up only if requested: soft warn on `/sandbox on` when chat is allowlisted VIP (OOS this pool).
3. Default: no further sandbox delivery work; ops continue using dedicated test chat + configured delivery mode.
