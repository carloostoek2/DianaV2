# Arch Audit: context-builder-contract

**Date:** 2026-07-23  
**Auditor:** arch-enforcer  
**Plan:** `.planning/quick/context-builder-contract/PLAN.md`  
**Summary:** `.planning/quick/context-builder-contract/SUMMARY.md`  
**Contract:** `docs/contratos_restantes.md` Anexo D (D.1–D.6)  
**Verdict:** PASS WITH NOTES  
**Critical violations:** 0

## Scope audited

Production:
- `src/diana/cognitive/context_builder.py` — dual `BuiltContext`, D.4 emission order, null-like omit, `max_prompt_chars` size fail
- `src/diana/cognitive/models.py` — `BuiltContext` (`prompt_final`, `included_blocks`, `extra="forbid"`); `Decision.action` still `approve|escalate`
- `src/diana/cognitive/exceptions.py` — `ContextExceedsLimitError` (`reason` / `str` = `contexto_excede_limite`)
- `src/diana/cognitive/director.py` — single-source `built.prompt_final` → Generator + trace; `built.included_blocks` → Evaluator; no partial `prompt_text` on fail
- `src/diana/application/turn_orchestrator.py` — typed D.6 branch + `admin.notify_info`; re-raise; no VIP path on fail
- `src/diana/composition.py` — still `ContextBuilder()` with constructor default (no Settings sprawl)

Cross-checks:
- AGENTS.md §3 module limits, §5.1 Director deterministic, §5.5 anti-contamination (names-only blocks), §5.6 learning post-turn
- Import purity: cognitive ↛ `telegram` / `behavior` / `learning` / `aiogram` / `application`
- Layer direction: Application → Cognitive OK; notify stays in application
- Focus checks from orchestrator brief (D.4, dual return, size fail, purity, Decision, scope)

Commits: `2650587`, `f7abe8b`, `933f038`

## Evidence

| Check | Result |
|-------|--------|
| Cognitive → telegram/behavior/learning/aiogram/application | **PASS** — `context_builder` imports only cognitive models/exceptions + stdlib; full cognitive package clean of reverse deps |
| Director deterministic | **PASS** — fixed pipeline; ContextBuilder pure assembly (no LLM); size fail re-raises via outer `handle_turn` FAILED latch |
| ContextBuilder single question (D.1) | **PASS** — docstring + code assemble only; no draft, score, decide, retrieve |
| D.3 dual output | **PASS** — `build(...) -> BuiltContext{prompt_final, included_blocks}`; English fields; Spanish names docstring-only |
| D.4 section order | **PASS** — Persona → knowledge (`_KNOWLEDGE_EMISSION_ORDER`) → Comprehension → **Current VIP message last** |
| Knowledge order independent of dict insertion | **PASS** — fixed tuple history→context→memory→policy→examples→schedule→profile; unknown keys ignored |
| D.5 null-like omit | **PASS** — `_is_null_like` skips None / empty collections / blank str; no empty knowledge headings |
| `included_blocks` = knowledge names only | **PASS** — capability names in emission order; not persona/comprehension; shared filter with `list_included_blocks` |
| D.5/D.6 size fail | **PASS** — `len(prompt) > max_prompt_chars` → `ContextExceedsLimitError()`; no truncate helper; no retry loop |
| Reason token exact | **PASS** — `str(exc) == "contexto_excede_limite"`; orchestrator `mark_failed(error="contexto_excede_limite")` |
| Director single-source (L8) | **PASS** — does **not** re-call `list_included_blocks`; uses `built.included_blocks`; stores string under `prompt_text` only after successful build |
| Owner notify in application (L7) | **PASS** — orchestrator `isinstance(ContextExceedsLimitError)` → notify_info; notifier failures do not mask typed error |
| No VIP send on size fail | **PASS** — exception before Generator/Decision/deliver; orchestrator test `send_count()==0`, learning not invoked |
| F1 Decision.action (L9) | **PASS** — still `Literal["approve","escalate"]`; no regenerate/consult_doctrine/send expansion |
| Anti-contamination | **PASS** — Evaluator still receives capability **names**, not memory/policy bodies (via `built.included_blocks`) |
| Scope vs PLAN | **PASS** — production files match PLAN/SUMMARY; composition untouched beyond pre-existing default; no Anexos E–I / A–C rework / alembic / telegram / behavior / learning |
| Layer dependency direction | **PASS** — Application imports cognitive exceptions (allowed); Cognitive stays pure |

