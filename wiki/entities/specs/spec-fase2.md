---
title: SPEC-FASE2.md
created: 2026-08-11
updated: 2026-08-21
type: entity
tags: [spec, memoria, aprendizaje, politica]
sources: [../../docs/SPEC-FASE2.md]
confidence: high
---

# SPEC-FASE2.md

Contrato de diseño e implementación de la **Fase 2 (MVP+)**: Memoria, Aprendizaje Controlado y Zona Gris (v2.1, basado en [[spec-1-1]] y [[spec-requerimientos]] bloques MEM/TRN/GAP/EVAL). **Estado (2026-08-21): implementada y desplegada** — los cuatro flags están activos en el entorno de ejecución (ver [[feature-flags]] y [[estado-del-proyecto]]).

## Propósito

Transformar el "bot supervisado" de Fase 1 en un sistema que aprende y razona con memoria:

1. **Memoria real** — retrievers con pgvector (memories, policies, examples).
2. **Doctrina reutilizable** — [[zona-gris-y-politicas]]: consultas a la dueña → policies estructuradas.
3. **Aprendizaje controlado** — [[aprendizaje-post-turno]] con Staging Area y promoción explícita.
4. **Evaluación calibrable** — registro de perfiles para [[calibracion-de-umbrales]] futura.
5. **Sustituibilidad** — mismas interfaces del [[capability-registry]]; el Director no cambia.

## Feature toggles (activos en runtime)

`FEATURE_MEMORY_ENABLED=true`, `FEATURE_GRAY_ZONE_ENABLED=true`, `FEATURE_STAGING_ENABLED=true`, `FEATURE_SANDBOX_ENABLED=true` — los cuatro activos en `.env` (defaults `false` en código, overridables por env; ver [[feature-flags]]).

## Componentes nuevos

- **Retrievers reales** (reemplazan stubs): MemoryRetriever (umbral 0.75, `WHERE vip_id` obligatorio), PolicyRetriever (umbral 0.8, scope), ExamplesRetriever (top-k 3-5, contraejemplo 10%).
- **StagingService** — `save_correction`, `promote_to_example`, `promote_to_policy`, `discard`. Toda política nueva pasa por staging (BR-13).
- **GrayZoneService** — `create_query`, `freeze_vip`/`unfreeze_vip`, `resolve_with_doctrine`, `expire_old_queries` (timeout 24h default, acción configurable: escalate o use_draft).
- **PolicyDistiller** — estructura la política: `trigger_description`, `rule`, `scope`, `ejemplo_aplicado`.
- **Evaluador** — doctrina según tabla: `needs_policy=false` → 0.7 neutral; con políticas → valor real; `needs_policy=true` + sin políticas → 0.2 (señal de zona gris).
- **Decisor** — prioridad 2 nueva: `consult_doctrine` cuando `needs_policy=true` y retrieval vacío (ver [[decisor]]).

## Orden de activación (histórico)

Índices HNSW → seed de políticas → flags uno a uno (memoria → staging → zona gris). Rollback solo cambiando configuración.

^[docs/SPEC-FASE2.md]
