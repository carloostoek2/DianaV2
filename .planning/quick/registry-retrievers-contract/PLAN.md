---
phase: quick
plan: registry-retrievers-contract
type: auto
item: registry-retrievers-contract (Pool remaining-contracts-app · 2/3)
effort: 4
stack: python>=3.12, pydantic-v2, pytest-asyncio
depends_on: context-builder-contract (D.5 null-like bare []), planner-contract (C.2 schedule requestable)
source_of_truth: docs/contratos_restantes.md Anexo H (H.1–H.4 only)
impact: .grok/agent-memory/impact-analyzer/registry-retrievers-contract.md
mode: standard
---

## Objective

Align **Capability Registry + Retrievers** runtime to `docs/contratos_restantes.md` Anexo H (H.1–H.4): static name→Retriever resolve with boot-safe planner universe, uniform read-only `fetch` returning **bare resultado** into Director’s knowledge map, H.3 History/Context payload shapes (empty history `[]` never `None`; Context English H.3 fields), stubs Memory/Policy/Examples stay registered→`None`, Schedule half-registered with `fuente=no_implementado` (resolve never KeyError when planned), Profile kept as F2 optional seat — without Spanish H.2 envelope DTOs, without ContextBuilder D.5 breakage, without cross-retriever imports, and without touching alembic dirty tree.

## Scope

- **In:**
  - `CapabilityRegistry` / `build_default_registry`: resolve map; schedule half-register semantics; optional planner-universe boot resolve check
  - `HistoryRetriever`: empty `[]` never `None`; map port rows → `{autor, texto, timestamp}` **bare list** (no outer `{mensajes:}`)
  - `ContextRetriever`: always non-null object with `waiting_for_reply_since` + `is_first_message_of_day` only (drop preview fields)
  - `ScheduleRetriever`: `fuente = "no_implementado"`, `fetch` → `None`; still resolvable
  - Stubs Memory/Policy/Examples (and Profile F2): still registered, still `None`
  - Protocol/docstring map H.2 envelope ↔ bare resultado; English Context keys ↔ Spanish H.3
  - Unit tests: registry, retrievers, director isolation, context_builder fixtures if shapes change, purity/cross-import gates
- **Out / Non-goals:**
  - Full Spanish H.2 envelope DTO on every fetch / Director unwrap rewrite
  - Outer history wrapper `{mensajes: …}` (breaks D.5 if empty dict-like object; locked bare list)
  - Anexos A–G / I (Analyst, Planner, ContextBuilder redesign, Generator, Decider, Evaluator, TurnCoordinator, Behavior)
  - Port/ORM rename of `role`/`text` columns (map **inside** HistoryRetriever only)
  - Cross-retriever shared snapshot / dual `get_recent` optimization (R7 out of scope)
  - Telegram / Behavior / Learning / Staging
  - Alembic / dirty-tree `turns.error` residual
  - Mass docs sync of `MVP_COMPONENT_DESIGN.md` §5.7 schedule=STUB (documentador residual)
  - F1 `Decision.action` expansion
- **Constraints:** Strict TDD; FakeLLM/InMemory only; cognitive never imports telegram/behavior/infrastructure; retrievers read-only; no retriever→retriever imports; no alembic

## Assumptions

- A1: Director stores `retrieved[cap] = await retriever.fetch(...)` as bare value; ContextBuilder already treats knowledge as `dict[str, Any | None]`. Bare resultado is the F1 runtime of H.2 `{capacidad, resultado, fuente}` (document only).
- A2: Empty history must remain bare `[]` so `_is_null_like` omits the Knowledge:history section (D.5 locked). Non-empty history is a **non-empty** list of mapped dicts → included.
- A3: Context always returns a dict with both keys present → never null-like → `knowledge.context` section always emitted when planned (intentional H.3 “object always”).
- A4: Planner still requests `knowledge.schedule` when `needs_schedule=true` (Anexo C locked). Registry must resolve without KeyError.
- A5: Profile is outside H.3 table but remains registered STUB (TAC-02 / F2 seat). Planner does not emit it in F1.
- A6: Port rows stay `role`/`text`/`timestamp?`; mapping to contract shape is retriever-local only. Infra SQL repo unchanged.
- A7: Bot/assistant/unknown roles are **excluded** from HistoryRetriever output (same vocabulary as Analyst `HistoryMessage`: `vip` | `dueña` only).

