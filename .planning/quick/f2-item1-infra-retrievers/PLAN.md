---
phase: quick
plan: f2-item1-infra-retrievers
type: auto
item: "Fase 2 — Item 1: Infraestructura y Retrievers"
source: SPEC-FASE2.md + Plan_fase2.md (milestones H0-H2)
mode: standard
---

## Objective

Replace 3 F1 stub retrievers (MemoryRetriever, PolicyRetriever, ExamplesRetriever) with real pgvector-backed implementations backed by 8 new tables, pgvector HNSW indexes, an EmbeddingService for sentence-transformers vectorization, and 3 new SQL repos. The signature of `build_default_registry()` gains optional parameters so existing tests and F1-only callers remain untouched.

## Scope

- **In:**
  - Alembic migration `003_f2_knowledge_tables.py` — 8 new tables (profiles, memories, contexts, policies, examples, staging_candidates, gray_zone_queries, learning_metrics), `CREATE EXTENSION vector`, 3 HNSW indexes + 3 B-tree indexes, seed system_config rows for feature flag defaults
  - 8 new ORM models in `src/diana/infrastructure/db/models.py` — Profile, Memory, Context, Policy, Example, StagingCandidate, GrayZoneQuery, LearningMetric (all with `pgvector.sqlalchemy.Vector` for embedding columns)
  - Dependencies `pgvector` and `sentence-transformers` in `pyproject.toml`
  - `src/diana/cognitive/embedding.py` — EmbeddingService (lazy-loaded model, 384-dim)
  - 3 new SQL repos: `src/diana/infrastructure/db/repositories/memories.py`, `policies.py`, `examples.py`
  - Real MemoryRetriever replacing stub in `src/diana/cognitive/retrievers/memory.py`
  - Real PolicyRetriever replacing stub in `src/diana/cognitive/retrievers/policy.py`
  - Real ExamplesRetriever replacing stub in `src/diana/cognitive/retrievers/examples.py`
  - `build_default_registry()` updated signature (optional `session_factory` + `embedding_service` params)
  - Wiring in `src/diana/composition.py` — instantiate EmbeddingService, pass session_factory to registry
  - Feature flag defaults in `src/diana/config.py` (`FEATURE_MEMORY_ENABLED`, `FEATURE_GRAY_ZONE_ENABLED`, `FEATURE_STAGING_ENABLED`, `FEATURE_SANDBOX_ENABLED` — all default `false`)
  - Update `test_orm_exposes_exactly_eight_f1_tables` to expect 16 tables

- **Out / Non-goals:**
  - StagingService, GrayZoneService, PolicyDistiller (Items 2-3)
  - Decider `consult_doctrine` action extension (Item 3)
  - Feature flag reading system (SqlSystemConfigStore.get_feature_flags — Item 3)
  - Sandbox, expiration job, composition wiring beyond registry signature
  - New test files (H11 is a separate later item in the full plan)
  - `src/diana/cognitive/decider.py`, `director.py`, `models.py` Decision.action — no changes

- **Constraints:**
  - All 3 retrievers implement the same `Retriever` protocol (`cognitive/ports.py`). No protocol change.
  - `build_default_registry()` signature gains ONLY optional params — existing callers in tests and F1 production pass zero new args and get stub behavior.
  - EmbeddingService MUST lazy-load model: no `sentence_transformers` import at module level or `__init__` time. First `embed()` call triggers `SentenceTransformer(model_name)`.
  - Anti-contamination (BR-15): every memory query `WHERE memories.vip_id = :vip_id`. Models table `examples` NEVER imported/read by ExamplesRetriever (AST gate).
  - Examples retriever may include a counter-example at ~10% probability.
  - MemoryRetriever returns `None` when `vip_id` is None (unidentified VIP).
  - No Cognitive Core module may import `aiogram` or `behavior` (import purity test).

## Assumptions

- A1: `pgvector.sqlalchemy.Vector` is the right type for embedding columns in SQLAlchemy 2.0 ORM. If unavailable, fall back to `ARRAY(Real)` with raw SQL casts — but the `pgvector` Python package provides the ORM type.
- A2: The sentence-transformers model `paraphrase-multilingual-MiniLM-L12-v2` produces 384-dim vectors. No alternative model or API embedding is needed for this item.
- A3: `build_default_registry` callers that only pass `history_port` (like all current tests and F1 production) must get exact same behavior as before — optional params default to None, retrievers return None.
- A4: Embedding model is loaded once per process and cached. No unload/reload needed.
- A5: LearningMetric model is created for schema completeness only. Its repo and service are F3+.

