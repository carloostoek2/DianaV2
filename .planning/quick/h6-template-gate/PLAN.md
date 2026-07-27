---
phase: quick
plan: h6-template-gate
type: auto
item: h6-template-gate — deterministic TemplateGate (saludo + deteccion_ia) pre-pipeline in CognitiveDirector; migrate J.4 identidad_ia off middleware to supervised approve
source: SPEC + clarify
mode: standard
spec: docs/ANEXO-H.md#H6
clarify: .planning/quick/h6-template-gate/CLARIFY.md
impact: .grok/agent-memory/impact-analyzer/h6-template-gate.md
---

## Objective

VIP short greetings and “are you AI?” probes no longer burn LLM tokens and no longer auto-deliver from middleware. They resolve in Cognitive Core via a pure **TemplateGate** at the top of `CognitiveDirector.handle_turn`, returning `Decision(action="approve", reason=plantilla_*, draft_text=template, evaluation=synthetic zeros)`. The existing TurnOrchestrator approve branch queues the draft for the owner. J.4 `pago_precio` / `compromiso_real` (and forbidden keywords) stay silent middleware short-circuits. `identidad_ia` is **removed** from J.4 classification/middleware so pure IA falls through to Director; hybrid IA+pago still escalates as **pago** (not IA approve).

## Scope

### In

- Pure `cognitive/template_gate.py`: `TemplateRule`, `TemplateGate.match` / `render`, local `_kw_hit` (no `diana.application` import).
- Rules (composition order locked): **`deteccion_ia` first**, then **`saludo_constante`** — annex patterns + exact IA response string.
- Optional `template_gate: TemplateGate | None = None` on `CognitiveDirector` (same optional pattern as `repetition_guard`); production composition always injects.
- Pre-pipeline branch in `handle_turn` → `_handle_template` with `_early_exit_evaluation()`, store `decision` only, skip Analyst→Decider.
- J.4 migration: remove `identidad_ia` path from `classify_j4_text` and ForbiddenKeywordsMiddleware IA deliver+escalate branch.
- Persona cleanup: `src/diana/config/persona_diana.json` `reglas_estilo` line without `(ver J.2 / examples)`.
- Tests: new pure gate unit file; Director H6.6 cases; invert middleware IA test; align `test_j4_triggers`; composition wiring; purity; pago/compromiso regression.

### Out / Non-goals

- Edit `TurnOrchestrator` approve branch (verify only).
- Make `Decision.evaluation` Optional (CLARIFY overrides ANEXO-H H6.4 `evaluation=None` — **stale**).
- Auto-send / autonomous template delivery; new feature flags.
- Expand `deteccion_ia` triggers to full former `IDENTIDAD_IA_KEYWORDS` (residual).
- Shared pure matcher module across cognitive/application (residual).
- Delete `handle_deterministic_template_escalate` (keep helper + unit tests; production path unused).
- Change pago/compromiso keyword lists or forbidden-keyword behavior.
- Docs rewrite of ANEXO-H H6.4 (optional residual).
- BehaviorEngine / Learning / Decider matrix / DB migrations.

### Constraints (locked — CLARIFY)

1. Migrate J.4 `identidad_ia` → TemplateGate Director approve (no auto-deliver VIP). Keep pago/compromiso in middleware.
2. Rule order: `deteccion_ia` → `saludo_constante`.
3. Synthetic evaluation H4 pattern (`_early_exit_evaluation()`), not Optional evaluation.
4. Cleanup `persona_diana.json` (not yaml).
5. No TurnOrchestrator changes.

## Assumptions

