# POOL-SUMMARY — telegram-hardener-3w

**Pool:** telegram-hardener-3w  
**Mode:** hardener-agile · Strict TDD  
**Date closed:** 2026-07-26  
**Status:** **COMPLETE** — items 1–4; self-checks PASSED; arch 0 critical; test-guardian adequate; review **0 open issues** each item  

**Sources:** item SUMMARYs under this directory · impact/arch/test-guardian agent reports · hardener review fix-rounds · git commits listed below.

---

## Objective

Harden the **Telegram I/O boundary and owner admin surface** after Fase 3 product pools: fail-closed error handling at the edge, process ops (dedup / rate-limit / health), thin handlers with presentation in application services, and single-instance scale-debt honesty (observability + CorrectSession UX + ops docs) — **without** Redis multi-replica, cognitive changes, or Decider semantics.

| Slice | Scope covered |
|-------|---------------|
| Item 1 error-safety | Outermost `ErrorHandlerMiddleware`; FreezeCheck fail-CLOSED; owner callback + business router edge guards |
| Item 2 ops-surface | Dedup + RateLimit middleware order; stdlib `GET /health` loopback + soft-fail bind; main lifecycle |
| Item 3 thin-handlers | `AdminTraceService` / `AdminMetricsService` presentation; thin admin/callback handlers; doctrine owner auth fix |
| Item 4 scale-debt | `log_swallowed` counter; CorrectSession resolve/expired UX; orch notify helper; `docs/OPS_SINGLE_INSTANCE.md` |

Out of scope (deferred residuals): multi-replica shared Redis for dedup/rate-limit/chat locks · full TurnOrchestrator god-file split · health disable flag · recontact_service `log_swallowed` stretch · CorrectSession↔TC supersede cascade.

---

## Items

| # | Title | Status | Primary evidence |
|---|--------|--------|------------------|
| 1 | error-safety | done | Freeze fail-closed + ErrorHandler + callback/business guards; fix-round `df8280f`; item **32** + telegram **134** / full unit **984–987** |
| 2 | ops-surface | done | Dedup@1 RateLimit@2 Freeze@6; health stdlib loopback; fix-round `48aed8a`; focused **62** + telegram **153** / full unit **1011** |
| 3 | thin-handlers | done | Trace/metrics formatters in application; thin handlers; review fix BUG-1 + doctrine owner (`cc5134a`, `e599d81`); focused **119–142** / full unit **1048** |
| 4 | scale-debt | done | `log_swallowed` + CorrectSession resolve + orch helper + OPS docs; item bundle **109 passed** |

**Aggregate gates:** executor self-checks **PASSED** all items · arch-enforcer **PASS WITH NOTES**, **0 critical** per item · test-guardian **suite adequate**, 0 prohibited mocks · hardener review **0 open issues** at item close.

---

## Commit themes (by item)

### Item 1 — error-safety

| Commit | Message |
|--------|---------|
| `7463a26` | `fix(telegram): fail-closed freeze on VIP lookup error` |
| `ea6297e` | `feat(telegram): add outermost ErrorHandlerMiddleware` |
| `1c2a0dd` | `fix(telegram): answer owner callback with alert on dispatch error` |
| `2178cd1` | `fix(telegram): swallow orchestrator errors at business router edge` |
| `df8280f` | `fix(telegram): review fix-round error-safety hardening` |

Themes: ErrorHandler index 0; freeze fail-closed + naive datetime→UTC; owner callback narrow try + awaiting_correct isolation; business edge swallow with structured extras; CancelledError not swallowed.

### Item 2 — ops-surface

| Commit | Message |
|--------|---------|
| `42f428c` | `feat(telegram): add DedupMiddleware and RateLimitMiddleware` |
| `47ad6b5` | `feat(telegram): wire ops middlewares into dispatcher order` |
| `970a09c` | `feat(telegram): add stdlib health endpoint and main lifecycle` |
| `7bafc9d` | `fix(telegram): drop unused Awaitable import in health module` |
| `48aed8a` | `fix(telegram): ops-surface review fix-round (loopback health, rate-limit prune)` |

Themes: process-local dedup/rate-limit; owner rate exempt; health 200 ok|degraded / 503 fail; `health_host` loopback-only; soft-fail bind; rate-limit prune + max_keys + fail-closed missing key.

### Item 3 — thin-handlers

| Commit | Message |
|--------|---------|
| `ef9d578` | `test+feat(application): trace presentation formatters` |
| `e64f091` | `feat(application): metrics render_week_summary` |
| `32c7ae8` | `refactor(telegram): thin admin trace/metrics handlers` |
| `cc5134a` | `fix(application): prefer total_ms and collapse list whitespace` |
| `e599d81` | `fix(telegram): require owner on doctrine callbacks` |

