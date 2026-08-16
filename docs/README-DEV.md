# DianaV2 — VIP chat automation (F1 core + flag-gated F2/F3)

The product README lives at the repo root: [README.md](../README.md).

Installable `src/diana` package: env-driven Settings, PostgreSQL schema via
Alembic (migrations **001–017**, F1 foundation through F3 tables/indexes), pure
cognitive decision pipeline, application shell (orchestrator + admin approval
gate), Behavior Engine, Learning post-turn, and **Telegram I/O** (aiogram 3
long-polling) with SQL repository adapters.

**Default runtime posture:** with **wired feature flags at default `false`**,
behavior is **supervised / F2-compatible** — VIP path does not auto-send;
delivery follows owner approve/correct unless autonomous mode is explicitly
unlocked. F2/F3 code surfaces exist; **wired** gates use Settings/env (see
table). Ops enable them gradually
(see [`.planning/quick/F3-PHASE-STATUS.md`](.planning/quick/F3-PHASE-STATUS.md)).

## Feature flags

All listed Settings fields default to **`false`** (ops enablement is gradual;
not always-on in production). **Runtime source of truth = process Settings/env**
(`diana.config.Settings`). `system_config` may seed `FEATURE_*` keys for future
merge; those seeds are **not** live overrides today.

| Surface | Flag (Settings field / env var) | Wired? | Notes |
|---------|----------------------------------|--------|--------|
| **F2** Memory | `feature_memory_enabled` / `FEATURE_MEMORY_ENABLED` | **yes** | Gates the VIP memory repo wiring at composition root (`memory_repo=None` when off → retrievers run without VIP memory). Flag off → pipeline behaves as Fase 1/2. |
| **F2** Gray zone | `feature_gray_zone_enabled` / `FEATURE_GRAY_ZONE_ENABLED` | **yes** | Doctrine consult (`consult_doctrine`) + VIP freeze path |
| **F2** Staging | `feature_staging_enabled` / `FEATURE_STAGING_ENABLED` | **yes** | `StagingService` wired when flag on: owner correct → staging candidates; gray-zone policy rows when gray zone on. Owner DM **`/staging`**: list pending **example** candidates + inline Promote/Discard (REQ-ADM-08). Flag off → staging deps `None`, surface unavailable. No auto-promote. |
| **F2** Sandbox | `feature_sandbox_enabled` / `FEATURE_SANDBOX_ENABLED` | **yes** | Catalog (6 fixtures) + session + owner `/sandbox` commands + turn isolation (auth bypass, fixture profile inject, learning/`should_persist` skip, recontact skip). Delivery uses configured `global_mode` / `delivery_mode` (real Telegram when supervised\|autonomous). Flag off → surface unavailable. Global `global_mode=fake_delivery` remains a separate ops mode |
| **F3** Autonomous | `feature_autonomous_mode` / `FEATURE_AUTONOMOUS_MODE` | **yes** | Decider may emit `send` when flag on and autonomous score mins met; auto-**delivery** also needs autonomous mode service L1/L2 (else demote to approve) |
| **F3** Recontact | `feature_recontact_enabled` / `FEATURE_RECONTACT_ENABLED` | **yes** | Silence recontact job + cancel-on-VIP-message path |
| **F3** Promo | `feature_promo_enabled` / `FEATURE_PROMO_ENABLED` | **yes** | Non-VIP exact-match promo |
| **F3** Calibration | `feature_calibration_enabled` / `FEATURE_CALIBRATION_ENABLED` | **yes** | Threshold calibration job + threshold writes / drift alerts |
| **F3** Advanced behavior | `feature_advanced_behavior` / `FEATURE_ADVANCED_BEHAVIOR` | **yes** | Message split + human quirks when delivery context enables them |
| **Persona admin** | `feature_persona_admin_enabled` / `FEATURE_PERSONA_ADMIN_ENABLED` | **yes** | Owner `/persona` menu + "Personalidad y reglas" panel with versioned catalog (migration **017**). Flag off → panel hidden, static `persona_diana.json` remains the source. |

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

Schema evolves through migrations **001–017** (F1 foundation, F2 knowledge /
freeze / trace timings, F3 flags·thresholds·auto_send·recontact/promo·calibration·
owner marks, runtime timers, business connections, and persona versions — pipeline_traces
indexes). See `alembic/versions/` and ORM models
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
- [`docs/PRODUCT_OWNER_ADMIN_SANDBOX.md`](docs/PRODUCT_OWNER_ADMIN_SANDBOX.md) — owner admin, real VIP facts/notes, sandbox fixtures (**implemented**; product source of truth)
- [`AGENTS.md`](AGENTS.md) — hard module limits for agents

## Locked contracts

| Contract | Rule |
|----------|------|
| `EvaluationProfile` | Exactly 7 floats; no single score / confidence |
| `Decision.action` | `approve` \| `escalate` \| `consult_doctrine` \| `send` — Decider emits `send` when autonomous **flag + mins** met; auto-**delivery** only if autonomous mode service L1/L2 enable (else demote to approve) |
| Schema | F1 foundation + F2 knowledge + F3 tables via migrations **001–017** (see `alembic/versions`) |
| Secrets | Env only; not in seed or repo |
| Feature flags | Default **`false`** in Settings/env (runtime SoT). Every Settings flag is a live gate — surfaces appear only when their flag is on |
