# Impact Analysis: Align Evaluator contract to Anexo B (`contrato_evaluador.md`)

**Date:** 2026-07-23  
**Change:** Align Evaluator runtime + input DTO + B.6 schema retry/fail path to Anexo B (B.1–B.8)  
**Analysis only** — no implementación  
**Source of truth:** `/home/ubuntu/repos/DianaV2/contrato_evaluador.md` (Anexo B)  
**Pattern reference:** `.planning/quick/analyst-contract/PLAN.md` + `src/diana/cognitive/analyst.py` (A.6 retry)

---

## Executive Summary

The Evaluator today is a thin F1 component: `evaluate(draft, comprehension, turn)` calls `generate_structured(..., EvaluationProfile)` once, with a short system prompt and a user payload that includes VIP message + partial comprehension (`intent`/`risk`/`urgency` only) + draft. **`EvaluationProfile` already matches B.3 English 7D vector** (finite, required, no aggregate score) and the Decider correctly consumes the vector (safety gate only). Composition wires `Evaluator(provider)` without extra ports.

Anexo B requires more than a signature tweak:

1. **B.2 `EvaluadorInput`** — full `Comprehension`, `contexto_usado.bloques_incluidos` (capability **names** that actually entered the Generator prompt, not block text), and `turno_actual`. Explicitly **no** prior drafts and **no** raw memory/policy content.
2. **B.3 doctrine guidance** — when `policy` is not among included blocks (F1 policy stub is always null → typically absent), Evaluator should score doctrine neutral-high (~0.7) via **prompt guidance**, not a system-invented profile on failure.
3. **B.6** — strict validation of all 7 dims; **exactly one retry** on schema-class failure; then typed `EvaluatorSchemaInvalidError` / reason `evaluador_schema_invalido`; turn failed + owner notify; **no conservative default profile**.
4. **B.1 / B.7** — still profile-only; no action/mode/regenerate (F1 actions stay `approve|escalate`).

**Global risk: medium.** Primary blast radius is **cognitive pipeline wiring** (Director + ContextBuilder must export included blocks) and **tests** for Evaluator/Director/Orchestrator. Decider, Admin persistence of evaluation JSON, and F1 Decision shape are **low impact** if `EvaluationProfile` field names stay English. Sensitive systems: deterministic Director control flow, anti-contamination (Evaluator must not see raw knowledge), fail-path durability (`turns.error` + owner notify without VIP send), and BR-09 (never collapse 7D → single score).

**Scope is valid and tight.** No re-partition required. Mirror the completed analyst-contract slice (models DTO → component retry → Director wiring → orchestrator notify). Do **not** mix unrelated dirty-tree work (`turns.error` residual / alembic 002) unless the fail column is already present (it is — used by `analista_schema_invalido`).

---

## Gap verification (contract vs code)

| Gap | Contract (Anexo B) | Current code | Status |
|-----|--------------------|--------------|--------|
| B.1 single question | Profile only; no action/rewrite | `EvaluationProfile` only; prompt says “Do not choose the system action” | **OK** (tighten wording to “trust this draft?”) |
| B.2 input DTO | `EvaluadorInput { borrador, comprension, contexto_usado.bloques_incluidos, turno_actual }` | `evaluate(draft, comprehension, turn)` — no blocks list | **CONFIRMED gap** |
| B.2 full comprehension | Full Comprehension object (incl. emotion for empathy) | Prompt uses only intent/risk/urgency | **CONFIRMED gap** |
| B.2 no raw knowledge | Names only, not block text | Currently does **not** pass knowledge text (good), but also does not pass names | **PARTIAL** — add names only |
| B.3 7 English dims 0..1 | naturalness…empathy; no score_global | `EvaluationProfile` + finite validators + invariant tests | **OK** |
| B.3 doctrine neutral-high | ~0.7 when policy not in `bloques_incluidos` | Not mentioned in `_SYSTEM` / user prompt | **CONFIRMED gap** (prompt/doc preferred) |
| B.6 retry | 1 retry then fail | Single `generate_structured`; `ValidationError` bubbles | **CONFIRMED gap** |
| B.6 no default profile | Never invent conservative profile | No default profile today (fail open) | **OK** — keep; do not add |
| B.6 owner notify + turn failed | Notify + `Turn.status=failed` | Orchestrator handles **Analyst** typed error only | **CONFIRMED gap** for Evaluator |
| B.7 no decide / no mode | Decider owns thresholds; Evaluator ignores mode | Evaluator OK; Decider has matrix | **OK** |
| B.7 regenerate from scratch | Each draft evaluated clean | F1 has no regenerate | **N/A F1 — do not add** |
| B.8 schema version | Optional future field | Not present | **Out of scope** unless natural (prefer skip) |
| F1 Decision.action | approve\|escalate | Already restricted | **OK — do not expand** |

