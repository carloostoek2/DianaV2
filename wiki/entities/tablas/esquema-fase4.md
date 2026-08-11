---
title: Esquema de Datos — Canal Atención (F4)
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [dato, modo, regla-negocio]
sources: [../../alembic/versions/, ../../docs/SPEC-FASE4.md]
confidence: high
---

# Esquema de Datos — Canal Atención (F4)

Cambios de esquema de la Fase 4 (Atención al Cliente General, canal no-VIP; ver [[canal-atencion]]). Migración 018.

## Tablas y cambios

- **`persona_versions.channel_type`** — columna nueva (`vip` | `atencion`); la constraint de versión activa pasa a ser por `(channel_type, is_active)`. Seed del perfil `atencion` (persona + estilo + políticas semilla).
- **`daily_message_limits`** — contador diario por chat de canal atención: PK única `(chat_id, fecha_local)`, `count`. Upsert atómico por turno; el corte es determinista (REQ-ATN-03/04).
- **`atencion_cycles`** — ciclo de vida de atención por chat (F4).

## Reglas

- El canal `atencion` usa solo `message_history` por chat — **nunca** `memories` (anti-contaminación entre canales).
- Los turns de atención se marcan `channel_type="atencion"` en pipeline_traces.

Relacionado: [[spec-fase4]], [[canal-atencion]], [[anti-contaminacion]].

^[alembic/versions/018, docs/SPEC-FASE4.md §13]
