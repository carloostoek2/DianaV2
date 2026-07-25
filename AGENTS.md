# AGENTS.md — Límites de módulo y flujos vivos
**Diana Business Bot / Sistema de Automatización de Chats VIP**

| Campo | Valor |
|-------|--------|
| Nivel | Operación para agentes de desarrollo (humanos o IA) |
| Basado en | [`REQUERIMIENTOS.md`](REQUERIMIENTOS.md) v2.1 + [`SPEC.md`](SPEC.md) v1.0 |
| Audiencia | Desarrolladores, agentes de código, revisores |
| Versión | 1.0 |
| Idioma | Español |

---

## 1. Propósito de este documento

Este archivo define **límites duros de módulo** y **flujos canónicos** que **ningún agente** (humano o IA) puede violar al modificar el código.

Su objetivo es proteger las propiedades arquitectónicas críticas del sistema:

1. El **Director es 100 % determinista** y nunca pregunta a un LLM “qué hacer”.
2. Cada componente cognitivo responde **una sola pregunta**.
3. El **Behavior Engine** está fuera de la cognición.
4. El aprendizaje es **siempre post-turno** y controlado (Staging Area).
5. Existe **anti-contaminación** total entre la Memoria de un VIP y el banco de ejemplos.
6. Toda decisión es **reconstruible** a partir de objetos persistidos.

Si un cambio propuesto viola alguna regla de este documento, **debe ser rechazado** o re-diseñado.

---

## 2. Principio rector (no negociable)

> El sistema no genera respuestas.  
> El sistema toma decisiones.  
> Las respuestas son únicamente una consecuencia de esas decisiones.

Cualquier PR, commit o generación de código que haga que un LLM decida la acción del turno (en lugar del Decisor determinista) es un **bug de arquitectura**.

---

## 3. Mapa de módulos y límites duros

### 3.1 Capas y responsabilidad exclusiva

| Capa / Módulo | Pregunta que responde | Puede hacer | **Nunca puede hacer** |
|---------------|-----------------------|-------------|-----------------------|
| **Telegram Layer** (`telegram/`) | ¿Cómo entro y salgo de Telegram? | Recibir updates, enviar mensajes con `business_connection_id`, middlewares de short-circuit | Decidir qué decir, invocar LLM, escribir en tablas de conocimiento |
| **Application Services** (`application/` o `services/`) | ¿Qué caso de uso es este? | Orquestar TurnOrchestrator, Admin, Sandbox, Promo, Recontact | Contener lógica cognitiva, generar texto, evaluar |
| **Cognitive Core** (`cognitive/`) | ¿Qué decisión tomar? | Ejecutar el pipeline Director → … → Decisor | Conocer aiogram, enviar mensajes, escribir en Staging, decidir delays |
| **Capability Registry + Retrievers** (`cognitive/retrievers/` o `knowledge/`) | ¿Qué sabemos sobre X? | Devolver conocimiento estructurado filtrado | Mezclar tipos de conocimiento, devolver Memoria de otro VIP, decidir si se usa o no |
| **Behavior Engine** (`behavior/`) | ¿Cómo se actúa el mensaje? | Delay, read, typing, send, cancel, FakeDelivery | Generar texto, decidir acción, invocar Analista/Generador |
| **Learning** (`learning/`) | ¿Qué aprendimos de este turno? | Extraer candidatos, escribir en Staging, destilar políticas, actualizar métricas | Ejecutarse durante el pipeline de decisión, promover automáticamente a banco vivo |
| **LLM Provider** (`llm/`) | ¿Cómo hablo con el modelo? | `generate` y `generate_structured` | Contener prompts de negocio, decidir umbrales, conocer VIP |
| **Infrastructure / Persistence** | ¿Cómo guardo y recupero datos? | Repositorios, sesiones, migraciones | Contener lógica de negocio o cognitiva |

### 3.2 Reglas de dependencia (dirección permitida)

```
Telegram Layer  →  Application Services  →  Cognitive Core
                                         ↘  Behavior Engine
Application Services  →  Learning          (solo post-turno)
Cognitive Core        →  Capability Registry → Retrievers → Persistence
Cognitive Core        →  LLM Provider
Behavior Engine       →  Telegram Layer (solo para I/O)
Learning              →  Persistence
```

**Prohibido:**
- Cognitive Core importar cualquier cosa de `telegram/` o `behavior/`
- Behavior Engine importar Analista, Generador, Evaluador o Decisor
- Learning ser llamado desde dentro del Director o del pipeline de decisión
- Cualquier Retriever importar otro Retriever de tipo distinto

---

## 4. Flujos canónicos (vivos)

Estos flujos son la fuente de verdad. Un agente que los altere debe actualizar también este documento y el SPEC.

### 4.1 Turno VIP normal (pipeline completo)

