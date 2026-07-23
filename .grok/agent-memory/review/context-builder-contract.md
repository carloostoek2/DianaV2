# Merged Review — context-builder-contract (HARD_ID 438d8c31) · Round 1

**Effort 4** · General CLEAN · General-2 (2 open) · General-3 CLEAN · Tests (1 open) · Plan CLEAN

## Review Issues

### Issue 1 [General-2] — Severity: bug
- **File**: src/diana/cognitive/context_builder.py (final `prompt.strip()` after assemble)
- **Description**: After D.4 reorder (current VIP message last), final `prompt.strip()` strips trailing whitespace from `turn.text`. Whitespace-only or trailing-space VIP bodies can be corrupted/disappear at the end of the prompt. Pre-D.4 strip hit later sections, not the VIP line.
- **Suggestion**: Do not strip the full prompt after current_turn is last; strip only intermediate joins, or rstrip only leading/trailing blank lines of non-turn sections, preserving `turn.text` verbatim in the Current section body.
- **Status**: fixed
- **Response**: Replaced full `prompt.strip()` with `lstrip("\n")` + ensure trailing newline so leading assembly noise is cleaned without rstrip of `turn.text`. Added `test_build_preserves_turn_text_trailing_whitespace` locking trailing spaces/tabs on the VIP body line.

### Issue 2 [General-2] — Severity: suggestion
- **File**: director.py / composition — style_rules
- **Description**: `style_rules` implemented and tested on ContextBuilder, but Director/composition never pass it — production always omits `reglas_estilo`.
- **Suggestion**: Either wire a minimal empty-list or config-based style_rules through Director, OR document as residual if PLAN L14 said out of scope for full REQ-VIP-04 pack. Prefer wiring empty/default if cheap so API is not dead; if PLAN locked residual, use wontfix with Response citing PLAN residual.
- **Status**: wontfix
- **Response**: PLAN L14 + residual #4 lock full REQ-VIP-04 style pack productization out of this item. ContextBuilder already accepts `style_rules=None` / `[]` (empty = omit lines). Passing empty through Director/composition is a pure no-op and would not change production behavior; wiring real config/Settings is the residual follow-up, not F1 DoD.

### Issue 3 [Tests] — Severity: suggestion
- **File**: tests/unit/cognitive/test_context_builder.py (`test_d4_current_turn_is_last_section` or similar)
- **Description**: D.4 full section order not fully locked — tests lock Persona first, knowledge internal order, Current last, Comp before Current, but not knowledge before Comprehension.
- **Status**: fixed
- **Suggestion**: Assert full headings equality (Persona → knowledge.* present → Comprehension → Current turn) so Persona→Comp→knowledge→Current would fail.
- **Response**: Strengthened `test_d4_current_turn_is_last_section` to assert exact headings list: Persona → knowledge.history → knowledge.context → Comprehension → Current VIP message.

## Fix Round Summary

| Issue | Status | Notes |
|-------|--------|-------|
| 1 strip turn.text | fixed | No full-prompt strip; preserve VIP trailing ws |
| 2 style_rules wire | wontfix | PLAN residual REQ-VIP-04 / L14; empty default already on builder |
| 3 full D.4 headings | fixed | Exact headings equality in unit test |

Tests: context_builder + director + evaluator + import_purity + turn_orchestrator cluster green.
Commit: fix work unit for Issue 1 + 3 tests/code.