Themes: plain `str` + DTO keyboard inputs (no aiogram in application); canonical `/traza` + `vt` summary; `render_week_summary` single-shot; doctrine callbacks owner-gated (SEC-AUTH-01).

### Item 4 — scale-debt

| Commit | Message |
|--------|---------|
| `ef0f3c9` | `feat(application): add log_swallowed process-local counter` |
| `b14b7db` | `feat(telegram): CorrectSession resolve + session_expired UX` |
| `9e1237a` | `refactor(application): wire log_swallowed via orch notify helper` |
| `4fd1f80` | `docs(ops): single-instance process-local inventory` |

Themes: process-local swallow observability; CorrectSession live/expired/none + English session_expired UX; `_safe_notify_info` / `_fail_director_typed`; TC recontact fail-soft wired; OPS single-instance inventory documented.

---

## Architecture / ops decisions (locked this pool)

### 1. Fail-closed at the Telegram edge

- VIP freeze lookup errors block the turn (fail-closed), not open pass-through.
- Orchestrator/dispatch faults are answered or swallowed only at handlers/middleware; pure helpers still re-raise.
- Source: item1 SUMMARY · arch-enforcer item1.

### 2. Middleware order (live)

```
ErrorHandlerMiddleware          # 0 outermost
DedupMiddleware                 # 1
RateLimitMiddleware             # 2
LoggingMiddleware
BusinessConnectionMiddleware
OwnerDetectionMiddleware
FreezeCheckMiddleware           # 6 message/business only (skipped on callback_query)
ForbiddenKeywordsMiddleware
AuthMiddleware
```

- Source: item1–2 SUMMARYs · middleware stack golds.

### 3. Single-instance process-local state

- Dedup, rate-limit, CorrectSession, chat locks, `log_swallowed` counters are **in-process**.
- Multi-replica requires shared store (Redis / advisory locks) — explicitly deferred; inventory in `docs/OPS_SINGLE_INSTANCE.md`.
- Source: item2 residuals · item4 SUMMARY · OPS doc.

### 4. Presentation lives in application

- Trace list/summary/step and weekly metrics body text are application formatters; telegram handlers only keyboard + answer.
- No aiogram imports under `application/`.
- Source: item3 SUMMARY · arch-enforcer item3.

### 5. Health surface

- stdlib-only `GET /health`; DB hard gate (503); optional bot check → 200 degraded.
- Bind host restricted to loopback; soft-fail if bind fails (process still polls).
- No disable flag in this pool (A8 always-on residual).
- Source: item2 SUMMARY fix-round.

---

## Verifications (pool-level)

| Gate | Result | Source |
|------|--------|--------|
| Self-check per item | PASSED ×4 | item SUMMARYs |
| Arch enforcer | PASS WITH NOTES, 0 critical ×4 | `.grok/agent-memory/arch-enforcer/telegram-hardener-3w-item*.md` |
| Test guardian | suite adequate ×4 | `.grok/agent-memory/test-guardian/telegram-hardener-3w-item*.md` |
| Hardener review | 0 open issues at close (fix-rounds applied items 1–3) | review memory + item SUMMARYs |
| Cognitive / Decider / Learning | untouched for decision semantics | item no-touch lists |

Representative unit counts after progressive items: telegram **134 → 153+**; full unit **~984 → 1011 → 1048+** (env embedding failures pre-existing / OOS).

---

## Residuals (consolidated)

See `.grok/agent-memory/residuals/telegram-hardener-3w.md`.

| Residual | Class |
|----------|--------|
| Multi-replica Redis (dedup / rate-limit / chat locks) | out-of-scope / deferred |
| Optional health disable env flag | out-of-scope |
| Full TurnOrchestrator action-branch / god-file split | out-of-scope |
| `recontact_service.py` → `log_swallowed` | in-scope-followup |
| CorrectSession cancel on TC supersede cascade | out-of-scope |
| Health payload swallow counters | out-of-scope |
| `tp` global pagination vs `/turnos` chat filter | out-of-scope (product) |
| Pre-existing `sentence_transformers` embedding test fails | out-of-scope (env) |

---

## Pool close note

Pool **telegram-hardener-3w** closed — **4** items completed, tests green per item packages, commits done, documentation updated. Telegram edge is fail-closed and ops-aware; owner admin presentation is application-owned; single-instance limits are explicit in `docs/OPS_SINGLE_INSTANCE.md`.

---

## Document map

| Artifact | Path |
|----------|------|
| This summary | `.planning/quick/telegram-hardener-3w/POOL-SUMMARY.md` |
| Item SUMMARYs | `.planning/quick/telegram-hardener-3w/item{1–4}-*/SUMMARY.md` |
| Residuals | `.grok/agent-memory/residuals/telegram-hardener-3w.md` |
| Documentador report | `.grok/agent-memory/documentador/pool-2026-07-26-telegram-hardener-3w.md` |
| OPS inventory | `docs/OPS_SINGLE_INSTANCE.md` |
