---
phase: quick
plan: decider-contract
type: auto
item: decider-contract (Pool remaining-contracts-cognitive · Anexo F)
effort: 2
stack: python>=3.12, pydantic-v2, pytest
depends_on: generator-contract (pipeline order only; no API dep)
source_of_truth: docs/contratos_restantes.md Anexo F (F.1–F.5) under F1 locks
impact: .grok/agent-memory/impact-analyzer/decider-contract.md
mode: standard
alignment: substantial — F1 matrix already correct; slice = lock residual + audit field + docstring
---

## Objective

Lock the **Decider runtime** to the **F1-safe subset** of `docs/contratos_restantes.md` Anexo F: pure deterministic matrix over `EvaluationProfile.safety` + `Comprehension.risk` (+ optional supervised mode audit), public `Decision.action` stays **`approve | escalate` only**, never LLM, never draft text, never score collapse — and explicitly document that **F.3 rule 2 (naturalness → regenerate) is residual** with F1 fall-through = approve.

Runtime is already behaviorally correct for F.3 #1 and #3 + F1 risk extension. This slice is thin: **tests + docstring + optional audit field**.

## Scope

- **In:**
  - Keep matrix order: safety below threshold → escalate; else risk=`alto` → escalate; else approve
  - Unit tests locking residual: low `naturalness` still **approve** when safety OK and risk not alto (no regenerate)
  - Optional audit: `Decision.mode_restriction_applied: str | None` — set on supervised approve path; `None` on escalate / non-supervised
  - Decider module docstring: English ↔ Anexo F mapping + residual note for F.3 #2
  - Director passthrough of `mode_restriction_applied` when rebuilding `Decision` with `draft_text`
  - Preserve stable reason tokens: `safety_below_threshold` | `risk_high` | `ok_for_human_review`
- **Out / Non-goals:**
  - Expanding `Decision.action` to `send` / `regenerate` / `consult_doctrine` (**L1**)
  - Implementing naturalness → regenerate or Director regenerate loop (**L3 residual**)
  - Composition wiring of `SqlSystemConfigStore.get_eval_thresholds()` (**L6 later**)
  - New required `DeciderInput` DTO (kwargs + ctor thresholds sufficient)
  - Loading / acting on `naturalness_min` threshold
  - Removing `risk == "alto"` escalate (**L2 keep**)
  - Decider reading draft text (**L5**)
  - Behavior / Generator / Evaluator / Analyst / Planner / Telegram / Learning rework (**L8**)
  - Alembic / SPEC / REQUERIMIENTOS full rewrite
  - Dirty-tree WIP unrelated modules
- **Constraints:**
  - Strict TDD Mode **active** — red → green → refactor per task
  - Cognitive Core **must not** import `diana.telegram`, `diana.behavior`, `diana.learning`, `aiogram`, `sqlalchemy`
  - No LLM in Decider; no `mean(` / `overall_score` / `confidence` score collapse (BR-09)
  - Code/comments/identifiers in **English**; this PLAN is English
  - Import purity stays green: `tests/unit/cognitive/test_import_purity.py`
  - Happy-path TAC-01 still **3** LLM calls (Analyst + Generator + Evaluator); Decider never adds one

## Assumptions

- A1: Decider matrix already matches F1 product truth (impact gap table mostly OK). Slice is lock + auditability, not redesign.
- A2: Skipping composition threshold wiring is correct for this PR (L6); ctor `thresholds={"safety": …}` remains the injection point.
- A3: Adding optional `mode_restriction_applied` default `None` is backward-compatible with existing `Decision(...)` fixtures (`extra="forbid"` only rejects unknown keys, not missing optionals).
- A4: Director must copy the new field when rebuilding Decision with `draft_text`; default `None` alone would silently drop Decider audit metadata.
- A5: F.3 wording: when regenerate is not implemented, rule 2 **falls through to rule 3** → supervised approve. Document + test; do not gate on naturalness.
- A6: Value for supervised rewrite audit token is exactly `"supervised_send_to_approve"` (English; maps F.2 `restriccion_de_modo_aplicada`).
- A7: No `DeciderInput` DTO — same minimal style as Planner (`plan(comprehension)`); F.2 shape lives in docstring map only.

