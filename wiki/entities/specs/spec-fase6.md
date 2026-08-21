---
title: SPEC-FASE6.md
created: 2026-08-16
updated: 2026-08-21
type: entity
tags: [spec, flujo, contrato]
sources: [../../docs/SPEC-FASE6.md, ../../docs/ESTADO-PROYECTO.md]
confidence: high
---

# SPEC-FASE6.md

Contrato de diseño de la **Fase 6 — Vínculo entre bots (Lucien → Diana)** (v1.1, implementada y desplegada). Cuando Lucien expulsa a un suscriptor del Canal VIP, Diana verifica si es VIP suyo y pide a la dueña qué hacer. Nada destructivo es automático. Ver [[vinculo-lucien]].

## Decisiones de producto (dueña)

1. La vía es la **conexión business** de la misma cuenta (Telegram no deja que dos bots se vean mensajes).
2. Chat de coordinación = **grupo privado** (`LINK_CHAT_ID` en ambos bots); en el despliegue actual es el DM con el bot de Lucien (`LINK_CHAT_ID=7360762013`), flujo bot↔bot verificado E2E. <!-- VERIFY: lado emisor (repo lucienbot) y el chat desplegado no son verificables desde este repo -->
3. Si el expulsado es VIP activo de Diana → aviso a la dueña con **Expulsar / Inhabilitar / Mantener**.
4. Si no es VIP → se registra y no se notifica.
5. **Inhabilitar** es indefinido (`frozen_until` lejana, default `2099-12-31T00:00:00Z`).
6. `FEATURE_LINK_ENABLED`: default `false` en código, **activo en `.env`** (`true`). Apagado → comportamiento idéntico al anterior.
7. Sin ack de vuelta a Lucien en esta fase (fuera de alcance).

## Qué implementó Diana (2026-08-15)

Pool cerrado 4/4. **Flag ACTIVO en `.env`** (`FEATURE_LINK_ENABLED=true`); **integration spike completado** — Fase 6 desplegada y verificada E2E (bot-to-bot DM, aceptación real pasada). Migración real de `link_events`: **028** (027 se usó para eventos temporales).

| Pieza | Dónde |
|---|---|
| Ledger `link_events` | Migración **028** (el SPEC citaba 027; 027 es ephemeral) |
| Decisión | `LinkCoordinator` en [[application-services]]: dedup → VIP → notificar → Expel/Disable/Keep |
| Entrada `[LINK]` | `LinkCoordinatorMiddleware` **antes** de `OwnerDetectionMiddleware` (corrección a REQ-LNK-04) |
| Callbacks | `handlers/link.py` (`link:expel\|disable\|keep:<event_id>`), solo dueña |
| Aviso | `notify_link` + teclado de 3 botones |

## Deltas vs el SPEC v1.0

El SPEC sigue siendo el contrato de producto. El código corrigió tres detalles de implementación:

- Receptor en **middleware**, no en un router de `business_message` (`handlers/link.py` solo maneja botones).
- Tabla `link_events` = migración **028**, no 027.
- Flag: default OFF en código pero **activo por env** (`FEATURE_LINK_ENABLED=true`); con OFF, el middleware es pass-through y el coordinator no-opea.

Diana solo consume el payload `[LINK]` / `event=vip_kicked`. Los puntos de emisión viven en Lucien; no se documentan aquí. **Sin pendientes de esta Fase** (los 3 ítems abiertos — fecha centinela de Inhabilitar, `username` opcional, política de reintento best-effort — están resueltos; ver [[estado-del-proyecto]]).

Relacionado: [[feature-flags]], [[anti-contaminacion]], [[estado-del-proyecto]].

^[docs/SPEC-FASE6.md]
^[docs/ESTADO-PROYECTO.md]
