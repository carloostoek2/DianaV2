# Impact Analysis: Align Registry + Retrievers to Anexo H (`docs/contratos_restantes.md`)

**Date:** 2026-07-23  
**Change:** Align Capability Registry + Retrievers runtime contracts to Anexo H (H.1–H.4)  
**Analysis only** — no implementación  
**Source of truth:** `/home/ubuntu/repos/DianaV2/docs/contratos_restantes.md` § Anexo H only  
**Pattern reference:** `.planning/quick/planner-contract/`, `.planning/quick/context-builder-contract/`  
**Pool:** remaining-contracts-app · ITEM 2/3  

---

## Executive Summary

Anexo H defines the Capability Registry as a **static name → Retriever map** (`resolve`) and each Retriever as answering only *“what do we know about X?”* with a uniform fetch surface. MVP already has a working registry (`build_default_registry`) and seven modules under `src/diana/cognitive/retrievers/` (history/context REAL via `MessageHistoryPort`; profile/memory/policy/examples/schedule STUB → `None`). Director only resolves **planned** capability names and stores `retrieved: dict[cap → value]`.

**Global risk: medium.** Most H.4 structural invariants already hold (stubs exist as real classes, no cross-retriever imports, read-only). The **confirmed product gaps** are:

1. **ContextRetriever payload shape** does not match H.3 (`esperando_respuesta_desde` / `es_primer_mensaje_del_dia`) — it returns a history-derived preview dict (`message_count`, `last_role`, `last_text_preview`).
2. **History payload shape** is a bare `list[dict]` with port keys `role`/`text`/(optional `timestamp`), not H.3 `{ mensajes: [{autor, texto, timestamp}] }`. Empty-chat **semantics** already match H.3 (`[]`, never `null`).
3. **Schedule “half-registered”** (H.3): contract wants schedule as the only recognized-but-unimplemented capability (`resultado: null`, `fuente: "no_implementado"`, **not** a boot-time missing-cap error). Code fully registers `ScheduleRetriever` as a normal STUB (same as memory/policy/examples). Tests lock **seven** resolved names including schedule (TAC-02 / MVP design).
4. **H.2 fetch envelope** `{ capacidad, resultado, fuente }` is not used; `Retriever.fetch` returns bare `Any | None`. Director + ContextBuilder already treat knowledge as `dict[str, Any | None]` (capability → resultado). Prior contract hardeners mapped Spanish envelopes to English runtime without full Spanish DTOs — recommend same here unless product insists on envelope objects in traces.

**Sensitive systems:** anti-contamination (history/examples chat_id / no memories table); ContextBuilder null-like omission (empty `[]`/`{}` omitted — wrapping history as `{mensajes:[]}` would **break** that); Planner capability names (Anexo C already locked); Director retrieve loop + trace `retrieved`; cognitive import purity (no infrastructure/sqlalchemy in retrievers).

**Scope is valid and tight** if limited to registry + retriever modules + tests, with **minimal** Director/ContextBuilder/ports changes only where shapes must stay coherent. Do **not** re-open Anexos C/D/E/F/G. Do **not** touch alembic `turns.error` residual. Profile remains F2 hook (out of H.3 table; keep registered STUB for TAC-02 unless explicitly de-scoped).

---

## Gap verification (contract vs code)

