---
title: AGENTS.md
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [spec, contrato, operacion]
sources: [../../AGENTS.md]
confidence: high
---

# AGENTS.md

Documento de operación para agentes de desarrollo (v1.3 — Fase 3 Producto Completo). Define **límites duros de módulo y flujos canónicos que ningún agente (humano o IA) puede violar** al modificar el código.

## Contenido clave

- **§0 Comunicación con el usuario:** reglas de [[comunicacion-con-producto]] y español neutro obligatorio.
- **§1 Propósito y principios rectores:** los 7 innegociables (Director determinista, una pregunta por componente, Behavior fuera de la cognición, aprendizaje post-turno, anti-contaminación, decisión reconstruible, Turn Coordinator serializa).
- **§2 Mapa de módulos y límites duros:** capas, preguntas, qué puede/nunca puede hacer cada módulo; reglas de dependencia unidireccionales y prohibiciones explícitas.
- **§3 Flujos canónicos por fase:** 4.1-4.12 (turno normal, cortocircuito, cancelación, memoria, zona gris, staging, sandbox, autónomo, recontacto, promo, calibración, behavior avanzado).
- **§4 Contratos críticos:** orden de prioridades del [[decisor]], BehaviorEngine, RecontactService, PromoService, CalibrationService.
- **§5 Reglas operativas por feature** y §6 checklist de revisión para PRs.
- **§7 Prohibiciones explícitas** con su razón; §8 cómo evolucionar el documento; §9 relación con los otros docs.

## Regla de evolución

Cualquier cambio de límite de módulo o flujo canónico se documenta **primero aquí y después en el código**. Cambios solo de implementación interna no requieren modificar este archivo.

^[AGENTS.md]
