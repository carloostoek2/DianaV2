---
phase: quick
plan: evaluator-contract
type: auto
item: 1/1
effort: 3
stack: python>=3.12, pydantic-v2, pytest-asyncio
depends_on: analyst-contract (A.6 retry + typed fail path pattern)
source_of_truth: contrato_evaluador.md (Anexo B)
impact: .grok/agent-memory/impact-analyzer/evaluator-contract.md
---

## Objective

Align the **Evaluator runtime + input DTO + B.6 schema fail path** to `contrato_evaluador.md` (Anexo B.1–B.7): `EvaluatorInput` with full `Comprehension`, capability **names** that actually entered the Generator prompt (`included_blocks`), single schema validation retry inside Evaluator, typed fail reason `evaluador_schema_invalido`, owner notify via existing application `notify_info` — without changing English `EvaluationProfile` 7D fields, without expanding F1 `Decision.action`, without inventing a default profile on fail, and without feeding raw knowledge bodies into the Evaluator.

## Context

@`.grok/agent-memory/impact-analyzer/evaluator-contract.md`
@`contrato_evaluador.md`
@`.planning/quick/analyst-contract/PLAN.md` (structure + A.6 gold pattern)
@`AGENTS.md` (§3 module limits, §5.1 Director, §5.2 EvaluationProfile vector, anti-contamination)
@`src/diana/cognitive/models.py` (`EvaluationProfile` 7D English OK; no `EvaluatorInput` yet)
@`src/diana/cognitive/evaluator.py` (`evaluate(draft, comprehension, turn)` once; partial comprension in prompt)
@`src/diana/cognitive/analyst.py` (**gold** for `_MAX_ATTEMPTS=2` + schema-class fail mapping)
@`src/diana/cognitive/exceptions.py` (`AnalystSchemaInvalidError` only — add Evaluator twin)
@`src/diana/cognitive/context_builder.py` (`build` returns `str`; `_is_null_like` is private — export list)
@`src/diana/cognitive/director.py` (sole production `evaluate` call site ~line 145)
@`src/diana/application/turn_orchestrator.py` (typed branch only for Analyst today)
@`src/diana/application/admin_service.py` (`notify_info` thin wrapper — reuse)
@`src/diana/llm/fake.py` (`FakeLLM` structured queue + call recording)
@`tests/unit/cognitive/test_evaluator.py`
@`tests/unit/cognitive/test_context_builder.py`
@`tests/unit/cognitive/test_director.py` (`make_director` helper)
@`tests/unit/cognitive/test_evaluation_profile_invariants.py` (must stay green)
@`tests/unit/application/test_turn_orchestrator.py` (A.6 Analyst notify gold)

## Locked decisions (NON-NEGOTIABLE)

