# Plan de Implementación — Fase 2 (MVP+ Memoria, Zona Gris, Staging)

> **Estado: plan implementado** — La Fase 2 está desplegada (2026-08-21). Todos los hitos de este plan se cumplieron; el diseño resultante está descrito en `docs/ARCHITECTURE.md` y `docs/SPEC-FASE2.md`.

## Contexto

La Fase 1 tiene un pipeline cognitivo completo con stubs para memory/policy/examples. La Fase 2 reemplaza esos stubs con implementaciones reales usando pgvector, añade el flujo de Zona Gris (consulta de doctrina con congelación de VIP), Staging Area para correcciones, sandbox, y feature flags. El objetivo es pasar de "bot supervisado" a "sistema que aprende y razona con memoria".

**Principio rector**: Sustituibilidad total — los nuevos retrievers implementan la misma interfaz `Retriever` que los stubs. El Director no cambia su lógica de orquestación, solo el Decisor y el Orchestrator aprenden una nueva acción (`consult_doctrine`).

## Discrepancia encontrada

El SPEC-FASE2.md afirma que las tablas Phase 2 "ya existen en el esquema de la Fase 1". Esto **no es cierto** — la migración 001 solo crea 8 tablas F1. Las tablas `profiles`, `memories`, `contexts`, `policies`, `examples`, `staging_candidates`, `gray_zone_queries`, y `learning_metrics` deben crearse en una nueva migración 003 con la extensión `pgvector`.

---

## Arquitectura de cambios

```
NUEVOS servicios (application/cognitive):
  EmbeddingService     → genera vectores desde texto (sentence-transformers)
  MemoryRetriever      → reemplaza stub, busca en pgvector por vip_id + similitud
  PolicyRetriever      → reemplaza stub, busca políticas activas por similitud
  ExamplesRetriever    → reemplaza stub, busca few-shots por similitud
  StagingService       → guarda correcciones, promueve a examples/policies
  GrayZoneService      → crea queries, congela/descongela VIP, expira queries
  PolicyDistiller      → destila texto libre → Policy estructurada

EXTENSIONES a componentes existentes:
  Decider              → añade regla consult_doctrine (prioridad 2)
  Decision model       → añade "consult_doctrine" al Literal de actions
  TurnOrchestrator     → routea consult_doctrine → GrayZoneService
  CognitiveDirector    → sin cambios (el Decider ya devuelve la acción nueva)
  ContextBuilder       → sin cambios (ya emite memory/policy/examples en orden)
  Planner              → sin cambios (ya mapea needs_* → capabilities)
  CapabilityRegistry   → sin cambios (misma interfaz, nuevas implementaciones)
  composition.py       → wiring de nuevos servicios

INFRA:
  models.py            → 8 nuevos modelos ORM
  migration 003        → tablas + pgvector + índices HNSW
  system_config        → feature flags (FEATURE_MEMORY_ENABLED, etc.)
```

---

## Plan de implementación (11 hitos)

### H0: Dependencias y migración inicial — **cumplido**
**Nuevos archivos:**
- `alembic/versions/003_f2_knowledge_tables.py` — crea 8 tablas Phase 2 + extensión `vector` + índices HNSW

**Modificados:**
- `pyproject.toml` — agrega `pgvector`, `sentence-transformers` como dependencias
- `src/diana/infrastructure/db/models.py` — agrega 8 modelos ORM (Profile, Memory, Context, Policy, Example, StagingCandidate, GrayZoneQuery, LearningMetric)

**Nota (actualizada a 2026-08-21)**: Este párrafo preveía que `learning_metrics`, `profiles` y `contexts` quedaran reservados para Fase 3. Hoy la Fase 3 está implementada: `learning_metrics` es una tabla existente y usada (agregación semanal en `src/diana/jobs/metrics.py` y `src/diana/application/metrics_service.py`); `profiles` y `contexts` están implementados y poblados (extracción post-turno `extract_post_turn`, backfill y `replace_vip_profile` en `src/diana/infrastructure/db/repositories/memories.py`). Ver `docs/SPEC-FASE3.md` y `docs/ARCHITECTURE.md`.

