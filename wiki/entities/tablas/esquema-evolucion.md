---
title: Esquema de Datos — Evolución de Agente
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [dato, aprendizaje, decision]
sources: [../../alembic/versions/, ../../docs/SPEC-EVOLUCION-AGENTE.md]
confidence: high
---

# Esquema de Datos — Evolución de Agente

Fundaciones de datos de la evolución de agente (migraciones 024+, Fase 0 del contrato; ver [[spec-evolucion-agente]]). Sin estos datos no hay perfil evolutivo ni trust budget.

## Tablas

- **`vip_profile`** — perfil sintetizado por VIP: `stable_traits` (jsonb), `recent_trend` (jsonb), `sensitivities` (jsonb), `version`, `last_synthesized_at`, `synthesis_trigger` (volume|session_close|strong_signal|emotional_signal) — ver [[perfil-evolutivo]].
- **`vip_profile_history`** — snapshots de cada versión anterior: `profile_snapshot` (jsonb), `diff_summary` (texto LLM), `created_at` — auditoría de drift.
- **`vip_mood_state`** — estado de mood por VIP: 3 ejes float (-1..1) `axis_playful_serious`, `axis_warm_distant`, `axis_energy`, `updated_at` — motor de mood (shadow).
- **`vip_trust_budget`** — confianza por `(vip_id, turn_category)`: `trust_score` (0..1), `correction_count`, `autonomous_count`, `last_correction_at` — ver [[trust-budget]].
- **`turn_category_log`** — clasificación de cada turno (phatic|informational|emotional|sensitive) — alimenta trust budget.
- **`emotional_signal_log`** — señal emocional por turno: `signal_type`, `intensity`, `should_trigger_synthesis`, `should_escalate_to_owner`, `pipeline_would_have_escalated` (nullable) — ver [[detector-emocional]].
- **`backfill_queue`** — cola durable de perfiles pendientes (REQ-MEM-05): una extracción a la vez, lock global.

## Retención

`vip_profile_history`, `turn_category_log` y `emotional_signal_log` crecen sin límite — política de purga con el patrón de `TracePurgeJob` (retención por tabla; `agent_data_purge.py`).

Relacionado: [[perfil-evolutivo]], [[trust-budget]], [[detector-emocional]], [[memoria-vip]].

^[alembic/versions/024+, docs/SPEC-EVOLUCION-AGENTE.md §Fase 0]
