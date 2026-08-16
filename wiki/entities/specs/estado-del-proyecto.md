---
title: Estado del Proyecto
created: 2026-08-11
updated: 2026-08-16
type: summary
tags: [estado, operacion, riesgo]
sources: [../../docs/ESTADO-PROYECTO.md]
confidence: high
---

# Estado del Proyecto

Síntesis del 2026-08-16. Fuente canónica: `docs/ESTADO-PROYECTO.md`. El snapshot de producción (PID, filas de memoria, apply de migraciones) **no se re-midió**; lo verificado en código es el repo en `a80e0d9`.

## Qué está en código y listo para operar

- **Fase 4 — Atención general** ✅ (`FEATURE_GENERAL_MODE_ENABLED`): ciclo 30 días, pago cierra, límite 20/día. Ver [[canal-atencion]].
- **Fase 5 — Memoria VIP** ✅ completa. Ver [[memoria-vip]].
- **Evolución de agente** ✅ shadow (mide, no decide). `FEATURE_AUTONOMOUS_MODE=false`. Ver [[perfil-evolutivo]], [[trust-budget]], [[detector-emocional]].
- **Fase 6 — Vínculo Lucien** ✅ en código, **flag OFF**. Ver [[vinculo-lucien]], [[spec-fase6]].
- **Destacar / Reprender** ✅ en código, **flag OFF**. Retrieval gold-first ya activo. Ver [[calidad-feedback]], [[spec-feedback]].
- **Eventos temporales** ✅ en código, **sin flag** (siempre cableados). Ver [[eventos-temporales]].
- **Menú de la dueña** ✅ A1–A13 cerrados. Ver [[superficie-admin]].

## Datos

- Repo Alembic: head **029**. Cadena 027 ephemeral → 028 link → 029 quality.
- Producción: último apply verificado = **026** (2026-08-11). 027–029 **SIN VERIFICAR**.
- 34 tablas en metadata. Ver [[esquema-conocimiento]], [[esquema-fase6]].

## Pendientes de decisión / ops

- Encender `FEATURE_LINK_ENABLED` solo después del spike Lucien↔Diana en deploy real.
- Encender `FEATURE_QUALITY_FEEDBACK_ENABLED` cuando la dueña quiera Destacar/Reprender.
- Aplicar 027→028→029 en producción **antes** de depender de esos tres.
- Doble puerta de envío autónomo sigue sin cablear.

^[docs/ESTADO-PROYECTO.md]