## Architecture Approach

### QUe (comportamiento / contratos)

| Comportamiento | Verdad |
|---|---|
| Migration 003 creates 8 new tables + pgvector extension | `alembic upgrade head` succeeds |
| ORM models match migration table-for-table, column-for-column | `Base.metadata.tables` count = 16 |
| EmbeddingService lazy-loads model | `sentence_transformers` import only on first `embed()` call |
| MemoryRetriever returns `None` when `session_factory` is `None` | `cls().fetch(turn, c)` returns None |
| MemoryRetriever queries `memories` with `WHERE vip_id = :vip_id` | Anti-contamination BR-15 |
| PolicyRetriever filters by `is_active = true` and scope match | Only active policies returned |
| ExamplesRetriever never imports `memory` or `memories` | AST import gate passes |
| Retrievers in registry respect stub behavior when no session factory | `build_default_registry(history_port)` produces same behavior as F1 |

### COMO (estructura / patrones)

**Capas / modulos:**

```
infrastructure/db/models.py        → 8 new ORM models
infrastructure/db/repositories/    → 3 new SQL repos (memories, policies, examples)
cognitive/embedding.py             → EmbeddingService (new module)
cognitive/retrievers/memory.py     → replace stub with real impl
cognitive/retrievers/policy.py     → replace stub with real impl
cognitive/retrievers/examples.py   → replace stub with real impl
cognitive/registry.py              → build_default_registry gains optional params
composition.py                     → wire new services
config.py                          → F2 feature flag defaults
alembic/versions/003_*.py          → migration
pyproject.toml                     → pgvector + sentence-transformers deps
```

**Pattern to copy:**

| Que copiar | Path analogo | Adaptar |
|---|---|---|
| ORM model style | `models.py::Vip` | Add `Vector(384)` for embedding columns; all 8 models follow same mapped_column pattern |
| Migration style | `alembic/versions/001_f1_foundation.py` | Add `CREATE EXTENSION vector`; 8 tables; 3 HNSW indexes via `sa.text("hnsw (...) vector_cosine_ops")`; seed with `ON CONFLICT DO NOTHING` |
| SQL repo pattern | `repositories/history.py::SqlMessageHistoryRepo` | `__init__(self, session_factory)`, `async with self._sf() as session:`, `session.execute(select(...))` |
| Retriever stub interface | `retrievers/memory.py` (current) | Keep `fetch(self, turn, comprehension) -> Any | None` signature; add optional `__init__` params |
| Retriever optional deps design | `retrievers/schedule.py` (half-registered `fuente`) | session_factory defaults to None → fetch returns None (stub compat) |

**Interfaces / tipos nuevos:**

- `EmbeddingService` — class (not protocol), no interface needed (only consumed by retrievers)
- `MemoriesRepo`, `PoliciesRepo`, `ExamplesRepo` — internal SQL repos with row-to-dict conversion helpers
- `Profile`, `Memory`, `Context`, `Policy`, `Example`, `StagingCandidate`, `GrayZoneQuery`, `LearningMetric` — ORM models in `models.py`
- `build_default_registry()` signature change: add `session_factory` and `embedding_service` optional kwargs

**Wiring (composition.py changes):**

```
build_app():
   ...
   embedding = EmbeddingService()  # lazy, no model load yet
   registry = build_default_registry(
       history,
       session_factory=sf,
       embedding_service=embedding,
   )
   ...
```

**Orden de dependencias entre tasks:**

```
Task 1 (models + migration + deps) ──┬── Task 2 (EmbeddingService)
                                      └── Task 3 (3 SQL repos)
                                               │
                                    Task 4 (retrievers + registry + composition)
                                        (needs 1, 2, 3)
```

### File Map