## Architecture Approach

### QUÉ (behavior / contracts)

| Contract | Runtime truth after this item |
|----------|-------------------------------|
| H.1 | `CapabilityRegistry.resolve(name) → Retriever`; static map built at composition/`build_default_registry` |
| H.1 fail-fast | Unknown **true** capability names KeyError at resolve; **planner universe** is resolvable after `build_default_registry` (no mid-turn surprise for planned caps). Schedule is half-registered, not “unknown”. |
| H.2 | `fetch(turn, comprehension) → Any \| None` = bare **resultado**; `IncomingTurn` carries `chat_id`. Envelope `{capacidad, resultado, fuente}` is docstring conceptual map only. |
| H.3 History data | Bare `list[{autor, texto, timestamp}]` last N via port; keys match Analyst vocabulary |
| H.3 History empty | `[]` never `None` |
| H.3 Context | Always `dict` with exactly: `waiting_for_reply_since`, `is_first_message_of_day` |
| H.3 Memory/Policy/Examples | Registered stubs → always `None` |
| H.3 Schedule | Half-registered: `resolve("knowledge.schedule")` succeeds; `fetch` → `None`; class attr `fuente == "no_implementado"` |
| H.3 Profile (extra) | Registered STUB → `None` (F2 seat; not in H.3 table) |
| H.4 | Real classes for stubs; no cross-retriever imports; read-only (no writes) |

**History mapping (locked L3):**

| Port row | History resultado item |
|----------|------------------------|
| `role="vip"` | `{"autor": "vip", "texto": <text or "">, "timestamp": <iso or "">}` |
| `role="owner"` | `{"autor": "dueña", "texto": …, "timestamp": …}` |
| `role` in bot/assistant/system/unknown | **drop row** |
| empty chat | `[]` |

Reuse the same role map as Director (`vip`→`vip`, `owner`→`dueña`) **copied locally** in `history.py` (do not import Director; do not create new package). Missing `text` → `""`; missing `timestamp` → `""`.

**Context derivation formulas (locked L4) — history port only:**

```text
waiting_for_reply_since (← esperando_respuesta_desde):
  Walk messages from end → start.
  Consider only roles mappable to vip|dueña (vip, owner).
  If none → None
  If last mappable role is vip → that row's timestamp as str
      (isoformat if datetime-like; str if already str; "" if missing)
  If last mappable role is owner/dueña → None
  (Bot-only tail with no prior human → None)

is_first_message_of_day (← es_primer_mensaje_del_dia):
  today = clock().date()  # default datetime.now(UTC); injectable clock for tests
  Count messages where role == "vip" AND parseable timestamp.date() == today
  True  iff count <= 1
  Empty history → True
  Unparseable/missing timestamps do not count as "today VIP"
```

**Constructor for testability (Context only):**

```python
def __init__(
    self,
    history_port: MessageHistoryPort,
    *,
    limit: int = 20,
    clock: Callable[[], datetime] | None = None,
) -> None:
    self._port = history_port
    self._limit = limit
    self._clock = clock or (lambda: datetime.now(UTC))
```

Do **not** change `Retriever.fetch` Protocol signature.

**Schedule half-register (locked L5):**

```python
class ScheduleRetriever:
    """Half-registered MVP seat (Anexo H.3). fuente=no_implementado; always None."""
    fuente: str = "no_implementado"

    async def fetch(self, turn, comprehension) -> None:
        _ = turn, comprehension
        return None
```

Keep `registry.register("knowledge.schedule", ScheduleRetriever())` so Director loop needs **zero** production change. Export constant for tests:

```python
# registry.py
UNIMPLEMENTED_CAPABILITIES: frozenset[str] = frozenset({"knowledge.schedule"})

PLANNER_CAPABILITY_UNIVERSE: tuple[str, ...] = (
    "knowledge.history",
    "knowledge.context",
    "knowledge.memory",
    "knowledge.policy",
    "knowledge.examples",
    "knowledge.schedule",
)
```