| ID | Decision |
|----|----------|
| L1 | **English model field names** for `EvaluationProfile` stay: `naturalness`, `precision`, `doctrine`, `consistency`, `safety`, `coverage`, `empathy`. Spanish Anexo B names live in docs/prompt text only. Do **not** rename profile fields. |
| L2 | **`EvaluatorInput` English identifiers** (map to Anexo B in docstring only): `draft`←borrador, `comprehension`←comprension, `included_blocks`←bloques_incluidos, `current_turn`←turno_actual. Flat DTO (no nested `context_used` object required). `extra="forbid"`. |
| L3 | **`included_blocks`** = registry capability **names** whose values passed ContextBuilder **non-null-like** filter and therefore appear as `## Knowledge: {name}` sections. Use full names (`knowledge.history`, `knowledge.policy`, …). Not short labels (`historial`). Not plan capability list. Not block body text. |
| L4 | **Null-like rules** (single source of truth with ContextBuilder): `None`; empty `list`/`dict`/`tuple`/`set`; empty/whitespace `str`. Prefer `ContextBuilder.list_included_blocks(knowledge)` sharing `_is_null_like`. |
| L5 | **API:** `async def evaluate(self, input: EvaluatorInput) -> EvaluationProfile`. Sole production caller: Director. |
| L6 | **Prompt (B.1):** single question — trust this draft? Output 7 English dims only. Forbid `score_global` / action / rewrite / mode. Include full public comprehension fields (at least intent, topics, emotion, urgency, risk — exclude `raw_llm_output` from LLM payload). |
| L7 | **Doctrine guidance (B.3):** when `"knowledge.policy" not in included_blocks`, system/user prompt instructs LLM to score **doctrine ~0.7** (neutral-high). **Prompt guidance only** — no hard-clamp of residual doctrine after LLM returns; no synthetic profile on validation fail. |
| L8 | **B.6 retry:** inside Evaluator only — on schema-class failure (`ValidationError`, `ValueError`, `TimeoutError`, type name contains `Timeout`), **exactly one** retry with the **same** messages; then raise `EvaluatorSchemaInvalidError` with stable reason `evaluador_schema_invalido`. Copy Analyst `_is_schema_class_failure` pattern. |
| L9 | **Typed error:** add `EvaluatorSchemaInvalidError` in `cognitive/exceptions.py`. `str(exc)` / `.reason` must be exactly `evaluador_schema_invalido`. **Never** invent a conservative default `EvaluationProfile` on fail. |
| L10 | **Owner notify IN this PR:** `TurnOrchestrator` except path: if `EvaluatorSchemaInvalidError`, `mark_failed(turn_id, error="evaluador_schema_invalido")` + `admin.notify_info(...)` with that reason token + turn_id. Mirror Analyst branch (notifier failures must not mask typed error). Cognitive Core **never** imports telegram. |
| L11 | **No VIP send on fail:** exception aborts before Decider returns a usable Decision for deliver; Behavior not called (existing orchestrator invariant — keep + assert `send_count()==0`). |
| L12 | **F1 actions unchanged:** `Decision.action` stays `approve \| escalate` only. No regenerate loop. Evaluator does not know mode. |
| L13 | **Anti-contamination (B.2):** Evaluator messages may contain capability **names** and draft/turn/comprehension; must **not** contain raw knowledge body text (history lines, memory payloads, policy text, examples content). |
| L14 | **Strict TDD:** tests first per task; FakeLLM / InMemory ports only; no live network. |
| L15 | **Out of scope:** Decider matrix rewrite, Telegram redesign, Learning, SPEC/REQ full rewrite, Alembic residual, F2 regenerate, B.8 schema version, doctrine hard-clamp, Spanish profile field aliases. |

### English ↔ Anexo B mapping (for docs/prompt only)

| Runtime (English) | Anexo B (Spanish) |
|-------------------|-------------------|
| `EvaluatorInput.draft` | `borrador` |
| `EvaluatorInput.comprehension` | `comprension` |
| `EvaluatorInput.included_blocks` | `contexto_usado.bloques_incluidos` |
| `EvaluatorInput.current_turn` | `turno_actual` |
| `naturalness` … `empathy` | `naturalidad` … `empatia` |
| `knowledge.policy` in `included_blocks` | short label `policy` in contract examples |

## Constraints

- Strict TDD Mode **active** — red → green → refactor per task surface.
- Cognitive Core **must not** import `diana.telegram`, `diana.behavior`, `diana.learning`, `aiogram`, `sqlalchemy`.
- Director control flow stays **100% deterministic** (fixed single retry is OK; not LLM-chosen control).
- BR-09: never collapse 7D → single score / `score_global` / mean in Evaluator or Decider path.
- Code/comments/identifiers in **English**; this PLAN is English.
- Keep import purity green: `tests/unit/cognitive/test_import_purity.py`.
- Keep evaluation profile invariants green: `tests/unit/cognitive/test_evaluation_profile_invariants.py`.
- Happy-path TAC-01 LLM call count stays **3**: Analyst structured + Generator text + Evaluator structured (retry only on fail path).

## Tasks

### Task 1: EvaluatorInput model + ContextBuilder.list_included_blocks
**type:** auto  
**Objective:** Add B.2 input DTO and a single source of truth for which knowledge capability names entered the Generator prompt (null-like parity with `build` headings).

**TDD order:**
1. Add tests in `test_models.py` + `test_context_builder.py` (red).
2. Change `models.py` + `context_builder.py` (green).
3. Do **not** change Evaluator/Director signatures yet (callers still use old API until Task 2–3).

**Files (edit):**
- `src/diana/cognitive/models.py`
- `src/diana/cognitive/context_builder.py`
- `tests/unit/cognitive/test_models.py`
- `tests/unit/cognitive/test_context_builder.py`
- Optional: `src/diana/cognitive/__init__.py` — export `EvaluatorInput` only if useful

**Model shape (exact intent):**

