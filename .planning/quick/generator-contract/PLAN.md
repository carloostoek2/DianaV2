---
phase: quick
plan: generator-contract
type: auto
item: generator-contract (Pool remaining-contracts-cognitive · Anexo E)
effort: 4
stack: python>=3.12, pydantic-v2, pytest-asyncio
depends_on: evaluator-contract (B.6 typed fail + notify); context-builder-contract (D.6 size fail gold)
source_of_truth: docs/contratos_restantes.md Anexo E (E.1–E.4 only)
impact: .grok/agent-memory/impact-analyzer/generator-contract.md
mode: standard
---

## Objective

Align the **Generator empty-output path + single-question surface** to `docs/contratos_restantes.md` Anexo E (E.1–E.4): Generator is the only node that drafts plain text from `prompt_final` (question: *how would the owner reply?*), retries **once** on empty/whitespace, then raises typed `GeneratorEmptyOutputError` with reason `generador_salida_vacia`; Director **removes** the post-eval `empty_draft` escalate branch so failure aborts **before** Evaluator/Decider; TurnOrchestrator marks the turn `failed` and `notify_info`s the owner — **no VIP send, no approval row, no empty draft in the approval queue**.

## Scope

- **In:**
  - Soft-align Generator system prompt to owner-reply single question (E.1)
  - Keep plain-text I/O: `generate(prompt: str) -> str` (E.2); no JSON/metadata envelope
  - Empty/whitespace detection + exactly one retry inside Generator (E.4)
  - Typed exception `GeneratorEmptyOutputError` / reason `generador_salida_vacia`
  - Director: delete empty→escalate branch; trust non-empty return; re-raise gen fail (status FAILED via existing outer handler)
  - Orchestrator: typed `mark_failed` + `notify_info` branch (mirror A.6/B.6/D.6)
  - Unit tests locking retry counts, typed reason, no evaluation/decision on gen fail, no VIP send
- **Out / Non-goals:**
  - F2 regenerate / `Decision.action` expansion beyond `approve|escalate` (L5/L8)
  - Quality scoring, length/tone/JSON “quality” gates inside Generator (L6)
  - Feeding prior `EvaluationProfile` into Generator (L5)
  - Optional `GeneratorInput` DTO (not required for E.2; bare `str` is F1 mapping of `texto`)
  - Temperature product-tuning PR (E.3 tuning only; default `generate` temp OK)
  - Anexos C, D, F rework; Behavior Engine; Telegram redesign; Learning
  - Alembic / SQL schema (reuse `turns.error` string column)
  - Dirty-tree WIP / unrelated modules
  - SPEC / REQUERIMIENTOS full rewrite (documentador residual if needed later)
- **Constraints:**
  - Strict TDD Mode **active** — red → green → refactor per task
  - Cognitive Core **must not** import `diana.telegram`, `diana.behavior`, `diana.learning`, `aiogram`, `sqlalchemy`
  - Director control flow stays **100% deterministic** (fixed `_MAX_ATTEMPTS=2` is OK)
  - Code/comments/identifiers in **English**; this PLAN is English
  - Import purity must stay green: `tests/unit/cognitive/test_import_purity.py`
  - Happy-path TAC-01 LLM call count stays **3**: Analyst structured + Generator text + Evaluator structured (retry only on fail path)

## Assumptions

- A1: Sole production Generator caller is `CognitiveDirector` with `built.prompt_final` unmodified (impact confirmed). Keep signature `async def generate(self, prompt: str) -> str`.
- A2: Empty ownership lives **inside Generator** only; Director must not double-check or escalate for empty after successful return.
- A3: On permanent empty, Generator raises **before** returning; Director never stores `generated_text` for failed generation (store is after `await generate` — no extra guard needed if raise propagates).
- A4: Orchestrator double FAILED (Director status sink FAILED then `mark_failed`) is existing A.6/B.6/D.6 pattern — keep; durable error **token** comes from orchestrator typed branch.
- A5: Transport/runtime errors from `llm.generate` (e.g. FakeLLM empty queue `RuntimeError`) are **not** empty-class — re-raise without empty-retry.
- A6: Skipping optional `GeneratorInput` DTO is reversible and keeps blast radius to three modules + tests.
- A7: Soft prompt wording change is product-aligned (L7) and must not instruct classify/search/evaluate/score/action.

