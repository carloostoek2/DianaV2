---
title: Feature Flags
created: 2026-08-11
updated: 2026-08-16
type: concept
tags: [operacion, decision, contrato]
sources: [../../src/diana/config/settings.py, ../../.env.example, ../../AGENTS.md]
confidence: high
---

# Feature Flags

**Regla de oro (AGENTS.md §1):** comportamientos nuevos van detrás de feature flags. Flag off = el sistema se comporta como en la fase anterior.

Runtime: pydantic `Settings` lee env `FEATURE_*` (campos `feature_*`). Default de código: **todos `false`**. Migraciones 003/006 siembran claves en `system_config`, pero `load_feature_flags` se removió; el wiring usa `settings`, no la tabla.

## Inventario (código)

### Fase 2

| Flag | Default | Efecto |
|------|---------|--------|
| `FEATURE_MEMORY_ENABLED` | false | Retrievers/extracción/backfill de memoria VIP |
| `FEATURE_GRAY_ZONE_ENABLED` | false | Consulta de doctrina / freeze |
| `FEATURE_STAGING_ENABLED` | false | Staging de correcciones |
| `FEATURE_SANDBOX_ENABLED` | false | Sandbox + FakeDelivery |

### Fase 3

| Flag | Default | Efecto |
|------|---------|--------|
| `FEATURE_AUTONOMOUS_MODE` | false | Envío autónomo (flujo 4.8). Sin esto nada se autoenvía |
| `FEATURE_RECONTACT_ENABLED` | false | Recontacto por silencio (4.9) |
| `FEATURE_PROMO_ENABLED` | false | Promo no-VIP por trigger exacto (4.10) |
| `FEATURE_CALIBRATION_ENABLED` | false | Job de calibración (4.11) |
| `FEATURE_ADVANCED_BEHAVIOR` | false | Split + quirks humanos (4.12) |
| `FEATURE_PERSONA_ADMIN_ENABLED` | false | Superficie admin de persona |

### Fase 4

| Flag | Default | Efecto |
|------|---------|--------|
| `FEATURE_GENERAL_MODE_ENABLED` | false | Canal atención no-VIP |

### Feedback de calidad (029)

| Flag | Default | Efecto |
|------|---------|--------|
| `FEATURE_QUALITY_FEEDBACK_ENABLED` | false | Escritura Destacar/Reprender. Retrieval siempre usa `quality`/`vip_id` (defaults = comportamiento pre-flag) |

No está en `.env.example`.

### Fase 6 (vínculo Lucien)

| Flag | Default | Efecto |
|------|---------|--------|
| `FEATURE_LINK_ENABLED` | false | Middleware `[LINK]` + `LinkCoordinator`. Requiere `LINK_CHAT_ID` |

### Evolución de agente (shadow)

| Flag | Default | Efecto |
|------|---------|--------|
| `FEATURE_EMOTIONAL_DETECTOR_ENABLED` | false | Detector emocional → `emotional_signal_log` |
| `FEATURE_PROFILE_SYNTHESIS_ENABLED` | false | Resíntesis → `vip_profile` + job LLM |
| `FEATURE_PHATIC_AUTONOMY` | false | Clasificador de turno → `turn_category_log` (solo medición/sombra) |
| `FEATURE_MOOD_ENGINE` | false | Motor de mood → `vip_mood_state` |
| `FEATURE_TRUST_BUDGET` | false | Presupuesto de confianza. **Inerte** sin `FEATURE_PHATIC_AUTONOMY` |

Encender evo-agente solo mide/registra. **No** usa estas flags para entregar mensajes al VIP.

### Saludo puro (entrega acotada)

| Flag | Default | Efecto |
|------|---------|--------|
| `FEATURE_PHATIC_AUTO_SEND` | false | Autoentrega del borrador de **saludo puro VIP** (`reason=plantilla_saludo`) tras el corte post-Analyst. OFF = cola de la dueña (approve). ON = `action=send` + deliver en orquestador **sin** AMS L1/L2 y **sin** trust_budget. Atención nunca. Congelado/pausado fail-closed. |

**Distinción obligatoria:**

| Flag | Rol |
|------|-----|
| `FEATURE_PHATIC_AUTONOMY` | Shadow del clasificador (`turn_category_log` / would_autonomous). **Nunca** es kill-switch de envío. |
| `FEATURE_PHATIC_AUTO_SEND` | Envío real **solo** de plantilla de saludo puro VIP. Independiente de AMS. |
| `FEATURE_AUTONOMOUS_MODE` | Envío autónomo del pipeline completo (Decider + AMS). Default false; el saludo auto-send **no** lo enciende. |

Documentado en `.env.example`. Pool saludo-cognitivo 2026-08-16 (`e10d4cd`…`21ab08b`).

### Sin flag

`ephemeral_events` (027) no tiene `FEATURE_EPHEMERAL*`. El augmenter está siempre cableado.

## Justificación

- Rollback sin redeploy (AGENTS.md §7).
- Nuevos comportamientos en `if settings.FEATURE_XXX_ENABLED:` (AGENTS.md §5.6).
- Checklist de revisión: “¿Los nuevos flujos están envueltos en feature flags?” (AGENTS.md §6).

## Estado de producción

Snapshot verificado en [[estado-del-proyecto]] (2026-08-11): calibración off; evo-agente ON en medición; `FEATURE_AUTONOMOUS_MODE=false`; F4 `FEATURE_GENERAL_MODE_ENABLED=true`; memoria on. `FEATURE_LINK_ENABLED` implementado y **off** (2026-08-15). Apply de 027–029 y valor prod de `FEATURE_QUALITY_FEEDBACK_ENABLED`: **no verificado** después de esa fecha.

Relacionado: [[modos-de-operacion]], [[esquema-fase6]], [[esquema-conocimiento]], [[calibracion-de-umbrales]].

^[src/diana/config/settings.py, .env.example, AGENTS.md §1 §5.6]