```python
class EvaluatorInput(BaseModel):
    """Evaluator input (Anexo B.2). English fields map to Spanish contract names in docstring."""

    model_config = ConfigDict(extra="forbid")

    draft: str
    comprehension: Comprehension
    included_blocks: list[str]
    current_turn: str
```

Docstring must map: draft←borrador, comprehension←comprension, included_blocks←bloques_incluidos, current_turn←turno_actual.

**ContextBuilder API (exact intent):**

```python
def list_included_blocks(self, knowledge: dict[str, Any | None]) -> list[str]:
    """Capability names that would appear as ## Knowledge sections in build()."""
    return [name for name, value in knowledge.items() if not _is_null_like(value)]
```

Preserve dict iteration order (insertion order). Do not sort unless tests require stable sort — prefer natural map order.

**Tests to add (must exist after task):**
- `test_evaluator_input_accepts_full_payload` — valid construction
- `test_evaluator_input_rejects_extra_fields` — `extra="forbid"`
- `test_evaluator_input_requires_all_fields` — omit any required field → `ValidationError`
- `test_list_included_blocks_matches_prompt_sections` — knowledge mix of None / `[]` / `{}` / whitespace str / real history+context; assert `list_included_blocks` == names that appear as `## Knowledge: {name}` in `build(...)` prompt
- `test_list_included_blocks_empty_when_all_null_like` — all stubs None/empty → `[]`

**Do NOT:**
- Change `EvaluationProfile` field names or validators.
- Change Decider, Decision.action, or Evaluator signature yet.
- Add nested `ContextUsed` model (flat list is locked L2).
- Pass knowledge body text through any new DTO field.

**Verification:**
```bash
python -m pytest -q \
  tests/unit/cognitive/test_models.py \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_evaluation_profile_invariants.py
```

**DoD:**
- [ ] `EvaluatorInput` exists with English fields + `extra="forbid"`
- [ ] `list_included_blocks` parity with `build` headings
- [ ] Profile invariants still green
- [ ] Commands above green

---

### Task 2: Evaluator B.1–B.3 prompt + B.6 retry + typed error
**type:** auto  
**Objective:** Evaluator answers only “should we trust this draft?” using `EvaluatorInput`, lists English 7 dims, guides doctrine ~0.7 when policy block absent, retries once on schema failure, then raises `EvaluatorSchemaInvalidError(reason="evaluador_schema_invalido")` — never invents a profile.

**TDD order:** write/extend `test_evaluator.py` red → implement `evaluator.py` + `exceptions.py` green.

**Files (create/edit):**
- `src/diana/cognitive/exceptions.py` **(edit)** — add `EvaluatorSchemaInvalidError`
- `src/diana/cognitive/evaluator.py` **(edit)**
- `tests/unit/cognitive/test_evaluator.py` **(edit)**

**`EvaluatorSchemaInvalidError` contract (mirror Analyst):**
```python
class EvaluatorSchemaInvalidError(Exception):
    reason: str = "evaluador_schema_invalido"
    def __str__(self) -> str:  # must yield "evaluador_schema_invalido"
        ...
```

Update `__all__` to export both errors.

**`Evaluator.evaluate` contract:**
```python
async def evaluate(self, input: EvaluatorInput) -> EvaluationProfile: ...
```
- Build messages: system (B.1 pure evaluator) + user content serializing:
  - `current_turn`
  - full public comprehension (exclude `raw_llm_output`)
  - `included_blocks` as names list
  - `draft`
- Call `generate_structured(..., EvaluationProfile)`.
- On schema-class failure: **retry once** same messages (`_MAX_ATTEMPTS = 2`).
- On second failure: raise `EvaluatorSchemaInvalidError` (do not return partial/default model).
- Happy path: still attach `raw_llm_output` if missing (existing behavior).
- Call counts: happy = 1 structured; fail-once-then-ok = 2; double-fail = 2 then error.

**Prompt rules (B.1 / B.3):**
- Single question: trust this draft? Score only the 7 English dims in [0,1].
- Explicitly forbid: overall score / score_global / choosing action / rewriting draft / using mode.
- **Doctrine:** if `knowledge.policy` is not in `included_blocks`, instruct doctrine ≈ 0.7 (neutral-high; do not punish missing policy stub).
- **Empathy:** use `comprehension.emotion`.
- **Precision/coverage:** compare draft to `current_turn` and only facts implied by included **capability names** (not external inventing).
- **Forbidden in system prompt:** instructions that decide approve/escalate, set thresholds, or request regeneration.