## Locked decisions (NON-NEGOTIABLE)

| ID | Decision |
|----|----------|
| L1 | Generator only produces plain text from `prompt_final`; no classify / knowledge search / self-evaluate (REQ-COG-07). |
| L2 | Empty/whitespace after **1 retry** (max **2** `llm.generate` calls) → typed `GeneratorEmptyOutputError` with reason **`generador_salida_vacia`**. |
| L3 | Remove Director empty→escalate branch; fail closed **before** Evaluator (no evaluation/decision artifacts on gen fail). |
| L4 | Orchestrator `mark_failed(error="generador_salida_vacia")` + `notify_info`; **no VIP send**; no approval. |
| L5 | No regenerate profile feedback; F1 has **no** regenerate loop. |
| L6 | No quality judgment in Generator — only non-empty after `strip()`. |
| L7 | Soft-align system prompt to “how would the owner reply?” if currently different. |
| L8 | `Decision.action` remains `approve \| escalate` only. |
| L9 | No dirty tree / Anexos C D F / Behavior changes. |
| L10 | Strict TDD: tests first; FakeLLM / InMemory ports only; no live network. |

## Architecture Approach

### QUÉ (behavior / contracts)

| Contract | Runtime truth after this item |
|----------|-------------------------------|
| E.1 | Generator answers only “how would the owner reply?”; sole text producer; no classify/search/score/action |
| E.2 in | User content is `prompt_final` as built by ContextBuilder — unmodified knowledge assembly |
| E.2 out | Plain `str` draft (English mapping of `texto`); no JSON envelope |
| E.3 | No EvaluationProfile feedback channel; no channel I/O from Generator |
| E.4 empty | Empty/whitespace → retry once same messages → then `failed` via typed error |
| E.4 quality | Evaluator only; Generator never scores |
| App | On gen fail: turn `failed`, error `generador_salida_vacia`, owner info notify, VIP send count 0, no approval |

**Terminal path change (critical):**

| Today | Required |
|-------|----------|
| Generate empty → store draft → evaluate → `Decision(escalate, empty_draft)` → owner escalation surface | Generate empty → retry once → raise `GeneratorEmptyOutputError` → Director FAILED + re-raise → orchestrator `mark_failed` + `notify_info` |

### CÓMO (structure / patterns)

- **Layers:** Cognitive Core (`generator`, `exceptions`, `director`) + Application (`turn_orchestrator` fail branch only). No Behavior / Telegram imports in cognitive.
- **Pattern to copy:**
  - Typed error shape: `src/diana/cognitive/exceptions.py` — `AnalystSchemaInvalidError` / `EvaluatorSchemaInvalidError` / `ContextExceedsLimitError`
  - Retry loop locality: `src/diana/cognitive/analyst.py` (`_MAX_ATTEMPTS = 2`) — **but** Generator retries only on empty/whitespace, **not** on schema-class exception sets
  - Orchestrator notify branch: `src/diana/application/turn_orchestrator.py` Analyst/Evaluator/Context blocks (lines ~116–166)
  - Director fail-before-downstream golds: `test_director_analyst_schema_fail_no_plan_trace`, `test_director_evaluator_schema_fail_no_decision_trace`, `test_director_context_exceeds_limit_no_decision`
  - Orchestrator gold: `test_orchestrator_*_schema_fail_marks_failed_notifies_owner` / `test_orchestrator_context_exceeds_limit_marks_failed_notifies_owner`