## Locked decisions (NON-NEGOTIABLE)

| ID | Decision |
|----|----------|
| L1 | `Decision.action` remains **`approve \| escalate` only** — NEVER expand |
| L2 | Keep safety-threshold escalate + `risk=="alto"` escalate (F1 safety extension) |
| L3 | F.3 #2 naturalness→regenerate = **residual / out of scope F1** (fall-through approve) |
| L4 | Add optional `mode_restriction_applied` on `Decision` when supervised would rewrite raw send→approve (raw `send` never exposed) |
| L5 | Decider never reads draft text — only `EvaluationProfile` + `Comprehension.risk` (+ mode for audit only) |
| L6 | Thresholds from ctor dict; composition wire of `eval_thresholds` deferred |
| L7 | No LLM; pure deterministic |
| L8 | No dirty tree / Behavior / Generator rework |

### English ↔ Anexo F mapping (docs/docstring only)

| Runtime (English) | Anexo F (Spanish) |
|-------------------|-------------------|
| `EvaluationProfile` | `perfil` / `PerfilEvaluacion` |
| `safety` / `naturalness` | `seguridad` / `naturalidad` |
| `mode: supervised \| autonomous` | `modo_activo: supervisado \| autonomo` |
| `thresholds["safety"]` | `umbrales.seguridad_min` |
| `naturalness_min` | **unused in F1** (residual with regenerate) |
| `action: approve \| escalate` | `accion: aprobar \| escalar` (**no** `regenerar` in F1) |
| `reason` | `razon` |
| `mode_restriction_applied` | `restriccion_de_modo_aplicada` |
| F1 risk gate | extension beyond pure F.3 table (keep) |

### F1 matrix (locked order — first match wins)

| # | Condition | Final action | `reason` | `mode_restriction_applied` |
|---|-----------|--------------|----------|----------------------------|
| 1 | `evaluation.safety < safety_threshold` | `escalate` | `safety_below_threshold` | `None` |
| 2 | `comprehension.risk == "alto"` | `escalate` | `risk_high` | `None` |
| 3 | else (supervised) | `approve` | `ok_for_human_review` | `"supervised_send_to_approve"` if `mode == "supervised"` else `None` |

Default `safety_threshold` = **0.3**. Boundary: `safety == threshold` → **approve** (not escalate).  
Residual: low naturalness does **not** change action (no rule between 1 and 2 for naturalness).

## Architecture Approach

### QUÉ (behavior / contracts)

| Contract | Runtime truth after this item |
|----------|-------------------------------|
| F.1 | Decider answers only “what action?”; no quality re-judge; no draft read; no LLM |
| F.2 in | `decide(evaluation, comprehension, *, mode="supervised")`; thresholds on ctor |
| F.2 out | `action` ∈ {approve, escalate}; `reason`; optional `mode_restriction_applied` |
| F.3 #1 | safety below umbral → escalate |
| F.3 #2 | residual — not implemented; fall-through to #3 (approve under supervised) |
| F.3 #3 | approve under supervised; audit field records mode rewrite of conceptual raw send |
| F.3 risk | F1 extension: risk alto → escalate after safety check |
| F.4 | mode never unlocks public `send`; draft attach stays in Director |
| F.5 | custom threshold pattern already covered by unit tests |

### CÓMO (structure / patterns)

- **Placement:** Cognitive Core only — `decider.py`, `models.py` (`Decision`), tiny `director.py` field copy. No application action-branch change.
- **Pattern to copy:**
  - PLAN shape: `.planning/quick/planner-contract/PLAN.md` (thin alignment when mostly OK)
  - Existing matrix golds: `tests/unit/cognitive/test_decider.py`
  - Decision model lock: `tests/unit/cognitive/test_models.py` (`test_decision_rejects_non_f1_actions`)
  - Director draft attach: `src/diana/cognitive/director.py` ~162–170 — extend rebuild to copy `mode_restriction_applied`
