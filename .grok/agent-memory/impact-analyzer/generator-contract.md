# Impact Analysis: Align Generator contract to Anexo E (`docs/contratos_restantes.md`)

**Date:** 2026-07-23  
**Change:** Align Generator runtime + empty-output fail path to Anexo E (E.1–E.4)  
**Analysis only** — no implementación  
**Source of truth:** `/home/ubuntu/repos/DianaV2/docs/contratos_restantes.md` § Anexo E  
**Pattern reference:** `.planning/quick/analyst-contract/PLAN.md` + `src/diana/cognitive/analyst.py` (A.6 retry) + evaluator-contract (B.6)

---

## Executive Summary

The Generator today is the thinnest cognitive LLM node: `Generator.generate(prompt: str) -> str` wraps `LLMProvider.generate` with a short system prompt (“write a natural reply draft… output draft text only”). Composition wires `Generator(provider)` with no extra ports. The Director calls it with `built.prompt_final`, stores `generated_text`, then always runs Evaluator + Decider. **Empty / whitespace drafts are handled in the Director**, not the Generator: after evaluation, Director fabricates `Decision(action="escalate", reason="empty_draft", draft_text=…)` and the orchestrator escalates (owner notify) rather than marking the turn `failed`.

Anexo E requires a stricter contract:

1. **E.1** — Only node that produces final visible text; single question “how would the owner reply?”; no classify / knowledge search / self-evaluate (REQ-COG-07).
2. **E.2** — Input is `prompt_final` as built by ContextBuilder (unchanged); output is plain text only (no JSON/metadata envelope).
3. **E.3** — Higher temperature allowed (tuning); **no** prior `EvaluationProfile` on regenerate (F1 has no regenerate — keep it that way); **never** write to any channel.
4. **E.4** — Empty/whitespace = **generation failure**: **exactly one retry**, then turn **`failed`** — **never** send an empty draft to the owner approval queue. Quality is exclusively Evaluator’s job.

**Global risk: medium.** Blast radius is **Generator + Director empty path + TurnOrchestrator typed fail**, plus tests. Composition/DI, Decider matrix, ContextBuilder, Evaluator, Behavior, Telegram I/O, and DB schema are low impact if `Decision.draft_text` remains a non-empty string on successful pipeline completion. Sensitive systems: deterministic Director control flow, approval-queue integrity (no empty drafts), fail durability (`turns.error` + owner `notify_info`), module purity (cognitive never imports telegram/behavior), and F1 action set (`approve|escalate` only — do **not** add `regenerate` / `send`).

**Scope is valid and tight** (effort ~4). No re-partition required. Mirror analyst/evaluator contract slices: optional input DTO → component empty-retry + typed error → Director remove escalate-for-empty → orchestrator notify branch. Do **not** implement F2 regenerate; do **not** invent quality scoring in Generator.

---

## Gap verification (contract vs code)

| Gap | Contract (Anexo E) | Current code | Status |
|-----|--------------------|--------------|--------|
| E.1 single question | “¿cómo respondería la dueña?”; only text producer | Prompt is “Write a natural reply draft…”; no classify/search | **PARTIAL** — tighten prompt wording; behavior OK |
| E.1 no self-evaluate | No scoring / action choice | Does not call structured eval or Decider | **OK** |
| E.1 no knowledge search | No retrievers | No registry/ports beyond LLM | **OK** |
| E.2 GeneradorInput | `{ prompt_final: string }` from D.3 as-is | `generate(prompt: str)` — bare str | **PARTIAL** — optional DTO `GeneratorInput`; Director already passes `built.prompt_final` unmodified |
| E.2 GeneradorOutput | `{ texto: string }` plain text | Returns bare `str` | **OK** for F1 (plain str is the English mapping of `texto`); do not wrap in JSON |
| E.3 higher temperature | May be higher than Analyst/Evaluator | Uses `generate` default `temperature=0.7`; Analyst/Eval structured default `0.0` | **OK / tuning** — optional explicit pass; not a hard contract fail |
| E.3 no prior EvaluationProfile | Same `prompt_final` on regenerate | F1 has no regenerate loop | **N/A F1 — do not add** |
| E.3 never writes channel | Output only through Evaluador→Decisor→approval | Returns str only; no telegram/behavior import | **OK** — keep purity tests |
| E.4 empty/whitespace | Fail generation; **1 retry** then `failed` | Director escalates after Evaluator with `empty_draft` | **CONFIRMED gap (critical behavior)** |
| E.4 never empty to approval | No empty draft in approval queue | Escalate path avoids approval, but wrong terminal semantics; empty can still reach owner via escalation notify | **CONFIRMED gap** |
| E.4 no quality validation | Only “produced something” | No quality gates in Generator | **OK** — do not add |
| Typed fail reason | Stable error for orchestrator (pattern A.6/B.6/D.6) | No `Generator*Error` in `exceptions.py` | **CONFIRMED gap** |
| Orchestrator owner notify | `mark_failed` + `notify_info` like other typed fails | Branches only for analyst / evaluator / context limit | **CONFIRMED gap** |