| Accion | Path | Notas |
|---|---|---|
| CREATE | `alembic/versions/003_f2_knowledge_tables.py` | Migration |
| CREATE | `src/diana/cognitive/embedding.py` | EmbeddingService |
| CREATE | `src/diana/infrastructure/db/repositories/memories.py` | MemoriesRepo |
| CREATE | `src/diana/infrastructure/db/repositories/policies.py` | PoliciesRepo |
| CREATE | `src/diana/infrastructure/db/repositories/examples.py` | ExamplesRepo |
| EDIT | `pyproject.toml` | Add 2 deps |
| EDIT | `src/diana/infrastructure/db/models.py` | Add 8 models + Vector import |
| EDIT | `src/diana/cognitive/retrievers/memory.py` | Replace stub |
| EDIT | `src/diana/cognitive/retrievers/policy.py` | Replace stub |
| EDIT | `src/diana/cognitive/retrievers/examples.py` | Replace stub |
| EDIT | `src/diana/cognitive/registry.py` | Optional params + inject to retrievers |
| EDIT | `src/diana/composition.py` | Wire embedding + session_factory |
| EDIT | `src/diana/config.py` | Feature flag defaults |
| EDIT | `tests/unit/infrastructure/test_f1_schema_metadata.py` | Update table count assertion |
| NO-TOUCH | `src/diana/cognitive/ports.py` | Retriever protocol unchanged |
| NO-TOUCH | `src/diana/cognitive/director.py` | No changes needed for Item 1 |
| NO-TOUCH | `src/diana/cognitive/decider.py` | F2 Items 2-3 |
| NO-TOUCH | `src/diana/cognitive/models.py` Decision.action | Stays `Literal["approve", "escalate"]` |
| NO-TOUCH | `src/diana/cognitive/retrievers/profile.py` | Stub stays |
| NO-TOUCH | `src/diana/cognitive/retrievers/schedule.py` | Stub stays |
| NO-TOUCH | `src/diana/cognitive/retrievers/context.py` | Unchanged |
| NO-TOUCH | `src/diana/cognitive/retrievers/history.py` | Unchanged |
| NO-TOUCH | Tests not in the edit list | `test_stubs_return_none` and `test_registry_isolation_history_uses_turn_chat_id` should pass unchanged |

## Context

Archivos relevantes:

- `docs/SPEC-FASE2.md` — sections 3-5 (feature flags, data model, contracts), section 7 (migration strategy)
- `docs/Plan_fase2.md` — milestones H0-H2, file list, architecture diagram
- `AGENTS.md` — anti-contamination BR-15, module boundaries, retriever rules
- `src/diana/cognitive/ports.py` — `Retriever` protocol (lines 78-102)
- `src/diana/cognitive/registry.py` — `build_default_registry()` current signature (lines 49-77)
- `src/diana/cognitive/retrievers/memory.py` — current stub (8 lines)
- `src/diana/cognitive/retrievers/policy.py` — current stub (17 lines)
- `src/diana/cognitive/retrievers/examples.py` — current stub (20 lines)
- `src/diana/infrastructure/db/models.py` — 8 F1 ORM models (pattern to follow)
- `src/diana/infrastructure/db/repositories/history.py` — SQL repo pattern
- `src/diana/composition.py` — current wiring (lines 137-265)
- `src/diana/config.py` — Settings class (feature flag defaults go here)
- `alembic/versions/001_f1_foundation.py` — migration pattern
- `tests/unit/infrastructure/test_f1_schema_metadata.py` — test that breaks (line 42-44)
- `tests/unit/cognitive/test_retrievers.py` — test_stubs_return_none (line 200-212), AST gates
- `tests/unit/cognitive/test_director.py` — test_registry_isolation_history_uses_turn_chat_id (lines 350-396)

## Tasks

### Task 1: Create migration 003, 8 ORM models, and update dependencies

**type:** auto
**Objective:** 8 new tables exist in the database schema, 8 new ORM models registered on `Base`, `pgvector` and `sentence-transformers` installable.

**Files:**
- CREATE `alembic/versions/003_f2_knowledge_tables.py`
- EDIT `src/diana/infrastructure/db/models.py`
- EDIT `pyproject.toml`

**Action:**

1. `pyproject.toml`: Add `"pgvector>=0.3"` and `"sentence-transformers>=3.0"` to `dependencies` list (alphabetical order, before `alembic`).