- A1: Local `_kw_hit` in `template_gate.py` is preferred over shared extract (impact C1 + CLARIFY deferred shared matcher). Semantics = `match_keywords` in `j4_triggers.py` (phrase substring on lowercased text; single-token word-boundary regex).
- A2: `template_gate=None` default avoids mass fixture breakage on `_turn(text="hola Diana")` (impact C3).
- A3: Removing `identidad_ia` from `classify_j4_text` is the hybrid policy (impact C2 recommended): IA-only text → `None` from classifier → handler → Director; IA+pago → pago escalate.
- A4: Keep `IA_TEMPLATE` / `IDENTIDAD_IA_KEYWORDS` constants in `j4_triggers.py` for dead-path helper tests and single string source; composition may import `IA_TEMPLATE` for the rule pool (composition is allowed to import application + cognitive).
- A5: Template path does not transition to `ANALYZING` (pre-pipeline); only stores `decision`. Orchestrator needs returned `Decision` only.
- A6: `handle_deterministic_template_escalate` stays; Forbidden may still accept `behavior=` (unused for IA). Do not require setup.py cleanup this item.
- A7: Owner UI shows zero eval dims for plantilla_* — reason string is source of truth (same as H4 `pregunta_repetida`).

## Architecture Approach

### QUÉ (behavior / contracts)

| Input (VIP text) | Layer | Outcome |
|------------------|-------|---------|
| Short greeting matching saludo patterns, `word_count ≤ 4` | Director TemplateGate | `approve`, `reason=plantilla_saludo`, `draft_text ∈ response_pool`, 0 LLM |
| Long “hola …” (>4 words) | Director full pipeline | No template |
| Annex IA probe e.g. `eres una ia?` | Director TemplateGate | `approve`, `reason=plantilla_deteccion_ia`, exact draft `jsjsj si y sólo vivo en tu mente 😏` |
| Mixed short `hola eres una ia` | Director TemplateGate | **deteccion_ia wins** (rule order) |
| Pago / compromiso keywords | Middleware J.4 | Silent escalate; Director never runs |
| Hybrid IA + pago | Middleware (pago after IA removed from classifier) | Silent escalate as pago_precio |
| Pure former J.4-only IA (`chatgpt`, `sos un bot`, …) not in annex | Full LLM pipeline | Coverage shrink accepted (residual expand keywords) |
| Forbidden keywords | Middleware | Unchanged silent escalate |

**Decision contract (template path):**

```text
Decision(
  action="approve",
  reason="plantilla_saludo" | "plantilla_deteccion_ia",
  evaluation=_early_exit_evaluation(),  # all zeros, required field
  draft_text=<rendered template>,       # non-empty
  mode_restriction_applied=None,
)
```

Side-effects: `TraceStore` gets only `decision` for that turn_id. No comprehension/plan/retrieved/generated_text/evaluation artifacts. No BehaviorEngine.deliver from Director or middleware for pure IA.

### CÓMO (structure / patterns)

**Placement**

| Piece | Layer | Module |
|-------|-------|--------|
| TemplateGate | Cognitive Core (pure) | `src/diana/cognitive/template_gate.py` |
| Early exit orchestration | Cognitive Core | `src/diana/cognitive/director.py` |
| Rule instances | Composition root | `src/diana/composition.py` |
| J.4 classify / IA_TEMPLATE constant | Application | `src/diana/application/j4_triggers.py` |
| Middleware branch removal | Telegram | `src/diana/telegram/middlewares/forbidden.py` |
| Persona style rules | Config | `src/diana/config/persona_diana.json` |

**Pattern to copy**

1. **Pure cognitive helper:** `src/diana/cognitive/repetition_guard.py`  
   - Frozen, no I/O, no LLM, `__all__` export.  
   - Injected optional on Director; unit tests inject only when needed.

2. **Synthetic Decision early-exit:** `src/diana/cognitive/director.py` H4 block (`pregunta_repetida` ~155–171) + `_early_exit_evaluation()` (~57–67).  
   - Same zero `EvaluationProfile`; store decision; return.  
   - H6 differs only in: runs **before** Analyst (not after), `action=approve` with non-null `draft_text`.