| Gap | Contract (Anexo H) | Current code | Status |
|-----|--------------------|--------------|--------|
| H.1 single question | name → concrete Retriever, static map | `CapabilityRegistry` dict + `register`/`resolve` | **OK** — keep |
| H.1 resolve API | `resolve(nombre) → Retriever` | `resolve(self, name: str) → Retriever` | **OK** |
| H.1 unknown cap | config error at **boot**, not mid-turn | `KeyError` at **resolve time** (turn loop) | **GAP** — no composition/boot validation of capability set |
| H.2 fetch signature | `fetch(chat_id, comprension) → {capacidad, resultado, fuente} \| null` | `fetch(turn: IncomingTurn, comprehension) → Any \| None` | **Partial** — turn embeds `chat_id`; no envelope/`fuente` |
| H.3 History has data | `{ mensajes: [{autor, texto, timestamp}] }`, last N | bare `list[{role, text, timestamp?}]` from port | **GAP shape** |
| H.3 History empty | `[]` never `null` | port + HistoryRetriever return `[]` | **OK semantics** |
| H.3 Context has/empty | always object with `esperando_respuesta_desde`, `es_primer_mensaje_del_dia` | always dict with `message_count`/`last_role`/`last_text_preview` | **GAP fields** |
| H.3 Memory/Policy/Examples stubs | always `null`, fully registered | `MemoryRetriever`/`PolicyRetriever`/`ExamplesRetriever` → `None` + registered | **OK** |
| H.3 Schedule half-registered | no normal entry; resolve → null + `fuente: "no_implementado"` | fully registered `ScheduleRetriever` STUB → `None` | **GAP** vs H.3 (OK vs MVP §5.7 STUB table) |
| H.4 stubs implement full interface | real classes, substitutable | all stubs have `async fetch` | **OK** |
| H.4 no cross-retriever | isolated modules | only package `__init__` re-exports; no peer imports | **OK** |
| H.4 read-only | no writes | only `MessageHistoryPort.get_recent`; stubs pure | **OK** |
| Profile (extra) | not in H.3 table | `knowledge.profile` STUB registered | **Keep** F2 seat (TAC-02 / MVP) — out of H.3 but intentional |

### Evidence: History empty `[]`

```python
# ports.InMemoryMessageHistory.get_recent → history[-limit:] or []
# HistoryRetriever.fetch → await self._port.get_recent(...)  # never coerces [] → None
```

### Evidence: Context non-H.3 fields

```20:39:src/diana/cognitive/retrievers/context.py
    async def fetch(...) -> dict[str, Any] | None:
        ...
        return {
            "message_count": len(messages),
            "last_role": last.get("role"),
            "last_text_preview": text[:_PREVIEW_LEN],
        }
```

### Evidence: Schedule full registration

```51:55:src/diana/cognitive/registry.py
    registry.register("knowledge.profile", ProfileRetriever())
    registry.register("knowledge.memory", MemoryRetriever())
    registry.register("knowledge.policy", PolicyRetriever())
    registry.register("knowledge.examples", ExamplesRetriever())
    registry.register("knowledge.schedule", ScheduleRetriever())
```

### Evidence: Director bare-value map (no H.2 envelope)

```123:127:src/diana/cognitive/director.py
        retrieved: dict[str, Any | None] = {}
        ...
                retriever = self._registry.resolve(cap)
                retrieved[cap] = await retriever.fetch(turn, comprehension)
```

---

## Consumers / Call Sites Map

### Production — primary (EDIT candidates)

| Location | Role | Impact |
|----------|------|--------|
| `src/diana/cognitive/registry.py` | Map + `build_default_registry` | **EDIT** — schedule half-register / known-unimplemented; optional boot validate set; keep profile F2 seat |
| `src/diana/cognitive/retrievers/history.py` | REAL history | **EDIT** if H.3 shape/wrapper + autor/texto mapping adopted |
| `src/diana/cognitive/retrievers/context.py` | REAL context | **EDIT** — H.3 field names + derivation rules |
| `src/diana/cognitive/retrievers/schedule.py` | STUB schedule | **EDIT or replace** — UnimplementedRetriever / fuente marker |
| `src/diana/cognitive/ports.py` | `Retriever` Protocol | **EDIT optional** — document envelope vs bare value; keep `IncomingTurn` (chat_id) English pattern |
| `src/diana/cognitive/director.py` | resolve+fetch loop; stores retrieved | **Tolerate / minimal** — if envelope adopted, unwrap `resultado` before ContextBuilder; if schedule fuente needed in trace, store meta carefully |
| `src/diana/cognitive/context_builder.py` | null-like + D.4 order | **Tolerate** — empty `[]` still omitted; **do not** wrap history as non-empty dict without updating `_is_null_like` |
| `src/diana/composition.py:175` | `build_default_registry(history)` | **Minimal** — factory signature only if boot validation added |

