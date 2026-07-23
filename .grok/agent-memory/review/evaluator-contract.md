# Merged hardener review c71950cb — final (round 2)
effort: 4 | rounds: 2 | open: 0
issues by severity r1: 0 bug, 3 suggestion, 2 nit (all fixed)

## [general]
# Review: evaluator-contract [General]

## Summary

Re-review after test-only fix commit `8de5069` (production cognitive/application paths unchanged). Prior general verdict remains: Anexo B + PLAN L1–L15 hold on live production code.

**Production (unchanged, re-confirmed):**
1. **B.1 / L9** — Evaluator answers only “trust this draft?”; no synthetic profile; raise `EvaluatorSchemaInvalidError` after 2 schema-class attempts.
2. **B.2 / L3–L4 / L13** — `list_included_blocks` shares `_is_null_like` with `build`; Director wires same `retrieved` map; messages carry capability names + public comprehension (no bodies, no `raw_llm_output`).
3. **B.6 / L8** — Analyst-parity retry: `ValidationError` | `ValueError` | `TimeoutError` (+ `"Timeout" in type name`); non-schema re-raises immediately.
4. **L10–L11** — Orchestrator typed branch: `mark_failed(error="evaluador_schema_invalido")` + `notify_info` + re-raise; no VIP send / no Behavior on fail.
5. **BR-09** — 7D English profile only; Decider uses vector dims (safety/risk), never mean/`score_global`.

**Test hardening in `8de5069` (locks production contracts more tightly):**
- Doctrine guidance tokens present only when `knowledge.policy` absent; absent when policy included.
- `raw_llm_output` exclusion from Evaluator LLM payload; happy-path `raw_llm_output` attach.
- TimeoutError → typed fail after one retry; non-schema `RuntimeError` propagates with call count 1.
- ValueError retry-then-success path; orchestrator notify count tightened to `== 1`.

No new production defects found on this axis.

## Issues

## Verdict
PASS with 0 open

---
## [general-2]
# Independent General Review #2 — evaluator-contract hardener (re-check)

| Field | Value |
|-------|--------|
| Project | `/home/ubuntu/repos/DianaV2` |
| Item | evaluator-contract (Anexo B hardener) |
| Reviewer | Independent general reviewer #2 |
| Date | 2026-07-23 |
| Action | Re-review after `8de5069` — **no implementation** |
| Prior verdict | PASS — **0 open** |
| Delta | `8de5069` `test(cognitive): harden Evaluator B.6 and doctrine guidance coverage` (**tests only**) |
| Base commits | `97eb6fe` `e14993f` `ce95f51` `a07be80` |
| Focus | EvaluatorInput wiring · Director included_blocks vs prompt map · empty/null-like edges · exception typing · F1 actions unchanged |
| Target | **0 open** |

---

## Verdict

**PASS — open: 0.**

Prior 0-open general verdict still holds. `8de5069` is test-only hardening (B.6 schema-class breadth, doctrine guidance positive/negative tokens, raw_llm_output exclusion, orchestrator notify coverage). Production wiring is unchanged and remains correct against PLAN L1–L15 and Anexo B.2/B.6.

---

## What `8de5069` changed

| Surface | Change | Production impact |
|---------|--------|-------------------|
| `tests/unit/cognitive/test_evaluator.py` | Stronger doctrine tokens; no-guidance when `knowledge.policy` included; `_ScriptedStructuredLLM` for ValueError/TimeoutError/non-schema; raw attach + raw blob exclusion | None |
| Related orch tests (fix round) | Notify/path assertions tightened per hardener tests review | None |
| `src/diana/**` | **Unchanged** by this commit | — |

Evidence: executor log `.planning/quick/gsd-evaluator-contract.log` — “FIX ROUND 1 … test-only … 8de5069”.

---

## Focus-area re-check (production)

| Focus | Result | Evidence |
|-------|--------|----------|
| EvaluatorInput wiring | **OK** | Sole production call in `director.py` ~146–156: `EvaluatorInput(draft, comprehension, included_blocks=blocks, current_turn=turn.text)`. Signature `evaluate(input: EvaluatorInput)`. |
| Same retrieved map as prompt | **OK** | `build(..., knowledge=retrieved)` then later `list_included_blocks(retrieved)`; no mutation of `retrieved` between BUILDING_CONTEXT and EVALUATING. |
| Empty / null-like knowledge | **OK** | Shared `_is_null_like` (None, empty list/dict/tuple/set, blank str). All-stub → `[]` blocks + no `## Knowledge` headings. Doctrine guidance when `"knowledge.policy" not in included_blocks` (including empty). |
| Exception typing | **OK** | `EvaluatorSchemaInvalidError` reason/`str` = `evaluador_schema_invalido`; `_MAX_ATTEMPTS=2`; schema-class ValidationError/ValueError/Timeout*; non-schema re-raise; no synthetic profile. Orchestrator typed branch + `notify_info` + re-raise. |
| F1 actions unchanged | **OK** | `Decision.action: Literal["approve","escalate"]`; Decider matrix untouched; Evaluator forbids choose-action / rewrite / mode. |