2. `models.py`: Add 8 new ORM models after the existing `SystemConfig` class. Each embedding column uses `Vector(384)` from `pgvector.sqlalchemy`. Follow the exact annotation style of existing models (`Mapped`, `mapped_column`, `ForeignKey`, `server_default`). The models are:

   - **Profile** (`profiles`): `vip_id` (PK/FK→vips.id), `embedding` (Vector(384)), `content` (JSONB), `tipo` (Text), `created_at`, `updated_at`
   - **Memory** (`memories`): `id` (UUID PK), `vip_id` (FK→vips.id, NOT NULL), `embedding` (Vector(384)), `content` (JSONB), `category` (Text), `confidence` (Float), `created_at`
   - **Context** (`contexts`): `id` (UUID PK), `vip_id` (FK→vips.id), `chat_id` (BigInteger), `embedding` (Vector(384)), `content` (JSONB), `expires_at` (DateTime), `created_at`
   - **Policy** (`policies`): `id` (UUID PK), `embedding` (Vector(384)), `trigger_description` (Text), `rule` (Text), `scope` (Text, default `'all'`), `is_active` (Boolean, default True), `valid_until` (DateTime nullable), `source_query_id` (UUID nullable), `created_at`
   - **Example** (`examples`): `id` (UUID PK), `embedding` (Vector(384)), `turn_text` (Text), `draft_text` (Text), `corrected_text` (Text), `context` (JSONB), `is_counter_example` (Boolean, default False), `created_at`
   - **StagingCandidate** (`staging_candidates`): `id` (UUID PK), `type` (Text, `'example'` or `'policy'`), `payload` (JSONB), `status` (Text, default `'pending'`), `turn_id` (FK→turns.id), `created_at`, `updated_at`
   - **GrayZoneQuery** (`gray_zone_queries`): `id` (UUID PK), `vip_id` (FK→vips.id), `turn_id` (FK→turns.id), `question` (Text), `draft` (Text), `status` (Text, default `'open'`), `freeze_until` (DateTime nullable), `created_at`, `resolved_at` (nullable)
   - **LearningMetric** (`learning_metrics`): `id` (UUID PK), `vip_id` (FK→vips.id), `metric_name` (Text), `value` (Float), `recorded_at` (DateTime)

   Import `Vector` from `pgvector.sqlalchemy` at the top of the file. Import `Float` from `sqlalchemy`.

3. `003_f2_knowledge_tables.py`: Follow `001_f1_foundation.py` exactly. Create the 8 tables with matching columns. Create 3 HNSW indexes using raw SQL via `op.execute()`:
   ```sql
   CREATE INDEX CONCURRENTLY IF NOT EXISTS memories_embedding_idx
     ON memories USING hnsw (embedding vector_cosine_ops);
   CREATE INDEX CONCURRENTLY IF NOT EXISTS policies_embedding_idx
     ON policies USING hnsw (embedding vector_cosine_ops);
   CREATE INDEX CONCURRENTLY IF NOT EXISTS examples_embedding_idx
     ON examples USING hnsw (embedding vector_cosine_ops);
   ```
   Create 3 B-tree indexes:
   ```sql
   CREATE INDEX IF NOT EXISTS memories_vip_id_idx ON memories (vip_id);
   CREATE INDEX IF NOT EXISTS policies_active_idx ON policies (is_active, valid_until);
   CREATE INDEX IF NOT EXISTS gray_zone_status_idx ON gray_zone_queries (status, freeze_until);
   ```
   Seed system_config with feature flag defaults (all `false`):
   ```sql
   INSERT INTO system_config (key, value) VALUES
     ('FEATURE_MEMORY_ENABLED', 'false'::jsonb),
     ('FEATURE_GRAY_ZONE_ENABLED', 'false'::jsonb),
     ('FEATURE_STAGING_ENABLED', 'false'::jsonb),
     ('FEATURE_SANDBOX_ENABLED', 'false'::jsonb)
   ON CONFLICT (key) DO NOTHING;
   ```
   NOTE: `CONCURRENTLY` cannot run inside a transaction. Wrap HNSW index creation outside the transactional `upgrade()`. Use `op.execute("SET statement_timeout = '10s'; CREATE INDEX CONCURRENTLY IF NOT EXISTS ...")` — or simpler: use non-concurrent `CREATE INDEX IF NOT EXISTS` inside the transaction (acceptable for dev/staging; production migration should be manual). For this item, use non-concurrent inside the transaction to keep migration atomic. Write a comment noting this decision.

   Set `down_revision = "002_turns_error"`.

**Verification:** `alembic upgrade head` runs without error. `pytest tests/unit/infrastructure/test_f1_schema_metadata.py::test_orm_exposes_exactly_eight_f1_tables -x` passes (after updating the test in this task).

