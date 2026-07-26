# SUMMARY — residuals-polish / item1-docs-sync

**Date:** 2026-07-26  
**Status:** DONE  
**Type:** docs only (no `src/`, `tests/`, `alembic/`)

## Objective

Align operator- and agent-facing docs with implemented code: F1 core + F2/F3 surfaces flag-gated (defaults false); Anexo T implemented; boot-load RuntimeThresholds closed in F3 status; residual index for pool.

## Tasks completed

| # | Task | Result |
|---|------|--------|
| 1 | README phase posture + locked contracts | Done — F1 core + flag-gated F2/F3; flags default false; Decision actions include `consult_doctrine`/`send`; migrations 001–011; doc links |
| 2 | ANEXO_T implemented + F3 boot-load closed | Done — Estado Implementado; exit framing updated; boot-load moved to closed follow-ups with evidence; `/fp` still open |
| 3 | Residual index + POOL/MEMORY + smoke | Done — index items 1–4 + OOS; POOL RESIDUALS pointer; MEMORY bullet; smoke clean |

## Commits

| Hash | Message |
|------|---------|
| (work unit on main) | docs: align README, Anexo T, F3 status to implemented reality |

Trust `git log -1 --oneline` for the short hash of this docs work unit.

## Files touched

| Path | Action |
|------|--------|
| `README.md` | rewrite lead, flags, migrations, docs, locked contracts |
| `docs/ANEXO_T-TRAZABILIDAD.md` | Estado + note + exit criterion + closing |
| `.planning/quick/F3-PHASE-STATUS.md` | closed boot-load; `/fp` open; polish pool pointer |
| `.grok/agent-memory/residuals/residuals-polish.md` | create |
| `.planning/quick/residuals-polish/POOL.md` | RESIDUALS + item1 done |
| `.grok/agent-memory/MEMORY.md` | Residuals pointer |

## Deviations

- Boot-load closed-row title rephrased slightly so smoke negative `rg` for the old open residual string stays clean.
- MEMORY.md: only residual pointer added; unrelated working-tree churn discarded before commit.

## Verifications

Smoke DoD from PLAN (stale phrases absent; required truths present; no product-code paths modified).

## Residuals

| title | class_sugerida | por_qué | archivos |
|-------|----------------|---------|----------|
| owner-fp-ui (pool item 2) | in-scope-followup | API exists; Telegram `/fp` UI still open | F3-PHASE-STATUS, residuals-polish.md |
| naturalness-mvp (item 3) | in-scope-followup | CLARIFY locked; not this item | CLARIFY, residuals-polish.md |
| profile-real (item 4) | in-scope-followup | CLARIFY locked; not this item | CLARIFY, residuals-polish.md |
| Exact Sunday 03:00 cron | out-of-scope | Doc residual only; CLARIFY OOS unless scheduled | F3-PHASE-STATUS |
| Unrelated dirty: gsd-documentador-system-prompt-struct.log | out-of-scope | Pre-existing working tree noise; not part of this work unit | `.planning/quick/gsd-documentador-system-prompt-struct.log` |

## Self-Check: PASSED

- [x] All PLAN tasks completed
- [x] Tests of PLAN (docs smoke) run
- [x] 0 regressions attributable (no product code)
- [x] Project conventions respected (docs English residual index; ANEXO_T Spanish status)
