---
title: Behavior Engine
created: 2026-08-11
updated: 2026-08-16
type: entity
tags: [modulo, contrato]
sources: [../../AGENTS.md, ../../docs/SPEC-1.1.md, ../../docs/REQUERIMIENTOS.md]
confidence: high
---

# Behavior Engine

Módulo de **actuación human-like** — infraestructura pura, **fuera de la cognición** (REQ-COG-13, principio rector nº 3).

- **Pregunta que responde:** ¿Cómo se actúa el mensaje?
- **Puede:** delay, marcar como leído, typing, enviar, cancelar, FakeDelivery (sandbox), dividir mensajes, quirks humanos.
- **Nunca puede:** generar texto, decidir la acción, invocar Analista/Generador/Evaluador/Decisor.

## Secuencia de entrega

`delay configurable → read_business_message → send_chat_action(typing) (duración proporcional) → send_message con business_connection_id` (SPEC-1.1 §4.9).

## Extensiones Fase 3 (AGENTS.md §4.2)

- `deliver_with_sequence(texts, ctx)`: secuencias multi-mensaje (promo, recontacto) con delays y typing entre mensajes.
- `ctx.allow_split=True` → divide mensajes largos preservando sentido (puntos, comas, saltos de línea).
- `ctx.allow_human_quirks=True` → con probabilidad baja (≈5%): pausas extra, correcciones tipográficas, divisiones "naturales".
- `ctx.is_frozen` (congelación por zona gris) debe respetarse: cero I/O hacia el VIP (REQ-NFR-03).

## Reglas

- `allow_split` y `allow_human_quirks` son flags del `DeliveryContext`, no configuraciones globales.
- Los quirks son probabilísticos y no afectan el contenido del mensaje.
- Cancelación: se aborta la asyncio.Task y se marca `cancelled` en `pending_deliveries`.
- FakeDelivery para Sandbox (BR-06: no contamina producción).

## Implementación real (2026-08-11, actualizado 2026-08-16)

`behavior/` sigue con **6** archivos (sin altas ni bajas desde el freeze): `engine.py` (entrega human-like, nunca decide ni llama LLM), `ports.py` (puertos I/O, sin LLM ni módulos cognitivos), `quirks.py` (helpers puros de quirks, H3.6), `split.py` (helpers puros de división de texto, H3.6), `timer_manager.py` (mapa en proceso de tareas de entrega por chat_id), `fake.py` (dobles de test).

Cambio post-freeze (2026-08-12, `ecd6d79`): `ports.py` exporta `ProgressKind` (`"reading"` | `"typing"`) y `DeliveryProgressCallback`. `BehaviorEngine.deliver(..., on_progress=)` notifica esas etapas en best-effort; un fallo del callback no aborta la entrega. La capa Telegram usa esto para el progreso en vivo del borrador (leer → escribiendo → enviado) sin que el engine conozca aiogram. Ver [[telegram-layer]] y [[application-services]].

^[src/diana/behavior/*, AGENTS.md §2.1]