### Naming note (capability short names vs registry)

Contract examples use short labels (`historial`, `examples`, `policy`). Runtime registry + ContextBuilder use:

- `knowledge.history`, `knowledge.context`, `knowledge.memory`, `knowledge.policy`, `knowledge.examples`, `knowledge.schedule`, `knowledge.profile`

**Locked assumption:** `bloques_incluidos` = names of capabilities that were **non-null-like** and **actually entered** the Generator prompt — **mirror ContextBuilder null-like rules**. Therefore store/pass **registry names** as they appear in `## Knowledge: {name}` headings (e.g. `knowledge.policy`), and treat “policy present” as `"knowledge.policy" in bloques_incluidos`. Document short-name mapping only in comments/docs, not as a second vocabulary in runtime.

### Null-like rules (source of truth for included blocks)

From `context_builder.py` `_is_null_like`:

- `None`
- empty `list` / `dict` / `tuple` / `set`
- empty/whitespace `str`

F1 stubs (memory/policy/examples/schedule/profile) return `None` → never included. REAL history/context may be empty → also omitted. **Included set is a subset of retrieved keys**, not the full plan capability list.

---

## Consumers / Call Sites Map

### Production — produce / validate EvaluationProfile

| Location | Role |
|----------|------|
| `src/diana/cognitive/models.py:149-172` | `EvaluationProfile` 7D English + finite validators; optional `raw_llm_output` |
| `src/diana/cognitive/evaluator.py:16-44` | Prompt + `evaluate(draft, comprehension, turn)` → one `generate_structured` |
| `src/diana/llm/deepseek.py` | Structured JSON → `model_validate(EvaluationProfile)` (shared path) |
| `src/diana/llm/fake.py:54-80` | Test double; dict path raises `ValidationError` on incomplete dims |

### Production — call Evaluator / build context

| Location | Behavior today | Needed for B.2 |
|----------|----------------|----------------|
| `src/diana/cognitive/director.py:131-146` | `build(...)` → prompt str only; `evaluate(draft, comprehension, turn)` | Compute `bloques_incluidos` from same knowledge map; call `evaluate(EvaluatorInput(...))` |
| `src/diana/cognitive/context_builder.py:19-56` | Returns `str` only; null-like omit sections | **Export** included block names (method or dual return) — single source of truth |
| `src/diana/composition.py:182` | `Evaluator(provider)` | No extra DI if blocks computed in Director/ContextBuilder |

### Production — consume EvaluationProfile (do not break)

| Location | Fields used | Notes |
|----------|-------------|-------|
| `src/diana/cognitive/decider.py:23-50` | `evaluation.safety` (+ thresholds) | Vector preserved; no mean |
| `src/diana/cognitive/director.py:148-165` | whole profile into `Decision` | Empty-draft escalate still attaches evaluation |
| `src/diana/cognitive/ports.py:22-40` | TRACE key `"evaluation"` | JSONB snapshot via `to_jsonable` |
| `src/diana/application/admin_service.py:37-45, 103-115` | all 7 dims display summary + dump | `_eval_summary` is display-only |
| `src/diana/application/ports.py:46, 77-78` | `evaluation` dict on approval/notify DTOs | No schema change if field names stable |
| `src/diana/infrastructure/db/models.py:124, 191` | JSONB `evaluation` columns | No migration if keys stay English |
| `src/diana/infrastructure/db/repositories/approvals.py` | pass-through evaluation dict | Low |
| `src/diana/telegram/notifier.py:34-35` | `evaluation_summary` string | Low |
| `src/diana/application/recovery_startup.py:107-108` | re-notify pending approvals | Low |

### Production — failure / notify path (B.6 related)

| Location | Behavior |
|----------|----------|
| `src/diana/cognitive/exceptions.py` | Only `AnalystSchemaInvalidError` today — **add** `EvaluatorSchemaInvalidError` |
| `src/diana/cognitive/director.py:100-104` | Any exception → `FAILED` status sink + re-raise; partial traces remain |
| `src/diana/application/turn_orchestrator.py:106-135` | Typed branch only for Analyst; else `mark_failed(str(exc))` | **Extend** for Evaluator reason + `notify_info` |
| `turns.error` column | Durable fail reason (already used for `analista_schema_invalido`) | Reuse — no new migration required for reason string |

