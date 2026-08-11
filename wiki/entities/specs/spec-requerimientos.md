---
title: REQUERIMIENTOS.md
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [spec, requisito, estado]
sources: [../../docs/REQUERIMIENTOS.md]
confidence: high
---

# REQUERIMIENTOS.md

Documento de requisitos del sistema (v2.1 — Arquitectura Cognitiva + refinamiento de aprendizaje, políticas y métricas). Define **qué debe cumplir** el sistema, sin prescribir tecnologías (eso vive en [[spec-1-1]]).

## Contenido principal

- **Arquitectura Cognitiva** (§3): el sistema no es un chatbot; el LLM es razonador especializado; principio rector (ver [[principio-rector]]).
- **Alcance** (§4): chats de negocio VIP, DM de la dueña, escalación, memoria, recontacto, promo no-VIP, sandbox, pipeline auditable.
- **Requisitos funcionales** (§9): REQ-AUTH, REQ-COG, REQ-VIP, REQ-HUM, REQ-MODE, REQ-ESC, REQ-GAP, REQ-MEM, REQ-TRN, REQ-EVAL, REQ-REE, REQ-PRO, REQ-ADM, REQ-PER, REQ-MET.
- **Requisitos no funcionales** (§10): REQ-NFR-01..16 (UX percibida, concurrencia, control de riesgo, explicabilidad, sustituibilidad, anti-contaminación, aprendizaje controlado…).
- **Reglas de negocio transversales** (§11): BR-01..15.
- **Matriz de decisión** (§12), historias de usuario (§13), criterios de aceptación AC-01..19 (§14).
- **MVP recomendado** (§18): recorte por releases (supervisado → MVP+ aprendizaje → producto completo).

## Relaciones

- Bases de [[spec-1-1]] (el "cómo").
- Operación para agentes: [[agents-md]] (límites de módulo).
- Cambios de comportamiento de producto → actualizar REQUERIMIENTOS primero, luego SPEC (§17).

^[docs/REQUERIMIENTOS.md]
