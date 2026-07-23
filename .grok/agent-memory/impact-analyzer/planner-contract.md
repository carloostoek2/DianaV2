# Impact Analysis: Align Planner contract to Anexo C (`docs/contratos_restantes.md`)

**Date:** 2026-07-23  
**Change:** Align Planner runtime + Plan mapping invariants to Anexo C (C.1–C.4)  
**Analysis only** — no implementación  
**Source of truth:** `/home/ubuntu/repos/DianaV2/docs/contratos_restantes.md` § Anexo C only  
**Pattern reference:** `.planning/quick/analyst-contract/`, `.planning/quick/evaluator-contract/`  
**Pool:** remaining-contracts-cognitive · ITEM 1/4 · effort 4  

---

## Executive Summary

The Planner is already a pure, deterministic, no-LLM mapper from `Comprehension.needs_*` → ordered capability names. Signature, English identifiers (`Plan.capabilities`), composition wiring (`Planner()`), and Director call site (`self._planner.plan(comprehension)`) are largely correct for C.1–C.2.

**Confirmed C.3 violation (primary change):** `src/diana/cognitive/planner.py` force-inserts `knowledge.history` when `needs_history` is false (and even when *all* `needs_*` are false). Unit tests currently **lock** that anti-contract behavior (`test_planner_inserts_history_first_when_missing`, `test_planner_forces_history_even_when_all_false`). Aligning to C.3 means **removing** that force path and inverting those tests.

**Global risk: low–medium.** Blast radius is small (one pure function + tests). Runtime behavior *does* change for turns where Analyst sets `needs_history=false` (e.g. trivial greetings per `contrato_analista.md`): Registry will not fetch `knowledge.history`, so the Generator prompt will not include that knowledge block. This is **intentional** under C.3 “mínimo conocimiento necesario.” Mitigating fact: Analyst already receives short `historial_reciente` on a **separate** path (`CognitiveDirector._build_analyst_input`, limit 8); only the **retrieval/plan** path loses forced history.

**Sensitive systems:** deterministic Director control flow; minimum-knowledge invariant; cognitive import purity (no telegram/behavior); F1 Decision.action remains `approve|escalate` (out of scope). No new error path, no orchestrator notify, no LLM, no migrations.

**Scope is valid and tight.** No re-partition required. Other anexos (D–I) out of scope. Do **not** touch dirty-tree WIP (turns.error alembic residual, unrelated agent-memory).

---

## Gap verification (contract vs code)

| Gap | Contract (Anexo C) | Current code | Status |
|-----|--------------------|--------------|--------|
| C.1 single question | “what knowledge to recover?” pure fn of Comprehension | Docstring + pure `plan()`; no LLM | **OK** — keep |
| C.1 not risk / not how-to-use | No risk decision; no prompt assembly | Planner only maps flags | **OK** |
| C.2 input | PlanificadorInput `{ comprension }` | `plan(self, comprehension: Comprehension)` | **OK** — no multi-field DTO needed (unlike Analyst/Evaluator) |
| C.2 output | `capacidades_solicitadas: string[]` | `Plan.capabilities: list[str]` | **OK** — English field; map Spanish name in docstring only (analyst/evaluator pattern) |
| C.2 mapping table | 6 fixed `needs_*` → `knowledge.*` | `_NEED_TO_CAPABILITY` tuple matches all 6 | **OK** |
| C.2 schedule always requestable | May stub later; still requestable | Maps to `knowledge.schedule`; registry has STUB | **OK** |
| C.2 profile | Not in C.2 table | Not requested (no `needs_profile`); registry still has F2 hook | **OK** — keep comment |
| C.3 never request if needs_*=false | Strict minimum knowledge | **Force-inserts history** | **CONFIRMED gap** |
| C.3 determinism | same Comprehension → same plan | Pure function; stable order | **OK** after force removal |
| C.3 no own error path | null comprehension = Director bug | No try/except; getattr defaults only on missing attr | **OK** — prefer direct attr access if tightening (all six required post-analyst-contract) |
| C.4 example set | memory, schedule, examples, history, context | Would match set after map | **OK** set-wise |
| C.4 example order | memory… then history… | Code order: history, context, memory, policy, examples, schedule | **Document** — C.4 is illustrative set; **stable code/MVP order is authoritative** for determinism |

