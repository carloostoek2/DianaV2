---
phase: 02
plan: cognitive-core
type: auto
item: 2/4
effort: 5
stack: python>=3.12, pydantic-v2, httpx, pytest-asyncio
depends_on: 01-foundation
---

## Objective

Implement the **Fase 1 cognitive decision path** (Director → Analyst → Planner → Registry/Retrievers → ContextBuilder → Generator → Evaluator → Decider) plus abstract `LLMProvider` + DeepSeek (httpx) and `FakeLLM` for unit tests. Foundation already froze pure Pydantic contracts (`Comprehension`, `Plan`, `EvaluationProfile` 7D, `Decision` approve|escalate, `IncomingTurn`, `TurnStatus`) and import purity. This item produces a clean `CognitiveDirector.handle_turn(turn_context) -> Decision` with no Telegram, Behavior, Learning, or delivery ownership.

## Context

@`.grok/agent-memory/impact-analyzer/02-cognitive-core.md`
@`.planning/phases/01-foundation/PLAN.md`
@`.planning/phases/01-foundation/SUMMARY.md`
@`docs/MVP_COMPONENT_DESIGN.md` (§5.4–5.11 Director–Decider, §8 LLMProvider)
@`AGENTS.md` (§3 module limits, §5.1 Director, §5.2 EvaluationProfile, §5.3 Decision)
@`src/diana/cognitive/models.py` (frozen L1/L2)
@`tests/unit/cognitive/test_import_purity.py` (hard gate — scans all `cognitive/**/*.py`)
@`src/diana/config.py` (`deepseek_api_key`, `llm_base_url`)

**Repo state:** foundation DONE (58 unit tests green). `src/diana/cognitive/` is models-only. No `llm/`, director, retrievers, or pipeline logic.

**Locked decisions (NON-NEGOTIABLE):**

| ID | Decision |
|----|----------|
| L1–L8 | Foundation freezes stand. **Do not** expand `Decision.action`, collapse 7D eval, add F2 tables, or put secrets in repo. |
| L9 | **Ports+DI:** cognitive never imports `diana.llm`, `diana.infrastructure`, `sqlalchemy`, `aiogram`, `diana.telegram`, `diana.behavior`, `diana.learning`, `diana.application`. Purity AST test remains green. |
| L10 | `CognitiveDirector.handle_turn(self, turn_context: IncomingTurn) -> Decision`. Optional `TurnStatusSink` for status transitions (no-op / in-memory in tests). **No** ORM `Turn` entity inside cognitive. |
| L11 | LLM use: Analyst + Evaluator → `generate_structured`; Generator → `generate`; **Planner, Decider, Director, Registry, ContextBuilder, Retrievers = zero LLM**. |
| L12 | Retrievers: `knowledge.history` REAL via `MessageHistoryPort`; `knowledge.context` REAL partial from history port; `profile`/`memory`/`policy`/`examples`/`schedule` STUB → `None`. |
| L13 | `TraceStore` protocol records 7 cognitive artifacts. Item 2 ships **InMemoryTraceStore** for units. SQL `TraceRepository` is **out** (item 3 may add). |
| L14 | Unit tests: FakeLLM + `httpx.MockTransport` only. **No live DeepSeek / no real network** in CI. |
| L15 | Decider F1 matrix: escalate if `evaluation.safety < safety_threshold` **or** `comprehension.risk == "alto"`; else approve. Always attach `draft_text` from Generator. Default `safety_threshold = 0.3`. Reasons: `safety_below_threshold` / `risk_high` / `ok_for_human_review` (prefer distinct reasons over single combined string). |
| L16 | `TurnContext` = use `IncomingTurn` as the public handle_turn argument (alias `TurnContext = IncomingTurn` allowed in models/ports; no second ORM-shaped type). |
| L17 | Composition root / `main.py` wiring is **item 3/4**. Factories inside tests are OK. |

## Constraints

- **Strict TDD Mode active:** write failing unit tests first for each task surface, then minimal implementation until green.
- **0 behavior / Telegram / Learning** packages created or imported from cognitive.
- **No schema changes** — do not edit Alembic versions or `infrastructure/db/models.py`.
- Code/comments/identifiers/README deltas: **English**.
- No Redis, LangChain, Celery, LangGraph as orchestrator.
- Do not weaken foundation invariant tests.
- Prefer constructing `Decision(..., draft_text=draft)` immutably over mutating after `decide` (R5).

