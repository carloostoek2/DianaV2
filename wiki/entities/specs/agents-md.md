---
title: AGENTS.md
created: 2026-08-11
updated: 2026-08-21
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

## Decisor (orden de prioridades alineado 2026-08-21)

El orden exacto que evalúa el [[decisor]] (coincide con `src/diana/cognitive/decider.py`):

| Prioridad | Condición | Acción |
|---|---|---|
| 1 | `perfil.seguridad` < umbral | Escalar |
| 2 | `needs_policy` Y retrieval vacío Y `FEATURE_GRAY_ZONE_ENABLED` | Consultar doctrina |
| 3 | `risk == "alto"` | Escalar (risk_high) |
| 4 | `emotion == "molesta"` | Escalar (frustracion_directa) |
| 5 | (pre-Decisor) `naturalidad` < umbral → Director re-genera 1× | no-op del Decisor |
| 6 | Modo autónomo activo Y umbrales superados | Enviar |
| 7 | Ninguna de las anteriores | Aprobar |

Cambio notable (2026-08-21): **`risk_high` (prioridad 3) se evalúa antes que `frustracion_directa` (prioridad 4)**. Si ambas aplican, la acción es Escalar y el `reason` queda `risk_high` (la severidad semántica gana; visible en `/traza`). `molesta` sola escala sin esperar acumulación de risk.

## Tabla de docs (relación §9)

La sección §9 etiqueta cada SPEC como diseño de fase y añade las piezas recientes:

| Documento | Qué define |
|---|---|
| SPEC-1.1.md v1.5 | Diseño de Fase 1 (MVP supervisado) |
| SPEC-FASE2.md | Diseño de Fase 2 (MVP+) |
| SPEC-FASE3.md | Diseño de Fase 3 (Producto Completo) |
| SPEC-FASE4.md | Atención general (canal no-VIP) |
| SPEC-FASE5.md | Perfil de memoria por VIP |
| SPEC-FASE6.md | Vínculo Lucien→Diana (migración real 028) |
| SPEC-FEEDBACK.md | Destacar/Reprender y bancos gold/vip (migración real 029) |
| ARCHITECTURE.md | Arquitectura consolidada del sistema actual (entrada técnica única) |

## Regla de evolución

Cualquier cambio de límite de módulo o flujo canónico se documenta **primero aquí y después en el código**. Cambios solo de implementación interna no requieren modificar este archivo.

^[AGENTS.md]
