# POOL-SUMMARY — residuals-polish

**Project:** DianaV2  
**Pool:** `residuals-polish`  
**Mode:** hardener residual polish (post-F3)  
**Status:** **CLOSED**  
**Date:** 2026-07-26  
**CLARIFY:** `.planning/quick/residuals-polish/CLARIFY.md`  
**Effort:** 5 (all items)

## Executive outcome

Closed four locked residual polish items: docs honesty, owner `/fp` Telegram UI, Director-owned naturalness 1× redraft MVP, and ProfileRetriever REAL mínimo (Schedule stays seat). All self-checks PASSED; arch 0 critical; reviews 0 open final; full unit suite green at close (~1213).

## Items

| # | Item | Outcome | Commits | Review |
|---|------|---------|---------|--------|
| 1 | **docs-sync** | README / ANEXO_T / F3-PHASE-STATUS / residual index aligned to code (F1 core + flag-gated F2/F3; boot-load closed; Anexo T implemented) | `311fe39`, `9d9ff22` | 0 open (fix-round honesty) |
| 2 | **owner-fp-ui** | Owner DM `/fp <turn_id>` → `AdminService.mark_false_positive`; dual owner gate; `fp_error` on store fail | `4a8d9ee`, `92cfffd`, `40acf9d`, `7432d2d`, `77c1f51` | 0 open |
| 3 | **naturalness-mvp** | Director 1× Generator+Evaluator redraft when naturalness < 0.5 (supervised default); no `Decision.action=regenerate`; Decider action order unchanged | `cee38e1`, `4c35a67`, `4c58553`, `97df474` | 0 open (T1/E2/G3 fixed) |
| 4 | **profile-real** | `ProfilesRepo` + `ProfileRetriever` REAL PK/`vip_id` (BR-15); Option B `needs_profile`; Schedule still `no_implementado` | `f2b908d`, `cce719c`, `03b51a5`, `dc27f33` | 0 open (findings 1–4 fixed) |

### Per-item verification (sources: item SUMMARYs)

| Item | Tests (reported) | Self-check |
|------|------------------|------------|
| 1 | Docs smoke DoD clean; no product paths | PASSED |
| 2 | admin commands 18; telegram pack 37; domain pack 97; unit 1191 | PASSED |
| 3 | unit 1200 ship; fix-round dir+dec 90 + models 56 | PASSED |
| 4 | primary 203; cognitive 348; unit 1213; fix slice 75 | PASSED |

## Architecture / product notes (from SUMMARYs + AGENTS)

1. **Naturalness is Director pre-Decider sequencing**, not a Decider action — AGENTS §4.1 P4 wording updated; no new `Decision.action`.
2. **`/fp` stays telegram-thin** — only calls existing AdminService; no escalate-action validation (accepted residual).
3. **Profile REAL is read-only mínimo** — writers/seed remain ops/OOS; empty/null-like content → None.
4. **Schedule half-seat unchanged** — `UNIMPLEMENTED_CAPABILITIES` still lists schedule only.

## Residuals after pool close

See consolidated index: `.grok/agent-memory/residuals/residuals-polish.md`.

### Still open / deferred (not this pool)

| Residual | Class |
|----------|--------|
| Live hydrate supervised `naturalness_min` into RuntimeThresholds / calibration | in-scope-followup (optional) |
| First-draft trace retention (non-overwrite history) | in-scope-followup |
| ProfilesRepo `load_only` exclude embedding | in-scope-followup |
| Exact Sunday 03:00 UTC cron | out-of-scope (doc residual) |

### Explicit OOS (document only)

| Residual | Class |
|----------|--------|
| Multi-worker / Redis / advisory locks G.4 | out-of-scope |
| Schedule REAL / external calendar | out-of-scope |
| Naturalness multi-retry / `action=regenerate` | out-of-scope |
| Profile writers / seed path | out-of-scope |
| Ops production flag enablement | out-of-scope |

## Sources of truth

- Item SUMMARYs under `.planning/quick/residuals-polish/item*/SUMMARY.md`
- Reviews: `.grok/agent-memory/review/residuals-polish-item*.md`
- Arch / test-guardian: `.grok/agent-memory/{arch-enforcer,test-guardian}/residuals-polish-item*.md`
- CLARIFY locked decisions (partition, OOS list)

## Close note

> Pool `residuals-polish` cerrado — 4 ítems completados, tests passing, commits hechos, documentación actualizada.