### Production — stubs (verify-only unless signature changes)

| Location | Role |
|----------|------|
| `retrievers/memory.py`, `policy.py`, `examples.py` | H.4 stubs → `None` |
| `retrievers/profile.py` | F2 hook STUB (keep) |
| `retrievers/__init__.py`, `base.py` | re-exports |

### Production — consumers of retrieved shapes (blast radius)

| Location | Role | Impact |
|----------|------|--------|
| `context_builder.py` | formats knowledge JSON into prompt | Field renames change prompt text; empty history still null-like if bare `[]` |
| `director.py` `_map_history_messages` | Analyst path uses **port history**, not HistoryRetriever output | Separate path — do not confuse with H.3 HistoryRetriever shape |
| `infrastructure/db/repositories/history.py` | port rows `role`/`text`/`timestamp` | **Prefer map inside HistoryRetriever**; avoid forcing ORM/port rename in this item |
| `application/memory.py` InMemory history | same port shape | No change if mapping stays in retriever |
| Planner (`planner.py`) | emits `knowledge.schedule` when needs_schedule | No change (Anexo C locked) |
| Evaluator doctrine path | checks `knowledge.policy` in included_blocks | Unaffected (stubs still null → never included) |

### Do NOT touch (out of scope)

| Location | Why |
|----------|-----|
| Analyst / Planner / Generator / Decider / Evaluator contracts | Already hardened C–F |
| TurnCoordinator (Anexo G) | Separate item |
| Behavior Engine (Anexo I) | Next/other item |
| Learning post-turn | After decision |
| Telegram / Behavior | Cognitive purity |
| Alembic `turns.error` / dirty tree | Residual no-touch |
| MVP_COMPONENT_DESIGN schedule=STUB prose | Doc drift; Anexo H supersedes for this item (documentador residual) |

---

## Risks

### Critical

| ID | Risk | Why | Mitigation |
|----|------|-----|------------|
| **R1 — ContextBuilder null-like break** | If History becomes `{mensajes: []}`, `_is_null_like` treats dict as present → empty “Knowledge: history” block (violates D.5) | ContextBuilder contract already locked | **Keep bare resultado in knowledge map** (Director unwrap). Empty history stays `[]`. Or extend null-like only if planner explicitly re-opens D. |
| **R2 — Schedule vs TAC-02 / seven-cap tests** | H.3 half-register conflicts with tests asserting schedule in `capabilities()` set and full STUB list | `test_registry.py` ALL_CAPS includes schedule; director isolation expects schedule key `None` | Redefine “resolvable” set: known-unimplemented still `resolve()` without KeyError; update registry tests to distinguish **registered REAL/STUB seats** vs **recognized-unimplemented**. Do not remove Planner→schedule mapping. |
| **R3 — Context field rewrite is product behavior change** | Prompt content for `knowledge.context` changes; FakeLLM/traces still pass but semantics differ | Director/context_builder tests assert `message_count` | Define deterministic derivation for `esperando_respuesta_desde` / `es_primer_mensaje_del_dia` from history port only (no new tables). Document formulas in PLAN. Update all assertions. |

### Medium

| ID | Risk | Why | Mitigation |
|----|------|-----|------------|
| **R4 — History autor mapping** | Port uses `role` (`vip`/`owner`/`bot`…); H.3 wants `autor` (`vip`/`dueña`) | Director already maps roles for Analyst via `_ROLE_TO_AUTOR` | Reuse same mapping in HistoryRetriever (or shared pure helper in cognitive, not infra). Drop/skip bot/system rows or include only vip/dueña — **decide explicitly** (H.3 array is autor-only vocabulary). |
| **R5 — H.2 envelope over-engineering** | Full envelope DTO + fuente on every fetch expands Director/trace/schema | Prior hardeners avoided Spanish DTOs when English map is equivalent | **Recommend:** keep `fetch → resultado`; optional `fuente` only for unimplemented schedule (registry-level metadata or thin UnimplementedRetriever). Document H.2 mapping in module docstring. |
| **R6 — Boot fail-fast (H.1)** | Unknown caps currently fail mid-VIP turn | Composition never validates | At `build_default_registry` or composition: assert Planner capability universe ⊆ resolve set ∪ known-unimplemented. Do not invent dynamic config file in F1. |
| **R7 — Dual history fetch race** | History + Context each call `get_recent` independently | Pre-existing hardener note; not new | Out of scope unless cheap: optional shared snapshot later. Do **not** introduce cross-retriever calls (violates H.4). |
| **R8 — Profile seat ambiguity** | H.3 omits profile; registry has it | TAC-02 / MVP 7 caps | Keep profile STUB registered; document as F2 hook outside H.3 table. |

