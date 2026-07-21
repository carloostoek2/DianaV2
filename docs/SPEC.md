# SPEC.md — Diseño e Implementación
**Diana Business Bot / Sistema de Automatización de Chats VIP**

| Campo | Valor |
|-------|--------|
| Nivel | Contrato de diseño e implementación (cómo) |
| Basado en | [`REQUERIMIENTOS.md`](REQUERIMIENTOS.md) v2.1 |
| Audiencia | Ingeniería, producto técnico |
| Versión | 1.0 — Arquitectura Cognitiva + decisiones de implementación |
| Estado | Aprobado para implementación (V1) |
| Idioma principal | Español |

---

## 1. Propósito de este documento

Este documento traduce los requisitos de producto (`REQUERIMIENTOS.md`) en decisiones concretas de implementación, contratos, modelos de datos, interfaces y estructura de código.

**Principio rector (citado del REQ):**

> El sistema no genera respuestas.  
> El sistema toma decisiones.  
> Las respuestas son únicamente una consecuencia de esas decisiones.

Todo diseño aquí presente debe respetar:
- Director 100 % determinista
- Especialización (cada componente responde una sola pregunta)
- Explicabilidad total (objetos intermedios persistidos)
- Anti-contaminación de conocimiento entre VIP
- Aprendizaje controlado (Staging Area + confirmación explícita)

---

## 2. Stack tecnológico (bloqueado)

| Capa | Tecnología | Notas |
|------|------------|-------|
| Lenguaje | Python 3.12+ | |
| Framework Telegram | **aiogram 3.x** | Soporte nativo Business Connection |
| Delivery de updates | Long-polling | `allowed_updates` incluye business_* |
| Base de datos | PostgreSQL 16+ | Único almacén |
| Vectores | **pgvector** | HNSW indexes |
| ORM | SQLAlchemy 2.0 (async) + asyncpg | |
| Validación / contratos | Pydantic v2 | Todos los objetos cognitivos |
| LLM | DeepSeek (primario) + Anthropic (secundario) | Interfaz abstracta, hot-swap |
| Cliente LLM | httpx + OpenAI-compatible / Anthropic SDK | |
| Embeddings (v1) | `sentence-transformers` (multilingual) | Local, cero coste extra |
| Timers / Behavior | `asyncio.Task` + tabla `pending_deliveries` | Sin Redis |
| Scheduler auxiliar | APScheduler (AsyncIOScheduler) opcional | Solo si se necesita recontacto periódico |
| Configuración | Pydantic Settings + variables de entorno | Secretos fuera del repo |
| Testing | pytest + pytest-asyncio | Pipeline cognitivo 100 % testable sin Telegram |

**No se usa en V1:** Redis, LangGraph, LangChain, Celery, Docker Swarm/K8s (solo Docker Compose simple si se desea).

---

## 3. Arquitectura de alto nivel

```
┌─────────────────────────────────────────────────────────────────┐
│                    Telegram Layer (aiogram 3.x)                 │
│  • business_message / edited_business_message                   │
│  • admin DM (comandos + inline keyboards)                       │
│  • long-polling                                                 │
│  • Middleware: Auth → ForbiddenWords → FreezeCheck → Director   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                    Application Services                         │
│  • TurnOrchestrator          (entrada turno VIP)                │
│  • AdminService                                                 │
│  • SandboxService            (perfiles ficticios aislados)      │
│  • PromoService              (no-VIP, trigger exacto, sin LLM)  │
│  • RecontactScheduler                                           │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                 COGNITIVE CORE (puro dominio)                   │
│                                                                 │
│  Director Cognitivo (100 % determinista)                        │
│       │                                                         │
│       ▼                                                         │
│  Analista (LLM → Comprehension)                                 │
│       │                                                         │
│       ▼                                                         │
│  Planificador Cognitivo (determinista desde Comprehension)      │
│       │                                                         │
│       ▼                                                         │
│  Capability Registry → Retrievers especializados                │
│       (memory | profile | context | policy | examples |         │
│        history | schedule)                                      │
│       │                                                         │
│       ▼                                                         │
│  Constructor de Contexto (prompt mínimo dinámico)               │
│       │                                                         │
│       ▼                                                         │
│  Generador (LLM → solo texto)                                   │
│       │                                                         │
│       ▼                                                         │
│  Evaluador → EvaluationProfile (vector 7 dimensiones)           │
│       │                                                         │
│       ▼                                                         │
│  Decisor (reglas sobre vector + restricciones de modo)          │
│                                                                 │
└──────────────────────────────┬──────────────────────────────────┘
                               │ Decision
┌──────────────────────────────▼──────────────────────────────────┐
│                 Behavior Engine (infraestructura)               │
│  delay → mark as read → typing → (split) → send                 │
│  FakeDelivery en Sandbox                                        │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│              Learning (siempre post-turno)                      │
│  extracción de memoria · Staging Area · destilación políticas   │
│  · métricas de efectividad                                      │
└─────────────────────────────────────────────────────────────────┘
```

