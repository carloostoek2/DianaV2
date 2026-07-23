---
phase: 01
plan: foundation
type: auto
item: 1/4
effort: 5
stack: python>=3.12, sqlalchemy2-async, asyncpg, alembic, pydantic-settings, pytest-asyncio
---

## Objective

Create the **physical foundation** of DianaV2 Fase 1 (supervised MVP): installable `src/diana` package, env-driven Settings, F1-only PostgreSQL schema (8 tables + non-secret seed), pure Pydantic cognitive domain models, and unit tests that freeze contracts for items 2–4. No cognitive pipeline logic, no Telegram handlers, no Behavior Engine.

## Context

@`.grok/agent-memory/impact-analyzer/01-foundation.md`
@`docs/MVP_COMPONENT_DESIGN.md` (§5.5–5.11 models, §6 DDL F1, §9 layout, §10 step 1)
@`docs/SPEC-1.1.md` (§1 stack, §5 FASE 1 tables, §11 folder tree)
@`AGENTS.md` (§3 module limits, §5.2 EvaluationProfile 7D, §5.3 Decision full-set vs F1 runtime)

**Repo state:** greenfield — only docs + stub README. All files below are create-only.

**Locked decisions (NON-NEGOTIABLE):**

| ID | Decision |
|----|----------|
| L1 | `EvaluationProfile` = exactly 7 floats: `naturalness`, `precision`, `doctrine`, `consistency`, `safety`, `coverage`, `empathy` (+ optional `raw_llm_output`). **Forbidden:** `confidence`, `overall_score`, any `mean()` helper. |
| L2 | F1 runtime `Decision.action: Literal["approve", "escalate"]` only. Full AGENTS set (`send`, `consult_doctrine`, `regenerate`) is F2+ — document in module docstring; do **not** expose in F1 model. |
| L3 | Secrets only via env. `.env.example` has empty placeholders. Migration seed must **not** contain real tokens/IDs. |
| L4 | Exactly **8 tables**: `vips`, `message_history`, `pipeline_traces`, `pending_deliveries`, `turns`, `escalation_events`, `system_config`, `pending_approvals`. No F2/F3 tables. |
| L5 | Package depth: implement only `config`, `infrastructure/db`, `cognitive/models` (+ package `__init__.py` for those). **Do not** create empty `director.py` / handlers / engine stubs. |
| L6 | Domain models = pure Pydantic in `cognitive/models.py`. ORM only under `infrastructure/db`. No `cognitive` → `telegram`/`behavior` imports. |
| L7 | Python `>=3.12` (SPEC §1 locked). User intake said 3.11+; prefer SPEC. |
| L8 | Seed `system_config`: `global_mode`, `forbidden_keywords` (example list), `eval_thresholds` with `safety: 0.3`, `trace_ttl_days: 30`. **Omit** `owner_telegram_id` from DB seed — owner lives in `Settings` from env only (R6). |

## Constraints

- **0 behavior** of pipeline, Telegram, Behavior, Learning, Admin.
- **New feature = scaffold only** (create-only files).
- **Strict TDD active:** for domain models and Settings, write failing unit tests **first**, then implement until green.
- Code/comments/identifiers in **English**.
- No Redis, LangChain, Celery, Kafka.
- No commits of real secrets.
- `main.py` may be absent or a one-line placeholder — not required for this item DoD.

## Tasks

### Task 1: Project scaffold + tooling
**type:** auto
**Objective:** Make the repo an installable Python package with pytest ready and F1 source roots present.

**Files (create):**
- `pyproject.toml`
- `src/diana/__init__.py`
- `src/diana/cognitive/__init__.py`
- `src/diana/infrastructure/__init__.py`
- `src/diana/infrastructure/db/__init__.py`
- `tests/conftest.py`
- `README.md` (overwrite stub — operational minimal)

**`pyproject.toml` requirements (exact intent):**
```toml
[project]
name = "diana"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "aiogram>=3.0,<4",
  "sqlalchemy[asyncio]>=2.0,<3",
  "asyncpg>=0.29",
  "pydantic-settings>=2.0",
  "alembic>=1.13",
  "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/diana"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]
```
(If hatchling package discovery needs `[tool.hatch.build.targets.wheel.packages]` alternative, use hatch `src` layout standard: set `packages = ["src/diana"]` or equivalent so `import diana` works after `pip install -e ".[dev]"`.)

**`tests/conftest.py`:** set `asyncio_mode` already in pyproject; optional empty fixtures only (e.g. env cleanup helper). No DB fixtures required for unit suite.