**Copy Analyst schema-fail helper pattern** (`_SCHEMA_FAIL_TYPES`, `_is_schema_class_failure`) — either duplicate small private helpers in `evaluator.py` or extract shared helper in a tiny internal module. Prefer **duplicate in evaluator.py** for minimal blast radius (same as current Analyst locality) unless a 5-line shared util already exists.

**Tests (must add/update):**
- `test_evaluate_accepts_evaluator_input` — DTO signature; returns `EvaluationProfile`
- `test_evaluate_messages_include_draft_and_turno_and_emotion` — user messages contain draft, current_turn text, and emotion (or full comprehension fields)
- `test_evaluate_messages_include_bloques_names_not_knowledge_bodies` — `included_blocks=["knowledge.history"]`; assert name present; assert a planted body marker string (e.g. `"SECRET-HISTORY-BODY"`) is **absent** even if test does not pass bodies (assert only names appear; optional negative assert against known body patterns)
- `test_evaluate_system_prompt_doctrine_guidance_when_policy_absent` — when `"knowledge.policy"` not in list, system and/or user content mentions doctrine guidance (~0.7 / neutral-high / policy absent). Keep assertion stable (substring tokens: `"0.7"` and `"doctrine"` or `"knowledge.policy"`).
- `test_evaluate_retries_once_on_validation_error` — incomplete dict then valid profile → OK, `len(calls)==2`, same messages
- `test_evaluate_double_fail_raises_evaluador_schema_invalido` — two incompletes → typed error, `str(exc)=="evaluador_schema_invalido"`, `len(calls)==2`
- Update `test_evaluate_incomplete_dims_raise_validation_error` → after exhausted retries expect **typed** error (not bare `ValidationError` to caller)
- Keep `test_evaluator_field_names_are_english_only`
- Optional gold: ValueError / TimeoutError schema-class mapping (mirror analyst tests if cheap)

**Helper for tests:**
```python
def _input(**overrides) -> EvaluatorInput:
    data = dict(
        draft="draft text",
        comprehension=_comprehension(),
        included_blocks=["knowledge.history"],
        current_turn="hola",
    )
    data.update(overrides)
    return EvaluatorInput(**data)
```

**Do NOT:**
- Hard-clamp `doctrine` after LLM returns.
- Invent default profile on fail.
- Import application/telegram.
- Pass raw knowledge dict into Evaluator.

**Verification:**
```bash
python -m pytest -q \
  tests/unit/cognitive/test_evaluator.py \
  tests/unit/cognitive/test_models.py \
  tests/unit/cognitive/test_evaluation_profile_invariants.py
```

**DoD:**
- [ ] Signature uses `EvaluatorInput`
- [ ] Exactly one retry then typed error
- [ ] Prompt has doctrine guidance when policy absent
- [ ] Messages include draft + turn + emotion; block names without bodies
- [ ] English dims only; no score_global
- [ ] Command above green

---

### Task 3: Director wiring — included_blocks + EvaluatorInput
**type:** auto  
**Objective:** Director computes `included_blocks` from the same retrieved knowledge map used for `build`, calls `evaluate(EvaluatorInput(...))`, never invents evaluation on schema fail, does not advance to a stored Decision after Evaluator failure.

**TDD order:** extend `test_director.py` red → `director.py` green.

**Files (edit):**
- `src/diana/cognitive/director.py`
- `tests/unit/cognitive/test_director.py`
- (if needed) purity test — should stay green without edits

**Pipeline change (EVALUATING step, exact intent):**
```python
blocks = self._context_builder.list_included_blocks(retrieved)
prompt = self._context_builder.build(...)  # existing; order OK if both use same map
# Prefer: compute blocks from same `retrieved` adjacent to build
evaluation = await self._evaluator.evaluate(
    EvaluatorInput(
        draft=draft,
        comprehension=comprehension,
        included_blocks=blocks,
        current_turn=turn.text,
    )
)
await self._store(turn_id, "evaluation", evaluation)
```