**Reglas de separación obligatorias:**
- El Cognitive Core **no conoce** Telegram ni aiogram.
- El Behavior Engine **no decide** qué decir; solo actúa el mensaje.
- El Learning **nunca** ocurre durante el pipeline de decisión.

---

## 4. Componentes cognitivos — responsabilidades y contratos

### 4.1 Director Cognitivo

**Pregunta que responde:** ¿Qué necesita este turno?

- 100 % código determinista.
- Nunca invoca un LLM para decidir “qué hacer”.
- Orquesta la secuencia canónica.
- Solo habla en **capacidades** (`knowledge.memory`, etc.).
- Persiste todos los objetos intermedios.

```python
class CognitiveDirector:
    async def handle_turn(self, turn_context: TurnContext) -> Decision:
        # 1. Analista
        comprehension = await self.analyst.analyze(turn_context)
        await self.trace.store("comprehension", comprehension)

        # 2. Planificador
        plan = self.planner.plan(comprehension)
        await self.trace.store("plan", plan)

        # 3. Recuperación vía Registry
        knowledge = await self.registry.retrieve_many(plan.needed_capabilities, ...)
        await self.trace.store("retrieved", knowledge)

        # 4. Construcción de contexto
        prompt = self.context_builder.build(turn_context, comprehension, knowledge)
        await self.trace.store("prompt", prompt)

        # 5. Generación
        draft = await self.generator.generate(prompt)
        await self.trace.store("generated", draft)

        # 6. Evaluación
        evaluation = await self.evaluator.evaluate(draft, comprehension, knowledge)
        await self.trace.store("evaluation", evaluation)

        # 7. Decisión
        decision = self.decider.decide(evaluation, mode=turn_context.mode, ...)
        await self.trace.store("decision", decision)

        return decision
```

### 4.2 Analista

**Pregunta:** ¿Qué está pasando en este turno?

- Único componente LLM que produce estructura.
- Salida obligatoria: objeto `Comprehension`.

```python
class Comprehension(BaseModel):
    intent: str
    topics: list[str]
    emotion: str
    urgency: Literal["baja", "media", "alta"]
    risk: Literal["bajo", "medio", "alto"]
    needs_memory: bool
    needs_policy: bool
    needs_schedule: bool
    needs_examples: bool
    needs_history: bool
    needs_context: bool
    needs_profile: bool = True
    raw_llm_output: dict | None = None  # para auditoría
```

### 4.3 Planificador Cognitivo

**Pregunta:** ¿Qué conocimiento recuperar?

- Determinista a partir de la `Comprehension`.
- Produce lista de capacidades a invocar + parámetros de retrieval (top-k, filtros, etc.).

### 4.4 Capability Registry + Retrievers

**Pregunta de cada Retriever:** ¿Qué sabemos sobre X?

