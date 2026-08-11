---
title: SPEC-1.1.md
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [spec, decision, arquitectura]
sources: [../../docs/SPEC-1.1.md]
confidence: high
---

# SPEC-1.1.md

Contrato de diseño e implementación (SPEC.md v1.5 — Híbrido Integrado, basado en [[spec-requerimientos]] v2.1). Es la **única fuente de verdad para la implementación**; estrategia incremental por fases.

## Stack tecnológico (bloqueado)

- Python 3.12+, aiogram 3.x (Business Connection nativo), PostgreSQL 16+ (único almacén durable), SQLAlchemy 2.0 async + asyncpg, Pydantic v2, pgvector (Fase 2+).
- LLM primario **DeepSeek**, secundario **Anthropic** (hot-swap vía interfaz abstracta).
- Embeddings locales sentence-transformers (Fase 2).
- **No se usa en V1:** Redis, LangChain, Celery, Kafka.

## Contenido clave

- Arquitectura de alto nivel con [[turn-coordinator]] y máquina de estados del turno (§2-3).
- Contratos por componente (§4): [[director-cognitivo]], Analista, Planificador, [[capability-registry]], Constructor de Contexto, Generador, Evaluador, [[decisor]], [[behavior-engine]].
- Modelo de datos clasificado por fase (§5): tablas Fase 1 (vips, message_history, pipeline_traces, pending_deliveries, turns, escalation_events), Fase 2 (profiles, memories, contexts, policies, examples, staging_candidates, gray_zone_queries), Fase 3 (learning_metrics, system_config).
- ADRs (§9): ADR-001 aiogram; ADR-002 Director + Capability Registry; ADR-003 solo PostgreSQL+pgvector; ADR-004 Behavior Engine con asyncio.Task; ADR-005 embeddings locales; ADR-006 LLMProvider con hot-swap.
- Criterios de aceptación técnicos TAC-01..13 (§10).
- Estructura de carpetas propuesta (§11) — coincide con `src/diana/` del repo.

^[docs/SPEC-1.1.md]
