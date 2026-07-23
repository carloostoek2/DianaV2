# Impact Analysis: Align ContextBuilder contract to Anexo D (`docs/contratos_restantes.md`)

**Date:** 2026-07-23  
**Change:** Align ContextBuilder (Constructor de Contexto) runtime + output shape + D.4 order + D.5/D.6 size-fail path to Anexo D (D.1–D.6 only)  
**Analysis only** — no implementación  
**Source of truth:** `/home/ubuntu/repos/DianaV2/docs/contratos_restantes.md` § Anexo D only  
**Pattern reference:** `.planning/quick/evaluator-contract/`, `.planning/quick/planner-contract/`, `exceptions.py` typed fail paths  
**Pool:** remaining-contracts-cognitive · ITEM 2/4 · effort 4  
**Prior golds:** planner-contract (C.3 force-history removed); evaluator-contract (`list_included_blocks` already exists)

---

## Executive Summary

ContextBuilder today is a small deterministic assembler in `src/diana/cognitive/context_builder.py`: `build(turn, comprehension, knowledge, persona) -> str` plus `list_included_blocks(knowledge) -> list[str]`. It already **omits null-like knowledge** (`None`, empty collections, blank strings) and exports block **names** that match `## Knowledge:` headings — that piece was locked by evaluator-contract (L3/L4) and must not regress.

Anexo D requires more than null-omit:

1. **D.3 dual output** — `ContextoConstruido { prompt_final, bloques_incluidos }` from a single assembly pass (not `str` + separate recompute).
2. **D.4 fixed order** — persona/voice always first; knowledge blocks in fixed capability order (history → context → memory → policy → examples); **`turno_actual` always last**. Current code places **current VIP message second** (right after persona), then comprehension, then knowledge in **dict iteration order**. That is a **confirmed D.4 violation**.
3. **D.5/D.6 size excess** — no prompt-budget check today; no typed reason `contexto_excede_limite`; silent truncation is absent (good) but explicit fail path is missing. Only own failure path; **no auto-retry**.

**Global risk: medium.** Blast radius is ContextBuilder + Director call site + optional models/exceptions + Orchestrator typed fail branch (mirror Analyst/Evaluator). Generator stays `generate(prompt: str)` — only the string changes content/order. Evaluator continues to receive `included_blocks` names; source should become the build result (single source of truth). Sensitive systems: deterministic Director control flow; REQ-NFR-07 prompt budget; anti-contamination (Evaluator still names-only); cognitive import purity; F1 Decision.action remains `approve|escalate`.

**Scope is valid and tight** for effort 4 if planner locks: (a) English `BuiltContext` dual return, (b) D.4 reorder + fixed capability emission order, (c) char-budget fail with typed exception + orchestrator notify, (d) keep null-like rules as-is (stricter than bare `!= null`, already gold). Out of scope: Anexos E–I, A–C rework, dirty-tree alembic/`turns.error` residual, Behavior, Telegram redesign, live tokenizers.

No re-partition required. If size-limit config sprawls into Settings + DeepSeek token counting + multi-PR notify polish, **slice size-fail as same PR still** (pattern is known from A.6/B.6) rather than splitting pools.

---

## Gap verification (contract vs code)