**`README.md` minimum sections (English):**
- What this is (DianaV2 Fase 1 foundation)
- Setup: Python 3.12+, `python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
- Copy `.env.example` → `.env`
- Tests: `pytest tests/unit -q`
- Migrations: `alembic upgrade head` (requires `DATABASE_URL`)
- Point to `docs/MVP_COMPONENT_DESIGN.md` and `AGENTS.md`
- Explicit: secrets never committed

**Do NOT create in this task:**
- `telegram/`, `application/`, `behavior/`, `learning/`, `llm/` package trees
- Any `director.py`, handler, or engine file

**Verification:**
```bash
pip install -e ".[dev]"
python -c "import diana; print(diana.__file__)"
pytest tests/unit -q --collect-only   # may collect 0 until later tasks; must not error on import path
```

---

### Task 2: Settings + `.env.example` + config unit tests (TDD)
**type:** auto
**Objective:** Env-driven configuration with no secrets in repo (AC-07).

**Files (create):**
- `src/diana/config.py`
- `.env.example`
- `tests/unit/test_config.py`

**TDD order:** write `tests/unit/test_config.py` first → implement `Settings`.

**`Settings` surface (pydantic-settings v2):**
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str
    owner_telegram_id: int
    database_url: str  # asyncpg form: postgresql+asyncpg://...
    deepseek_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    global_mode: Literal["supervised"] = "supervised"
    trace_ttl_days: int = 30
    log_level: str = "INFO"
```

**Rules:**
- Required secrets (`telegram_bot_token`, `owner_telegram_id`, `database_url`) have **no unsafe production defaults**.
- Tests may set env via `monkeypatch` / `os.environ` only inside fixtures.
- `.env.example` keys with empty values, e.g. `TELEGRAM_BOT_TOKEN=`, `OWNER_TELEGRAM_ID=`, `DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/diana`.
- Env names: uppercase; pydantic-settings maps automatically.

**Tests must cover:**
1. Valid env → `Settings()` constructs successfully.
2. Missing required field → ValidationError (or clear failure).
3. Defaults: `global_mode=="supervised"`, `trace_ttl_days==30`.
4. No default that hardcodes a real bot token.

**Verification:**
```bash
pytest tests/unit/test_config.py -q
```

---

### Task 3: Cognitive domain models + invariant unit tests (TDD)
**type:** auto
**Objective:** Freeze F1 cognitive contracts for items 2–4.

**Files (create):**
- `src/diana/cognitive/models.py`
- `tests/unit/cognitive/test_models.py`
- `tests/unit/cognitive/test_evaluation_profile_invariants.py`

**TDD order:** tests first → models.

**Models to implement (exact fields):**

```python
# Comprehension
intent: str
topics: list[str]
emotion: str
urgency: Literal["baja", "media", "alta"]
risk: Literal["bajo", "medio", "alto"]
needs_memory: bool = False
needs_policy: bool = False
needs_schedule: bool = False
needs_examples: bool = False
needs_history: bool = True
needs_context: bool = True
raw_llm_output: dict | None = None

# Plan
capabilities: list[str]

# EvaluationProfile — 7 dimensions only
naturalness: float
precision: float
doctrine: float
consistency: float
safety: float
coverage: float
empathy: float
raw_llm_output: dict | None = None

# Decision — F1 runtime
action: Literal["approve", "escalate"]
reason: str
evaluation: EvaluationProfile
draft_text: str | None = None

# TurnStatus (str Enum or Literal alias)
received | analyzing | planning | retrieving | building_context |
generating | evaluating | deciding | pending_approval |
escalated | superseded | delivered | failed
```

Optional (include if cheap, used by later Analyst protocol):
```python
class IncomingTurn(BaseModel):
    turn_id: UUID
    chat_id: int
    vip_id: UUID | None = None
    text: str
    telegram_message_id: int | None = None
    business_connection_id: str | None = None
```

**Module docstring (required on `models.py`):**
- State that full Decision actions in product vision include `send|approve|escalate|consult_doctrine|regenerate` (AGENTS).
- F1 runtime model **restricts** to `approve|escalate`.
- EvaluationProfile is a 7D vector; never collapse to a single score.

**Tests must cover:**
1. `EvaluationProfile` constructs with all 7 dims; missing any dim fails.
2. Model field names set equals the 7 canonical names (inspect `model_fields`).
3. No field named `confidence` / `overall_score` / `score`.
4. `Decision(action="approve", ...)` and `action="escalate"` OK.
5. `Decision(action="send")` / `"regenerate"` / `"consult_doctrine"` → ValidationError.
6. `Comprehension` urgency/risk Literals reject invalid values.
7. `Plan(capabilities=["knowledge.history"])` OK.
8. `TurnStatus` includes terminal set `{superseded, delivered, failed, escalated}` and non-terminal `pending_approval`.

**Verification:**
```bash
pytest tests/unit/cognitive -q
```

---

### Task 4: SQLAlchemy F1 models + async session + Alembic migration + seed
**type:** auto
**Objective:** Materialize the 8 F1 tables and prove migration upgrades on Postgres.