### EvaluatorInput + Director (Anexo B.2)

```python
blocks = self._context_builder.list_included_blocks(retrieved)
evaluation = await self._evaluator.evaluate(
    EvaluatorInput(
        draft=draft,
        comprehension=comprehension,
        included_blocks=blocks,
        current_turn=turn.text,
    )
)
```

- Flat English DTO, `extra="forbid"`.
- Names-only `included_blocks` (L3/L13); full public comprehension without `raw_llm_output` in LLM payload (L6).
- On schema fail: no `evaluation`/`decision` store; FAILED status (`test_director_evaluator_schema_fail_no_decision_trace`).

### Null-like parity (L4)

```python
def list_included_blocks(self, knowledge):
    return [name for name, value in knowledge.items() if not _is_null_like(value)]
# build() skips the same predicate before "## Knowledge: {name}"
```

Locked by `test_list_included_blocks_matches_prompt_sections` and `test_list_included_blocks_empty_when_all_null_like`.

### Exception path (B.6 / L8–L11)

- Retry once then typed error; orchestrator `mark_failed(error="evaluador_schema_invalido")` + owner notify; VIP send 0.
- `failed→failed` with error is allowed by terminal latch (identity status) so reason token sticks after Director sink FAILED.

### Edge cases (still clean)

| Case | Behavior |
|------|----------|
| Empty knowledge map / all null-like | `included_blocks=[]`; doctrine guidance applies |
| Empty history `[]` | Omitted from blocks/prompt |
| Policy planned but stub `None` | Not in blocks → ~0.7 doctrine guidance (prompt-only, L7) |
| Policy name present in blocks | No neutral-doctrine append (now unit-locked) |
| Empty draft after valid eval | Evaluate then Director empty-draft escalate |
| Double schema fail | No decision/evaluation trace |

---

## Open issues

_None._

No new production defects introduced by `8de5069`. Test delta only strengthens locks already satisfied by production code.

---

## Counts

| Severity | Open |
|----------|-----:|
| bug | 0 |
| suggestion | 0 |
| nit | 0 |
| **Total open** | **0** |

---

## Non-blocking residuals (not open)

Same as prior review / PLAN residuals:

1. Trace snapshot of `included_blocks` (optional reconstructability).
2. Doctrine hard-clamp if prompt guidance fails calibration (out of scope L7).
3. B.8 `evaluacion_schema_version` (out of scope).

---

*Re-check complete after `8de5069`. No code changes. Target met: 0 open.*

---
## [general-3]
# Independent General Review #3 — evaluator-contract (RE-REVIEW)

**Project:** `/home/ubuntu/repos/DianaV2`  
**Hardener ID:** `c71950cb`  
**Reviewer:** Independent general reviewer #3  
**Scope:** evaluator-contract after test-only hardener `8de5069`  
**Emphasize:** maintainability · AGENTS.md compliance  
**Mode:** Re-review only — **no code changes**  
**Date:** 2026-07-23  
**Prior open count:** **0**  
**This pass open count:** **0**  

## Commits in scope

| SHA | Kind | Message |
|-----|------|---------|
| `97eb6fe` | feat | add EvaluatorInput and list_included_blocks |
| `e14993f` | feat | Evaluator schema retry and EvaluatorSchemaInvalidError |
| `ce95f51` | feat | Director passes included_blocks to Evaluator |
| `a07be80` | feat | notify owner on evaluador_schema_invalido |
| `8de5069` | **test only** | harden Evaluator B.6 and doctrine guidance coverage |

**HEAD reviewed:** `8de5069` `test(cognitive): harden Evaluator B.6 and doctrine guidance coverage`

---

## Verdict

**PASS — 0 open.**

Prior AGENTS.md disposition stands. `8de5069` is **tests only** (plus stronger locks); production cognitive / application surfaces for Evaluator are **unchanged**. No new architecture or purity regressions.

---

## What `8de5069` changed

Commit message and tree inspection:

- **Production:** no edits under `src/diana/**` (evaluator, models, director, orchestrator, exceptions unchanged).
- **Tests:** `tests/unit/cognitive/test_evaluator.py` (+ orchestrator assert tighten).

