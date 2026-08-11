---
title: Learning
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [modulo, aprendizaje, contrato]
sources: [../../AGENTS.md, ../../docs/SPEC-1.1.md]
confidence: high
---

# Learning

Módulo de aprendizaje, **siempre post-turno y controlado** (ver [[aprendizaje-post-turno]]).

- **Pregunta que responde:** ¿Qué aprendimos de este turno?
- **Puede:** extraer candidatos, escribir en Staging, destilar políticas, actualizar métricas, calibrar umbrales.
- **Nunca puede:** ejecutarse durante el pipeline de decisión, promover automáticamente a banco vivo.

## Subcomponentes (SPEC-1.1 §11)

- `extractor.py` — extracción de hechos/candidatos (Fase 2).
- `staging.py` — gestión del Staging Area (Fase 2).
- `policy_distiller.py` — destilación de respuestas de zona gris en políticas estructuradas (Fase 2).
- `metrics.py` — métricas agregadas de aprendizaje (Fase 3).

## Límites duros

- **Prohibido** que Learning sea llamado desde dentro del Director o del pipeline de decisión (AGENTS.md §2.2).
- La calibración de umbrales solo se ejecuta como job programado, nunca dentro del pipeline (AGENTS.md §4.5, ver [[feature-flags]]).

## Implementación real (2026-08)

`learning/` tiene 1 archivo real: `post_turn.py` — "Post-turn learning for F1: TRACE_KEYS completeness check only (no Staging)". El grueso del aprendizaje vive en `application/` (staging_service, memory_extraction_service, calibration_service) y en jobs — el módulo learning quedó mínimo; el staging se opera desde la capa de aplicación, respetando la regla post-turno.

^[src/diana/learning/*, src/diana/application/staging_service.py, AGENTS.md §2.1]