**Nota (2026-08-21, bases vectoriales)**: `contexts` quedó creada en la migración 003 pero sin repo ni escritor hasta ahora. Con esta actualización se implementó su fin de diseño (REQ-MEM-06): `ContextsRepo` + `ContextStoreService` post-turno (flag `FEATURE_CONTEXT_ENABLED`) persisten el contexto interpretado con embedding y expiración, y `ContextRetriever` lo lee con fallback a la derivación en vivo. Además `ProfilesRepo` ahora computa embeddings reales del contenido (antes ceros) y expone `find_by_similarity`. `FEATURE_MEMORY_ENABLED` alineado a `true` también en `system_config` (la semilla 003 lo dejó en `false`).

### H1: EmbeddingService — **cumplido**
**Nuevo archivo:**
- `src/diana/cognitive/embedding.py` — `EmbeddingService` con `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dims), método `embed(text) -> list[float]`, carga lazy del modelo

### H2: Retrievers reales (Memory, Policy, Examples) — **cumplido**
**Reemplazan stubs existentes:**
- `src/diana/cognitive/retrievers/memory.py` — `MemoryRetriever`: recibe `vip_id` + `query_text`, genera embedding, busca en `memories` con `WHERE vip_id = :vip_id AND cosine_similarity > 0.75`, devuelve `list[Memory]` formateadas como texto para el contexto
- `src/diana/cognitive/retrievers/policy.py` — `PolicyRetriever`: busca en `policies` activas con `cosine_similarity > 0.8`, filtra por scope (all o segmento del VIP), devuelve `list[Policy]`
- `src/diana/cognitive/retrievers/examples.py` — `ExamplesRetriever`: busca en `examples` con `cosine_similarity > umbral`, top-k=5, 10% de probabilidad de incluir un contraejemplo

**Nuevos repositorios SQL:**
- `src/diana/infrastructure/db/repositories/memories.py`
- `src/diana/infrastructure/db/repositories/policies.py`
- `src/diana/infrastructure/db/repositories/examples.py`

### H3: StagingService — **cumplido**
**Nuevo archivo:**
- `src/diana/application/staging_service.py` — `StagingService` con métodos `save_correction()`, `promote_to_example()`, `promote_to_policy()`, `discard()`
- `src/diana/infrastructure/db/repositories/staging.py` — repo SQL para `staging_candidates`

**Flujo**: Dueña corrige borrador → `save_correction()` guarda en staging → notificación con botones "Promover a Ejemplo" | "Promover a Política" | "Descartar" → confirmación explícita requerida

### H4: GrayZoneService + PolicyDistiller — **cumplido**
**Nuevos archivos:**
- `src/diana/application/gray_zone_service.py` — `GrayZoneService` con `create_query()`, `resolve_with_doctrine()`, `freeze_vip()`, `unfreeze_vip()`, `expire_old_queries()`
- `src/diana/cognitive/policy_distiller.py` — `PolicyDistiller.distill_from_text()` usa LLM para extraer trigger, rule, scope, ejemplo de texto libre
- `src/diana/infrastructure/db/repositories/gray_zone.py` — repo SQL para `gray_zone_queries`

**Congelación VIP**: Se implementa como un flag `frozen_until` en la tabla `vips`. El Behavior Engine y los middlewares verifican este flag para rechazar I/O.

### H5: Extender Decider (consult_doctrine) — **cumplido**
**Modificado:**
- `src/diana/cognitive/models.py` — `Decision.action` pasa de `Literal["approve", "escalate"]` a `Literal["approve", "escalate", "consult_doctrine"]`
- `src/diana/cognitive/decider.py` — Nueva regla prioridad 2:
  ```
  if comprehension.needs_policy == true AND policy_retrieval_result == empty AND FEATURE_GRAY_ZONE_ENABLED
    → action="consult_doctrine", reason="doctrine_not_found"
  ```
  El Decider ahora recibe `retrieved: dict | None` como parámetro adicional para verificar si `knowledge.policy` está vacío.

### H6: Extender TurnOrchestrator + AdminService — **cumplido**
**Modificados:**
- `src/diana/application/turn_orchestrator.py` — Nuevo branch para `decision.action == "consult_doctrine"`:
  1. `GrayZoneService.create_query()` → guarda query, congela VIP
  2. Notifica a la dueña con la pregunta y borrador
  3. No llama a BehaviorEngine.deliver
- `src/diana/application/admin_service.py` — Nuevo método `send_doctrine_query()` para notificar zona gris a la dueña con botones de respuesta. Maneja la respuesta de doctrina de la dueña (texto libre + confirmación de generalización).

### H7: Feature Flag System — **cumplido**
**Modificado:**
- `src/diana/infrastructure/db/repositories/system_config.py` — Agregar método `get_feature_flags()` que lee las keys `FEATURE_*` de `system_config`
- `src/diana/config.py` — Agregar defaults para feature flags

**Flags y defaults** (todos `false` para mantener compatibilidad F1):
- `FEATURE_MEMORY_ENABLED`
- `FEATURE_GRAY_ZONE_ENABLED`
- `FEATURE_STAGING_ENABLED`
- `FEATURE_SANDBOX_ENABLED`

**Estado actual (2026-08-21)**: los cuatro flags están activos en runtime (`true`), habilitando memoria, zona gris, staging y sandbox. Ver `docs/ARCHITECTURE.md` §4.

Cada componente nuevo verifica su flag correspondiente antes de actuar. Si está desactivado, se comporta exactamente como en Fase 1 (stubs devuelven None, no hay zona gris, correcciones se ignoran).

### H8: Sandbox Mode — **cumplido**
**Modificado:**
- `src/diana/behavior/engine.py` — Ya tiene soporte para `fake_delivery` mode
- `src/diana/application/sandbox.py` — `SandboxService`: crea perfiles ficticios, aísla traces en tabla separada o marca `sandbox=true`
- `src/diana/composition.py` — Si `FEATURE_SANDBOX_ENABLED`, wiring alternativo con FakeDelivery

### H9: Expiration Job para Gray Zone Queries — **cumplido**
**Nuevo archivo:**
- `src/diana/jobs/gray_zone_expiration.py` — `GrayZoneExpirationJob`: tarea asyncio que corre cada N minutos, consulta queries expiradas (`freeze_until < now() - timeout`), ejecuta acción configurable (`escalate` por defecto, o `use_draft`), notifica a la dueña

**Modificado:**
- `src/diana/main.py` — Inicia el job como background task durante `async_main()`

### H10: Composición y Wiring — **cumplido**
**Modificado:**
- `src/diana/composition.py` — `build_app()` actualizado para:
  1. Instanciar `EmbeddingService`
  2. Reemplazar stubs en `build_default_registry()` con retrievers reales (si flags activos)
  3. Instanciar `StagingService`, `GrayZoneService`, `PolicyDistiller`
  4. Inyectar `GrayZoneService` en `TurnOrchestrator`
  5. Pasar `retrieved` del Director al Decider (nueva dependencia)

### H11: Tests — **cumplido**
**Nuevos archivos de test:**
- `tests/unit/cognitive/test_memory_retriever.py`
- `tests/unit/cognitive/test_policy_retriever.py`
- `tests/unit/cognitive/test_examples_retriever.py`
- `tests/unit/cognitive/test_embedding.py`
- `tests/unit/cognitive/test_policy_distiller.py`
- `tests/unit/application/test_staging_service.py`
- `tests/unit/application/test_gray_zone_service.py`
- `tests/unit/application/test_sandbox.py`
- `tests/unit/cognitive/test_decider_f2.py` — extiende tests existentes con consult_doctrine
- `tests/unit/application/test_turn_orchestrator_f2.py` — extiende con routing de consult_doctrine

**Modificados:**
- `tests/unit/cognitive/test_decider.py` — agrega casos de consult_doctrine
- `tests/unit/cognitive/test_registry.py` — verifica que retrievers reales se registran correctamente

---

## Orden de implementación ejecutado

```
H0 (migración) → H1 (embeddings) → H2 (retrievers)
  → H3 (staging) → H4 (gray zone + distiller)
  → H5 (decider) → H6 (orchestrator)
  → H7 (feature flags) → H8 (sandbox)
  → H9 (expiration job) → H10 (wiring) → H11 (tests)
