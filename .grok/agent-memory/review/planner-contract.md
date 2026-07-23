# Merged Review — planner-contract (HARD_ID bab3bdb6) · Round 1

**Effort:** 4 · Reviewers: General CLEAN, General-2 (6 open), General-3 CLEAN, Tests (3 open, deduped), Plan CLEAN

## Review Issues

### Issue 1 [General-2] — Severity: suggestion
- **File**: tests/unit/cognitive/test_director.py
- **Description**: Empty-plan Director blast path not locked. Partial omit-history is covered; empty `Plan.capabilities == []` is only unit-tested on Planner. No Director path with all six `needs_*=false` asserting empty plan/retrieved and pipeline still completes.
- **Suggestion**: Add Director test: all needs false → plan capabilities `[]`, retrieved empty/keys match plan, decision still produced, no extra LLM calls beyond TAC-01.
- **Status**: fixed
- **Response**: Added `test_director_empty_plan_when_all_needs_false`: all six needs false → plan `[]`, retrieved `{}`, decision produced, TAC-01 call count remains 3.

### Issue 2 [General-2] — Severity: suggestion
- **File**: tests/unit/cognitive/test_planner.py
- **Description**: Single-true flag matrix (incl. schedule-only) missing. Parametrize one-true-at-a-time for all six needs_*.
- **Suggestion**: Parametrize over each needs_* alone True → capabilities exact single-element list matching C.2 map in stable order.
- **Status**: fixed
- **Response**: Added `test_planner_single_true_flag_maps_to_single_cap` parametrized over production `_NEED_TO_CAPABILITY` (one-true → exact single-cap list, including schedule-only).

### Issue 3 [General-2][Tests] — Severity: suggestion
- **File**: tests/unit/cognitive/test_planner.py (~101-112)
- **Description**: `test_planner_never_requests_cap_when_need_false` uses membership only; weak vs duplicates/extras.
- **Suggestion**: Assert exact ordered list equality against full map minus the false flag (len and order).
- **Status**: fixed
- **Response**: Strengthened to `assert plan.capabilities == expected` where expected is full `_NEED_TO_CAPABILITY` order minus the false flag; also asserts `len == 5`.

### Issue 4 [General-2] — Severity: nit
- **File**: src/diana/cognitive/planner.py:33
- **Description**: `getattr(..., False)` soft-fails on map/attr drift; all needs_* required post-analyst.
- **Suggestion**: Prefer bare attribute access `getattr(comprehension, attr)` or direct access so typos fail loud; or keep with comment if intentional.
- **Status**: fixed
- **Response**: Changed to bare `getattr(comprehension, attr)` (no default) so map/attr drift raises AttributeError; comment documents intent.

### Issue 5 [General-2] — Severity: nit
- **File**: tests/unit/cognitive/test_planner.py:19-26 vs planner.py
- **Description**: Dual capability maps in tests vs production risk drift.
- **Suggestion**: Import production `_NEED_TO_CAPABILITY` (or a public constant) in tests instead of redefining the map.
- **Status**: fixed
- **Response**: Tests now import `_NEED_TO_CAPABILITY` from `diana.cognitive.planner`; `_NEED_FLAGS`, `_FLAG_TO_CAP`, `_STABLE_CAPS` derived from production map.

### Issue 6 [General-2] — Severity: nit
- **File**: tests/unit/cognitive/test_planner.py:151-152
- **Description**: Redundant set assert in C.4 test after exact list assert already implies set.
- **Suggestion**: Keep set assert for C.4 documentation clarity OR drop if purely redundant; prefer keep set + list as contract doc in test name/comment if kept.
- **Status**: fixed
- **Response**: Kept both asserts; docstring/comment now state set = C.4 set-equality and list = L5 stable order.

### Issue 7 [Tests] — Severity: nit
- **File**: tests/unit/cognitive/test_director.py
- **Description**: No Director blast for empty plan `[]` (overlaps Issue 1; treat as same fix).
- **Suggestion**: Covered by Issue 1 fix.
- **Status**: fixed
- **Response**: Same fix as Issue 1 (`test_director_empty_plan_when_all_needs_false`).

## Dedup notes
- Tests Issue "membership only" merged into Issue 3
- Tests Issue empty Director blast merged with Issue 1 (same fix)
- Tests single-true nit strengthened to suggestion Issue 2

## Fix Round Summary

**Round:** 1  
**Date:** 2026-07-23  
**Outcome:** All 7 open issues fixed (0 wontfix).

| Issue | Status | Change |
|-------|--------|--------|
| 1 | fixed | Director empty-plan blast test |
| 2 | fixed | Parametrize single-true matrix |
| 3 | fixed | Exact ordered list equality |
| 4 | fixed | Bare getattr (no soft default) |
| 5 | fixed | Import production `_NEED_TO_CAPABILITY` |
| 6 | fixed | Keep set+list with C.4/L5 comments |
| 7 | fixed | Same as Issue 1 |

**Tests:** cognitive slice 100 passed; full `tests/unit` 376 passed.  
**Commit:** work unit for fix round (tests + getattr nit).