3. **Keyword match algorithm:** `src/diana/application/j4_triggers.py::match_keywords` (lines 146–165) — **duplicate** as private `_kw_hit(kw, lower_text) -> bool` inside template_gate (do **not** import application from cognitive).

4. **Optional port injection:** `repetition_guard: RepetitionGuard | None = None` on `CognitiveDirector.__init__`.

**Interfaces / types (new)**

```python
# cognitive/template_gate.py
@dataclass(frozen=True)
class TemplateRule:
    id: str
    trigger_patterns: list[str]
    max_words: int | None
    response_pool: list[str]
    reason: str

class TemplateGate:
    def __init__(self, rules: list[TemplateRule], *, rng: Any = random) -> None: ...
    def match(self, text: str) -> TemplateRule | None: ...
    def render(self, rule: TemplateRule) -> str: ...
```

Match algorithm (must match annex + local `_kw_hit`):

```text
for rule in self._rules:  # order = priority
  words = text.strip().split()
  if rule.max_words is not None and len(words) > rule.max_words: continue
  if any(_kw_hit(kw, text.lower()) for kw in rule.trigger_patterns): return rule
return None
```

**Rules factory (composition — exact content)**

```python
deteccion_ia = TemplateRule(
    id="deteccion_ia",
    trigger_patterns=[
        "eres una ia", "eres un bot", "eres ia",
        "hablo con una ia", "hablo con un bot", "eres real",
    ],
    max_words=None,
    response_pool=[IA_TEMPLATE],  # or literal "jsjsj si y sólo vivo en tu mente 😏"
    reason="plantilla_deteccion_ia",
)
saludo_constante = TemplateRule(
    id="saludo_constante",
    trigger_patterns=[
        "hola", "holaa", "holis", "buenas", "buenos días",
        "buenas tardes", "buenas noches", "hey", "qué tal",
    ],
    max_words=4,
    response_pool=["Holis 😁", "Holaa, qué tal?", "Hola amor, cómo vas?"],
    reason="plantilla_saludo",
)
template_gate = TemplateGate(rules=[deteccion_ia, saludo_constante])  # IA first
```

**Director wiring**

```text
handle_turn(turn):
  try:
    if self._template_gate is not None:
      rule = self._template_gate.match(turn.text)
      if rule is not None:
        return await self._handle_template(turn, rule)
    return await self._run_pipeline(turn)
  except:
    status FAILED; raise

_handle_template(turn, rule):
  text = self._template_gate.render(rule)
  decision = Decision(
    action="approve",
    reason=rule.reason,
    evaluation=_early_exit_evaluation(),
    draft_text=text,
    mode_restriction_applied=None,
  )
  await self._store(turn.turn_id, "decision", decision)
  return decision
```

**J.4 migration (application + telegram)**

- `classify_j4_text`: drop IA first-branch entirely. Order becomes: pago → compromiso. Docstring update. Keep `match_keywords`, pago/compromiso lists, `IA_TEMPLATE` constant.
- `J4Category` Literal: may keep `"identidad_ia"` for type/history or narrow to pago|compromiso — prefer **narrow to** `Literal["pago_precio", "compromiso_real"]` if no production code constructs IA hits; update tests accordingly. If narrowing breaks escalation_labels imports only as strings, leave Literal with three values but never emit IA (simpler: leave Literal + never return IA).
  - **Decision (planner):** Keep `J4Category` including `"identidad_ia"` and `IDENTIDAD_IA_KEYWORDS` constants for residual/history, but **never return** `identidad_ia` from `classify_j4_text`. Document in module docstring.
- `forbidden.py`: delete block `if j4 is not None and j4.category == "identidad_ia":` (deliver+escalate). Remaining `if j4 is not None:` handles pago/compromiso only.
- Do **not** remove `handle_deterministic_template_escalate` function or its unit tests.

**File map**

