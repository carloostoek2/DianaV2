---
title: Learning
created: 2026-08-11
updated: 2026-08-16
type: entity
tags: [modulo, aprendizaje, contrato]
sources: [../../AGENTS.md, ../../docs/SPEC-1.1.md, ../../src/diana/application/staging_service.py]
confidence: high
---

# Learning

Módulo de aprendizaje, **siempre post-turno y controlado** (ver [[aprendizaje-post-turno]]).

- **Pregunta que responde:** ¿Qué aprendimos de este turno?
- **Puede:** extraer candidatos, escribir en Staging, destilar políticas, actualizar métricas, calibrar umbrales.
- **Nunca puede:** ejecutarse durante el pipeline de decisión, promover automáticamente a banco vivo.

## Subcomponentes (SPEC-1.1 §11 — diseño)

El diseño nombra extractor, staging, destiller y métricas. En el repo el grueso vive fuera de `learning/`:

- `cognitive/policy_distiller.py` — destilación de doctrina de zona gris a política estructurada.
- `application/staging_service.py` — Staging Area y promoción (Fase 2+).
- `application/memory_extraction_service.py` — extracción de hechos (Fase 5).
- `application/calibration_service.py` + jobs — métricas y calibración (Fase 3).

## APIs de promoción (2026-08-16)

`StagingService` exige confirmación de la dueña. No hay auto-promoción.

| API | Qué escribe | Staging previo |
|---|---|---|
| `promote_to_example` | few-shot global `quality=standard` | sí (candidato `example` pending) |
| `promote_to_counter_example(vip_id=…)` | contraejemplo, global o de ese VIP | sí |
| `insert_gold_example(..., quality=gold, vip_id=…)` | gold (Destacar); alcance global o VIP | no — la dueña ya confirmó con Destacar |
| `promote_to_policy(..., vip_id=…)` | política activa, global o de ese VIP | sí |

`AtencionPromoteBlocked`: un candidato del canal `atencion` no entra al banco VIP (REQ-ATN-13, ver [[anti-contaminacion]]). Escrituras Destacar/Reprender van detrás de `FEATURE_QUALITY_FEEDBACK_ENABLED`; el retrieval de examples **siempre** usa `quality` y `vip_id`.

## Límites duros

- **Prohibido** que Learning sea llamado desde dentro del Director o del pipeline de decisión (AGENTS.md §2.2).
- La calibración de umbrales solo se ejecuta como job programado, nunca dentro del pipeline (AGENTS.md §4.5, ver [[feature-flags]]).

## Implementación real (2026-08)

`learning/` tiene 1 archivo real: `post_turn.py` — "Post-turn learning for F1: TRACE_KEYS completeness check only (no Staging)". El staging se opera desde la capa de aplicación, respetando la regla post-turno.

^[src/diana/learning/*, src/diana/application/staging_service.py, AGENTS.md §2.1]