### Low

| ID | Risk | Why | Mitigation |
|----|------|-----|------------|
| **R9 — Examples anti-contam** | Only AST “memory” substring gate | F1 stub never reads DB | Keep AST gate; do not add memories reads. |
| **R10 — MVP doc drift** | MVP §5.7 lists schedule as normal STUB | Anexo H supersedes for this hardener | No prod fix; documentador residual. |
| **R11 — InMemory history missing timestamps** | Tests seed without `timestamp` | H.3 wants timestamp field | Map missing → `""` or omit optional; SQL path already has ISO timestamp. |

---

## Design decisions for gsd-planner (recommended defaults)

| # | Decision | Recommendation | Tradeoff |
|---|----------|----------------|----------|
| L1 | H.2 envelope | **Bare resultado** in runtime knowledge map; document Spanish envelope as conceptual | Less churn vs full DTO |
| L2 | History empty | Keep `[]` never `None`; lock with unit test | Already true |
| L3 | History shape | **Prefer** map inside HistoryRetriever to `{mensajes:[{autor,texto,timestamp}]}` **only if** ContextBuilder/Director knowledge value remains the list **or** null-like updated for wrapper | Safer F1: map fields on list items (`autor`/`texto`/`timestamp`) **without** outer `{mensajes:}` wrapper so D.5 stays intact — document outer wrapper as Spanish alias of the list |
| L4 | Context fields | Implement H.3 keys only (drop preview fields) | Breaking prompt shape — intentional |
| L5 | Schedule | `resolve("knowledge.schedule")` succeeds with unimplemented seat (`resultado None`, `fuente=no_implementado`); **not** KeyError; may remove ordinary STUB registration from “full seats” set | Update TAC-02 tests wording |
| L6 | Memory/Policy/Examples | No behavior change | — |
| L7 | Profile | Keep registered STUB | Out of H.3 |
| L8 | Cross-retriever / write | Enforce with tests (import graph + no session.write) | — |
| L9 | Ports | Keep `IncomingTurn` (has `chat_id`); no chat_id-only signature rewrite | English pattern consistency |
| L10 | Dirty tree | No alembic / turns.error | — |

**Scope validity:** tight enough for one hardener item if L1 avoids full envelope rewrite and L3 avoids D.5 breakage. If product requires literal `{mensajes:…}` **and** H.2 envelope **and** schedule half-register **and** Context field rewrite together with ContextBuilder updates, risk elevates — still one item but budget closer to medium effort.

---

## Affected Tests

### Must update / extend

| File | Why |
|------|-----|
| `tests/unit/cognitive/test_registry.py` | Schedule half-register / known-unimplemented; resolve does not KeyError; optional boot set |
| `tests/unit/cognitive/test_retrievers.py` | History empty `[]`; optional autor/texto map; Context H.3 fields; stubs still None; schedule unimplemented semantics; cross-import AST gate optional |
| `tests/unit/cognitive/test_director.py` | `test_registry_isolation_*` asserts on context keys + schedule presence/None; retrieved history shape |
| `tests/unit/cognitive/test_context_builder.py` | Only if knowledge fixture shapes change (field names in JSON dumps) |
| `tests/unit/infrastructure/test_sql_repo_shapes.py` | **Verify only** if port shape unchanged (preferred) |

### Regression / blast (run, minimal edit)

