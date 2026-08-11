---
title: SPEC-EVOLUCION-AGENTE.md
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [spec, decision, aprendizaje, riesgo]
sources: [../../docs/SPEC-EVOLUCION-AGENTE.md]
confidence: high
---

# SPEC-EVOLUCION-AGENTE.md

Contrato de implementación de la **Evolución de agente** (v1.2): llevar a Diana de "bot con memoria consultada" a "agente con perfil evolutivo, autonomía calibrada por confianza y personalidad con textura (mood)".

**Principio guía:** cada pieza nueva detrás de feature flag y con traza auditable — nada se libera sin poder revertirse.

**Lección incorporada (2026-08-06):** los umbrales de seguridad/confianza son **constantes fijas con override manual** vía `system_config`, **nunca auto-calibrados por LLM**. Precedente: el incidente de calibración (safety_min calibrado a 0.95 por correcciones → escalaciones masivas). Ver [[calibracion-de-umbrales]].

## Decisiones de diseño aprobadas (EA-01..06)

- **EA-01** — El [[trust-budget]] es la **fuente única de la decisión conductual** por (VIP, categoría); autoenvío = doble puerta: `trust_score >= umbral` Y evaluación del turno >= mínimos del Decider. Se actualiza solo por eventos (correcciones/autónomos), jamás por calibración LLM.
- **EA-02** — Carril rápido con 3 filtros baratos: clasificador seguro de fático, sin trigger forbidden, chequeo de seguridad del borrador.
- **EA-03** — Categoría `sensitive` = regla dura: siempre aprobación del owner.
- **EA-04** — `feedback_signals`: proxy por categoría + LLM de síntesis filtra relevancia (sin esquema de clasificación extra).
- **EA-05** — Anti-contaminación: `stable_traits`/`sensitivities` jamás alimentan el banco de ejemplos; solo `recent_trend` y mood entran al contexto de generación.
- **EA-06** — UI admin: secciones en la ficha existente del VIP (sin comandos nuevos).

## Fases del contrato

- **Fase 0 — Fundaciones:** migraciones 024+ (`vip_profile`, `vip_profile_history`, `vip_mood_state`, `vip_trust_budget`, `turn_category_log`, `emotional_signal_log`) + [[detector-emocional]] (componente transversal).
- **Fase 1 — Resíntesis de memoria:** [[perfil-evolutivo]] (stable_traits/recent_trend/sensitivities, decaimiento, versionado, `profile_synthesis_job`).
- **Fase 2 — Autonomía fática:** clasificador de turno (phatic/informational/emotional/sensitive) + carril rápido (ver [[trust-budget]]).
- **Fase 3 — Motor de mood:** 3 ejes (juguetón-serio, cálido-distante, energía), promedio móvil con retorno a la base; matiza selección de variantes.
- **Fase 4 — Iniciativa contextual:** recontacto prioriza `recent_trend` + hechos con `follow_up` (campo aditivo opcional).
- **Fase 5 — Trust budget:** [[trust-budget]] activo.

## Orden de ejecución

Fase 0 + detector → Fase 1 y 2 en paralelo (shadow) → Fase 3 (shadow) → Fase 5 (activo cuando Fase 2 sale de shadow) → Fase 4.

## Estado (2026-08)

Fase 0 y componentes desplegados; flags en medición; pendiente la mecánica del modo shadow (3 estados, doble llave, sombra por defecto).

^[docs/SPEC-EVOLUCION-AGENTE.md]
