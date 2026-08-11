---
title: Feature Flags
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [operacion, decision, contrato]
sources: [../../AGENTS.md, ../../docs/SPEC-EVOLUCION-AGENTE.md]
confidence: high
---

# Feature Flags

**Regla de oro (AGENTS.md §1):** todos los nuevos comportamientos de Fase 3 están envueltos en feature flags. Si un flag está desactivado, el sistema se comporta como en Fase 2.

## Flags principales

- `FEATURE_AUTONOMOUS_MODE` — envío autónomo (flujo 4.8)
- `FEATURE_RECONTACT_ENABLED` — recontacto por silencio (flujo 4.9)
- `FEATURE_PROMO_ENABLED` — promo no-VIP por trigger exacto (flujo 4.10)
- `FEATURE_CALIBRATION_ENABLED` — calibración automática de umbrales (flujo 4.11)
- `FEATURE_ADVANCED_BEHAVIOR` — mensajes divididos y quirks humanos (flujo 4.12)

Y de Fase 2: `FEATURE_MEMORY_ENABLED`, `FEATURE_GRAY_ZONE_ENABLED`, `FEATURE_STAGING_ENABLED`, `FEATURE_SANDBOX_ENABLED`.

## Justificación

- Permite **rollback sin redeploy** (AGENTS.md §7).
- Todos los nuevos comportamientos deben vivir en `if settings.FEATURE_XXX_ENABLED:` (AGENTS.md §5.6).
- En el checklist de revisión: "¿Los nuevos flujos están envueltos en feature flags?" (AGENTS.md §6).

Nota de estado (2026-08): la calibración está desactivada en producción (`FEATURE_CALIBRATION_ENABLED=false`); el resto de flags en medición. Ver [[estado-del-proyecto]] cuando se ingiera el Pool 5.

^[AGENTS.md §1, §5.6]
