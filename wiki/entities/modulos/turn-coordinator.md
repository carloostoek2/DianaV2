---
title: Turn Coordinator
created: 2026-08-11
updated: 2026-08-16
type: entity
tags: [modulo, contrato, flujo]
sources: [../../AGENTS.md, ../../docs/SPEC-1.1.md]
confidence: high
---

# Turn Coordinator

Módulo de la capa Application que **serializa por chat_id** y garantiza que solo exista **un turno no terminal** por chat (REQ-NFR-02, REQ-VIP-06). Principio rector nº 7: "El Turn Coordinator garantiza la serialización por chat".

- **Pregunta que responde:** ¿Qué turno está vivo?
- **Puede:** serializar por chat, gestionar la máquina de estados del Turn, cancelar entregas obsoletas.
- **Nunca puede:** decidir qué decir, invocar LLM, tocar memoria persistente (banco de conocimiento VIP).

## Máquina de estados del Turn

Estados en `TurnStatus` (`cognitive/models.py`):

```
[received] → [waiting_delay] → [analyzing] → [planning] → [retrieving]
           → [building_context] → [generating] → [evaluating] → [deciding]
           → [pending_approval] → (aprueba) → [delivered] (TERMINAL)
                               → (descarta/escala) → [escalated] (TERMINAL)
                               → (nuevo msg del VIP) → [superseded] (TERMINAL)
[received] → (cortocircuito) → [escalated] (TERMINAL)
[gray_zone] (consulta de doctrina)
[promo_pending] (secuencia no-VIP en vuelo)
[failed] (TERMINAL)
```

**Invariante crítica:** solo un Turn no terminal (fuera de `superseded|delivered|failed|escalated`) por chat_id. Terminales = ese cuarteto (`TERMINAL_TURN_STATUSES`).

## Implementación real (verificado 2026-08-16)

`turn_coordinator.py` **no cambió** desde 2026-08-11. La serialización es `ChatLockProvider`: un `asyncio.Lock` por `chat_id` **en el proceso** (`lock_acquire_timeout_s=5`, 2 reintentos). Timeouts levantan `ChatLockTimeoutError` (G.5 F1: fail loud, sin cola durable).

`SELECT … FOR UPDATE` / advisory lock multi-proceso **no está implementado** — queda residual documentado en el propio módulo y en `docs/OPS_SINGLE_INSTANCE.md`. No es una decisión abierta.

También mantiene épocas VIP por chat (mensaje nuevo aborta trabajo en vuelo), cancela entregas vía `BehaviorCanceller`, y opcionalmente invalida la UI de aprobación / reagenda recontacto.

## Reglas de dependencia

- Recibe de la capa Telegram (middlewares) y orquesta hacia [[pipeline-cognitivo]].
- Vive en [[application-services]]; prohibido **by-passear** el Turn Coordinator (AGENTS.md §2.2).

^[src/diana/application/turn_coordinator.py, docs/SPEC-1.1.md §3, AGENTS.md §2.1]