| Action | Path |
|--------|------|
| CREATE | `src/diana/cognitive/template_gate.py` |
| CREATE | `tests/unit/cognitive/test_template_gate.py` |
| EDIT | `src/diana/cognitive/director.py` |
| EDIT | `src/diana/composition.py` |
| EDIT | `src/diana/application/j4_triggers.py` |
| EDIT | `src/diana/telegram/middlewares/forbidden.py` |
| EDIT | `src/diana/config/persona_diana.json` |
| EDIT | `tests/unit/cognitive/test_director.py` |
| EDIT | `tests/unit/telegram/test_forbidden_mw.py` |
| EDIT | `tests/unit/application/test_j4_triggers.py` |
| EDIT | `tests/unit/test_composition_wiring.py` |
| KEEP (no functional change required) | `tests/unit/application/test_deterministic_escalate.py` |
| NO TOUCH | `turn_orchestrator.py`, `decider.py`, `behavior/**`, `learning/**`, Alembic |

## Context

@docs/ANEXO-H.md (H6; evaluation=None is stale — CLARIFY wins)  
@.planning/quick/h6-template-gate/CLARIFY.md  
@.grok/agent-memory/impact-analyzer/h6-template-gate.md  
@src/diana/cognitive/repetition_guard.py  
@src/diana/cognitive/director.py (`_early_exit_evaluation`, H4 early exit, `handle_turn`)  
@src/diana/application/j4_triggers.py (`match_keywords`, `classify_j4_text`, `IA_TEMPLATE`)  
@src/diana/telegram/middlewares/forbidden.py (IA branch ~133–178)  
@src/diana/composition.py (Director construct ~395–418)  
@src/diana/config/persona_diana.json (reglas_estilo line with J.2 note)  
@tests/unit/cognitive/test_import_purity.py  
@AGENTS.md (cognitive purity; Director determinism; one-turn invariant)

## Tasks

### Task 1: Pure TemplateGate (TDD)

**type:** auto  
**Objective:** Deterministic match/render with rule order and local keyword hit; zero I/O.

**Files:**
- CREATE `src/diana/cognitive/template_gate.py`
- CREATE `tests/unit/cognitive/test_template_gate.py`

**Action:**
1. **RED:** Write pure unit tests (no Director):
   - Empty / blank text → `None`
   - `saludo_constante` alone: `"Hola"` / `"holis"` match; `"Hola, tengo una pregunta sobre el contenido"` (5+ words) no match
   - `deteccion_ia` alone: `"eres una ia?"` matches; `render` returns exact single-pool string
   - **Order:** gate with `[deteccion_ia, saludo_constante]`; `"hola eres una ia"` → rule id `deteccion_ia`
   - Phrase vs token: multi-word triggers substring; single-token word boundary (e.g. `hola` not inside unrelated long token if applicable)
   - `render` with fixed `rng=random.Random(0)` is stable / in pool
2. **GREEN:** Implement `TemplateRule`, `TemplateGate`, `_kw_hit` per Architecture Approach. Export `__all__ = ["TemplateRule", "TemplateGate"]`.
3. No imports from `diana.application`, `diana.telegram`, `diana.behavior`.

**Verification:**
```bash
pytest -q tests/unit/cognitive/test_template_gate.py tests/unit/cognitive/test_import_purity.py -v
```

**Done:**
- [ ] All pure gate cases green
- [ ] `test_import_purity` green with new module present
- [ ] `_kw_hit` lives only in template_gate (no application import)

---

### Task 2: Director pre-pipeline template path (TDD)

**type:** auto  
**Objective:** When gate matches, Director returns synthetic approve Decision without calling Analyst/Generator/Evaluator/Planner/Decider; default `template_gate=None` preserves existing suite.

**Files:**
- EDIT `src/diana/cognitive/director.py`
- EDIT `tests/unit/cognitive/test_director.py`