## Tasks

### Task 1: Cognitive ports + FakeLLM + DeepSeek provider
**type:** auto  
**Objective:** Freeze I/O boundaries so cognitive stays pure and LLM is swappable. Deliver protocols, test double, and real DeepSeek client (mocked HTTP only in tests).

**TDD order:** tests first for FakeLLM + DeepSeek mock → implement.

**Files (create):**
- `src/diana/cognitive/ports.py`
- `src/diana/llm/__init__.py`
- `src/diana/llm/fake.py`
- `src/diana/llm/deepseek.py`
- `tests/unit/llm/test_fake_llm.py`
- `tests/unit/llm/test_deepseek_provider.py`

**`cognitive/ports.py` protocols (exact intent):**

```python
# LLMProvider
name: str
async def generate(messages: list[dict], *, temperature: float = 0.7, max_tokens: int = 1024) -> str: ...
async def generate_structured(messages: list[dict], schema: type[BaseModel], **kwargs) -> BaseModel: ...

# Retriever
async def fetch(turn: IncomingTurn, comprehension: Comprehension) -> Any | None: ...

# MessageHistoryPort
async def get_recent(chat_id: int, *, limit: int = 20) -> list[dict]: ...
# each dict: at least {role, text, timestamp?} — chat-scoped only

# TraceStore
async def store(turn_id: UUID, key: str, value: Any) -> None: ...
# keys used by Director: comprehension | plan | retrieved | prompt | generated | evaluation | decision

# TurnStatusSink
async def transition(turn_id: UUID, status: str | TurnStatus) -> None: ...
```

Also provide **test helpers in `llm/fake.py` or ports** (may live under `cognitive` only if pure):
- `InMemoryTraceStore` — dict keyed by `turn_id` → nested key/value (or list of events); unit-test readable.
- `InMemoryMessageHistory` — map `chat_id -> list[dict]`; implements `MessageHistoryPort`.
- `NoOpTurnStatusSink` / `InMemoryTurnStatusSink`.

**`FakeLLM` requirements:**
- Scriptable: queue/map of text responses and structured model instances (or factories).
- Records every call (`generate` / `generate_structured` args) for TAC-01 assertions.
- Async methods matching `LLMProvider`.
- Does **not** live under `cognitive/` if that would tempt cognitive→llm imports; cognitive components receive `LLMProvider` via constructor DI only.

**`DeepSeekProvider` requirements:**
- `httpx.AsyncClient` OpenAI-compatible (`/chat/completions` against `Settings.llm_base_url`).
- Auth: `Authorization: Bearer <api_key>` from `SecretStr.get_secret_value()` at I/O boundary only.
- `generate` → content string from assistant message.
- `generate_structured` → request JSON mode / schema instruction; parse JSON into Pydantic `schema`; store raw if needed by callers.
- Fail loud if API key empty when constructing real provider (or on first call — pick one, document, test).
- Unit tests use `httpx.MockTransport` (or respx if already a dep — **prefer MockTransport** to avoid new deps).
- **Never** call live network in tests.

**Do NOT:**
- Import `diana.llm` from any file under `cognitive/`.
- Add SQL repositories in this task.
- Touch foundation models fields beyond optional `TurnContext = IncomingTurn` alias in `models.py` (additive only).

**Verification:**
```bash
pytest tests/unit/llm -q
pytest tests/unit/cognitive/test_import_purity.py -q
pytest tests/unit -q   # foundation suite still green
```

---

### Task 2: Deterministic pieces — Planner, Decider, Registry, Retrievers, ContextBuilder
**type:** auto  
**Objective:** All non-LLM cognitive logic: capability planning, knowledge fetch map, prompt assembly, F1 decision matrix.

**TDD order:** `test_planner` → `test_decider` → `test_registry` / `test_retrievers` → `test_context_builder` → implement each until green.

