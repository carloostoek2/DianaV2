---
title: Trust Budget
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [decision, aprendizaje, modo, riesgo]
sources: [../../docs/SPEC-EVOLUCION-AGENTE.md]
confidence: high
---

# Trust Budget

Presupuesto de confianza por VIP y por categoría de turno (EA-01). Es la **fuente única de la decisión conductual**: reemplaza la habilitación global por VIP del `AutonomousModeService`, que queda como infraestructura (master switch + umbrales de evaluación).

- Tabla: `vip_trust_budget` — `vip_id`, `turn_category`, `trust_score` (0..1), `correction_count`, `autonomous_count`, `last_correction_at`.
- Categorías de turno (de `turn_category_log`): `phatic` | `informational` | `emotional` | `sensitive`.

## Cálculo (asimétrico por diseño, SPEC-EVOLUCION-AGENTE §5.1)

```
si autonomo_sin_correccion: trust_score += incremento_pequeño
si owner_corrige:           trust_score -= decremento_mayor; correction_count += 1
```

Arranca en un valor bajo por defecto. El **castigo pesa más que el premio**: el sistema es conservador por diseño. Se actualiza **solo por eventos** (correcciones / autónomos sin corrección) — la calibración LLM jamás lo toca.

## Doble puerta del autoenvío (EA-01)

```
autoenviar = (trust_score[categoria] >= umbral) AND (evaluacion del turno >= minimos del Decider)
```

## Reglas

- **EA-03 (regla dura):** la categoría `sensitive` nunca entra en autonomía, sin importar el trust_score — siempre aprobación del owner.
- **Fase 2 (carril rápido fático):** para turnos `phatic`, 3 filtros baratos antes de autoenviar: (1) clasificador seguro, (2) sin trigger forbidden, (3) chequeo de seguridad del borrador generado (EA-02). El trust budget para esa categoría debe superar el umbral (arranque conservador, ej. 0.9).
- **Fase 5.2:** para turnos de pipeline completo, alta dispersión entre las 7 dimensiones del [[perfil-evaluacion-multidimensional]] → tratar como baja confianza y no autoenviar aunque el trust_score sea alto.
- El owner ve la sección "Confianza" en la ficha del VIP (EA-06): score por categoría, tendencia y últimas correcciones.

Relacionado: [[decisor]], [[modos-de-operacion]], [[spec-evolucion-agente]].

^[docs/SPEC-EVOLUCION-AGENTE.md §5, EA-01..03]