**Action:**
1. Extend `make_director` with optional `template_gate: TemplateGate | None = None` passed through to `CognitiveDirector`.
2. **RED tests (H6.6.1–4 director-level):** inject real `TemplateGate(rules=[deteccion_ia, saludo_constante], rng=Random(0))`:
   - `"Hola"` → `action=="approve"`, `reason=="plantilla_saludo"`, `draft_text in pool`, evaluation all zeros, trace has `decision` only (no comprehension), Analyst/Gen/Eval mocks `assert_not_called` (use spies/AsyncMock on director collaborators **or** assert FakeLLM call count 0 / no analyst queue consumption as existing suite does)
   - Long hola message → full pipeline still runs (existing happy path pattern; text must not match template)
   - `"eres una ia?"` → exact IA draft, `reason=="plantilla_deteccion_ia"`
   - Decision fields: `evaluation` is non-None zero profile; `draft_text` non-empty; never `action=="send"` or `escalate` for templates
3. **GREEN:** Add `template_gate` kwarg default `None`; store `self._template_gate`; implement `handle_turn` pre-check + `_handle_template` as specified. Reuse `_early_exit_evaluation()`. Do **not** set evaluation to None.
4. Ensure existing tests that use default `make_director` without gate keep working with fixture text `"hola Diana"`.

**Verification:**
```bash
pytest -q tests/unit/cognitive/test_template_gate.py tests/unit/cognitive/test_director.py -v
```

**Done:**
- [ ] H6.6 cases 1–3 green at Director level
- [ ] Zero LLM path on template match
- [ ] Default gate None → no false saludo on `"hola Diana"` fixtures
- [ ] Existing director tests still green

---

### Task 3: Migrate J.4 identidad_ia off middleware (TDD)

**type:** auto  
**Objective:** Pure IA text no longer short-circuits in ForbiddenKeywordsMiddleware; hybrid IA+pago still escalates as pago; pago/compromiso unchanged.

**Files:**
- EDIT `src/diana/application/j4_triggers.py`
- EDIT `src/diana/telegram/middlewares/forbidden.py`
- EDIT `tests/unit/application/test_j4_triggers.py`
- EDIT `tests/unit/telegram/test_forbidden_mw.py`

**Action:**
1. **RED:** Rewrite/invert tests:
   - `test_j4_triggers`: remove or rewrite expectations that `classify_j4_text("eres una ia")` returns `identidad_ia`. Pure IA → `None`. Hybrid e.g. text with both IA-ish and `precio`/`cuesta` → `pago_precio`. Keep pago/compromiso positive tests.
   - `test_forbidden_mw.test_j4_ia_delivers_template_then_escalates` → **invert**: for `"eres una ia?"` (or similar), handler **is awaited**, no template deliver, no `identidad_ia` escalation event. Rename e.g. `test_j4_ia_passes_to_handler`.
   - Keep pago stop-pipeline tests green (no rewrite of expected escalate behavior).
2. **GREEN:**
   - `classify_j4_text`: remove IA branch; only pago then compromiso; update module docstring (priority no longer starts with identidad_ia).
   - `forbidden.py`: remove entire `identidad_ia` branch (deliver+escalate / fail-closed IA). Drop unused imports only if truly unused (`IA_TEMPLATE`, `handle_deterministic_template_escalate`) — if unused after edit, remove those imports from forbidden.py.
3. **Keep** `handle_deterministic_template_escalate` + `test_deterministic_escalate.py` as-is (dead production path, live unit coverage).
4. Do not change `escalation_labels` identidad_ia entries.

**Verification:**
```bash
pytest -q tests/unit/application/test_j4_triggers.py tests/unit/application/test_deterministic_escalate.py tests/unit/telegram/test_forbidden_mw.py -v
```

**Done:**
- [ ] Pure IA: middleware passes handler (no deliver, no escalate)
- [ ] Pago/compromiso still short-circuit escalate
- [ ] Hybrid pago wins via classifier (no IA category returned)
- [ ] Deterministic template helper unit tests still green

