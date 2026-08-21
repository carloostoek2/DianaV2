---
title: Estado del Proyecto
created: 2026-08-11
updated: 2026-08-21
type: summary
tags: [estado, operacion, riesgo]
sources: [../../docs/ESTADO-PROYECTO.md]
confidence: high
---

# Estado del Proyecto

Síntesis del 2026-08-21. Fuente canónica: `docs/ESTADO-PROYECTO.md`. Head `b592192`. El snapshot de producción (PID, filas de memoria) **no se re-midió el 21**; lo verificado en código es el repo en `b592192` y el `.env` (valores de flags).

## Qué está en código y activo

- **Fase 6 — Vínculo Lucien** ✅ **ACTIVO** (`FEATURE_LINK_ENABLED=true`), desplegada y verificada E2E (bot-to-bot DM). Ver [[vinculo-lucien]], [[spec-fase6]].
- **Destacar / Reprender** ✅ **ACTIVO** (`FEATURE_QUALITY_FEEDBACK_ENABLED=true`). Retrieval gold-first siempre activo. Ver [[calidad-feedback]], [[spec-feedback]].
- **Fase 4 — Atención general** ✅ activa (`FEATURE_GENERAL_MODE_ENABLED=true`): ciclo 30 días, pago cierra, límite 20/día. Ver [[canal-atencion]].
- **Fase 5 — Memoria VIP** ✅ completa (81 filas snapshot 2026-08-11). Ver [[memoria-vip]].
- **Evolución de agente** ✅ shadow activo (F0–F5 miden/registran, no deciden). `FEATURE_AUTONOMOUS_MODE=false`. Ver [[perfil-evolutivo]], [[trust-budget]], [[detector-emocional]].
- **Eventos temporales** ✅ en código, **sin flag** (siempre cableados). Ver [[eventos-temporales]].
- **Menú de la dueña** ✅ A1–A13 cerrados. Ver [[superficie-admin]].

## Datos

- Repo Alembic: head **029**. Cadena 027 ephemeral → 028 link → 029 quality.
- Producción: último apply verificado = **026** (2026-08-11). 027–029 **SIN VERIFICAR**.
- El bot sigue 100 % supervisado: la **doble puerta de autoenvío está cableada** (pipeline de envío autónomo en `turn_orchestrator.py` ~304/2549, `recontact_service.py` ~209) **pero deshabilitada** por el kill-switch L1 (`FEATURE_AUTONOMOUS_MODE=false`). Nada se autoenvía.

## Pendientes reales (2026-08-21)

- **AUTH-03** — Tope configurable de VIPs: no implementado.
- **AUTH-07** — Modo observación silenciosa de chats no-VIP: no implementado.
- **GAP-11** — Generalización explícita al crear políticas: **parcial** (el campo `generalization` existe y se persiste; `doctrine.py` usa el mismo texto para generalization y rule sin preguntar el alcance).
- **REE-02 / COG-15** — Recontacto con pipeline reducido: no implementado (plantillas fijas `{nombre}`/`{producto}`).
- **MODE-09** — Feedback post-send autónomo dedicado: no implementado.
- **ADM-03** — Cambio de LLM en caliente: no implementado.
- **Autoenvío (doble puerta)** — deshabilitado: `FEATURE_AUTONOMOUS_MODE=false`.
- **Cola durable `synthesis_queue`** para síntesis de perfiles: no implementada (hoy guard en memoria).
- **Ficha de perfil EA-06** con historial de versiones (`vip_profile_history`): no implementada.
- **Fase 4 de evolución de agente (iniciativa contextual)**: diferida por decisión de producto.
- **Migraciones 027–029 en producción**: apply sin verificar (operativo).
- **Deuda técnica de privacidad**: masking PII previo al envío al LLM, retención/modelo local y acuerdo de procesamiento con el proveedor, recalibración del umbral de dedup 0.85 tras uso real.

^[docs/ESTADO-PROYECTO.md]