**Files (create):**
- `src/diana/cognitive/planner.py`
- `src/diana/cognitive/decider.py`
- `src/diana/cognitive/registry.py`
- `src/diana/cognitive/context_builder.py`
- `src/diana/cognitive/retrievers/__init__.py`
- `src/diana/cognitive/retrievers/base.py` (optional thin re-export of Retriever protocol)
- `src/diana/cognitive/retrievers/history.py`
- `src/diana/cognitive/retrievers/context.py`
- `src/diana/cognitive/retrievers/memory.py`   # STUB
- `src/diana/cognitive/retrievers/profile.py`  # STUB
- `src/diana/cognitive/retrievers/policy.py`   # STUB
- `src/diana/cognitive/retrievers/examples.py` # STUB
- `src/diana/cognitive/retrievers/schedule.py` # STUB
- `tests/unit/cognitive/test_planner.py`
- `tests/unit/cognitive/test_decider.py`
- `tests/unit/cognitive/test_registry.py`
- `tests/unit/cognitive/test_retrievers.py`
- `tests/unit/cognitive/test_context_builder.py`

**Planner (MVP §5.6 — lock algorithm):**
```python
# Map needs_* → capabilities in this order:
# history, context, memory, policy, examples, schedule
# If knowledge.history missing → insert(0, "knowledge.history")
# No LLM. Pure function / class method.
```

**Decider (L15 matrix):**
| Condition | action | reason |
|-----------|--------|--------|
| `evaluation.safety < safety_threshold` | `escalate` | `safety_below_threshold` |
| else if `comprehension.risk == "alto"` | `escalate` | `risk_high` |
| else | `approve` | `ok_for_human_review` |

- Inject `thresholds: dict | None = None`; default safety `0.3`.
- `mode` parameter accepts `"supervised"` only for F1; never returns `send`.
- **Forbidden:** `mean()`, overall confidence, LLM calls, non-F1 actions.
- `draft_text` may be filled by Director after decide; Decider may leave it `None`.

**Registry:**
- Register all **7** capabilities at construction (factory helper OK).
- `resolve(name) -> Retriever`; unknown name → clear `KeyError` / custom error.
- Director only passes capability **strings**.

**Retrievers:**
| Capability | Class | Behavior |
|------------|-------|----------|
| `knowledge.history` | `HistoryRetriever(history_port, limit=20)` | `await port.get_recent(turn.chat_id, limit=N)` |
| `knowledge.context` | `ContextRetriever(history_port, limit=20)` | Derive simple dict e.g. `{message_count, last_role, last_text_preview}` from history — **no F2 tables** |
| others | `StubRetriever` or dedicated stubs | always `None` |

Rules:
- History **must** filter by `chat_id` only (anti-contamination for this layer).
- STUB modules must not import each other (R19).
- `knowledge.examples` STUB must not touch any memory concept (BR-15).

**ContextBuilder:**
```python
def build(turn, comprehension, knowledge: dict[str, Any | None], persona: str) -> str
```
- Always include: persona/voice block + current VIP message (`turn.text`).
- Include knowledge sections **only** when value is not `None`.
- Unit test: all stubs null → prompt has persona + current message, **no** empty stub headings for null caps.
- F1 persona: constructor constant or injected `persona: str` (default short English/Spanish-neutral system voice string is fine; no Settings change required).

**Verification:**
```bash
pytest tests/unit/cognitive/test_planner.py tests/unit/cognitive/test_decider.py \
       tests/unit/cognitive/test_registry.py tests/unit/cognitive/test_retrievers.py \
       tests/unit/cognitive/test_context_builder.py -q
pytest tests/unit/cognitive/test_import_purity.py \
       tests/unit/cognitive/test_evaluation_profile_invariants.py -q
```

---

### Task 3: LLM-backed Analyst, Generator, Evaluator
**type:** auto  
**Objective:** Components that call `LLMProvider` only for their single question; validate structured outputs into frozen English Pydantic models.

**TDD order:** tests with FakeLLM first → implement.

**Files (create):**
- `src/diana/cognitive/analyst.py`
- `src/diana/cognitive/generator.py`
- `src/diana/cognitive/evaluator.py`
- `tests/unit/cognitive/test_analyst.py`
- `tests/unit/cognitive/test_generator.py`
- `tests/unit/cognitive/test_evaluator.py`

**Contracts:**

