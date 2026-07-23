---
phase: quick
plan: context-builder-contract
type: auto
item: context-builder-contract (Pool remaining-contracts-cognitive · 2/4)
effort: 4
stack: python>=3.12, pydantic-v2, pytest
depends_on: evaluator-contract (list_included_blocks + typed fail gold); planner-contract (C.3 no force-history)
source_of_truth: docs/contratos_restantes.md Anexo D (D.1–D.6 only)
impact: .grok/agent-memory/impact-analyzer/context-builder-contract.md
mode: standard
---

## Objective

Align the **ContextBuilder runtime** to `docs/contratos_restantes.md` Anexo D (D.1–D.6): dual output `BuiltContext { prompt_final, included_blocks }`, fixed D.4 assembly order with **current turn last**, null-like omit (no empty placeholders), explicit typed fail `contexto_excede_limite` (no truncate, no auto-retry), Director single-source for Generator prompt + Evaluator `included_blocks`, Orchestrator `mark_failed` + owner notify on size fail — without expanding F1 `Decision.action`, without Cognitive→Telegram imports, and without reworking Anexos A–C or E–I.

## Scope

- **In:**
  - `BuiltContext` model (English fields; Spanish D.3 names in docstring only)
  - `ContextBuilder.build(...) -> BuiltContext` with D.4 section order + fixed knowledge emission order
  - Shared null-like filter; `list_included_blocks` stays consistent with prompt knowledge headings (D.4 order)
  - Optional empty `style_rules: list[str] = []` under persona (D.2 `reglas_estilo`; empty = omit)
  - Constructor `max_prompt_chars` (high default); size excess → `ContextExceedsLimitError`
  - Director consumes dual return; stores string under trace key `prompt_text`
  - Orchestrator typed branch for `contexto_excede_limite` + `notify_info` (mirror A.6/B.6)
  - Unit tests locking order independence, dual return, null-omit, size-fail, wiring, notify
- **Out / Non-goals:**
  - Anexos E–I (Generator DTO, Decider rewrite, Registry contract, etc.)
  - Rework of Analyst / Planner / Evaluator contracts (A–C already gold)
  - Token-accurate budgeting / live tokenizer / Settings migration
  - Spanish field aliases on models; renaming SQL `prompt_text` column
  - Silent truncation helpers; auto-retry inside builder or Director for size fail
  - Telegram / Behavior / Learning / Staging redesign
  - Dirty-tree WIP: alembic `turns.error` residual, unrelated `.grok/agent-memory/**`
  - F1 `Decision.action` expansion beyond `approve|escalate`
  - Mass docs sync of `MVP_COMPONENT_DESIGN.md` / SPEC (documentador residual)
- **Constraints:** Strict TDD; FakeLLM/InMemory only; cognitive never imports telegram/behavior; 0 Behavior change outside orchestrator fail path

## Assumptions

- A1: Sole production `build` caller is `CognitiveDirector` (impact confirmed). Generator stays `generate(prompt: str)` — only the string content/order changes.
- A2: Char-length proxy is the F1 approximation of provider limit (no tokenizer). Default `max_prompt_chars` is high enough that happy-path F1 history+context never trips; tests inject a tiny limit for fail path.
- A3: Keeping `## Comprehension` (not in D.4 list) after knowledge and **before** current turn is locked product utility for Generator; it is **not** a knowledge capability and **not** in `included_blocks`.
- A4: Fixed knowledge emission order includes `knowledge.schedule` and `knowledge.profile` after examples (plan can request schedule; profile is F2 hook). Unknown capability keys are **ignored** (not emitted).
- A5: `list_included_blocks` remains public for tests/compat but Director prefers `built.included_blocks` from the single assembly pass (L8).
- A6: Orchestrator double FAILED (Director FAILED then `mark_failed`) is existing A.6/B.6 pattern — keep; ensure error **token** comes from orchestrator branch.
- A7: Optional `style_rules` empty default is reversible UX; no Settings/env required in this item.

## Architecture Approach

### QUÉ (behavior / contracts)