At end of `build_default_registry`, assert each name in `PLANNER_CAPABILITY_UNIVERSE` resolves (loop `resolve`). Profile remains registered outside that universe.

### CÓMO (structure / patterns)

- **Placement:** Cognitive Core only — `registry.py`, `retrievers/*`, optional docstring on `ports.Retriever`. No application/telegram/behavior/learning. No Director production change unless a real assertion requires it (prefer tests-only).
- **Pattern to copy:**
  - PLAN structure: `.planning/quick/planner-contract/PLAN.md` + `.planning/quick/context-builder-contract/PLAN.md`
  - Stub style: `src/diana/cognitive/retrievers/memory.py` / `policy.py`
  - Role map gold: `src/diana/cognitive/director.py` `_ROLE_TO_AUTOR` (copy, don’t import)
  - Null-like consumer: `src/diana/cognitive/context_builder.py` `_is_null_like` (tolerate; do not change for this item)
  - Tests gold: `tests/unit/cognitive/test_retrievers.py`, `test_registry.py`, director isolation test
- **File map:**
  - **Edit:** `registry.py`, `retrievers/history.py`, `retrievers/context.py`, `retrievers/schedule.py`, `ports.py` (docstring only), primary tests
  - **Edit fixtures only:** `test_director.py`, `test_context_builder.py` (shape assertions)
  - **Maybe:** `retrievers/__init__.py` only if export constants
  - **No-touch:** director production logic (prefer), composition signature, planner, analyst, telegram, behavior, learning, alembic, infra history repo
- **Interfaces first:** none new public types; optional module constants on registry
- **Wiring:** `build_default_registry(history)` unchanged call shape; composition already injects port
- **Verificación:** `.venv/bin/python -m pytest -q …` per task; full `tests/unit` before handoff
- **Riesgos:** R1 D.5 / bare list; R2 schedule vs TAC-02; R3 context field rewrite; R4 autor map; R5 no envelope DTO

### English ↔ Anexo H mapping (docs/docstring only)

| Runtime (English) | Anexo H (Spanish) |
|-------------------|-------------------|
| bare `fetch` return value | `resultado` inside conceptual envelope |
| `Retriever.fuente` (schedule only) | `fuente` |
| `waiting_for_reply_since` | `esperando_respuesta_desde` |
| `is_first_message_of_day` | `es_primer_mensaje_del_dia` |
| bare `list[{autor,texto,timestamp}]` | conceptual `{ mensajes: [...] }` alias of the list |
| `IncomingTurn.chat_id` | `chat_id` arg of H.2 |
| `CapabilityRegistry.resolve` | `Registry.resolve` |
| `UNIMPLEMENTED_CAPABILITIES` | half-registered / `no_implementado` seats |

## Locked decisions (NON-NEGOTIABLE)

| ID | Decision |
|----|----------|
| L1 | **Bare resultado** in knowledge map; no H.2 Spanish envelope DTO; document envelope in Protocol/module docstring |
| L2 | History empty = bare `[]` never `None` (D.5 / ContextBuilder null-like) |
| L3 | History non-empty = bare list of `{autor, texto, timestamp}`; **no** outer `{mensajes:}` wrapper; map inside HistoryRetriever; drop bot/unknown roles |
| L4 | Context payload keys **English only**: `waiting_for_reply_since`, `is_first_message_of_day`; Spanish names only in docstring; drop `message_count` / `last_role` / `last_text_preview` |
| L5 | Schedule half-registered: still `resolve` OK + `fuente="no_implementado"` + `fetch→None`; **not** KeyError when planned |
| L6 | Memory/Policy/Examples remain full registered stubs → `None` |
| L7 | Profile stays registered STUB (F2 seat); not in H.3 table; not removed |
| L8 | No cross-retriever imports; read-only; AST gates keep/extend |
| L9 | Keep `fetch(turn, comprehension)` Protocol (chat_id via turn); no chat_id-only signature rewrite |
| L10 | No alembic / dirty-tree / infra ORM schema edits |
| L11 | Strict TDD; FakeLLM/InMemory only |
| L12 | Do not re-open Anexos A–G / I |

