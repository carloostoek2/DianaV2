---
title: Vínculo Lucien → Diana
created: 2026-08-16
updated: 2026-08-21
type: concept
tags: [flujo, contrato, operacion]
sources: [../../docs/SPEC-FASE6.md, ../../src/diana/application/link.py]
confidence: high
---

# Vínculo Lucien → Diana

Cuando Lucien saca a alguien del Canal VIP, Diana **no lo da de baja sola**. Comprueba si esa persona es VIP suyo y le pregunta a la dueña. La llave es `FEATURE_LINK_ENABLED` (default `false` en código; **activo en `.env`**: `FEATURE_LINK_ENABLED=true`, 2026-08-21). La integración está **desplegada y verificada E2E** (bot-to-bot DM, aceptación real pasada). Contrato: [[spec-fase6]].

## Quick path

1. Llega un mensaje de coordinación con prefijo `[LINK]` al chat `LINK_CHAT_ID`.
2. El middleware lo consume **antes** de detectar dueña / auth / freeze — no entra al pipeline ni a `message_history`.
3. Si el `user_id` es un VIP **activo** → DM a la dueña con 3 botones. Si no → se registra y termina.
4. La dueña elige. El mensaje pierde los botones.

## Qué consume Diana

Una línea, JSON estricto. Campos que el middleware exige: `event` = `vip_kicked`, `event_id` (texto no vacío), `user_id`, `reason` (texto no vacío). Opcionales: `username`, `channel_id`, `channel_name`.

```
[LINK] {"v":1,"event":"vip_kicked","event_id":"<uuid>","user_id":123,"username":"@ana","reason":"admin_revoke","ts":1789123456}
```

Lucien puede mandar el `@` en `username`; el aviso lo normaliza (`Ana @ana`, nunca `@@ana`).

## Botones de la dueña

Texto del aviso (español neutro): «El suscriptor {nombre} ha sido expulsado del Canal VIP. ¿Quieres inhabilitarlo aquí?»

| Botón | Acción en `vips` | Estado en `link_events` |
|---|---|---|
| ❌ Expulsar | `is_active = false` (baja suave; el registro se conserva) | `decided_expel` |
| 🚫 Inhabilitar | `frozen_until` = fecha lejana (default 2099-12-31 UTC) | `decided_disable` |
| ✅ Mantener | sin cambios | `decided_keep` |

Un VIP pausado o congelado **sigue siendo VIP**: si `is_active` es true, el aviso llega. Si el VIP ya no aplica al pulsar (carrera, ya inactivo, acción desconocida) → «ya no aplica» y estado `noop`.

## Fail-closed y anti-contaminación

- Con `FEATURE_LINK_ENABLED` activo, sin `LINK_CHAT_ID` configurado, o sin coordinator: el mensaje sigue de largo; cero comportamiento nuevo.
- Mismo `event_id` otra vez → no se vuelve a notificar (dedup UNIQUE + `create` idempotente).
- JSON inválido, `event` distinto, ids no finitos (`OverflowError`) → log `link_malformed`, se consume, no crashea, no llega al orquestador.
- Error real del coordinator **no** se disfraza de malformado: sube al `ErrorHandlerMiddleware`.
- Solo la dueña puede pulsar los botones (`link:*` owner-gated, antes del catch-all).
- El chat de coordinación **nunca** entra a `message_history`, al [[pipeline-cognitivo]] ni al [[aprendizaje-post-turno]].

Relacionado: [[feature-flags]], [[modos-de-operacion]], [[anti-contaminacion]].

^[docs/SPEC-FASE6.md]
^[src/diana/application/link.py]
^[docs/ESTADO-PROYECTO.md §Fase 6]
