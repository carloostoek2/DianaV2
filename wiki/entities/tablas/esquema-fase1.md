---
title: Esquema de Datos — Base (F1)
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [dato, requisito, operacion]
sources: [../../alembic/versions/, ../../docs/SPEC-1.1.md]
confidence: high
---

# Esquema de Datos — Base (F1)

Tablas fundacionales de la Fase 1 (MVP Supervisado). Diseñadas en SPEC-1.1 §5 para evitar migraciones rotas; implementadas en las migraciones 001-005+.

## Tablas

- **`vips`** — allowlist: `telegram_user_id` único, `display_name`, `is_active`, `paused_until` (REQ-AUTH-01..03, REQ-ADM-04).
- **`message_history`** — historial crudo de mensajes (`chat_id`, `role` vip|owner|bot, `text`, `timestamp`; índice por chat+timestamp).
- **`pipeline_traces`** — trazabilidad completa del pipeline (comprensión, plan, retrieved, prompt, texto generado, evaluación, decisión, delivery) — la base de la explicabilidad (REQ-COG-11, REQ-PER-06/07).
- **`pending_deliveries`** — entregas en vuelo con `status` (pending|delivering|done|cancelled); recuperación tras reinicio (REQ-PER-02).
- **`turns`** — máquina de estados del turno (`status`: received…delivered|escalated|superseded|failed; `superseded_by` para la cadena de supersedencia). Invariante: un no-terminal por chat (ver [[turn-coordinator]]).
- **`escalation_events`** — eventos de escalación (`tipo`: cortocircuito_determinista | semantica, `motivo`, `notificado`; ver [[escalacion]]).
- **`business_connections`** — conexiones de negocio persistentes (REQ-PER-01).
- **`pending_approvals`** — cola de aprobaciones en DM (CAS `claim_waiting`, paridad con el doble en memoria).

Relacionado: [[spec-1-1]], [[superficie-admin]], [[infrastructure-persistence]].

^[alembic/versions/001-005, src/diana/infrastructure/db/models.py]
