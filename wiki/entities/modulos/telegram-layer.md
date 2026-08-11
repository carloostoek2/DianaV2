---
title: Telegram Layer
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [modulo, contrato]
sources: [../../AGENTS.md, ../../docs/SPEC-1.1.md]
confidence: high
---

# Telegram Layer

Capa de adaptación con Telegram (aiogram 3.x, Business Connection). Es la puerta de entrada y salida del sistema.

- **Pregunta que responde:** ¿Cómo entro y salgo de Telegram?
- **Puede:** recibir updates, enviar mensajes, middlewares de short-circuit.
- **Nunca puede:** decidir qué decir, invocar LLM, escribir en tablas de conocimiento.

## Middlewares (SPEC-1.1 §2)

- **Auth:** ¿está en allowlist? (REQ-AUTH-01)
- **ForbiddenWords:** cortocircuito de escalación por palabras/temas prohibidos (Fase 1, ver [[escalacion]])
- **FreezeCheck:** ¿está congelado por zona gris? (Fase 2, ver [[zona-gris-y-politicas]])

## Estructura prevista (SPEC-1.1 §11)

`telegram/handlers/` (business.py, admin.py, callbacks.py), `telegram/middlewares/` (auth, forbidden, freeze), `telegram/keyboards.py`.

## Reglas de dependencia

- Telegram Layer → Turn Coordinator (nunca directo al Cognitive Core).
- El mensaje saliente al VIP se envía en nombre de la dueña vía la conexión de negocio (REQ-AUTH-04, REQ-NFR-09) — nunca como un bot con otro nombre.

## Implementación real (2026-08)

`telegram/` tiene 24 archivos:

- **Handlers** (8): `business.py` (mensajes VIP), `admin.py`, `menu.py`, `callbacks.py` (keyboards de borradores), `doctrine.py` (zona gris `g:`), `staging.py`, `memory_approval.py` (aprobación de hechos sensibles F5), `persona_admin.py`, `business_connection.py`.
- **Middlewares** (8): `auth.py`, `forbidden.py`, `freeze_middleware.py`, `owner.py`, `rate_limit.py`, `dedup.py`, `business_connection.py`, `error_handler.py`, `logging.py`.
- **Otros:** `actuator.py` (adaptador aiogram del puerto de actuación), `notifier.py` (DMs a la dueña), `keyboards.py` (callback_data ≤ 64 bytes), `health.py` (probe /health), `setup.py`.

^[src/diana/telegram/*, AGENTS.md §2.1]