### Tests — high impact

| File | Impact |
|------|--------|
| `tests/unit/cognitive/test_evaluator.py` | **HIGH** — signature, retry, input payload, blocks, doctrine prompt, typed error |
| `tests/unit/cognitive/test_director.py` | **HIGH** — evaluate call + bloques derivation + fail before Decider / no eval invent |
| `tests/unit/cognitive/test_context_builder.py` | **MED** — new API for included blocks if exported here |
| `tests/unit/application/test_turn_orchestrator.py` | **HIGH** — B.6 notify + `evaluador_schema_invalido` + `send_count==0` |
| `tests/unit/cognitive/test_models.py` | **MED** — `EvaluatorInput` construction/validation |
| `tests/unit/cognitive/test_evaluation_profile_invariants.py` | **LOW** — keep green; no aggregate score |

### Tests — low impact (construct EvaluationProfile only)

| File | Notes |
|------|-------|
| `tests/unit/cognitive/test_decider.py` | Profile fixture only |
| `tests/unit/application/test_admin_service.py` | Profile fixture |
| `tests/unit/application/test_admin_owner_escalate.py` | Profile fixture |
| `tests/unit/telegram/test_callbacks.py` | Profile fixture |
| `tests/unit/acceptance/test_tac_mvp_f1.py` | FakeDirector + profile; no real Evaluator |
| `tests/unit/cognitive/test_import_purity.py` | Must stay green (no telegram/behavior imports) |
| `tests/unit/llm/test_fake_llm.py` / `test_deepseek_provider.py` | Shared structured path; only if schema behavior changes |

### Call-site line map (evaluate)

| Path | Lines | Note |
|------|-------|------|
| `evaluator.py` | 20-44 | definition |
| `director.py` | 145 | **sole production call site** |
| `test_evaluator.py` | 55, 69, 75 | unit calls |
| `composition.py` | 182 | constructor only |
| `test_director.py` / `test_turn_orchestrator.py` | make_director / wiring | indirect via pipeline |

---

## Risks

### Critical

1. **Inventing a default EvaluationProfile on schema fail (B.6)**  
   - **Risk:** Tempting “safe” profile (low safety) so Decider still runs — would fabricate business inputs.  
   - **Mitigation:** After 2 failed attempts, raise `EvaluatorSchemaInvalidError`; never return a synthetic profile. Orchestrator marks failed + notifies; Behavior not called. Assert `send_count()==0`.

2. **Anti-contamination / oversharing into Evaluator (B.2)**  
   - **Risk:** Passing full `retrieved` knowledge blobs (memory/policy/examples text) into Evaluator messages “for better scoring”.  
   - **Mitigation:** Input carries **capability name list only**. Unit test: messages must not contain knowledge body text when retrieved map has history/memory content; may contain names like `knowledge.history`.

### Medium

3. **Breaking API: `evaluate` signature**  
   - **Risk:** `evaluate(draft, comprehension, turn)` → `evaluate(input: EvaluatorInput)` breaks all call sites.  
   - **Mitigation:** Single production call site (Director) + unit tests; no public package consumers outside cognitive. Prefer one DTO (mirror `AnalystInput`) rather than kwargs expansion.

4. **`bloques_incluidos` drift vs prompt contents**  
   - **Risk:** Director builds list from plan capabilities while ContextBuilder omits null-like values → Evaluator thinks policy was present when it was not (or reverse).  
   - **Mitigation:** Single function shared with ContextBuilder (`_is_null_like` / `list_included_blocks(knowledge)`). Prefer ContextBuilder owns both prompt sections and included names.

5. **doctrine 0.7 hard-clamp vs prompt guidance**  
   - **Risk:** Post-LLM clamp when policy absent forces 0.7 and hides real model output; prompt-only may still return 0.2.  
   - **Mitigation (locked):** Prefer **prompt guidance** + docs; flag hard-clamp as residual/MVP+ calibration. Do not invent profile on fail; optional soft post-adjust only if product later requires determinism.

6. **Orchestrator fail reason typing**  
   - **Risk:** Generic `str(exc)` loses stable `evaluador_schema_invalido` for ops triage.  
   - **Mitigation:** Mirror Analyst branch: `isinstance(exc, EvaluatorSchemaInvalidError)` → fixed error string + `notify_info` containing token.