Notes:
- `list_included_blocks` may run before or after `build`; both must use the **same** `retrieved` dict.
- On `EvaluatorSchemaInvalidError`: outer `handle_turn` already transitions `FAILED` + re-raises. Ensure **no** `decision` trace is stored after fail. Do **not** store a fabricated evaluation.
- Empty-draft escalate path still requires a **valid** evaluation first (current order: evaluate then empty-draft check) — keep that order; schema fail never reaches empty-draft branch with fake scores.

**Tests (must add):**
- `test_director_passes_included_blocks_to_evaluator` — seed history so registry returns non-null `knowledge.history` (and typically `knowledge.context`); after `handle_turn`, inspect FakeLLM **Evaluator** structured call messages for `knowledge.history` name; assert no accidental dump of unrelated policy body (policy still null in F1).
- `test_director_evaluator_schema_fail_no_decision_trace` — FakeLLM queue: valid Comprehension + valid draft text + **two** invalid EvaluationProfile payloads → raises `EvaluatorSchemaInvalidError`; trace has no `decision` key (or no decision stored); status includes FAILED; optional: assert no fabricated evaluation store (or evaluation absent).
- Update any direct `evaluate(...)` assumptions if director tests monkeypatch Evaluator.
- Keep `test_tac01_llm_calls_only_analyst_generator_evaluator` green (happy path still 3 calls).

**Do NOT:**
- Change Decider thresholds or F1 matrix.
- Expand `Decision.action`.
- Import SQL/telegram into cognitive.
- Compute included blocks from plan.capabilities without null-like filter.

**Verification:**
```bash
python -m pytest -q \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_evaluator.py \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_import_purity.py
```

**DoD:**
- [ ] Director builds `EvaluatorInput` with null-like-filtered block names
- [ ] Schema fail stops before Decision store; typed error propagates
- [ ] TAC-01 happy path call count still 3
- [ ] Commands above green

---

### Task 4: Orchestrator B.6 notify + mark_failed reason
**type:** auto  
**Objective:** On Evaluator schema failure, turn is `failed` with error `evaluador_schema_invalido`, owner is notified via existing `AdminService.notify_info`, VIP receives nothing.

**TDD order:** add orchestrator test red → minimal `turn_orchestrator.py` change green.

**Files (edit):**
- `src/diana/application/turn_orchestrator.py`
- `tests/unit/application/test_turn_orchestrator.py`

**Orchestrator except block (exact intent — extend Analyst branch):**
```python
except Exception as exc:
    if isinstance(exc, AnalystSchemaInvalidError):
        error = "analista_schema_invalido"
        await self._coordinator.mark_failed(turn_id, error=error)
        try:
            await self._admin.notify_info(
                f"Turn {turn_id} failed: analista_schema_invalido",
                chat_id=incoming.chat_id,
            )
        except Exception:
            logger.exception("owner_notify_failed_after_analyst_schema_invalid", ...)
    elif isinstance(exc, EvaluatorSchemaInvalidError):
        error = "evaluador_schema_invalido"
        await self._coordinator.mark_failed(turn_id, error=error)
        try:
            await self._admin.notify_info(
                f"Turn {turn_id} failed: evaluador_schema_invalido",
                chat_id=incoming.chat_id,
            )
        except Exception:
            logger.exception("owner_notify_failed_after_evaluator_schema_invalid", ...)
    else:
        await self._coordinator.mark_failed(turn_id, error=str(exc))
    logger.exception("director_failed", ...)
    raise
```

Imports: add `EvaluatorSchemaInvalidError` next to Analyst import from `diana.cognitive.exceptions`.

**Message content:** must include reason token `evaluador_schema_invalido` and turn_id (mirror Analyst format).

**Test (must add):**
- `test_orchestrator_evaluator_schema_fail_marks_failed_notifies_owner`  
  - Mirror Analyst A.6 test setup (real Director + FakeLLM + FakeOwnerNotifier + FakeTelegramActuator).  
  - FakeLLM structured queue: **valid** Comprehension, then **two invalid** EvaluationProfile dicts (missing dims); text queue: one valid draft string.  
  - Assert `pytest.raises(EvaluatorSchemaInvalidError)`.  
  - Assert turn status `failed`, `error == "evaluador_schema_invalido"`.  
  - Assert `notifier.infos` ≥1 contains `evaluador_schema_invalido` and turn_id.  
  - Assert `actuator.send_count()==0`.  
  - Assert learning not invoked for success path (existing pattern: no post-turn success deliver).  
  - Assert exception re-raised (keep re-raise).

