---
title: Superficie de Admin
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [operacion, contrato, modo]
sources: [../../src/diana/telegram/handlers/, ../../docs/SPEC-1.1.md]
confidence: high
---

# Superficie de Admin

Superficie de administración de la dueña en el DM con el bot (REQ-ADM-*). Toda acción de admin exige que el emisor sea el admin configurado (middleware `owner.py`).

## Handlers reales (2026-08)

- **`menu.py`** — menú principal y navegación.
- **`admin.py`** — aprobación/rechazo de borradores, estado del sistema (modo, LLM activo, salud).
- **`doctrine.py`** — flujo de [[zona-gris-y-politicas]] (`g:` — responder doctrina, `g:use_draft` en timeout).
- **`staging.py`** — gestión del Staging Area (promover/descartar candidatos; ver [[aprendizaje-post-turno]]).
- **`memory_approval.py`** — aprobación de hechos de memoria sensible `pending_owner` (F5; ver [[memoria-vip]]).
- **`persona_admin.py`** — gestión de `persona_versions` por canal ([[canal-atencion]]; migración 018).
- **`callbacks.py`** — keyboards de borradores (aprobar, corregir, regenerar, navegar variantes; `draft_variants.py`).
- **`business.py`** — mensajes de negocio (VIP).
- **`business_connection.py`** — gestión de la conexión de negocio.

## Capacidades por área (REQ-ADM)

- Allowlist VIP: añadir/quitar sin redeploy (REQ-AUTH-02); tope configurable (REQ-AUTH-03).
- Estado: modo, LLM activo, salud básica (REQ-ADM-02); hot-swap de proveedor (REQ-ADM-03).
- Pausa de VIP (REQ-ADM-04), sandbox (REQ-ADM-05), traza cognitiva de respuestas (REQ-ADM-07), staging (REQ-ADM-08), métricas de aprendizaje (REQ-ADM-09).
- Notificaciones: escalaciones + triage, doctrina pendiente, perfil generado, intención de pago (canal atención), resumen semanal.

## Reglas

- Solo la dueña (admin configurado) opera menús, aprobaciones y comandos (REQ-AUTH-08).
- Sin comandos nuevos para evolución de agente: todo vive en secciones de la ficha del VIP (EA-06).
- Los textos de la UI son español neutro obligatorio (ver [[comunicacion-con-producto]]).

^[src/diana/telegram/handlers/*, docs/REQUERIMIENTOS.md §9.13]
