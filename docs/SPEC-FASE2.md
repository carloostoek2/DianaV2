SPEC-FASE2.md — MVP+ (Memoria, Aprendizaje Controlado y Zona Gris)

Diana Business Bot / Sistema de Automatización de Chats VIP

Campo Valor
Nivel Contrato de diseño e implementación para la Fase 2
Basado en SPEC.md v1.5 (Híbrido) + REQUERIMIENTOS.md v2.1 (Bloques MEM, TRN, GAP, EVAL)
Audiencia Ingeniería
Versión 2.1 — MVP+ (Revisión Post-Review)
Estado Aprobado para implementación (sobre base de Fase 1)
Documentos relacionados Anexos_contratos.md (contratos detallados de todos los nodos)

---

Índice

1. Propósito de esta Fase
2. Alcance de la Fase 2
3. Feature Toggles (Activación gradual)
4. Modelo de Datos (Incremento sobre Fase 1)
5. Contratos de los Nuevos Componentes
6. Flujos Canónicos de Fase 2
7. Integración con Fase 1 (Estrategia de Migración)
8. Roadmap de Implementación (Fase 2)
9. Trazabilidad REQ → Componentes de Fase 2
10. Decisiones de Diseño Abiertas
11. Relación con los Anexos
12. Notas Finales

---

1. Propósito de esta Fase

Transformar el "bot supervisado" de la Fase 1 en un sistema que aprende y razona con memoria.

Objetivos concretos:

1. Memoria real: Recuperar hechos y preferencias de cada VIP (Memories) usando vectores.
2. Doctrina reutilizable: Resolver dudas de negocio (Zona Gris) y convertirlas en Policies estructuradas.
3. Aprendizaje controlado: Capturar correcciones de la dueña en un Staging Area y promoverlas solo bajo confirmación explícita.
4. Evaluación calibrable: Empezar a registrar perfiles para ajustar umbrales empíricamente.
5. Sustituibilidad total: Mantener la misma interfaz de Capability Registry, de modo que activar estas capacidades no requiera modificar el Director ni el Planificador.

---

2. Alcance de la Fase 2

2.1 Dentro de alcance

ID Área
F2-01 Implementación real de los Retrievers memory, policy y examples con pgvector.
F2-02 Mecanismo de Zona Gris: congelación del VIP, consulta a la dueña, destilación de políticas estructuradas con confirmación de generalización y paso por Staging.
F2-03 Staging Area: captura de correcciones como candidatos, promoción explícita a examples o policies.
F2-04 Evaluación con registro de perfiles para calibración futura (REQ-EVAL).
F2-05 Feature flags para activar/desactivar cada capacidad sin redeploy (REQ-ADM-03).
F2-06 Sandbox con FakeDelivery (para pruebas sin afectar producción).
F2-07 Expiración automática de consultas de zona gris (REQ-GAP-07) con acción configurable.

2.2 Fuera de alcance (postergado a Fase 3 o posterior)

ID Exclusión
F2-O1 Modo autónomo (send directo sin aprobación).
F2-O2 Recontacto por silencio.
F2-O3 Promo no-VIP.
F2-O4 Calibración automática de umbrales (solo registro de datos).
F2-O5 Behavior Engine avanzado (mensajes divididos, quirks humanos).
F2-O6 Listado y desactivación de políticas desde el DM (REQ-GAP-08, P2). Se posterga a Fase 3 o herramienta administrativa.

---

3. Feature Toggles (Activación gradual)

Todos los nuevos comportamientos de Fase 2 deben estar envueltos en feature flags almacenados en system_config. Los valores por defecto son false para mantener compatibilidad con Fase 1.

Flag Descripción Valor en Fase 2
FEATURE_MEMORY_ENABLED Habilita Retrievers reales de memoria, políticas y ejemplos true
FEATURE_GRAY_ZONE_ENABLED Habilita el flujo de consult_doctrine y congelación true
FEATURE_STAGING_ENABLED Habilita la captura de correcciones en Staging Area true
FEATURE_SANDBOX_ENABLED Habilita el modo sandbox con FakeDelivery true

