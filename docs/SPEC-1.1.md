¡Perfecto! Vamos a construir ese SPEC 1.5 Híbrido Final. He tomado la estructura incremental y la máquina de estados de SPEC-2 (para que el MVP sea ejecutable hoy), y le he injertado toda la profundidad técnica, los modelos de datos completos, los ADRs y la visión de futuro de SPEC-1.

El resultado es un documento único que no especula, sino que planifica por capas: tienes las tablas de Fase 3 diseñadas desde el día 1 (para evitar migrations rotas), pero el código de Fase 1 solo toca su lote. He marcado cada sección con [FASE 1] , [FASE 2] o [FASE 3] para que no haya dudas.

Aquí tienes tu SPEC v1.5 — Híbrido Integrado.

---

SPEC.md — Diseño e Implementación (v1.5 Híbrido)

Diana Business Bot / Sistema de Automatización de Chats VIP

Campo Valor
Nivel Contrato de diseño e implementación (el "cómo")
Basado en REQUERIMIENTOS.md v2.1
Estrategia Incremental por Fases (Fase 1 = MVP Supervisado, Fase 2 = MVP+, Fase 3 = Completo)
Audiencia Ingeniería, producto técnico
Versión 1.5 — Híbrido Integrado
Estado Aprobado para implementación (Inicio por Fase 1)

---

0. Principio Rector (Inamovible)

El sistema no genera respuestas. El sistema toma decisiones. Las respuestas son únicamente una consecuencia de esas decisiones.

Este principio obliga a:

· Director 100 % determinista (nunca pregunta a un LLM "¿qué hago?").
· Especialización: cada componente responde una sola pregunta.
· Explicabilidad total: objetos intermedios persistidos para reconstruir cualquier decisión.
· Sustituibilidad: vía Capability Registry, ningún componente conoce a otro concreto.
· Anti-contaminación: la Memoria de un VIP nunca se convierte en few-shot general.

---

1. Stack Tecnológico (Bloqueado para todas las fases)

Capa Tecnología Notas
Lenguaje Python 3.12+ 
Framework Telegram aiogram 3.x Soporte nativo Business Connection
Delivery Long-polling allowed_updates incluye business_*
Base de datos PostgreSQL 16+ Único almacén durable
Vectores (Fase 2+) pgvector con índices HNSW 
ORM SQLAlchemy 2.0 (async) + asyncpg 
Validación Pydantic v2 Todos los objetos cognitivos
LLM Primario DeepSeek Interfaz abstracta para hot-swap
LLM Secundario Anthropic (Claude) Respaldo configurable
Embeddings (Fase 2) sentence-transformers (multilingual) Local, sin coste; intercambiable por API
Timers / Behavior asyncio.Task + tabla pending_deliveries Sin Redis en V1
Configuración Pydantic Settings + .env Secretos fuera del repo
Testing pytest + pytest-asyncio Pipeline 100 % testeable sin Telegram

No se usa en V1: Redis, LangChain, Celery, Kafka.

---

2. Arquitectura de Alto Nivel (con Turn Coordinator)

