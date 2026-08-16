---
title: Calidad Feedback
created: 2026-08-16
updated: 2026-08-16
type: concept
tags: [aprendizaje, flujo, operacion]
sources: [../../docs/SPEC-FEEDBACK.md, ../../docs/UX.md, ../../src/diana/application/admin_service.py]
confidence: high
---

# Calidad Feedback (Destacar / Reprender)

Dos palancas extra en el borrador VIP, más allá de Aprobar / Corregir / Escalar: **Destacar** una respuesta que sí hay que repetir, y **Reprender** una que no.

El flag `FEATURE_QUALITY_FEEDBACK_ENABLED` (env `feature_quality_feedback_enabled`) está **apagado por defecto**. Con el flag OFF los botones no aparecen y Aprobar/Corregir/Escalar no cambia. El retrieval gold-first y el filtro `vip_id` sí están en el esquema (migración `029_feedback_quality`) aunque el flag esté OFF — no escriben filas nuevas sin los botones.

## Estado actual

Solo borradores **VIP** (`approval.vip_id` presente). Canal [[canal-atencion]] se bloquea antes de enviar (`AtencionPromoteBlocked`, REQ-ATN-13). Sandbox entrega el mensaje pero **no** persiste gold ni lección (`should_persist=false`).

### Destacar

1. La dueña toca Destacar. **Todavía no se envía.**
2. Elige **🌍 General** (`vip_id` NULL) o **👤 Este VIP** (`vip_id` del turno). Volver restaura el teclado del borrador.
3. Entonces se aprueba (misma entrega que Aprobar) y se inserta un `Example` con `quality='gold'`, `draft_text == corrected_text`. **No** pasa por la cola de `staging_candidates`.

### Reprender (entrega ya, combo solo promociona)

1. Toca Reprender y escribe el texto corregido.
2. Ese texto **se entrega al VIP en ese momento** (`handle_correct_with_candidate`). Queda un candidato interno.
3. El combo posterior es **solo promoción** (no reenvía):

   - **Regla dura** → `promote_to_policy` (trigger recortado del texto del VIP, `rule` = texto de la dueña, `scope='all'`, `vip_id` según alcance).
   - **No repetir** → `promote_to_counter_example` (`is_counter_example=True`).

4. Si el VIP escribe de nuevo, el combo se cancela. El mensaje ya enviado no se revierte. Un combo huérfano o vencido no vuelve a entregar (fail-closed).

La dueña elige severidad y alcance caso por caso. No hay heurística automática (FB-01). Superficie: [[superficie-admin]].

## Bancos: gold-first y alcance VIP

| Columna | Dónde | Semántica |
|---|---|---|
| `examples.quality` | `standard` (default) / `gold` | Un gold sobre el umbral de similitud **siempre** ordena antes que un standard más parecido. |
| `examples.vip_id` / `policies.vip_id` | `NULL` = global | VIP ve `(vip_id IS NULL) OR (vip_id = este)`. Atención ve **solo** globales. Eje distinto de `policies.scope` (canal). |

El [[aprendizaje-post-turno]] de Corregir sigue igual: candidato `pending` y la dueña confirma en staging. Destacar/Reprender no usan esa cola de revisión. Los contraejemplos ya no se muestrean al 10%: si hay match sobre el umbral, se incluyen siempre.

Anti-contaminación Memoria ↔ Ejemplos se mantiene ([[anti-contaminacion]]). Atención jamás entra al banco VIP.

## Preguntas abiertas

- No hay Destacar/Reprender retroactivo sobre historial (`/traza`).
- Editar a mano el `trigger` autogenerado de una política-reprimenda depende del menú de políticas existente ([[superficie-admin]] → Personalidad), no de este flujo.
- No está enganchado al [[trust-budget]].

Contrato de diseño: [[spec-feedback]].
