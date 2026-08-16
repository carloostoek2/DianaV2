---
title: SPEC-FEEDBACK.md
created: 2026-08-16
updated: 2026-08-16
type: entity
tags: [spec, aprendizaje, operacion]
sources: [../../docs/SPEC-FEEDBACK.md]
confidence: high
---

# SPEC-FEEDBACK.md

Síntesis del spec de implementación **Feedback de calidad + fix zona gris** (`docs/SPEC-FEEDBACK.md` v1.0). Esta página no copia el spec: apunta al archivo y registra qué quedó vivo en código.

**Estado (2026-08-16, `main` `a80e0d9`):** Fase 0 y Fases 1–3 implementadas. El flag de escritura `FEATURE_QUALITY_FEEDBACK_ENABLED` sigue en **default OFF**.

## Qué cubre el spec

1. **Fase 0 (crítica, aislada)** — si falla el DM de `consult_doctrine` en el path **VIP**, no dejar al VIP congelado 24 h. Mismo patrón F6 que atención: `discard_and_close` + demote a `approve` con `reason=vip_doctrine_notify_failed`. Hoy está en `turn_orchestrator.py` (rama `else` de consult_doctrine). Ver [[zona-gris-y-politicas]].
2. **Feedback de calidad (FB-01..FB-06)** — Destacar / Reprender, gold-first, contraejemplo determinista, `vip_id` nuevo (no reutilizar `policies.scope`), promoción inmediata sin cola de revisión de Corregir, todo detrás del flag. Producto: [[calidad-feedback]].

## Desvíos respecto al texto del spec

El spec se escribió **antes** de implementar. Lo que el código hace hoy:

| Spec | Código |
|---|---|
| Migración Alembic **027** | **029_feedback_quality** (027 = eventos temporales, 028 = link) |
| Botones `⭐ Destacar` / `🚫 Reprender` | Labels `Destacar` / `Reprender` (sin emoji) |
| Reprender: capturar texto → combo → entonces resolver/entregar | El texto se **entrega al instante**; el combo `rpc:` es promote-only |
| Destacar/Reprender en el teclado genérico de drafts | Solo si hay `vip_id` (VIP). Atención excluida |
| Combo vivo si el VIP escribe de nuevo | Se cancela (`cancel_combo_for_chat`) |

FB-02/FB-03/FB-04 (retrieval gold-first, contraejemplo determinista, columna `vip_id`) están en repos + retrievers **siempre**, independientes del flag de botones.

## Dónde leer el detalle

- Texto completo, decisiones FB-01..FB-06 y el parche propuesto de Fase 0: [`docs/SPEC-FEEDBACK.md`](../../../docs/SPEC-FEEDBACK.md).
- UX de dueña: [`docs/UX.md`](../../../docs/UX.md), [[superficie-admin]].
- Límites de módulo: [[agents-md]] (Director determinista, Learning post-turno, Behavior no genera texto).

^[docs/SPEC-FEEDBACK.md]