Regla de implementación:
Si un flag está desactivado, el sistema debe comportarse exactamente como en Fase 1 (stubs devuelven null, las correcciones se ignoran, no hay zona gris). Esto permite un rollback instantáneo cambiando solo la configuración.

---

4. Modelo de Datos (Incremento sobre Fase 1)

Las tablas ya existen en el esquema de la Fase 1 (creadas para evitar migraciones rotas). En Fase 2 se implementan los repositorios que las llenan y consultan. A continuación se detallan las entidades clave:

4.1 Tablas ya existentes (sin cambios)

· profiles (perfil permanente del VIP)
· memories (hechos y preferencias, con embedding)
· contexts (contexto temporal interpretado, con expiración)
· policies (doctrina estructurada, con embedding)
· examples (banco vivo de few-shots, con embedding)
· staging_candidates (candidatos a ejemplo/política)
· gray_zone_queries (consultas abiertas)
· learning_metrics (reservada para Fase 3)

4.2 Índices requeridos (crear en Fase 2)

```sql
-- Índices HNSW para búsqueda vectorial
CREATE INDEX CONCURRENTLY IF NOT EXISTS memories_embedding_idx ON memories USING hnsw (embedding vector_cosine_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS policies_embedding_idx ON policies USING hnsw (embedding vector_cosine_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS examples_embedding_idx ON examples USING hnsw (embedding vector_cosine_ops);

-- Índices de filtrado
CREATE INDEX CONCURRENTLY IF NOT EXISTS memories_vip_id_idx ON memories (vip_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS policies_active_idx ON policies (is_active, valid_until);
CREATE INDEX CONCURRENTLY IF NOT EXISTS gray_zone_status_idx ON gray_zone_queries (status, freeze_until);
```

4.3 Nuevos repositorios a implementar

Repositorio Tabla Responsabilidad
MemoryRetriever memories Buscar por similitud semántica + vip_id (anti-contaminación)
PolicyRetriever policies Buscar políticas activas por similitud semántica y scope
ExamplesRetriever examples Buscar ejemplos (y ocasionalmente contraejemplos) por similitud
StagingService staging_candidates Guardar correcciones, promover a examples o policies
GrayZoneService gray_zone_queries Crear consultas, congelar/descongelar VIP, gestionar expiración

---

5. Contratos de los Nuevos Componentes

Los contratos detallados de todos los nodos cognitivos (incluyendo los ya existentes en Fase 1) se encuentran en el documento Anexos_contratos.md. Aquí se resumen las extensiones específicas de Fase 2.

5.1 Planificador (extensión)

Ahora debe solicitar todas las capacidades que el Analista marque como necesarias, incluyendo knowledge.memory, knowledge.policy y knowledge.examples.

Ver Anexo C para el contrato completo.

5.2 Retrievers reales (reemplazan stubs)

Retriever Entrada Salida Invariante
MemoryRetriever vip_id, query (texto) Lista de Memory con similitud > umbral (0.75) WHERE vip_id = :vip_id es obligatorio
PolicyRetriever query, vip_id (opcional) Lista de Policy activas con similitud > umbral (0.8) Solo políticas con scope='all' o scope coincidente con segmento del VIP
ExamplesRetriever query Lista de Example (top-k = 3-5) Puede incluir ocasionalmente un contraejemplo (10% de veces)

Ver Anexo H para el contrato completo del Capability Registry y los Retrievers.

5.3 Constructor de Contexto (extensión)

Incluye los nuevos bloques en el orden fijo (Anexo D):

1. Persona/voz
2. Historial
3. Contexto temporal
4. Memoria (si se recuperó)
5. Políticas (si se recuperaron)
6. Ejemplos (si se recuperaron)
7. Turno actual

Nota: Si un bloque devuelve null o lista vacía, la sección correspondiente no aparece en el prompt (mantiene el principio de mínimo conocimiento necesario).

5.4 Decisor (extensión) — Con prioridad explícita

Se añade una nueva regla de acción, evaluada en el siguiente orden (prioridad de arriba a abajo):