7. **TAC-01 LLM call counts**  
   - **Risk:** Retry doubles Evaluator structured calls only on fail path; happy path must stay Analyst(1)+Generator(1)+Evaluator(1).  
   - **Mitigation:** Keep happy-path assert; add dedicated retry tests with FakeLLM queues.

8. **Identifier language (English vs Spanish DTO fields)**  
   - **Risk:** Contract Spanish (`borrador`, `bloques_incluidos`) vs locked “English identifiers”; Analyst already used Spanish for `AnalystInput` fields.  
   - **Mitigation:** Follow locked assumption for this pool: English model identifiers (`EvaluatorInput`, `draft`, `comprehension`, `included_blocks` / nested `context_used`, `current_turn_text`) with Spanish allowed only in prompt text. Document mapping to Anexo B names in model docstring. Alternative (if planner prefers Analyst parity): Spanish field names like Analyst — pick **one** in PLAN and do not mix.

### Low

9. **Admin `_eval_summary` display** — unaffected if dims stay English.  
10. **B.8 `evaluacion_schema_version`** — skip unless adding version is free; residual.  
11. **Emotion in Evaluator prompt** — adding full comprehension (incl. emotion) improves empathy scoring; may slightly enlarge prompt; no Decider change.  
12. **Docs drift** — SPEC/REQ may lag Anexo B; out of scope full rewrite.

---

## Sensitive systems (AGENTS.md)

| System | Why sensitive | Rule for this change |
|--------|---------------|----------------------|
| Cognitive Director | Deterministic sequencer | Fixed single retry is OK; no LLM-chosen control |
| Evaluator single question | B.1 / BR-09 | Profile only; no action/mode |
| EvaluationProfile vector | Decider safety gate | No mean/score_global; English 7 dims |
| Anti-contamination | BR-15 / B.2 | Names only; no raw memory/policy |
| Behavior Engine | Outside cognition | Fail path must not deliver |
| Learning | Post-turn only | Do not touch |
| Import purity | Cognitive isolation | No telegram/application imports inside evaluator |

---

## Affected Tests

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

### Application fail path + wiring

```bash
python -m pytest -q \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/llm/test_fake_llm.py
```

### Full unit gate (required before handoff done)

```bash
python -m pytest -q tests/unit
```

### Gold / sensitive re-runs after change

```bash
python -m pytest -q \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_evaluation_profile_invariants.py \
  tests/unit/application/test_turn_orchestrator.py
```

### Optional acceptance (low impact; FakeDirector)

```bash
python -m pytest -q tests/unit/acceptance/test_tac_mvp_f1.py
```

### Tests to add (planner must require)

**`test_evaluator.py`**
- `test_evaluate_accepts_evaluator_input` — DTO signature
- `test_evaluate_messages_include_draft_and_turno_and_emotion` — full comprension fields (at least emotion/intent)
- `test_evaluate_messages_include_bloques_names_not_knowledge_bodies`
- `test_evaluate_system_prompt_doctrine_neutral_when_policy_absent` (or assert guidance text when `knowledge.policy` not in list)
- `test_evaluate_retries_once_on_validation_error` — invalid then valid → 2 calls
- `test_evaluate_double_fail_raises_evaluador_schema_invalido`
- Update incomplete-dims test: after exhausted retries → typed error (not bare `ValidationError` to caller)
- Keep English field-name guard

**`test_context_builder.py`** (if export API)
- `test_list_included_blocks_matches_prompt_sections` — null-like parity with headings

**`test_director.py`**
- `test_director_passes_included_blocks_to_evaluator` — seed non-null history; assert names in Evaluator messages
- `test_director_evaluator_schema_fail_no_decision_trace` — double invalid eval → typed error; no decision stored; optional: evaluation not stored as fabricated

**`test_turn_orchestrator.py`**
- `test_orchestrator_evaluator_schema_fail_marks_failed_notifies_owner` — mirror Analyst A.6 test with FakeLLM structured queue: valid Comprehension + valid text draft + two bad profiles

**`test_models.py`**
- `EvaluatorInput` required fields / extra forbid

---

## Files Map

### Edit