**Done:**
- [ ] `alembic upgrade head` creates 16 tables (8 F1 + 8 F2)
- [ ] `Base.metadata.tables` keys include all 16 table names
- [ ] pgvector extension registered in the database
- [ ] 3 HNSW + 3 B-tree indexes created
- [ ] 4 feature flag rows seeded in `system_config`
- [ ] `pyproject.toml` has `pgvector` and `sentence-transformers`
- [ ] `pip install -e ".[dev]"` installs without error

---

### Task 2: Implement EmbeddingService

**type:** auto
**Objective:** Text-to-vector conversion with lazy-loaded sentence-transformers model (384 dims).

**Files:**
- CREATE `src/diana/cognitive/embedding.py`

**Action:**

Create a single class `EmbeddingService`:

```python
class EmbeddingService:
    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self._model_name = model_name
        self._model = None  # lazy

    async def embed(self, text: str) -> list[float]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        loop = asyncio.get_running_loop()
        emb = await loop.run_in_executor(None, self._model.encode, text)
        return emb.tolist()
```

Key design decisions:
- `sentence_transformers` imported ONLY inside `embed()`, not at module top level. This preserves the existing import purity of `diana.cognitive` (the embedding module lives in `cognitive/` but the import only happens on first call).
- Use `asyncio.get_running_loop().run_in_executor(None, ...)` to avoid blocking the event loop during `model.encode()`.
- Constructor takes no args beyond optional `model_name` so composition.py can instantiate it without side effects.

Export `__all__ = ["EmbeddingService"]`.

**Verification:** `python -c "from diana.cognitive.embedding import EmbeddingService; import inspect; assert 'sentence_transformers' not in inspect.getsource(EmbeddingService.embed)"` — top-level source must not contain sentence_transformers import.

**Done:**
- [ ] `EmbeddingService` can be imported without triggering sentence-transformers load
- [ ] First call to `embed("hello world")` loads model and returns list of 384 floats
- [ ] `embed()` does not block event loop (uses `run_in_executor`)
- [ ] Subsequent calls reuse the cached model

---

### Task 3: Implement 3 SQL repositories

**type:** auto
**Objective:** Data access layer for memories, policies, and examples tables.

**Files:**
- CREATE `src/diana/infrastructure/db/repositories/memories.py`
- CREATE `src/diana/infrastructure/db/repositories/policies.py`
- CREATE `src/diana/infrastructure/db/repositories/examples.py`

**Action:**

Follow the exact pattern of `SqlMessageHistoryRepo` in `repositories/history.py`:

```python
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload  # if needed

from diana.infrastructure.db.models import Memory  # or Policy, Example
```

Each repo:
1. Constructor takes `session_factory: async_sessionmaker[AsyncSession]` (required — repos are only instantiated when we have a real DB).
2. Each method uses `async with self._sf() as session:` and executes `select()` queries.
3. Row-to-dict conversion is done with a standalone function (like `rows_to_recent_messages` in `history.py`).

**MemoriesRepo** (`memories.py`):
- `find_by_vip_and_similarity(vip_id: UUID, embedding: list[float], threshold: float = 0.75, limit: int = 5) -> list[dict]`:
  ```python
  async def find_by_vip_and_similarity(self, vip_id, embedding, threshold=0.75, limit=5):
      async with self._sf() as session:
          result = await session.execute(
              select(Memory)
              .where(
                  Memory.vip_id == vip_id,
                  Memory.embedding.cosine_distance(embedding) < 1 - threshold,
              )
              .order_by(Memory.embedding.cosine_distance(embedding))
              .limit(limit)
          )
          return [memory_to_dict(row) for row in result.scalars().all()]
  ```
  Note: `cosine_distance` returns 0.0 for identical vectors, 1.0 for opposite. So `cosine_distance < 1 - threshold` means "cosine_similarity > threshold".

**PoliciesRepo** (`policies.py`):
- `find_active_by_similarity(embedding: list[float], threshold: float = 0.8, scope: str | None = None, limit: int = 5) -> list[dict]`:
  Filter `Policy.is_active == true` and `(Policy.valid_until.is_(None) | (Policy.valid_until > func.now()))`. If `scope` is not None, also filter `(Policy.scope == 'all') | (Policy.scope == scope)`.

**ExamplesRepo** (`examples.py`):
- `find_by_similarity(embedding: list[float], threshold: float, limit: int = 5, counter_example: bool = False) -> list[dict]`:
  When `counter_example=False`, filter `Example.is_counter_example == false`. When `counter_example=True`, filter `Example.is_counter_example == true`.
  MUST NOT import Memory, memories, or any other retriever type (AST gate enforcement).

