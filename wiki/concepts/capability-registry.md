---
title: Capability Registry
created: 2026-08-11
updated: 2026-08-16
type: concept
tags: [arquitectura, modulo, contrato]
sources: [../../docs/REQUERIMIENTOS.md, ../../docs/SPEC-1.1.md, ../../src/diana/cognitive/registry.py]
confidence: high
---

# Capability Registry

El corazón de la **sustituibilidad** (REQ-NFR-14). El [[director-cognitivo]] no conoce módulos concretos: conoce únicamente **capacidades** (`knowledge.memory`, `knowledge.policy`, `knowledge.schedule`, `knowledge.examples`, `knowledge.history`, `knowledge.context`, `knowledge.profile`, `knowledge.persona_facts`, `knowledge.voice_patterns`).

- **Pregunta que responde:** ¿Qué componente concreto satisface esta capacidad?
- **Contrato:** `resolve(capacidad) → Retriever` (todos con interfaz `fetch(turn) → resultado | null`).

## Capacidades y estado por fase

| Capacidad | Fase 1 (MVP) | Fase 2 (MVP+) | Fase 3+ |
|---|---|---|---|
| `knowledge.history` | REAL (últimos N mensajes, SQL) | REAL mejorado | REAL |
| `knowledge.context` | REAL parcial | REAL parcial (derivado del historial; no lee `contexts`) | REAL parcial |
| `knowledge.profile` | STUB (null) | REAL (profiles, PK) | REAL |
| `knowledge.memory` | STUB | REAL (memories, pgvector + vip_id) | REAL |
| `knowledge.policy` | STUB | REAL (policies activas) | REAL + `vip_id` |
| `knowledge.examples` | STUB | REAL (few-shot) | REAL + gold-first + `vip_id` |
| `knowledge.schedule` | STUB | STUB | REAL (agenda de la dueña) |
| `knowledge.persona_facts` | — | — | REAL (catálogo estático / canal) |
| `knowledge.voice_patterns` | — | — | REAL (catálogo estático / canal) |

`knowledge.ephemeral` **no** es asiento del Registry: lo inyecta un `KnowledgeAugmenter` de aplicación después del fetch (eventos con vigencia). El Constructor de Contexto sí lo emite si viene en el mapa.

## Retrieval vivo (2026-08-16)

- **Examples (gold-first):** `find_by_similarity` ordena `quality=gold` antes que `standard`, y luego por distancia coseno. Umbral 0.7, límite 5; siempre intenta anexar 1 contraejemplo. Visibilidad: Atención ve solo globales; un VIP ve globales + las suyas ([[anti-contaminacion]]).
- **Policies:** match estático por `tema ∩ (topics ∪ intent)` + path DB (umbral 0.8). `vip_id` es eje distinto de `scope`. En Atención el path DB fuerza `scope='all'` (nunca una política VIP-scoped). Fallo de DB no tira los hits estáticos.
- **Context:** sigue siendo REAL parcial — `waiting_for_reply_since`, `is_first_message_of_day`, `dia_semana`, `hora_actual` (America/Mexico_City). No usa la tabla `contexts`.
- **Memory / Profile:** no fetch si `vip_id is None`.

## Límites duros

- Ningún Retriever puede importar otro Retriever de tipo distinto.
- Los retrievers devuelven conocimiento estructurado filtrado; nunca mezclan tipos ni deciden si se usará lo recuperado.
- Un retriever nunca devuelve Memoria de otro VIP ([[anti-contaminacion]]).

^[docs/SPEC-1.1.md §4.4, docs/REQUERIMIENTOS.md §3.4, src/diana/cognitive/retrievers/]