| File | Change |
|------|--------|
| `src/diana/cognitive/models.py` | Add `EvaluatorInput` (+ optional nested `ContextUsed` with `included_blocks: list[str]`) |
| `src/diana/cognitive/evaluator.py` | New signature; B.1/B.3 prompt; full input serialization; A.6-style retry; no default profile |
| `src/diana/cognitive/exceptions.py` | Add `EvaluatorSchemaInvalidError` (`reason="evaluador_schema_invalido"`) |
| `src/diana/cognitive/context_builder.py` | Export included block names using existing `_is_null_like` (recommended) |
| `src/diana/cognitive/director.py` | Build `EvaluatorInput`; pass blocks; re-raise evaluator schema error without inventing profile |
| `src/diana/application/turn_orchestrator.py` | Typed fail branch + owner `notify_info` for Evaluator (mirror Analyst) |
| `tests/unit/cognitive/test_evaluator.py` | Signature + retry + purity + doctrine guidance |
| `tests/unit/cognitive/test_context_builder.py` | Included-blocks parity |
| `tests/unit/cognitive/test_director.py` | Wiring + fail path |
| `tests/unit/cognitive/test_models.py` | EvaluatorInput |
| `tests/unit/application/test_turn_orchestrator.py` | B.6 notify path |

### Create

| File | Change |
|------|--------|
| (none required) | Prefer co-locate exception in existing `exceptions.py` |

### Optional / low priority edit

| File | Change |
|------|--------|
| `src/diana/cognitive/__init__.py` | Export `EvaluatorInput` / error only if useful |
| `README.md` | One-line Evaluator contract note — residual docs |

### No touch

- `decider.py` thresholds / F1 matrix (unless tests only)
- `Decision.action` Literal / F2 regenerate
- Behavior Engine, Learning, Telegram handlers redesign
- Retrievers, registry capability names
- Alembic / `turns.error` residual unless already broken (column present)
- Full SPEC/REQUERIMIENTOS rewrite
- Unrelated dirty tree work

---

## Recommended design (for planner — not implementation)

### DTO (English identifiers — locked)

```python
class EvaluatorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft: str                          # B.2 borrador
    comprehension: Comprehension        # B.2 comprension (full)
    included_blocks: list[str]          # B.2 contexto_usado.bloques_incluidos
    current_turn: str                   # B.2 turno_actual
```

Docstring maps English → Anexo B Spanish names.

### API

```python
async def evaluate(self, input: EvaluatorInput) -> EvaluationProfile: ...
```

### Included blocks helper (ContextBuilder)

```python
def list_included_blocks(self, knowledge: dict[str, Any | None]) -> list[str]:
    return [name for name, value in knowledge.items() if not _is_null_like(value)]
```

Director:

```python
blocks = self._context_builder.list_included_blocks(retrieved)
prompt = self._context_builder.build(...)
evaluation = await self._evaluator.evaluate(
    EvaluatorInput(
        draft=draft,
        comprehension=comprehension,
        included_blocks=blocks,
        current_turn=turn.text,
    )
)
```

### Retry (copy Analyst)

- `_MAX_ATTEMPTS = 2`
- Catch schema-class failures: `ValidationError`, `ValueError`, `TimeoutError`, name contains `Timeout`
- Second failure → `EvaluatorSchemaInvalidError()`  
- Happy path: still attach `raw_llm_output` if missing

### Prompt (B.1 / B.3)

- Single question: trust this draft? Output 7 English dims only.
- List closed field names; forbid score_global / action / rewrite.
- Include in user content: `current_turn`, serialized comprehension (all public fields; exclude or omit `raw_llm_output`), `included_blocks`, `draft`.
- Doctrine: if `knowledge.policy` not in `included_blocks`, score doctrine neutral-high ~0.7 (do not punish Generator for missing policy stub).
- Empathy: use comprehension.emotion.
- Precision/coverage: compare draft to current_turn and only facts implied by included **capabilities** (not external inventing).

### Orchestrator

```python
if isinstance(exc, AnalystSchemaInvalidError):
    error = "analista_schema_invalido"
    ...
elif isinstance(exc, EvaluatorSchemaInvalidError):
    error = "evaluador_schema_invalido"
    mark_failed + notify_info(...evaluador_schema_invalido...)
else:
    mark_failed(str(exc))
```

Notifier failures must not mask typed schema error (same try/except pattern as Analyst).

---

## Recommended PLAN task split (4–5 tasks)

### Task 1 — Models + included-blocks export
- Add `EvaluatorInput` in `models.py` (+ tests).
- Add `ContextBuilder.list_included_blocks` (or dual return) with null-like parity tests.
- Do **not** change Decider / EvaluationProfile shape.

