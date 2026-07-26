# residuals-polish — residual index

**Pool:** residuals-polish  
**Status:** in_progress  
**CLARIFY:** `.planning/quick/residuals-polish/CLARIFY.md`  
**POOL:** `.planning/quick/residuals-polish/POOL.md`  
**Created:** 2026-07-26

## Pool items

| # | Item | Status | Path / notes |
|---|------|--------|--------------|
| 1 | docs-sync | **done** | `.planning/quick/residuals-polish/item1-docs-sync/` — README, ANEXO_T, F3-PHASE-STATUS, this index |
| 2 | owner-fp-ui | open | Telegram `/fp` (or equiv.) → `AdminService.mark_false_positive`; F3-PHASE-STATUS follow-up R5 UI |
| 3 | naturalness-mvp | open | Director 1× re-generate + re-eval when naturalidad low; no new Decision.action |
| 4 | profile-real | open | ProfileRetriever REAL mínimo (SQL `profiles`); Schedule stays seat `no_implementado` |

## Closed by item1 (docs only)

| Residual | Notes |
|----------|-------|
| README F1-only narrative | Flags default false; wired F3 + gray-zone gates documented; memory/staging Settings stubs called out (not live gates) |
| ANEXO_T “Pendiente de implementación” | Implemented: 005 + AdminTraceService + `/turnos` `/traza` |
| F3 boot-load RuntimeThresholds open row | Done in code: `load_runtime_thresholds` @ composition + main boot |
| Hardener fix-round flag honesty | Memory/staging unwired; sandbox ≠ FakeDelivery; config path; naturalness OOS narrowed |

## Explicit OOS (CLARIFY — do not expand)

- Multi-worker / Redis / advisory locks G.4 — see [`docs/OPS_SINGLE_INSTANCE.md`](../../../docs/OPS_SINGLE_INSTANCE.md)
- Fuzzy J.4 / admin hot-edit catalogs
- Promo rate-limit hard silence
- Sandbox FakeDelivery UX complete (`global_mode=fake_delivery` is separate from `feature_sandbox_enabled`)
- Schedule REAL / external calendar
- Naturalness `regenerate` action or >1 retry (multi-retry OOS; **1× MVP is item 3**)
- Ops production flag enablement
- Exact Sunday 03:00 cron (doc residual only unless scheduled work)

## Related

- Impact: `.grok/agent-memory/impact-analyzer/residuals-polish-item1-docs-sync.md`
- Master F3 status: `.planning/quick/F3-PHASE-STATUS.md` (not replaced by this file)
