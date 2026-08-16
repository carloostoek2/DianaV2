---
title: Esquema de Datos — Evolución de Agente
created: 2026-08-11
updated: 2026-08-16
type: entity
tags: [dato, aprendizaje, decision]
sources: [../../alembic/versions/024_agent_evolution_foundations.py, ../../alembic/versions/026_agent_evolution_turn_category_columns.py, ../../src/diana/infrastructure/db/models.py]
confidence: high
---

# Esquema de Datos — Evolución de Agente

Fundaciones de datos de la evolución de agente (migraciones 024–026; ver [[spec-evolucion-agente]]). Sin estos datos no hay perfil evolutivo ni trust budget.

## Tablas

- **`vip_profile`** — perfil sintetizado por VIP: `stable_traits` jsonb, `recent_trend` jsonb, `sensitivities` jsonb, `version`, `last_synthesized_at`, `synthesis_trigger` (`volume`|`session_close`|`strong_signal`|`emotional_signal`) — ver [[perfil-evolutivo]].
- **`vip_profile_history`** — snapshots de cada versión anterior: `profile_snapshot` jsonb, `diff_summary`, `created_at` — auditoría de drift.
- **`vip_mood_state`** — mood por VIP: 3 ejes float `axis_playful_serious`, `axis_warm_distant`, `axis_energy`, `updated_at`.
- **`vip_trust_budget`** — confianza por `(vip_id, turn_category)`: `trust_score` (0..1), `correction_count`, `autonomous_count`, `last_correction_at` — ver [[trust-budget]].
- **`turn_category_log`** — una fila por turno (unique `turn_id`). Vocab CHECK: `fatico`|`informativo`|`emocional`|`sensible`. 026: `would_autonomous` (shadow: el carril rápido habría autoenviado; no lee trust budget), `confidence` (nullable; “no estoy seguro” es confidence por debajo del umbral, no un valor extra del CHECK).
- **`emotional_signal_log`** — señal emocional por turno: `signal_type` (`vulnerabilidad`|`angustia`|`revelacion_de_vida`|`ruptura_de_patron`), `intensity`, `should_trigger_synthesis`, `should_escalate_to_owner`, `pipeline_would_have_escalated` (nullable) — ver [[detector-emocional]].
- **`backfill_queue`** — cola durable de perfiles pendientes (023, REQ-MEM-05): una extracción a la vez, lock global.

## Retención

`vip_profile_history`, `turn_category_log` y `emotional_signal_log` crecen sin límite — política de purga con el patrón de `TracePurgeJob` (`agent_data_purge.py`; TTL env `*_TTL_DAYS`, default 90).

Relacionado: [[perfil-evolutivo]], [[trust-budget]], [[detector-emocional]], [[memoria-vip]], [[feature-flags]].

^[alembic/versions/023-026, docs/SPEC-EVOLUCION-AGENTE.md §Fase 0]
