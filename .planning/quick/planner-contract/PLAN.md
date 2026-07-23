---
phase: quick
plan: planner-contract
type: auto
item: planner-contract (Pool remaining-contracts-cognitive · 1/4)
effort: 4
stack: python>=3.12, pydantic-v2, pytest
depends_on: analyst-contract (Comprehension needs_* required + legal emotion)
source_of_truth: docs/contratos_restantes.md Anexo C (C.1–C.4 only)
impact: .grok/agent-memory/impact-analyzer/planner-contract.md
mode: standard
---

## Objective

Align the **Planner runtime** to `docs/contratos_restantes.md` Anexo C (C.1–C.4): pure deterministic map from `Comprehension.needs_*` → ordered `Plan.capabilities` (`knowledge.*`), **never** request a capability when its `needs_*` is false (remove illegal force-history insert), allow empty `[]` when all needs are false, keep stable `_NEED_TO_CAPABILITY` order — without LLM, without Planner error path, without expanding F1 `Decision.action`, and without inventing `needs_profile` / `knowledge.profile` in F1.

## Scope

- **In:**
  - `Planner.plan(comprehension)` C.3 minimum-knowledge (no force-history)
  - Unit tests locking C.2 mapping, C.3 omit/empty/determinism, C.4 set equality with stable order
  - Optional `Plan` docstring map: English `capabilities` ← Spanish `capacidades_solicitadas`
  - Optional Director path assert: `needs_history=false` → plan/retrieved omit `knowledge.history`
- **Out / Non-goals:**
  - Anexos D–I (ContextBuilder, Generator, Decider, Registry contract rewrite, etc.)
  - New `PlannerInput` DTO (single `Comprehension` arg is sufficient — C.2 input shape)
  - Spanish rename of `Plan.capabilities` or capability strings
  - Planner error path / orchestrator notify for Planner
  - Re-introducing force-history to match outdated `docs/MVP_COMPONENT_DESIGN.md` §5.6
  - Telegram / Behavior / Learning / Decider / Analyst / Evaluator code changes
  - Dirty-tree WIP: alembic `turns.error` residual, unrelated `.grok/agent-memory/**`
  - F1 `Decision.action` expansion beyond `approve|escalate`
  - Inventing `needs_profile` or requesting `knowledge.profile` in F1
- **Constraints:** Strict TDD; FakeLLM/InMemory only; cognitive never imports telegram/behavior; 0-behavior outside Planner contract alignment

## Assumptions

- A1: Director `for cap in plan.capabilities` already tolerates `[]` (empty retrieved map) — no Director production change required for empty plan (impact confirmed).
- A2: Analyst still injects short `historial_reciente` for classification; removing plan-side force-history does **not** remove Analyst history (separate path).
- A3: C.4 JSON example is a **set** of capabilities; authoritative **list order** is `_NEED_TO_CAPABILITY` (history→context→memory→policy→examples→schedule).
- A4: Registry stubs already resolve unrequested caps by omission (never auto-add history) — no registry change.
- A5: Optional director blast test is recommended for blast-radius; if fixture cost is high, Task 1 unit tests alone prove C.3 for Planner — still prefer Task 2 when cheap.

## Architecture Approach

### QUÉ (behavior / contracts)

| Contract | Runtime truth after this item |
|----------|-------------------------------|
| C.1 | Planner answers only “what knowledge to recover?” — pure fn of `Comprehension`; no LLM; no risk decision; no prompt assembly |
| C.2 input | `plan(self, comprehension: Comprehension) -> Plan` (no multi-field DTO) |
| C.2 output | `Plan.capabilities: list[str]` English; Spanish `capacidades_solicitadas` only in docs/docstring |
| C.2 map | Exactly 6 flags → 6 capabilities (table below); schedule always requestable when `needs_schedule=true` |
| C.3 | Cap present **iff** corresponding `needs_*=true`; never insert when false |
| C.3 empty | All six false → `capabilities == []` |
| C.3 determinism | Same comprehension → same plan (call twice, equal) |
| C.3 errors | No try/except / no typed Planner error / no orchestrator notify |
| C.4 | Example set equality; order = stable map, not C.4 example list order |

**C.2 mapping table (locked L2):**

| `needs_*` | capability |
|-----------|------------|
| `needs_history` | `knowledge.history` |
| `needs_context` | `knowledge.context` |
| `needs_memory` | `knowledge.memory` |
| `needs_policy` | `knowledge.policy` |
| `needs_examples` | `knowledge.examples` |
| `needs_schedule` | `knowledge.schedule` |