### Task 2 — Evaluator B.1–B.3 prompt + B.6 retry + typed error
- `Evaluator.evaluate(EvaluatorInput)`.
- Prompt: full comprehension, blocks names, doctrine guidance.
- Retry once; `EvaluatorSchemaInvalidError`.
- Tests for retry, double-fail, anti-body contamination, English dims.

### Task 3 — Director wiring
- After `build` / from same knowledge map: pass `EvaluatorInput`.
- On evaluator schema fail: no Decision; do not invent evaluation; re-raise.
- Tests: blocks appear in FakeLLM messages; fail path.

### Task 4 — Orchestrator B.6 notify
- `evaluador_schema_invalido` durable error + owner notify + no VIP send.
- Mirror Analyst test.

### Task 5 (optional, merge into 4 if small) — Full unit gate + invariants
- `pytest -q tests/unit`
- Confirm TAC-01 happy path call counts; import purity; evaluation profile invariants.

Strict TDD: red → green per task. FakeLLM / in-memory ports only.

---

## DoD checklist for downstream

### gsd-planner
- [ ] PLAN locks English DTO field names + mapping table to Anexo B Spanish
- [ ] Locks `included_blocks` = ContextBuilder non-null-like capability names (`knowledge.*`)
- [ ] Locks doctrine as **prompt guidance** (no hard-clamp unless residual flagged)
- [ ] Locks error token `evaluador_schema_invalido` + mirror Analyst notify path
- [ ] Locks F1 `Decision.action` unchanged; no regenerate loop
- [ ] Tasks ordered TDD with exact pytest slices
- [ ] Out of scope list: Decider rewrite, Telegram redesign, Learning, SPEC full rewrite, F2

### gsd-executor
- [ ] No production code before failing tests per task
- [ ] No default EvaluationProfile on fail
- [ ] No raw knowledge bodies in Evaluator messages
- [ ] Cognitive import purity preserved
- [ ] Conventional commits only; no AI attribution
- [ ] `python -m pytest -q tests/unit` green before done

### arch-enforcer
- [ ] Evaluator still answers only “trust this draft?” (profile only)
- [ ] Director remains deterministic sequencer
- [ ] No cognitive → telegram/behavior/learning imports
- [ ] BR-09: no score_global / mean in Evaluator or Decider path
- [ ] Anti-contamination: Evaluator input has names not memory/policy text
- [ ] Fail path does not call Behavior / does not invent profile
- [ ] Modes not known to Evaluator

### test-guardian
- [ ] Retry once (2 structured calls) then typed error
- [ ] Happy path still 3 LLM ops (Analyst structured, Generator text, Evaluator structured)
- [ ] Orchestrator: failed + reason + notify + `send_count==0`
- [ ] Invariant suite for 7D profile still green
- [ ] No live network; FakeLLM only for unit
- [ ] Fixture blast radius controlled

---

## Residual candidates (out of scope follow-ups)

1. **Hard-clamp doctrine to 0.7** when policy absent — only if prompt guidance proves unreliable in calibration (REQ-EVAL).
2. **B.8 `evaluacion_schema_version`** when dimensions change.
3. **Spanish ↔ English field alias layer** for LLM providers that emit Spanish keys (if production models mis-emit).
4. **SPEC.md / REQUERIMIENTOS.md** full sync to Anexo B wording.
5. **Per-dimension model routing** (B.8 future: cheap safety classifier) — architecture allows; not F1.
6. **F2 regenerate** evaluates from scratch (B.7) — document when F2 lands; no code now.
7. **Decider threshold config from `system_config`** — AGENTS.md 6.2; separate item.
8. **Trace key for `included_blocks`** snapshot (reconstructability) — optional; could store alongside evaluation or prompt metadata later.
9. Unrelated dirty tree: `turns.error` residual / alembic 002 — only if separate fail-durability work remains.

---

## Ready for chain

**Verdict: READY** for gsd-planner with tight scope.

Handoff summary:
- Mirror analyst-contract PLAN structure (4 tasks: models/blocks → evaluator retry → director → orchestrator).
- Sole production evaluate call site: `director.py:145`.
- EvaluationProfile 7D English already contract-aligned; focus on **input DTO + included blocks + B.6 fail path + prompt**.
- Tests listed above; full `python -m pytest -q tests/unit` as gate.
- Top risks: no synthetic profile; no knowledge body leakage; blocks/null-like parity; stable fail reason + notify.