Prioridad Condición Acción bruta Filtro de modo Acción final
1 perfil.seguridad < umbral_seguridad Escalar No se filtra Escalar
2 comprension.needs_policy == true Y policy_retrieval_result == vacío Y FEATURE_GRAY_ZONE_ENABLED Consultar doctrina No se filtra Consultar doctrina
3 perfil.naturalidad < umbral_naturalidad Regenerar No se filtra Regenerar (si implementado)
4 Ninguna de las anteriores Enviar supervisado → Aprobar Aprobar

Nota: La condición de zona gris usa policy_retrieval_result == vacío como disparador principal. Esto evita que la decisión dependa de umbrales numéricos de doctrina que podrían descalibrarse. El Evaluador, en caso de needs_policy=true y sin políticas, asigna doctrina = 0.2 (bajo) como señal complementaria.

Ver Anexo F para el contrato completo del Decisor.

5.5 Evaluador (precisión sobre doctrina)

El Evaluador debe comportarse así respecto a la dimensión doctrina:

Situación Valor de doctrina Razón
needs_policy=false 0.7 (neutral) No se espera que el Generador aplique políticas, no se penaliza ni premia.
needs_policy=true Y policy_retrieval_result != vacío Valor real evaluado (0–1) Mide coherencia con las políticas encontradas.
needs_policy=true Y policy_retrieval_result == vacío 0.2 (bajo) Indica ausencia de doctrina; el Decisor usará la condición explícita para activar zona gris.

Nota: Este esquema separa la señal de "falta de política" (que activa zona gris) de la señal de "incoherencia con políticas existentes" (que podría escalar o regenerar). Ambas son manejadas por el Decisor en prioridades diferentes.

Ver Anexo B.3 para la definición completa.

5.6 Nuevos servicios

StagingService

```python
class StagingService:
    async def save_correction(turn_id, original_draft, corrected_text, context) -> StagingCandidate
    async def promote_to_example(candidate_id) -> Example
    async def promote_to_policy(candidate_id, trigger, rule, scope) -> Policy
    async def discard(candidate_id)
```

Regla clave: Toda nueva política (de zona gris o manual) debe pasar por promote_to_policy(), que escribe en staging_candidates y espera confirmación explícita. No se crean políticas directamente desde GrayZoneService.

GrayZoneService

```python
class GrayZoneService:
    async def create_query(vip_id, turn_id, question, draft) -> GrayZoneQuery
    async def resolve_with_doctrine(query_id, generalization, rule) -> None
        # Crea un StagingCandidate de tipo 'policy' con el payload
        # La dueña debe confirmar la promoción para que la política sea activa
        # Solo entonces se cierra la gray_zone_query y se descongela al VIP
    async def freeze_vip(vip_id, duration)
    async def unfreeze_vip(vip_id)
    async def expire_old_queries(timeout_hours=24) -> None
        # Marca como expired las queries con freeze_until < now() - timeout
        # Ejecuta acción configurable: 'use_draft' o 'escalate'
```

PolicyDistiller

```python
class PolicyDistiller:
    async def distill_from_text(question: str, answer: str, generalization: str) -> Policy
    # Crea un objeto Policy estructurado: trigger_description, rule, scope, ejemplo_aplicado
    # Se usa como helper dentro del flujo de staging
```

---

6. Flujos Canónicos de Fase 2 (Activos con Feature Flags)

6.1 Turno VIP con recuperación de memoria

```
business_message
  → TurnCoordinator (igual que Fase 1)
  → Director
      → Analista → Comprehension (needs_memory = true)
      → Planificador → solicita "knowledge.memory" (y otras)
      → Registry → MemoryRetriever (real, con pgvector)
      → Constructor de Contexto → incluye bloque de memoria
      → Generador → borrador informado por memoria
      → Evaluador → perfil (doctrina según tabla 5.5)
      → Decisor → approve (si todo OK)
  → Cola de aprobación → dueña aprueba o corrige
  → Behavior Engine → entrega
  → Learning → registra traza (y si hubo corrección, Staging si flag activo)
```

6.2 Zona Gris (consult_doctrine) — Flujo completo