### Critical semantic change (E.4)

| Aspect | Today | Required |
|--------|-------|----------|
| Empty first LLM output | Stored as `generated_text`, evaluated, then `escalate` / `empty_draft` | Retry once with same messages; if still empty → raise typed error |
| Terminal status | `ESCALATED` via orchestrator | `FAILED` via `mark_failed` |
| Owner surface | Escalation notify (may include empty draft context) | Info notify with stable reason — **no approval row**, **no VIP send** |
| Evaluator call | Runs on empty draft | **Must not run** after generation failure |
| Decision object | Fabricated escalate Decision | **None** — pipeline aborts before Decider |

**Locked recommendation for planner:** implement empty-check + single retry **inside Generator** (mirror Analyst/Evaluator), raise e.g. `GeneratorEmptyOutputError` with reason `generador_salida_vacia`. Director deletes the empty-draft escalate branch. Orchestrator adds typed notify branch.

---

## Consumers / Call Sites Map

### Production — produce draft text

| Location | Role |
|----------|------|
| `src/diana/cognitive/generator.py:14-23` | `Generator.generate(prompt) -> str`; system prompt + `llm.generate` |
| `src/diana/cognitive/ports.py:55-67` | `LLMProvider.generate(..., temperature=0.7, max_tokens=1024)` |
| `src/diana/llm/deepseek.py:128-141` | Real text generation path |
| `src/diana/llm/fake.py:33-52` | Test double; records temperature; queue-driven text |

### Production — call Generator / empty handling

| Location | Behavior today | Needed for E.4 |
|----------|----------------|----------------|
| `src/diana/cognitive/director.py:144-176` | `draft = generate(prompt_final)`; store; evaluate; if blank → escalate Decision | Call generate; on success store non-empty; **remove** empty escalate branch; let typed error bubble |
| `src/diana/composition.py:181` | `Generator(provider)` | No extra DI expected |
| `src/diana/cognitive/exceptions.py` | Analyst / Evaluator / Context errors only | **Add** Generator empty/fail exception |

### Production — consume draft_text (must not receive empty on success)

| Location | Notes |
|----------|-------|
| `src/diana/cognitive/models.py:210-218` | `Decision.draft_text: str \| None` — escalate/approve carry draft |
| `src/diana/cognitive/director.py:149-156` | Passes draft into `EvaluatorInput.draft` |
| `src/diana/application/admin_service.py:93-112` | Approval + draft notify uses `decision.draft_text or ""` |
| `src/diana/application/turn_orchestrator.py:188-198` | approve → approval queue; escalate → notify_escalation |
| `src/diana/application/ports.py` | `DraftNotification.draft_text`, approval DTOs |
| `src/diana/infrastructure/db/models.py:123,189` | `pipeline_traces.generated_text`, `approvals.draft_text` |
| `src/diana/telegram/notifier.py:31` | Owner draft display |
| `src/diana/application/recovery_startup.py` | Re-notify pending approvals (pre-existing drafts) |

### Production — failure / notify path (E.4 related)