## Context

@`.grok/agent-memory/impact-analyzer/registry-retrievers-contract.md`
@`docs/contratos_restantes.md` (Anexo H only)
@`AGENTS.md` (§3 Capability Registry + Retrievers; §5.5 anti-contam; §6.1 new retriever rules)
@`.planning/quick/planner-contract/PLAN.md` (structure gold)
@`.planning/quick/context-builder-contract/PLAN.md` (D.5 null-like; knowledge emission order)
@`src/diana/cognitive/registry.py`
@`src/diana/cognitive/ports.py` (`Retriever`, `MessageHistoryPort`, `InMemoryMessageHistory`)
@`src/diana/cognitive/retrievers/history.py`
@`src/diana/cognitive/retrievers/context.py`
@`src/diana/cognitive/retrievers/schedule.py`
@`src/diana/cognitive/retrievers/memory.py` (stub gold)
@`src/diana/cognitive/director.py` (`_ROLE_TO_AUTOR`, retrieve loop — pattern only)
@`src/diana/cognitive/context_builder.py` (`_is_null_like` — tolerate)
@`tests/unit/cognitive/test_registry.py`
@`tests/unit/cognitive/test_retrievers.py`
@`tests/unit/cognitive/test_director.py` (`test_registry_isolation_*`)
@`tests/unit/cognitive/test_context_builder.py` (fixtures with old context keys)
@`tests/unit/cognitive/test_import_purity.py`

## Tasks

### Task 1: TDD — History + Context H.3 payloads
**type:** auto  
**Objective:** History returns bare mapped list / empty `[]`; Context returns only H.3 English fields with deterministic derivation; stubs still `None`.

**TDD order (mandatory):**
1. Rewrite/extend `tests/unit/cognitive/test_retrievers.py` so current preview/role shapes fail (**RED**).
2. Implement `history.py` + `context.py` (**GREEN**).
3. Keep examples AST anti-contam gate; add empty-history never-None lock.

**Files (edit):**
- `tests/unit/cognitive/test_retrievers.py`
- `src/diana/cognitive/retrievers/history.py`
- `src/diana/cognitive/retrievers/context.py`

**History production intent (`history.py`):**

```python
_ROLE_TO_AUTOR = {"vip": "vip", "owner": "dueña"}

async def fetch(self, turn, comprehension) -> list[dict]:
    _ = comprehension
    raw = await self._port.get_recent(turn.chat_id, limit=self._limit)
    out: list[dict] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        autor = _ROLE_TO_AUTOR.get(str(row.get("role") or ""))
        if autor is None:
            continue
        texto = row.get("text")
        if texto is None:
            texto = ""
        ts = row.get("timestamp")
        if ts is None:
            ts = ""
        elif not isinstance(ts, str) and hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        else:
            ts = str(ts)
        out.append({"autor": autor, "texto": str(texto), "timestamp": ts})
    return out  # may be []
```

**Context production intent (`context.py`):**

- Remove `_PREVIEW_LEN` and preview fields entirely.
- Always return both keys (never `None` from fetch).
- Implement formulas from Architecture Approach; optional `clock` kw-only on `__init__`.

**Tests — replace / add:**

| Action | Test name | Assert |
|--------|-----------|--------|
| **REPLACE** | `test_history_retriever_returns_chat_scoped_messages` | chat 100 only; items use `autor`/`texto`/`timestamp`; assistant row dropped; vip mapped |
| **Keep/adapt** | `test_history_retriever_isolates_chat_ids` | isolation still holds with new shape |
| **Keep/adapt** | `test_history_retriever_respects_limit` | limit still applies at port fetch; mapped length ≤ limit |
| **ADD** | `test_history_retriever_empty_chat_returns_empty_list_not_none` | no seed → `result == []` and `result is not None` |
| **ADD** | `test_history_retriever_maps_owner_to_duena` | `role=owner` → `autor=dueña` |
| **REPLACE** | `test_context_retriever_derives_partial_from_history` | keys exactly `waiting_for_reply_since`, `is_first_message_of_day`; no `message_count` |
| **REPLACE** | `test_context_retriever_empty_history` | empty → `{waiting_for_reply_since: None, is_first_message_of_day: True}` |
| **ADD** | `test_context_waiting_when_last_is_vip` | last mappable vip with ts → waiting equals that ts; `is_first_message_of_day` per clock |
| **ADD** | `test_context_not_waiting_when_last_is_owner` | last owner → `waiting_for_reply_since is None` |
| **ADD** | `test_context_is_first_message_of_day_false_with_two_vip_today` | two vip today (fixed clock) → `False` |
| **Keep** | `test_stubs_return_none` | Profile/Memory/Policy/Examples/Schedule still None |
| **Keep** | `test_examples_stub_has_no_memory_imports_ast` | unchanged |

