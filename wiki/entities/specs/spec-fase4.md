---
title: SPEC-FASE4.md
created: 2026-08-11
updated: 2026-08-21
type: entity
tags: [spec, modo, regla-negocio]
sources: [../../docs/SPEC-FASE4.md]
confidence: high
---

# SPEC-FASE4.md

Contrato de diseño e implementación de la **Fase 4 — Atención al Cliente General (canal no-VIP)** (v1.1, implementada y desplegada). Convierte el sistema en asistente permanente de atención: cualquier persona que escriba por Telegram Business (no-VIP) recibe atención con identidad Diana versión servicio.

## Decisiones de producto

1. Atención **supervisada** siempre (aprobación/corrección de la dueña; el modo automático queda **fuera de alcance, no implementado**).
2. Identidad: misma Diana, **versión servicio**: cálida y profesional, sin coqueteo, sin contenido íntimo.
3. Flujo con guion: promo de bienvenida automática (existente) → identificación de intención → guion (precios, diferencias, suscripción, datos de pago).
4. Reglas duras: sin contacto personal ("¿dónde te puedo ver?" → servicio inexistente); **Diana es la única que atiende** (nunca derivar).
5. **Límite: 20 mensajes del cliente por día por chat** (zona horaria `America/Mexico_City`).
6. Sin entrega automática de contenido: el bot guía hasta el pago y **avisa a la dueña** (entrega manual).
7. Zona gris aplica a atención: ante desconocimiento → consulta a la dueña, nunca inventar ni derivar.

## Concepto clave: perfil de canal

El sistema pasa de "una persona global" a un perfil por tipo de chat (ver [[canal-atencion]]). Una sola rama determinista en la puerta (AuthMiddleware): `vip_id` + `channel_type` se deciden una vez, el pipeline no cambia.

- `FEATURE_GENERAL_MODE_ENABLED` (default `false` en código; **activo**: `true` en `.env`) gobierna todo el comportamiento.
- `persona_versions.channel_type` (`vip` | `atencion`) — una versión activa por canal (migración 018).
- Tabla `daily_message_limits` (chat_id, fecha_local, count).
- Anti-contaminación total entre canales: atención nunca toca `memories` ni el banco VIP.

## Seguridad

El perfil `atencion` nunca emite contenido explícito/sexual ni material del canal VIP; `forbidden_keywords` y freeze aplican a ambos canales (ver [[zona-gris-y-politicas]]).

^[docs/SPEC-FASE4.md]
