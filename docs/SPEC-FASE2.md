SPEC-FASE2.md — MVP+ (Memoria, Aprendizaje Controlado y Zona Gris)

Diana Business Bot / Sistema de Automatización de Chats VIP

Campo Valor
Nivel Contrato de diseño e implementación para la Fase 2
Basado en SPEC.md v1.5 (Híbrido) + REQUERIMIENTOS.md v2.1 (Bloques MEM, TRN, GAP, EVAL)
Audiencia Ingeniería
Versión 2.1 — MVP+ (Revisión Post-Review)
Estado Implementado y desplegado (flags activos: memoria, zona gris, staging, sandbox)
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
8. Estado de Implementación (Fase 2)
9. Trazabilidad REQ → Componentes de Fase 2
10. Decisiones resueltas
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
F2-02 Mecanismo de Zona Gris: congelación del VIP/Atención, consulta a la dueña por una REGLA, persistencia viva en policies, regen del mismo turno con force-inject, cola de aprobación; freeze hasta envío real. Staging queda para correcciones (no para el resolve de zona gris).
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
F2-O6 Listado y desactivación de políticas desde el DM (REQ-GAP-08, P2). Sigue sin implementarse; no se observa evidencia en el código actual.

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
· learning_metrics (tabla existente, grupo de Fase 3)

Hoy las tablas de la Fase 2 se pueblan y consultan mediante repositorios reales: `memories` y `profiles` se escriben vía extracción post-turno (`memory_extraction_service`), backfill (`memory_backfill_service`) y actualización de perfil (`replace_vip_profile`) en cada finalización exitosa.

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

Prioridad Condición Acción Nota
1 perfil.seguridad < umbral_seguridad Escalar Prioridad absoluta (seguridad)
2 comprension.needs_policy == true Y policy_retrieval_result == vacío Y FEATURE_GRAY_ZONE_ENABLED Consultar doctrina Puede resolver el riesgo raíz
3 comprension.risk == "alto" Escalar Riesgo semántico, pero solo si no hay doctrina pendiente
4 perfil.naturalidad < umbral_naturalidad Regenerar (si implementado)
5 Ninguna de las anteriores Aprobar 

Aclaración: La escalación por riesgo semántico (paso 3) solo se alcanza si no se activó la zona gris (paso 2). Si el riesgo alto va acompañado de falta de política, gana la zona gris. Si el riesgo alto va acompañado de seguridad baja, gana la escalación por seguridad (paso 1).

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

Regla clave (actualizada): Las políticas que nacen del **resolve de zona gris** se insertan **vivas** en `policies` (GrayZoneService.persist_live_policy) sin `staging_candidates`. Las políticas/ejemplos que nacen de **correcciones** o de la UI `/staging` siguen pasando por `promote_to_policy()` / Staging. No mezclar ambos caminos.

GrayZoneService

```python
class GrayZoneService:
    async def create_query(vip_id, turn_id, question, draft) -> GrayZoneQuery
    async def persist_live_policy(query_id, rule_text, *, vip_id, scope) -> Policy
        # Inserta policies activa; NO escribe staging_candidates; NO descongela
    async def mark_awaiting_send(query_id) -> None
        # status='awaiting_send'; freeze retenido
    async def close_awaiting_send(query_id, *, unfreeze: bool) -> None
        # status='resolved' + unfreeze opcional (tras send exitoso)
    async def discard_and_close(...)  # escalate/paracaídas: libera freeze
    async def freeze_vip(vip_id, duration)
    async def unfreeze_vip(vip_id)
    async def expire_old_queries(timeout_hours=24) -> None
        # Solo expira status='open' (NO awaiting_send)
        # Ejecuta acción configurable: 'use_draft' o 'escalate' con query.draft original
```

PolicyDistiller

```python
class PolicyDistiller:
    async def distill_from_text(question: str, answer: str, generalization: str) -> Policy
    # Helper opcional para armar trigger_description + rule desde texto de la dueña
    # En resolve de zona gris puede usarse con answer="" / rule-as-generalization
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

6.2 Zona Gris (consult_doctrine) — Flujo completo (supersede: resolve ya no pasa por Staging)

```
Decisor emite action = "consult_doctrine"
  → GrayZoneService.create_query()
      → gray_zone_queries status = 'open'
      → VIP/Atención congelado
      → DM a la dueña: pregunta + borrador sugerido (contexto); pide REGLA
      → Teclado: 📝 Escribir regla | ⚠️ Escalar  (sin "✅ Usar borrador")
  → Dueña escribe la REGLA + alcance Solo este VIP / A todos
  → AdminService (orquestación):
      → persist_live_policy → fila activa en policies (sin staging_candidates)
      → Director.handle_turn(..., knowledge_overrides) force-inject de la regla
      → Si regen ok: supervised approval con borrador REGENERADO;
         query → 'awaiting_send' (NO descongela)
      → Si regen falla / consult_doctrine de nuevo: desactivar policy; freeze retenido; avisar
  → Dueña aprueba/corrige/escala el borrador regenerado (cola normal)
  → Send exitoso → close_awaiting_send(unfreeze=True)
  → Escalate/discard → liberar freeze; conservar policy viva (salvo fallo de regen)
  → SI la dueña no responde en GRAY_ZONE_TIMEOUT_HOURS (default 24h):
      → expire solo status='open' (no awaiting_send)
      → usa query.draft original → supervisión o escalate (legado)