**Do NOT:**
- Wrap history as `{mensajes: ...}`
- Change port/SQL shapes
- Change ContextBuilder `_is_null_like`
- Import other retrievers or Director

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q tests/unit/cognitive/test_retrievers.py --tb=short
```

**Done:**
- [ ] Empty history `[]` never `None`
- [ ] History items `autor`/`texto`/`timestamp`; bots dropped
- [ ] Context only H.3 English keys; formulas locked by tests
- [ ] Stubs still `None`
- [ ] Command above green

**Commit (work unit 1):**
```
fix(cognitive): align History/Context retrievers to Anexo H.3 shapes
```

---

### Task 2: TDD — Schedule half-register + Registry H.1 universe + Protocol docs
**type:** auto  
**Objective:** Schedule resolvable with `fuente=no_implementado`; planner universe resolves after `build_default_registry`; H.2 mapping documented; Memory/Policy/Examples/Profile seats unchanged.

**TDD order:**
1. Extend `test_registry.py` + schedule asserts in `test_retrievers.py` (**RED** where needed).
2. Edit `schedule.py`, `registry.py`, `ports.py` docstring (**GREEN**).

**Files (edit):**
- `tests/unit/cognitive/test_registry.py`
- `tests/unit/cognitive/test_retrievers.py` (schedule fuente only if not covered)
- `src/diana/cognitive/retrievers/schedule.py`
- `src/diana/cognitive/registry.py`
- `src/diana/cognitive/ports.py` (Retriever docstring only)

**Registry production intent:**

```python
UNIMPLEMENTED_CAPABILITIES: frozenset[str] = frozenset({"knowledge.schedule"})

PLANNER_CAPABILITY_UNIVERSE: tuple[str, ...] = (
    "knowledge.history",
    "knowledge.context",
    "knowledge.memory",
    "knowledge.policy",
    "knowledge.examples",
    "knowledge.schedule",
)

def build_default_registry(...) -> CapabilityRegistry:
    ...
    registry.register("knowledge.schedule", ScheduleRetriever())
    # Boot fail-fast for planner-requested names (H.1)
    for name in PLANNER_CAPABILITY_UNIVERSE:
        registry.resolve(name)
    return registry
```

Keep all seven names registered (history, context, profile, memory, policy, examples, schedule). Profile remains F2 seat. Docstring on `build_default_registry` must state schedule is half-registered / unimplemented.

**Protocol docstring intent (`ports.Retriever`):**

Document that runtime returns bare `resultado`; conceptual Anexo H.2 envelope is `{capacidad, resultado, fuente}`; unimplemented seats may expose `fuente` class attribute; `IncomingTurn` supplies `chat_id`.

**Tests — add / adapt:**

| Action | Test name | Assert |
|--------|-----------|--------|
| **Keep/adapt** | `test_default_registry_resolves_all_seven_capabilities` | still resolves all seven including schedule + profile |
| **Keep** | `test_unknown_capability_raises_key_error` | `knowledge.unknown` → KeyError |
| **Keep** | `test_capabilities_lists_registered_names` | set equality with ALL_CAPS (7 names) |
| **ADD** | `test_schedule_is_unimplemented_seat` | `name in UNIMPLEMENTED_CAPABILITIES`; `resolve` ok; `getattr(retriever, "fuente") == "no_implementado"`; `await fetch(...) is None` |
| **ADD** | `test_build_default_registry_resolves_planner_universe` | every `PLANNER_CAPABILITY_UNIVERSE` name resolves |
| **ADD** | `test_memory_policy_examples_registered_stubs` | resolve each + fetch None (H.4) |
| **ADD** | `test_profile_f2_seat_still_registered` | resolve `knowledge.profile` + fetch None |

**Do NOT:**
- Remove schedule from resolve path
- Make Planner special-case schedule
- Raise at boot for schedule
- Change composition factory signature

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_registry.py \
  tests/unit/cognitive/test_retrievers.py --tb=short
```

