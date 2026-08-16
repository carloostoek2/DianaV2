---
title: Aprendizaje Post-Turno
created: 2026-08-11
updated: 2026-08-16
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

La corrección clásica entra primero a una zona intermedia (`staging_candidates`) y solo pasa al banco vivo tras **confirmación explícita** de la dueña. **Nunca se promueve solo.**

Excepción controlada ([[calidad-feedback]]): **Destacar** inserta un ejemplo `quality=gold` **sin** candidato de staging, porque la dueña ya confirmó. **Reprender** entrega el texto al VIP al instante y el combo posterior promociona el contraejemplo (tampoco espera la cola de revisión). Atención no puede destacar ni reprender.

## Reglas de oro

- El banco de Ejemplos y la Memoria por VIP tienen reglas de acceso separadas ([[anti-contaminacion]]).
- El retrieval de few-shots es **gold-first** (destacados antes que standard) + similitud; si hay match, siempre anexa 1 contraejemplo. Ya no hay sorteo al 10 %.
- Un ejemplo o una política puede ser global (`vip_id` vacío) o de un VIP. Atención solo ve globales.
- La extracción de hechos nuevos (REQ-MEM-02) clasifica en el tipo correcto de conocimiento; nada entra sin revisión cuando corresponde.

^[docs/REQUERIMIENTOS.md §9.9, AGENTS.md §1]