| Gap | Contract (Anexo D) | Current code | Status |
|-----|--------------------|--------------|--------|
| D.1 single question | Minimal context for Generator; assemble, no draft text | Docstring + pure string assembly; no LLM | **OK** — keep |
| D.1 no evaluate | Must not score/decide | No eval/decision code | **OK** |
| D.2 input comprehension | `comprension` | `comprehension: Comprehension` param | **OK** — English map in docstring |
| D.2 knowledge shape | `Array[{capacidad, resultado}]` | `knowledge: dict[str, Any \| None]` | **OK practical** — dict is Director/Registry shape; document map; do **not** force Array DTO unless planner wants pure contract isomorphism |
| D.2 `voz_configurada` | `{ persona, reglas_estilo: string[] }` | `persona: str` only; `DEFAULT_PERSONA` in composition | **PARTIAL gap** — no `style_rules` / `reglas_estilo` |
| D.2 current turn | Used as final block (D.4.7) | Via `IncomingTurn.text` | **OK** as source; **order wrong** (see D.4) |
| D.3 output dual | `{ prompt_final, bloques_incluidos }` | `build → str`; separate `list_included_blocks` | **CONFIRMED gap** — unify |
| D.3 bloques subset | Non-null results that entered prompt | `_is_null_like` filter; names = knowledge headings | **OK semantics** — keep null-like (stricter than `!= null`); lock dual-return consistency |
| D.4.1 persona always | Always present | `## Persona` first | **OK** |
| D.4.2–6 knowledge fixed order | history → context → memory → policy → examples (if present) | Emits in `knowledge.items()` order | **PARTIAL** — works only if Director inserted in plan order; **must not rely on dict order** |
| D.4.7 `turno_actual` last | Always last before Generator writes | `## Current VIP message` is **second** block | **CONFIRMED gap** |
| D.4 comprehension section | Not listed in D.4 | Always emits `## Comprehension` mid-prompt | **Design decision** — recommend keep (Generator utility) **before** current turn; document as L-decision (not a knowledge block; not in `bloques_incluidos`) |
| D.4 schedule/profile | Not in D.4 list | May appear if non-null (schedule plannable; profile F2 hook) | **Design decision** — fixed slots after examples, before current_turn: `knowledge.schedule`, then `knowledge.profile` |
| D.5 never null placeholders | No empty section for null | `_is_null_like` skip — tested | **OK** — keep mandatory tests |
| D.5 no silent truncate | Fail explicit if over limit | No size check; full content always joined | **CONFIRMED gap** (fail path missing) |
| D.5 reason token | `Turn.status=failed`, motivo `contexto_excede_limite` | No typed exception; generic Exception → `str(exc)` | **CONFIRMED gap** |
| D.6 only size fail own path | No auto-retry | N/A until size check exists | **OK intent** — implement raise-once only |
| D.6 not Planner/retry same turn | Config fix, not retry | N/A | **OK** — do not add retry loop |

### D.4 order evidence (current)

```26:46:src/diana/cognitive/context_builder.py
        parts: list[str] = [
            "## Persona",
            persona.strip(),
            "",
            "## Current VIP message",
            turn.text,
            "",
            "## Comprehension",
            ...
        ]
        for name, value in knowledge.items():
            if _is_null_like(value):
                continue
            ...
```

Contract-required end state (conceptual):

1. Persona (+ optional style rules)  
2. Knowledge in fixed order (only non-null-like)  
3. Comprehension summary (**recommended**, locked by planner — not in D.4 list)  
4. **Current turn last**

### Size-fail pattern gold (mirror)

- `AnalystSchemaInvalidError` / `EvaluatorSchemaInvalidError` in `exceptions.py`
- Director: re-raise; outer `handle_turn` → `TurnStatus.FAILED`
- Orchestrator: typed branch → `mark_failed(..., error="<token>")` + `admin.notify_info(...)`; no VIP send

Apply same for e.g. `ContextExceedsLimitError` with `reason = "contexto_excede_limite"`.

---

## Consumers / Call Sites Map

### Production — ContextBuilder (EDIT core)

| Location | Role | Impact |
|----------|------|--------|
| `src/diana/cognitive/context_builder.py:11-69` | `build`, `list_included_blocks`, `_is_null_like`, `_format_value` | **EDIT** — D.4 order; dual return; size check; optional style_rules |
| `src/diana/cognitive/models.py` | Domain DTOs; no BuiltContext today | **EDIT** — add `BuiltContext` (English: `prompt_final` or `prompt_text`? see L-decisions) |
| `src/diana/cognitive/exceptions.py` | Analyst + Evaluator typed errors only | **EDIT** — add size-limit typed error |
| `src/diana/cognitive/director.py:133-154` | `build(...)` → store `prompt_text`; `list_included_blocks(retrieved)` → Evaluator | **EDIT** — consume dual return; pass `built.prompt` to Generator; `built.included_blocks` to Evaluator |
| `src/diana/cognitive/generator.py:18-23` | `generate(prompt: str)` | **No signature change** — still receives final string (Anexo E out of scope) |
| `src/diana/cognitive/evaluator.py` | Uses `included_blocks` names | **No change** if Director still passes correct list |
| `src/diana/composition.py:54-57,180,185` | `ContextBuilder()`, `DEFAULT_PERSONA` | **Maybe** — inject max chars / empty style_rules; keep simple defaults |
| `src/diana/application/turn_orchestrator.py:12,106-152` | Typed fail for Analyst/Evaluator | **EDIT** — third branch for `contexto_excede_limite` + notify |
| `src/diana/config.py` | Settings; no prompt budget | Prefer **constructor default constant** over new Settings field (effort 4); optional env later |

### Production — do NOT touch (out of scope)