```python
class Capability(str, Enum):
    KNOWLEDGE_MEMORY   = "knowledge.memory"
    KNOWLEDGE_PROFILE  = "knowledge.profile"
    KNOWLEDGE_CONTEXT  = "knowledge.context"
    KNOWLEDGE_POLICY   = "knowledge.policy"
    KNOWLEDGE_EXAMPLES = "knowledge.examples"
    KNOWLEDGE_HISTORY  = "knowledge.history"
    KNOWLEDGE_SCHEDULE = "knowledge.schedule"

class Retriever(Protocol):
    async def retrieve(
        self,
        need: RetrievalNeed,
        vip_id: int,
        comprehension: Comprehension,
    ) -> RetrievedKnowledge: ...

class CapabilityRegistry:
    def register(self, capability: Capability, retriever: Retriever) -> None: ...
    def resolve(self, capability: Capability) -> Retriever: ...
    async def retrieve_many(self, needs: list[RetrievalNeed], ...) -> KnowledgeBundle: ...
```

**Regla de oro:** El Director nunca importa un Retriever concreto.

### 4.5 Constructor de Contexto

**Pregunta:** ¿Cuál es el contexto mínimo necesario?

- Compone dinámicamente el prompt.
- Nunca existe un prompt fijo.
- Solo incluye los bloques que el Planificador solicitó.
- Inyecta persona/voz, reglas de estilo y ejemplos (top-k = 3-5).

### 4.6 Generador

**Pregunta:** ¿Cómo respondería la dueña?

- Solo recibe contexto ya preparado.
- Solo redacta texto.
- No clasifica, no busca conocimiento, no toma decisiones.

### 4.7 Evaluador

**Pregunta:** ¿Debemos confiar en este mensaje?

- Produce **vector multidimensional** (nunca score único).

```python
class EvaluationProfile(BaseModel):
    naturalness: float   # 0.0 – 1.0
    precision: float
    doctrine: float
    consistency: float
    safety: float
    coverage: float
    empathy: float
    raw_llm_output: dict | None = None
```

### 4.8 Decisor

**Pregunta:** ¿Qué acción tomar?

- Trabaja sobre el vector + restricciones de modo (supervisado/autónomo).
- Acciones posibles:

```python
class Decision(BaseModel):
    action: Literal[
        "send",               # enviar directamente (modo autónomo)
        "approve",            # enviar a dueña para aprobación
        "escalate",           # humano debe tomar el hilo
        "consult_doctrine",   # zona gris → congelación
        "regenerate",         # pedir otra versión al Generador
    ]
    reason: str
    evaluation: EvaluationProfile
    draft_text: str | None = None
    regenerated_from: str | None = None
```

**Reglas de ejemplo (calibrables empíricamente):**

| Condición | Acción |
|-----------|--------|
| `safety < umbral_safety` | `escalate` |
| `doctrine < umbral_doctrine` | `consult_doctrine` |
| `naturalness < umbral_naturalness` | `regenerate` (máx. N veces) |
| Modo supervisado + resto OK | `approve` |
| Modo autónomo + resto OK | `send` |

Los umbrales viven en `system_config` y se recalibran periódicamente (REQ-EVAL-*).

---

## 5. Behavior Engine

**Pregunta:** ¿Cómo se actúa el mensaje?

Es infraestructura pura. Fuera de la cognición.

```python
class DeliveryContext(BaseModel):
    chat_id: int
    business_connection_id: str
    vip_id: int | None
    mode: Literal["supervised", "autonomous", "sandbox"]
    is_frozen: bool = False
    personality: dict  # rangos de delay, allow_split, allow_human_quirks

class DeliveryResult(BaseModel):
    success: bool
    message_ids: list[int]
    actual_delay_seconds: float
    typing_duration: float
    error: str | None = None

class BehaviorEngine(Protocol):
    async def deliver(
        self,
        decision: Decision,
        texts: list[str],
        ctx: DeliveryContext,
    ) -> DeliveryResult: ...

    async def cancel_pending(self, chat_id: int) -> None: ...
```

### Secuencia de entrega normal

1. Registrar en `pending_deliveries` (status=`pending`)
2. Sleep con delay aleatorio (rango según modo)
3. `bot.read_business_message(business_connection_id=..., message_id=...)`
4. `bot.send_chat_action(..., action="typing")` + sleep(duración proporcional a longitud)
5. Enviar mensaje(s) con `business_connection_id`
6. Actualizar `pending_deliveries` → `done` + registrar resultado en traza

