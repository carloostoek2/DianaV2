---
title: Infrastructure / Persistence
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [modulo, contrato]
sources: [../../AGENTS.md, ../../docs/SPEC-1.1.md]
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
- Tablas diseñadas por fase en SPEC-1.1 §5 (ver [[spec-1-1]]); migraciones 001-026 en `alembic/versions/`.

## Reglas

- Secretos (tokens, API keys) nunca en código versionado (REQ-PER-04) — viven en `.env`.
- Los objetos intermedios del pipeline se persisten con TTL configurable (REQ-COG-11, REQ-PER-06).
- La capa no conoce el pipeline; los repositorios exponen operaciones de datos.

## Implementación real (2026-08)

`infrastructure/` tiene 36 archivos: `db/models.py` (ORM SQLAlchemy 2.0 de F1+F2+F3), `db/session.py`, y ~30 repositorios en `db/repositories/` — incluyendo los nuevos de evolución de agente (`vip_profile`, `vip_profile_history`, `vip_trust_budget`, `vip_mood_state`, `turn_category`, `emotional_signal`), memoria F5 (`backfill_queue`, `memories`), F4 (`atencion_cycles`, `daily_message_limits`), F3 (`promo_triggers`, `promo_executions`, `recontact_schedules`, `runtime_timers`), más `traces`, `turns`, `deliveries`, `approvals`, `staging`, `gray_zone`, `system_config`, `persona_versions`, `owner_marks`, `calibration_data`, `metrics_data`, `learning_metrics`, `examples`, `policies`, `profiles`, `history`, `vips`, `escalations`, `business_connections`. También `telethon/vip_history_fetcher.py` (importación de historial DM de la cuenta personal).

^[src/diana/infrastructure/*, docs/SPEC-1.1.md §1]