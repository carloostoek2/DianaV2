# DianaV2 — Fase 1 Cognitive Core + Foundation

Installable `src/diana` package with env-driven Settings, F1 PostgreSQL schema
(8 tables), pure Pydantic cognitive domain models, and the **supervised
cognitive decision pipeline** (Director → Analyst → Planner → Registry →
ContextBuilder → Generator → Evaluator → Decider) plus abstract `LLMProvider`
(DeepSeek httpx client + `FakeLLM` for unit tests).

This slice does **not** implement Telegram handlers, Behavior Engine, Admin,
TurnOrchestrator, or Learning (items 3–4).

## Requirements

- Python **3.12+**
- PostgreSQL **16+** (for migrations only; unit tests do not need a DB)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Edit .env with real secrets — never commit .env
```

## Configuration

All secrets come from environment variables (see `.env.example`).

Required:

- `TELEGRAM_BOT_TOKEN`
- `OWNER_TELEGRAM_ID`
- `DATABASE_URL` — async form, e.g. `postgresql+asyncpg://user:pass@localhost:5432/diana`

**Never commit real tokens or owner IDs.**

## Tests

```bash
# Full unit suite (no Postgres, no network)
pytest tests/unit -q

# Cognitive pipeline + LLM doubles only
pytest tests/unit/cognitive tests/unit/llm -q
```

Unit tests freeze F1 contracts (`EvaluationProfile` 7D, `Decision` approve|escalate,
Settings, import purity) and exercise the Director with **FakeLLM** (scripted
responses, call log). DeepSeek provider tests use `httpx.MockTransport` only —
never live API calls. Postgres is not required for the unit suite.

Cognitive components receive `LLMProvider` via constructor DI; they never import
`diana.llm` (architecture purity gate).

## Migrations

`DATABASE_URL` is **required**. Alembic fails loud if it is unset (no silent
fallback to placeholder credentials in `alembic.ini`).

```bash
export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/diana
alembic upgrade head
```

Creates exactly 8 F1 tables and seeds non-secret `system_config` keys
(`global_mode`, `forbidden_keywords`, `eval_thresholds`, `trace_ttl_days`).
The `pgcrypto` extension is created on upgrade and intentionally retained on
downgrade (shared DB-level resource).

## Docs

- [`docs/MVP_COMPONENT_DESIGN.md`](docs/MVP_COMPONENT_DESIGN.md) — F1 component guide
- [`docs/SPEC-1.1.md`](docs/SPEC-1.1.md) — technical design
- [`AGENTS.md`](AGENTS.md) — hard module limits for agents

## Locked F1 contracts

| Contract | Rule |
|----------|------|
| `EvaluationProfile` | Exactly 7 floats; no single score / confidence |
| `Decision.action` | `approve` \| `escalate` only (full action set is F2+) |
| Schema | 8 tables only — no F2/F3 tables |
| Secrets | Env only; not in seed or repo |
