# Arch Audit: generator-contract

**Date:** 2026-07-23  
**Auditor:** arch-enforcer  
**Plan:** `.planning/quick/generator-contract/PLAN.md`  
**Summary:** `.planning/quick/generator-contract/SUMMARY.md`  
**Contract:** `docs/contratos_restantes.md` Anexo E (E.1–E.4)  
**Verdict:** PASS WITH NOTES  
**Critical violations:** 0

## Scope audited

Production:
- `src/diana/cognitive/generator.py` — owner-reply system prompt (E.1); plain `generate(prompt) -> str` (E.2); `_MAX_ATTEMPTS=2` empty/whitespace-only retry; raise `GeneratorEmptyOutputError` (E.4); no quality gates; transport errors propagate
- `src/diana/cognitive/exceptions.py` — `GeneratorEmptyOutputError` (`reason` / `str` = `generador_salida_vacia`); exported in `__all__`
- `src/diana/cognitive/director.py` — sole production `generate` call site with `built.prompt_final`; **no** empty→escalate branch; store draft only after success; fail before Evaluator/Decider; outer FAILED latch re-raises
- `src/diana/application/turn_orchestrator.py` — typed `GeneratorEmptyOutputError` branch → `mark_failed(error="generador_salida_vacia")` + `notify_info`; notifier failure isolated; re-raise; no VIP path / no approval on fail

Cross-checks:
- AGENTS.md §3 module limits, §5.1 Director deterministic, Generator single-question (REQ-COG-07), Behavior outside cognition, learning post-turn only
- Import purity: cognitive ↛ `telegram` / `behavior` / `learning` / `aiogram` / `sqlalchemy` / `application`
- Layer direction: Application → Cognitive OK; Cognitive does not reverse-import Application/Telegram
- Focus: empty fail closed, no empty escalate, purity
- `empty_draft` absent from entire repo (src + tests + docs residual optional)
- F1 `Decision.action` still `Literal["approve","escalate"]`
- Sole production Generator caller: Director; composition wires `Generator(provider)` only

Commits: `49dc4d9`, `3d60877`, `ef4f43d`

## Evidence

| Check | Result |
|-------|--------|
| Cognitive → telegram/behavior/learning/aiogram/sqlalchemy/application | **PASS** — generator imports only `exceptions` + `ports.LLMProvider`; full cognitive package clean |
| Director deterministic | **PASS** — fixed pipeline; Generator retry fixed max 2 text calls (not LLM-chosen control) |
| Generator single question (E.1 / REQ-COG-07) | **PASS** — system prompt: “how would the owner reply?”; forbids classify/search knowledge/score/choose actions; draft text only |
| E.2 plain I/O | **PASS** — `async def generate(self, prompt: str) -> str`; only `llm.generate` (not structured); user content = prompt unmodified |
| E.3 no profile feedback / no channel I/O | **PASS** — no EvaluationProfile param; same messages on retry; no telegram/behavior |
| E.4 empty retry then fail | **PASS** — `_MAX_ATTEMPTS=2`; empty/whitespace → retry same messages → `GeneratorEmptyOutputError`; reason `generador_salida_vacia` |
| E.4 no quality judgment | **PASS** — only `(text or "").strip()`; no length/language/JSON gates |
| Transport errors not swallowed | **PASS** — no broad `except` around `llm.generate`; FakeLLM empty queue → `RuntimeError` after 1 call |
| No empty_draft escalate (L3) | **PASS** — `empty_draft` zero matches in repo; Director always Decider path on successful non-empty draft |
| Fail before Evaluator/Decider | **PASS** — raise before `_store("generated_text")`; status GENERATING then FAILED; no EVALUATING/DECIDING; no evaluation/decision keys |
| Owner notify in application (L4) | **PASS** — orchestrator `isinstance(GeneratorEmptyOutputError)` → `mark_failed` + `notify_info`; logger event `owner_notify_failed_after_generator_empty_output` |
| No VIP send / no approval on gen fail | **PASS** — exception before Decision post-path; orchestrator test: `send_count()==0`, `drafts==[]`, `escalations==[]`, `approvals` empty, `learn.calls==[]` |
| Dual empty handling forbidden | **PASS** — ownership only inside Generator; Director does not re-check emptiness after return |
| F1 Decision.action | **PASS** — still `approve\|escalate` only; no regenerate/send expansion |
| Scope vs PLAN | **PASS** — files match PLAN file map; no Decider/Evaluator/Analyst/Planner/ContextBuilder/Behavior/Telegram/Learning/Alembic changes beyond planned director+orchestrator+exceptions+generator+tests |
| Layer dependency direction | **PASS** — Application imports cognitive exceptions (allowed); Cognitive stays pure |

## Findings

### Critical (must fix before advance)

_None._

### Medium

_None that block advance._

### Observations

1. **System-prompt forbid test is soft** — `test_generate_system_prompt_is_owner_reply_question` asserts owner/reply + “do not” / “score” presence; the forbidden-token loop body is a no-op `pass`. Contract wording is still correct in production `_SYSTEM`; test-guardian may tighten assertion strength if desired.
2. **Double FAILED latch** — Director status sink FAILED then orchestrator `mark_failed` — existing A.6/B.6/D.6 pattern; durable error token comes from orchestrator typed branch (PLAN A4).
3. **Optional `GeneratorInput` DTO skipped** — intentional (A6); bare `str` is F1 mapping of `texto` / `prompt_final`. Reversible later without architectural debt.
4. **Temperature product tuning not done** — E.3 tuning only; default provider `generate` temp OK per PLAN non-goals.
5. **Residuals correctly left out of scope** — SPEC/documentador empty-draft wording, dirty-tree alembic `turns.error`, F2 regenerate, Anexos C/D/F — do not inflate this item.

## Compliance Checklist

- [x] Capas respetadas (Cognitive ↛ telegram/behavior/learning)
- [x] Scope del PLAN respetado (no Behavior/Telegram/Learning/Decider/Anexos C–D–F/alembic dirty tree)
- [x] Director 100% determinista en control de flujo
- [x] Generator responde una sola pregunta; plain text; sin classify/search/score/action
- [x] E.4: empty/whitespace → 1 retry → `generador_salida_vacia`; sin quality gates
- [x] Fail closed before Evaluator/Decider; sin `empty_draft` escalate
- [x] Owner notify en application; Cognitive sin conocer Telegram
- [x] Fail path: sin VIP send; sin approval queue; Learning no post-turno de éxito
- [x] Import purity / `test_import_purity` surface intact
- [x] F1 `Decision.action` solo `approve|escalate`
- [x] Logging: orchestrator `logger.exception` on director fail + notify-fail isolation
- [x] Dependencias de capa en dirección permitida
- [x] No dual empty handling (raise in Generator only)

## Residuals (not item scope inflation)

| Residual | Class | Notes |
|----------|-------|-------|
| SPEC / documentador empty-draft → failed semantics | out-of-scope | PLAN non-goal SPEC rewrite; runtime aligned |
| Dirty-tree alembic `turns.error` | out-of-scope | L9 / no-touch; not committed by this item |
| Optional GeneratorInput DTO | out-of-scope | A6 reversible |
| Temperature product tuning | out-of-scope | E.3 tuning only |
| Soften system-prompt unit assert | observation | Production prompt correct; test could be stricter |

## Handoff

**Verdict PASS WITH NOTES (0 critical) → advance to test-guardian.**