---

### Task 4: Composition wire + persona cleanup + integration assertions

**type:** auto  
**Objective:** Production Director has TemplateGate with correct rule order; persona style line cleaned; wiring test asserts gate present.

**Files:**
- EDIT `src/diana/composition.py`
- EDIT `src/diana/config/persona_diana.json`
- EDIT `tests/unit/test_composition_wiring.py`
- Optional assert touch: `tests/unit/cognitive/test_director.py` if needed for end-to-end reason strings only

**Action:**
1. In composition, construct `TemplateGate(rules=[deteccion_ia, saludo_constante])` and pass `template_gate=...` into `CognitiveDirector(...)`.
2. Persona: change reglas_estilo entry  
   `"Máximo una expresión característica de voz por mensaje (ver J.2 / examples)."`  
   → `"Máximo una expresión característica de voz por mensaje."`  
   (or equivalent without the J.2 parenthetical).
3. Composition wiring test: assert director has non-None template_gate / rules ordered deteccion_ia then saludo_constante (inspect private attrs as other wiring tests do, or public property if you add a minimal `@property` — prefer mirror existing H4 assertions style without new public API unless needed).
4. H6.6.5: unit test that loads persona JSON (or composition-loaded voz) and asserts no substring `(ver J.2 / examples)` in reglas_estilo.

**Verification:**
```bash
pytest -q tests/unit/test_composition_wiring.py tests/unit/cognitive/test_template_gate.py tests/unit/cognitive/test_director.py tests/unit/cognitive/test_import_purity.py tests/unit/application/test_j4_triggers.py tests/unit/telegram/test_forbidden_mw.py -v
```

**Full safety net (before claiming item done):**
```bash
pytest -q tests/unit/cognitive tests/unit/telegram tests/unit/application/test_j4_triggers.py tests/unit/application/test_deterministic_escalate.py tests/unit/application/test_turn_orchestrator.py tests/unit/application/test_admin_service.py tests/unit/test_composition_wiring.py -v
```

**Done:**
- [ ] Production wiring injects gate with IA-first rule order
- [ ] Persona JSON cleaned
- [ ] Composition test green
- [ ] Safety net green

## Instrucciones para gsd-executor

### Mode & process

- **Strict TDD** is active: RED → GREEN per task; do not implement production code before failing tests for that behavior.
- **Work-unit commits** (conventional commits, English messages, no Co-Authored-By):
  1. `feat(cognitive): add pure TemplateGate for deterministic reply templates`
  2. `feat(cognitive): short-circuit Director handle_turn on TemplateGate match`
  3. `refactor(j4): stop middleware short-circuit for IA identity probes`
  4. `feat(composition): wire TemplateGate and clean persona style rule`
- Each commit includes the tests that prove that unit.
- Technical artifacts (code, comments, commit messages) in **English**. Product template strings remain Spanish as in annex.

### Patterns to copy

- `repetition_guard.py` — pure helper + optional Director inject
- Director H4 early exit + `_early_exit_evaluation()` — synthetic Decision
- `match_keywords` algorithm — **local** `_kw_hit` only

### Anti-patterns (forbidden)

- `from diana.application...` inside any `cognitive/` module
- `evaluation=None` on Decision
- Editing `turn_orchestrator.py` “just in case”
- Auto-deliver template from Director or reintroducing middleware IA deliver
- Importing TemplateGate matcher from application
- Default-on TemplateGate in unit `make_director` without opt-in (breaks `"hola Diana"`)
- Expanding IA keywords beyond annex in this item
- Calling Learning / Behavior from template path
- Touching Decider priority matrix for templates

### Layer rules (AGENTS.md)

- Cognitive: decide / pure gate only — no Telegram I/O
- Application J.4: classify text only for middleware residual categories
- Telegram middleware: short-circuit pago/compromiso/forbidden only after this item
- One turn per message: approve path only for templates (no parallel escalate)

