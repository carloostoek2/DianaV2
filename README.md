# DianaV2 — VIP chat automation (F1 core + flag-gated F2/F3)

Installable `src/diana` package: env-driven Settings, PostgreSQL schema via
Alembic (migrations **001–011**, F1 foundation through F3 tables/indexes), pure
cognitive decision pipeline, application shell (orchestrator + admin approval
gate), Behavior Engine, Learning post-turn, and **Telegram I/O** (aiogram 3
long-polling) with SQL repository adapters.

**Default runtime posture:** with **all feature flags at default `false`**,
behavior is **supervised / F2-compatible** — VIP path does not auto-send;
delivery follows owner approve/correct unless autonomous mode is explicitly
unlocked. F2/F3 surfaces exist in code and are **flag-gated**; ops enable them
gradually (see [`.planning/quick/F3-PHASE-STATUS.md`](.planning/quick/F3-PHASE-STATUS.md)).

## Feature flags

All listed flags default to **`false`** in Settings (ops enablement is gradual;
not always-on in production).

| Surface | Flag (Settings / env-style) | Notes |
|---------|----------------------------|--------|
| **F2** Memory | `feature_memory_enabled` / `FEATURE_MEMORY_ENABLED` | VIP memory retrieval |
| **F2** Gray zone | `feature_gray_zone_enabled` / `FEATURE_GRAY_ZONE_ENABLED` | Doctrine consult + freeze path |
| **F2** Staging | `feature_staging_enabled` / `FEATURE_STAGING_ENABLED` | Correction → staging candidates |
| **F2** Sandbox | `feature_sandbox_enabled` / `FEATURE_SANDBOX_ENABLED` | Sandbox / fake delivery path |
| **F3** Autonomous | `feature_autonomous_mode` / `FEATURE_AUTONOMOUS_MODE` | Decider `send` when thresholds + AMS path unlock |
| **F3** Recontact | `feature_recontact_enabled` / `FEATURE_RECONTACT_ENABLED` | Silence recontact job |
| **F3** Promo | `feature_promo_enabled` / `FEATURE_PROMO_ENABLED` | Non-VIP exact-match promo |
| **F3** Calibration | `feature_calibration_enabled` / `FEATURE_CALIBRATION_ENABLED` | Threshold calibration job |
| **F3** Advanced behavior | `feature_advanced_behavior` / `FEATURE_ADVANCED_BEHAVIOR` | Message split + human quirks |

**Freeze** is implemented on the gray-zone / freeze path (middleware + Behavior
delivery hard-check). **Traceability (Anexo T)** is available for the owner DM:
`/turnos`, `/traza` (migration `005_trace_timings`, `AdminTraceService`).

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
2. Boot-loads calibrated evaluation thresholds into `RuntimeThresholds` (`load_runtime_thresholds`)
3. Runs **safe recovery**: expires mid-flight `delivering` + recoverable pending
   (re-notify owner; **never** silent VIP re-send / auto-approve)
4. Starts aiogram long-polling

**Ops assumption:** single active bot process. Multi-instance polling / multi-writer
CAS for delivery rows is **out of scope** for default deploy (see
[docs/OPS_SINGLE_INSTANCE.md](docs/OPS_SINGLE_INSTANCE.md)).
Process-local inventory (chat locks, CorrectSession, dedup, rate-limit):
[docs/OPS_SINGLE_INSTANCE.md](docs/OPS_SINGLE_INSTANCE.md).

## Tests

```bash
# Full unit suite (no Postgres, no live Telegram)
.venv/bin/pytest tests/unit -q

# Purity gates
.venv/bin/pytest tests/unit/cognitive/test_import_purity.py \
  tests/unit/application/test_application_import_purity.py \
  tests/unit/behavior/test_behavior_import_purity.py -q
```

Unit tests freeze contracts and use FakeLLM / FakeTelegramActuator / MagicMock
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

Schema evolves through migrations **001–011** (F1 foundation, F2 knowledge /
freeze / trace timings, F3 flags·thresholds·auto_send·recontact/promo·calibration·
owner marks, and pipeline_traces indexes). See `alembic/versions/` and ORM models
for the authoritative table set (do not hard-code a table count).
Seeds include non-secret `system_config` keys (`global_mode`, `forbidden_keywords`,
`eval_thresholds`, feature flags default false, etc.). The `pgcrypto` extension is
created on upgrade and intentionally retained on downgrade (shared DB-level resource).

## Docs

- [`docs/MVP_COMPONENT_DESIGN.md`](docs/MVP_COMPONENT_DESIGN.md) — F1 component guide
- [`docs/SPEC-1.1.md`](docs/SPEC-1.1.md) — F1 technical design
- [`docs/SPEC-FASE2.md`](docs/SPEC-FASE2.md) — Fase 2 (memory, gray zone, staging, sandbox)
- [`docs/SPEC-FASE3.md`](docs/SPEC-FASE3.md) — Fase 3 (autonomous, recontact, promo, calibration, advanced behavior)
- [`docs/ANEXO_T-TRAZABILIDAD.md`](docs/ANEXO_T-TRAZABILIDAD.md) — owner DM traceability (implemented)
- [`.planning/quick/F3-PHASE-STATUS.md`](.planning/quick/F3-PHASE-STATUS.md) — F3 implementation status + flag ops order
- [`docs/OPS_SINGLE_INSTANCE.md`](docs/OPS_SINGLE_INSTANCE.md) — single-process ops assumption
- [`AGENTS.md`](AGENTS.md) — hard module limits for agents

## Locked contracts

| Contract | Rule |
|----------|------|
| `EvaluationProfile` | Exactly 7 floats; no single score / confidence |
| `Decision.action` | `approve` \| `escalate` \| `consult_doctrine` \| `send` (`send` only when autonomous path unlocked: flag + thresholds + AMS) |
| Schema | F1 foundation + F2 knowledge + F3 tables via migrations **001–011** (see `alembic/versions`) |
| Secrets | Env only; not in seed or repo |
| Feature flags | Default **`false`**; F2/F3 surfaces are opt-in |