### Cancelación (REQ-VIP-06)

Cuando llega un nuevo mensaje del mismo VIP:
- Se cancela el `asyncio.Task` pendiente
- Se marca el registro en `pending_deliveries` como `cancelled`

### Congelación (REQ-GAP-03 / REQ-NFR-03)

Si `is_frozen=True` o existe `gray_zone_query` abierta → el Behavior Engine **rechaza cualquier I/O** hacia ese VIP.

### Sandbox

`FakeDelivery`: registra todo lo que habría hecho, nunca llama a Telegram.

---

## 6. Modelo de datos (PostgreSQL + pgvector)

### 6.1 Tablas principales

```sql
-- VIP allowlist
CREATE TABLE vips (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_user_id BIGINT NOT NULL UNIQUE,
    display_name    TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    is_sandbox      BOOLEAN NOT NULL DEFAULT false,
    auto_send       BOOLEAN NOT NULL DEFAULT false,  -- excepción a modo supervisado
    paused_until    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Perfil permanente (información relativamente estable)
CREATE TABLE profiles (
    vip_id          UUID NOT NULL REFERENCES vips(id) ON DELETE CASCADE,
    data            JSONB NOT NULL DEFAULT '{}',  -- nombre, ciudad, profesión, preferencias...
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (vip_id)
);

-- Memoria (hechos útiles y preferencias) — PRIVADA por VIP
CREATE TABLE memories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vip_id          UUID NOT NULL REFERENCES vips(id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    embedding       vector(768),                  -- o 384 según modelo
    source          TEXT,                         -- "extraction" | "manual_note" | ...
    confidence      REAL DEFAULT 0.8,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_accessed_at TIMESTAMPTZ
);
CREATE INDEX ON memories USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON memories (vip_id);

-- Contexto temporal ya interpretado
CREATE TABLE contexts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vip_id          UUID NOT NULL REFERENCES vips(id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    embedding       vector(768),
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON contexts (vip_id, expires_at);

-- Políticas (doctrina estructurada)
CREATE TABLE policies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_description TEXT NOT NULL,           -- tipo de situación (no palabras exactas)
    rule                TEXT NOT NULL,           -- qué hacer / decir
    example_applied     TEXT,
    scope               TEXT NOT NULL DEFAULT 'all',  -- 'all' | segmento
    valid_until         TIMESTAMPTZ,
    is_active           BOOLEAN NOT NULL DEFAULT true,
    embedding           vector(768),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_from_gray_zone UUID                   -- trazabilidad
);
CREATE INDEX ON policies USING hnsw (embedding vector_cosine_ops);

-- Banco vivo de ejemplos (few-shot) + contraejemplos
CREATE TABLE examples (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    context_text        TEXT NOT NULL,
    response_text       TEXT NOT NULL,
    is_counterexample   BOOLEAN NOT NULL DEFAULT false,
    original_draft      TEXT,                     -- solo si es contraejemplo
    quality_score       REAL DEFAULT 0.7,
    embedding           vector(768),
    promoted_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_staging_id   UUID
);
CREATE INDEX ON examples USING hnsw (embedding vector_cosine_ops);

-- Staging Area (candidatos a ejemplo / memoria / política)
CREATE TABLE staging_candidates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type            TEXT NOT NULL,                -- 'example' | 'memory' | 'policy'
    payload         JSONB NOT NULL,
    source_turn_id  UUID,
    status          TEXT NOT NULL DEFAULT 'pending', -- pending | promoted | discarded
    created_by      TEXT,                         -- 'correction' | 'extraction' | 'gray_zone'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at     TIMESTAMPTZ,
    reviewed_by     BIGINT                        -- telegram_user_id de la dueña
);

-- Trazas completas del pipeline (auditoría)
CREATE TABLE pipeline_traces (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id         UUID NOT NULL,
    vip_id          UUID REFERENCES vips(id),
    chat_id         BIGINT NOT NULL,
    comprehension   JSONB,
    plan            JSONB,
    retrieved       JSONB,                        -- qué IDs de conocimiento se usaron
    prompt_text     TEXT,
    generated_text  TEXT,
    evaluation      JSONB,
    decision        JSONB,
    delivery_result JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON pipeline_traces (vip_id, created_at DESC);
CREATE INDEX ON pipeline_traces (turn_id);

-- Deliveries en vuelo (recuperación tras reinicio)
CREATE TABLE pending_deliveries (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id                 BIGINT NOT NULL,
    vip_id                  UUID REFERENCES vips(id),
    business_connection_id  TEXT NOT NULL,
    texts                   JSONB NOT NULL,       -- list[str]
    decision                JSONB NOT NULL,
    scheduled_at            TIMESTAMPTZ NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'pending', -- pending | delivering | done | cancelled
    turn_id                 UUID NOT NULL,
    cancel_reason           TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON pending_deliveries (status, scheduled_at);

-- Zona gris abierta
CREATE TABLE gray_zone_queries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vip_id          UUID NOT NULL REFERENCES vips(id),
    turn_id         UUID NOT NULL,
    question        TEXT NOT NULL,                -- resumen de la duda
    draft_text      TEXT,
    status          TEXT NOT NULL DEFAULT 'open', -- open | resolved | expired
    freeze_until    TIMESTAMPTZ,
    resolution      JSONB,                        -- doctrina destilada
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);

-- Historial de mensajes (con límite de retención)
CREATE TABLE message_history (
    id                  BIGSERIAL PRIMARY KEY,
    chat_id             BIGINT NOT NULL,
    telegram_message_id BIGINT,
    role                TEXT NOT NULL,            -- 'vip' | 'owner' | 'bot'
    text                TEXT NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,
    is_business         BOOLEAN NOT NULL DEFAULT true
);
CREATE INDEX ON message_history (chat_id, timestamp DESC);

-- Configuración global del sistema
CREATE TABLE system_config (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Métricas de aprendizaje (agregadas)
CREATE TABLE learning_metrics (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    week_start              DATE NOT NULL,
    approval_without_correction_rate REAL,
    gray_zone_repetition_count INT,
    false_positive_escalation_rate REAL,
    total_turns             INT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 6.2 Reglas de integridad y anti-contaminación

- Toda consulta a `memories` **debe** filtrar por `vip_id`.
- El retriever de `examples` **nunca** hace JOIN ni consulta a `memories`.
- La promoción desde `staging_candidates` es el **único** camino hacia el banco vivo de ejemplos.
- Las políticas se crean siempre en formato estructurado (nunca respuesta literal).

---

## 7. Capability Registry — nombres y contratos de retrieval

| Capacidad | Retriever | Filtros obligatorios | Top-k por defecto |
|-----------|-----------|----------------------|-------------------|
| `knowledge.profile` | ProfileRetriever | vip_id | 1 (todo el perfil) |
| `knowledge.memory` | MemoryRetriever | vip_id + similitud semántica | 5 |
| `knowledge.context` | ContextRetriever | vip_id + expires_at > now() | 5 |
| `knowledge.policy` | PolicyRetriever | is_active + (scope o embedding) | 3 |
| `knowledge.examples` | ExamplesRetriever | knowledge_type=example + similitud | 3-5 |
| `knowledge.history` | HistoryRetriever | chat_id + límite de mensajes | 12-20 |
| `knowledge.schedule` | ScheduleRetriever | global o por dueña | 1 |

Todos los Retrievers implementan la misma interfaz y devuelven `RetrievedKnowledge` (contenido + metadatos + IDs usados para traza).

---

## 8. Flujos principales

### 8.1 Turno VIP normal (supervisado)

1. Llega `business_message`
2. Middleware: ¿está en allowlist? ¿está congelado? ¿palabra prohibida?
3. `TurnOrchestrator` cancela cualquier delivery pendiente del mismo chat
4. Director ejecuta pipeline completo
5. Decisor → `approve`
6. Se envía borrador + traza resumida al DM de la dueña
7. Dueña aprueba / corrige / regenera
8. Si aprueba → Behavior Engine entrega
9. Learning post-turno (Staging si hubo corrección)

### 8.2 Turno VIP normal (autónomo)

Igual hasta el Decisor → `send` → Behavior Engine entrega directamente.  
Opcionalmente notifica a la dueña según reglas del perfil de evaluación.

### 8.3 Escalación determinística

Middleware detecta palabra/tema prohibido **antes** del Analista →  
crea registro de escalación + notifica a la dueña → VIP no recibe respuesta automática.

### 8.4 Zona gris (consult_doctrine)

1. Decisor decide `consult_doctrine`
2. Se crea `gray_zone_queries` + se marca VIP como congelado
3. Behavior Engine bloquea cualquier I/O
4. Dueña responde doctrina
5. Sistema pide confirmación de generalización (“¿aplica siempre que…?”)
6. Se destila a `policies` (formato estructurado)
7. Se resuelve la query → se descongela → se retoma flujo normal (approve/send)

### 8.5 Corrección → Staging

Cuando la dueña corrige un borrador:
- Se guarda en `staging_candidates` el par `(original_draft, final_text)` como contraejemplo potencial.
- Solo pasa al banco vivo de `examples` tras botón explícito “Usar como ejemplo”.

### 8.6 Reinicio del proceso

Al arrancar:
1. Cargar todas las `pending_deliveries` con `status='pending'` y `scheduled_at > now()`
2. Re-programar los `asyncio.Task` correspondientes
3. Re-notificar gray-zone abiertas y borradores pendientes de aprobación

---

## 9. Superficie de administración (DM de la dueña)

Comandos / menús mínimos (V1):

| Comando / Acción | Descripción |
|------------------|-------------|
| `/start` / `/menu` | Menú principal |
| Añadir / quitar VIP | Reenvío de mensaje o por user_id |
| Ver estado | Modo actual, LLM activo, salud básica, VIP activos |
| Cambiar modo | Supervisado ↔ Autónomo |
| Cambiar LLM | DeepSeek ↔ Anthropic (hot-swap) |
| Pausar VIP | Por tiempo o indefinido |
| Sandbox on/off | Activar modo prueba con perfiles ficticios |
| Ver traza | “¿Por qué respondió esto?” (últimos N turnos) |
| Staging | Listar / promover / descartar candidatos |
| Métricas | Tasa de aprobación, repetición zona gris, falsos positivos |
| Exportar / borrar memoria de un VIP | Cumple REQ de privacidad |
| Listar / desactivar políticas | |

Todas las acciones de aprobación, corrección, regeneración y resolución de zona gris se hacen mediante **inline keyboards** en el DM.

---

## 10. Aprendizaje controlado

### Fuentes de señal (ordenadas por calidad)

1. **Aprobación sin cambios** → señal fuerte positiva
2. **Corrección de la dueña** → la más valiosa (se guarda como contraejemplo en Staging)
3. **Resolución de zona gris** → se convierte en **Política estructurada** (nunca en few-shot)
4. **Turnos observados** (dueña responde a mano en chats solo observados) → señal ruidosa, menor confianza

### Reglas inviolables

- El aprendizaje ocurre **siempre después** del turno (REQ-TRN-05).
- Ninguna corrección entra al banco vivo sin pasar por Staging + confirmación explícita (REQ-TRN-07, BR-13).
- La Memoria de un VIP **nunca** se convierte en few-shot reutilizable entre VIP (BR-15).

### Destilación de políticas

Al resolver una zona gris el sistema **debe** pedir (o inferir y pedir confirmación) la generalización:

> “¿Esto aplica siempre que pregunten por X, o solo en este caso puntual?”

Sin este paso no se crea la política.

---

## 11. Observabilidad y auditoría

- Toda decisión del pipeline deja traza completa en `pipeline_traces`.
- Se puede reconstruir: “¿Qué se comprendió → qué se recuperó → qué se evaluó → por qué se decidió?”.
- Logs operativos suficientes para diagnosticar “por qué no contestó / por qué escaló”.
- Métricas de aprendizaje expuestas al admin (REQ-MET-*).
- Calibración empírica de umbrales del Evaluador (REQ-EVAL-*).

---

## 12. Decisiones de arquitectura (ADRs)

### ADR-001: Framework Telegram = aiogram 3.x
**Estado:** Aceptado  
**Razón:** Soporte nativo de Business Connection, pure asyncio, middleware/routers ideales para short-circuits, comunidad activa en 2026.

### ADR-002: Orquestación = Director custom + Capability Registry
**Estado:** Aceptado  
**Razón:** Cumple estrictamente REQ-COG-02, BR-08, REQ-NFR-13 y REQ-NFR-14. Ningún framework de agentes externo.

### ADR-003: Almacenamiento = solo PostgreSQL + pgvector
**Estado:** Aceptado  
**Razón:** Volumen bajo, simplicidad operativa, un solo proceso, anti-contaminación fácil de forzar en queries.

### ADR-004: Behavior Engine = asyncio.Task + pending_deliveries
**Estado:** Aceptado  
**Razón:** Suficiente para el volumen, recuperable tras reinicio, desacoplado del Cognitive Core.

### ADR-005: Embeddings locales (sentence-transformers multilingual)
**Estado:** Aceptado para V1  
**Razón:** Cero coste, privado, calidad suficiente en español. Interfaz intercambiable.

### ADR-006: LLMProvider abstracto con hot-swap
**Estado:** Aceptado  
**Razón:** REQ-ADM-03. DeepSeek primario, Anthropic secundario.

---

## 13. Estructura de carpetas propuesta

```
diana-bot/
├── pyproject.toml
├── .env.example
├── README.md
├── REQUERIMIENTOS.md
├── SPEC.md                          ← este documento
├── AGENTS.md                        ← límites de módulo (futuro)
│
├── src/
│   └── diana/
│       ├── __init__.py
│       ├── main.py                  ← entrypoint (long-polling)
│       ├── config.py                ← Pydantic Settings
│       │
│       ├── telegram/                ← capa de adaptación
│       │   ├── handlers/
│       │   │   ├── business.py
│       │   │   ├── admin.py
│       │   │   └── callbacks.py
│       │   ├── middlewares/
│       │   │   ├── auth.py
│       │   │   ├── forbidden.py
│       │   │   └── freeze.py
│       │   └── keyboards.py
│       │
│       ├── application/             ← orquestación de casos de uso
│       │   ├── turn_orchestrator.py
│       │   ├── admin_service.py
│       │   ├── sandbox_service.py
│       │   ├── promo_service.py
│       │   └── recontact.py
│       │
│       ├── cognitive/               ← CORE PURO (sin Telegram)
│       │   ├── director.py
│       │   ├── analyst.py
│       │   ├── planner.py
│       │   ├── context_builder.py
│       │   ├── generator.py
│       │   ├── evaluator.py
│       │   ├── decider.py
│       │   ├── registry.py
│       │   ├── models.py            ← Comprehension, EvaluationProfile, Decision...
│       │   └── retrievers/
│       │       ├── base.py
│       │       ├── memory.py
│       │       ├── profile.py
│       │       ├── context.py
│       │       ├── policy.py
│       │       ├── examples.py
│       │       ├── history.py
│       │       └── schedule.py
│       │
│       ├── behavior/                ← Behavior Engine
│       │   ├── engine.py
│       │   ├── fake.py
│       │   └── timer_manager.py
│       │
│       ├── learning/                ← post-turno
│       │   ├── extractor.py
│       │   ├── staging.py
│       │   ├── policy_distiller.py
│       │   └── metrics.py
│       │
│       ├── llm/                     ← abstracción de proveedores
│       │   ├── provider.py
│       │   ├── deepseek.py
│       │   └── anthropic.py
│       │
│       ├── embeddings/
│       │   └── local.py
│       │
│       └── infrastructure/
│           ├── db/
│           │   ├── models.py        ← SQLAlchemy
│           │   ├── session.py
│           │   └── repositories/
│           ├── logging.py
│           └── tracing.py
│
└── tests/
    ├── unit/
    │   ├── cognitive/
    │   ├── behavior/
    │   └── learning/
    ├── integration/
    └── fixtures/
