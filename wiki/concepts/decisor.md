---
title: Decisor
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [arquitectura, modulo, contrato]
sources: [../../docs/REQUERIMIENTOS.md, ../../AGENTS.md, ../../docs/SPEC-1.1.md]
confidence: high
---

# Decisor

Componente determinista que decide la acción del turno. Trabaja sobre el vector del [[perfil-evaluacion-multidimensional]] + las restricciones de modo (BR-12: los modos son restricciones externas; el Decisor propone, los modos filtran).

- **Pregunta que responde:** ¿Qué acción tomar?
- **Acciones posibles:** Enviar, Aprobar, Escalar, Consultar doctrina, (Regenerar es residual).

## Orden de prioridades (contrato crítico, AGENTS.md §4.1)

1. `seguridad < umbral` → **Escalar**
2. `needs_policy == true` + sin política + zona gris activa → **Consultar doctrina**
2b. `emotion == "molesta"` → **Escalar** (frustración directa)
3. `risk == "alto"` → **Escalar**
4. Naturalidad baja → re-generación **ya ocurrió upstream** (pre-Decisor; el Decisor no emite regenerate)
5. Modo autónomo activo Y umbrales superados → **Enviar**
6. Ninguna de las anteriores → **Aprobar**

## Justificaciones registradas

- **Zona gris antes que risk=alto (BR-02 modificado):** la falta de doctrina es causa tratable; resolverla elimina escalaciones futuras. La escalación por risk=alto solo se ejecuta cuando no hay doctrina pendiente.
- **Frustración directa (2b):** `emotion=molesta` escala sin esperar acumulación de riesgo; se evalúa después de zona gris (doctrina tratable gana) y antes de risk alto / send autónomo.

## Reglas de fase

- **Fase 1 (supervisado):** solo approve o escalate. Enviar, consultar doctrina y regenerar deshabilitados.
- **Fase 3+:** send autónomo al final del orden (solo si el modo autónomo está activo y los umbrales se superan).

^[AGENTS.md §4.1, docs/REQUERIMIENTOS.md §3.7, docs/SPEC-1.1.md §4.8]