**Done:**
- [ ] Schedule resolve OK + fuente + None
- [ ] Planner universe resolvable post-build
- [ ] Seven seats still present (profile F2)
- [ ] Command above green

**Commit (work unit 2):**
```
fix(cognitive): mark knowledge.schedule half-registered (Anexo H.3)
```

---

### Task 3: Blast fixtures + H.4 isolation gates + full unit gate
**type:** auto  
**Objective:** Director isolation + ContextBuilder fixtures match new shapes; H.4 no cross-import / read-only gates; primary cluster + full unit green. Prefer **zero** Director production edits.

**TDD order:**
1. Update assertions/fixtures that still expect `role`/`text` history or `message_count` context (**RED** if left stale).
2. Add H.4 AST gates if missing.
3. Run blast + full unit (**GREEN**).

**Files (edit):**
- `tests/unit/cognitive/test_director.py` — `test_registry_isolation_history_uses_turn_chat_id` history/context asserts; `_STUB_CAPS` may keep schedule (still None)
- `tests/unit/cognitive/test_context_builder.py` — replace fixture `"message_count"` / old context keys with H.3 English keys where asserted in prompt JSON
- Optional: `tests/unit/cognitive/test_retrievers.py` or new helper for cross-import AST over all `retrievers/*.py` (except `__init__.py` / `base.py` re-exports)
- Optional: `tests/unit/cognitive/test_import_purity.py` only if new forbidden import appears (should not)

**Director isolation expected after Task 1:**

```python
assert retrieved["knowledge.history"] == [
    {"autor": "vip", "texto": "from-42", "timestamp": ""},
]
assert retrieved["knowledge.context"] == {
    "waiting_for_reply_since": "",  # or None if empty ts treated as ""; lock to implementation from Task 1
    "is_first_message_of_day": True,  # single vip, no parseable day or only one
}
# stubs including schedule still present and None
```

**Note on empty timestamp:** Task 1 locks missing ts → `""` for history items and for `waiting_for_reply_since` when last is vip without ts. Empty history context uses `None` for waiting. Be consistent in director fixture (seed without ts → waiting `""`).

**ContextBuilder fixtures:** only change values that are string-asserted in prompt (e.g. `"message_count"` → new keys). Do **not** change null-like semantics or emission order.

**H.4 cross-import gate (add if cheap):**

- For each file in `src/diana/cognitive/retrievers/{history,context,memory,policy,examples,profile,schedule}.py`, AST-import graph must not import `diana.cognitive.retrievers.*` peer modules (package `__init__` / `base` re-export only).
- Read-only: those modules must not call/attribute `append`, `commit`, `add`, `delete` on persistence (string/AST lightweight gate is enough; do not over-engineer).

**Do NOT:**
- Edit `director.py` production unless a genuine bug blocks green (unexpected)
- Touch alembic, composition signature, planner, telegram, behavior
- Re-open ContextBuilder contract beyond fixture string updates

**Verification:**
```bash
cd /home/ubuntu/repos/DianaV2
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_registry.py \
  tests/unit/cognitive/test_retrievers.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_import_purity.py \
  --tb=short

.venv/bin/python -m pytest -q \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/infrastructure/test_sql_repo_shapes.py \
  --tb=short

.venv/bin/python -m pytest -q tests/unit --tb=short
```

**Done:**
- [ ] Isolation + CB fixtures green with H.3 shapes
- [ ] H.4 gates present/green
- [ ] Planner still requests schedule; orchestrator still builds registry
- [ ] Full `tests/unit` green
- [ ] No alembic / no-touch list violated