```
Telegram Business Connection (aiogram 3.x)
        │
        ▼
┌───────────────────────────────────────────────────────────────────┐
│                      MIDDLEWARES (capa Telegram)                  │
│  • Auth (¿está en allowlist?)                                     │
│  • ForbiddenWords (cortocircuito de escalación)  [FASE 1]        │
│  • FreezeCheck (¿está congelado por zona gris?) [FASE 2]         │
└───────────────────────────────┬───────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────┐
│                   TURN COORDINATOR (NUEVO)                        │
│  • Serializa por chat_id (garantiza 1 turno no terminal)         │
│  • Cancela turnos obsoletos (REQ-VIP-06)                         │
│  • Gestiona la Máquina de Estados del Turn                       │
└───────────────────────────────┬───────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────┐
│                      COGNITIVE CORE (puro)                        │
│                                                                   │
│  Director Cognitivo (100% determinista)                           │
│       │                                                           │
│       ▼                                                           │
│  Analista (LLM → Comprehension)                                   │
│       │                                                           │
│       ▼                                                           │
│  Planificador Cognitivo (determinista)                            │
│       │                                                           │
│       ▼                                                           │
│  Capability Registry → Retrievers (REAL o STUB según Fase)       │
│       │                                                           │
│       ▼                                                           │
│  Constructor de Contexto (prompt mínimo dinámico)                 │
│       │                                                           │
│       ▼                                                           │
│  Generador (LLM → solo texto)                                     │
│       │                                                           │
│       ▼                                                           │
│  Evaluador → EvaluationProfile (vector 7 dimensiones)             │
│       │                                                           │
│       ▼                                                           │
│  Decisor (reglas sobre vector + restricciones de modo)            │
│                                                                   │
└───────────────────────────────┬───────────────────────────────────┘
                                │ Decisión
┌───────────────────────────────▼───────────────────────────────────┐
│                    BEHAVIOR ENGINE (Infraestructura)               │
│  delay → mark as read → typing → (split) → send                   │
│  • FakeDelivery para Sandbox [FASE 2+]                            │
└───────────────────────────────┬───────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────┐
│                 LEARNING (siempre post-turno)                     │
│  • Registro de trazas [FASE 1]                                    │
│  • Staging + destilación [FASE 2]                                 │
│  • Métricas agregadas [FASE 3]                                    │
└───────────────────────────────────────────────────────────────────┘
```

---

3. Máquina de Estados del Turn (Clave para evitar duplicados)

Tomado de SPEC-2. Cada mensaje VIP crea un Turn que transita así:

```
[received] 
    │
    ├──(cortocircuito por palabra prohibida)──► [escalated] (TERMINAL)
    │
    └──(flujo normal)──► [analyzing] ──► [planning] ──► [retrieving] 
                         ──► [building_context] ──► [generating] 
                         ──► [evaluating] ──► [deciding]
                              │
                              ▼
                         [pending_approval] ──(dueña aprueba)──► [delivered] (TERMINAL)
                              │
                              ├──(dueña descarta/escala)──► [escalated] (TERMINAL)
                              │
                              └──(llega nuevo msg del VIP)──► [superseded] (TERMINAL)
```

Invariante crítica: Solo puede existir un Turn no terminal (status fuera de superseded|delivered|failed|escalated) por chat_id.
El Turn Coordinator lo garantiza mediante serialización (ej. SELECT ... FOR UPDATE o cola FIFO por chat).

---

4. Contratos por Componente (Fase 1 y Extensiones)

Cada componente responde una sola pregunta (REQ-NFR-13).

4.1 Director Cognitivo

Pregunta: ¿Qué necesita este turno?
Naturaleza: 100 % código determinista.
Entrada: Turn en estado received + texto.
Salida: Decision (aprobación o escalación en Fase 1).

Pasos (Fase 1):

1. Cortocircuito (REQ-COG-16): Si el texto coincide con palabras/temas prohibidos → EscalationEvent + Turn.status = escalated + fin.
2. Invoca Analista → obtiene Comprehension.
3. Invoca Planificador → obtiene Plan.
4. Pide al Capability Registry resolver cada capacidad del Plan (en Fase 1, history y context son reales; el resto son STUBS).
5. Constructor de Contexto → genera prompt.
6. Generador (LLM) → produce Borrador.
7. Evaluador (LLM) → produce EvaluationProfile.
8. Decisor → produce Decision (siempre approve o escalate en Fase 1).

4.2 Analista (LLM)

Pregunta: ¿Qué está pasando en este turno?
Entrada: Texto del turno + historial mínimo.
Salida (schema estricto Pydantic):

