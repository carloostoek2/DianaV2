---
title: Esquema de Datos — Proactividad y Métricas (F3)
created: 2026-08-11
updated: 2026-08-16
type: entity
tags: [dato, operacion, modo]
sources: [../../alembic/versions/008_recontact_promo.py, ../../alembic/versions/003_f2_knowledge_tables.py, ../../src/diana/infrastructure/db/models.py]
confidence: high
---

# Esquema de Datos — Proactividad y Métricas (F3)

Tablas de la Fase 3 (Producto Completo): recontacto, promo, métricas, configuración y timers de runtime.

## Tablas

- **`recontact_schedules`** — recontacto programado: `last_contact_at`, `next_contact_at`, `status` (pending|done|cancelled). Índice por `(next_contact_at, status)`.
- **`promo_triggers`** — triggers exactos de promo: `trigger_text` único, `response_sequence` jsonb, `repeat_first_message`, `is_active`.
- **`promo_executions`** — trazabilidad ligera (`chat_id`, `trigger_id`, `sent_at`, `sequence_sent`, `status`) — no usa `pipeline_traces` (no es turno cognitivo).
- **`learning_metrics`** — EAV creado en 003 (no columnas semanales): `metric_name` text, `value` float, `vip_id` nullable, `recorded_at`. 009 no ALTER esta tabla; solo siembra el blob `calibration` en `system_config`.
- **`system_config`** — configuración global (flags sembrados, umbrales, blobs) — base de [[feature-flags]] y de [[calibracion-de-umbrales]]. Los flags de runtime se leen de env, no de esta tabla.
- **`runtime_timers`** — timers persistentes de runtime para recuperación tras crash (014/016).
- **`owner_marks`** — marcas de la dueña (ej. falsos positivos de escalación) para métricas. PK compuesta `(turn_id, kind)`.

Relacionado: [[spec-fase3]], [[application-services]], [[jobs]], [[modos-de-operacion]].

^[alembic/versions/003, 008-010, 014, 016, src/diana/infrastructure/db/models.py]
