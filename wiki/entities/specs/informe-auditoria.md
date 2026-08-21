---
title: Informe de Auditoría
created: 2026-08-11
updated: 2026-08-21
type: summary
tags: [riesgo, estado, requisito]
sources: [../../docs/INFORME_AUDITORIA.md]
confidence: high
---

# Informe de Auditoría

Auditoría de alineamiento código ↔ requerimientos (julio 2026, re-verificada 2026-08-21 contra el código en `b592192`): **161 requisitos revisados** (P0/P1/P2), base [[spec-requerimientos]].

## Resumen numérico

| Estado | Cantidad |
|---|---|
| ✅ Cumple | 143 |
| ⚠️ Observación menor | 11 |
| 🔍 No implementado (P2 / fuera de alcance) | 5 |
| ❌ No implementado (P1) | **2** |

Reclasificados a CUMPLE en la re-verificación: **MODE-05** (regenerar variantes — `DraftVariantService.regenerate` + callbacks regen/prev/next), **MET-04** (drift detector con baseline — `drift_alert_threshold: 0.1`, `baseline_weeks: 4`), **MEM-02** (extracción post-turno — `extract_post_turn` → `insert_facts` cableada) y **TRN-06** (fuentes de señal de aprendizaje — `strong_signal_heuristics` + `profile_synthesis_trigger_service`).

## Los 2 no implementados (P1)

1. **AUTH-03** — No hay tope configurable de VIPs (el sistema intentaría procesar cualquier cantidad).
2. **AUTH-07** — Modo observación de chats no-VIP sin responder no existe.

## Observaciones relevantes

- **GAP-11 (P1)** — Al resolver zona gris no se pide generalización explícita a la dueña; hoy se usa el texto tal cual como `generalization` y `rule` (parcial: el campo existe y se persiste). Ver [[zona-gris-y-politicas]].
- **MODE-09 (P1)** — Sin feedback post-send autónomo dedicado.
- **ADM-03 (P1)** — Sin cambio de LLM en caliente (overrides por `system_config` solo para `phatic_classifier`, `profile_synthesis`, `trust_budget`).
- **COG-16** — El cortocircuito de escalación vive en un middleware de Telegram, no en el Director como dice el diseño (funciona, capa distinta).
- **REE-02 / COG-15 (P2)** — El recontacto usa plantillas fijas, no el pipeline reducido con personalización.
- **EVAL-04 (P2)** — Sin visualización de calibración por dimensión (el resumen semanal muestra tasa global y drift).
- **GAP-08 (P2)** — Sin comando dedicado para listar/desactivar políticas de doctrina desde admin.

## Fortalezas confirmadas

Pipeline cognitivo completo con Director determinista, evaluación 7D con prioridades correctas, Behavior Engine separado, zona gris completa con expiración 24h, 5 tipos de conocimiento separados con anti-contaminación, persistencia total en PostgreSQL con secretos fuera del repo, admin completa.

^[docs/INFORME_AUDITORIA.md]
