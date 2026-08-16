---
title: Telegram Layer
created: 2026-08-11
updated: 2026-08-16
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

Contrato de producto (SPEC):

- **Auth:** ¿está en allowlist? (REQ-AUTH-01)
- **ForbiddenWords:** cortocircuito de escalación por palabras/temas prohibidos (Fase 1, ver [[escalacion]])
- **FreezeCheck:** ¿está congelado por zona gris? (Fase 2, ver [[zona-gris-y-politicas]])

Orden real de registro (`F2_MIDDLEWARE_ORDER` en `telegram/middlewares/__init__.py`; el primero es el más externo):

`ErrorHandler → Dedup → RateLimit → Logging → BusinessConnection → LinkCoordinator → Owner → FreezeCheck → Auth → Forbidden`

Auth va antes de Forbidden para que un no-VIP no dispare escalación J.4. `FreezeCheckMiddleware` vive en `telegram/freeze_middleware.py` (raíz del paquete, no en `middlewares/`). En `callback_query` se omite Freeze (no-op). El update `business_connection` solo lleva ErrorHandler + Logging.

## Estructura prevista (SPEC-1.1 §11)

`telegram/handlers/` (business.py, admin.py, callbacks.py), `telegram/middlewares/` (auth, forbidden, freeze), `telegram/keyboards.py`.

## Reglas de dependencia

- Telegram Layer → Turn Coordinator (nunca directo al Cognitive Core).
- El mensaje saliente al VIP se envía en nombre de la dueña vía la conexión de negocio (REQ-AUTH-04, REQ-NFR-09) — nunca como un bot con otro nombre.

## Implementación real (2026-08-11, actualizado 2026-08-16)

`telegram/` tiene **26** archivos `.py` (sin `__init__.py`). El directorio `telegram/menu/` no tiene fuentes; el menú está en `handlers/menu.py`.

- **Handlers (10):** `business.py` (mensajes VIP; cancela combo de calidad al inbound), `admin.py`, `menu.py` (panel de dueña + wizard de [[eventos-temporales]]), `callbacks.py` (keyboards de borradores + Destacar/Reprender), `doctrine.py` (zona gris `g:`), `staging.py`, `memory_approval.py` (aprobación de hechos sensibles F5), `persona_admin.py`, `business_connection.py`, `link.py` (callbacks `link:<action>:<event_id>` de [[vinculo-lucien]]).
- **Middlewares (9 en `middlewares/` + Freeze en raíz):** `auth.py`, `forbidden.py`, `owner.py`, `rate_limit.py`, `dedup.py`, `business_connection.py`, `error_handler.py`, `logging.py`, `link.py` (`LinkCoordinatorMiddleware`: consume `[LINK]` del chat Lucien, no llega al orquestador). Freeze: `freeze_middleware.py`.
- **Otros:** `actuator.py` (adaptador aiogram del puerto de actuación), `notifier.py` (DMs a la dueña: draft/escalate/doctrine/info + `notify_link` + `edit_draft`/`void_draft`), `keyboards.py` (callback_data ≤ 64 bytes; fila Destacar/Reprender detrás de `feature_quality_feedback_enabled`; `link_kick_keyboard`), `health.py` (probe /health), `setup.py` (orden F2 + routers), `helpers.py` (tiempo relativo de UI).

Inventario post-freeze (sin la historia de producto): teclas de [[calidad-feedback]], middleware/handler de [[vinculo-lucien]], wizard de [[eventos-temporales]] en el menú.

^[src/diana/telegram/*, AGENTS.md §2.1]