### Forced-history evidence

```32:34:src/diana/cognitive/planner.py
        if _HISTORY_CAP not in capabilities:
            capabilities.insert(0, _HISTORY_CAP)
        return Plan(capabilities=capabilities)
```

Also documented as intentional in outdated `docs/MVP_COMPONENT_DESIGN.md` §5.6 (“Siempre asegurar history como mínimo operativo”). **Anexo C supersedes that** for this hardener item. Residual MVP doc drift is **out of scope** unless a later documentador pass.

Prior pools explicitly deferred this: analyst-contract `SUMMARY.md` residual + PLAN L15 “Planner force-history behavior” out of scope.

---

## Consumers / Call Sites Map

### Production — Planner / Plan

| Location | Role | Impact |
|----------|------|--------|
| `src/diana/cognitive/planner.py:12-34` | Mapping + **illegal force-history** | **EDIT** — remove force; keep ordered map |
| `src/diana/cognitive/models.py:141-146` | `Plan(capabilities: list[str])` | Optional docstring only (`capacidades_solicitadas` map); no schema rename |
| `src/diana/cognitive/director.py:117-126` | `plan = self._planner.plan(comprehension)` then `for cap in plan.capabilities` | **Tolerate `[]`** — loop already safe; no code change required if empty plan is OK |
| `src/diana/cognitive/director.py:115-119` | Trace store `plan` after plan | Stores whatever capabilities list results |
| `src/diana/composition.py:178` | `planner=Planner()` | No DI change |
| `src/diana/cognitive/registry.py` | Resolves only **requested** caps | No change; never auto-adds history |
| `src/diana/cognitive/context_builder.py` | Builds prompt from retrieved map | Omits null-like; empty map → persona+turn+comprehension only — **OK** |
| Retrievers (`history.py`, etc.) | Only run if planned | When `needs_history=false`, history retriever **not called** |

### Production — do NOT touch (out of scope / no Planner contract)

| Location | Why |
|----------|-----|
| Analyst / `AnalystInput` / A.6 | Already done; supplies `needs_*` |
| Evaluator / Decider / Generator | Consume later pipeline stages |
| Behavior / Telegram | Cognitive never imports them |
| Learning post-turn | After decision |
| Alembic / `turns.error` ORM residual | Dirty tree — **leave alone** |
| Anexos D–I (ContextBuilder contract, Generator, …) | Separate pool items |

### Tests — lock / invert / add

| Location | Role |
|----------|------|
| `tests/unit/cognitive/test_planner.py` | **Primary** — invert force-history tests; add C.3 + determinism + empty-plan |
| `tests/unit/cognitive/test_director.py:221-224` | Asserts default plan `["knowledge.history","knowledge.context"]` — still valid if fixture keeps both needs true |
| `tests/unit/cognitive/test_director.py:290-298` | All-needs-true order — still valid |
| `tests/unit/cognitive/test_models.py:294-298` | Plan shape — optional empty-list accept test |
| `tests/unit/application/test_turn_orchestrator.py` | Uses `Planner()` with fixtures that set `needs_history=True` — **no change expected** |
| `tests/unit/cognitive/test_import_purity.py` | Boundary — keep green |
| Acceptance TAC | Unlikely to assert forced history; re-run full unit as gate |

---

## Risks

### Critical

None for architecture (no layer breach required). The force-history removal is a **product/contract alignment** change, not a security hole.

### Medium

| Risk | Why | Mitigation |
|------|-----|------------|
| **R1 — Generator context thinner when `needs_history=false`** | History knowledge block no longer forced into prompt | Contract-intended. Analyst still gets short history for classification. Add director/unit test: `needs_history=False` → plan lacks `knowledge.history` → retrieved keys match plan only. |
| **R2 — Empty `Plan.capabilities` first-class** | All `needs_*` false → `[]` | Director `for cap in plan.capabilities` is safe. Assert empty retrieved map + non-empty prompt still builds. Do **not** special-case “always request something.” |
| **R3 — Tests encode anti-contract behavior** | Force-history tests will fail red-first under TDD | Rewrite as C.3 invariants (never include when false; empty when all false). |