```

---

## 14. Roadmap de implementación

### Fase 0 — Esqueleto (1-2 días)
- Estructura de carpetas + pyproject.toml
- Configuración + conexión Postgres + pgvector
- aiogram long-polling + handler vacío de `business_message`
- Modelos Pydantic básicos + tablas mínimas (`vips`, `system_config`)

### Fase 1 — MVP Supervisado (valor seguro)
1. Allowlist VIP + Admin DM básico
2. Middleware de auth + palabras prohibidas
3. Director + Analista + Generador + Evaluador + Decisor (happy path)
4. Behavior Engine (delay + read + typing + send)
5. Persistencia de `pipeline_traces` + `pending_deliveries`
6. Flujo de aprobación / corrección en DM
7. Cancelación de turnos obsoletos (REQ-VIP-06)
8. Escalación determinística

**Criterio de salida:** Un VIP autorizado recibe respuesta en nombre de la dueña con espera + lectura + typing, y nada se envía sin aprobación en modo supervisado.

### Fase 2 — Aprendizaje controlado + conocimiento
9. 5 tipos de conocimiento + pgvector + retrievers
10. Staging Area + promoción explícita
11. Políticas estructuradas + destilación + generalización
12. Hot-swap de LLM
13. Sandbox con perfiles ficticios aislados
14. Métricas básicas de aprendizaje
15. Exportar / borrar memoria de un VIP

### Fase 3 — Producto completo
16. Recontacto por silencio (pipeline reducido)
17. Promo no-VIP (trigger exacto)
18. Calibración empírica de umbrales
19. Observabilidad completa + reconstrucción de trazas desde admin
20. Behavior Engine avanzado (split messages, quirks humanos opcionales)

---

## 15. Criterios de aceptación técnicos (alineados a AC del REQ)

| ID | Criterio técnico | REQ principal |
|----|------------------|---------------|
| TAC-01 | Director es código puro, sin llamadas a LLM para decidir | REQ-COG-02 |
| TAC-02 | Capability Registry resuelve todos los recuperadores | REQ-COG-03 |
| TAC-03 | EvaluationProfile es vector de 7 dimensiones (sin score único) | REQ-COG-08 |
| TAC-04 | Todos los objetos intermedios se persisten | REQ-COG-11 |
| TAC-05 | Behavior Engine está completamente separado del Cognitive Core | REQ-COG-13 |
| TAC-06 | Sandbox ejecuta el mismo pipeline + FakeDelivery | REQ-COG-14 |
| TAC-07 | Escalación por palabra prohibida ocurre antes del Analista | REQ-COG-16 |
| TAC-08 | Cancelación de delivery al llegar mensaje nuevo del VIP | REQ-VIP-06 |
| TAC-09 | Congelación impide cualquier I/O hacia el VIP | REQ-NFR-03 |
| TAC-10 | Ninguna corrección se promueve sin Staging + confirmación | REQ-TRN-07 |
| TAC-11 | Memoria de un VIP no puede filtrarse a ejemplos de otros | REQ-MEM-07 |
| TAC-12 | Reinicio recupera pending_deliveries y gray-zone abiertas | REQ-PER-02 |
| TAC-13 | LLM se puede cambiar en caliente sin redeploy | REQ-ADM-03 |

---

## 16. Open questions / extensiones futuras

- Modelo de embedding definitivo (¿cambiar a API si la calidad local no es suficiente?).
- Política exacta de retención de `pipeline_traces` y `message_history`.
- ¿Soportar mensajes editados del VIP de forma especial o ignorarlos por defecto?
- Umbrales iniciales del Evaluador (se calibrarán con datos reales).
- Posible introducción de Redis más adelante solo si el volumen crece.

---

**Fin del documento de diseño**

Este SPEC es la fuente de verdad de implementación.  
Cualquier cambio de comportamiento de producto debe actualizar primero `REQUERIMIENTOS.md` y después este documento.

Equipo de Arquitectura — Julio 2026
