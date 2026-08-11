---
title: SPEC-FASE3.md
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [spec, modo, operacion, aprendizaje]
sources: [../../docs/SPEC-FASE3.md]
confidence: high
---

# SPEC-FASE3.md

Contrato de diseño e implementación de la **Fase 3 (Producto Completo)**: Autonomía, Proactividad y Métricas (v3.1, revisión post-review; base: [[spec-1-1]], [[spec-fase2]], Anexo T).

## Capacidades que completa

1. **Modo autónomo** — envío sin aprobación previa sujeto a umbrales y config por VIP (extensión del [[decisor]]: prioridades 5-6; ver [[modos-de-operacion]]).
2. **Recontacto por silencio** — pipeline reducido con exclusión de estados bloqueantes (`is_blocked()`: pausa, congelación, aprobación pendiente, sandbox; REQ-REE-03, BR-05).
3. **Promo no-VIP** — trigger exacto, secuencia multi-mensaje **sin LLM**, diferenciación primer envío/reenvío (`promo.repeat_days` = 30) y trazabilidad (`promo_executions`).
4. **[[calibracion-de-umbrales]] automática** — job semanal; garantía de margen: autónomo >= supervisado + 0.05.
5. **Behavior Engine avanzado** — mensajes divididos (`split_chars` 4096), quirks humanos, secuencias (`deliver_with_sequence`).
6. **Métricas agregadas** — `learning_metrics`: tasa de aprobación sin corrección, repetición de zona gris, falsos positivos de escalación, `style_drift_score`, `autonomous_send_rate`.

## Umbrales iniciales (arranque en frío)

- Autónomos: `safety_min=0.9`, `doctrine_min=0.8`, `naturalness_min=0.7`.
- Supervisados: `safety_min=0.5`, `doctrine_min=0.4`, `naturalness_min=0.5`.

## Tablas nuevas

`recontact_schedules`, `promo_triggers`, `promo_executions`, `learning_metrics.style_drift_score`.

## Hook de cancelación (BR-07)

El TurnCoordinator llama `RecontactService.cancel_recontact(vip_id)` cuando el VIP escribe — el recontacto programado se cancela si hay actividad.

## Nota de activación

Recomendado activar flags uno a uno: recontacto → promo → calibración → autónomo → behavior avanzado (ver [[feature-flags]]).

^[docs/SPEC-FASE3.md]
