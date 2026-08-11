---
title: Esquema de Datos — Proactividad y Métricas (F3)
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [dato, operacion, modo]
sources: [../../alembic/versions/, ../../docs/SPEC-FASE3.md]
confidence: high
---

# Esquema de Datos — Proactividad y Métricas (F3)

Tablas de la Fase 3 (Producto Completo): recontacto, promo, métricas, configuración y timers de runtime.

## Tablas

- **`recontact_schedules`** — recontacto programado: `last_contact_at`, `next_contact_at`, `status` (pending|done|cancelled). Índice por `(next_contact_at, status)`.
- **`promo_triggers`** — triggers exactos de promo: `trigger_text` único, `response_sequence` jsonb, `is_active`.
- **`promo_executions`** — trazabilidad ligera de promos enviadas (`chat_id`, `trigger_id`, `sequence_sent`, `status`) — no usa pipeline_traces (no es turno cognitivo).
- **`learning_metrics`** — métricas agregadas semanales: `approval_without_correction_rate`, `gray_zone_repetition_count`, `false_positive_escalation_rate`, `style_drift_score`, `autonomous_send_rate`, `total_turns`.
- **`system_config`** — configuración global (flags, umbrales, blobs) — la base de los [[feature-flags]] y de la [[calibracion-de-umbrales]].
- **`runtime_timers`** — timers persistentes de runtime para recuperación tras crash (timer_manager).
- **`owner_marks`** — marcas de la dueña (ej. falsos positivos de escalación) para métricas.

Relacionado: [[spec-fase3]], [[application-services]], [[jobs]], [[modos-de-operacion]].

^[alembic/versions/006+, docs/SPEC-FASE3.md §4]