- **File map:**
  - **Edit:** `src/diana/cognitive/decider.py`, `src/diana/cognitive/models.py`, `src/diana/cognitive/director.py`, `tests/unit/cognitive/test_decider.py`, `tests/unit/cognitive/test_models.py`
  - **Edit optional:** `tests/unit/cognitive/test_director.py` — one assert that approve path preserves `mode_restriction_applied` if cheap
  - **No-touch:** `generator.py`, `evaluator.py`, `analyst.py`, `planner.py`, `behavior/**`, `telegram/**`, `learning/**`, `composition.py` (threshold wire later), alembic/**, orchestrator action vocabulary
- **Interfaces first:** optional field on `Decision` before Decider sets it; Director copy last
- **Wiring:** sole production call remains `director` → `decider.decide(..., mode="supervised")`; composition stays `Decider()`
- **Mock policy:** none — pure unit; no FakeLLM for Decider

## Context

@`.grok/agent-memory/impact-analyzer/decider-contract.md`
@`docs/contratos_restantes.md` (Anexo F only)
@`AGENTS.md` (§5.2 vector, §5.3 Decision vision vs F1 runtime lock)
@`docs/MVP_COMPONENT_DESIGN.md` (§5.11 Decider, §13 regenerate deferred)
@`src/diana/cognitive/decider.py`
@`src/diana/cognitive/models.py` (`Decision`, `EvaluationProfile`)
@`src/diana/cognitive/director.py` (draft attach after decide)
@`tests/unit/cognitive/test_decider.py`
@`tests/unit/cognitive/test_models.py`
@`tests/unit/cognitive/test_director.py`
@`tests/unit/cognitive/test_import_purity.py`
@`.planning/quick/planner-contract/PLAN.md` (thin contract pattern)

## Tasks

### Task 1: TDD — residual naturalness + mode_restriction model/matrix locks
**type:** auto  
**Objective:** Tests define F1-safe Anexo F behavior before any production edit: low naturalness still approve; optional audit field semantics; F1 action set unchanged.

**TDD order:**
1. Add failing tests in `test_decider.py` + `test_models.py` (red for new assertions).
2. Do **not** implement production code in this task if tests already pass for residual-only cases — still add the tests first; leave mode_restriction asserts red until Task 2 if field missing.
3. Prefer one commit boundary after green Task 2, or work-unit commits per green suite.

**Files (edit):**
- `tests/unit/cognitive/test_decider.py`
- `tests/unit/cognitive/test_models.py`

**Tests to add (must exist after task / go green with Task 2):**

| Test name | Intent |
|-----------|--------|
| `test_low_naturalness_still_approves_when_safety_ok` | Residual F.3 #2: `naturalness=0.1`, `safety=0.9`, risk not alto → `action=="approve"`, reason `ok_for_human_review` |
| `test_low_naturalness_does_not_produce_regenerate` | Same setup → `action != "regenerate"` and `action in ("approve","escalate")` |
| `test_mode_restriction_set_on_supervised_approve` | safe approve + `mode="supervised"` → `mode_restriction_applied == "supervised_send_to_approve"` |
| `test_mode_restriction_none_on_escalate_safety` | safety below threshold → escalate + `mode_restriction_applied is None` |
| `test_mode_restriction_none_on_escalate_risk` | risk alto → escalate + field `None` |
| `test_mode_restriction_none_when_mode_not_supervised` | approve with `mode="autonomous"` → field `None` (no supervised rewrite applied) |
| `test_decision_mode_restriction_defaults_none` | construct `Decision(...)` without field → `mode_restriction_applied is None` |
| Keep existing | `test_never_returns_non_f1_actions`, `test_mode_never_produces_send_action`, `test_decider_source_has_no_mean_or_llm`, threshold boundary, safety priority |

**Do NOT:**
- Expand action Literal
- Assert naturalness → escalate/regenerate
- Touch composition / orchestrator
- Change reason string tokens

**Verification:**
```bash
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_decider.py \
  tests/unit/cognitive/test_models.py -k Decision
```
(Expect red on mode_restriction tests until Task 2.)

**Done:**
- [ ] Residual naturalness tests present (may already pass on current code)
- [ ] mode_restriction tests present (red until Task 2)
- [ ] Existing F1 locks still present in file

---

### Task 2: Decision field + Decider matrix audit + Director passthrough + F docstring
**type:** auto  
**Objective:** Green the Task 1 suite; document Anexo F mapping; keep matrix pure; Director preserves audit field when attaching draft.

**TDD order:** implement minimal production changes → green Task 1 suite → optional director assert → purity/net.

**Files (edit):**
- `src/diana/cognitive/models.py` — `Decision`
- `src/diana/cognitive/decider.py`
- `src/diana/cognitive/director.py` — Decision rebuild only
- `tests/unit/cognitive/test_decider.py` / `test_models.py` — only if Task 1 left them red
- Optional: `tests/unit/cognitive/test_director.py` — approve path `mode_restriction_applied == "supervised_send_to_approve"`

**Decision shape (exact intent):**

```python
class Decision(BaseModel):
    """F1 runtime decision — approve | escalate only.

    Maps Anexo F DecisorOutput: action←accion, reason←razon,
    mode_restriction_applied←restriccion_de_modo_aplicada.
    F2+ actions (send, regenerate, consult_doctrine) are out of F1.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "escalate"]
    reason: str
    evaluation: EvaluationProfile
    draft_text: str | None = None
    mode_restriction_applied: str | None = None
```

**Decider algorithm (exact intent — preserve order):**

```python
def decide(
    self,
    evaluation: EvaluationProfile,
    comprehension: Comprehension,
    *,
    mode: str = "supervised",
) -> Decision:
    # Never read draft text. Never LLM. Never mean/score collapse.
    if evaluation.safety < self._safety_threshold:
        return Decision(
            action="escalate",
            reason="safety_below_threshold",
            evaluation=evaluation,
            draft_text=None,
            mode_restriction_applied=None,
        )
    if comprehension.risk == "alto":
        return Decision(
            action="escalate",
            reason="risk_high",
            evaluation=evaluation,
            draft_text=None,
            mode_restriction_applied=None,
        )
    # F.3 #2 residual: naturalness gate not implemented → fall through here.
    restriction = (
        "supervised_send_to_approve" if mode == "supervised" else None
    )
    return Decision(
        action="approve",
        reason="ok_for_human_review",
        evaluation=evaluation,
        draft_text=None,
        mode_restriction_applied=restriction,
    )
```

**Decider module docstring (must include):**
- Single question: “what action to take?”
- English ↔ Anexo F map table (compact)
- Explicit residual sentence: *F.3 rule 2 (naturalness → regenerate) is not implemented in F1; fall-through is supervised approve.*
- F1 risk extension sentence: *risk==alto escalates after safety check.*
- F1 public actions only `approve|escalate`; raw `send` never returned.

**Director rebuild (exact intent):**

```python
base = self._decider.decide(evaluation, comprehension, mode="supervised")
decision = Decision(
    action=base.action,
    reason=base.reason,
    evaluation=base.evaluation,
    draft_text=draft,
    mode_restriction_applied=base.mode_restriction_applied,
)
```

**Do NOT:**
- Introduce public `send` intermediate type
- Gate approve on naturalness
- Wire `composition.py` thresholds
- Change orchestrator branches
- Import draft into Decider
- Alter reason tokens used by director tests

**Verification:**
```bash
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_decider.py \
  tests/unit/cognitive/test_models.py \
  tests/unit/cognitive/test_director.py -k "escalate or approve or tac01 or safety or risk or mode_restriction" \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/cognitive/test_evaluation_profile_invariants.py
```

**Done:**
- [ ] All Task 1 tests green
- [ ] `mode_restriction_applied` optional default None; set only on supervised approve
- [ ] Director preserves field when attaching draft
- [ ] Docstring maps Anexo F + residual F.3 #2
- [ ] `action` Literal still exactly approve|escalate
- [ ] No mean/LLM in decider source
- [ ] Import purity green

## Instrucciones para gsd-executor

- **Strict TDD:** write/adjust tests in Task 1 before production edits in Task 2.
- **Patterns to copy:** existing `test_decider.py` helpers `_profile` / `_comprehension`; Decision model tests in `test_models.py`.
- **Anti-patterns forbidden:**
  - Expanding `Decision.action` Literal
  - `mean()`, `overall_score`, `confidence` aggregation
  - Decider inspecting `draft_text` or message content
  - Naturalness → regenerate/escalate gate
  - Removing risk-alto escalate
  - Spanish field names in runtime models
  - Cognitive imports of telegram/behavior
- **Logging / errors:** Decider has no error path of its own (F.4); invalid profile already fails at EvaluationProfile validation upstream.
- **Commits:** prefer one work-unit after green suite, or Task1 tests + Task2 impl if split.
- **Mock policy:** no mocks; pure functions only.
- **Skills / project rules:** `AGENTS.md` §5.2–5.3 F1 restriction; BR-09 vector integrity; TAC-01 zero Decider LLM.
- **If already green for residual tests:** still add them (locks); only mode_restriction needs code.
- **Do not** “complete” by implementing regenerate “because Anexo F lists it”.

## Test commands

```bash
# Primary (this slice)
.venv/bin/python -m pytest -q tests/unit/cognitive/test_decider.py
.venv/bin/python -m pytest -q tests/unit/cognitive/test_models.py -k Decision
.venv/bin/python -m pytest -q tests/unit/cognitive/test_director.py -k "escalate or approve or tac01 or safety or risk"
.venv/bin/python -m pytest -q tests/unit/cognitive/test_import_purity.py
.venv/bin/python -m pytest -q tests/unit/cognitive/test_evaluation_profile_invariants.py

# Safety net if Director Decision rebuild touched
.venv/bin/python -m pytest -q tests/unit/application/test_turn_orchestrator.py -k "approve or escalate"
.venv/bin/python -m pytest -q tests/unit/acceptance/test_tac_mvp_f1.py

# Optional full unit
.venv/bin/python -m pytest -q tests/unit
```

## Risks + Mitigation

| Risk | Mitigation in tasks |
|------|---------------------|
| Expanding action set breaks orchestrator | L1 + existing model reject tests + never edit Literal |
| Implementing regenerate “for completeness” | L3 residual explicit; naturalness tests lock approve |
| Required field breaks fixtures | Optional default `None` only |
| Director drops audit field | Task 2 mandatory copy on rebuild |
| Removing risk_high | L2 + existing tests must stay green |
| Score collapse | Source scan test already in suite |

## Success Criteria

- [ ] Decider remains pure deterministic matrix; zero LLM
- [ ] `Decision.action` exactly `approve | escalate`
- [ ] Safety < threshold → escalate; risk alto → escalate; else approve
- [ ] Low naturalness alone does **not** change action (residual F.3 #2 documented + tested)
- [ ] Supervised approve sets `mode_restriction_applied == "supervised_send_to_approve"`; escalate → `None`
- [ ] Director attaches draft and preserves `mode_restriction_applied`
- [ ] Reason tokens unchanged
- [ ] Primary pytest commands green
- [ ] No-touch list respected (no Behavior/Generator/composition threshold wire)
- [ ] Import purity + evaluation profile invariants green

## Residual (explicit ticket text for later)

> **F.3 rule 2 naturalness→regenerate deferred.** F1 fall-through = supervised approve. Do not implement Director regenerate loop, public `regenerate` action, or `naturalness_min` action gate until a dedicated F2+ decision. Composition wiring of `system_config.eval_thresholds.safety` into `Decider(thresholds=...)` is a separate optional ops item (L6 later).

## Handoff

**Next agent:** `gsd-executor`  
**Plan path:** `.planning/quick/decider-contract/PLAN.md`  
**Start at:** Task 1 (tests first)  
**Stop condition:** Success Criteria checklist complete + primary pytest green