New / hardened coverage (Analyst A.6 parity):

| Test lock | AGENTS / contract value |
|-----------|-------------------------|
| `TimeoutError` double-fail → `evaluador_schema_invalido` | B.6 typed fail path |
| `RuntimeError` non-schema → no retry | fail path does not wash infra errors |
| `ValueError` then recover | schema-class retry once |
| Doctrine guidance **absent** when `knowledge.policy` in blocks | B.3 inverse; no false neutral-0.7 |
| Doctrine tokens distinctive (`approximately 0.7`, `neutral-high`, …) | avoids false pass on bare dim name |
| `raw_llm_output` attach when missing | reconstructability |
| Structural anti-contamination: exclude `raw_llm_output` / secret blob from LLM payload | prompt purity / no knowledge body dump |
| Orchestrator `len(notifier.infos) == 1` | single owner notify on B.6 fail |

These **strengthen** the prior gate; they do not invent product behavior.

---

## Focus matrix (AGENTS.md) — re-check

| Focus | Result | Evidence on HEAD `8de5069` |
|-------|--------|----------------------------|
| **Cognitive purity** — Evaluator scores only | **PASS** | `evaluator.py` still: `EvaluationProfile` only; no Decider/Behavior/Learning/Telegram imports. Import purity test still applies to cognitive package. |
| **EvaluationProfile 7D invariants** | **PASS** | 7 required `ScoreUnit` dims; finite/`[0,1]`; `extra="forbid"`; no aggregate score fields/helpers. Invariant suite unchanged and still binding. |
| **No Decider logic leak into Evaluator** | **PASS** | No thresholds / action / mode on `EvaluatorInput`. Doctrine ≈0.7 remains scoring guidance when policy block absent — not escalate. Safety + risk matrix stay in `decider.py`. |
| **Prompt purity (no mode, no action as inputs)** | **PASS** | User payload still: `current_turn` + public comprehension + `included_blocks` names + `draft`. No `supervised`/`autonomous` injected. System forbids action choice / rewrite / operating mode; does not feed a mode or recommended action. New tests freeze doctrine inverse + raw blob exclusion. |
| **A.6 consistency without bad drift** | **PASS (behavioral)** | B.6 still mirrors A.6: 1+1 attempts, schema-class set, typed reason, Director no evaluation/decision store, orchestrator failed+notify+re-raise. Test parity with Analyst now closer (Timeout + non-schema no-retry). Residual DRY of shared helper remains optional note only. |
| **Anti-contamination** | **PASS** | Names-only blocks; director test still forbids history body; new evaluator test forbids comprehension `raw_llm_output` secret in messages. |
| **B.6 fail-closed** | **PASS** | No synthetic profile; `evaluador_schema_invalido`; VIP send 0; learning not called; owner notify exactly once (strict `== 1`). |
| **Director determinism** | **PASS** | Fixed pipeline; Evaluator remains one scoring step; Decider unchanged. |

---

## AGENTS.md hard-limit checklist

| Rule | Status |
|------|--------|
| Director 100% deterministic | OK |
| One cognitive question (Evaluator = trust draft?) | OK |
| Behavior Engine outside cognition | OK |
| Learning post-turn only | OK (schema-fail path still skips learning) |
| EvaluationProfile never single score | OK |
| Modes external filters only | OK |
| Decider on vector + risk | OK |
| Cognitive import boundaries | OK |

---

## Prior residual notes (still not open)

Same optional maintainability notes as prior pass — **not Status: open**:

1. A.6/B.6 retry helper still copy-mirrored Analyst ↔ Evaluator (optional shared helper later).  
2. Schema-invalid exceptions still sibling types (optional common base + `exc.reason` in orchestrator).  
3. Doctrine 0.7 still prompt-hardcoded (contrato default; fine for F1 policy stub).  

`8de5069` does **not** worsen these; it reduces **test** gap risk on Timeout / non-schema / doctrine inverse.

---

## Issues (current)

_None._

### Issue count

| Severity | Open |
|----------|------|
| bug | 0 |
| suggestion | 0 |
| nit | 0 |
| **open total** | **0** |

| Prior disposition | This pass |
|-------------------|-----------|
| 0 open PASS | **confirmed** — no reopen, no new opens |

---

## Production surface spot-check (unchanged)

