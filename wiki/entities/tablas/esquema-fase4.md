---
title: Esquema de Datos — Canal Atención (F4)
created: 2026-08-11
updated: 2026-08-16
type: entity
tags: [dato, modo, regla-negocio]
sources: [../../alembic/versions/018_channel_type_atencion.py, ../../alembic/versions/021_atencion_cycles.py, ../../src/diana/infrastructure/db/models.py]
confidence: high
---

# Esquema de Datos — Canal Atención (F4)

Cambios de esquema de la Fase 4 (Atención al Cliente General, canal no-VIP; ver [[canal-atencion]]). Migraciones 018–021.

## Tablas y cambios

- **`persona_versions.channel_type`** — columna (`vip` | `atencion`); unique parcial activo por `(channel_type, is_active)`. Seed del perfil `atencion`.
- **`daily_message_limits`** — contador diario por chat de canal atención: PK `(chat_id, fecha_local)`, `count`. Upsert atómico por turno; el corte es determinista (REQ-ATN-03/04).
- **`atencion_cycles`** — ciclo de vida por chat (021): PK `chat_id`, `started_at` (ventana lineal de 30 días, no se extiende al re-trigger), `closed_at` / `close_reason` (cierre anticipado, p. ej. pago).
- **`gray_zone_queries`** — F4 añade `chat_id` (019) y `business_connection_id` (020) para freeze/reconstrucción en chats sin VIP.
- **`turns.channel_type`** / **`pipeline_traces.channel_type`** — default `vip` (019).

## Reglas

- El canal `atencion` usa solo `message_history` por chat — **nunca** `memories` (anti-contaminación entre canales).
- Los turns de atención se marcan `channel_type="atencion"` en `turns` y `pipeline_traces`.

Relacionado: [[spec-fase4]], [[canal-atencion]], [[anti-contaminacion]], [[esquema-conocimiento]].

^[alembic/versions/018-021, docs/SPEC-FASE4.md §13]
