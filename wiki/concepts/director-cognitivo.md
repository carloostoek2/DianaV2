---
title: Director Cognitivo
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [arquitectura, modulo, contrato]
sources: [../../docs/REQUERIMIENTOS.md, ../../docs/SPEC-1.1.md, ../../AGENTS.md]
confidence: high
---

# Director Cognitivo

Componente 100 % código determinista que orquesta el pipeline. **Nunca piensa, nunca escribe, nunca consulta memoria directamente, nunca invoca un LLM para decidir qué hacer.**

- **Pregunta que responde:** ¿Qué necesita este turno?
- **Naturaleza:** código puro (REQ-COG-02, BR-08).
- **Entrada:** Turn en estado received + texto.
- **Salida:** coordinación del pipeline hasta obtener una Decision.

## Cómo opera

1. Cortocircuito de escalación por palabras/temas prohibidos (antes del Analista, REQ-COG-16).
2. Invoca Analista → obtiene Comprensión.
3. Invoca Planificador → obtiene Plan de recuperación.
4. Pide al [[capability-registry]] resolver cada capacidad del plan.
5. Constructor de Contexto → prompt mínimo dinámico.
6. Generador (LLM) → borrador.
7. Evaluador (LLM) → [[perfil-evaluacion-multidimensional]].
8. [[decisor]] → Decision.

El Director conoce únicamente **capacidades** (`knowledge.memory`, `knowledge.policy`, etc.), no módulos concretos — eso garantiza sustituibilidad total (REQ-COG-03).

## Límites duros

- Nunca consulta un LLM para decidir.
- No conoce aiogram ni la capa Telegram.
- No escribe en Staging ni decide delays.
- La regeneración por naturalidad baja es secuenciación del Director (pre-Decisor), no una acción del [[decisor]] (AGENTS.md §4.1 nota prioridad 4).

^[docs/REQUERIMIENTOS.md §3.3, AGENTS.md §2.1]