```
Decisor emite action = "consult_doctrine"
  → GrayZoneService.create_query()
      → gray_zone_queries status = 'open'
      → VIP marcado como frozen
      → Notificación a la dueña con pregunta y borrador sugerido
      → Behavior Engine rechaza cualquier I/O hacia ese chat
  → Dueña responde con texto libre y confirma generalización
      → Ejemplo: "Siempre ofrecer descuento del 10% si pide 3 unidades"
      → Generalización: "Siempre que pregunten por cantidad >= 3"
  → PolicyDistiller crea objeto Policy estructurado (en memoria)
  → Se guarda en staging_candidates con tipo 'policy', status='pending'
  → La dueña recibe notificación: "¿Promover esta política a vigente?"
  → SI confirma:
      → StagingService.promote_to_policy() → se activa la política (is_active=true)
      → Se cierra gray_zone_query (status='resolved')
      → Se descongela VIP
      → Se retoma el turno (re-ejecución o re-generación con nueva política)
  → SI NO confirma:
      → Se descarta el candidato (staging_candidates status='discarded')
      → Se cierra gray_zone_query (status='resolved') pero sin política
      → Se descongela VIP
      → El turno se maneja según decisión de la dueña (aprueba el borrador original)
  → SI la dueña no responde en GRAY_ZONE_TIMEOUT_HOURS (default 24h):
      → GrayZoneService.expire_old_queries() marca como 'expired'
      → Ejecuta acción configurable: 'escalate' (por defecto) o 'use_draft'
      → Se notifica a la dueña la expiración
```

Congelación: dura hasta que la política sea confirmada, descartada o expire. El tiempo máximo de congelación es GRAY_ZONE_TIMEOUT_HOURS (configurable).

6.3 Corrección → Staging

```
Dueña corrige borrador en DM
  → Se envía el texto corregido al VIP (BehaviorEngine)
  → SI FEATURE_STAGING_ENABLED:
      StagingService.save_correction(turn_id, original_draft, corrected_text, context)
      → Se notifica a la dueña: "Corrección guardada en Staging. ¿Usar como ejemplo?"
      → Botones: "Promover a Ejemplo" | "Promover a Política" | "Descartar"
  → SI NO (Fase 1): solo se envía y ya.
```

6.4 Sandbox (pruebas aisladas)

```
Dueña activa sandbox desde DM (FEATURE_SANDBOX_ENABLED = true)
  → Se crean perfiles ficticios (no tocan VIP reales)
  → El pipeline se ejecuta completo, pero Behavior Engine usa FakeDelivery
  → No se persisten trazas en producción (se guardan en tabla de sandbox aparte)
  → No se escribe en memorias/políticas reales
```

---

7. Integración con Fase 1 (Estrategia de Migración)

Para evitar interrupciones, la activación de Fase 2 se hará en pasos:

1. Crear índices (sin bloquear escrituras, usando CONCURRENTLY).
2. Cargar políticas iniciales (si la dueña tiene reglas de negocio claras) mediante un script de seed.
3. Activar feature flags uno a uno:
   · Primero FEATURE_MEMORY_ENABLED (menos riesgoso, solo agrega información al contexto).
   · Luego FEATURE_STAGING_ENABLED (empieza a capturar correcciones, sin promover automáticamente).
   · Finalmente FEATURE_GRAY_ZONE_ENABLED (el más delicado, requiere que la dueña entienda el flujo).
4. Monitorear métricas de aprobación y repetición de zona gris para validar mejora.

Rollback: Basta con desactivar los flags correspondientes en system_config; el sistema vuelve a comportamiento de Fase 1 sin necesidad de redeploy.

---

8. Roadmap de Implementación (Fase 2)

Hito Descripción Dependencias
H2.1 Implementar MemoryRetriever, PolicyRetriever, ExamplesRetriever con pgvector. Índices HNSW creados.
H2.2 Implementar StagingService (guardar, promover, descartar). Tabla staging_candidates existente.
H2.3 Implementar GrayZoneService y PolicyDistiller. Tablas gray_zone_queries y policies.
H2.4 Extender Planner para solicitar todas las capacidades. Contratos de Retrievers listos.
H2.5 Extender Decisor con regla de consult_doctrine (envuelta en flag). —
H2.6 Modificar Director para manejar la nueva acción. —
H2.7 Implementar sandbox con FakeDelivery. Behavior Engine ya tiene interfaz.
H2.8 Implementar job de expiración de gray_zone_queries (configurable). —
H2.9 Unificar flujo de promoción de políticas vía Staging (zona gris + manual). H2.2, H2.3
H2.10 Actualizar AGENTS.md para marcar flujos como activos. —
H2.11 Pruebas de integración y activación gradual de flags. Todos los anteriores

