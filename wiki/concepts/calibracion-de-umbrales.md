---
title: Calibración de Umbrales
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [aprendizaje, decision, riesgo]
sources: [../../docs/REQUERIMIENTOS.md, ../../docs/SPEC-FASE3.md, ../../docs/SPEC-EVOLUCION-AGENTE.md]
confidence: high
---

# Calibración de Umbrales

Ajuste empírico de los umbrales del Evaluador/Decisor a partir de la tasa de corrección real (REQ-EVAL-01..03). Los valores absolutos del Evaluador no se toman al pie de la letra: se calibran contra la curva real de correcciones de la dueña.

## Mecanismo (SPEC-FASE3 §5.5)

- Job semanal (ej. domingo 3 AM) → `CalibrationService.calibrate_thresholds(window_days=30)`.
- Para cada dimensión calcula el percentil donde la tasa de corrección es baja: **supervisado = percentil 70**, **autónomo = percentil 90**.
- **Garantía de margen:** umbral autónomo >= umbral supervisado + `autonomous_margin_min` (0.05) — el autónomo siempre es más estricto.
- Actualiza `system_config` con ambos conjuntos + registro con timestamp para auditoría.
- `detect_drift()` compara el estilo actual con la línea base; si supera el umbral, alerta a la dueña (REQ-MET-04).

## El incidente que cambió la regla (2026-08)

La calibración automática calibro `safety_min` a ~0.95 a partir de correcciones → **escalaciones masivas**. Consecuencia, codificada en SPEC-EVOLUCION-AGENTE v1.2:

> Los umbrales de seguridad y confianza son **constantes fijas con override manual** vía `system_config`, **nunca auto-calibrados por LLM**. La recalibración automática de gates de seguridad/confianza queda prohibida.

La calibración automática quedó **desactivada** en producción (`FEATURE_CALIBRATION_ENABLED=false`); umbrales en DB con valores por defecto. Al reactivarla: no calibrar gates P1 desde correcciones y recomputar la línea base de deriva.

## Umbrales de arranque en frío (SPEC-FASE3 §4.2)

| Dimensión | Supervisado | Autónomo |
|---|---|---|
| safety_min | 0.5 | 0.9 |
| doctrine_min | 0.4 | 0.8 |
| naturalness_min | 0.5 | 0.7 |

Relacionado: [[perfil-evaluacion-multidimensional]], [[decisor]], [[feature-flags]].

^[docs/SPEC-FASE3.md §5.5, docs/SPEC-EVOLUCION-AGENTE.md §0]