**Files (create):**
- `src/diana/infrastructure/db/models.py`
- `src/diana/infrastructure/db/session.py`
- `alembic.ini`
- `alembic/env.py`
- `alembic/script.py.mako` (if not generated by `alembic init`)
- `alembic/versions/<rev>_f1_foundation.py`

**ORM tables (SQLAlchemy 2.0 `DeclarativeBase`, map to MVP §6 DDL):**

| Table | Key columns / notes |
|-------|---------------------|
| `vips` | `id` UUID PK default `gen_random_uuid()`, `telegram_user_id` BIGINT UNIQUE NOT NULL, `display_name`, `is_active` default true, `paused_until`, `created_at` |
| `message_history` | BIGSERIAL PK, `chat_id`, `telegram_message_id`, `role` TEXT, `text`, `timestamp`; index `(chat_id, timestamp DESC)` |
| `turns` | UUID PK, `chat_id`, `vip_id` FK→vips, `status` TEXT, `trigger_message_id`, `superseded_by`, timestamps; indexes `(chat_id, status)`, `(chat_id, created_at DESC)` |
| `pipeline_traces` | UUID PK, `turn_id` UUID NOT NULL (**FK → turns.id** preferred), `vip_id` FK, `chat_id`, JSONB: comprehension/plan/retrieved/evaluation/decision/delivery_result, `prompt_text`, `generated_text`, `created_at`; indexes turn_id + (vip_id, created_at DESC) |
| `pending_deliveries` | UUID PK, chat/vip/biz_conn, `texts` JSONB, `decision` JSONB, `scheduled_at`, `status` default `pending`, `turn_id`, `created_at`; index `(status, scheduled_at)` |
| `pending_approvals` | UUID PK, `turn_id` UNIQUE, vip/chat/biz_conn, `draft_text`, `cognitive_summary`, `evaluation` JSONB, `status` default `waiting`, `owner_message_id`, timestamps; index `(status, created_at)` |
| `escalation_events` | UUID PK, `turn_id`, `tipo`, `motivo`, `notificado` default false, `created_at` |
| `system_config` | `key` TEXT PK, `value` JSONB NOT NULL, `updated_at` |

**Migration must:**
1. `CREATE EXTENSION IF NOT EXISTS pgcrypto;` (or use PG16 built-in `gen_random_uuid()` — still enable extension if needed for portability).
2. Create **only** the 8 F1 tables + indexes above.
3. Seed `system_config` rows:
   - `global_mode` → `"supervised"`
   - `forbidden_keywords` → example list `["pago", "transferencia", "eres un bot", "reclamación"]` (docs example; not a secret)
   - `eval_thresholds` → `{"safety": 0.3}`
   - `trace_ttl_days` → `30`
   - **Do not seed** real `owner_telegram_id` (comes from Settings).
4. Include `downgrade()` that drops the 8 tables (order respects FKs).

**`session.py`:**
```python
# async_engine from Settings.database_url
# async_sessionmaker(expire_on_commit=False)
# async def get_session() -> AsyncGenerator[AsyncSession, None]
```

**Alembic async `env.py` pattern:**
- Import `Base.metadata` from `diana.infrastructure.db.models`.
- `sqlalchemy.url` from env `DATABASE_URL` (override `alembic.ini` placeholder).
- Use async engine + `run_sync(do_run_migrations)` (standard SA2 async alembic template).

**Do NOT:**
- Create F2/F3 tables.
- Put business rules in ORM beyond columns/defaults.
- Commit a filled `.env`.

**Optional (nice-to-have, not blocking unit DoD):**
- `tests/integration/test_schema_f1.py` — skip unless `DATABASE_URL` set; asserts 8 table names + seed keys exist after upgrade.

**Verification:**
```bash
# Unit suite still green (no Postgres required)
pytest tests/unit -q

# Schema smoke (local Postgres required)
export DATABASE_URL=postgresql+asyncpg://...
alembic upgrade head
# optional: alembic downgrade base && alembic upgrade head
```

If Postgres is unavailable in the executor environment: unit tests + migration file review still required; document exact `DATABASE_URL` and `alembic upgrade head` in README as manual DoD step. Do **not** fake-pass migration against SQLite for UUID/JSONB fidelity.

## Instrucciones para gsd-executor

### Patterns to copy
- Domain models: pure Pydantic v2 `BaseModel` — mirror field names from MVP §5.5 / §5.10 / §5.11.
- ORM: SQLAlchemy 2.0 `Mapped[]` + `mapped_column` style.
- Config: `pydantic_settings.BaseSettings` + `SettingsConfigDict`.
- Alembic: single revision `f1_foundation`; revision id short hash or descriptive slug.
- Tests: plain pytest + pydantic `ValidationError` assertions; no mocks required for Task 2–3.