| File | Status vs prior review |
|------|------------------------|
| `/home/ubuntu/repos/DianaV2/src/diana/cognitive/evaluator.py` | Unchanged behavior |
| `/home/ubuntu/repos/DianaV2/src/diana/cognitive/models.py` (`EvaluatorInput`, `EvaluationProfile`) | Unchanged |
| `/home/ubuntu/repos/DianaV2/src/diana/cognitive/exceptions.py` | Unchanged |
| `/home/ubuntu/repos/DianaV2/src/diana/cognitive/context_builder.py` (`list_included_blocks`) | Unchanged |
| `/home/ubuntu/repos/DianaV2/src/diana/cognitive/director.py` | Unchanged |
| `/home/ubuntu/repos/DianaV2/src/diana/cognitive/decider.py` | Unchanged (no leak) |
| `/home/ubuntu/repos/DianaV2/src/diana/application/turn_orchestrator.py` | Unchanged B.6 branch |

---

## Tests inspected (delta)

- `/home/ubuntu/repos/DianaV2/tests/unit/cognitive/test_evaluator.py` — B.6 breadth + doctrine inverse + anti-contamination + raw attach  
- `/home/ubuntu/repos/DianaV2/tests/unit/application/test_turn_orchestrator.py` — `len(notifier.infos) == 1` on evaluator schema fail  

---

## Verdict (repeat)

**0 open PASS.** AGENTS.md cognitive purity, 7D EvaluationProfile, Decider isolation, and prompt isolation remain clean after test-only `8de5069`. No production regression; test surface is stronger.

**End of re-review.** No code changes by this reviewer.

---
## [tests]
# Tests Audit — hardener-agile evaluator-contract

**Project:** `/home/ubuntu/repos/DianaV2`  
**Auditor role:** Tests specialist (hardener-agile) — prompt-only, no code fixes  
**Eval id:** `c71950cb`  
**Pass:** re-review after fix commit `8de5069`  
**Scope:** Evaluator contract DoD paths — `EvaluatorInput`, `list_included_blocks`, B.6 retry, doctrine guidance, Director wiring, orchestrator notify, `send_count==0`, anti-contamination; TAC-01 3 LLM calls  
**Files reviewed:**
- `tests/unit/cognitive/test_evaluator.py`
- `tests/unit/cognitive/test_context_builder.py`
- `tests/unit/cognitive/test_director.py`
- `tests/unit/cognitive/test_models.py`
- `tests/unit/application/test_turn_orchestrator.py`
- Production: `src/diana/cognitive/{evaluator,context_builder,director,models,exceptions}.py`, `src/diana/application/turn_orchestrator.py`, `src/diana/llm/fake.py`

**Out of scope (not demanded):** doctrine hard-clamp, B.8 schema version, SPEC rewrite.

---

## Executive summary

Prior re-review filed **5 open issues**. After `8de5069`, **all five are fixed**.

Evaluator-contract DoD paths are now locked with real SUT + FakeLLM/ports at Analyst parity for B.6 schema-class handling, doctrine present/absent guidance, orchestrator notify exactness, structural anti-contamination, and `raw_llm_output` attach/recover polish.

| DoD path | Covered? | Strength |
|----------|----------|----------|
| `EvaluatorInput` DTO (fields, required, extra forbid) | **YES** | High |
| `list_included_blocks` ≡ `build()` knowledge headings | **YES** | High |
| B.6 ValidationError: 1 retry, same messages, typed fail | **YES** | High |
| B.6 ValueError: double-fail + recover-on-retry | **YES** | High |
| B.6 TimeoutError → typed after 1 retry | **YES** | High |
| B.6 non-schema RuntimeError, no retry (1 call) | **YES** | High |
| Doctrine guidance when policy **absent** | **YES** | High — distinctive tokens |
| Doctrine guidance **not** applied when policy **present** | **YES** | High |
| Director wires `list_included_blocks` → Evaluator | **YES** | High |
| Director B.6: no evaluation/decision + FAILED | **YES** | High |
| Orchestrator: failed + notify `== 1` + `send_count==0` | **YES** | High |
| Anti-contamination (names only; no raw_llm dump / history body) | **YES** | High |
| TAC-01 exactly 3 LLM calls | **YES** | High |

**Mock audit: clean (0 prohibited).**  
**Open issues: 0**

---

## Prior issues — verification