Criterio de salida de Fase 2:
El sistema puede recordar hechos de conversaciones anteriores, resolver dudas de doctrina sin repetir preguntas (con políticas que pasan por Staging), capturar correcciones para mejorar futuras respuestas, y manejar expiración de consultas de zona gris.

---

9. Trazabilidad REQ → Componentes de Fase 2

Bloque REQ Componente(s)
REQ-MEM-01..07 MemoryRetriever, ContextRetriever, ProfileRetriever, anti-contaminación
REQ-TRN-01..09 StagingService, ExamplesRetriever, fuentes de señal
REQ-GAP-01..11 GrayZoneService, PolicyRetriever, PolicyDistiller, Decisor, StagingService
REQ-EVAL-01..04 Evaluator (registro de perfiles), métricas básicas
REQ-COG-14 SandboxService + FakeDelivery
REQ-ADM-03 Feature flags + hot-swap de LLM (ya existe en Fase 1)
REQ-NFR-16 StagingArea (confirmación explícita)

---

10. Decisiones de Diseño Abiertas (para resolver en implementación)

1. Umbral de similitud para MemoryRetriever: Se sugiere 0.75 (distancia coseno). ¿Se calibra con datos reales o se deja fijo hasta Fase 3?
2. Frecuencia de inclusión de contraejemplos: 10% de las veces, ¿es adecuado o se configura por VIP?
3. Duración de congelación en zona gris (GRAY_ZONE_TIMEOUT_HOURS): Se propone 24h configurable. ¿Es suficiente o se necesita más?
4. Acción por defecto ante expiración de zona gris: Se recomienda "escalate" (seguridad), pero podría ser "use_draft" (envía el borrador original) si la dueña prefiere no dejar al VIP sin respuesta.
5. Modelo de embeddings: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (384 dims). ¿Se mantiene o se cambia a API en Fase 2?

---

11. Relación con los Anexos

Todos los contratos detallados de los nodos (entrada/salida, invariantes, manejo de errores) se especifican en el documento Anexos_contratos.md, que forma parte integral de este SPEC. Las secciones de los anexos que han sido modificadas o extendidas en esta Fase 2 son:

Anexo Cambios respecto a Fase 1
Anexo B (Evaluador) Se añade la tabla de casos para doctrina según disponibilidad de políticas (Sección 5.5 de este documento).
Anexo F (Decisor) Se modifica la tabla de reglas para incluir la condición de consult_doctrine con prioridad explícita (Sección 5.4 de este documento).
Anexo H (Registry/Retrievers) Se añaden contratos para MemoryRetriever, PolicyRetriever y ExamplesRetriever reales.

---

12. Notas Finales

· Compatibilidad: Esta Fase 2 es totalmente compatible con la Fase 1. El Director, el Generador y el Behavior Engine no cambian; solo se añaden implementaciones reales detrás de las mismas interfaces.
· Rendimiento: Las búsquedas vectoriales deben ser rápidas gracias a los índices HNSW. El modelo de embeddings es ligero y se ejecuta localmente.
· Seguridad: La anti-contaminación (BR-15) se garantiza a nivel de consultas SQL (WHERE vip_id = :current). El Staging asegura que ningún ejemplo o política entre en producción sin revisión humana.
· Zona Gris: El flujo de zona gris ahora pasa por Staging, lo que añade un paso de confirmación explícita antes de que una política sea activa. Esto cumple con REQ-GAP-10/11 y BR-13, pero extiende el tiempo de congelación hasta que la dueña confirme la política (o expire). Esto es intencional y está alineado con la filosofía de control humano.

---

Fin del SPEC-FASE2.md (v2.1)
Última actualización: Julio 2026
Equipo de Arquitectura — Fase 2 lista para implementación sobre base de Fase 1, con todas las correcciones del review integradas.