```python
class Analyst:
    def __init__(self, llm: LLMProvider): ...
    async def analyze(self, turn: IncomingTurn) -> Comprehension: ...
    # generate_structured(..., Comprehension); attach raw_llm_output when available

class Generator:
    def __init__(self, llm: LLMProvider): ...
    async def generate(self, prompt: str) -> str: ...
    # llm.generate only — draft text, no classification

class Evaluator:
    def __init__(self, llm: LLMProvider): ...
    async def evaluate(self, draft: str, comprehension: Comprehension, turn: IncomingTurn) -> EvaluationProfile: ...
    # generate_structured(..., EvaluationProfile); 7 English field names only
```

**Rules:**
- Constructor DI of `LLMProvider` protocol — type hint as `Protocol` / ports type, **not** `DeepSeekProvider` concrete class.
- Prompts are English-oriented instruction strings inside these modules (or small private helpers); no business action choice.
- Invalid structured payload → raise clear validation error (Pydantic `ValidationError`); tests cover incomplete EvaluationProfile dims.
- Spanish SPEC dim names (`seguridad`, etc.) must **not** appear as model fields; if prompt mentions semantics, mapping stays English fields (R10).
- No Retriever / Registry / Decider imports inside these three.

**Verification:**
```bash
pytest tests/unit/cognitive/test_analyst.py \
       tests/unit/cognitive/test_generator.py \
       tests/unit/cognitive/test_evaluator.py -q
pytest tests/unit/cognitive/test_import_purity.py -q
```

---

### Task 4: CognitiveDirector + pipeline integration tests
**type:** auto  
**Objective:** Deterministic sequencer that wires Task 2–3 components, records full trace, returns F1 `Decision` with `draft_text` set. Prove TAC-01 (no LLM for control flow / Decider path).

**TDD order:** write `test_director.py` failing scenarios first → implement `director.py`.

**Files (create):**
- `src/diana/cognitive/director.py`
- `tests/unit/cognitive/test_director.py`

**Files (edit, minimal):**
- `src/diana/cognitive/__init__.py` — re-export public API: `CognitiveDirector`, models already exported as needed
- `README.md` — one short section: cognitive unit tests / FakeLLM (English)

**Director algorithm (lock to MVP §5.4 + L10):**

```text
handle_turn(turn_context: IncomingTurn) -> Decision
  1. status → analyzing;  analyst.analyze → trace comprehension
  2. status → planning;   planner.plan     → trace plan
  3. status → retrieving; for each cap: registry.resolve + fetch → trace retrieved
  4. status → building_context; context_builder.build → trace prompt
  5. status → generating; generator.generate → trace generated
  6. status → evaluating; evaluator.evaluate → trace evaluation
  7. status → deciding;   decider.decide(mode="supervised")
     Decision with draft_text=draft → trace decision
  8. return decision
```

**Constructor DI (all injected — no service locator, no global Settings inside Director):**
- `analyst`, `planner`, `registry`, `context_builder`, `generator`, `evaluator`, `decider`
- `trace: TraceStore`
- `persona: str` (passed into ContextBuilder.build)
- `status_sink: TurnStatusSink | None = None` (default no-op)

**Prohibited in Director:**
- Import/use of LLM provider for branching or action selection
- `aiogram`, BehaviorEngine, Learning, delays, mean score
- Writing `turns` / SQL directly
- Returning non-F1 actions
- Calling Learning / deliver

**`test_director.py` must cover:**
1. **Happy path approve:** FakeLLM scripted Comprehension (risk not alto) + EvaluationProfile with `safety >= 0.3` → `action=="approve"`, `draft_text` non-empty, reason `ok_for_human_review`.
2. **Escalate safety:** `safety < 0.3` → `escalate`, reason `safety_below_threshold`.
3. **Escalate risk:** `risk=="alto"` with safe eval → `escalate`, reason `risk_high`.
4. **TAC-01 / control flow:** after full run, FakeLLM call log shows **only** Analyst + Generator + Evaluator invocations (counts: structured, generate, structured). **Zero** LLM calls attributable to Planner/Decider/Director branching.
5. **TAC-04 trace keys:** InMemoryTraceStore contains `comprehension`, `plan`, `retrieved`, `prompt`, `generated`, `evaluation`, `decision` for `turn_id`.
6. **Registry isolation:** Director only uses capability names from Plan; history port receives correct `chat_id`.
7. **Import purity still green** after all new files (run existing test).