```json
{
  "intent": "negociar",
  "topics": ["precio", "producto"],
  "emotion": "amistosa",
  "urgency": "media",
  "risk": "bajo",
  "needs_memory": true,
  "needs_policy": true,
  "needs_schedule": false,
  "needs_examples": false,
  "needs_history": true,
  "needs_context": true
}
```

4.3 Planificador Cognitivo

Pregunta: ¿Qué conocimiento recuperar?
Naturaleza: Determinista.
Salida: Subconjunto de needs_* en true mapeado a nombres de capacidad (knowledge.memory, etc.).

4.4 Capability Registry (El corazón de la sustituibilidad)

Pregunta: ¿Qué componente concreto satisface esta capacidad?
Contrato: resolve(capacidad: str) → Retriever (todos con interfaz fetch(turn) → resultado | null).

Estado de implementación por Fase:

Capacidad Fase 1 (MVP) Fase 2 (MVP+) Fase 3 (Completo)
knowledge.history REAL: Últimos N mensajes (SQL) REAL (mejorado) REAL
knowledge.context REAL (parcial): Deriva estado simple del historial REAL: Usa tabla contexts con embeddings y expiración REAL
knowledge.profile STUB: Devuelve null REAL: Busca en profiles REAL
knowledge.memory STUB: Devuelve null REAL: Busca en memories (pgvector + vip_id) REAL
knowledge.policy STUB: Devuelve null REAL: Busca en policies activas REAL
knowledge.examples STUB: Devuelve null REAL: Busca en examples (few-shot) REAL
knowledge.schedule STUB STUB REAL: Agenda de la dueña

4.5 Constructor de Contexto

Pregunta: ¿Cuál es el contexto mínimo necesario?
Regla: Composición dinámica. Si un bloque de conocimiento es null, no aparece en el prompt (mantiene budget, REQ-NFR-07).
Siempre incluye: Persona/voz configurada + reglas de estilo.

4.6 Generador (LLM)

Pregunta: ¿Cómo respondería la dueña?
Entrada: prompt construido.
Salida: Texto plano del borrador. No clasifica, no decide, no busca.

4.7 Evaluador (LLM)

Pregunta: ¿Debemos confiar en este mensaje?
Salida (vector 7D, sin score único, REQ-COG-08):

```json
{
  "naturalidad": 0.85,
  "precision": 0.90,
  "doctrina": 0.40,
  "consistencia": 0.80,
  "seguridad": 0.95,
  "cobertura": 0.70,
  "empatia": 0.88
}
```

4.8 Decisor (Determinista)

Pregunta: ¿Qué acción tomar?
Reglas de Fase 1 (Modo Supervisado Global):

· Si seguridad < umbral_seguridad → Escalar.
· En cualquier otro caso → Aprobar (nunca Enviar directo).
· Regenerar y Consultar doctrina están deshabilitados en Fase 1 (se activan en Fase 2).

4.9 Behavior Engine

Pregunta: ¿Cómo se actúa el mensaje? (Infraestructura pura).
Secuencia Fase 1: Delay configurable → read_business_message → send_chat_action(typing) (duración proporcional) → send_message con business_connection_id.
Cancelación: Si se cancela un turno, se aborta la asyncio.Task y se marca como cancelled en pending_deliveries.

---

5. Modelo de Datos (Clasificado por Fase)

Nota: Las tablas de Fase 2 y 3 ya están diseñadas aquí para evitar migraciones rotas, pero el código de Fase 1 solo implementa las marcadas como FASE 1. Las demás tablas se crean (con sus índices) al activar la fase correspondiente, o pueden crearse desde el inicio con datos vacíos.