- **File map:**
  - **Edit:** `generator.py`, `exceptions.py`, `director.py`, `turn_orchestrator.py`, `test_generator.py`, `test_director.py`, `test_turn_orchestrator.py`
  - **No-touch:** `decider.py`, `evaluator.py`, `analyst.py`, `planner.py`, `context_builder.py`, `behavior/**`, `telegram/**`, `learning/**`, Alembic, F1 action set
- **Wiring:** Director already passes `built.prompt_final`; Generator raises; Director outer `except` → status FAILED; Orchestrator catches typed error.
- **Interfaces first:** exception class before Generator raise; no new public DTO required.

### Generator algorithm (exact intent)

```python
_MAX_ATTEMPTS = 2  # initial + exactly one retry (Anexo E.4)

_SYSTEM = (
    "You are the message Generator for a VIP chat assistant. "
    "Answer only one question: how would the owner reply? "
    "Write a natural reply draft based only on the prompt. "
    "Do not classify, search knowledge, score, or choose system actions. "
    "Output the draft text only."
)

async def generate(self, prompt: str) -> str:
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": prompt},
    ]
    last_empty: str | None = None
    for _attempt in range(_MAX_ATTEMPTS):
        text = await self._llm.generate(messages)  # let non-empty transport errors propagate
        if (text or "").strip():
            return text
        last_empty = text
        continue
    raise GeneratorEmptyOutputError() from None  # or without cause; reason fixed
```

Notes:
- Do **not** wrap `llm.generate` in broad `except Exception` that treats transport errors as empty.
- Same `messages` on retry (E.3 / E.4 — no profile feedback, no rewritten prompt).
- Optional: pass explicit `temperature=` only if already desirable; default provider 0.7 is OK (E.3 tuning).

### Exception contract (exact intent)

```python
class GeneratorEmptyOutputError(Exception):
    """Raised when Generator returns empty/whitespace after one retry (Anexo E.4).

    Stable reason: ``generador_salida_vacia``.
    """

    reason: str = "generador_salida_vacia"

    def __init__(self, reason: str = "generador_salida_vacia") -> None:
        self.reason = reason
        super().__init__(reason)

    def __str__(self) -> str:
        return self.reason
```

Export in `__all__`.

### Director change (exact intent)

1. Keep: `draft = await self._generator.generate(built.prompt_final)` then store on success.
2. **Delete** the block:

```python
if not (draft or "").strip():
    decision = Decision(action="escalate", reason="empty_draft", ...)
else:
    base = self._decider.decide(...)
```

3. Replace with single path: Decider always runs on successful non-empty draft; set `draft_text=draft`.
4. Update module/docstring that mentions escalate-for-empty-draft / `empty_draft`.
5. On `GeneratorEmptyOutputError`: do not store evaluation/decision (never reached); outer handler sets FAILED + re-raise. Document: “On Generator empty fail no generated_text/evaluation/decision is stored.”

### Orchestrator change (exact intent)

Import `GeneratorEmptyOutputError`. Add branch **before** generic else:

```python
elif isinstance(exc, GeneratorEmptyOutputError):
    error = "generador_salida_vacia"
    await self._coordinator.mark_failed(turn_id, error=error)
    try:
        await self._admin.notify_info(
            f"Turn {turn_id} failed: generador_salida_vacia",
            chat_id=incoming.chat_id,
        )
    except Exception:
        logger.exception(
            "owner_notify_failed_after_generator_empty_output",
            extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
        )
```

Notifier failure must never mask the typed error (same as A.6/B.6/D.6).

## Context

