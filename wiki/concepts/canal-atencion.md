---
title: Canal de Atención
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [modo, regla-negocio, memoria]
sources: [../../docs/SPEC-FASE4.md]
confidence: high
---

# Canal de Atención

Perfil de canal para clientes **no-VIP** (Fase 4, `channel_type="atencion"`). El sistema pasa de "una persona global" a **un perfil por tipo de chat**; el canal se decide una vez, de forma determinista, en la puerta de entrada (AuthMiddleware) — el pipeline cognitivo no cambia.

## Diferencias con el canal VIP

| Aspecto | VIP | Atención |
|---|---|---|
| Determinación | allowlist (auth) | no-VIP + `FEATURE_GENERAL_MODE_ENABLED` |
| Identidad | Diana actual | Diana versión servicio |
| Estilo | Cálida, cercana, coqueta permitida | Cálida-profesional, **sin coqueteo**, sin contenido íntimo |
| Memoria | `memories` por VIP | Solo `message_history` por chat (nunca `memories`) |
| Entrega | Supervisada / autónoma | **Supervisada** (autónomo postergado) |
| Límite | Sin límite | **20 mensajes del cliente/día/chat** (zona `America/Mexico_City`) |
| Aprendizaje | Banco de ejemplos VIP | Marcado `channel_type=atencion`, jamás al banco VIP |

## Reglas de oro

- **Diana es la única que atiende**: prohibido derivar a terceros o decir "eso lo ves con alguien más". Ante desconocimiento → [[zona-gris-y-politicas]] (consulta a la dueña), nunca inventar.
- **Sin contacto personal** (política `no_contacto_personal`): "¿dónde te puedo ver?" → servicio inexistente, respuesta cálida y firme.
- **Sin entrega de contenido automática**: el bot guía hasta el pago y avisa a la dueña por DM (entrega manual; `datos_pago` activada o comprensión de pago → notificación).
- **Guiones son doctrina** (policies), no few-shots: precios, diferencias_niveles, suscripcion, datos_pago, no_contacto_personal, no_contenido_hasta_pago, unica_atencion, fuera_alcance.
- **Anti-contaminación total entre canales** (REQ-ATN-13): el staging filtra por canal; la calibración y el drift usan **solo muestras VIP**.
- **Tope diario** (REQ-ATN-03): contador determinista por `(chat_id, fecha_local)` en `daily_message_limits`; al alcanzar 20, una única respuesta de cierre (plantilla fija) y luego drop silencioso.

## Cambios de esquema

Migración 018: `persona_versions.channel_type` (constraint de activo por `(channel_type, is_active)`) + tabla `daily_message_limits`. El toggle manual `training_mode_enabled` queda deprecado para producción.

Relacionado: [[spec-fase4]], [[modos-de-operacion]], [[anti-contaminacion]], [[feature-flags]].

^[docs/SPEC-FASE4.md]