### Anti-patterns (reject if introduced)
- `score = mean(...)` or single confidence field on EvaluationProfile.
- `Decision.action` including `send` / `regenerate` / `consult_doctrine` in F1.
- F2 tables in migration.
- Real secrets / real owner telegram id in seed or `.env.example`.
- Empty stub files: `director.py`, handlers, `behavior/engine.py`.
- Domain models importing SQLAlchemy or aiogram.
- Redis / LangChain / Celery dependencies.
- Collapsing package into flat modules outside `src/diana`.

### Strict TDD
Project has **Strict TDD Mode enabled**.
1. Write failing tests for Task 2 and Task 3 first.
2. Implement minimal code to pass.
3. Only then Task 4 (schema can be schema-first with unit models already green).

### Logging
- No production logging framework required this item.
- Do not add `infrastructure/logging.py` unless trivial re-export; prefer defer.

### Language / artifacts
- All code identifiers, comments, README, commit messages: **English**.
- Do not inject persona slang into artifacts.

### Commits (if committing)
- Conventional commits, no AI co-author trailer.
- Suggested split: `chore: scaffold package and tooling` → `feat: add settings` → `feat: add cognitive domain models` → `feat: add f1 schema and alembic`.
- Single PR for whole foundation is acceptable.

### Scope fence for items 2–4
Leave these for later items — **no-touch implementation**:
- Cognitive pipeline components (director, analyst, planner, …)
- TurnCoordinator / AdminService / BehaviorEngine
- Telegram middlewares/handlers
- Learning staging, gray zone, sandbox, promo

## Test commands

```bash
# From repo root, venv active, deps installed
pip install -e ".[dev]"

# Primary gate (must pass without Postgres)
pytest tests/unit -q
pytest tests/unit/test_config.py tests/unit/cognitive -q --asyncio-mode=auto

# Narrow
pytest tests/unit/test_config.py -q
pytest tests/unit/cognitive/test_models.py -q
pytest tests/unit/cognitive -q -k evaluation

# Migration smoke (Postgres required)
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://diana:diana@localhost:5432/diana}"
alembic upgrade head
```

**Sensitive / contract tests to always re-run after edits:**
- `tests/unit/cognitive/test_evaluation_profile_invariants.py`
- Decision action rejection cases in `test_models.py`

## Risks + Mitigation

| ID | Risk | Mitigation in this plan |
|----|------|-------------------------|
| R1 | Decision set mismatch AGENTS vs F1 | L2 + module docstring + tests reject non-F1 actions |
| R2 | Score collapse | L1 + dedicated invariant tests |
| R3 | Scope creep items 2–4 | L5 + explicit no-touch file list |
| R4 | `pending_approvals` / `system_config` missing from SPEC F1 block | L4 includes both (MVP §6 is executable schema) |
| R5 | SQLite ≠ Postgres | Unit tests without DB; migration smoke on Postgres only |
| R6 | Secrets in seed | L8: no owner id / tokens in migration |
| R7 | Turn status free text | Domain `TurnStatus` enum; DB TEXT with documented values |
| R8 | Import path | `pythonpath = ["src"]` + editable install |
| R9 | Alembic async setup fragile | Standard async env.py; DoD includes upgrade head |
| R13 | `pipeline_traces.turn_id` FK | Prefer FK to `turns(id)` in migration |
| R14 | `gen_random_uuid` | `CREATE EXTENSION IF NOT EXISTS pgcrypto` when needed |

## Success Criteria

- [ ] `pip install -e ".[dev]"` succeeds; `import diana` works
- [ ] `pytest tests/unit -q` green with no Postgres
- [ ] `EvaluationProfile` has exactly the 7 canonical float fields; tests lock names
- [ ] `Decision.action` accepts only `approve` and `escalate`; rejects `send` / `regenerate` / `consult_doctrine`
- [ ] Alembic revision creates **exactly 8** F1 tables (no F2/F3)
- [ ] Seed has `eval_thresholds.safety == 0.3`, `global_mode`, `forbidden_keywords`, `trace_ttl_days`; no real secrets
- [ ] `.env.example` present with empty secret placeholders; no real tokens in git-tracked files
- [ ] `cognitive/models.py` has zero SQLAlchemy/aiogram imports
- [ ] No `director.py` / telegram handlers / behavior engine implementation files
- [ ] README documents install, test, and `alembic upgrade head`
- [ ] `alembic upgrade head` documented and runnable against local Postgres (executed if Postgres available)

## Executor handoff checklist

1. Read this PLAN fully + impact report if unsure.
2. Task 1 scaffold → Task 2 TDD config → Task 3 TDD models → Task 4 DB/Alembic.
3. Stop at foundation boundary; do not start item 2.
4. Report: files created, test output, migration status (ran / documented-only).