**Do NOT:**
- Call Behavior on fail.
- Import cognitive exceptions into telegram layer.
- Change happy-path approve/escalate flow.
- Redesign AdminService (reuse `notify_info`).

**Verification:**
```bash
python -m pytest -q \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_evaluator.py \
  tests/unit/cognitive/test_import_purity.py
```

**Full unit gate (required before handoff done):**
```bash
python -m pytest -q tests/unit
```

**DoD:**
- [ ] Fail reason stored as `evaluador_schema_invalido`
- [ ] Owner notified once on Evaluator schema fail
- [ ] VIP send count stays 0
- [ ] Analyst A.6 path still green
- [ ] Full `tests/unit` green

---

## Instrucciones para gsd-executor

### Patterns to copy
- **Analyst A.6 retry:** copy control flow from `src/diana/cognitive/analyst.py` (`_MAX_ATTEMPTS=2`, `_is_schema_class_failure`, typed error after loop).
- **Typed error twin:** copy structure of `AnalystSchemaInvalidError` → `EvaluatorSchemaInvalidError` in `exceptions.py`.
- **FakeLLM:** queue `structured_responses` with full `EvaluationProfile` or incomplete dicts; assert `llm.calls` for method names and message content (see `test_evaluator.py`, `test_analyst.py`).
- **Director test factory:** `make_director` in `test_director.py` — no new DI ports required (ContextBuilder already injected).
- **Orchestrator notify gold:** copy `test_orchestrator_analyst_schema_fail_marks_failed_notifies_owner` and swap error type / FakeLLM queue positions (valid Comprehension first, then two bad profiles + text draft).
- **Owner notify:** `AdminService.notify_info` + `FakeOwnerNotifier.infos` from `application/memory.py`.
- **Null-like parity:** assert `list_included_blocks` against headings produced by existing `build` tests in `test_context_builder.py`.

### Anti-patterns (reject if you introduce them)
- Default / synthetic `EvaluationProfile` on schema fail (low safety “safe” profile).
- Hard-clamping `doctrine` to 0.7 in Python after LLM returns (locked L7 = prompt only).
- Passing raw `retrieved` knowledge bodies into Evaluator messages.
- Computing `included_blocks` from full plan list without null-like filter.
- Renaming EvaluationProfile fields to Spanish.
- Expanding `Decision.action` or adding regenerate.
- Cognitive importing `diana.telegram` / `diana.behavior` / aiogram.
- Infinite or multi-retry loops (max **1** retry = **2** LLM structured calls for Evaluator).
- Collapsing 7D to mean / score_global anywhere in this change.
- Live DeepSeek / real network in unit tests.
- Co-Authored-By / AI attribution in commits.

### Strict TDD sequence (mandatory)
1. Task 1 tests → models + list_included_blocks  
2. Task 2 tests → evaluator + exception  
3. Task 3 tests → director wiring  
4. Task 4 tests → orchestrator notify  
5. Full unit gate  

Do not implement production code for a task before its new failing tests exist.

### AGENTS.md invariants to preserve
- Director deterministic sequencer.
- Evaluator single question only (profile, not action).
- EvaluationProfile remains a 7D vector (BR-09).
- Behavior outside cognition; Learning post-turn only.
- Anti-contamination: Evaluator sees capability **names**, not memory/policy bodies.
- Intermediate objects persisted when valid; fail path does not invent evaluation.

### Commits (suggested)
1. `test(cognitive): lock EvaluatorInput and included_blocks null-like parity`
2. `feat(cognitive): EvaluatorInput, schema retry, EvaluatorSchemaInvalidError`
3. `feat(cognitive): Director passes included_blocks to Evaluator`
4. `feat(application): notify owner on evaluador_schema_invalido`

Conventional commits only; no AI attribution trailers.

### Logging
Append progress to `.planning/quick/gsd-executor-evaluator-contract.log` with task start/end + pytest results. Planner log is `.planning/quick/gsd-planner-evaluator-contract.log`.

## Test commands

### Primary slice (evaluator contract)
```bash
python -m pytest -q \
  tests/unit/cognitive/test_models.py \
  tests/unit/cognitive/test_evaluation_profile_invariants.py \
  tests/unit/cognitive/test_evaluator.py \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_decider.py \
  tests/unit/cognitive/test_import_purity.py
```