```
business_message
  → Middleware stack (Auth → Forbidden → Freeze → …)
  → TurnOrchestrator.cancel_pending(chat_id)          # REQ-VIP-06
  → CognitiveDirector.handle_turn()
       1. Analyst        → Comprehension
       2. Planner        → lista de capacidades
       3. Registry       → KnowledgeBundle
       4. ContextBuilder → prompt mínimo
       5. Generator      → draft_text
       6. Evaluator      → EvaluationProfile (vector)
       7. Decider        → Decision
  → según Decision.action:
       • send      → BehaviorEngine.deliver()
       • approve   → enviar borrador al DM de la dueña
       • escalate  → notificar dueña + no responder al VIP
       • consult_doctrine → crear gray_zone + congelar VIP
       • regenerate → volver a Generator (máx. N veces)
  → Learning.run_post_turn()                          # siempre al final
```

### 4.2 Short-circuit de escalación determinística

```
business_message
  → ForbiddenKeywordsMiddleware (ANTES del Analista)
  → si match → crear Escalation + notificar dueña
  → NO se entra al Cognitive Core
```

### 4.3 Zona gris (consult_doctrine)

```
Decider → action = "consult_doctrine"
  → crear gray_zone_queries (status=open)
  → marcar VIP como frozen
  → BehaviorEngine rechaza cualquier I/O hacia ese chat
  → notificar dueña con pregunta de doctrina
  → dueña responde + confirma generalización
  → PolicyDistiller crea Policy estructurada
  → resolver gray_zone → descongelar
  → retomar flujo normal (approve o send según modo)
```

### 4.4 Corrección de la dueña → Staging

```
Dueña corrige borrador
  → se envía la versión final al VIP (vía BehaviorEngine)
  → se crea StagingCandidate(
        type="example",
        payload={original_draft, corrected_text, context},
        status="pending"
     )
  → NUNCA se escribe directamente en la tabla `examples`
  → solo pasa al banco vivo con acción explícita de la dueña (“Usar como ejemplo”)
```

### 4.5 Cancelación por mensaje nuevo (REQ-VIP-06)

```
Nuevo business_message del mismo VIP
  → TurnOrchestrator / Middleware
  → BehaviorEngine.cancel_pending(chat_id)
  → Task.cancel() + pending_deliveries.status = 'cancelled'
  → se inicia un nuevo pipeline limpio
```

### 4.6 Reinicio del proceso

```
main.py arranca
  → cargar pending_deliveries WHERE status='pending' AND scheduled_at > now() - interval
  → re-crear asyncio.Tasks o marcar como expired + notificar
  → re-notificar gray_zone abiertas y borradores pendientes de aprobación
```

---

## 5. Contratos que ningún agente puede romper

### 5.1 Director Cognitivo

```python
# OBLIGATORIO
class CognitiveDirector:
    async def handle_turn(self, turn_context: TurnContext) -> Decision: ...
```

- Debe ser 100 % determinista en el control de flujo.
- Solo puede llamar a: Analyst, Planner, Registry, ContextBuilder, Generator, Evaluator, Decider, TraceStore.
- **Prohibido**: importar `aiogram`, `BehaviorEngine`, o decidir delays.

### 5.2 EvaluationProfile (nunca score único)

```python
class EvaluationProfile(BaseModel):
    naturalness: float
    precision: float
    doctrine: float
    consistency: float
    safety: float
    coverage: float
    empathy: float
```

El Decisor trabaja sobre el **vector**. Cualquier código que haga `score = mean(...)` o `if confidence > 0.8` es incorrecto.

### 5.3 Decision

```python
action: Literal["send", "approve", "escalate", "consult_doctrine", "regenerate"]
```

Los modos (supervisado/autónomo) son **filtros externos**. El Decisor propone; el modo restringe.

Nota sobre BR-02: La regla "escalación gana sobre zona gris" aplica estrictamente para seguridad (safety baja). Para riesgo semántico (risk=alto), la zona gris tiene prioridad cuando falta doctrina, porque es la vía para resolver la causa raíz del riesgo. Ver SPEC-FASE2 §5.4.


### 5.4 BehaviorEngine

```python
async def deliver(self, decision: Decision, texts: list[str], ctx: DeliveryContext) -> DeliveryResult
async def cancel_pending(self, chat_id: int, reason: str = "new_turn") -> None
```

- Solo actúa. Nunca genera texto ni decide la acción.
- Debe respetar `ctx.is_frozen`.
- En sandbox debe usar FakeDelivery.

### 5.5 Anti-contaminación (BR-15 / REQ-MEM-07)

- Toda query a `memories` **debe** incluir `WHERE vip_id = :current_vip_id`.
- El retriever de `examples` **nunca** puede leer de la tabla `memories`.
- Staging es el único puente legítimo hacia el banco vivo de ejemplos.

### 5.6 Aprendizaje post-turno

```python
# Solo se llama DESPUÉS de que el turno terminó (enviado, escalado, etc.)
await learning.run_post_turn(turn_id, decision, final_text, human_correction=None)
```

