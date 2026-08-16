---
title: Esquema de Datos — Conocimiento (F2)
created: 2026-08-11
updated: 2026-08-16
type: entity
tags: [dato, memoria, aprendizaje, politica]
sources: [../../alembic/versions/003_f2_knowledge_tables.py, ../../alembic/versions/029_feedback_quality.py, ../../alembic/versions/027_ephemeral_events.py, ../../src/diana/infrastructure/db/models.py]
confidence: high
---

# Esquema de Datos — Conocimiento (F2)

Tablas de conocimiento (Fase 2 + extensiones 027/029). Índices HNSW con pgvector (384 dims). Las columnas de SPEC-1.1 que nunca se migraron (`example_applied`, `quality_score`, `source_staging_id`) no existen en el esquema vivo.

## Tablas F2

- **`profiles`** — un embedding por VIP. PK `vip_id` (FK `vips.id`); `embedding` vector(384); `content` jsonb (no `data`); `tipo` text. Recuperado por `ProfileRetriever` (knowledge.profile).
- **`memories`** — hechos y preferencias por VIP, **siempre filtradas por `vip_id`** (BR-15; ver [[memoria-vip]]). `content` jsonb, `category`, `confidence`, `embedding`. F5 (022): `status` (`auto`|`pending_owner`|`approved`|`discarded`), `source_turn_id` (sin FK).
- **`contexts`** — contexto temporal interpretado: `chat_id`, `embedding`, `content` jsonb, `expires_at`.
- **`policies`** — doctrina estructurada: `trigger_description`, `rule`, `scope` (eje de canal, default `all`), `is_active`, `valid_until`, `source_query_id` (sin FK; no `created_from_gray_zone`). 029: `vip_id` nullable (FK `vips.id`, índice). `vip_id IS NULL` = global. No reutilizar `scope` para el eje VIP.
- **`examples`** — banco vivo: `turn_text`, `draft_text`, `corrected_text`, `context` jsonb, `is_counter_example` (no `is_counterexample`). 029: `quality` text NOT NULL default `standard` (repo valida `standard`|`gold`; gold rankea antes en similitud); `vip_id` nullable (FK `vips.id`). Visibilidad: Atención/None solo globales; VIP ve globales + propios.
- **`staging_candidates`** — Staging Area: `candidate_type` (013; no `type`), `payload` jsonb, `status` default `pending`, `turn_id` FK. No hay columna `created_by`; `original_draft` vive dentro de `payload` — ver [[aprendizaje-post-turno]].
- **`gray_zone_queries`** — consultas de doctrina: `question`, `draft`, `status` default `open`, `freeze_until`, `resolved_at` (no `resolution`). F4: `chat_id` (019), `business_connection_id` (020) — ver [[zona-gris-y-politicas]].

## Eventos temporales (027)

- **`ephemeral_events`** — contexto acotado que inyecta la dueña (`knowledge.ephemeral`). Activa si `is_paused = false` y `start_at <= now < end_at` (ventana semiabierta). Columnas: `body`, `start_at`, `end_at`, `is_paused`, `created_by`, `created_at`, `updated_at`. Sin feature flag: el augmenter está siempre cableado. Caducadas no se purgan; el retriever deja de encontrarlas.

Relacionado: [[capability-registry]], [[spec-fase2]], [[anti-contaminacion]], [[esquema-fase6]], [[feature-flags]].

^[alembic/versions/003_f2_knowledge_tables.py, alembic/versions/027_ephemeral_events.py, alembic/versions/029_feedback_quality.py, src/diana/infrastructure/db/models.py]