### Low

| Risk | Why | Mitigation |
|------|-----|------------|
| **R4 — C.4 order vs stable order** | Example lists caps in non-MVP order | Lock **stable `_NEED_TO_CAPABILITY` order** (history→context→memory→policy→examples→schedule). Assert **set equality** against C.4 if needed, not list identity to C.4 example order. |
| **R5 — `getattr(..., False)` soft-default** | Post-analyst, all needs are required on model | Prefer `getattr` only if keeping defensive style; direct attribute access is fine and fails loud on broken Comprehension (Director bug per C.3). |
| **R6 — MVP_COMPONENT_DESIGN / SPEC residual force-history** | Docs contradict Anexo C | Out of scope for code item; note for documentador; do not “fix” by re-introducing force to match old design doc. |
| **R7 — knowledge.profile** | Registered but never planned | Keep; do not invent `needs_profile` in F1. |

### Non-risks (explicit)

- No new typed exception / orchestrator notify (C.3: no own error path).
- No Decision.action expansion.
- No Decider threshold changes.
- No Registry rewrite.
- No migration / SQL.

---

## Affected Tests

### Must change (red → green under Strict TDD)

**File:** `tests/unit/cognitive/test_planner.py`

| Current test | After alignment |
|--------------|-----------------|
| `test_planner_maps_default_needs_to_history_and_context` | Keep (needs true) |
| `test_planner_includes_all_needs_in_stable_order` | Keep |
| `test_planner_inserts_history_first_when_missing` | **REPLACE** → `test_planner_omits_history_when_needs_history_false` (capabilities must **not** contain `knowledge.history`; remaining caps only for true flags; stable order among present) |
| `test_planner_forces_history_even_when_all_false` | **REPLACE** → `test_planner_returns_empty_when_all_needs_false` (`capabilities == []`) |
| `test_planner_has_no_llm_dependency` | Keep; optionally tighten to ban any “force” narrative if desired |

**Recommended new tests (same file):**

1. `test_planner_never_requests_cap_when_need_false` — parametric or multi-assert: each false flag excludes its capability.
2. `test_planner_determinism_same_comprehension_same_plan` — call twice, `assert plan1 == plan2`.
3. `test_planner_c4_example_set` — needs_memory/schedule/examples/history/context true, policy false → set equals C.4; order = stable map order:
   `["knowledge.history","knowledge.context","knowledge.memory","knowledge.examples","knowledge.schedule"]`  
   (policy absent; schedule still present when true).

**Optional (recommended for blast-radius):**

- `tests/unit/cognitive/test_director.py`: one path with FakeLLM comprehension `needs_history=False, needs_context=True` → plan/retrieved keys omit history; TAC-01 style LLM count still 3 if full pipeline runs.

### Commands (exact)

Primary slice (TDD loop):

```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q tests/unit/cognitive/test_planner.py -q
```

Director + purity regression:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_models.py \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/cognitive/test_registry.py \
  tests/unit/cognitive/test_context_builder.py