**NOTE on vector operations:** The exact API depends on `pgvector.sqlalchemy`. `Vector` column type exposes `.cosine_distance()` as a method that generates the appropriate SQL. If the method signature differs, adapt accordingly. The key SQL generated should be:
```sql
SELECT * FROM memories
WHERE vip_id = :vip_id
  AND embedding <=> :embedding < 0.25  -- 1 - 0.75 = 0.25
ORDER BY embedding <=> :embedding
LIMIT 5;
```

**Verification:** `python -c "from diana.infrastructure.db.repositories.memories import MemoriesRepo; from diana.infrastructure.db.repositories.policies import PoliciesRepo; from diana.infrastructure.db.repositories.examples import ExamplesRepo; print('OK')"` — all import without error.

**Done:**
- [ ] All 3 repos import cleanly
- [ ] Each repo follows the `history.py` async session pattern
- [ ] Row-to-dict conversion functions exist
- [ ] ExamplesRepo has zero references to `memory` or `memories` in imports

---

### Task 4: Replace stub retrievers with real implementations + registry + composition wiring

**type:** auto
**Objective:** MemoryRetriever, PolicyRetriever, ExamplesRetriever return real data from pgvector when session_factory is provided; return None (stub-compatible) when it is not.

**Files:**
- EDIT `src/diana/cognitive/retrievers/memory.py`
- EDIT `src/diana/cognitive/retrievers/policy.py`
- EDIT `src/diana/cognitive/retrievers/examples.py`
- EDIT `src/diana/cognitive/registry.py`
- EDIT `src/diana/composition.py`
- EDIT `src/diana/config.py`
- EDIT `tests/unit/infrastructure/test_f1_schema_metadata.py` (table count assertion)

**Action:**

**4a. `config.py`** — Add 4 feature flag defaults to `Settings`:
```python
# F2 feature flag defaults (read from system_config at runtime by Items 3+)
feature_memory_enabled: bool = False
feature_gray_zone_enabled: bool = False
feature_staging_enabled: bool = False
feature_sandbox_enabled: bool = False
```
These are STATIC defaults only (the runtime flag reading via SqlSystemConfigStore is Item 3). They document intended defaults and could be used as fallback.

**4b. MemoryRetriever (`memory.py`)**

Constructor takes optional deps:
```python
def __init__(
    self,
    *,
    embedding_service: EmbeddingService | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    self._embed = embedding_service
    self._repo = MemoriesRepo(session_factory) if session_factory else None
```

`fetch()`:
1. If `self._repo is None` or `self._embed is None` → return None (stub compat).
2. Extract `vip_id` from `turn.vip_id`. If None → return None (unidentified VIP, BR-15).
3. Extract query text from `turn.text` (or from `comprehension` if a summary query field exists — use `turn.text` as default).
4. Call `self._embed.embed(query_text)`.
5. Call `self._repo.find_by_vip_and_similarity(vip_id, embedding, threshold=0.75)`.
6. Format result as list of strings (e.g. `f"[{row['category']}] {row['content']['fact']}"` for easy inclusion in ContextBuilder prompt). If empty → return empty list.
7. Return formatted list.

Key: `vip_id` is optional on `IncomingTurn`. When None, return None per BR-15.

**4c. PolicyRetriever (`policy.py`)**

Constructor same pattern as MemoryRetriever.

`fetch()`:
1. If no repo or embed → return None.
2. Extract query from `turn.text`.
3. Get embedding.
4. Find VIP segment/scope from `comprehension` data (use comprehension fields if available, otherwise default to `None` → matches `scope='all'`).
5. `self._repo.find_active_by_similarity(embedding, threshold=0.8, scope=vip_segment)`.
6. Format as list of strings: `f"Trigger: {row['trigger_description']} | Rule: {row['rule']}"`.
7. Return formatted list or empty list.

**4d. ExamplesRetriever (`examples.py`)**

Constructor same pattern + an extra param for counter-example probability:
```python
def __init__(
    self,
    *,
    embedding_service: EmbeddingService | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    counter_example_chance: float = 0.1,
) -> None:
```