@`.grok/agent-memory/impact-analyzer/generator-contract.md`
@`docs/contratos_restantes.md` (Anexo E only)
@`.planning/quick/evaluator-contract/PLAN.md` (structure + typed fail pattern)
@`.planning/quick/context-builder-contract/PLAN.md` (D.6 fail + notify gold)
@`AGENTS.md` (§3 module limits, §5.1 Director, Generator single-question, Behavior outside cognition)
@`src/diana/cognitive/generator.py`
@`src/diana/cognitive/exceptions.py`
@`src/diana/cognitive/director.py` (empty_draft branch ~160–176)
@`src/diana/application/turn_orchestrator.py` (typed fail branches)
@`src/diana/cognitive/analyst.py` (_MAX_ATTEMPTS gold — adapt for empty-only)
@`tests/unit/cognitive/test_generator.py`
@`tests/unit/cognitive/test_director.py` (`test_empty_draft_escalates` — flip)
@`tests/unit/application/test_turn_orchestrator.py` (A.6/B.6/D.6 notify golds)
@`tests/unit/cognitive/test_import_purity.py`

## Tasks

### Task 1: Generator E.1 prompt + E.4 empty retry + typed error
**type:** auto  
**Objective:** Generator drafts plain text with owner-reply system prompt; empty/whitespace retries once then raises `GeneratorEmptyOutputError(reason="generador_salida_vacia")`; never calls structured generation or judges quality.

**TDD order:**
1. Extend `tests/unit/cognitive/test_generator.py` + exception unit assertion (RED).
2. Edit `exceptions.py` + `generator.py` (GREEN).
3. Refactor only if needed; do **not** change Director/Orchestrator yet (Director empty escalate still exists until Task 2).

**Files (edit):**
- `src/diana/cognitive/exceptions.py`
- `src/diana/cognitive/generator.py`
- `tests/unit/cognitive/test_generator.py`

**Tests to add/keep (must exist after task):**
- Keep: `test_generate_returns_draft_text`, `test_generate_passes_prompt_to_llm`, `test_generate_uses_only_generate_not_structured`
- `test_generate_system_prompt_is_owner_reply_question` — system message content mentions owner reply (or equivalent single-question wording); forbids instruct to classify/score/choose actions; user content still equals/includes `prompt` unmodified
- `test_generate_empty_then_success_retries_once` — FakeLLM `text_responses=["", "Hola ok"]` → returns `"Hola ok"`; exactly **2** `generate` calls; both use same user prompt
- `test_generate_whitespace_then_success_retries_once` — `["   \n", "draft"]` → `"draft"`; 2 calls
- `test_generate_double_empty_raises_generador_salida_vacia` — `["", "  "]` → raises `GeneratorEmptyOutputError`; `str(exc) == "generador_salida_vacia"`; `exc.reason == "generador_salida_vacia"`; exactly 2 `generate` calls
- `test_generate_transport_error_does_not_count_as_empty_retry` — FakeLLM empty queue / forced `RuntimeError` on first call → propagates; call count 1 (no empty-class swallow)
- `test_generator_empty_output_error_str_and_reason` — unit on exception class (mirror evaluator)

**Do NOT:**
- Add quality checks (min length, language detect, JSON detect).
- Call `generate_structured`.
- Change Director/Orchestrator (Task 2–3).
- Add `regenerate` or EvaluationProfile parameters.
- Introduce `GeneratorInput` DTO (out of scope A6).

**Verification:**
```bash
python -m pytest -q \
  tests/unit/cognitive/test_generator.py \
  tests/unit/cognitive/test_import_purity.py
```

**Done:**
- [ ] `_MAX_ATTEMPTS = 2` empty-only retry in Generator
- [ ] `GeneratorEmptyOutputError` exported; stable reason `generador_salida_vacia`
- [ ] System prompt soft-aligned to owner-reply single question
- [ ] Commands above green

---

### Task 2: Director remove empty_draft escalate; fail closed before Evaluator
**type:** auto  
**Objective:** Empty generation never reaches Evaluator/Decider; no `Decision(reason="empty_draft")`; successful path always has non-empty `draft_text` from Generator return.

**TDD order:** flip/add director tests RED → edit `director.py` GREEN.

**Files (edit):**
- `src/diana/cognitive/director.py`
- `tests/unit/cognitive/test_director.py`

