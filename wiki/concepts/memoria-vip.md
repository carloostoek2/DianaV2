---
title: Memoria VIP
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [memoria, aprendizaje]
sources: [../../docs/SPEC-FASE5.md, ../../docs/REQUERIMIENTOS.md]
confidence: high
---

# Memoria VIP

Conocimiento procesado del VIP en `memories` (Fase 5: "Perfil de VIP con Memoria"). Construye el puente entre el historial crudo (`message_history`, funcional) y la memoria procesada (estaba **vacía: no existía escritor**).

## Estructura de la ficha

Cada sección es una fila de `memories` con `category` + embedding + `content` jsonb, más una fila `category='perfil'` con la ficha completa (vista/edición, backfill idempotente):

- `identidad` — datos personales estables
- `preferencias` — tono y temas que le funcionan
- `comercial` — historial de compra e intereses
- `limites` — temas a evitar
- `sensible` — datos delicados (requieren aprobación de la dueña)
- `perfil` — ficha completa en un JSON

Formato de fila: `{texto, tipo, confianza, fuente, turno_id, aprobado_por}`.

## Flujos

- **Backfill (inicial):** historial cronológico → LLM por ventanas (200 msgs / 12K chars) → secciones + perfil. Idempotente. **Cola de a uno** con lock global y timer `BACKFILL_INTERVAL_SEC` (3600s) para proteger la cuenta de Telegram. Disparo: botón "Generar perfil" en la ficha del panel + automático al registrar VIP nuevo (decisión 2026-08-05: TODOS los VIPs se perfilan, sin opt-out).
- **Mantenimiento post-turno:** extracción incremental tras turns terminales no-sandbox con `FEATURE_MEMORY_ENABLED`; el LLM recibe un resumen de la ficha para **no repetir** hechos.
- **Dedup:** similitud semántica ≥ 0.85 contra filas del mismo VIP antes de insertar; fusiona si aporta detalle.
- **Control de la dueña:** hechos `sensible` nacen `status='pending_owner'` → DM de aprobación (aprobar/descartar/editar). **Pendiente no se inyecta al contexto** (REQ-MEM-10).
- **Runtime:** `MemoryRetriever` sin cambios de interfaz (umbral 0.75, límite 5, filtrado por `vip_id`); excluye `pending_owner`/`discarded`.

## Reglas

- **BR-15 / REQ-MEM-12:** toda lectura/escritura filtra por `vip_id`; el canal `atencion` ([[canal-atencion]]) nunca toca `memories`; los ejemplos del banco y la memoria son mundos separados ([[anti-contaminacion]]).
- **Límites de módulo:** el escritor vive en `application/` y `learning/` (post-turno), nunca en `cognitive/` ni `behavior/`; `cognitive/` solo lee vía retriever.
- **Trazabilidad:** cada fila tiene `source_turn_id` + `aprobado_por`; la ficha `generado_el`/`actualizado_el`. Migración 022 (`status`, `source_turn_id`, índice `(vip_id, status)`).

Relacionado: [[spec-fase5]], [[perfil-evolutivo]], [[aprendizaje-post-turno]].

^[docs/SPEC-FASE5.md]