| # | Was | Fix evidence | Status |
|---|-----|--------------|--------|
| 1 | **suggestion** — no TimeoutError / non-schema RuntimeError B.6 tests | `test_evaluate_timeout_maps_to_evaluador_schema_invalido` (`TimeoutError`×2 → typed, 2 calls); `test_evaluate_non_schema_errors_propagate_without_retry` (`RuntimeError`, 1 call) via `_ScriptedStructuredLLM` | **fixed** |
| 2 | **suggestion** — doctrine guidance only when policy absent | `test_evaluate_system_prompt_no_neutral_doctrine_when_policy_included` asserts `_DOCTRINE_GUIDANCE_TOKENS` absent; absent path now uses distinctive tokens only | **fixed** |
| 3 | **suggestion** — orchestrator `infos >= 1` soft | `test_orchestrator_evaluator_schema_fail_marks_failed_notifies_owner`: `assert len(notifier.infos) == 1` | **fixed** |
| 4 | **nit** — vacuous `SECRET-HISTORY-BODY` unit assert | `test_evaluate_messages_include_bloques_names_not_knowledge_bodies` injects `raw_llm_output` secret blob + asserts excluded; structural included_blocks/public comprehension checks | **fixed** |
| 5 | **nit** — raw_llm attach / ValueError recover / weak doctrine tokens | `test_evaluate_attaches_raw_llm_output_when_missing`; `test_evaluate_retries_once_on_value_error_then_succeeds` (same messages); absent doctrine uses unique phrase tokens | **fixed** |

### ISSUE-1 detail (B.6 schema-class completeness)

```266:282:tests/unit/cognitive/test_evaluator.py
async def test_evaluate_timeout_maps_to_evaluador_schema_invalido() -> None:
    llm = _ScriptedStructuredLLM([TimeoutError("llm timeout"), TimeoutError("again")])
    with pytest.raises(EvaluatorSchemaInvalidError) as ei:
        await Evaluator(llm).evaluate(_input())
    assert str(ei.value) == "evaluador_schema_invalido"
    assert len(llm.calls) == 2

async def test_evaluate_non_schema_errors_propagate_without_retry() -> None:
    llm = _ScriptedStructuredLLM([RuntimeError("provider 500")])
    with pytest.raises(RuntimeError, match="provider 500"):
        await Evaluator(llm).evaluate(_input())
    assert len(llm.calls) == 1
```

Removing Timeout from schema-class handling or washing provider 500s fails the gate.

### ISSUE-2 detail (doctrine inverse)

```201:211:tests/unit/cognitive/test_evaluator.py
async def test_evaluate_system_prompt_no_neutral_doctrine_when_policy_included() -> None:
    await Evaluator(llm).evaluate(
        _input(included_blocks=["knowledge.history", "knowledge.policy"])
    )
    ...
    for token in _DOCTRINE_GUIDANCE_TOKENS:
        assert token not in system_l
```

Always-on neutral guidance fails. Absent path locks `approximately 0.7` / `neutral-high` / `not among included_blocks` (not bare `"doctrine"`).

### ISSUE-3 detail (notify exactness)

```470:477:tests/unit/application/test_turn_orchestrator.py
    assert actuator.send_count() == 0
    assert learn.calls == []
    assert len(notifier.infos) == 1
    assert notifier.drafts == []
    assert notifier.escalations == []
    info_text, _info_chat = notifier.infos[0]
    assert "evaluador_schema_invalido" in info_text
```

Double notify fails. Parity with Analyst A.6 gold.

### ISSUE-4 / ISSUE-5 detail (anti-contam + polish)

- Unit anti-contam injects `raw_llm_output={"marker": "SECRET-RAW-LLM-BLOB-ZZ"}` and asserts marker + key absent from Evaluator messages; public fields (`ansiosa`, `intent`) and block names remain.
- `test_evaluate_attaches_raw_llm_output_when_missing` locks happy-path raw fill for all 7 dims.
- `test_evaluate_retries_once_on_value_error_then_succeeds` locks ValueError → valid recover with same messages.

---

## Coverage matrix (PLAN DoD)

### EvaluatorInput

| Case | Test | Verdict |
|------|------|---------|
| Full payload accepted | `test_evaluator_input_accepts_full_payload` | OK |
| Extra fields forbidden (`score_global`) | `test_evaluator_input_rejects_extra_fields` | OK |
| All four fields required | `test_evaluator_input_requires_all_fields` | OK |
| `evaluate()` accepts DTO | `test_evaluate_accepts_evaluator_input` | OK |

### list_included_blocks

| Case | Test | Verdict |
|------|------|---------|
| Blocks match `## Knowledge:` headings | `test_list_included_blocks_matches_prompt_sections` | OK |
| Null / empty / whitespace omitted | `test_list_included_blocks_empty_when_all_null_like` + null build tests | OK |
| Director uses builder output | `test_director_passes_included_blocks_to_evaluator` | OK |

### B.6 retry / typed fail