## Findings

### Critical (must fix before advance)

_None._

### Medium

_None that block advance._

### Observations

1. **`style_rules` not wired through Director/composition** — `build` accepts optional `style_rules`; Director never passes them (empty default). Matches L14 / residual “full REQ-VIP-04 style pack out of scope.” Not a contract break.
2. **Char-length proxy, not tokens** — intentional F1 approximation (`DEFAULT_MAX_PROMPT_CHARS = 100_000`). Token-accurate budgeting is documented residual; high default avoids happy-path false positives.
3. **`## Comprehension` not in strict D.4 prose list** — locked A3/L3: keep after knowledge, before current turn; excluded from `included_blocks`. Correct product decision, not scope creep.
4. **`list_included_blocks` remains public** — Director prefers `built.included_blocks` (single pass). Public helper stays for parity/tests and shares `_is_null_like` + emission order — good anti-drift.
5. **`included_blocks` not snapshotted in TraceStore** — reconstructability relies on re-deriving from `retrieved` + null-like rules (same residual class as evaluator-contract). Fail path correctly omits `prompt_text` when build raises.
6. **Double FAILED latch** — Director transitions FAILED then orchestrator `mark_failed` — existing A.6/B.6 pattern; error token comes from orchestrator branch.

## Compliance Checklist

- [x] Capas respetadas (Cognitive ↛ telegram/behavior/learning)
- [x] Scope del PLAN respetado (no Behavior/Telegram/Learning/Anexos E–I/alembic dirty tree)
- [x] Director 100% determinista en control de flujo
- [x] ContextBuilder responde una sola pregunta; pure assembly, no LLM
- [x] D.4: current turn last; knowledge emission order fixed
- [x] Dual `BuiltContext`; single source for prompt + blocks
- [x] Null-like omit; no empty knowledge placeholders
- [x] Size fail typed `contexto_excede_limite`; no truncate; no retry
- [x] Owner notify en application; Cognitive sin conocer Telegram
- [x] Fail path: sin VIP send; Learning no post-turno de éxito
- [x] Anti-contaminación: `included_blocks` = nombres de capacidad
- [x] F1 `Decision.action` solo `approve|escalate`
- [x] Logging: orchestrator `logger.exception` on director fail + notify-fail isolation
- [x] Dependencias de capa en dirección permitida

## Residuals (not item scope inflation)

| Residual | Class | Notes |
|----------|-------|-------|
| Token-accurate / Settings for `max_prompt_chars` | out-of-scope | Constructor default is F1 approximation |
| Full REQ-VIP-04 style pack via Director | out-of-scope | Optional param empty default only |
| MVP_COMPONENT_DESIGN / SPEC early-turn wording | out-of-scope | Documentador residual |
| Anexos E–I | out-of-scope | Separate pool items |
| Dirty-tree alembic `turns.error` | out-of-scope | L11 — not staged |
| Trace snapshot for `included_blocks` | observation | Same class as evaluator residual |

## Handoff

**Verdict PASS WITH NOTES (0 critical) → advance to test-guardian.**

No executor rework required for architecture gate. Test-guardian should re-verify:
- primary cluster + full `tests/unit` green
- D.4 order independence + current-turn-last tests
- size-fail: typed reason + orchestrator notify + `send_count==0`
- null-omit + included_blocks↔headings parity
- import purity; Decision still approve|escalate
- TAC-01 happy path still 3 LLM calls when build succeeds
