---
title: Decisor
created: 2026-08-11
updated: 2026-08-16
type: concept
tags: [arquitectura, modulo, contrato]
sources: [../../docs/REQUERIMIENTOS.md, ../../AGENTS.md, ../../docs/SPEC-1.1.md, ../../src/diana/cognitive/decider.py]
confidence: high
---

# Decisor

Componente determinista que decide la acción del turno. Trabaja sobre el vector del [[perfil-evaluacion-multidimensional]] + las restricciones de modo (BR-12: los modos son restricciones externas; el Decisor propone, los modos filtran).

- **Pregunta que responde:** ¿Qué acción tomar?
- **Acciones posibles:** Enviar, Aprobar, Escalar, Consultar doctrina. (Regenerar es residual; el Decisor no la emite.)

## Orden de prioridades (contrato de **acciones**)

1. `seguridad < umbral` → **Escalar** (`safety_below_threshold`)
2. `needs_policy == true` + sin política + zona gris activa → **Consultar doctrina** (`doctrine_not_found`)
3. `risk == "alto"` → **Escalar** (`risk_high`)
4. `emotion == "molesta"` → **Escalar** (`frustracion_directa`)
5. Naturalidad baja → re-generación **ya ocurrió upstream** (pre-Decisor; el Decisor no emite regenerate)
6. Flag `feature_autonomous_mode` Y umbrales `*_min` superados → **Enviar** (`autonomous_ok`)
7. Flag autónomo activo pero algún `*_min` no superado → **Aprobar** (`autonomous_below_threshold`)
8. Si no → **Aprobar** (`ok_for_human_review`)

`mode` es residual de auditoría: **no** habilita ni bloquea el send. El único candado de envío es `feature_autonomous_mode`. El Director pasa `mode="supervised"` a propósito.

## Risk vs frustración (live, 2026-08-16)

El código evalúa `risk=alto` **antes** que `emotion=molesta`. Si un turno cumple ambas, la acción sigue siendo **Escalar** y el `reason` es `risk_high` (la señal más grave y accionable en `/traza`). AGENTS.md §4.1 aún lista 2b antes que 3; es drift de documento, no de acciones.

La redraft de naturalidad es secuenciación del [[director-cognitivo]] (1×), no un paso de esta matriz.

## Justificaciones registradas

- **Zona gris antes que risk=alto (BR-02 modificado):** la falta de doctrina es causa tratable; resolverla elimina escalaciones futuras. La escalación por risk=alto solo se ejecuta cuando no hay doctrina pendiente.
- **Frustración directa:** `emotion=molesta` escala sin esperar acumulación de riesgo; se evalúa después de zona gris y de risk alto, y antes de send autónomo.

## Reglas de fase

- **Fase 1 (supervisado):** solo approve o escalate. Enviar, consultar doctrina y regenerar deshabilitados.
- **Fase 3+:** send autónomo al final del orden (solo si el flag autónomo está activo y los umbrales se superan). Los hooks de evolución de agente (trust, fático, mood) son **shadow-only** en application: no alteran esta matriz.

^[AGENTS.md §4.1, docs/REQUERIMIENTOS.md §3.7, src/diana/cognitive/decider.py]
