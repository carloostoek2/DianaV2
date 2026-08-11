---
title: Estado del Proyecto
created: 2026-08-11
updated: 2026-08-11
type: summary
tags: [estado, operacion, riesgo]
sources: [../../docs/ESTADO-PROYECTO.md]
confidence: high
---

# Estado del Proyecto

Estado verificado el 2026-08-11: bot en producción (tmux prod, polling activo), migraciones al día (head `026`), branch main al día.

## Qué está activo

- **Fase 4 — Atención general** ✅ activa (`FEATURE_GENERAL_MODE_ENABLED=true`): ciclo por chat de **30 días lineales** (trigger "Quiero más información 🔥" → promo sin LLM → chat habilitado; **el pago cierra el ciclo** y la entrega es manual de la dueña). Límite 20 msgs/día (CDMX), fail-open si falla la DB. Ver [[canal-atencion]].
- **Fase 5 — Perfil de memoria por VIP** ✅ completa (4 pools): backfill con cola durable + timer 1h (protección de cuenta), post-turno incremental best-effort, aprobación de sensibles por DM (`/memoria`), ficha con sección 🧠 Memoria. En producción: **81 filas** en `memories` (52 auto, 18 discarded, 11 approved), 10 backfills. Ver [[memoria-vip]].
- **Evolución de agente (pool `evo-agente`)** ✅ **shadow activo en producción** (migraciones 024-026 aplicadas): los hooks **miden y registran, no cambian decisiones** — el bot sigue 100 % supervisado (`FEATURE_AUTONOMOUS_MODE=false`). Datos shadow reales (2026-08-11): `turn_category_log` 48, `emotional_signal_log` 29, `vip_profile` 9 (versiones hasta v7), `vip_trust_budget` 2 (fático, score ~0.18). Ver [[perfil-evolutivo]], [[trust-budget]], [[detector-emocional]].

## Flags en producción (modo medición)

`FEATURE_EMOTIONAL_DETECTOR_ENABLED`, `FEATURE_PROFILE_SYNTHESIS_ENABLED`, `FEATURE_PHATIC_AUTONOMY`, `FEATURE_MOOD_ENGINE`, `FEATURE_TRUST_BUDGET` = **true** (solo miden); `FEATURE_AUTONOMOUS_MODE=false`. Ver [[feature-flags]].

## Calidad

Suite unit **2441 verdes** + e2e (Docker) verdes; purity gates 3/3. Auditoría de 161 requisitos: ver [[informe-auditoria]].

## Pendientes

- **Fase 5 real de evolución (cablear doble puerta):** `can_autonomous` sin call-sites de envío; requiere confianza por categoría + `recent_trend` confiable.
- Cola durable `synthesis_queue` (hoy guard en memoria); ficha perfil EA-06 completa (historial de versiones); `.env.example` con flags nuevos.
- Fase 4 (iniciativa contextual) diferida por decisión del usuario.
- Drift de estilo: score 0.25 vs umbral 0.1 (esperado tras cambio de persona; se re-ancla en ~4 semanas).
- Privacidad backfill: opt-out por VIP, masking PII, retención, acuerdo con proveedor (documentado en [[spec-fase5]]).

^[docs/ESTADO-PROYECTO.md]
