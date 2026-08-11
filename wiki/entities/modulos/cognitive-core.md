---
title: Cognitive Core
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [modulo, arquitectura, contrato]
sources: [../../AGENTS.md, ../../docs/SPEC-1.1.md]
confidence: high
---

# Cognitive Core

Capa que ejecuta el pipeline de decisión (Director → Analista → Planificador → Recuperación → Contexto → Generación → Evaluación → Decisión). Es **puro**: no conoce aiogram, no envía mensajes, no escribe en Staging, no decide delays.

- **Pregunta que responde:** ¿Qué decisión tomar?
- **Nunca puede:** conocer aiogram, enviar mensajes, escribir en Staging, decidir delays.

## Componentes internos

- [[director-cognitivo]] (orquestador determinista)
- Analista (LLM → Comprensión)
- Planificador (determinista → Plan)
- [[capability-registry]] + Retrievers (resolución de capacidades)
- Constructor de Contexto (prompt mínimo dinámico, REQ-NFR-07)
- Generador (LLM, solo redacta)
- Evaluador (LLM → [[perfil-evaluacion-multidimensional]])
- [[decisor]] (reglas sobre vector + modo)

## Reglas de dependencia

- Cognitive Core → Capability Registry → Retrievers → Persistence.
- Cognitive Core → LLM Provider.
- **Prohibido:** que Cognitive Core importe cualquier cosa de `telegram/` o `behavior/`.

## Implementación real (2026-08)

`cognitive/` tiene 29 archivos y cumple el diseño, con detalles adicionales:

- **Director** (`director.py`) — "deterministic sequencer for the F1 decision path".
- **Decider** (`decider.py`) — "F3 Decider — pure deterministic matrix" (ver [[decisor]]).
- **Evaluator** (`evaluator.py`) — perfil 7D; **Generator** — solo redacta; **Analyst** — Comprensión.
- **Planner** (`planner.py`) — función pura, sin llamadas al modelo.
- **Registry** (`registry.py`) — resolución nombre → Retriever (Anexo H.1).
- **Thresholds** (`thresholds.py`) — defaults duales F3 (SPEC-FASE3 §4.2); `runtime_thresholds.py` — umbrales mutables en runtime para lecturas del Decider tras la calibración (ver [[calibracion-de-umbrales]]).
- **Retrievers reales:** `history` (REAL, mensajes recientes del chat), `context` (REAL parcial, derivado del historial), `memory` (VIP-scoped, BR-15), `policy`, `profile` (por PK), `examples` (nunca lee memoria VIP), `schedule` (REAL: agenda semanal fija), `persona_facts` y `voice_patterns` (catálogo estático por tags).
- **Extras de seguridad:** `template_gate.py` (matcher determinístico para respuestas cortas VIP, H6), `repetition_guard.py` (detector de intents repetidos), `j4_triggers.py` + `deterministic_escalate.py` (en application/) — cortocircuito pre-Director sin LLM.

^[src/diana/cognitive/*, AGENTS.md §2.1]
