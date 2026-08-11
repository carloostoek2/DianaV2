---
title: Esquema de Datos — Conocimiento (F2)
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [dato, memoria, aprendizaje, politica]
sources: [../../alembic/versions/, ../../docs/SPEC-FASE2.md]
confidence: high
---

# Esquema de Datos — Conocimiento (F2)

Tablas de conocimiento de la Fase 2 (MVP+): los cinco tipos de conocimiento + staging + zona gris. Índices HNSW con pgvector (384 dims, embeddings locales).

## Tablas

- **`profiles`** — perfil permanente del VIP (PK `vip_id`, `data` jsonb). Recuperado por `ProfileRetriever` (knowledge.profile).
- **`memories`** — hechos y preferencias por VIP, **siempre filtradas por `vip_id`** (BR-15; ver [[memoria-vip]]). Columnas F5: `status` (auto|pending_owner|approved|discarded), `source_turn_id`.
- **`contexts`** — contexto temporal interpretado, con `expires_at` (knowledge.context).
- **`policies`** — doctrina estructurada: `trigger_description`, `rule`, `example_applied`, `scope`, `valid_until`, `is_active`, `created_from_gray_zone` (ver [[zona-gris-y-politicas]]).
- **`examples`** — banco vivo de few-shots + contraejemplos (`is_counterexample`, `original_draft`, `quality_score`, `source_staging_id`).
- **`staging_candidates`** — Staging Area: `type` (example|memory|policy), `payload` jsonb, `status` (pending|promoted|discarded), `created_by` (correction|extraction|gray_zone) — ver [[aprendizaje-post-turno]].
- **`gray_zone_queries`** — consultas de doctrina abiertas: `status` (open|resolved|expired), `freeze_until`, `resolution` — ver [[zona-gris-y-politicas]].

Relacionado: [[capability-registry]], [[spec-fase2]], [[anti-contaminacion]].

^[alembic/versions/003+, docs/SPEC-FASE2.md §4]