`fetch()`:
1. If no repo or embed → return None.
2. Get embedding.
3. Decide: `include_counter = random.random() < self._counter_example_chance`.
4. Fetch examples with `find_by_similarity(embedding, threshold=0.7, limit=5, counter_example=False)`.
5. If `include_counter`, also fetch 1 counter-example and append it.
6. Format as list of strings.
7. Return formatted list or empty list.

CRITICAL: Do NOT import Memory, MemoriesRepo, or any memory-related module. AST gate in `test_retrievers.py` enforces this.

**4e. `registry.py`** — Update `build_default_registry()`:

```python
def build_default_registry(
    history_port: MessageHistoryPort,
    *,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    embedding_service: EmbeddingService | None = None,
) -> CapabilityRegistry:
```

Inside, replace the 3 stub instantiation lines with real (but conditional on optional params):
```python
registry.register(
    "knowledge.memory",
    MemoryRetriever(
        embedding_service=embedding_service,
        session_factory=session_factory,
    ),
)
# Same for policy and examples
```

Important: ProfileRetriever stays stub (its real implementation is deferred). ScheduleRetriever stays half-registered.

**4f. `composition.py`** — In `build_app()`:

After the existing repo instantiations and before the Director creation:
```python
from diana.cognitive.embedding import EmbeddingService

# F2 knowledge services (Item 1)
embedding_svc = EmbeddingService()  # lazy, no model load at boot

registry = build_default_registry(
    history,
    session_factory=sf,
    embedding_service=embedding_svc,
)
```

Replace the existing `registry = build_default_registry(history)` with the above.

**4g. `tests/unit/infrastructure/test_f1_schema_metadata.py`**:

Update `test_orm_exposes_exactly_eight_f1_tables`:
```python
def test_orm_exposes_exactly_sixteen_tables() -> None:
    assert len(Base.metadata.tables) == 16
```
Update `F1_TABLES` set if needed, or keep the test separate for F1 vs total. The cleanest approach: keep `F1_TABLES` and rename the test to `test_orm_exposes_exactly_sixteen_tables` asserting `len == 16`. Keep the old test name as a separate assertion that F1_TABLES is a subset.

**Verification:**
- `pytest tests/unit/infrastructure/test_f1_schema_metadata.py -x` — passes
- `pytest tests/unit/cognitive/test_retrievers.py -x` — passes (stub tests still work)
- `pytest tests/unit/cognitive/test_director.py -x` — passes
- `pytest tests/unit/cognitive/test_registry.py -x` — passes (if exists)

**Done:**
- [ ] All existing F1 tests pass with no modifications (except table count test which was updated)
- [ ] `cls().fetch(turn, c)` returns None for all 3 retrievers (backward compat)
- [ ] MemoryRetriever returns formatted list when vip_id is present and DB has matches
- [ ] MemoryRetriever returns None when vip_id is None (BR-15)
- [ ] ExamplesRetriever AST gate passes (no `memory` import)
- [ ] `build_default_registry(history)` works without keyword args (backward compat)
- [ ] composition.py passes session_factory and embedding_service to registry

## Instrucciones para gsd-executor

### Patrones a copiar (paths)

1. **SQL Repo pattern**: `src/diana/infrastructure/db/repositories/history.py` — `SqlMessageHistoryRepo`. Copy: `__init__` accepting `async_sessionmaker`, `async with self._sf() as session:`, standalone row-to-dict helpers.

2. **ORM model pattern**: `src/diana/infrastructure/db/models.py::Vip`. Copy: `Mapped[t] = mapped_column(...)` annotations, `server_default=text(...)` for defaults, `ForeignKey` references, `DateTime(timezone=True)`.

3. **Migration pattern**: `alembic/versions/001_f1_foundation.py`. Copy: module structure, `sa.Column()` calls, `op.create_table`, `op.create_index`, `op.execute` for seeds. Adapt: add `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`.

4. **Retriever shape**: current `src/diana/cognitive/retrievers/memory.py` (stub). Keep `async def fetch(self, turn: IncomingTurn, comprehension: Comprehension) -> Any | None:` signature. Add optional constructor params.

### Anti-patterns prohibidos

- **Do NOT** import `aiogram` or `diana.behavior` anywhere in `diana.cognitive` (import purity test).
- **Do NOT** make session_factory required in retrievers — must default to None for backward compat.
- **Do NOT** load sentence-transformers at module level or in `EmbeddingService.__init__()`.
- **Do NOT** add `consult_doctrine` to `Decision.action` — that's Item 3.
- **Do NOT** implement feature flag reading logic here (the SqlSystemConfigStore.get_feature_flags is Item 3). Just add config defaults.
- **Do NOT** import memory-related symbols in `examples.py` (AST gate enforcement).
- **Do NOT** use `session.commit()` or `session.add()` in retrievers — retrievers are read-only (tested by AST gate).

