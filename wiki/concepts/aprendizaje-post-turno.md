---
title: Aprendizaje Post-Turno
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [aprendizaje, contrato, flujo]
sources: [../../docs/REQUERIMIENTOS.md, ../../AGENTS.md]
confidence: high
---

# Aprendizaje Post-Turno

El aprendizaje ocurre **siempre después de terminar el turno**, nunca durante el pipeline de decisión (REQ-TRN-05, BR-11). Es un proceso separado del pipeline cognitivo (AGENTS.md: "El aprendizaje es siempre post-turno y controlado").

## Fuentes de señal (REQ-TRN-06, con calidad distinta)

1. **Aprobación sin cambios** → señal fuerte positiva.
2. **Corrección de la dueña** → la más valiosa: se guarda el par `(borrador_original, corrección_final)` como **contraejemplo**.
3. **Resolución de zona gris** → se convierte en Política estructurada, no en few-shot.
4. **Turnos observados** (dueña responde a mano) → señal ruidosa, menor confianza por defecto.

## Staging Area (REQ-TRN-07, BR-13, REQ-NFR-16)

Toda corrección entra primero a una zona intermedia de candidatos (tabla `staging_candidates`). Solo pasa al banco vivo de ejemplos tras **confirmación explícita** de la dueña (botón "usar como ejemplo"). **Nunca se promueve automáticamente.**

## Reglas de oro

- El banco de Ejemplos y la Memoria por VIP tienen reglas de acceso separadas ([[anti-contaminacion]]).
- El retrieval de few-shots prioriza: similitud semántica → recencia → limpieza (aprobados sin corrección antes que correcciones); puede incluir un contraejemplo explícito junto al positivo.
- La extracción de hechos nuevos (REQ-MEM-02) clasifica en el tipo correcto de conocimiento; nada entra sin revisión cuando corresponde.

^[docs/REQUERIMIENTOS.md §9.9, AGENTS.md §1]