**Director edits (exact):**
1. Remove empty/whitespace escalate branch after evaluation.
2. Always: `base = self._decider.decide(...); Decision(..., draft_text=draft)`.
3. Docstring/`handle_turn` docs: drop “empty string when escalate-for-empty-draft”; document Generator empty fail like other typed fails (no evaluation/decision stored; no `generated_text` if raise before store).

**Tests (must flip/add):**
- **Replace** `test_empty_draft_escalates` with e.g. `test_generator_empty_fails_before_evaluator`:
  - FakeLLM: valid comprehension structured; text queue permanent empty (`["", "  "]` or two empties); **no** evaluator profile needed (must not be consumed)
  - `pytest.raises(GeneratorEmptyOutputError)`; `str == "generador_salida_vacia"`
  - Trace keys: `generated_text` **absent**; `evaluation` **absent**; `decision` **absent**
  - Status sink: `GENERATING` present; `EVALUATING` / `DECIDING` **absent**; last status `FAILED`
  - LLM calls: no second `generate_structured` for EvaluationProfile (only Analyst structured)
- Keep existing happy-path director tests green (non-empty draft → approve/escalate via Decider only).

**Do NOT:**
- Reintroduce empty checks in Decider.
- Store synthetic evaluation on gen fail.
- Change Decider thresholds or action set.
- Touch Behavior / Telegram.

**Verification:**
```bash
python -m pytest -q \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_generator.py
```

**Done:**
- [ ] No `empty_draft` Decision path in production code
- [ ] Gen fail aborts before Evaluator
- [ ] Commands above green

---

### Task 3: Orchestrator typed fail + owner notify for Generator empty
**type:** auto  
**Objective:** On `GeneratorEmptyOutputError`, durable `turns.error = generador_salida_vacia`, owner `notify_info` once, zero VIP sends, no approval/draft/escalation notify surfaces.

**TDD order:** add orchestrator test RED → edit `turn_orchestrator.py` GREEN.

**Files (edit):**
- `src/diana/application/turn_orchestrator.py`
- `tests/unit/application/test_turn_orchestrator.py`

**Implementation:** import `GeneratorEmptyOutputError`; add `elif isinstance(exc, GeneratorEmptyOutputError):` branch mirroring Context/Evaluator (see Architecture Approach).

**Test to add (copy structure from `test_orchestrator_evaluator_schema_fail_marks_failed_notifies_owner`):**
- `test_orchestrator_generator_empty_marks_failed_notifies_owner`
  - Real `CognitiveDirector` + FakeLLM: valid Analyst comprehension; `text_responses=["", ""]` (or whitespace pair); no evaluator responses required
  - `pytest.raises(GeneratorEmptyOutputError)`
  - Turn status `failed`; `failed.error == "generador_salida_vacia"`
  - `actuator.send_count() == 0`
  - `learn.calls == []` (fail before post-success learning paths that send; existing schema-fail tests assert empty learn — match them)
  - `len(notifier.infos) == 1`; info text contains reason + turn id
  - `notifier.drafts == []`; `notifier.escalations == []`
  - No pending approval created (if approvals store is inspectable — assert empty like other fail tests; at minimum no draft notify)

**Do NOT:**
- Route empty gen through `notify_escalation` or approval queue.
- Change generic `else: mark_failed(str(exc))` semantics for non-typed errors beyond adding the new branch.
- Import telegram into cognitive.

**Verification:**
```bash
python -m pytest -q \
  tests/unit/cognitive/test_generator.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/cognitive/test_import_purity.py
```

**Full unit gate (after Task 3):**
```bash
python -m pytest -q tests/unit
```

**Done:**
- [ ] Typed orchestrator branch live
- [ ] Primary + full unit suite green
- [ ] No VIP send / no empty approval on gen fail

## Instrucciones para gsd-executor