| Contract | Runtime truth after this item |
|----------|-------------------------------|
| D.1 | ContextBuilder answers only “minimal context for Generator?” — pure assembly, no LLM, no draft, no score |
| D.2 input | `build(turn, comprehension, knowledge: dict, persona, style_rules=[])` — dict is Registry shape (document Array map in docstring) |
| D.3 output | `BuiltContext(prompt_final: str, included_blocks: list[str])` — not bare `str` |
| D.3 blocks | `included_blocks` = capability names whose values are non-null-like **and** emitted as `## Knowledge:` sections |
| D.4 order | Persona → knowledge in fixed tuple order (only non-null-like) → Comprehension → **Current VIP message last** |
| D.5 null | Never emit empty/placeholder knowledge sections for null-like results |
| D.5 size | If `len(prompt_final) > max_prompt_chars` → raise typed error; **no** truncate |
| D.6 | Only own fail path is size excess; **no** auto-retry inside builder |
| App | On size fail: turn `failed`, error `contexto_excede_limite`, owner notified, VIP send count 0 |

**Section order (locked L3 + A3):**

```
## Persona
{persona.strip()}
[optional style lines if style_rules non-empty]

## Knowledge: knowledge.history    # only if non-null-like
## Knowledge: knowledge.context
## Knowledge: knowledge.memory
## Knowledge: knowledge.policy
## Knowledge: knowledge.examples
## Knowledge: knowledge.schedule
## Knowledge: knowledge.profile

## Comprehension
intent: ...
topics: ...
emotion: ...
urgency: ...
risk: ...

## Current VIP message
{turn.text}
```

**Fixed knowledge emission order (constant):**

```python
_KNOWLEDGE_EMISSION_ORDER: tuple[str, ...] = (
    "knowledge.history",
    "knowledge.context",
    "knowledge.memory",
    "knowledge.policy",
    "knowledge.examples",
    "knowledge.schedule",
    "knowledge.profile",
)
```

**Null-like (keep evaluator gold L3/L8):** `None`; empty `list`/`dict`/`tuple`/`set`; empty/whitespace `str`.

### CÓMO (structure / patterns)

- **Placement:** Cognitive Core for model/exception/builder/director; Application layer only for orchestrator typed notify (same as A.6/B.6). No telegram/behavior/learning.
- **Pattern to copy:**
  - PLAN shape: `.planning/quick/evaluator-contract/PLAN.md` (typed error + orchestrator notify tasks)
  - Typed error twin: `EvaluatorSchemaInvalidError` / `AnalystSchemaInvalidError` in `exceptions.py`
  - Orchestrator notify gold: `test_orchestrator_evaluator_schema_fail_marks_failed_notifies_owner`
  - Null-like + headings parity: existing `tests/unit/cognitive/test_context_builder.py`
  - Director factory: `make_director` in `test_director.py`