| Location | Why |
|----------|-----|
| Planner / Analyst / Decider contracts | Already aligned or separate items |
| Retrievers / Registry | Order of assembly is ContextBuilder’s job (Anexo I note); retrieval stays plan-driven |
| Behavior / Telegram / Learning | Cognitive boundary |
| Alembic / `turns.error` residual | Dirty tree — **leave alone** (column already used by mark_failed) |
| Anexos E–I (Generator contract rewrite, etc.) | Separate pool items |
| `docs/MVP_COMPONENT_DESIGN.md` §5.8 outdated signature | Documentador residual; do not re-break order to match old MVP sketch |

### Tests — primary + regression

| Location | Role |
|----------|------|
| `tests/unit/cognitive/test_context_builder.py` | **Primary** — order, null-omit, dual return, size fail, included_blocks consistency |
| `tests/unit/cognitive/test_director.py` | Happy path `prompt_text`; included_blocks → Evaluator; add size-fail if Director surfaces error |
| `tests/unit/application/test_turn_orchestrator.py` | Gold notify tests for Analyst/Evaluator — **add** `contexto_excede_limite` twin |
| `tests/unit/cognitive/test_models.py` | Optional `BuiltContext` shape |
| `tests/unit/cognitive/test_evaluator.py` | Must stay green (names-only, doctrine guidance) |
| `tests/unit/cognitive/test_import_purity.py` | Boundary — keep green |
| `tests/unit/cognitive/test_planner.py` | No force-history gold — keep green |
| Acceptance TAC | LLM call count unchanged on happy path (still 3); size-fail aborts before Generator |

### Call-site line map (Director)

```133:154:src/diana/cognitive/director.py
        await self._status.transition(turn_id, TurnStatus.BUILDING_CONTEXT)
        prompt = self._context_builder.build(
            turn,
            comprehension,
            knowledge=retrieved,
            persona=self._persona,
        )
        await self._store(turn_id, "prompt_text", prompt)
        ...
        draft = await self._generator.generate(prompt)
        ...
        blocks = self._context_builder.list_included_blocks(retrieved)
        evaluation = await self._evaluator.evaluate(
            EvaluatorInput(..., included_blocks=blocks, ...)
        )
```

After change (conceptual): one `built = build(...)`; store `built.prompt_final`; `generate(built.prompt_final)`; `included_blocks=built.included_blocks`. Trace key stays `prompt_text` (SQL column) — store the string, not the whole DTO.

---

## Risks

### Critical

None for architecture layers if Cognitive stays free of telegram/behavior and size fail is typed + application-notified (same as A.6/B.6).

### Medium

| Risk | Why | Mitigation |
|------|-----|------------|
| **R1 — D.4 reorder changes Generator prompt** | Moving current turn to end + fixed knowledge order changes LLM input vs all prior F1 behavior | Contract-intended. Lock with unit tests on section order (index/find order of headings). Re-run director happy path + TAC. Do not change Generator system prompt in this item. |
| **R2 — Dual return breaks call sites** | `build` currently returns `str`; Director + 3 orchestrator test constructors + composition | Grep-enforced: only Director production caller. Update Director + any test that asserts `isinstance(prompt, str)` on return. Keep `list_included_blocks` as thin wrapper over same filter for backward compat **or** derive only from BuiltContext (prefer single path). |
| **R3 — Size limit false positives / false negatives** | No real tokenizer; char proxy ≠ tokens; default too low breaks normal history | Inject `max_prompt_chars` on ContextBuilder (constructor). Default **high** enough for F1 history+context (e.g. 32k–100k chars) so happy path never trips; tests inject tiny limit for fail path. **Do not** silent-truncate to fit. Document char proxy as F1 approximation of provider limit. |
| **R4 — Orchestrator double FAILED transition** | Director already transitions FAILED on any Exception; orchestrator `mark_failed` again | Existing pattern for Analyst/Evaluator — keep. Ensure error **token** is written by orchestrator `mark_failed(error=...)`. |
| **R5 — Comprehension block vs strict D.4** | D.4 list omits comprehension; code always includes it; tests assert `intent:` | **Lock decision:** keep non-knowledge `## Comprehension` section **after** knowledge blocks and **before** current turn; exclude from `bloques_incluidos`. Do not invent capability name for it. |
| **R6 — `reglas_estilo` incomplete vs REQ-VIP-04** | D.2 lists style rules; composition has only persona string | Minimal: accept `style_rules: list[str] = []`; if non-empty, append under persona section. Empty default = no behavior change. Full product style pack out of scope. |

### Low

