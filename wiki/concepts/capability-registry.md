---
title: Capability Registry
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [arquitectura, modulo, contrato]
sources: [../../docs/REQUERIMIENTOS.md, ../../docs/SPEC-1.1.md]
confidence: high
---

# Capability Registry

El corazón de la **sustituibilidad** (REQ-NFR-14). El [[director-cognitivo]] no conoce módulos concretos: conoce únicamente **capacidades** (`knowledge.memory`, `knowledge.policy`, `knowledge.schedule`, `knowledge.examples`, `knowledge.history`, `knowledge.context`, `knowledge.profile`).

- **Pregunta que responde:** ¿Qué componente concreto satisface esta capacidad?
- **Contrato:** `resolve(capacidad) → Retriever` (todos con interfaz `fetch(turn) → resultado | null`).

## Capacidades y estado por fase

| Capacidad | Fase 1 (MVP) | Fase 2 (MVP+) | Fase 3+ |
|---|---|---|---|
| `knowledge.history` | REAL (últimos N mensajes, SQL) | REAL mejorado | REAL |
| `knowledge.context` | REAL parcial | REAL (contexts + embeddings + expiración) | REAL |
| `knowledge.profile` | STUB (null) | REAL (profiles) | REAL |
| `knowledge.memory` | STUB | REAL (memories, pgvector + vip_id) | REAL |
| `knowledge.policy` | STUB | REAL (policies activas) | REAL |
| `knowledge.examples` | STUB | REAL (few-shot) | REAL |
| `knowledge.schedule` | STUB | STUB | REAL (agenda de la dueña) |

## Límites duros

- Ningún Retriever puede importar otro Retriever de tipo distinto.
- Los retrievers devuelven conocimiento estructurado filtrado; nunca mezclan tipos ni deciden si se usará lo recuperado.
- Un retriever nunca devuelve Memoria de otro VIP ([[anti-contaminacion]]).

^[docs/SPEC-1.1.md §4.4, docs/REQUERIMIENTOS.md §3.4]
