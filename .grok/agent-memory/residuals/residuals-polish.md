# residuals-polish — residual index

**Pool:** residuals-polish  
**Status:** **CLOSED** (2026-07-26)  
**CLARIFY:** `.planning/quick/residuals-polish/CLARIFY.md`  
**POOL:** `.planning/quick/residuals-polish/POOL.md`  
**POOL-SUMMARY:** `.planning/quick/residuals-polish/POOL-SUMMARY.md`  
**Created:** 2026-07-26  

## Pool items (all done)

| # | Item | Status | Path / notes | Commits |
|---|------|--------|--------------|---------|
| 1 | docs-sync | **done** | README, ANEXO_T, F3-PHASE-STATUS, this index | `311fe39`, `9d9ff22` |
| 2 | owner-fp-ui | **done** | Telegram `/fp` → `mark_false_positive`; dual owner gate; `fp_error` | `4a8d9ee`, `92cfffd`, `40acf9d`, `7432d2d`, `77c1f51` |
| 3 | naturalness-mvp | **done** | Director 1× redraft pre-Decider; threshold supervised 0.5; no `regenerate` action | `cee38e1`, `4c35a67`, `4c58553`, `97df474` |
| 4 | profile-real | **done** | ProfileRetriever REAL mínimo + `needs_profile`; Schedule seat unchanged | `f2b908d`, `cce719c`, `03b51a5`, `dc27f33` |

## Closed in this pool

| Residual | Closed by | Notes |
|----------|-----------|-------|
| README F1-only / stale Anexo T / boot-load open row | item1 | Code-aligned docs; flags default false honesty |
| Telegram `/fp` UI (R5 surface) | item2 | Owner DM; tokens `fp_marked`/`fp_usage`/`fp_unavailable`/`fp_error`; no escalate validation |
| Naturalness 1× re-draft MVP | item3 | Director owns; AGENTS §4.1 P4; total_ms + store order fix-round |
| Profile REAL mínimo + planner path | item4 | ProfilesRepo + BR-15; Option B `needs_profile`; Schedule still seat |

## Open follow-ups (deferred queue — not auto-created items)

| Residual | Class | Why | Files / origin |
|----------|-------|-----|----------------|
| Supervised `naturalness_min` live hydrate into RuntimeThresholds / calibration | in-scope-followup | PLAN non-goal; ctor default 0.5 only | director.py, RuntimeThresholds |
| First-draft trace retention (non-overwrite history on redraft) | in-scope-followup | MVP overwrites final wins | director.py |
| Second-G empty after first success edge (fail-closed) | in-scope-followup | PLAN A5 | director.py |
| Composition scan lock for `naturalness_min` | in-scope-followup | optional hygiene G3-3 | composition tests |
| ProfilesRepo `load_only` exclude embedding | in-scope-followup | nit5 performance when QPS/writers arrive | profiles.py |
| Exact Sunday 03:00 UTC cron | out-of-scope | Doc residual; v1 hourly + internal gates | F3-PHASE-STATUS / Pool3 |

## Explicit OOS (CLARIFY + item SUMMARYs — do not expand without product ask)

| Residual | Origin |
|----------|--------|
| **Multi-replica** / multi-worker / Redis / advisory locks G.4 | CLARIFY · OPS_SINGLE_INSTANCE.md |
| **Schedule REAL** / external calendar | CLARIFY · item4 no-touch |
| **Profile writers** / real VIP facts+notes + **sandbox catalog/UI** | **CLOSED** by pool `owner-admin-sandbox` (2026-07-27) — see `.grok/agent-memory/residuals/owner-admin-sandbox.md` |
| **Naturalness multi-retry** / `Decision.action=regenerate` | CLARIFY locked |
| Fuzzy J.4 / admin hot-edit catalogs | CLARIFY |
| Promo hard rate-limit silence | CLARIFY |
| Sandbox FakeDelivery UX complete | **CLOSED** by pool `owner-admin-sandbox` item4 (session isolation + `fake_delivery` + learning skip) |
| Ops production flag enablement | CLARIFY |
| Mark FP without escalate-decision validation | item2 accepted residual |
| Inline keyboard “mark FP” on escalate notifications | item2 non-goal |
| Director timing key `profile_retriever_ms` | item4 nit7 |

## Related

- Master F3 status: `.planning/quick/F3-PHASE-STATUS.md`
- Documentador report: `.grok/agent-memory/documentador/pool-2026-07-26-residuals-polish.md`
- Reviews: `.grok/agent-memory/review/residuals-polish-item*.md`
- Promoted residual close: `.grok/agent-memory/residuals/owner-admin-sandbox.md` · `docs/PRODUCT_OWNER_ADMIN_SANDBOX.md`