| Risk | Why | Mitigation |
|------|-----|------------|
| **R7 — schedule/profile not in D.4** | Planner can request schedule; profile is F2 hook | Fixed emission order tuple includes them after examples. Null-like still omits. |
| **R8 — knowledge dict key order independence** | Random/shuffled keys must still D.4 | Unit test: pass dict with reversed key insertion; assert heading order fixed. |
| **R9 — `list_included_blocks` order** | Evaluator/doctrine only cares about membership of `knowledge.policy`; order may still be asserted | Return blocks in **D.4 emission order** (stable), matching prompt headings order (existing test). |
| **R10 — MVP_COMPONENT_DESIGN / SPEC residual** | Docs still show current-turn early | Out of scope for code item; documentador later. |
| **R11 — Strict TDD red first** | Order tests + size-fail tests will fail on current code | Expected; planner tasks: red → green per surface. |

### Non-risks (explicit)

- Generator API / Anexo E — still receives a string.
- EvaluationProfile 7D / Decider matrix — untouched.
- Planner empty plan — ContextBuilder already builds persona+turn(+comprehension) with no knowledge; after D.4 still valid.
- Import purity — no new layer deps if exception stays in cognitive and notify stays in application.
- Migrations — not required; `turns.error` column already used.

---

## Affected Tests

### Primary (write / invert first under Strict TDD)

```bash
# ContextBuilder unit (primary surface)
python -m pytest tests/unit/cognitive/test_context_builder.py -q

# Suggested new/updated cases inside that module:
# - test_d4_current_turn_is_last_section
# - test_d4_knowledge_emitted_in_fixed_order_regardless_of_dict_insertion
# - test_null_knowledge_omits_stub_headings (keep)
# - test_empty_list_and_dict_knowledge_omitted (keep)
# - test_build_returns_built_context_prompt_and_blocks (dual return)
# - test_included_blocks_match_knowledge_headings_order (keep/adapt)
# - test_contexto_excede_limite_raises_typed_error_no_truncate
# - test_style_rules_optional_under_persona (if L includes style_rules)
```

### Integration / consumer

```bash
python -m pytest tests/unit/cognitive/test_director.py -q
python -m pytest tests/unit/application/test_turn_orchestrator.py -q -k "schema_fail or contexto or context"
python -m pytest tests/unit/cognitive/test_evaluator.py -q
python -m pytest tests/unit/cognitive/test_models.py -q
python -m pytest tests/unit/cognitive/test_import_purity.py -q
```

### Gate commands (exact)

```bash
# Critical contract cluster
python -m pytest \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_evaluator.py \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/application/test_turn_orchestrator.py \
  -q

# Full unit suite (pre-merge / test-guardian)
python -m pytest tests/unit -q
```

### Gold / critical assertions to preserve

- Null-like omit (D.5 first invariant) — already gold.
- `list_included_blocks` ≡ knowledge headings (evaluator-contract).
- Director passes included_blocks names to Evaluator without raw knowledge dump.
- Orchestrator typed fail: `mark_failed` error token + `notify_info` + `send_count()==0`.
- Planner C.3 no force-history — regression green.
- Import purity cognitive → no telegram/behavior.

---

## Files Map

### Edit (expected)

- `src/diana/cognitive/context_builder.py` — D.4 order, dual return, size check, optional style_rules
- `src/diana/cognitive/models.py` — `BuiltContext` (or `ConstructedContext`) English fields + docstring map to D.3
- `src/diana/cognitive/exceptions.py` — `ContextExceedsLimitError` / reason `contexto_excede_limite`
- `src/diana/cognitive/director.py` — consume BuiltContext; single source for prompt + blocks
- `src/diana/application/turn_orchestrator.py` — typed fail branch + owner notify
- `tests/unit/cognitive/test_context_builder.py` — primary TDD surface
- `tests/unit/cognitive/test_director.py` — wiring / order-in-trace / fail path
- `tests/unit/application/test_turn_orchestrator.py` — `contexto_excede_limite` notify gold
- `tests/unit/cognitive/test_models.py` — optional BuiltContext shape (if model added)

### Maybe (planner discretion, keep minimal)

- `src/diana/composition.py` — pass `max_prompt_chars` / empty `style_rules` only if not defaulted on class
- `src/diana/cognitive/__init__.py` / exports — only if package re-exports exceptions

### Create

- None required for production  
- Optional planning artifacts by gsd-planner: `.planning/quick/context-builder-contract/PLAN.md`

### No touch

