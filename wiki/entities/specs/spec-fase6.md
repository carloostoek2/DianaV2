---
title: SPEC-FASE6.md
created: 2026-08-16
updated: 2026-08-16
type: entity
tags: [spec, flujo, contrato]
sources: [../../docs/SPEC-FASE6.md, ../../docs/ESTADO-PROYECTO.md]
confidence: high
---

# SPEC-FASE6.md

Contrato de diseño de la **Fase 6 — Vínculo entre bots (Lucien → Diana)** (v1.0, aprobado 2026-08-11). Cuando Lucien expulsa a un suscriptor del Canal VIP, Diana verifica si es VIP suyo y pide a la dueña qué hacer. Nada destructivo es automático. Ver [[vinculo-lucien]].

## Decisiones de producto (dueña)

1. La vía es la **conexión business** de la misma cuenta (Telegram no deja que dos bots se vean mensajes).
2. Chat de coordinación = **grupo privado** (`LINK_CHAT_ID` en ambos bots).
3. Si el expulsado es VIP activo de Diana → aviso a la dueña con **Expulsar / Inhabilitar / Mantener**.
4. Si no es VIP → se registra y no se notifica.
5. **Inhabilitar** es indefinido (`frozen_until` lejana, default `2099-12-31T00:00:00Z`).
6. `FEATURE_LINK_ENABLED` default `false`: apagado → comportamiento idéntico al anterior.
7. Sin ack de vuelta a Lucien en esta fase.

## Qué implementó Diana (2026-08-15)

Pool cerrado 4/4. Flag **OFF por default** en código. Falta el spike de integración real (dueña conecta Lucien, expulsa un usuario de prueba, confirma el aviso).

| Pieza | Dónde |
|---|---|
| Ledger `link_events` | Migración **028** (el SPEC decía 027; 027 es ephemeral) |
| Decisión | `LinkCoordinator` en [[application-services]]: dedup → VIP → notificar → Expel/Disable/Keep |
| Entrada `[LINK]` | `LinkCoordinatorMiddleware` **antes** de `OwnerDetectionMiddleware` (corrección a REQ-LNK-04) |
| Callbacks | `handlers/link.py` (`link:expel\|disable\|keep:<event_id>`), solo dueña |
| Aviso | `notify_link` + teclado de 3 botones |

## Deltas vs el SPEC v1.0

El SPEC sigue siendo el contrato de producto. El código corrigió tres detalles de implementación:

- Receptor en **middleware**, no en un router de `business_message` (`handlers/link.py` solo maneja botones).
- Tabla `link_events` = migración **028**, no 027.
- Flag OFF: el middleware se registra inerte (`enabled=False`); el coordinator no-opea; el router de botones no se incluye.

Diana solo consume el payload `[LINK]` / `event=vip_kicked`. Los puntos de emisión viven en Lucien; no se documentan aquí.

Relacionado: [[feature-flags]], [[anti-contaminacion]], [[estado-del-proyecto]].

^[docs/SPEC-FASE6.md]
^[docs/ESTADO-PROYECTO.md]
