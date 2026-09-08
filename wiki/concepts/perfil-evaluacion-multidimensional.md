---
title: Perfil de Evaluación Multidimensional
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [arquitectura, decision]
sources: [../../docs/REQUERIMIENTOS.md, ../../docs/SPEC-1.1.md]
confidence: high
---

# Perfil de Evaluación Multidimensional

El Evaluador produce un **vector de dimensiones independientes**. **No existe score único ni promedio** (REQ-COG-08, BR-09) — es el reemplazo de la antigua "confianza única".

## Dimensiones mínimas obligatorias (7)

- **Naturalidad** — ¿suena a la dueña?
- **Precisión** — ¿dice algo falso?
- **Doctrina** — ¿respeta reglas de negocio **cuando el turno trae reglas recuperadas o las requiere**? Con regla presente se mide cumplimiento real **solo** contra el fence de policy (`<<KNOWLEDGE_POLICY_DATA>>`; memoria/perfil no son reglas). Sin regla aplicable (no hay `knowledge.policy` y `needs_policy=false`), internamente queda 0.5 y **no gatea** la autonomía; la dueña ve **«no aplica»** (borrador y modo sombra, sin ❌), no el número 0.5.
- **Consistencia** — ¿coherente con el historial?
- **Seguridad** — ¿evita promesas/riesgos?
- **Cobertura** — ¿responde lo que preguntaron?
- **Empatía** — ¿tono adecuado al estado del interlocutor?

## Uso

El [[decisor]] aplica reglas sobre el vector (no sobre un promedio):

- Seguridad < umbral → Escalar
- Doctrina < umbral y falta política → Consultar doctrina (zona gris)
- Naturalidad < umbral → re-generación (secuenciada por el Director, pre-Decisor)

## Calibración

Los umbrales operativos **no se confían a los valores absolutos** del Evaluador: se calibran empíricamente a partir de la curva de correcciones reales (REQ-EVAL-01..03, ver [[calibracion-de-umbrales]] cuando se ingiera el Pool 2). El sistema registra por turno el perfil completo y si el borrador fue corregido.

^[docs/REQUERIMIENTOS.md §3.7, §9.10]
