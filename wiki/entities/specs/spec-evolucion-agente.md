---
title: SPEC-EVOLUCION-AGENTE.md
created: 2026-08-11
updated: 2026-08-21
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
- **Fase 4 — Iniciativa contextual:** recontacto prioriza `recent_trend` + hechos con `follow_up` (campo aditivo opcional). **No implementada (diferida por decisión de producto).**
- **Fase 5 — Trust budget:** [[trust-budget]] activo.

## Estado (2026-08-21) — shadow mode activo

La capa de evolución de agente está desplegada en **shadow mode (modo medición)** en producción: los flags F0–F5 están `true` y **miden/registran sin cambiar decisiones** ([[perfil-evolutivo]], [[trust-budget]], [[detector-emocional]]). El bot sigue 100 % supervisado.

- Migraciones 024–026 aplicadas en producción; head del repo 029.
- **F4 (iniciativa contextual): no implementada** (diferida).
- **Autoenvío deshabilitado:** `FEATURE_AUTONOMOUS_MODE=false`. La doble puerta (trust budget + evaluación del Decider + filtros EA-02) está **cableada tras el flag**, pero el kill-switch L1 la desactiva — nada se autoenvía.
- Pendientes reales: cola durable `synthesis_queue` para síntesis de perfiles (hoy guard en memoria) y ficha de perfil EA-06 completa con historial de versiones (`vip_profile_history`).

^[docs/SPEC-EVOLUCION-AGENTE.md]