```

Full unit gate (pre-handoff / arch-enforcer / guardian):

```bash
.venv/bin/python -m pytest -q tests/unit
```

Strict TDD: **active** — write/adjust failing tests first, then remove force-history lines.

---

## Files Map

### Edit (expected)

| File | Change |
|------|--------|
| `src/diana/cognitive/planner.py` | Remove `_HISTORY_CAP` force-insert; optional C.1–C.3 module docstring; keep `_NEED_TO_CAPABILITY` order |
| `tests/unit/cognitive/test_planner.py` | Invert force tests; add C.3/determinism/empty/C.4-set |

### Edit (optional, small)

| File | Change |
|------|--------|
| `src/diana/cognitive/models.py` | `Plan` docstring: map `capabilities` ← `capacidades_solicitadas` (Anexo C.2) |
| `tests/unit/cognitive/test_director.py` | Optional integration assert for `needs_history=False` |
| `tests/unit/cognitive/test_models.py` | Optional `Plan(capabilities=[])` accept |

### Create (process only — gsd-planner / later phases)

| File | Owner |
|------|-------|
| `.planning/quick/planner-contract/PLAN.md` | gsd-planner |
| `.planning/quick/planner-contract/decisions.md` | gsd-planner / executor |
| `.planning/quick/planner-contract/SUMMARY.md` | documentador / close |

### No touch

- `src/diana/telegram/**`, `src/diana/behavior/**`, `src/diana/learning/**`
- `src/diana/cognitive/analyst.py`, `evaluator.py`, `decider.py`, `generator.py` (unless fixture-only)
- `src/diana/application/turn_orchestrator.py` (no Planner error path)
- `alembic/**`, `src/diana/infrastructure/db/**` dirty residual
- Other anexos work in `docs/contratos_restantes.md` D–I
- Unrelated `.grok/agent-memory/**` from prior pools

---

## Recommended work-unit split (for gsd-planner)

Effort 4 total — prefer **1–2 commits**, tests with code:

1. **WU1 (core):** Remove force-history + rewrite `test_planner.py` C.3 invariants (+ optional Plan docstring).  
   Message sketch: `fix(cognitive): Planner omits caps when needs_* is false (Anexo C.3)`
2. **WU2 (optional blast):** Director path test for `needs_history=false` if not already covered by unit isolation.

Single PR is fine (well under 400-line budget). No chained PR needed.

### Locked decisions to propose (handoff)

| ID | Decision |
|----|----------|
| L1 | Remove forced `knowledge.history`; never request cap when corresponding `needs_*` is false |
| L2 | Empty plan `[]` is valid when all needs false |
| L3 | Stable capability order remains `_NEED_TO_CAPABILITY` order (not C.4 example list order) |
| L4 | English identifiers: `Plan.capabilities`, capability names `knowledge.*`; Spanish only in docs/comments |
| L5 | No `PlannerInput` DTO required (input is single `Comprehension`) |
| L6 | No Planner error path / no orchestrator notify branch |
| L7 | F1 `Decision.action` stays `approve\|escalate` |
| L8 | Do not invent `needs_profile` / do not request `knowledge.profile` |
| L9 | Out of scope: Anexos D–I, MVP design doc rewrite, dirty-tree alembic |
| L10 | Strict TDD; FakeLLM/in-memory only |

---

## DoD for downstream

### gsd-planner

- [ ] PLAN.md with objective = Anexo C only; locked L1–L10 above
- [ ] Tasks: (1) tests C.3 + empty + determinism, (2) remove force-history, (3) optional director blast test
- [ ] Explicit **out of scope** list (D–I, telegram, force reintroduction via “MVP design says so”)
- [ ] Test commands copied from this report
- [ ] Work units ≤400 lines; single PR

### executor (sdd-apply / implementer)

- [ ] Red tests first for force-history removal
- [ ] Delete `_HISTORY_CAP` insert block (and constant if unused)
- [ ] Do not “compensate” by hardcoding history in Director/Registry
- [ ] Keep import purity
- [ ] No production edits outside Files Map Edit set

### arch-enforcer

- [ ] Cognitive still has no telegram/behavior/learning imports
- [ ] Director remains deterministic sequencer
- [ ] Planner has zero LLM / generate calls
- [ ] Minimum-knowledge: plan never contains cap for false needs
- [ ] No new module-boundary violations

### test-guardian

- [ ] No tests that re-assert forced history
- [ ] Coverage of empty plan + selective omit
- [ ] Determinism asserted
- [ ] No prohibited mocks (no live network); FakeLLM OK where used
- [ ] Primary slice green; full `tests/unit` green

---

## Ready for chain

**Status:** READY  
**Handoff:** gsd-planner  
**Scope:** tight — `planner.py` + `test_planner.py` (+ optional docstring/director test)  
**Intentional behavior change:** stop forcing `knowledge.history` when `needs_history=false`  
**Report path:** `.grok/agent-memory/impact-analyzer/planner-contract.md`  
**Log path:** `.planning/quick/gsd-impact-analyzer-planner-contract.log`  