| File | Why |
|------|-----|
| `tests/unit/cognitive/test_planner.py` | schedule still plannable |
| `tests/unit/cognitive/test_import_purity.py` | no new forbidden imports |
| `tests/unit/application/test_turn_orchestrator.py` | uses `build_default_registry` |
| `tests/unit/acceptance/test_tac_mvp_f1.py` | TAC-02 registry resolve |

### Exact commands

```bash
# Primary cluster (item)
python -m pytest -q \
  tests/unit/cognitive/test_registry.py \
  tests/unit/cognitive/test_retrievers.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_import_purity.py \
  --tb=short

# TAC / wiring blast
python -m pytest -q \
  tests/unit/acceptance/test_tac_mvp_f1.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/infrastructure/test_sql_repo_shapes.py \
  --tb=short

# Full unit (pre-merge)
python -m pytest -q tests/unit --tb=short
```

---

## Files Map

### Edit (likely)

- `src/diana/cognitive/registry.py`
- `src/diana/cognitive/retrievers/context.py`
- `src/diana/cognitive/retrievers/history.py` (shape/mapping if L3)
- `src/diana/cognitive/retrievers/schedule.py` (or replace with unimplemented seat)
- `src/diana/cognitive/ports.py` (docstring / Protocol notes only unless envelope)
- `tests/unit/cognitive/test_registry.py`
- `tests/unit/cognitive/test_retrievers.py`
- `tests/unit/cognitive/test_director.py`
- possibly `tests/unit/cognitive/test_context_builder.py` (fixtures only)

### Edit (minimal / conditional)

- `src/diana/cognitive/director.py` — only if unwrap envelope or schedule meta in retrieved
- `src/diana/composition.py` — only if boot validation hook
- `src/diana/cognitive/retrievers/__init__.py` — export changes

### Create (optional)

- shared pure helper for role→autor mapping (if extracted from Director) under `cognitive/` — **not** new package

### No touch

- Analyst/Planner/Generator/Evaluator/Decider production logic (beyond incidental fixtures)
- Behavior / Telegram / Learning
- Alembic / infra ORM schema
- `docs/MVP_COMPONENT_DESIGN.md` (documentador residual)
- TurnCoordinator

---

## Ready for chain

Handoff a **gsd-planner** with **tight scope**:

1. **H.1** Keep static `CapabilityRegistry.resolve`; add known-unimplemented handling for schedule; optional composition-time capability universe check (no mid-turn surprise for planned caps).
2. **H.3 History** Lock empty `[]` never `None`; map message fields toward `autor`/`texto`/`timestamp` **without** breaking ContextBuilder empty omission (prefer bare list as resultado).
3. **H.3 Context** Replace payload with explicit `esperando_respuesta_desde` + `es_primer_mensaje_del_dia` derived only from `MessageHistoryPort` (deterministic rules in PLAN).
4. **H.3/H.4 Stubs** Leave memory/policy/examples → `None` + registered; keep profile F2 seat.
5. **H.3 Schedule** Half-registered / `fuente: "no_implementado"` semantics; Planner may still request; resolve never KeyError.
6. **H.4** Preserve no cross-retriever imports + read-only; add/keep AST gates as needed.
7. **H.2** Document mapping; avoid full Spanish envelope DTO unless review demands it.
8. Tests: registry + retrievers + director isolation + purity + primary cluster commands above.
9. Arch-enforcer: AGENTS §3/§5 retrievers; TAC-02 reinterpretation; purity.
10. Test-guardian: no prohibited mocks; lock empty history, context fields, schedule resolve, stubs null.

**DoD for downstream**

| Role | Must verify |
|------|-------------|
| **gsd-planner** | PLAN lists L1–L10 decisions; explicit Context derivation formulas; schedule semantics; D.5 non-break |
| **executor** | Strict TDD; only files in Edit map; no alembic |
| **arch-enforcer** | Director still name-only; no cognitive→infra; no retriever→retriever; no writes; stubs substitutable |
| **test-guardian** | Commands green; TAC-02 updated for half-register; empty history + context fields locked |

**Analysis only complete.** Next: gsd-planner.
