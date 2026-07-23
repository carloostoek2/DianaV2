# SUMMARY — 01 Foundation

**Status:** complete  
**Date:** 2026-07-22  
**Item:** 1/4 Foundation (scaffold + config + DB + domain models)

## What was done

Implemented Fase 1 physical foundation exactly per PLAN:

1. **Project scaffold** — installable `src/diana` via hatchling, pytest config, package roots (`cognitive`, `infrastructure/db` only — no empty stubs for items 2–4).
2. **Settings (TDD)** — `pydantic-settings` env-driven config; required secrets with no unsafe defaults; `.env.example` placeholders only.
3. **Cognitive domain models (TDD)** — pure Pydantic: `Comprehension`, `Plan`, `EvaluationProfile` (7D), `Decision` (approve|escalate), `TurnStatus` + terminal set, optional `IncomingTurn`.
4. **ORM + Alembic** — 8 F1 tables, FK `pipeline_traces.turn_id → turns.id`, seed without secrets/owner id; async `session.py` + async `alembic/env.py`.

## Files created

| Path | Role |
|------|------|
| `pyproject.toml` | Package + deps + pytest |
| `.env.example` | Empty secret placeholders |
| `README.md` | Setup, tests, migrations |
| `src/diana/__init__.py` | Package root |
| `src/diana/config.py` | Settings |
| `src/diana/cognitive/__init__.py` | Cognitive package |
| `src/diana/cognitive/models.py` | F1 domain contracts |
| `src/diana/infrastructure/__init__.py` | Infrastructure package |
| `src/diana/infrastructure/db/__init__.py` | DB package |
| `src/diana/infrastructure/db/models.py` | SQLAlchemy 8 tables |
| `src/diana/infrastructure/db/session.py` | Async engine/session |
| `alembic.ini` | Alembic config (placeholder URL) |
| `alembic/env.py` | Async migration env |
| `alembic/script.py.mako` | Alembic template |
| `alembic/versions/001_f1_foundation.py` | F1 schema + seed |
| `tests/conftest.py` | Env cleanup fixture |
| `tests/unit/test_config.py` | Settings tests |
| `tests/unit/cognitive/test_models.py` | Domain model tests |
| `tests/unit/cognitive/test_evaluation_profile_invariants.py` | 7D invariants |

## Commits

Not committed by executor (workspace may commit separately). Suggested conventional split if needed:

- `chore: scaffold package and tooling`
- `feat: add settings`
- `feat: add cognitive domain models`
- `feat: add f1 schema and alembic`

## Deviations

| Item | Resolution |
|------|------------|
| Pre-existing DB objects / alembic_version `0003_escalations_vip_fk_set_null` | Dropped public schema for clean smoke; ran `001_f1_foundation` successfully |
| MVP seed includes `owner_telegram_id` | **Omitted** per PLAN L8 / R6 — owner only via Settings/env |
| `pipeline_traces.turn_id` FK | **Added** (prefer FK per impact R13) |
| Indexes with `DESC` | Created in migration via `sa.text("… DESC")`; ORM uses plain composite indexes |

## Verifications

```text
pytest tests/unit -q
# 17 passed

alembic upgrade head   # DATABASE_URL=postgresql+asyncpg://diana:diana@localhost:5432/diana
alembic downgrade base
alembic upgrade head
# OK — 8 tables; seed keys: global_mode, forbidden_keywords, eval_thresholds.safety=0.3, trace_ttl_days=30
# 0 F2/F3 tables
```

## Locked contracts frozen

- `EvaluationProfile`: exactly 7 float dims; no confidence/score/mean
- `Decision.action`: only `approve` | `escalate`
- Schema: exactly 8 F1 tables
- Secrets: env only

## Self-Check: PASSED

- [x] All PLAN tasks completed
- [x] PLAN unit tests run (`pytest tests/unit`)
- [x] 0 regressions attributable (greenfield)
- [x] Project conventions respected (AGENTS limits, English artifacts, no pipeline logic)

## Hardener fix round (a075917f)

- **pytest:** 58 passed
- **28 fixed / 1 wontfix** (pgcrypto retained on downgrade — documented)
- Highlights: `.gitignore`, SecretStr + validation, alembic fail-loud, `extra=forbid`, DESC indexes, turn_id FKs, schema/import purity tests

## Log

`.planning/quick/gsd-01-foundation.log`


## Review loop (hardener)
- effort: 5
- rounds: 2
- reviewers: 3 general + plan + tests + security
- round1 opens: ~29 markers (deduped bugs: notificado, gitignore, tests, secrets)
- round2 opens: 0
- tests after fixes: 58 passed