### Logging / errores / convenciones del proyecto

- Use `logger = logging.getLogger(__name__)` at module level (no root logger).
- Error handling: let exceptions propagate (Director catches and marks FAILED). Retriever errors should not be silently caught.
- No `print()` statements.
- Use `from __future__ import annotations` in every file.
- All new models use `vip_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("vips.id"), nullable=True)` pattern.

### Commits

Each task is a work unit = one behaviorally verifiable step. Commit after each task passes its verification.

### Mock policy (tests)

- Existing tests use no real DB. `session_factory=None` in retrievers = stub behavior (returns None).
- New repo tests (if added later) should use `async_sessionmaker(AsyncSession(bind=engine))` with a test DB or SQLite. Not needed for this item since no new test files are created.

### Skills del proyecto aplicables

- `telegram-bot-hardener`: Not needed here (no Telegram layer changes).
- `work-unit-commits`: Use for the commit-per-verify-cycle.

## Test commands

```bash
# Migration
alembic upgrade head

# Full existing test suite (must pass)
pytest tests/ -x

# Schema metadata (table count test updated)
pytest tests/unit/infrastructure/test_f1_schema_metadata.py -x

# Retriever tests (stub backward compat confirmed)
pytest tests/unit/cognitive/test_retrievers.py -x

# Director tests (registry isolation + full pipeline)
pytest tests/unit/cognitive/test_director.py -x

# Import checks
pytest tests/unit/cognitive/test_import_purity.py -x

# Specific embedding import gate
python -c "from diana.cognitive.embedding import EmbeddingService; import inspect; assert 'sentence_transformers' not in inspect.getsource(EmbeddingService.embed)"
```

## Riesgos + Mitigacion

| Riesgo | Impacto | Mitigacion |
|---|---|---|
| `pgvector.sqlalchemy.Vector` API differs from expected `.cosine_distance()` | Migration or queries fail | Test migration + one query with `alembic upgrade head` and `python -c` verification. If API differs, use raw `text()` for vector distance. |
| `sentence-transformers` model download on first `embed()` is slow (>10s) | First call blocks event loop | Already mitigated by `run_in_executor`. Non-blocking. Can add timeout log warning. |
| `test_orm_exposes_exactly_eight_f1_tables` breaks | CI fails | Updated assertion to 16 tables in Task 4g. |
| `test_stubs_return_none` breaks | CI fails | Mitigated by optional `session_factory` defaulting to None → `cls().fetch()` returns None. Should pass unchanged. |
| `test_registry_isolation_history_uses_turn_chat_id` breaks | CI fails | Mitigated by optional deps. The test calls `build_default_registry(history)` without `session_factory` → retrievers get None → return None. Assertions pass unchanged. |
| `test_retrievers.py` AST gates fail for examples.py | CI fails | Ensure examples.py has zero references to "memory" or "memories" string literals or imports. |
| `test_retrievers_are_read_only_ast` fails | CI fails | Do NOT import `sqlalchemy` or use `session.add`/`session.commit` in retriever modules. Leave those in repos. |
| Embedding model changes dimension (384) | Migration column type wrong | Pinned to `paraphrase-multilingual-MiniLM-L12-v2` which is 384-dim. If model changes, migration must change `vector(384)`. |

## Success Criteria

- [ ] `alembic upgrade head` succeeds and creates 16 tables with pgvector extension and 6 indexes
- [ ] `pip install -e ".[dev]"` installs pgvector and sentence-transformers without error
- [ ] `pytest tests/ -x` passes with ZERO modifications to any test except the table count assertion
- [ ] `build_default_registry(history_port)` returns a registry indistinguishable from F1 (stub behavior preserved)
- [ ] `build_default_registry(history_port, session_factory=sf, embedding_service=emb)` returns registry with real retrievers
- [ ] EmbeddingService lazy-loads model only on first `embed()` call
- [ ] MemoryRetriever returns None when `vip_id` is None (BR-15)
- [ ] ExamplesRetriever AST gate passes (no memory imports detected)
- [ ] No Cognitive Core module imports aiogram or behavior engine
