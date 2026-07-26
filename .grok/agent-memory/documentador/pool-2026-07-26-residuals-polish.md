# Pool Documentation: residuals-polish

**Items:** 4  
**Date:** 2026-07-26  
**Project:** DianaV2  
**Pool:** residuals-polish  
**Mode:** hardener residual polish (post-F3)  
**Effort:** 5  

## Consolidated Outcomes

### Item 1 — docs-sync

| Field | Value |
|-------|--------|
| Outcome | Align README, ANEXO_T, F3-PHASE-STATUS, residual index to implemented reality (F1 core + flag-gated F2/F3; Anexo T implemented; boot-load closed; flag honesty fix-round). |
| Commits | `311fe39` docs align · `9d9ff22` honesty polish |
| Tests | Docs smoke DoD; 0 product code paths |
| Self-check | PASSED · review 0 open after fix-round |

### Item 2 — owner-fp-ui

| Field | Value |
|-------|--------|
| Outcome | Owner DM `/fp <turn_id>` → existing `AdminService.mark_false_positive`; pure dispatcher + `Command("fp")`; dual owner gate; store exception → `fp_error` + system-error UX. |
| Commits | `4a8d9ee` feat · `92cfffd` residual close · `40acf9d` hash fix · `7432d2d` fp_error · `77c1f51` SUMMARY hash |
| Tests | admin 18 · telegram pack 37 · domain pack 97 · unit 1191 |
| Self-check | PASSED · review 0 open |

### Item 3 — naturalness-mvp

| Field | Value |
|-------|--------|
| Outcome | Director-owned 1× Generator+Evaluator redraft when naturalness < supervised 0.5; no new Decision.action; Decider order intact; total_ms/`*_ms` + store-order fix-round. |
| Commits | `cee38e1` feat · `4c35a67` residual docs · `4c58553` total_ms/store · `97df474` residual ownership docs |
| Tests | unit 1200 ship · fix dir+dec 90 + models 56 |
| Self-check | PASSED · review 0 open (T1/E2/G3 fixed; A1/A2/E1 wontfix) |

### Item 4 — profile-real

| Field | Value |
|-------|--------|
| Outcome | ProfilesRepo + ProfileRetriever REAL (PK + BR-15 vip_id); Option B `needs_profile`; Schedule seat unchanged; null-like content → None. |
| Commits | `f2b908d` RED · `cce719c` REAL path · `03b51a5` needs_profile · `dc27f33` review locks |
| Tests | primary 203 · cognitive 348 · unit 1213 · fix slice 75 |
| Self-check | PASSED · review 0 open (findings 1–4 fixed; nits 5–7 wontfix) |

### Pool aggregate

| Metric | Value |
|--------|--------|
| Items | **4** complete |
| Arch critical | **0** ×4 |
| Review open at close | **0** ×4 |
| Full unit (item4) | **1213** passed |
| Multi-replica / Schedule REAL / regenerate loop | **not implemented** (documented OOS) |

## Learnings / Patterns

1. **Director sequencing vs Decider actions** — Naturalness redraft is pre-Decider Director work; keep residual docs free of substring `generate`/`regenerate` where source guards ban them; use “redraft” wording.
2. **Thin owner UI** — Wire existing AdminService API; dual fail-closed owner gate (pure + router); map store faults to explicit `fp_error`, never false-success.
3. **REAL mínimo readers** — PK + vip_id short-circuit + null-like content parity with ContextBuilder; defer writers/seed and `load_only` polish.
4. **Docs-first residual close** — Stale phase narrative and boot-load “open” rows poison agent planning; close with evidence paths, not aspirational text.
5. **Accepted residuals stay classified** — Mark-FP without escalate validation and first-draft overwrite are product choices, not unfinished work.

## Residuals

### Auto-items / Deferred

| Residual | Class |
|----------|--------|
| Live hydrate supervised `naturalness_min` → RuntimeThresholds | in-scope-followup |
| First-draft redraft history retention | in-scope-followup |
| ProfilesRepo `load_only` exclude embedding | in-scope-followup |
| Exact Sunday 03:00 cron | out-of-scope (doc) |

### Out of scope (documented only)

| Residual | Class |
|----------|--------|
| Multi-replica / Redis / advisory locks | out-of-scope |
| Schedule REAL / external calendar | out-of-scope |
| Naturalness multi-retry / `action=regenerate` | out-of-scope |
| Profile writers / seed / FakeProfiles production wire | out-of-scope |
| Ops production flag enablement | out-of-scope |

Full residual log: `.grok/agent-memory/residuals/residuals-polish.md`.

## Roadmap Updates

- `POOL.md` → all 4 items **done**, status CLOSED
- Created `POOL-SUMMARY.md` under residuals-polish/
- Consolidated residual index (closed vs open OOS)
- Updated `.planning/quick/F3-PHASE-STATUS.md` — polish pack DONE + close note
- MEMORY.md documentador + residuals pointer

## Docs commit

`docs(residuals-polish): close hardener pool residuals-polish`

## Next Steps

1. Orchestrator **Commit Gate de pool** after this docs commit.
2. Optional follow-ups only if product asks: naturalness hydrate, schedule REAL, multi-replica, profile writers.
3. Default next work = **ops gradual F3 flag enablement** (not a code pool).
4. Pause residual polish unless new review residuals appear.