### Application fail path + LLM doubles
```bash
python -m pytest -q \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/llm/test_fake_llm.py
```

### Full unit gate (required before handoff done)
```bash
python -m pytest -q tests/unit
```

### Optional acceptance (low impact; FakeDirector)
```bash
python -m pytest -q tests/unit/acceptance/test_tac_mvp_f1.py
```

### Sensitive / gold re-runs after change
```bash
python -m pytest -q \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_evaluation_profile_invariants.py \
  tests/unit/application/test_turn_orchestrator.py
```

## Risks + Mitigation

| Risk | Level | Mitigation |
|------|-------|------------|
| Inventing default EvaluationProfile on schema fail (B.6) | Critical | Raise typed error after 2 attempts; assert no Decision; orchestrator `send_count==0` |
| Raw knowledge bodies into Evaluator (B.2) | Critical | Names only via `included_blocks`; unit assert bodies absent |
| `included_blocks` drift vs prompt headings | Medium | Single `list_included_blocks` sharing `_is_null_like` with `build` |
| doctrine hard-clamp vs prompt guidance | Medium | Locked L7: prompt only; residual hard-clamp if calibration fails later |
| Breaking `evaluate` signature | Medium | One production call site (Director) + unit tests; TDD Task 2→3 |
| Orchestrator loses stable fail reason | Medium | Typed `isinstance` branch stores exact `evaluador_schema_invalido` |
| TAC-01 call count regression | Medium | Happy path still 3 LLM ops; retry isolated in fail tests |
| Fixture / call-site blast from signature change | Low–Med | Update only evaluator + director + orchestrator tests; profile fixtures elsewhere unchanged |
| SPEC/REQ docs lag Anexo B | Low | Out of scope residual |

## Success Criteria

- [ ] `EvaluatorInput` exists (English fields) with full comprehension + included_blocks + current_turn + draft
- [ ] `ContextBuilder.list_included_blocks` matches non-null-like `## Knowledge` sections
- [ ] `Evaluator.evaluate(EvaluatorInput)` retries once then raises `evaluador_schema_invalido`
- [ ] Prompt includes doctrine ~0.7 guidance when `knowledge.policy` absent; no hard-clamp
- [ ] Messages include draft/turn/emotion and block **names**; no knowledge bodies
- [ ] Director wires blocks from same retrieved map; fail path stores no Decision / no synthetic evaluation
- [ ] On schema fail: turn failed, owner notified, VIP send count 0
- [ ] `EvaluationProfile` English 7D unchanged; invariants green
- [ ] F1 `Decision.action` still only `approve|escalate`
- [ ] Cognitive import purity green
- [ ] `python -m pytest -q tests/unit` green
- [ ] No Behavior/Learning/Telegram redesign

## Residuals / out of scope (do not touch)

1. **Doctrine hard-clamp to 0.7** when policy absent — only if prompt guidance proves unreliable (REQ-EVAL calibration).
2. **B.8 `evaluacion_schema_version`** when dimensions change.
3. **Spanish ↔ English field alias layer** for mis-emitting providers.
4. **SPEC.md / REQUERIMIENTOS.md** full sync to Anexo B wording.
5. **F2 regenerate** evaluates from scratch (B.7) — document when F2 lands.
6. **Decider threshold config from `system_config`** — AGENTS.md 6.2; separate item.
7. **Trace snapshot for `included_blocks`** (reconstructability) — optional later.
8. **Telegram handlers / Behavior Engine / Learning / Staging**.
9. **Alembic / unrelated dirty-tree** `turns.error` residual work (column already present).
10. **Decider matrix rewrite** / expanding F1 actions.

## Self-check checklist for executor

Before marking the item done, confirm:

- [ ] TDD order followed per task (failing test before production edit)
- [ ] L1–L15 locked decisions respected (especially L7 prompt-only doctrine, L9 no default profile, L13 names-only)
- [ ] `EvaluatorSchemaInvalidError.reason == "evaluador_schema_invalido"`
- [ ] Happy path TAC-01 still 3 LLM calls
- [ ] Analyst A.6 orchestrator path still green
- [ ] Import purity green
- [ ] Evaluation profile invariants green
- [ ] Full `python -m pytest -q tests/unit` green
- [ ] Conventional commits only; no AI attribution
- [ ] No production scope creep into Decider/Telegram/Learning/SPEC