**Stable order (locked L5):** history → context → memory → policy → examples → schedule (current `_NEED_TO_CAPABILITY` tuple).

**Intentional behavior change:** turns with `needs_history=false` no longer force `knowledge.history` into the plan; Registry does not fetch history for the Generator knowledge block. Analyst short history path unchanged.

### CÓMO (structure / patterns)

- **Placement:** Cognitive Core only — `src/diana/cognitive/planner.py` (+ optional docstring on `Plan` in `models.py`). No application/telegram/behavior.
- **Pattern to copy:**
  - Structure/PLAN shape: `.planning/quick/evaluator-contract/PLAN.md` + `.planning/quick/analyst-contract/PLAN.md`
  - Implementation style: keep pure `Planner.plan` loop over `_NEED_TO_CAPABILITY`; **delete** force-insert block only
  - Tests gold: existing `tests/unit/cognitive/test_planner.py` helpers (`_comprehension`) — invert force tests; do not invent FakeLLM for Planner (no LLM)
- **File map:**
  - **Edit:** `src/diana/cognitive/planner.py`, `tests/unit/cognitive/test_planner.py`
  - **Edit optional:** `src/diana/cognitive/models.py` (`Plan` docstring only), `tests/unit/cognitive/test_director.py` (one path)
  - **No-touch:** telegram/**, behavior/**, learning/**, analyst/evaluator/decider/generator (except director test fixture), alembic/**, dirty WIP
- **Interfaces first:** none — `Plan` and `plan(comprehension)` already exist; no new public types required
- **Wiring:** Director call site `self._planner.plan(comprehension)` unchanged; composition `Planner()` unchanged
- **Verificación:** pytest with `.venv/bin/python -m pytest -q …` per task; full `tests/unit` before handoff
- **Riesgos:** R1 thinner Generator context when history false (contract-intended); R2 empty plan; R3 tests currently lock anti-contract force-history — invert under TDD

### English ↔ Anexo C mapping (docs/docstring only)

| Runtime (English) | Anexo C (Spanish) |
|-------------------|-------------------|
| `Comprehension` | `comprension` / `ComprensionObject` |
| `Plan.capabilities` | `capacidades_solicitadas` |
| `Planner.plan` | Planificador pure map |
| `knowledge.*` | capability names (same strings in contract) |

## Locked decisions (NON-NEGOTIABLE)

| ID | Decision |
|----|----------|
| L1 | English `Plan.capabilities` stays; Spanish `capacidades_solicitadas` only in docs/docstring map |
| L2 | C.2 mapping table exactly as Anexo (6 needs_* → knowledge.*) — no `needs_profile` in F1 |
| L3 | **Remove force-history** insert — never request capability when `needs_*=false` |
| L4 | Empty plan `[]` is legal when all needs_* false; Director must tolerate (already does) |
| L5 | Stable capability order = `_NEED_TO_CAPABILITY` order (history→context→memory→policy→examples→schedule); C.4 example is **set**, not list order |
| L6 | No Planner error path / no orchestrator notify for Planner |
| L7 | F1 `Decision.action` stays `approve\|escalate` — out of scope |
| L8 | Cognitive never imports telegram/behavior |
| L9 | Strict TDD; FakeLLM/InMemory only (Planner itself needs neither) |
| L10 | Do not touch dirty tree: turns.error alembic residual, unrelated WIP |
| L11 | Anexos D–I out of scope |

## Context

@`.grok/agent-memory/impact-analyzer/planner-contract.md`
@`docs/contratos_restantes.md` (Anexo C only)
@`.planning/quick/evaluator-contract/PLAN.md` (structure gold)
@`.planning/quick/analyst-contract/PLAN.md` (structure gold; residual deferred force-history)
@`AGENTS.md` (§3 Cognitive Core, §5.1 Director deterministic, capability registry via names)
@`src/diana/cognitive/planner.py` (force-history at lines 32–33 — **remove**)
@`src/diana/cognitive/models.py` (`Plan`)
@`src/diana/cognitive/director.py` (`plan = self._planner.plan(comprehension)` ~118; `for cap in plan.capabilities`)
@`tests/unit/cognitive/test_planner.py`
@`tests/unit/cognitive/test_director.py` (happy path still expects history+context when both needs true)
@`tests/unit/cognitive/test_import_purity.py`

## Tasks

### Task 1: C.3 unit contract — omit when false + empty plan + remove force-history
**type:** auto  
**Objective:** Planner requests only capabilities whose `needs_*` is true; all-false → `[]`; force-history path deleted; determinism and C.4 set locked in unit tests.

**TDD order (mandatory):**
1. Rewrite/extend `tests/unit/cognitive/test_planner.py` so force-history tests fail against current code (**RED**).
2. Edit `src/diana/cognitive/planner.py` — remove force-insert (**GREEN**).
3. Optional same-commit: `Plan` docstring map in `models.py`.
4. Run primary slice green.

**Files (edit):**
- `tests/unit/cognitive/test_planner.py` **(edit)**
- `src/diana/cognitive/planner.py` **(edit)**
- Optional: `src/diana/cognitive/models.py` — `Plan` docstring only:
  ```python
  class Plan(BaseModel):
      """Planner output (Anexo C.2): which knowledge capabilities to retrieve.

      English field ``capabilities`` maps to Spanish contract name
      ``capacidades_solicitadas``. Empty list is legal when all needs_* are false.
      """
  ```

**Production change (exact intent) — `planner.py`:**

After edit, `plan` must be equivalent to:

```python
def plan(self, comprehension: Comprehension) -> Plan:
    capabilities: list[str] = []
    for attr, cap in _NEED_TO_CAPABILITY:
        if getattr(comprehension, attr, False):  # or direct getattr without default if preferred
            capabilities.append(cap)
    return Plan(capabilities=capabilities)
```

**Must remove:**
- `_HISTORY_CAP` constant (if unused after delete)
- Block:
  ```python
  if _HISTORY_CAP not in capabilities:
      capabilities.insert(0, _HISTORY_CAP)
  ```

**Keep:**
- `_NEED_TO_CAPABILITY` order and all six mappings unchanged
- Module note that `knowledge.profile` is F2-only / not planned
- No LLM imports; no try/except; no new exceptions
- Optional docstring on module/class citing C.1–C.3 single-question + minimum knowledge

**Tests — replace / add (must exist after task):**

| Action | Test name | Assert |
|--------|-----------|--------|
| **Keep** | `test_planner_maps_default_needs_to_history_and_context` | default helper → `["knowledge.history","knowledge.context"]` |
| **Keep** | `test_planner_includes_all_needs_in_stable_order` | all true → full six in map order |
| **REPLACE** | `test_planner_inserts_history_first_when_missing` → `test_planner_omits_history_when_needs_history_false` | `needs_history=False`, `needs_context=True`, `needs_memory=True` → `["knowledge.context","knowledge.memory"]` — **no** `knowledge.history` |
| **REPLACE** | `test_planner_forces_history_even_when_all_false` → `test_planner_returns_empty_when_all_needs_false` | all six false → `capabilities == []` |
| **Keep** | `test_planner_has_no_llm_dependency` | source has no `LLM` / `generate` |
| **Add** | `test_planner_never_requests_cap_when_need_false` | For each of the six flags: set only that flag false (others true) → corresponding cap **absent**; or multi-assert table. Prefer parametrize if style fits. |
| **Add** | `test_planner_determinism_same_comprehension_same_plan` | two `plan()` calls on same object → `plan1.capabilities == plan2.capabilities` (and preferably `plan1 == plan2`) |
| **Add** | `test_planner_c4_example_set` | memory/schedule/examples/history/context true, policy false → **set** equals C.4 set; **list** equals stable order: `["knowledge.history","knowledge.context","knowledge.memory","knowledge.examples","knowledge.schedule"]` (policy absent) |

Helper `_comprehension` stays; defaults may remain `needs_history=True, needs_context=True` for the first keep-test.

**Do NOT:**
- Re-introduce force-history for “MVP operational minimum”
- Special-case empty plan in Director/Registry
- Add `PlannerInput` DTO
- Request `knowledge.profile`
- Change Analyst/Evaluator/Decider
- Touch alembic / dirty tree

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q tests/unit/cognitive/test_planner.py
```

**Done:**
- [ ] No force-history code path remains in `planner.py`
- [ ] `needs_*=false` never yields that capability
- [ ] All false → `[]`
- [ ] Determinism + C.4 set tests green
- [ ] Command above green

**Commit (work unit 1):**
```
fix(cognitive): Planner omits caps when needs_* is false (Anexo C.3)
```
Include tests + production change in the **same** commit (work-unit-commits).

---

### Task 2: Director blast path (needs_history=false) + full unit gate
**type:** auto  
**Objective:** Prove Director/Registry respect a plan without history when Analyst marks `needs_history=false`; no production Director change unless a real bug appears; full unit suite green.

**TDD order:**
1. Add one director test (**RED** only if production already wrong — with Task 1 done, test should go green if Director only iterates `plan.capabilities`).
2. If RED for unexpected reason: fix only the documented cause (must not re-force history). Prefer no production edit.
3. Full unit gate.

**Files (edit):**
- `tests/unit/cognitive/test_director.py` **(edit)** — one new test
- Production: **no-touch expected** (`director.py` already tolerates empty/partial plans)

**Test (must add):**

`test_director_plan_omits_history_when_needs_history_false`

- Use existing `make_director` + FakeLLM structured queue that returns a full valid `Comprehension` with:
  - `needs_history=False`
  - `needs_context=True`
  - other needs false (or only context true)
- Valid draft text + valid `EvaluationProfile` for pipeline completion (same pattern as other happy-path director tests).
- After `handle_turn`:
  - `trace["plan"]["capabilities"]` does **not** contain `"knowledge.history"`
  - contains `"knowledge.context"`
  - `retrieved` keys match plan only (no history key)
- Optional: TAC-01 style call count still 3 structured/text ops on happy path if full pipeline runs.
- Do **not** assert force-history anywhere.

**Keep green without edits (confirm only):**
- `test_director` paths that use default comprehension with both history+context true (still `["knowledge.history","knowledge.context"]`)
- `tests/unit/cognitive/test_import_purity.py`
- Orchestrator fixtures that set `needs_history=True` (no change expected)

**Do NOT:**
- Hardcode history in Director or Registry to “fix” thinner context
- Expand Decision.action
- Import telegram/behavior into cognitive
- Rewrite MVP_COMPONENT_DESIGN.md in this item

**Verification (director + purity + planner):**
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_models.py \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/cognitive/test_registry.py \
  tests/unit/cognitive/test_context_builder.py
```

**Full unit gate (required before handoff done):**
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q tests/unit
```

**Done:**
- [ ] Director path proves omit-history when `needs_history=false`
- [ ] No production re-force of history
- [ ] Import purity green
- [ ] Full `tests/unit` green

**Commit (work unit 2, if test file only):**
```
test(cognitive): Director omits knowledge.history when needs_history is false
```

If Task 2 adds zero production code, a single `test(...)` commit is correct.

---

## Instrucciones para gsd-executor

### Patterns to copy
- **Pure planner loop:** `src/diana/cognitive/planner.py` — keep `_NEED_TO_CAPABILITY` iteration; delete only force-insert.
- **Test helper:** `_comprehension(**overrides)` in `test_planner.py` — full six `needs_*` + legal emotion (`neutral`).
- **Director factory:** `make_director` in `test_director.py` — FakeLLM structured queue with full valid `Comprehension` (post-analyst-contract: required needs + emotion enum).
- **Contract alignment style:** evaluator/analyst plans — English identifiers; Spanish only in docstring map comments.
- **Import purity:** re-run `tests/unit/cognitive/test_import_purity.py` after any cognitive edit.

### Anti-patterns (reject if you introduce them)
- Force-insert / always-include `knowledge.history` “for operational minimum”
- Compensating hardcode of history in Director, Registry, or ContextBuilder
- Requesting `knowledge.profile` or adding `needs_profile` in F1
- Planner try/except, typed Planner errors, orchestrator notify for Planner
- Renaming `capabilities` → Spanish field name
- Asserting list equality against C.4 example **order** (use set for C.4; list for stable map order)
- Expanding `Decision.action` or Decider thresholds
- Cognitive importing `diana.telegram` / `diana.behavior` / aiogram
- Live network / real LLM in unit tests
- Touching alembic / dirty-tree residual
- Co-Authored-By / AI attribution in commits
- Implementing production code before RED tests for Task 1

### Strict TDD sequence (mandatory)
1. Task 1: invert/add `test_planner.py` → RED → remove force-history → GREEN → commit work unit  
2. Task 2: director omit-history test → green (no prod change expected) → full unit gate → commit if tests added  
3. Do not mark item done until full `tests/unit` green

### AGENTS.md invariants to preserve
- Director remains 100% deterministic sequencer (Planner stays pure, no LLM control).
- Planner single question only: what knowledge to recover.
- Behavior outside cognition; Learning post-turn only.
- Capability Registry resolves only requested names (minimum knowledge).
- Cognitive Core does not import telegram/behavior.

### Commits (hybrid policy / work-unit-commits)
- One commit = one deliverable behavior (tests with the code they lock).
- Suggested:
  1. `fix(cognitive): Planner omits caps when needs_* is false (Anexo C.3)`
  2. `test(cognitive): Director omits knowledge.history when needs_history is false`
- Conventional commits only; no AI attribution trailers.
- Do not commit unrelated dirty-tree files.

### Logging
Append progress to `.planning/quick/gsd-executor-planner-contract.log` with task start/end + pytest results.  
Planner log: `.planning/quick/gsd-planner-planner-contract.log`.

### Skills
- Work-unit commits: tests with behavior; no file-type split commits.
- Strict TDD active: test runner `.venv/bin/python -m pytest -q`.

## Test commands

### Primary slice (TDD loop)
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q tests/unit/cognitive/test_planner.py
```

### Cognitive regression slice
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_models.py \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/cognitive/test_registry.py \
  tests/unit/cognitive/test_context_builder.py
```

### Full unit gate (required before handoff done)
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q tests/unit
```

### Sensitive / gold re-runs after change
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_planner.py
```

## Risks + Mitigation

| Risk | Level | Mitigation |
|------|-------|------------|
| R1 — Generator prompt thinner when `needs_history=false` | Medium | Contract-intended (C.3). Analyst still gets short history. Task 2 asserts plan/retrieved omit history; do not re-force. |
| R2 — Empty `Plan.capabilities` first-class | Medium | Director loop already safe. Unit test all-false → `[]`. No “always request something” special case. |
| R3 — Tests lock anti-contract force-history | Medium | Task 1 replaces those tests under Strict TDD before/with impl. |
| R4 — C.4 order vs stable order confusion | Low | Assert set for C.4; list for `_NEED_TO_CAPABILITY` order (L5). |
| R5 — MVP_COMPONENT_DESIGN still says force history | Low | Out of scope docs residual; Anexo C supersedes; do not re-introduce force. |
| R6 — Compensating history elsewhere | Medium | Explicit anti-pattern; arch-enforcer checks minimum-knowledge. |
| R7 — Dirty tree pollution in commits | Low | L10: never stage alembic residual / unrelated WIP. |

## Success Criteria

- [ ] Planner is pure deterministic map; no LLM; no own error path
- [ ] Force-history insert removed from `planner.py`
- [ ] Never includes a capability when corresponding `needs_*` is false
- [ ] All six needs false → `capabilities == []`
- [ ] Stable order = history→context→memory→policy→examples→schedule among present caps
- [ ] C.4 example covered as **set** equality with stable list order
- [ ] Determinism: same comprehension → same plan
- [ ] English `Plan.capabilities` retained; Spanish only in docs/docstring
- [ ] No `needs_profile` / no planned `knowledge.profile` in F1
- [ ] Director tolerates omit-history / empty plan without production hacks
- [ ] Cognitive import purity green
- [ ] F1 `Decision.action` still only `approve|escalate`
- [ ] `.venv/bin/python -m pytest -q tests/unit` green
- [ ] No telegram/behavior/learning/alembic/dirty-WIP edits

## Residuals / out of scope (do not touch)

1. Anexos D–I contract alignment (separate pool items).
2. `docs/MVP_COMPONENT_DESIGN.md` / SPEC wording that still mention force-history (documentador residual).
3. `needs_profile` / `knowledge.profile` F2 hook activation.
4. PlannerInput multi-field DTO (unnecessary).
5. Registry / ContextBuilder / Generator redesign.
6. Decider matrix / Decision.action expansion.
7. Telegram, Behavior Engine, Learning, Staging.
8. Alembic / `turns.error` dirty residual.
9. Orchestrator notify paths (Planner has none).

## Self-check checklist for executor

Before marking the item done, confirm:

- [ ] TDD order followed (RED force-history tests before deleting insert)
- [ ] L1–L11 locked decisions respected (especially L3 remove force, L4 empty legal, L5 order)
- [ ] No test still asserts forced history
- [ ] Import purity green
- [ ] Full unit suite green
- [ ] Conventional commits only; no AI attribution
- [ ] No production scope creep into Director/Registry/Telegram
- [ ] Dirty-tree files not staged