```

Este orden se ejecutó en su totalidad. Los hitos H0-H2 fueron bloqueantes para todo lo demás; H3 y H4 se hicieron en paralelo; H5-H6 dependieron de H4; H7 fue transversal; H8-H9 fueron independientes entre sí. Todos los hitos quedaron cumplidos.

---

## Archivos clave a modificar (resumen)

| Archivo | Tipo de cambio |
|---------|---------------|
| `src/diana/cognitive/models.py` | Añadir `consult_doctrine` a Decision.action, nuevos modelos F2 |
| `src/diana/cognitive/decider.py` | Nueva regla consult_doctrine, recibe `retrieved` |
| `src/diana/cognitive/director.py` | Pasar `retrieved` al Decider |
| `src/diana/application/turn_orchestrator.py` | Nuevo branch `consult_doctrine` |
| `src/diana/application/admin_service.py` | Manejo de respuestas de doctrina |
| `src/diana/composition.py` | Wiring de 6+ nuevos servicios |
| `src/diana/config.py` | Feature flag defaults |
| `src/diana/infrastructure/db/models.py` | 8 nuevos modelos ORM |
| `src/diana/main.py` | Iniciar expiration job |
| `pyproject.toml` | pgvector, sentence-transformers |

## Archivos a crear (resumen)

| Archivo | Responsabilidad |
|---------|----------------|
| `alembic/versions/003_f2_knowledge_tables.py` | Migración Phase 2 |
| `src/diana/cognitive/embedding.py` | EmbeddingService |
| `src/diana/cognitive/policy_distiller.py` | PolicyDistiller |
| `src/diana/application/staging_service.py` | StagingService |
| `src/diana/application/gray_zone_service.py` | GrayZoneService |
| `src/diana/application/sandbox.py` | SandboxService |
| `src/diana/infrastructure/db/repositories/memories.py` | MemoriesRepo |
| `src/diana/infrastructure/db/repositories/policies.py` | PoliciesRepo |
| `src/diana/infrastructure/db/repositories/examples.py` | ExamplesRepo |
| `src/diana/infrastructure/db/repositories/staging.py` | StagingRepo |
| `src/diana/infrastructure/db/repositories/gray_zone.py` | GrayZoneRepo |
| `src/diana/jobs/gray_zone_expiration.py` | Expiration job |

---

## Verificación

> **Estado: verificación ejecutada** — la Fase 2 quedó implementada y desplegada (2026-08-21); los flujos canónicos 6.1–6.4 (memoria, zona gris, staging, sandbox) están activos según `docs/ARCHITECTURE.md` §4.

1. **Migración**: `alembic upgrade head` crea todas las tablas sin errores
2. **Tests unitarios**: `pytest tests/ -x` — todos los tests existentes F1 pasan sin modificaciones (compatibilidad hacia atrás)
3. **Tests F2**: `pytest tests/unit/cognitive/test_embedding.py tests/unit/cognitive/test_memory_retriever.py tests/unit/cognitive/test_decider_f2.py -x`
4. **Feature flags off**: Con todos los flags en `false`, el sistema se comporta exactamente como Fase 1 (stubs devuelven None, no hay zona gris, correcciones se ignoran)
5. **Feature flags on**: Activar flags uno a uno y verificar cada flujo canónico (6.1 memoria, 6.2 zona gris, 6.3 staging, 6.4 sandbox)
6. **Import purity**: `tests/unit/cognitive/test_import_purity.py` sigue pasando (cognitive no importa aiogram)
7. **Anti-contaminación**: `WHERE vip_id = :vip_id` en MemoryRetriever es obligatorio y testeado