```sql
-- =============================================
-- [FASE 1] MVP SUPERVISADO (IMPLEMENTAR AHORA)
-- =============================================

-- VIP allowlist
CREATE TABLE vips (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_user_id BIGINT NOT NULL UNIQUE,
    display_name    TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    paused_until    TIMESTAMPTZ,                -- REQ-ADM-04 (reserva)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Historial de mensajes (raw)
CREATE TABLE message_history (
    id                  BIGSERIAL PRIMARY KEY,
    chat_id             BIGINT NOT NULL,
    telegram_message_id BIGINT,
    role                TEXT NOT NULL,          -- 'vip' | 'owner' | 'bot'
    text                TEXT NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL
);
CREATE INDEX ON message_history (chat_id, timestamp DESC);

-- Trazas completas del pipeline (auditoría)
CREATE TABLE pipeline_traces (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id         UUID NOT NULL,
    vip_id          UUID REFERENCES vips(id),
    chat_id         BIGINT NOT NULL,
    comprehension   JSONB,
    plan            JSONB,
    retrieved       JSONB,
    prompt_text     TEXT,
    generated_text  TEXT,
    evaluation      JSONB,
    decision        JSONB,
    delivery_result JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON pipeline_traces (vip_id, created_at DESC);

-- Deliveries en vuelo (recuperación tras reinicio)
CREATE TABLE pending_deliveries (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id                 BIGINT NOT NULL,
    vip_id                  UUID REFERENCES vips(id),
    business_connection_id  TEXT NOT NULL,
    texts                   JSONB NOT NULL,
    decision                JSONB NOT NULL,
    scheduled_at            TIMESTAMPTZ NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'pending', -- pending | delivering | done | cancelled
    turn_id                 UUID NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON pending_deliveries (status, scheduled_at);

-- Turnos (máquina de estados)
CREATE TABLE turns (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id             BIGINT NOT NULL,
    vip_id              UUID REFERENCES vips(id),
    status              TEXT NOT NULL,  -- received, analyzing, planning, retrieving, building_context, generating, evaluating, deciding, pending_approval, escalated, superseded, delivered, failed
    trigger_message_id  BIGINT,
    superseded_by       UUID,           -- cadena de supersedencia
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Escalaciones
CREATE TABLE escalation_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id     UUID NOT NULL,
    tipo        TEXT NOT NULL,  -- cortocircuito_determinista | semantica
    motivo      TEXT,
    notificado  BOOLEAN DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================
-- [FASE 2] MVP+ (MEMORIA + APRENDIZAJE + ZONA GRIS)
-- =============================================

-- Perfil permanente (información relativamente estable)
CREATE TABLE profiles (
    vip_id          UUID NOT NULL REFERENCES vips(id) ON DELETE CASCADE,
    data            JSONB NOT NULL DEFAULT '{}',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (vip_id)
);

-- Memoria (hechos útiles y preferencias) — PRIVADA por VIP
CREATE TABLE memories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vip_id          UUID NOT NULL REFERENCES vips(id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    embedding       vector(384),                -- o 768 según modelo
    source          TEXT,                       -- 'extraction' | 'manual_note'
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
    embedding       vector(384),
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON contexts (vip_id, expires_at);

-- Políticas (doctrina estructurada)
CREATE TABLE policies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_description TEXT NOT NULL,
    rule                TEXT NOT NULL,
    example_applied     TEXT,
    scope               TEXT NOT NULL DEFAULT 'all',
    valid_until         TIMESTAMPTZ,
    is_active           BOOLEAN NOT NULL DEFAULT true,
    embedding           vector(384),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_from_gray_zone UUID
);
CREATE INDEX ON policies USING hnsw (embedding vector_cosine_ops);

-- Banco vivo de ejemplos (few-shot) + contraejemplos
CREATE TABLE examples (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    context_text        TEXT NOT NULL,
    response_text       TEXT NOT NULL,
    is_counterexample   BOOLEAN NOT NULL DEFAULT false,
    original_draft      TEXT,
    quality_score       REAL DEFAULT 0.7,
    embedding           vector(384),
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
    reviewed_by     BIGINT
);

-- Zona gris abierta
CREATE TABLE gray_zone_queries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vip_id          UUID NOT NULL REFERENCES vips(id),
    turn_id         UUID NOT NULL,
    question        TEXT NOT NULL,
    draft_text      TEXT,
    status          TEXT NOT NULL DEFAULT 'open', -- open | resolved | expired
    freeze_until    TIMESTAMPTZ,
    resolution      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);

-- =============================================
-- [FASE 3] PRODUCTO COMPLETO
-- =============================================

-- Métricas de aprendizaje (agregadas semanales)
CREATE TABLE learning_metrics (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    week_start              DATE NOT NULL,
    approval_without_correction_rate REAL,
    gray_zone_repetition_count INT,
    false_positive_escalation_rate REAL,
    total_turns             INT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Configuración global del sistema (se amplía en Fase 3)
CREATE TABLE system_config (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

6. Flujos Principales por Fase

6.1 [FASE 1] Turno VIP Normal (Supervisado)

1. Llega business_message.
2. Middleware: Auth (¿VIP?).
3. Turn Coordinator: Crea Turn o marca el anterior como superseded (cancela su delivery).
4. Director ejecuta pipeline (cortocircuito incluido).
5. Decisor (solo en modo supervisado) → approve o escalate.
6. Si approve: Turn → pending_approval. Se envía borrador + resumen al DM de la dueña.
7. Dueña aprueba (envía) o corrige (sustituye y envía).
8. Behavior Engine entrega al VIP con delay, lectura y typing.
9. Aprendizaje post-turno: Solo persiste traza en pipeline_traces.

6.2 [FASE 2] Zona Gris (Consultar Doctrina)

1. Decisor (ahora con consult_doctrine habilitada) detecta doctrine baja y needs_policy=true.
2. Crea gray_zone_queries y marca VIP como congelado (Behavior Engine bloquea I/O).
3. Dueña responde en DM.
4. Sistema pide generalización: "¿Esto aplica siempre que pregunten por X?".
5. Se destila a policies (formato estructurado) y se guarda en Staging (confirmación explícita para pasar a viva).
6. Se descongela y se retoma flujo normal.

6.3 [FASE 2] Corrección → Staging

1. Dueña corrige un borrador en DM.
2. Se guarda en staging_candidates el par (original_draft, final_text) como contraejemplo potencial.
3. Solo pasa a examples tras botón explícito "Usar como ejemplo".

6.4 [FASE 3] Recontacto por Silencio (Pipeline Reducido)

1. Scheduler detecta VIP inactivo > N días.
2. Ejecuta pipeline reducido: Director → Recuperar memoria + políticas → Generar → Evaluar → Enviar (sin pasar por Analista/Planificador completo).

---

7. Superficie de Administración (DM de la Dueña)

Comando / Acción Fase
/start, /menu Fase 1
Añadir / quitar VIP (reenvío o ID) Fase 1
Ver estado (modo, LLM activo, salud) Fase 1
Aprobar / Corregir borradores (inline) Fase 1
Cambiar modo (Supervisado ↔ Autónomo) Fase 2
Pausar VIP Fase 2
Activar Sandbox Fase 2
Ver traza cognitiva de una respuesta Fase 2
Gestionar Staging (promover/descartar) Fase 2
Ver métricas (tasa aprobación, zona gris) Fase 3

---

8. Roadmap de Implementación (Alineado con REQUIREMENTS §18)

Fase Hitos Criterio de Salida
Fase 1 (MVP) 1. Turn Coordinator + Máquina de Estados. 2. Director con cortocircuito. 3. Analista + Generador + Evaluador (LLMs). 4. Decisor (solo approve/escalate). 5. Behavior Engine básico (delay, read, typing). 6. Cola de aprobación en DM. 7. Tablas Fase 1 (vips, history, traces, pending, turns, escalations). VIP autorizado recibe respuesta en nombre de la dueña con espera, lectura y typing; nada se envía sin aprobación.
Fase 2 (MVP+) 8. Activar Retrievers reales (memoria, políticas, ejemplos) con pgvector. 9. Staging Area + promoción explícita. 10. Zona gris + destilación de políticas. 11. Evaluación con calibración empírica. 12. Hot-swap de LLM. 13. Sandbox con FakeDelivery. 14. Tablas Fase 2 (profiles, memories, contexts, policies, examples, staging, gray_zone). El sistema aprende de correcciones (vía Staging) y resuelve dudas de doctrina sin repetir preguntas.
Fase 3 (Completo) 15. Recontacto por silencio. 16. Promo no-VIP (trigger exacto). 17. Métricas de aprendizaje agregadas. 18. Behavior Engine avanzado (mensajes divididos, quirks). 19. Tablas Fase 3 (learning_metrics, system_config ampliada). Producto completo alineado al 100 % con REQUERIMIENTOS.

---

9. Decisiones de Arquitectura (ADRs) y Decisiones Abiertas

ADRs (Tomados de SPEC-1)

· ADR-001: Framework Telegram = aiogram 3.x (soporte Business nativo).
· ADR-002: Orquestación = Director custom + Capability Registry (sin frameworks de agentes externos).
· ADR-003: Almacenamiento = solo PostgreSQL + pgvector (simplicidad operativa).
· ADR-004: Behavior Engine = asyncio.Task + pending_deliveries (suficiente para el volumen).
· ADR-005: Embeddings locales (sentence-transformers) para Fase 2 (cero coste, intercambiable).
· ADR-006: LLMProvider abstracto con hot-swap (DeepSeek primario, Anthropic secundario).

Decisiones Abiertas para Ingeniería (Fase 1)

1. ¿Incluir regeneración por naturalidad baja en Fase 1?
      Recomendación: No. Diferir a Fase 2. En Fase 1, siempre approve y que la dueña corrija si es necesario.
2. Mecanismo concreto de serialización por chat:
      Recomendación: Usar SELECT ... FOR UPDATE sobre la tabla turns filtrando por chat_id y status NOT IN ('terminales'), o una cola en memoria con asyncio.Queue por chat_id para evitar latencia de DB en alta concurrencia.
3. Umbrales iniciales del Decisor:
      Recomendación: umbral_seguridad = 0.3 (muy conservador, escalar ante la mínima duda). Ajustar manualmente tras los primeros 50 turnos reales, hasta que Fase 2 incorpore calibración automática (REQ-EVAL-*).
4. TTL de objetos intermedios (pipeline_traces):
      Recomendación: 30 días para Fase 1, ajustable por variable de entorno.

---

10. Criterios de Aceptación Técnicos (por Fase)

ID Criterio Fase REQ asociado
TAC-01 Director es código puro (sin LLM para decidir) 1 REQ-COG-02
TAC-02 Capability Registry resuelve todos los recuperadores (reales o stub) 1 REQ-COG-03
TAC-03 EvaluationProfile es vector 7D (sin score único) 1 REQ-COG-08
TAC-04 Todos los objetos intermedios se persisten 1 REQ-COG-11
TAC-05 Behavior Engine separado del Cognitive Core 1 REQ-COG-13
TAC-06 Escalación por palabra prohibida ocurre antes del Analista 1 REQ-COG-16
TAC-07 Cancelación de delivery al llegar nuevo mensaje del VIP 1 REQ-VIP-06
TAC-08 Reinicio recupera pending_deliveries 1 REQ-PER-02
TAC-09 Memoria de un VIP NO se filtra a ejemplos de otros (en Fase 2) 2 REQ-MEM-07
TAC-10 Ninguna corrección se promueve sin Staging + confirmación (Fase 2) 2 REQ-TRN-07
TAC-11 Zona gris congela al VIP y destila política estructurada (Fase 2) 2 REQ-GAP-*
TAC-12 LLM se cambia en caliente (Fase 2) 2 REQ-ADM-03
TAC-13 Existen métricas de tasa de aprobación y repetición de zona gris (Fase 3) 3 REQ-MET-*

---

11. Estructura de Carpetas Propuesta (Unificada)

```
diana-bot/
├── pyproject.toml
├── .env.example
├── README.md
├── REQUERIMIENTOS.md
├── SPEC.md                          ← este documento (v1.5)
│
├── src/
│   └── diana/
│       ├── __init__.py
│       ├── main.py                  # entrypoint (long-polling)
│       ├── config.py                # Pydantic Settings
│       │
│       ├── telegram/                # capa de adaptación
│       │   ├── handlers/
│       │   │   ├── business.py
│       │   │   ├── admin.py
│       │   │   └── callbacks.py
│       │   ├── middlewares/
│       │   │   ├── auth.py
│       │   │   ├── forbidden.py     # cortocircuito Fase 1
│       │   │   └── freeze.py        # Fase 2
│       │   └── keyboards.py
│       │
│       ├── application/             # orquestación de casos de uso
│       │   ├── turn_coordinator.py  # NUEVO (Fase 1)
│       │   ├── turn_orchestrator.py
│       │   ├── admin_service.py
│       │   ├── sandbox_service.py   # Fase 2
│       │   ├── promo_service.py     # Fase 3
│       │   └── recontact.py         # Fase 3
│       │
│       ├── cognitive/               # CORE PURO (sin Telegram)
│       │   ├── director.py
│       │   ├── analyst.py
│       │   ├── planner.py
│       │   ├── context_builder.py
│       │   ├── generator.py
│       │   ├── evaluator.py
│       │   ├── decider.py
│       │   ├── registry.py
│       │   ├── models.py            # Comprehension, EvaluationProfile, Decision...
│       │   └── retrievers/
│       │       ├── base.py
│       │       ├── memory.py        # STUB en Fase 1, REAL en Fase 2
│       │       ├── profile.py       # STUB en Fase 1, REAL en Fase 2
│       │       ├── context.py       # REAL (parcial) en Fase 1
│       │       ├── policy.py        # STUB en Fase 1, REAL en Fase 2
│       │       ├── examples.py      # STUB en Fase 1, REAL en Fase 2
│       │       ├── history.py       # REAL en Fase 1
│       │       └── schedule.py      # STUB hasta Fase 3
│       │
│       ├── behavior/                # Behavior Engine
│       │   ├── engine.py
│       │   ├── fake.py              # Fase 2
│       │   └── timer_manager.py
│       │
│       ├── learning/                # post-turno
│       │   ├── extractor.py         # Fase 2
│       │   ├── staging.py           # Fase 2
│       │   ├── policy_distiller.py  # Fase 2
│       │   └── metrics.py           # Fase 3
│       │
│       ├── llm/                     # abstracción de proveedores
│       │   ├── provider.py
│       │   ├── deepseek.py
│       │   └── anthropic.py
│       │
│       ├── embeddings/
│       │   └── local.py             # Fase 2
│       │
│       └── infrastructure/
│           ├── db/
│           │   ├── models.py        # SQLAlchemy (todas las tablas)
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

12. No-metas (Explícitas)

· No define UI/UX de menús más allá de "existe un comando" (se define en la capa de Telegram).
· No aborda escalado masivo (>100 VIPs concurrentes) en Fase 1 o 2 (REQ-NFR-11 es P2).
· La Zona Gris (GAP-), el Aprendizaje (TRN-) y la Memoria (MEM-*) no se implementan en Fase 1, solo están diseñados.
· No se implementa auto-envío (modo autónomo) hasta Fase 2 como mínimo.

---

Fin del documento de diseño híbrido v1.5

Este documento es la única fuente de verdad para la implementación.
Para la Fase 1, el equipo debe ignorar las secciones marcadas como [FASE 2] y [FASE 3] y concentrarse en los contratos, la máquina de estados y las tablas de la Fase 1.
Para la Fase 2, se "encienden" los Retrievers reales y se materializan las tablas de memoria y staging, sin tocar una línea del Director.
