---
title: SPEC-FASE5.md
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [spec, memoria, aprendizaje]
sources: [../../docs/SPEC-FASE5.md]
confidence: high
---

# SPEC-FASE5.md

Contrato de diseño e implementación de la **Fase 5 — Perfil de VIP con Memoria (backfill + mantenimiento)** (v1.0, aprobado). Construye el puente entre los dos caminos de la información:

- **Historial crudo** (`message_history`): funcional, 1.015+ mensajes importados.
- **Memoria procesada** (`memories`): **vacía (0 filas) — no existía escritor**. Esta fase lo crea (ver [[memoria-vip]]).

## Decisiones de producto (dueña)

1. El perfil por VIP se construye **una vez (backfill)** leyendo el historial completo; fichas ricas o casi vacías son aceptables.
2. Luego se **mantiene solo** con extracción post-turno incremental.
3. **Control de la dueña**: datos sensibles (salud, familia, dinero, ubicación, trabajo) → candidatos que la dueña aprueba; lo trivial se agrega solo.
4. La ficha es **visible y editable** en el panel (datos/notas por VIP).
5. Nada de esto se comparte con el canal de atención ([[spec-fase4]]): la memoria es exclusiva de VIPs.
6. `FEATURE_MEMORY_ENABLED` es la llave maestra: apagada → comportamiento idéntico al actual.

## Elementos clave

- **Backfill**: historial → LLM (ventanas de 200 msgs / 12K chars) → secciones en `memories` + fila `perfil`. Idempotente. Cola persistente con **lock global: una extracción a la vez** y timer (`BACKFILL_INTERVAL_SEC` = 3600s) para proteger la cuenta de Telegram.
- **Categorías de la ficha**: `identidad`, `preferencias`, `comercial`, `limites`, `sensible`, `perfil` (ficha completa).
- **Migración 022**: `memories.status` (`auto` | `pending_owner` | `approved` | `discarded`) + `source_turn_id` + índice `(vip_id, status)`.
- **Aprobación**: hechos `pending_owner` aparecen en el DM de la dueña (aprobar/descartar/editar); **no se inyectan al contexto** hasta aprobación.
- **Dedup**: similitud semántica ≥ 0.85 contra filas del mismo VIP antes de insertar.
- **Anti-contaminación**: toda lectura/escritura filtra por `vip_id` (BR-15); el canal `atencion` nunca toca `memories`; tests explícitos de aislamiento.

## Pendientes de privacidad (fix round F3)

Durante el backfill el historial completo del chat se envía al proveedor LLM externo (by-design, con ventanas y tope de 12K chars). Pendientes: opt-out por VIP, evaluación de masking PII, documentar retención, acuerdo de procesamiento con el proveedor.

^[docs/SPEC-FASE5.md]