| Case | Test | Verdict |
|------|------|---------|
| Incomplete dims → retry then success + same messages | `test_evaluate_retries_once_on_validation_error` | OK |
| Double incomplete → `evaluador_schema_invalido` + 2 calls | `test_evaluate_double_fail_*` / incomplete dims | OK |
| ValueError double → typed, 2 attempts | `test_evaluate_value_error_is_schema_class_and_retries` | OK |
| ValueError then valid → recover | `test_evaluate_retries_once_on_value_error_then_succeeds` | OK |
| TimeoutError → typed after 1 retry | `test_evaluate_timeout_maps_to_evaluador_schema_invalido` | OK |
| Non-schema RuntimeError, 1 call | `test_evaluate_non_schema_errors_propagate_without_retry` | OK |
| Stable reason string | unit + director + orchestrator | OK |
| No synthetic evaluation/decision on fail | `test_director_evaluator_schema_fail_no_decision_trace` | OK |

### Doctrine guidance (B.3 / prompt)

| Case | Test | Verdict |
|------|------|---------|
| No `knowledge.policy` → distinctive guidance | `test_evaluate_system_prompt_doctrine_guidance_when_policy_absent` | OK |
| Policy present → no neutral-0.7 guidance | `test_evaluate_system_prompt_no_neutral_doctrine_when_policy_included` | OK |

### Director wiring + TAC-01

| Case | Test | Verdict |
|------|------|---------|
| Evaluator messages get block **names** | `test_director_passes_included_blocks_to_evaluator` | OK |
| History **body** not in Evaluator prompt | same (`prior-from-42-HISTORY-BODY`) | OK |
| Schema fail: no decision/eval, has generated_text, FAILED | `test_director_evaluator_schema_fail_no_decision_trace` | OK |
| Exactly Analyst structured + Generator text + Evaluator structured | `test_tac01_llm_calls_only_analyst_generator_evaluator` | OK |
| Schemas Comprehension / EvaluationProfile | TAC-01 asserts | OK |

### Orchestrator notify + send_count==0

| Case | Test | Verdict |
|------|------|---------|
| Real Director+Evaluator+FakeLLM gold | `test_orchestrator_evaluator_schema_fail_marks_failed_notifies_owner` | OK |
| `failed.error == evaluador_schema_invalido` | same | OK |
| `actuator.send_count() == 0` | same | OK |
| Learning not run | `learn.calls == []` | OK |
| Notify count exact `== 1` | same | OK |
| drafts/escalations empty; reason + turn_id in info | same | OK |

### Anti-contamination

| Case | Test | Verdict |
|------|------|---------|
| Unit: block names + public comprehension | `test_evaluate_messages_include_bloques_names_not_knowledge_bodies` | OK |
| Unit: `raw_llm_output` blob excluded | same (injected secret marker) | OK |
| Director: real history body absent | `test_director_passes_included_blocks_to_evaluator` | OK |

### raw_llm_output attach

| Case | Test | Verdict |
|------|------|---------|
| Fills when missing on happy path | `test_evaluate_attaches_raw_llm_output_when_missing` | OK |

---

## Mock audit

| Location | Double | Replaces SUT under test? | Verdict |
|----------|--------|--------------------------|---------|
| `test_evaluator.py` | `FakeLLM` | No — LLM port | **PERMITTED** |
| `test_evaluator.py` | `_ScriptedStructuredLLM` | No — LLM exception/result scripting only | **PERMITTED** |
| `test_director.py` | `FakeLLM` + InMemory ports | No — real Director/Evaluator/ContextBuilder | **PERMITTED** |
| `test_turn_orchestrator.py` B.6 evaluator | Real CognitiveDirector + Evaluator + FakeLLM + Fake actuator/notifier | No — gold critical path | **PERMITTED** |
| Other orchestrator branches | `FakeDirector` | No — outside evaluator-contract gold | **PERMITTED** |
| `test_models.py` / `test_context_builder.py` | none | N/A | **CLEAN** |
| In-scope suite | `@patch` / `MagicMock` / `AsyncMock` of Evaluator/Director/EvaluationProfile | **Absent** | N/A |

**Prohibited mocks: 0**  
**Confidence of reality: high**

---

## Open issues

### (none)

---

## Gold / critical paths

| Path | Real SUT? | Verdict |
|------|-----------|---------|
| TAC-01 3 LLM calls (Analyst / Generator / Evaluator) | Real Director + FakeLLM | **Locked** |
| Director included_blocks + history-body anti-contam | Real Director + registry history | **Locked** |
| Director evaluator schema fail (no decision/eval) | Real Evaluator | **Locked** |
| Orchestrator B.6 evaluator fail + notify×1 + no VIP send | Real Director+Evaluator stack | **Locked** |
| Unit Evaluator B.6 full schema-class family | Real Evaluator + FakeLLM / scripted LLM | **Locked** |
| Doctrine present vs absent prompt branch | Real Evaluator | **Locked** |