**Commit (work unit 3):**
```
test(cognitive): lock registry/retriever Anexo H blast fixtures
```

## Instrucciones para gsd-executor

- **Strict TDD:** RED → GREEN per task; do not implement production before failing tests for that task’s new asserts.
- **Patterns to copy:** stub modules under `retrievers/memory.py`; role map from `director._ROLE_TO_AUTOR` (copy dict only); prior contract PLANs under `.planning/quick/*-contract/PLAN.md`.
- **Anti-patterns forbidden:**
  - Spanish H.2 envelope objects in `retrieved` map
  - Outer `{mensajes: []}` history wrapper (breaks D.5)
  - Cross-retriever imports or shared mutable snapshot
  - Writing to DB/session from any retriever
  - Removing profile seat “because not in H.3”
  - Making Planner skip schedule
  - KeyError for `knowledge.schedule` when planned
  - Touching alembic / dirty residual
  - Cognitive → telegram/behavior/infrastructure imports
- **Logging / errors:** no new exception types required; unknown capability remains `KeyError` from `resolve`.
- **Commits:** one work-unit commit per task (tests + production that make that unit green). Conventional commits only; no AI attribution.
- **Mock policy:** InMemory history + FakeLLM only at Director blast; never mock HistoryRetriever internals when testing HistoryRetriever; never mock other retrievers from inside a retriever test.
- **AGENTS.md:** Registry answers only name→implementation; each Retriever answers only “what do we know about X?”; anti-contam: history port always chat-scoped; examples never read memories.
- **Skills applicable:** hardener-agile work-unit commits; project AGENTS module limits.

## Test commands

```bash
# Primary cluster
.venv/bin/python -m pytest -q \
  tests/unit/cognitive/test_registry.py \
  tests/unit/cognitive/test_retrievers.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_context_builder.py \
  tests/unit/cognitive/test_planner.py \
  tests/unit/cognitive/test_import_purity.py \
  --tb=short

# Wiring / shape blast
.venv/bin/python -m pytest -q \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/infrastructure/test_sql_repo_shapes.py \
  --tb=short

# Pre-merge
.venv/bin/python -m pytest -q tests/unit --tb=short
```

## Risks + Mitigation

| ID | Risk | Mitigation in tasks |
|----|------|---------------------|
| R1 | `{mensajes:[]}` breaks D.5 | L2/L3 bare list; Task 1 empty lock |
| R2 | Schedule vs seven-cap tests | L5 keep resolve + fuente; Task 2 tests redefine unimplemented seat |
| R3 | Context field rewrite | L4 formulas + fixed clock tests Task 1; fixture updates Task 3 |
| R4 | autor mapping drift | Copy Director map; drop bots; tests for owner→dueña |
| R5 | Envelope over-engineering | L1 docstring only; no Director unwrap |
| R6 | Mid-turn unknown planned cap | Task 2 planner-universe resolve loop at build |
| R8 | Profile removed accidentally | L7 + explicit profile seat test |
| R10 | Doc drift MVP §5.7 | Non-goal; documentador residual |
| Dirty tree | alembic turns.error | L10 no-touch |

## Success Criteria

- [ ] History empty → `[]` never `None`; non-empty → bare list of `{autor,texto,timestamp}` (bots excluded)
- [ ] Context always object with only `waiting_for_reply_since` + `is_first_message_of_day` (English); Spanish names in docstring
- [ ] Memory/Policy/Examples stubs registered → `None`; Profile F2 seat remains
- [ ] Schedule: `resolve` OK, `fuente=="no_implementado"`, `fetch→None`; no KeyError when planned
- [ ] No H.2 envelope in runtime knowledge map; Director loop unchanged (or only incidental)
- [ ] No cross-retriever imports; read-only preserved
- [ ] ContextBuilder still omits empty history `[]`; does not require D.5 rewrite
- [ ] Primary pytest commands + full `tests/unit` green
- [ ] No alembic / no-touch list violated

## Handoff

Next agent: **gsd-executor**  
Execute Task 1 → Task 2 → Task 3 in order under Strict TDD.  
Do not start arch-enforcer until Success Criteria hold.
