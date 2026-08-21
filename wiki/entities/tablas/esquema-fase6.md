---
title: Esquema de Datos — Vínculo Lucien (F6)
created: 2026-08-16
updated: 2026-08-21
type: entity
tags: [dato, operacion, contrato]
sources: [../../alembic/versions/028_link_events.py, ../../src/diana/infrastructure/db/repositories/link_events.py, ../../docs/SPEC-FASE6.md]
confidence: high
---

# Esquema de Datos — Vínculo Lucien (F6)

Ledger de expulsiones Canal VIP (Lucien → Diana). Migración **`028_link_events`** (encadena 027; SPEC-FASE6 decía 027, pero 027 ya era `ephemeral_events`).

## Tabla

- **`link_events`** — una fila por payload `[LINK]`. `event_id` text unique (dedup idempotente). `user_id` del expulsado; `username`, `channel_id`, `channel_name` opcionales; `reason` obligatorio. `vip_id` UUID suelto (sin FK): se resuelve antes del insert si el expulsado es VIP activo; NULL si no. `state` default `pending`. `decision_at` al decidir. `created_at`.

ORM: clase `LinkEvent` **inline** en `src/diana/infrastructure/db/repositories/link_events.py` (no está en `models.py`). Se registra en `Base.metadata` al importar el paquete de repositorios.

## Estados

`pending` → `notified` → `decided_expel` | `decided_disable` | `decided_keep`. Si no es VIP activo: `ignored_not_vip` (sin aviso a la dueña).

## Gate

Solo corre con `FEATURE_LINK_ENABLED` y `LINK_CHAT_ID` (ver [[feature-flags]]). El flag está **activo** en `.env` desde 2026-08-21 (Fase 6 desplegada y verificada E2E); con el flag off el comportamiento sería idéntico al previo a la F6. Anti-contaminación: el `[LINK]` no entra al pipeline ni a `message_history`.

Relacionado: [[esquema-conocimiento]], [[infrastructure-persistence]], [[modos-de-operacion]], [[spec-fase3]].

^[alembic/versions/028_link_events.py, src/diana/application/link.py, docs/SPEC-FASE6.md]