| Location | Behavior |
|----------|----------|
| `src/diana/cognitive/director.py:100-106` | Any exception → status sink `FAILED` + re-raise; partial traces remain |
| `src/diana/application/turn_orchestrator.py:110-173` | Typed branches: `analista_schema_invalido`, `evaluador_schema_invalido`, `contexto_excede_limite`; else `str(exc)` | **Extend** for Generator reason + `notify_info` |
| `turns.error` column | Durable fail reason | Reuse — **no migration** for new reason string |

### Tests — high impact

| File | Impact |
|------|--------|
| `tests/unit/cognitive/test_generator.py` | **HIGH** — empty retry, typed error, prompt purity, only `generate` not structured, no quality checks |
| `tests/unit/cognitive/test_director.py` | **HIGH** — replace `test_empty_draft_escalates`; assert no evaluation/decision on gen fail; status `GENERATING` then fail; no `empty_draft` Decision |
| `tests/unit/application/test_turn_orchestrator.py` | **HIGH** — typed fail + `notify_info` + `send_count==0` + no approval for empty generation |
| `tests/unit/cognitive/test_models.py` | **MED** — if `GeneratorInput` DTO added |
| `tests/unit/cognitive/test_import_purity.py` | **LOW** — keep green; Generator must not grow forbidden imports |

### Tests — low impact (construct draft strings only)

| File | Notes |
|------|-------|
| `tests/unit/application/test_admin_service.py` | Uses non-empty drafts; empty-correct already rejected |
| `tests/unit/acceptance/test_tac_mvp_f1.py` | Draft strings in fixtures |
| `tests/unit/llm/test_fake_llm.py` / `test_deepseek_provider.py` | Provider surface unchanged if temperature optional |

### Evidence lines (current empty path)

```160:176:src/diana/cognitive/director.py
        # Empty / whitespace-only draft must never approve (product safety).
        if not (draft or "").strip():
            decision = Decision(
                action="escalate",
                reason="empty_draft",
                evaluation=evaluation,
                draft_text=draft if draft is not None else "",
            )
        else:
            base = self._decider.decide(evaluation, comprehension, mode="supervised")
            ...
```

```14:23:src/diana/cognitive/generator.py
class Generator:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def generate(self, prompt: str) -> str:
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ]
        return await self._llm.generate(messages)
```

Only test locking wrong semantics: `tests/unit/cognitive/test_director.py::test_empty_draft_escalates` (whitespace → escalate/`empty_draft`).

---

## Risks

### Critical

| Risk | Why | Mitigation |
|------|-----|------------|
| Empty draft reaches approval queue | Admin uses `draft_text or ""`; if Decision ever `approve`s empty, owner gets blank approval | Generator fails closed **before** Evaluator/Decider; assert no `create_waiting` / `notify_draft` on empty |
| Keeping `empty_draft` escalate | Violates E.4 terminal `failed`; confuses ops vs real escalations | Delete Director branch; flip test; orchestrator `mark_failed` + info notify |

### Medium

| Risk | Why | Mitigation |
|------|-----|------------|
| Double empty-check (Generator + Director) | Drift / dead code | Single ownership: Generator validates “produced something”; Director trusts non-empty return |
| Storing empty `generated_text` before retry | Trace noise / reconstructability debate | Prefer store only successful non-empty draft; optional store last empty only if needed for debug — default: no store on fail (mirror Context size fail before GENERATING) |
| Retry count off-by-one | Contract: one retry = max 2 attempts | `_MAX_ATTEMPTS = 2` pattern from Analyst/Evaluator; assert FakeLLM call count |
| Treating LLM transport errors as empty | Over-broad catch masks infra bugs | Empty/whitespace only triggers empty-retry; other exceptions re-raise unchanged (unlike A.6 schema class set) |
| Inventing “quality” in Generator (JSON detect, length, tone) | Violates E.4 / REQ-COG-07 | Only `strip()` emptiness; no content quality rules |

### Low

