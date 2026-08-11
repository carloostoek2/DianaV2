---
title: Operación Single-Instance
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [operacion, riesgo, contrato]
sources: [../../docs/OPS_SINGLE_INSTANCE.md]
confidence: high
---

# Operación Single-Instance

Diana corre como **un solo proceso de bot activo**. Varios controles de concurrencia y seguridad son **process-local** (en memoria): correctos bajo esa premisa, **no seguros multi-réplica**.

## Inventario process-local

| Componente | Ubicación | Qué es local |
|---|---|---|
| Chat locks | `ChatLockProvider` / TurnCoordinator | Mapa `asyncio.Lock` por `chat_id`; serializa el turno dentro del proceso |
| CorrectSessionStore | `telegram/handlers/callbacks.py` | FSM en memoria (owner escribiendo corrección libre, TTL 15 min); **un restart limpia las sesiones** |
| DedupMiddleware | `telegram/middlewares/dedup.py` | Caché TTL en memoria de ids de update/callback |
| RateLimitMiddleware | `telegram/middlewares/rate_limit.py` | Ventana deslizante por usuario en proceso; owner exento |

## Consecuencias multi-réplica (si se corre igual)

- Double long-poll / multi-writer: dos procesos pueden recibir y actuar sobre los mismos updates.
- Sesiones Correct divididas: botón en A, texto libre en B → ignorado o sesión equivocada.
- Rate limits/dedup débiles: contadores por proceso, no globales.
- El chat lock no cruza procesos: pipelines concurrentes para el mismo chat pueden correr en paralelo.

**No tratar como features multi-réplica soportadas.** Preferir un único proceso activo (o coordinación real compartida antes de escalar). El lock multi-proceso por chat queda residual (Postgres `SELECT … FOR UPDATE` / advisory locks).

^[docs/OPS_SINGLE_INSTANCE.md]