---

## Verdict

**Open issues: 0**

Suite is **hardener-clean** for evaluator-contract unit protection after `8de5069`. All five prior issues (Timeout/non-schema B.6, doctrine inverse, notify exactness, structural anti-contam, raw_llm/ValueError polish) are closed with non-vacuous asserts. No remaining in-scope test-protection gaps that would let the previously identified regressions pass silently.

**Handoff:** Tests axis **CLEAN**. Ready for hardener close on this slice.

---
## [plan]
# Plan Alignment Review — evaluator-contract (re-review)

**Plan:** `.planning/quick/evaluator-contract/PLAN.md`  
**Commits (implementation + prior):** `97eb6fe`, `e14993f`, `ce95f51`, `a07be80`  
**Follow-up (test-only):** `8de5069`  
**Scope:** Locked decisions L1–L15 + Tasks 1–4 DoD  
**Out of scope (L15 residuals ignored):** doctrine hard-clamp, B.8 schema version, Spanish aliases, SPEC/REQ rewrite, F2 regenerate, Decider matrix/system_config, included_blocks trace snapshot, Telegram/Behavior/Learning redesign, Alembic residual.

**Delta since prior ALIGNED review:** `8de5069` is **test-only** hardening (stronger doctrine / anti-contamination / schema-class / notify-once asserts). Production surface for L1–L14 is unchanged.

---

## Verdict

**ALIGNED** — open issues: **0**

Implementation still matches locked PLAN decisions and task DoDs. No in-scope gaps. No production scope creep. Test-only follow-up stays inside PLAN Task 2 optional gold / DoD lock-in (does not expand L15 residuals).

---

## Locked decisions (L1–L15)

| ID | Status | Evidence |
|----|--------|----------|
| L1 | Met | `EvaluationProfile` English 7D unchanged: naturalness, precision, doctrine, consistency, safety, coverage, empathy (`models.py`). Spanish only in docs/prompt text. |
| L2 | Met | `EvaluatorInput`: draft, comprehension, included_blocks, current_turn; flat; `extra="forbid"`; docstring maps Anexo B. |
| L3 | Met | `included_blocks` = full capability names via `list_included_blocks(retrieved)`; Director passes names only (not bodies / not plan list). |
| L4 | Met | Shared `_is_null_like` with `build`; None / empty list·dict·tuple·set / whitespace str; insertion order preserved. |
| L5 | Met | `async def evaluate(self, input: EvaluatorInput) -> EvaluationProfile`; sole production caller = Director EVALUATING. |
| L6 | Met | System: trust draft? 7 English dims; forbid score_global / action / rewrite / mode. User: full public comprehension (excludes `raw_llm_output`), draft, turn, block names. |
| L7 | Met | When `"knowledge.policy" not in included_blocks`, system appends doctrine ≈ 0.7 (neutral-high); **no** post-LLM hard-clamp. |
| L8 | Met | `_MAX_ATTEMPTS = 2`; `_is_schema_class_failure` mirrors Analyst (ValidationError, ValueError, TimeoutError, type name contains Timeout); same messages on retry. |
| L9 | Met | `EvaluatorSchemaInvalidError`; `str` / `.reason` == `evaluador_schema_invalido`; no synthetic default profile on fail. |
| L10 | Met | Orchestrator branch: `mark_failed(..., "evaluador_schema_invalido")` + `admin.notify_info` with reason + turn_id; notifier failures must not mask typed error; cognitive does not import telegram. |
| L11 | Met | Fail aborts before usable Decision deliver; `send_count()==0`; learning not invoked on fail path. |
| L12 | Met | `Decision.action` remains `approve \| escalate` only; no regenerate; Evaluator does not know mode. |
| L13 | Met | Messages: capability **names** + draft/turn/comprehension; no knowledge bodies; `raw_llm_output` excluded from LLM payload. |
| L14 | Met | Unit tests use FakeLLM / scripted doubles / in-memory ports; no live network. |
| L15 | N/A | Residuals correctly left untouched. |

---

## Tasks 1–4 DoD

### Task 1 — EvaluatorInput + list_included_blocks