Nunca dentro del Director ni del Generador.

---

## 6. Reglas operativas para agentes de código

### 6.1 Al añadir un nuevo Retriever

1. Implementar la interfaz `Retriever`.
2. Registrarlo en el `CapabilityRegistry` con un nombre de capacidad (`knowledge.xxx`).
3. El Director solo debe referenciar la capacidad, nunca la clase concreta.
4. Añadir tests unitarios que demuestren que no filtra datos de otros VIP.

### 6.2 Al tocar el Evaluador o el Decisor

1. Mantener el vector de 7 dimensiones.
2. Cualquier nuevo umbral debe vivir en `system_config` (no hardcodeado).
3. Documentar la regla en la matriz de decisión del SPEC.
4. Añadir test que demuestre el comportamiento con valores límite.

### 6.3 Al modificar el Behavior Engine

1. No introducir llamadas a LLM.
2. Mantener la posibilidad de cancelación por `chat_id`.
3. Garantizar que `pending_deliveries` se actualiza en todos los caminos (done / cancelled / error).
4. Sandbox debe seguir siendo FakeDelivery.

### 6.4 Al trabajar con Staging / Learning

1. Nunca promover automáticamente.
2. Toda corrección de la dueña debe crear un `StagingCandidate` con el par original + final.
3. La destilación de políticas debe pedir (o confirmar) la generalización.

### 6.5 Al tocar el middleware de Telegram

Orden obligatorio del stack:

1. Logging
2. Extracción de `business_connection_id`
3. Detección de mensaje de la dueña → cancel_pending + observe
4. FreezeCheck
5. ForbiddenKeywords (escalación determinística)
6. Auth (allowlist + paused)
7. TurnOrchestrator / PromoService

No reordenar sin actualizar este documento.

---

## 7. Checklist de revisión (para PRs y agentes)

Antes de aceptar un cambio, verificar:

- [ ] ¿El Director sigue siendo 100 % determinista?
- [ ] ¿Cada componente cognitivo responde una sola pregunta?
- [ ] ¿El Behavior Engine sigue fuera de la cognición?
- [ ] ¿El aprendizaje ocurre solo post-turno?
- [ ] ¿Se mantiene la anti-contaminación Memoria ↔ Ejemplos?
- [ ] ¿Todos los objetos intermedios del pipeline se siguen persistiendo?
- [ ] ¿Los modos (supervisado/autónomo) siguen siendo filtros externos?
- [ ] ¿Staging sigue requiriendo confirmación explícita?
- [ ] ¿Las políticas se crean en formato estructurado + generalización?
- [ ] ¿Sandbox sigue aislado y con FakeDelivery?

Si alguna respuesta es “no”, el cambio **no se mergea**.

---

## 8. Qué está explícitamente prohibido

| Prohibición | Razón |
|-------------|-------|
| Llamar a un LLM desde el Director para decidir la acción | Viola REQ-COG-02 y BR-08 |
| Mezclar score único de confianza | Viola REQ-COG-08 y BR-09 |
| Escribir directamente en `examples` desde una corrección | Viola REQ-TRN-07 y BR-13 |
| Que un Retriever de ejemplos lea la tabla `memories` | Viola REQ-MEM-07 y BR-15 |
| Ejecutar Learning dentro del pipeline de decisión | Viola REQ-TRN-05 y BR-11 |
| Que el Generador busque conocimiento o clasifique | Viola REQ-COG-07 |
| Enviar mensaje al VIP sin pasar por Behavior Engine | Viola REQ-COG-13 y separación de capas |
| Hardcodear umbrales del Evaluador en el código del Decisor | Impide calibración empírica (REQ-EVAL) |
| Usar LangGraph / LangChain / agentes externos como orquestador | Viola el diseño de Director determinista |
| Introducir Redis u otro store sin actualizar SPEC y este documento | Mantiene el stack controlado |

---

## 9. Cómo evolucionar este documento

- Cualquier cambio de **límite de módulo** o de **flujo canónico** debe actualizar primero este `AGENTS.md` y después el código.
- Los cambios solo de implementación interna de un módulo (sin romper contratos) no requieren modificar este archivo.
- Cuando se añada un nuevo flujo canónico (ej. recontacto, promo avanzada), se documenta aquí en la sección 4.

---

## 10. Relación con los otros documentos

| Documento | Qué define |
|-----------|------------|
| `REQUERIMIENTOS.md` | **Qué** debe cumplir el sistema (producto) |
| `SPEC.md` | **Cómo** se implementa (diseño técnico) |
| `AGENTS.md` | **Límites** que ningún agente puede cruzar al tocar el código |

Un agente de desarrollo debe leer los tres. Este archivo es el más restrictivo y el que se usa como checklist de revisión.

---

**Fin de AGENTS.md**

Última actualización: Julio 2026  
Equipo de Arquitectura