### Patterns to copy (paths)
- Exception class: `src/diana/cognitive/exceptions.py` (`AnalystSchemaInvalidError` twin)
- Retry constant locality: `src/diana/cognitive/analyst.py` (`_MAX_ATTEMPTS = 2`) — empty-only predicate for Generator
- Orchestrator notify: `src/diana/application/turn_orchestrator.py` Evaluator/Context branches
- Director fail golds: `tests/unit/cognitive/test_director.py` schema/size fail tests
- Orchestrator notify golds: `tests/unit/application/test_turn_orchestrator.py`

### Anti-patterns (forbidden)
- Dual empty handling (Generator raise **and** Director `empty_draft` escalate left in place)
- Quality gates in Generator (length, language, “looks like JSON”, sentiment)
- Adding `regenerate` / `send` to `Decision.action` or Generator API
- Passing EvaluationProfile / “what failed” feedback into Generator messages
- Cognitive importing telegram/behavior/learning
- Broad `except Exception` that maps transport errors to empty retry
- Silent return of `" "` or placeholder draft to keep pipeline alive
- Live DeepSeek / network in unit tests

### Logging / errors / conventions
- Stable reason token **Spanish**: `generador_salida_vacia` (ops consistency with `analista_schema_invalido`, `evaluador_schema_invalido`, `contexto_excede_limite`)
- Exception class name **English**: `GeneratorEmptyOutputError`
- Notify message shape: `f"Turn {turn_id} failed: generador_salida_vacia"`
- Logger event name for notify secondary fail: `owner_notify_failed_after_generator_empty_output`
- Identifiers/comments English; no Rioplatense in code artifacts

### Commits
- Work unit = verifiable behavior per task (1 commit per task OK):
  1. `test(cognitive): generator empty retry + typed error (Anexo E.4)`
  2. `fix(cognitive): remove empty_draft escalate; fail before evaluator`
  3. `fix(application): notify owner on generador_salida_vacia`
- Conventional commits only; no AI co-author trailer

### Mock policy
- Mock only external LLM edge via `FakeLLM` text queue
- InMemory stores for orchestrator (existing helpers)
- Do **not** mock Director internals when testing Generator unit; do **not** mock Generator when asserting Director fail path — use FakeLLM at the port

### Strict TDD
- Write/flip tests first until RED, then implement GREEN, then small refactor
- Do not “implement all three modules then write tests”

### Skills / project rules
- `AGENTS.md` module purity + deterministic Director + Behavior outside cognition
- Strict TDD Mode enabled for this project

## Test commands

Primary (item):
```bash
python -m pytest -q \
  tests/unit/cognitive/test_generator.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/cognitive/test_import_purity.py
```

Full unit gate:
```bash
python -m pytest -q tests/unit
```

## Risks + Mitigation

| Risk | Mitigation in tasks |
|------|---------------------|
| Empty draft reaches approval | Task 1–2 fail closed before Decider; Task 3 asserts no draft notify / no send |
| Dual empty checks left behind | Task 2 deletes Director branch; grep `empty_draft` must be test-history only or gone |
| Retry off-by-one | Assert call count == 2 on permanent empty and on empty→success |
| Transport errors swallowed | Task 1 explicit non-empty-error propagation test |
| Regenerate creep | Explicit non-goals + L5; no Decision.action change |
| Quality judgment creep | Only `strip()` emptiness; tests forbid structured/score APIs |

## Success Criteria

- [ ] Generator answers only owner-reply draft; plain text in/out
- [ ] Empty/whitespace → at most 2 `generate` calls → `GeneratorEmptyOutputError` / `generador_salida_vacia`
- [ ] Director has **no** `empty_draft` escalate path; gen fail never stores evaluation/decision
- [ ] Orchestrator: turn `failed` + owner info notify + VIP send count 0 + no approval on gen fail
- [ ] Primary pytest commands green; full `tests/unit` green
- [ ] No-touch list respected (Behavior, Telegram, Decider matrix, Anexos C/D/F, dirty tree)
- [ ] Import purity green
- [ ] F1 `Decision.action` still only `approve|escalate`