| DoD item | Status | Evidence |
|----------|--------|----------|
| `EvaluatorInput` English + `extra="forbid"` | Met | `src/diana/cognitive/models.py` |
| `list_included_blocks` parity with `build` headings | Met | `context_builder.py` + `test_list_included_blocks_matches_prompt_sections` |
| Profile invariants untouched | Met | `EvaluationProfile` fields/validators unchanged |
| Required tests | Met | `test_evaluator_input_accepts_full_payload`, `_rejects_extra_fields`, `_requires_all_fields`; `test_list_included_blocks_*` (2) |

### Task 2 — Evaluator prompt + B.6 retry + typed error

| DoD item | Status | Evidence |
|----------|--------|----------|
| Signature uses `EvaluatorInput` | Met | `evaluator.py` |
| Exactly one retry then typed error | Met | `_MAX_ATTEMPTS=2`; double-fail / incomplete→typed tests |
| Doctrine guidance when policy absent | Met | `_DOCTRINE_NO_POLICY`; tests assert distinctive tokens (`approximately 0.7`, `neutral-high`, `not among included_blocks`) |
| Doctrine guidance **not** when policy present | Met | `test_evaluate_system_prompt_no_neutral_doctrine_when_policy_included` (locks L7 inverse) |
| Draft + turn + emotion; names not bodies | Met | message tests; `raw_llm_output` blob absent from payload |
| English dims only; no score_global | Met | system prompt + English field-name test |
| Optional gold (ValueError / Timeout) | Met | scripted LLM: ValueError retry/recover; TimeoutError→typed; non-schema RuntimeError no retry |
| Happy path raw attach | Met | `test_evaluate_attaches_raw_llm_output_when_missing` |
| Required PLAN tests | Met | accept DTO, messages, doctrine, retry once, double fail, incomplete→typed, English-only fields |

### Task 3 — Director wiring

| DoD item | Status | Evidence |
|----------|--------|----------|
| Builds `EvaluatorInput` from null-like-filtered blocks | Met | `list_included_blocks(retrieved)` then `evaluate(EvaluatorInput(...))` |
| Schema fail: no Decision / no synthetic evaluation | Met | `test_director_evaluator_schema_fail_no_decision_trace` — no `decision`/`evaluation` keys; FAILED; no DECIDING |
| TAC-01 happy path still 3 LLM calls | Met | `test_tac01_llm_calls_only_analyst_generator_evaluator` |
| Included blocks anti-contamination | Met | `test_director_passes_included_blocks_to_evaluator` — names present; history body absent |

### Task 4 — Orchestrator B.6 notify

| DoD item | Status | Evidence |
|----------|--------|----------|
| Fail reason `evaluador_schema_invalido` | Met | `mark_failed` + `failed.error` assert |
| Owner notified once | Met | `len(notifier.infos) == 1`; info contains reason + turn_id |
| VIP send count 0 | Met | `actuator.send_count()==0` |
| Learning not success-path on fail | Met | `learn.calls == []` |
| Analyst A.6 path preserved | Met | Analyst `isinstance` branch still first in except chain |

---

## Scope creep check

### Production surface (unchanged by `8de5069`)

Planned files only:

- `src/diana/cognitive/models.py` — `EvaluatorInput`
- `src/diana/cognitive/context_builder.py` — `list_included_blocks`
- `src/diana/cognitive/exceptions.py` — `EvaluatorSchemaInvalidError`
- `src/diana/cognitive/evaluator.py` — DTO API + B.1/B.3 prompt + B.6 retry
- `src/diana/cognitive/director.py` — EvaluatorInput wiring
- `src/diana/application/turn_orchestrator.py` — typed notify branch

**Not touched (correct):** Decider matrix, `Decision.action` expansion, Telegram, Behavior, Learning, SPEC/REQ, Alembic, doctrine hard-clamp, Spanish field aliases, B.8 version field.

### Follow-up `8de5069` (test-only)

Touches tests under PLAN Task 2–4 surfaces (primarily `test_evaluator.py`, minor assert tighten on orchestrator notify count). No production file changes. Aligns with PLAN “Optional gold: ValueError / TimeoutError schema-class mapping” and stronger L7/L13 locks — **not** scope creep.

Optional PLAN item (export `EvaluatorInput` from package `__init__`) still not done — allowed (“only if useful”).

---

## Open issues

_None._

---

## Summary

| Metric | Value |
|--------|-------|
| L1–L15 | 15/15 met (L15 N/A residual ignore) |
| Tasks 1–4 DoD | All met |
| Scope creep | None (prod + test-only follow-up) |
| Prior verdict | ALIGNED (0 open) |
| **Verdict after `8de5069`** | **ALIGNED** |
| **Open count** | **0** |

---
