# DianaV2 — Fase 1 (supervised VIP chat automation)

Installable `src/diana` package: env-driven Settings, F1 PostgreSQL schema
(8 tables), pure cognitive decision pipeline, application shell (orchestrator +
admin approval gate), Behavior Engine, Learning post-turn check, and **Telegram
I/O** (aiogram 3 long-polling) with SQL repository adapters.

F1 is **supervised only**: VIP path never auto-sends; deliver only after owner
approve/correct. No Freeze / Staging / gray zone / autonomous `send`.

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

## Run (long-polling)

```bash
export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/diana
alembic upgrade head
python -m diana.main
# or: python -c "from diana.main import main; main()"
```

On startup the process:
1. Loads `forbidden_keywords` from `system_config`
2. Runs **safe recovery**: expires mid-flight `delivering` + recoverable pending
   (re-notify owner; **never** silent VIP re-send / auto-approve)
3. Starts aiogram long-polling

**Ops assumption:** single active bot process. Multi-instance polling / multi-writer
CAS for delivery rows is an F2 concern (see `.planning/phases/MVP-FASE1-SUMMARY.md`).

## Tests

```bash
# Full unit suite (no Postgres, no live Telegram)
.venv/bin/pytest tests/unit -q

# Purity gates
.venv/bin/pytest tests/unit/cognitive/test_import_purity.py \
  tests/unit/application/test_application_import_purity.py \
  tests/unit/behavior/test_behavior_import_purity.py -q
```

Unit tests freeze F1 contracts and use FakeLLM / FakeTelegramActuator / MagicMock
Bot only — never live API or Telegram. Postgres is not required for the unit suite.

Layer purity: `cognitive` / `application` / `behavior` / `learning` must not import
`aiogram`. Telegram adapters live under `diana.telegram`.

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