```

Congelación: desde `consult_doctrine` hasta envío real exitoso (o escalate/discard). Status `open` y `awaiting_send` cuentan como freeze. El timeout máximo de consultas `open` es GRAY_ZONE_TIMEOUT_HOURS (configurable).

Nota: el camino Staging (`resolve_with_doctrine` + `confirm_and_apply` / `promote_to_policy`) queda **superseded para el resolve de zona gris**; Staging permanece para correcciones (FEATURE_STAGING_ENABLED) y UI `/staging`.

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

8. Estado de Implementación (Fase 2)

La Fase 2 está implementada y desplegada. Los cuatro flags de la Sección 3 están activos en el entorno de ejecución (`FEATURE_MEMORY_ENABLED`, `FEATURE_GRAY_ZONE_ENABLED`, `FEATURE_STAGING_ENABLED`, `FEATURE_SANDBOX_ENABLED` = `true`). Ver `docs/ARCHITECTURE.md` §4 para el estado de flags y §3 para los flujos canónicos tal como operan hoy.

Hito Descripción Estado
H2.1 Implementar MemoryRetriever, PolicyRetriever, ExamplesRetriever con pgvector. Índices HNSW creados. Implementado
H2.2 Implementar StagingService (guardar, promover, descartar). Tabla staging_candidates existente. Implementado
H2.3 Implementar GrayZoneService y PolicyDistiller. Tablas gray_zone_queries y policies. Implementado
H2.4 Extender Planner para solicitar todas las capacidades. Contratos de Retrievers listos. Implementado
H2.5 Extender Decisor con regla de consult_doctrine (envuelta en flag). Implementado
H2.6 Modificar Director para manejar la nueva acción. Implementado
H2.7 Implementar sandbox con FakeDelivery. Behavior Engine ya tiene interfaz. Implementado
H2.8 Implementar job de expiración de gray_zone_queries (configurable). Implementado
H2.9 (histórico) Unificar promoción de políticas vía Staging. **Superseded para resolve de zona gris:** live persist + regen; Staging permanece para correcciones/UI.
H2.10 Actualizar AGENTS.md para marcar flujos como activos. Implementado
H2.11 Pruebas de integración y activación gradual de flags. Implementado

Criterio de salida de Fase 2 (cumplido):
El sistema recuerda hechos de conversaciones anteriores, resuelve dudas de doctrina sin repetir preguntas (políticas vivas desde zona gris + Staging para correcciones), captura correcciones para mejorar futuras respuestas, y maneja la expiración de consultas de zona gris `open`.

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

10. Decisiones resueltas (implementadas)

1. Umbral de similitud para MemoryRetriever: fijado en 0.75 (distancia coseno), constante `DEFAULT_MEMORY_THRESHOLD` en `src/diana/cognitive/retrievers/memory.py`. El PolicyRetriever usa 0.8 (`DEFAULT_POLICY_THRESHOLD`) y el ExamplesRetriever 0.7. Los umbrales se mantienen fijos; la calibración automática sigue desactivada (`FEATURE_CALIBRATION_ENABLED=false`).
2. Frecuencia de inclusión de contraejemplos: se abandonó el 10% probabilístico. El ExamplesRetriever anexa un contraejemplo siempre que exista uno que coincida (límite 1), ver `src/diana/cognitive/retrievers/examples.py`.
3. Duración de congelación en zona gris (GRAY_ZONE_TIMEOUT_HOURS): confirmada en 24h configurable (`default_timeout_hours=24` en `src/diana/application/gray_zone_service.py`). El VIP/Atención permanece congelado desde la consulta hasta un envío real exitoso (o escalate/discard); el timeout aplica a queries `open` (no a `awaiting_send`).
4. Acción por defecto ante expiración de zona gris: híbrida. Si la consulta expirada tiene borrador, se convierte en aprobación pendiente supervisada (no deja al VIP sin respuesta); si no hay borrador o no hay servicio administrativo, se escala (`escalate`), ver `src/diana/jobs/gray_zone_expiration.py`.
5. Modelo de embeddings: se mantuvo `paraphrase-multilingual-MiniLM-L12-v2` (384 dims), local con sentence-transformers y carga lazy, ver `src/diana/cognitive/embedding.py` (ADR-005).

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
· Seguridad: La anti-contaminación (BR-15) se garantiza a nivel de consultas SQL (WHERE vip_id = :current). El Staging asegura que ningún ejemplo (y políticas promocionadas desde correcciones/UI) entre en producción sin revisión humana.
· Zona Gris (actualizado): el resolve pide una REGLA, la persiste viva en `policies`, regenera el mismo turno con force-inject y pone el borrador regenerado en cola de aprobación. El freeze se mantiene hasta el envío real. Staging ya no es el happy path del resolve (sí de correcciones). El control humano se ejerce al escribir la regla y al aprobar el borrador regenerado.

---

Fin del SPEC-FASE2.md (v2.1)
Última actualización: Agosto 2026
Equipo de Arquitectura — Fase 2 implementada y desplegada sobre la base de Fase 1, con todas las correcciones del review integradas.