**Optional factory for tests only** (in test file or `tests/fakes/cognitive_factory.py`):
```python
def make_director(fake_llm, history_port=..., **overrides) -> CognitiveDirector
```
Not required in production `main.py`.

**Do NOT create in this item:**
- `telegram/`, `behavior/`, `learning/`, `application/`
- SQL repos under `infrastructure/db/repositories/`
- Alembic changes, F2 tables
- Live DeepSeek smoke as CI DoD

**Verification:**
```bash
pytest tests/unit/cognitive/test_director.py -q
pytest tests/unit/cognitive tests/unit/llm -q
pytest tests/unit -q
# architecture golds
pytest tests/unit/cognitive/test_import_purity.py \
       tests/unit/cognitive/test_evaluation_profile_invariants.py \
       tests/unit/cognitive/test_decider.py \
       tests/unit/cognitive/test_director.py -q
```

## Instrucciones para gsd-executor

### Patterns to copy
- Domain models: reuse `src/diana/cognitive/models.py` as-is (additive alias only).
- Ports: `typing.Protocol` + `runtime_checkable` optional; structural typing is enough.
- FakeLLM: queue/script pattern; expose `.calls` list of `(method, kwargs)` for assertions.
- DeepSeek: thin httpx client; OpenAI chat completions JSON shape.
- Planner/Decider: pure Python, unit-testable without asyncio if sync (Planner/Decider/ContextBuilder may be sync; Director awaits async neighbors).
- Retrievers: one module per capability; constructor injects ports.
- Director: ordered awaits only — no `if llm says X` branches.

### Anti-patterns (reject if introduced)
- `from diana.llm import ...` inside `cognitive/`
- `from diana.infrastructure...` or `sqlalchemy` inside `cognitive/`
- `score = mean(...)` / `confidence` / `overall_score` on EvaluationProfile or Decider
- `Decision(action="send"|"regenerate"|"consult_doctrine")` paths
- Learning or Behavior calls from Director
- Registry resolving by importing concrete classes inside Director body
- Live HTTP in unit tests
- Hardcoded production API keys
- Cross-imports between Retriever modules
- Rewriting foundation models L1/L2 contracts
- Empty stub packages for telegram/behavior/application

### Strict TDD
1. Task 1: FakeLLM + DeepSeek mock tests → implement.
2. Task 2: planner/decider/registry/retrievers/context_builder tests → implement.
3. Task 3: analyst/generator/evaluator tests → implement.
4. Task 4: director integration tests → implement Director.
5. After each task: `pytest tests/unit/cognitive/test_import_purity.py -q` green.

### Logging
- No new logging framework required. Prefer no noisy prints. Optional `logging.getLogger(__name__)` debug only if useful; default silence.

### Language / artifacts
- All code identifiers, comments, README, commit messages: **English**.
- Do not inject persona slang into artifacts.

### Commits (if committing)
- Conventional commits, no AI co-author trailer.
- Suggested split:
  1. `feat(llm): add LLMProvider ports FakeLLM and DeepSeek client`
  2. `feat(cognitive): add planner decider registry retrievers context builder`
  3. `feat(cognitive): add analyst generator evaluator`
  4. `feat(cognitive): add CognitiveDirector pipeline`
- Single PR for whole item is acceptable; flag **review workload** if diff ≫ 400 LOC (likely) — delivery may use chained PRs by task split above.

### Scope fence for items 3–4
**No-touch implementation:**
- TurnCoordinator / TurnOrchestrator / AdminService
- BehaviorEngine.deliver / cancel_pending
- Telegram middlewares/handlers
- Learning staging / gray zone / regenerate loop / autonomous send
- SQL TraceRepository / durable turn status writes
- F2 tables (profiles, memories, contexts, policies, examples, staging)

### Item 3 handoff expectations
- Consumes `Decision` with `draft_text` + `evaluation` + `action` in {approve, escalate}
- Owns durable `turns.status` and Admin/Behavior side effects
- May replace InMemoryTraceStore with SQL TraceRepository
- Learning only **after** orchestrator finishes decision path

## Test commands

