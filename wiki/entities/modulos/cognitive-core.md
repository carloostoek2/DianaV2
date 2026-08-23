---
title: Cognitive Core
created: 2026-08-11
updated: 2026-08-16
type: entity
tags: [modulo, arquitectura, contrato]
sources: [../../AGENTS.md, ../../docs/SPEC-1.1.md, ../../src/diana/cognitive/]
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

## Implementación real (2026-08-16)

`cognitive/` tiene 31 archivos `.py` (29 módulos + 2 `__init__`) y cumple el diseño, con detalles adicionales:

- **Director** (`director.py`) — sequencer determinista del path de decisión. Tras el Registry puede inyectar un `KnowledgeAugmenter` de aplicación (`knowledge.ephemeral`, perfil sandbox) **sin** que el Core conozca esas tablas.
- **Decider** (`decider.py`) — matriz F3 pura (ver [[decisor]]). Los hooks de evolución de agente (clasificador, mood, trust, detector, síntesis) viven en `application/` y son **shadow-only**: miden y registran; no cambian esta matriz.
- **Evaluator** (`evaluator.py`) — perfil 7D; **Generator** — solo redacta; **Analyst** — Comprensión.
- **Planner** (`planner.py`) — función pura, sin llamadas al modelo.
- **Registry** (`registry.py`) — resolución nombre → Retriever (Anexo H.1).
- **Thresholds** (`thresholds.py`) — defaults duales F3 (SPEC-FASE3 §4.2); `runtime_thresholds.py` — umbrales mutables en runtime para lecturas del Decider tras la calibración (ver [[calibracion-de-umbrales]]).
- **ContextBuilder** (`context_builder.py`) — emite bloques en orden fijo (D.4) y omite valores nulos. Cerca user-controllable (profile / memory / policy / examples / ephemeral) con fences SEC-INJ para que el LLM no los trate como instrucciones.
- **Retrievers reales:** `history` (mensajes recientes del chat), `context` (REAL: estado conversacional derivado del historial; con `FEATURE_CONTEXT_ENABLED` lee el snapshot interpretado no expirado de la tabla `contexts` — REQ-MEM-06 — con fallback a la derivación en vivo; ver [[esquema-conocimiento]]), `memory` (VIP-scoped, BR-15), `policy` (estáticas por tema + DB con `scope` y `vip_id`), `profile` (por PK; embeddings reales del contenido al escribir + `find_by_similarity`; no fetch si `vip_id` es None), `examples` (nunca lee memoria VIP; gold-first + visibilidad `vip_id`; anexa 1 contraejemplo), `schedule` (agenda semanal fija), `persona_facts` y `voice_patterns` (catálogo estático por tags / canal).
- **Extras de seguridad:** `template_gate.py` (matcher determinístico para respuestas cortas VIP, H6), `repetition_guard.py` (detector de intents repetidos), `j4_triggers.py` + `deterministic_escalate.py` (en application/) — cortocircuito pre-Director sin LLM.

Relacionado: [[anti-contaminacion]], [[zona-gris-y-politicas]].

^[src/diana/cognitive/*, AGENTS.md §2.1]