### Mock policy

- Prefer **real** `TemplateGate` in Director tests.
- Mock only external LLM (`FakeLLM`) / ports as existing director tests do.
- On template path: assert LLM / analyst side-effects not invoked.
- Do not mock away `_kw_hit` internals.

### Logging

- No required new logs; optional `logger` not needed for pure gate. If adding Director log, keep structured extras consistent with existing director style — prefer no new noise unless useful for `/traza` debugging (skip unless needed).

## Test commands

### Per-task (see Tasks)

### H6.6 acceptance matrix

| # | Case | Assert |
|---|------|--------|
| 1 | `"Hola"` | `reason==plantilla_saludo`, draft ∈ pool, no Analyst/Gen/Eval |
| 2 | Long hola (5+ words) | no template; pipeline runs |
| 3 | `"eres una ia?"` | exact IA draft string |
| 4 | Template Decision | `action==approve`; compatible with admin draft path; **no** auto-deliver |
| 5 | persona JSON | no `(ver J.2 / examples)` in reglas_estilo |

### Regression

| Case | Assert |
|------|--------|
| Middleware pago | still silent escalate |
| Middleware compromiso | still silent escalate |
| Middleware pure IA | handler awaited; no deliver/escalate |
| Mixed `"hola eres una ia"` | `plantilla_deteccion_ia` |
| `test_import_purity` | green |
| Approve orch path | still works without TO edits |

### Full unit (pre-merge optional)

```bash
pytest -q tests/unit -v
```

## Risks + Mitigation

| ID | Risk | Mitigation in plan |
|----|------|--------------------|
| C1 | Cognitive purity break | Local `_kw_hit`; Task 1 purity verify |
| C2 | Hybrid IA+pago becomes approve draft | Remove IA from `classify_j4_text`; hybrid → pago; Task 3 tests |
| C3 | Mass director test false-fire on `"hola Diana"` | `template_gate=None` default; inject only in H6 tests |
| M1 | Keyword coverage shrink vs old J.4 IA set | Accepted residual; document in SUMMARY |
| M2 | Product flip: VIP waits for owner on IA | Intentional supervised path; assert no middleware deliver |
| M3 | Dead `handle_deterministic_template_escalate` | Keep helper + unit tests; residual delete later |
| M6 | Wrong rule order | Composition list IA first + unit order test |
| L3 | Flaky pool RNG | Fixed `Random(0)` in tests; assert membership not exact saludo variant unless fixed rng |

## Success Criteria

- [ ] Pure TemplateGate matches annex rules with `deteccion_ia` before `saludo_constante`
- [ ] Director template path: approve + synthetic eval + draft; 0 LLM; decision stored
- [ ] Default Director without gate: existing tests green
- [ ] Middleware: no IA auto-deliver/escalate; pago/compromiso intact
- [ ] Hybrid IA+pago escalates as payment (not template approve)
- [ ] Composition injects gate; persona JSON cleaned
- [ ] All verification commands in Tasks 1–4 green
- [ ] No edits to no-touch list (`turn_orchestrator.py`, `decider.py`, behavior, learning, Alembic)
- [ ] `test_import_purity` green

## Residuals (explicit — not this item)

1. Expand `deteccion_ia` triggers toward former `IDENTIDAD_IA_KEYWORDS`.
2. Shared pure keyword matcher module.
3. Remove unused `handle_deterministic_template_escalate` + Forbidden `behavior=` if fully dead.
4. ANEXO-H H6.4 doc fix: synthetic evaluation vs `None`.
5. Owner UI: soften zero scores for `plantilla_*`.
6. Suite-wide fixture text hygiene (`hola Diana`).

## Expected SUMMARY path

After execution + verify, write:

`.planning/quick/h6-template-gate/SUMMARY.md`

Skeleton sections: Objective met / Files changed / Test commands + results / Residuals / Deviations from PLAN (none expected).