```bash
# From repo root, venv active
pip install -e ".[dev]"

# Primary gate (must pass without Postgres / without network)
pytest tests/unit -q

# Cognitive + LLM only
pytest tests/unit/cognitive tests/unit/llm -q

# Per-task narrow
pytest tests/unit/llm -q
pytest tests/unit/cognitive/test_planner.py tests/unit/cognitive/test_decider.py -q
pytest tests/unit/cognitive/test_registry.py tests/unit/cognitive/test_retrievers.py \
       tests/unit/cognitive/test_context_builder.py -q
pytest tests/unit/cognitive/test_analyst.py tests/unit/cognitive/test_generator.py \
       tests/unit/cognitive/test_evaluator.py -q
pytest tests/unit/cognitive/test_director.py -q

# Architecture golds (always re-run before handoff)
pytest tests/unit/cognitive/test_import_purity.py \
       tests/unit/cognitive/test_evaluation_profile_invariants.py \
       tests/unit/cognitive/test_models.py \
       tests/unit/cognitive/test_decider.py \
       tests/unit/cognitive/test_director.py -q
```

**Baseline regression:** foundation suite (~58 tests) must remain green.

**Out of default CI DoD:** live DeepSeek smoke; Postgres history/trace integration.

## Risks + Mitigation

| ID | Risk | Mitigation in this plan |
|----|------|-------------------------|
| R1 | Director uses LLM to choose action | L11 + Director only sequences; test_director TAC-01 call log; Decider pure |
| R2 | Score collapse | Keep invariant tests; Decider uses named `safety` dim only |
| R3 | Import purity break | L9 ports; purity test after every task; DeepSeek outside cognitive |
| R4 | Scope creep item 3/4 | Explicit no-touch list; Director returns Decision only |
| R5 | draft_text missing | Director constructs Decision with draft; tests assert both paths |
| R6 | Trace incomplete | L13 InMemoryTraceStore + TAC-04 key assertions |
| R7 | History pulls SQL into cognitive | MessageHistoryPort only; no SQL in cognitive |
| R8 | Context needs F2 table | Partial derive from history port only |
| R9 | Missing registry caps | Register all 7; resolve unknown fails loudly |
| R10 | Spanish schema keys | English Pydantic models; FakeLLM returns English fields |
| R11 | Live network / secrets | MockTransport; empty key fail-loud; SecretStr at boundary |
| R12 | Hardcoded thresholds forever | Injected thresholds dict default 0.3 |
| R14 | examples STUB reads memories | STUB returns None; no table access |
| R16 | Null knowledge pollutes prompt | ContextBuilder omits None blocks; unit test |
| R19 | Cross-retriever imports | One module per stub; independent |

## Success Criteria

- [ ] `pytest tests/unit -q` green (foundation + new cognitive/llm); **no network**, no Postgres required
- [ ] `CognitiveDirector.handle_turn(IncomingTurn) -> Decision` implemented and covered
- [ ] Director control flow deterministic; FakeLLM shows **no** LLM calls for Planner/Decider/action choice (TAC-01 / MVP-08)
- [ ] Registry resolves all **7** capabilities by name (TAC-02 / MVP-10)
- [ ] `EvaluationProfile` still exactly 7D; invariant tests green (TAC-03 / MVP-09)
- [ ] TraceStore receives: comprehension, plan, retrieved, prompt, generated, evaluation, decision (TAC-04 / MVP-07)
- [ ] Import purity AST green for all new `cognitive/**/*.py` (TAC-05 / MVP-11)
- [ ] Decider returns only `approve` | `escalate` (MVP-12 / L15 matrix)
- [ ] `draft_text` set on returned Decision for approve and escalate paths
- [ ] History REAL via port (chat_id scoped); context partial REAL; other caps STUB → None
- [ ] DeepSeek unit tests use MockTransport only; FakeLLM used for cognitive suite
- [ ] No telegram/behavior/learning/application packages introduced
- [ ] No Alembic / F1 schema changes
- [ ] README notes how to run cognitive/llm unit tests

## Executor handoff checklist

1. Read this PLAN fully + impact report if unsure.
2. Task 1 ports/FakeLLM/DeepSeek → Task 2 deterministic → Task 3 LLM components → Task 4 Director.
3. Keep `test_import_purity` + evaluation invariants green throughout.
4. Stop at cognitive boundary; do not start item 3 orchestrator/telegram/behavior.
5. Report: files created, test counts, any deviation from L9–L17.