| Risk | Why | Mitigation |
|------|-----|------------|
| Temperature change affects golds | No golden text fixtures; FakeLLM ignores temp for content | Document optional higher temp; keep default unless product asks |
| `GeneratorInput` DTO churn | Call sites are Director + unit tests only | Optional; if added, English field `prompt_final` maps 1:1 to contract |
| Reason string naming | Ops + tests depend on stable token | Lock `generador_salida_vacia` (Spanish stable reason, English exception class name) |
| F1 regenerate creep | E.3 mentions regenerate | Explicit out of scope; Decision.action stays approve\|escalate |

### Architecture (AGENTS.md) — must not break

- Director remains 100% deterministic (fixed retry count is OK; not LLM-chosen control).
- Generator still answers one question only.
- Behavior Engine remains outside cognition; Generator never sends.
- Learning stays post-turn only (orchestrator already).
- Anti-contamination: Generator sees only `prompt_final` (already assembled); no memory table access.
- No new LangChain/LangGraph orchestrator.

---

## Affected Tests

### Primary (must pass / rewrite under Strict TDD)

```bash
python -m pytest -q \
  tests/unit/cognitive/test_generator.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/cognitive/test_models.py \
  tests/unit/cognitive/test_import_purity.py
```

### Full unit gate (post-slice)

```bash
python -m pytest -q tests/unit
```

### Recommended new / flipped cases

| Case | File | Assert |
|------|------|--------|
| Non-empty draft returned | `test_generator.py` | existing |
| Prompt passed unmodified as user content | `test_generator.py` | existing + assert system ≠ user body rewrite of prompt_final |
| Only `generate`, never `generate_structured` | `test_generator.py` | existing |
| Empty → one retry → success | `test_generator.py` | 2 `generate` calls; returns second non-empty |
| Whitespace then empty → typed error | `test_generator.py` | raises `GeneratorEmptyOutputError`; reason `generador_salida_vacia`; 2 calls |
| Director empty fail: no evaluation/decision keys | `test_director.py` | replace escalate test; trace has prompt_text maybe, no evaluation/decision; status sink FAILED |
| Orchestrator empty gen fail | `test_turn_orchestrator.py` | `mark_failed(error="generador_salida_vacia")` + `notify_info` + actuator send_count 0 + no approval |
| Import purity still green | `test_import_purity.py` | no new forbidden imports |

### Do not require for this slice

- Live DeepSeek network tests
- Behavior engine delivery tests (Generator must not call them)
- Decider matrix changes
- Alembic migrations

---

## Files Map

### Edit (expected)

- `src/diana/cognitive/generator.py` — E.1 prompt; empty retry; optional temperature; input typing
- `src/diana/cognitive/exceptions.py` — `GeneratorEmptyOutputError` (+ reason)
- `src/diana/cognitive/director.py` — remove empty_draft escalate; trust Generator; document fail path
- `src/diana/application/turn_orchestrator.py` — typed fail + notify branch
- `tests/unit/cognitive/test_generator.py` — E.4 coverage
- `tests/unit/cognitive/test_director.py` — flip empty semantics
- `tests/unit/application/test_turn_orchestrator.py` — notify/fail path

### Edit optional / small

- `src/diana/cognitive/models.py` — only if adding `GeneratorInput { prompt_final: str }`
- `tests/unit/cognitive/test_models.py` — only with DTO

### Create (optional docs)

- `.planning/quick/generator-contract/PLAN.md` (planner)
- decisions.md if reason string / DTO choices need recording

### No touch

- `src/diana/cognitive/decider.py` — no empty special case
- `src/diana/cognitive/evaluator.py` / analyst / planner / context_builder — out of scope
- `src/diana/behavior/**` — Generator never delivers
- `src/diana/telegram/**` — orchestrator already owns owner notify
- `src/diana/learning/**` — post-turn unchanged
- Alembic / SQL schema — new reason string only in `turns.error`
- F1 `Decision.action` set — do not add `regenerate` / `send`
- Dirty unrelated tree work

---

## Recommended task split (for gsd-planner)