- `alembic/versions/*`, dirty `turns.error` residual work
- Retrievers, Registry, Planner, Analyst, Decider, Generator contract rewrites
- Behavior Engine, Telegram handlers, Learning
- Anexos E–I implementation
- Mass unrelated `.grok/agent-memory` rewrites outside this item

---

## Recommended locked decisions for gsd-planner

| ID | Decision |
|----|----------|
| L1 | **English identifiers:** `BuiltContext.prompt_final` + `BuiltContext.included_blocks` map to D.3 Spanish names in docstring only. Trace/SQL still stores string under key/column `prompt_text`. |
| L2 | **API:** `build(...) -> BuiltContext`. Keep `list_included_blocks(knowledge)` as thin shared filter **or** implement via same private helper used by build (must not diverge). Prefer build as single assembly entry for Director. |
| L3 | **Null-like (keep evaluator gold):** `None`; empty `list`/`dict`/`tuple`/`set`; empty/whitespace `str`. Stricter than bare `resultado != null` — intentional F1. |
| L4 | **D.4 knowledge emission order (fixed tuple):** `knowledge.history`, `knowledge.context`, `knowledge.memory`, `knowledge.policy`, `knowledge.examples`, `knowledge.schedule`, `knowledge.profile`. Skip missing/null-like. Ignore unknown keys or append after profile deterministically (prefer **ignore unknown** + log-free skip for F1). |
| L5 | **Section order:** Persona (+ optional style rules) → knowledge sections (L4) → Comprehension summary → **Current VIP message last**. |
| L6 | **Comprehension:** not in `included_blocks`; always present if build succeeds (uses required Comprehension fields). |
| L7 | **Size limit:** constructor `max_prompt_chars: int` with high default; measure final prompt string length; if `len(prompt) > max_prompt_chars` raise typed error **before** return; no truncation; no retry. |
| L8 | **Typed error:** `ContextExceedsLimitError` with `.reason == "contexto_excede_limite"` and `str(exc) == "contexto_excede_limite"`. |
| L9 | **Orchestrator:** same notify pattern as A.6/B.6; no VIP send; Learning not required on fail path (existing). |
| L10 | **style_rules:** optional `list[str] = []`; empty = omit; non-empty under persona block. No Settings migration required. |
| L11 | **Strict TDD;** FakeLLM/InMemory only; no live network. |
| L12 | **Out of scope:** Anexo E Generator DTO rename, Decider, Telegram, Alembic residual, token-accurate budgeting, Spanish field aliases on models. |

---

## DoD for downstream chain

### gsd-planner

- [ ] PLAN with locked L1–L12 (or equivalent), task order: tests red → models/exception → ContextBuilder → Director → Orchestrator → full unit gate
- [ ] Explicit file list matching Files Map; no dirty-tree files
- [ ] Exact pytest commands above in PLAN verification section
- [ ] Note: dual return + D.4 order + size fail are **one item**; do not expand to Generator Anexo E

### Executor (sdd-apply / implementer)

- [ ] Strict TDD per task surface
- [ ] No production code without failing test first for D.4 order and size fail
- [ ] Director single-source `included_blocks` from build result
- [ ] Cognitive import purity preserved
- [ ] Happy-path TAC LLM call count still 3 (size fail does not add retries)

### arch-enforcer

- [ ] Director still deterministic sequencer; ContextBuilder no LLM
- [ ] No Behavior/Telegram imports from cognitive
- [ ] `bloques_incluidos` / included_blocks remain capability **names**, not bodies
- [ ] Fail path reason token exact `contexto_excede_limite`
- [ ] No silent truncation helpers

### test-guardian

- [ ] Primary cluster green + full `tests/unit`
- [ ] Order independence test present
- [ ] Size-fail: typed reason + orchestrator notify + no actuator send
- [ ] Null-omit + included_blocks↔headings still locked
- [ ] No forbidden live mocks; FakeLLM only

---

## Ready for chain

**Handoff → gsd-planner** with scope:

> Align ContextBuilder to Anexo D.1–D.6 only: fixed D.4 assembly (current turn last; fixed knowledge order; null-like omit), `BuiltContext` dual output, explicit `contexto_excede_limite` fail (no retry, no truncate), optional empty `style_rules`, Director+Orchestrator wiring mirroring evaluator-contract typed fail gold. Leave Anexos E–I, dirty alembic tree, and A–C alone.

**status:** complete  
**next:** gsd-planner  
**report:** `.grok/agent-memory/impact-analyzer/context-builder-contract.md`  
**log:** `.planning/quick/gsd-impact-analyzer-context-builder-contract.log`
