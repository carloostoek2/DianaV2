---
title: Esquema de Datos — Base (F1)
created: 2026-08-11
updated: 2026-08-16
type: entity
tags: [dato, requisito, operacion]
sources: [../../alembic/versions/001_f1_foundation.py, ../../src/diana/infrastructure/db/models.py]
confidence: high
---

# Esquema de Datos — Base (F1)

Tablas fundacionales de la Fase 1 (MVP Supervisado). Diseñadas en SPEC-1.1 §5; implementadas en 001–005 y columnas operativas posteriores sobre las mismas tablas.

## Tablas

- **`vips`** — allowlist: `telegram_user_id` único, `display_name`, `is_active`, `paused_until` (REQ-AUTH-01..03, REQ-ADM-04). 004: `frozen_until`. 007: `auto_send` (default false).
- **`message_history`** — historial crudo (`chat_id`, `role` vip|owner|bot, `text`, `timestamp`; índice por chat+timestamp).
- **`pipeline_traces`** — trazabilidad del pipeline (comprensión, plan, retrieved, prompt, texto generado, evaluación, decisión, delivery). 005: `timings` jsonb. 019: `channel_type` (`vip`|`atencion`).
- **`pending_deliveries`** — entregas en vuelo con `status` (pending|delivering|done|cancelled); recuperación tras reinicio (REQ-PER-02).
- **`turns`** — máquina de estados (`status`: received…delivered|escalated|superseded|failed; `superseded_by`). 002: `error`. 019: `channel_type`. Invariante: un no-terminal por chat (ver [[turn-coordinator]]).
- **`escalation_events`** — eventos de escalación (`tipo`: cortocircuito_determinista | semantica, `motivo`, `notificado`; ver [[escalacion]]).
- **`business_connections`** — conexiones de negocio persistentes (015; REQ-PER-01).
- **`pending_approvals`** — cola de aprobaciones en DM (CAS `claim_waiting`, paridad con el doble en memoria).
- **`system_config`** — clave/valor jsonb global (flags sembrados, umbrales). Runtime de flags es env; ver [[feature-flags]].

Relacionado: [[spec-1-1]], [[superficie-admin]], [[infrastructure-persistence]].

^[alembic/versions/001-007, src/diana/infrastructure/db/models.py]