| # | Task | TDD surface |
|---|------|-------------|
| 1 | **E.1/E.2 surface** — tighten system prompt to owner-reply single question; keep plain-text I/O; optional `GeneratorInput`; assert no structured calls | `test_generator.py`, maybe `test_models.py` |
| 2 | **E.4 empty retry + typed error** — `_MAX_ATTEMPTS=2`; strip empty; `GeneratorEmptyOutputError` / `generador_salida_vacia` | `test_generator.py`, `exceptions.py` |
| 3 | **Director wiring** — remove empty_draft escalate; abort before Evaluator on gen fail; partial-trace policy | `test_director.py` |
| 4 | **Orchestrator notify** — branch like A.6/B.6/D.6; no VIP send; durable `turns.error` | `test_turn_orchestrator.py` |

Strict TDD active: red → green → refactor per task.

### Locked decisions to propose in PLAN (non-negotiable candidates)

| ID | Decision |
|----|----------|
| L1 | Empty/whitespace ownership lives **inside Generator** (not Director post-eval). |
| L2 | Exactly **one** retry (max 2 LLM `generate` calls) on empty/whitespace only. |
| L3 | Typed error reason string: **`generador_salida_vacia`**. |
| L4 | Terminal: turn **`failed`** + owner `notify_info`; **not** `escalate` / `empty_draft`. |
| L5 | No Evaluator / Decider / approval on generation failure. |
| L6 | F1 **no regenerate**; Decision.action stays `approve\|escalate`. |
| L7 | No quality/content validation beyond non-empty strip. |
| L8 | `prompt_final` passed as-is from BuiltContext (no Generator rewrite of knowledge). |
| L9 | Cognitive purity: no telegram/behavior/learning imports. |
| L10 | Out of scope: temperature product tuning PR, SPEC rewrite, Alembic, Behavior, F2 actions. |

---

## DoD for downstream chain

### gsd-planner
- Scope stays Generator + Director empty path + Orchestrator typed fail only.
- Tasks ordered Strict TDD; list exact pytest commands.
- Encode L1–L10; reject any task that adds regenerate or quality scoring in Generator.

### executor
- Tests first for empty retry and orchestrator notify.
- Flip `test_empty_draft_escalates` before/with Director change.
- Do not leave dual empty handling (Generator + Director escalate).

### arch-enforcer
- Generator answers one question; no channel write.
- Director still deterministic; no LLM action choice.
- Fail path: no VIP send; no approval with empty draft.
- Import purity green.

### test-guardian
- Assert max 2 generate attempts on permanent empty.
- Assert `generador_salida_vacia` durable + notify.
- Assert no evaluation/decision artifacts on gen fail.
- Full `tests/unit` green; no live network mocks required.

---

## Ready for chain

**Status:** READY  
**Handoff:** gsd-planner  
**Scope tight:** generator-contract (Anexo E) only  
**Primary tests:** listed above  
**Effort estimate:** 4 (matches pool item)

### Return payload (orchestrator)

```yaml
status: ready
executive_summary: >
  Generator is almost E.1–E.3 compliant (plain text LLM node, no channel I/O).
  Critical E.4 gap: empty/whitespace drafts escalate after evaluation instead of
  one-retry-then-failed. Align via Generator empty-retry + typed error + Director
  branch removal + orchestrator notify. No regenerate, no quality gates, no schema migration.
gaps:
  - empty_draft escalate violates E.4 failed semantics
  - no Generator empty retry
  - no typed GeneratorEmptyOutputError / orchestrator branch
  - E.1 prompt wording soft vs owner-reply question
risks:
  critical: [empty draft path semantics, approval-queue integrity]
  medium: [retry off-by-one, dual empty checks, over-broad exception catching]
  low: [temperature tuning, optional GeneratorInput DTO]
tests:
  primary: >
    python -m pytest -q tests/unit/cognitive/test_generator.py
    tests/unit/cognitive/test_director.py
    tests/unit/application/test_turn_orchestrator.py
    tests/unit/cognitive/test_models.py
    tests/unit/cognitive/test_import_purity.py
  full: python -m pytest -q tests/unit
next: gsd-planner
```