- **File map:**
  - **Edit:** `context_builder.py`, `models.py`, `exceptions.py`, `director.py`, `turn_orchestrator.py`, primary tests
  - **Maybe:** `composition.py` only if constructor needs explicit `max_prompt_chars` (prefer class default)
  - **No-touch:** telegram/**, behavior/**, learning/**, analyst/planner/evaluator/decider/generator contracts, alembic/**, dirty WIP
- **Interfaces first:** Task 1 adds `BuiltContext` + `ContextExceedsLimitError` before/with builder API flip
- **Wiring:** Director one `built = build(...)`; `generate(built.prompt_final)`; `EvaluatorInput(included_blocks=built.included_blocks)`
- **Verificación:** `.venv/bin/python -m pytest -q …` per task; full `tests/unit` before handoff
- **Riesgos:** R1 prompt reorder changes LLM input (contract-intended); R2 dual return blast (Director only); R3 size default false positives (high default); R8 dict order independence (unit test)

### English ↔ Anexo D mapping (docs/docstring only)

| Runtime (English) | Anexo D (Spanish) |
|-------------------|-------------------|
| `BuiltContext` | `ContextoConstruido` |
| `prompt_final` | `prompt_final` |
| `included_blocks` | `bloques_incluidos` |
| `style_rules` | `reglas_estilo` |
| `ContextBuilder.build` | Constructor de Contexto |
| `ContextExceedsLimitError.reason` | `contexto_excede_limite` |
| `knowledge` dict | `conocimiento_recuperado` Array map |

## Locked decisions (NON-NEGOTIABLE)

| ID | Decision |
|----|----------|
| L1 | English model: `BuiltContext` with fields `prompt_final: str` + `included_blocks: list[str]`; Spanish D.3 names only in docstring. Trace/SQL still stores the **string** under key/column `prompt_text`. |
| L2 | `build(...) -> BuiltContext` (not bare `str`). Director adapts; Generator still receives `str`. |
| L3 | D.4 order: Persona → knowledge (fixed emission order, only non-null-like) → Comprehension (keep, before turn) → **Current VIP message last**. |
| L4 | `included_blocks` = capability names that appear as `## Knowledge:` headings (same filter as `list_included_blocks`); **not** comprehension; **not** persona. |
| L5 | Never emit empty placeholder sections for null-like results. |
| L6 | Size excess → typed error reason exactly `contexto_excede_limite`; no truncate; no auto-retry inside builder. |
| L7 | Orchestrator: `mark_failed` + `notify_info` on typed size error (mirror Analyst/Evaluator); no VIP send. |
| L8 | Reuse/share `_is_null_like` with `list_included_blocks`; single assembly pass preferred for Director (`built.included_blocks`). |
| L9 | F1 `Decision.action` stays `approve\|escalate`; cognitive never imports telegram/behavior. |
| L10 | Configurable `max_prompt_chars` via `ContextBuilder.__init__` with high default (e.g. `100_000`); tests use small limit. |
| L11 | No dirty-tree / Anexos E–I / rework A–C. |
| L12 | Strict TDD; FakeLLM/InMemory only; no live network. |
| L13 | Knowledge emission order = fixed tuple history→context→memory→policy→examples→schedule→profile; ignore unknown keys. |
| L14 | `style_rules: list[str] = []` optional under persona; empty = no extra lines. |

## Context

@`.grok/agent-memory/impact-analyzer/context-builder-contract.md`
@`docs/contratos_restantes.md` (Anexo D only)
@`.planning/quick/evaluator-contract/PLAN.md` (typed fail + orchestrator gold)
@`.planning/quick/planner-contract/PLAN.md` (structure gold)
@`AGENTS.md` (§3 Cognitive Core, §5.1 Director deterministic, anti-contamination)
@`src/diana/cognitive/context_builder.py` (current: turn early; returns `str`)
@`src/diana/cognitive/models.py` (`EvaluatorInput` pattern for `BuiltContext`)
@`src/diana/cognitive/exceptions.py` (Analyst + Evaluator only today)
@`src/diana/cognitive/director.py` (~133–156: build + list_included_blocks)
@`src/diana/application/turn_orchestrator.py` (A.6/B.6 notify branches)
@`src/diana/composition.py` (`ContextBuilder()`, `DEFAULT_PERSONA`)
@`tests/unit/cognitive/test_context_builder.py`
@`tests/unit/cognitive/test_director.py`
@`tests/unit/application/test_turn_orchestrator.py`
@`tests/unit/cognitive/test_import_purity.py`

## Tasks

### Task 1: BuiltContext + size error + ContextBuilder D.3/D.4/D.5
**type:** auto  
**Objective:** ContextBuilder returns dual `BuiltContext`, assembles D.4 order (current turn last; fixed knowledge order independent of dict insertion), omits null-like knowledge, raises `ContextExceedsLimitError(reason="contexto_excede_limite")` when over budget — no truncate, no retry.

**TDD order (mandatory):**
1. Rewrite/extend `test_context_builder.py` + add model/exception tests so dual return + D.4 order + size fail **RED** against current code.
2. Implement `BuiltContext`, `ContextExceedsLimitError`, and `context_builder.py` (**GREEN**).
3. Do **not** change Director/Orchestrator yet (Task 2–3). Temporary breakage of director tests is expected until Task 2 if those import `build` return type — prefer Task 1 verification scoped to builder/models; if import-time fails, run Task 1 + Task 2 in same work session but still TDD-per-surface.

**Files (edit):**
- `src/diana/cognitive/models.py` — add `BuiltContext`
- `src/diana/cognitive/exceptions.py` — add `ContextExceedsLimitError`; update `__all__`
- `src/diana/cognitive/context_builder.py` — dual return, D.4, size check, emission order
- `tests/unit/cognitive/test_context_builder.py` — primary surface
- `tests/unit/cognitive/test_models.py` — BuiltContext shape (optional if tests live next to builder; prefer models tests for `extra="forbid"`)

**`BuiltContext` (exact intent):**

```python
class BuiltContext(BaseModel):
    """ContextBuilder output (Anexo D.3).

    English fields map to Spanish contract names:
    prompt_final←prompt_final, included_blocks←bloques_incluidos.
    """

    model_config = ConfigDict(extra="forbid")

    prompt_final: str
    included_blocks: list[str]
```

Export in `models.__all__`.

**`ContextExceedsLimitError` (mirror Evaluator):**

```python
class ContextExceedsLimitError(Exception):
    """Raised when assembled prompt exceeds max_prompt_chars (Anexo D.5/D.6).

    Stable reason: ``contexto_excede_limite``.
    """

    reason: str = "contexto_excede_limite"

    def __init__(self, reason: str = "contexto_excede_limite") -> None:
        self.reason = reason
        super().__init__(reason)

    def __str__(self) -> str:
        return self.reason
```

**`ContextBuilder` API (exact intent):**

```python
DEFAULT_MAX_PROMPT_CHARS = 100_000

class ContextBuilder:
    def __init__(
        self,
        *,
        max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
    ) -> None:
        self._max_prompt_chars = max_prompt_chars

    def build(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
        knowledge: dict[str, Any | None],
        persona: str,
        style_rules: list[str] | None = None,
    ) -> BuiltContext:
        ...
        # single pass:
        # 1) persona (+ style_rules if non-empty strings)
        # 2) for name in _KNOWLEDGE_EMISSION_ORDER: if name in knowledge and not null-like → section + append name to blocks
        # 3) comprehension summary (existing fields)
        # 4) current turn last
        # prompt = "\n".join(parts).strip() + "\n"
        # if len(prompt) > self._max_prompt_chars: raise ContextExceedsLimitError()
        # return BuiltContext(prompt_final=prompt, included_blocks=blocks)

    def list_included_blocks(self, knowledge: dict[str, Any | None]) -> list[str]:
        """Capability names that appear as ## Knowledge sections in build() (D.4 order)."""
        return [
            name
            for name in _KNOWLEDGE_EMISSION_ORDER
            if name in knowledge and not _is_null_like(knowledge[name])
        ]
```

**Keep:**
- `_is_null_like` and `_format_value` semantics (no regression)
- Heading format `## Knowledge: {name}` (Evaluator parity tests depend on this)
- Comprehension field lines: intent, topics, emotion, urgency, risk

**Must change vs today:**
- Move `## Current VIP message` from early position to **last**
- Emit knowledge in `_KNOWLEDGE_EMISSION_ORDER`, not `knowledge.items()` insertion order
- Return `BuiltContext` not `str`
- Size check after full join

**Tests — update / add (must exist after task):**

| Action | Test | Assert |
|--------|------|--------|
| **Adapt** | `test_always_includes_persona_and_current_message` | use `.prompt_final`; persona + body present |
| **Adapt** | `test_null_knowledge_omits_stub_headings` | `.prompt_final`; caps not in prompt |
| **Adapt** | `test_non_null_knowledge_sections_included` | headings present; null memory absent |
| **Adapt** | `test_comprehension_summary_present` | intent line in `.prompt_final` |
| **Adapt** | `test_empty_list_and_dict_knowledge_omitted` | null-like omit |
| **Adapt** | `test_list_included_blocks_matches_prompt_sections` | blocks == knowledge headings from `built.prompt_final`; order D.4; profile last among non-null |
| **Keep/adapt** | `test_list_included_blocks_empty_when_all_null_like` | `[]` |
| **Add** | `test_build_returns_built_context_prompt_and_blocks` | `isinstance(built, BuiltContext)`; `prompt_final` str; blocks list matches headings |
| **Add** | `test_d4_current_turn_is_last_section` | last non-empty heading (or last `##` section) is Current VIP message; body is after all knowledge + comprehension |
| **Add** | `test_d4_knowledge_emitted_in_fixed_order_regardless_of_dict_insertion` | insert knowledge keys reversed / shuffled; headings order still history→context→… for present non-null |
| **Add** | `test_contexto_excede_limite_raises_typed_error_no_truncate` | `ContextBuilder(max_prompt_chars=50)` + large history body → raises `ContextExceedsLimitError`; `str(exc)=="contexto_excede_limite"`; `exc.reason=="contexto_excede_limite"`; assert no truncated partial return |
| **Add** | `test_style_rules_optional_under_persona` | non-empty rules appear under persona region before knowledge; empty/default omit |
| **Add** | `test_built_context_rejects_extra_fields` (models) | `extra="forbid"` |
| **Add** | `test_included_blocks_exclude_comprehension_and_persona` | blocks never contain `"Comprehension"` / persona labels — only `knowledge.*` |

**Helper tip for order asserts:**

```python
def _section_headings(prompt: str) -> list[str]:
    return [line for line in prompt.splitlines() if line.startswith("## ")]
```

**Do NOT:**
- Truncate prompt to fit budget
- Retry build or call LLM
- Put comprehension into `included_blocks`
- Emit unknown capability keys
- Change Generator / Evaluator signatures
- Touch Director/Orchestrator in this task if avoidable (Director in Task 2)

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_models.py
```

**Done:**
- [ ] `BuiltContext` exists with English fields + `extra="forbid"`
- [ ] `build` returns dual structure; `prompt_final` ends with current turn section
- [ ] Knowledge order fixed independent of dict insertion
- [ ] Null-like omit still gold; `list_included_blocks` ≡ knowledge headings
- [ ] Size fail raises exact `contexto_excede_limite`; no truncate
- [ ] Command above green

**Commit (work unit 1):**
```
feat(cognitive): ContextBuilder dual BuiltContext, D.4 order, size fail
```

---

### Task 2: Director wiring — BuiltContext single source
**type:** auto  
**Objective:** Director uses one `build` result for Generator prompt and Evaluator `included_blocks`; stores string under `prompt_text`; size fail propagates as typed error with no Decision / no synthetic evaluation.

**TDD order:** extend `test_director.py` red → `director.py` green.

**Files (edit):**
- `src/diana/cognitive/director.py`
- `tests/unit/cognitive/test_director.py`

**Pipeline change (BUILDING_CONTEXT / EVALUATING — exact intent):**

```python
await self._status.transition(turn_id, TurnStatus.BUILDING_CONTEXT)
built = self._context_builder.build(
    turn,
    comprehension,
    knowledge=retrieved,
    persona=self._persona,
)
await self._store(turn_id, "prompt_text", built.prompt_final)

await self._status.transition(turn_id, TurnStatus.GENERATING)
draft = await self._generator.generate(built.prompt_final)
await self._store(turn_id, "generated_text", draft)

await self._status.transition(turn_id, TurnStatus.EVALUATING)
# Prefer built.included_blocks (single assembly pass) over re-calling list_included_blocks
evaluation = await self._evaluator.evaluate(
    EvaluatorInput(
        draft=draft,
        comprehension=comprehension,
        included_blocks=built.included_blocks,
        current_turn=turn.text,
    )
)
```

On `ContextExceedsLimitError`: outer `handle_turn` already transitions `FAILED` + re-raises (same as other exceptions). Ensure **no** `prompt_text` is required if fail before store — either fail after full build raise (no store) or store only after successful build. **Preferred:** raise before return from `build` → Director never stores partial prompt if `build` raises (current flow stores after build returns — keep store after successful build only).

**Tests (must add/update):**
- Adapt any assumption that `build` returns `str` (trace `prompt_text` remains `str` after store).
- `test_director_prompt_uses_built_context_current_turn_last` — after happy `handle_turn`, `trace["prompt_text"]` has `## Current VIP message` after knowledge/comprehension headings (index order).
- `test_director_evaluator_uses_built_included_blocks` — keep/extend `test_director_passes_included_blocks_to_evaluator`: Evaluator messages still see capability **names** not raw bodies; blocks come from build result.
- `test_director_context_exceeds_limit_no_decision` — inject `ContextBuilder(max_prompt_chars=N_small)` via `make_director` (or construct director with small limit) + large history seed so build fails → raises `ContextExceedsLimitError`; no `decision` in trace; status FAILED path; Generator not called (FakeLLM text call count 0 for generator if observable) or pipeline aborts before decision.
- Keep TAC-01 happy path: still **3** LLM ops (Analyst structured + Generator text + Evaluator structured) when build succeeds.
- Keep import purity green.

**`make_director` adjustment:** accept optional `context_builder=` or `max_prompt_chars=` so size-fail test can inject tiny budget without rewriting the whole factory.

**Do NOT:**
- Call `list_included_blocks` as separate source of truth if `built.included_blocks` is available (L8)
- Expand Decision.action
- Import telegram/behavior
- Catch size error inside Director to invent a short prompt

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_evaluator.py \
  tests/unit/cognitive/test_import_purity.py
```

**Done:**
- [ ] Director stores `built.prompt_final` as `prompt_text`
- [ ] Evaluator receives `built.included_blocks`
- [ ] Size fail aborts before Decision; typed error propagates
- [ ] Happy path TAC call count still 3
- [ ] Commands above green

**Commit (work unit 2):**
```
feat(cognitive): Director consumes BuiltContext for prompt and blocks
```

---

### Task 3: Orchestrator D.6 notify + full unit gate
**type:** auto  
**Objective:** On `ContextExceedsLimitError`, turn is `failed` with error `contexto_excede_limite`, owner notified via `AdminService.notify_info`, VIP receives nothing; full unit suite green.

**TDD order:** add orchestrator test red → minimal `turn_orchestrator.py` green → full gate.

**Files (edit):**
- `src/diana/application/turn_orchestrator.py`
- `tests/unit/application/test_turn_orchestrator.py`

**Orchestrator except block (exact intent — third typed branch):**

```python
from diana.cognitive.exceptions import (
    AnalystSchemaInvalidError,
    ContextExceedsLimitError,
    EvaluatorSchemaInvalidError,
)

# inside except Exception as exc:
if isinstance(exc, AnalystSchemaInvalidError):
    ...  # existing
elif isinstance(exc, EvaluatorSchemaInvalidError):
    ...  # existing
elif isinstance(exc, ContextExceedsLimitError):
    error = "contexto_excede_limite"
    await self._coordinator.mark_failed(turn_id, error=error)
    try:
        await self._admin.notify_info(
            f"Turn {turn_id} failed: contexto_excede_limite",
            chat_id=incoming.chat_id,
        )
    except Exception:
        logger.exception(
            "owner_notify_failed_after_context_exceeds_limit",
            extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
        )
else:
    await self._coordinator.mark_failed(turn_id, error=str(exc))
```

Message must include reason token `contexto_excede_limite` and `turn_id`. Notifier failures must not mask the typed error. Always re-raise.

**Test (must add):**

`test_orchestrator_context_exceeds_limit_marks_failed_notifies_owner`

- Mirror Evaluator B.6 setup: real Director path **or** FakeDirector that raises `ContextExceedsLimitError` — prefer **real Director + tiny `ContextBuilder(max_prompt_chars=...)` + seeded large history** if factory allows; else FakeDirector raising typed error is acceptable for orchestrator-only contract (mark_failed + notify + send_count).
- Assert `pytest.raises(ContextExceedsLimitError)`.
- Assert turn status `failed`, `error == "contexto_excede_limite"`.
- Assert `notifier.infos` ≥1 contains `contexto_excede_limite` and turn_id.
- Assert `actuator.send_count()==0`.
- Assert exception re-raised.
- Keep Analyst A.6 and Evaluator B.6 tests green without edits.

**Do NOT:**
- Call Behavior on fail
- Import cognitive exceptions into telegram layer
- Change happy-path approve/escalate
- Redesign AdminService
- Stage dirty-tree files

**Verification (orchestrator + cognitive cluster):**
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_evaluator.py \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_import_purity.py
```

**Full unit gate (required before handoff done):**
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q tests/unit
```

**Done:**
- [ ] Fail reason stored as `contexto_excede_limite`
- [ ] Owner notified once on size fail
- [ ] VIP send count stays 0
- [ ] A.6 and B.6 paths still green
- [ ] Full `tests/unit` green

**Commit (work unit 3):**
```
feat(application): notify owner on contexto_excede_limite
```

---

## Instrucciones para gsd-executor

### Patterns to copy
- **Typed error twin:** `EvaluatorSchemaInvalidError` / `AnalystSchemaInvalidError` → `ContextExceedsLimitError` in `exceptions.py` (same `reason` / `__str__` shape).
- **Orchestrator notify gold:** copy `test_orchestrator_evaluator_schema_fail_marks_failed_notifies_owner` structure; swap exception type and reason token.
- **Null-like parity:** keep `_is_null_like`; assert `list_included_blocks` against `## Knowledge:` headings in `built.prompt_final`.
- **Director factory:** `make_director` — extend for `context_builder=` / `max_prompt_chars=` only if needed for size-fail tests.
- **Model gold:** `EvaluatorInput` style docstring map + `extra="forbid"` for `BuiltContext`.
- **Import purity:** re-run `tests/unit/cognitive/test_import_purity.py` after any cognitive edit.

### Anti-patterns (reject if you introduce them)
- Silent truncation of prompt or knowledge bodies to fit budget
- Auto-retry of `build` / size fail inside builder or Director
- Returning bare `str` from `build` (must be `BuiltContext`)
- Emitting empty knowledge placeholder sections for null-like values
- Putting current turn before knowledge (old order) — **D.4 violation**
- Relying on dict insertion order for knowledge sections
- Including comprehension/persona labels in `included_blocks`
- Computing Evaluator blocks from full plan list without null-like filter
- Expanding `Decision.action` or touching Decider matrix
- Cognitive importing `diana.telegram` / `diana.behavior` / aiogram
- Live network / real LLM in unit tests
- Touching alembic / dirty-tree residual / Anexos E–I / A–C rework
- Co-Authored-By / AI attribution in commits
- Implementing production code before RED tests for D.4 order and size fail

### Strict TDD sequence (mandatory)
1. Task 1: builder/model/exception tests RED → dual return + D.4 + size fail GREEN → commit work unit  
2. Task 2: director tests RED → wire BuiltContext GREEN → commit  
3. Task 3: orchestrator notify RED → branch GREEN → full `tests/unit` → commit  
4. Do not mark item done until full unit gate green

### AGENTS.md invariants to preserve
- Director remains 100% deterministic sequencer (ContextBuilder still pure assembly).
- ContextBuilder single question only: minimal context for Generator.
- Behavior outside cognition; Learning post-turn only.
- Anti-contamination: Evaluator still receives capability **names**, not memory/policy bodies.
- Intermediate objects persisted when valid; fail path does not invent evaluation/decision.
- Cognitive Core does not import telegram/behavior.

### Commits (hybrid policy / work-unit-commits)
- One commit = one deliverable behavior (tests with the code they lock).
- Suggested:
  1. `feat(cognitive): ContextBuilder dual BuiltContext, D.4 order, size fail`
  2. `feat(cognitive): Director consumes BuiltContext for prompt and blocks`
  3. `feat(application): notify owner on contexto_excede_limite`
- Conventional commits only; no AI attribution trailers.
- Do not commit unrelated dirty-tree files.

### Logging
Append progress to `.planning/quick/gsd-executor-context-builder-contract.log` with task start/end + pytest results.  
Planner log: `.planning/quick/gsd-planner-context-builder-contract.log`.

### Skills
- Work-unit commits: tests with behavior; no file-type split commits.
- Strict TDD active: test runner `.venv/bin/python -m pytest -q`.

## Test commands

### Primary slice (TDD loop — ContextBuilder)
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_models.py
```

### Critical contract cluster
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_evaluator.py \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/application/test_turn_orchestrator.py
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
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_evaluator.py \
  tests/unit/application/test_turn_orchestrator.py
```

## Risks + Mitigation

| Risk | Level | Mitigation |
|------|-------|------------|
| R1 — D.4 reorder changes Generator LLM input | Medium | Contract-intended. Lock section order with unit tests; re-run director happy path + TAC; do not change Generator system prompt. |
| R2 — Dual return breaks callers | Medium | Only Director production caller. Update Director + all `build` test asserts to `.prompt_final`. |
| R3 — Size limit false positives | Medium | High default (`100_000`); tests inject tiny limit; never truncate. |
| R4 — Orchestrator double FAILED | Low | Existing A.6/B.6 pattern; ensure error token via `mark_failed`. |
| R5 — Comprehension vs strict D.4 list | Low | Locked L3/A3: keep before turn; exclude from blocks. |
| R6 — `style_rules` incomplete vs full REQ-VIP-04 | Low | Empty default; optional lines only; full style pack out of scope. |
| R7 — schedule/profile not in D.4 prose | Low | Fixed tuple after examples (A4/L13); null-like omit. |
| R8 — dict key order independence | Medium | Unit test reversed insertion → fixed heading order. |
| R9 — `list_included_blocks` drift | Medium | Same `_is_null_like` + emission order; parity test vs headings. |
| R10 — Dirty tree pollution | Low | L11: never stage alembic residual / unrelated WIP. |

## Success Criteria

- [ ] `BuiltContext` exists (`prompt_final`, `included_blocks`) with `extra="forbid"`
- [ ] `build(...) -> BuiltContext`; Director stores string under `prompt_text`
- [ ] D.4: Persona → knowledge (fixed order) → Comprehension → **current turn last**
- [ ] Knowledge emission independent of dict insertion order
- [ ] Null-like results never produce knowledge sections / not in `included_blocks`
- [ ] `included_blocks` matches knowledge headings only (no comprehension)
- [ ] Size excess raises exact `contexto_excede_limite`; no truncate; no retry
- [ ] On size fail: turn failed, owner notified, VIP send count 0
- [ ] Happy-path TAC still 3 LLM calls when build succeeds
- [ ] Evaluator names-only / planner no-force-history / import purity still green
- [ ] F1 `Decision.action` still only `approve|escalate`
- [ ] `.venv/bin/python -m pytest -q tests/unit` green
- [ ] No telegram/behavior/learning/alembic/dirty-WIP edits

## Residuals / out of scope (do not touch)

1. Anexos E–I contract alignment (Generator, Decider, …) — separate pool items.
2. Token-accurate budgeting / provider tokenizer integration.
3. Settings/env migration for `max_prompt_chars` (constructor default is enough for F1).
4. Full REQ-VIP-04 style pack productization beyond optional `style_rules` list.
5. `docs/MVP_COMPONENT_DESIGN.md` / SPEC wording that still show early current-turn (documentador residual).
6. Spanish field aliases on models.
7. Analyst / Planner / Evaluator rework (A–C).
8. Telegram, Behavior Engine, Learning, Staging.
9. Alembic / `turns.error` dirty residual.
10. Expanding F1 Decision actions / regenerate loop.

## Self-check checklist for executor

Before marking the item done, confirm:

- [ ] TDD order followed (RED for D.4 order + size fail before production)
- [ ] L1–L14 locked decisions respected (especially dual return, current turn last, exact reason token)
- [ ] `ContextExceedsLimitError.reason == "contexto_excede_limite"` and `str(exc)` matches
- [ ] No silent truncation helpers
- [ ] Director single-source `included_blocks` from build result
- [ ] Orchestrator A.6 + B.6 still green
- [ ] Import purity green
- [ ] Full unit suite green
- [ ] Conventional commits only; no AI attribution
- [ ] No production scope creep into Generator/Decider/Telegram/Anexos E–I
- [ ] Dirty-tree files not staged
