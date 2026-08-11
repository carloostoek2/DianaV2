---
title: Turn Coordinator
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [modulo, contrato, flujo]
sources: [../../AGENTS.md, ../../docs/SPEC-1.1.md]
confidence: high
---

# Turn Coordinator

Módulo de la capa Application que **serializa por chat_id** y garantiza que solo exista **un turno no terminal** por chat (REQ-NFR-02, REQ-VIP-06). Principio rector nº 7: "El Turn Coordinator garantiza la serialización por chat".

- **Pregunta que responde:** ¿Qué turno está vivo?
- **Puede:** serializar por chat, gestionar la máquina de estados del Turn, cancelar entregas obsoletas.
- **Nunca puede:** decidir qué decir, invocar LLM, tocar memoria persistente.

## Máquina de estados del Turn

```
[received] → (cortocircuito) → [escalated] (TERMINAL)
[received] → [analyzing] → [planning] → [retrieving] → [building_context]
           → [generating] → [evaluating] → [deciding]
           → [pending_approval] → (aprueba) → [delivered] (TERMINAL)
                               → (descarta/escala) → [escalated] (TERMINAL)
                               → (nuevo msg del VIP) → [superseded] (TERMINAL)
```

**Invariante crítica:** solo un Turn no terminal (fuera de `superseded|delivered|failed|escalated`) por chat_id. Implementación sugerida: `SELECT ... FOR UPDATE` sobre `turns` o cola FIFO en memoria por chat (SPEC-1.1 §3, decisión abierta nº 2).

## Reglas de dependencia

- Recibe de la capa Telegram (middlewares) y orquesta hacia [[pipeline-cognitivo]].
- Prohibido **by-passear** el Turn Coordinator (AGENTS.md §2.2).

^[docs/SPEC-1.1.md §3, AGENTS.md §2.1]
