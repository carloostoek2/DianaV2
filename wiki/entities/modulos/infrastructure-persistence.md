---
title: Infrastructure / Persistence
created: 2026-08-11
updated: 2026-08-16
type: entity
tags: [modulo, contrato]
sources: [../../AGENTS.md, ../../src/diana/infrastructure/db/models.py, ../../alembic/versions/029_feedback_quality.py]
confidence: high
---

# Infrastructure / Persistence

Capa de persistencia e infraestructura. **PostgreSQL es el único almacén durable** (ADR-003) — sin Redis en V1.

- **Pregunta que responde:** ¿Cómo guardo y recupero datos?
- **Puede:** repositorios, sesiones, migraciones (Alembic).
- **Nunca puede:** contener lógica de negocio o cognitiva.

## Tecnología

- SQLAlchemy 2.0 (async) + asyncpg; Pydantic v2 para validación de objetos cognitivos.
- pgvector con índices HNSW para embeddings (Fase 2+).
- 34 tablas en `Base.metadata`. Head de repo: **`029_feedback_quality`** (cadena 001–029 en `alembic/versions/`). Tablas por fase: [[esquema-fase1]], [[esquema-conocimiento]], [[esquema-fase3]], [[esquema-fase4]], [[esquema-evolucion]], [[esquema-fase6]].

## Reglas

- Secretos (tokens, API keys) nunca en código versionado (REQ-PER-04) — viven en `.env`.
- Los objetos intermedios del pipeline se persisten con TTL configurable (REQ-COG-11, REQ-PER-06).
- La capa no conoce el pipeline; los repositorios exponen operaciones de datos.

## Implementación real (2026-08-16)

`infrastructure/` agrupa `db/models.py` (ORM F1–F5 + evo + `ephemeral_events`), `db/session.py`, 35 repositorios en `db/repositories/`, y `telethon/vip_history_fetcher.py`.

Repositorios: evo-agente (`vip_profile`, `vip_profile_history`, `vip_trust_budget`, `vip_mood_state`, `turn_category`, `emotional_signal`), memoria F5 (`backfill_queue`, `memories`), F4 (`atencion_cycles`, `daily_message_limits`), F3 (`promo_triggers`, `promo_executions`, `recontact_schedules`, `runtime_timers`), F6 (`link_events`), eventos temporales (`ephemeral_events`), más `traces`, `turns`, `deliveries`, `approvals`, `staging`, `gray_zone`, `system_config`, `persona_versions`, `owner_marks`, `calibration_data`, `metrics_data`, `learning_metrics`, `examples`, `policies`, `profiles`, `history`, `vips`, `escalations`, `business_connections`.

`LinkEvent` no vive en `models.py`: ORM inline en `db/repositories/link_events.py` (se registra al importar el paquete). `examples.quality` / `examples.vip_id` / `policies.vip_id` están en `models.py` (029).

Apply en producción de 027–029: **no verificado** (último snapshot: [[estado-del-proyecto]] 2026-08-11, head prod 026).

^[src/diana/infrastructure/*, alembic/versions/027-029]
