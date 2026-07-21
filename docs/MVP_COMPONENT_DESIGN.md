# MVP Component Design — Supervised Mode
**Diana Business Bot**

| Campo | Valor |
|-------|--------|
| Nivel | Diseño de componentes para el primer valor seguro |
| Basado en | `REQUERIMIENTOS.md` v2.1 + `SPEC.md` v1.0 + `AGENTS.md` v1.0 |
| Objetivo | Entregar el MVP Supervisado lo antes posible, sin romper la arquitectura |
| Versión | 1.0 |
| Fecha | Julio 2026 |

---

## 1. Objetivo del MVP

Un VIP autorizado envía un mensaje → el sistema genera un borrador → la dueña lo ve en su DM → aprueba o corrige → el mensaje se entrega en nombre de la dueña con delay + lectura + typing.

**Criterio de éxito (AC-01 + AC-03 + AC-05):**
- El VIP recibe la respuesta como si fuera la dueña (Business Connection).
- Nada llega al VIP sin aprobación explícita.
- Hay espera, mark-as-read y typing indicator.
- Escalación por palabras prohibidas funciona sin pasar por el LLM.
- Un segundo mensaje del VIP cancela el turno anterior.

---

## 2. Alcance exacto del MVP

### Dentro de alcance

| # | Componente | Notas |
|---|------------|-------|
| 1 | Telegram Layer (aiogram) | long-polling + business_message + admin DM |
| 2 | Middleware stack | Auth (allowlist) + Forbidden words + Owner detection |
| 3 | TurnOrchestrator | Entrada del turno + cancelación de pending |
| 4 | CognitiveDirector | Orquestación determinista del happy path |
| 5 | Analyst | LLM → Comprehension (versión mínima) |
| 6 | ContextBuilder | Prompt mínimo (persona + historial reciente + mensaje actual) |
| 7 | Generator | LLM → texto del borrador |
| 8 | Evaluator | LLM → EvaluationProfile (vector 7 dimensiones) |
| 9 | Decider | Reglas deterministas → Decision (solo `approve` o `escalate` en MVP) |
| 10 | BehaviorEngine | delay + read + typing + send + cancel |
| 11 | AdminService + keyboards | Aprobar / Corregir / Ver traza resumida |
| 12 | Persistencia mínima | vips, message_history, pipeline_traces, pending_deliveries, system_config |
| 13 | Escalación determinística | Antes del Analista |

### Explícitamente fuera de alcance (se stubbean o no existen)

| Componente | Tratamiento en MVP |
|------------|--------------------|
| Capability Registry + Retrievers | No existen. ContextBuilder usa solo historial + persona fija |
| 5 tipos de conocimiento / pgvector | No |
| Staging Area / Learning | No se escribe nada en bancos de conocimiento |
| Zona gris / consult_doctrine | No. Decider solo puede devolver `approve` o `escalate` |
| Modo autónomo | Solo existe modo supervisado |
| Sandbox | No |
| Recontacto / Promo no-VIP | No |
| Hot-swap de LLM | Hardcodeado a DeepSeek (interfaz ya preparada) |
| Métricas / calibración | No |
| Notas manuales / memoria por VIP | No |

---

## 3. Componentes del MVP — responsabilidades y contratos

### 3.1 Telegram Layer + Middleware

**Orden obligatorio del middleware stack:**

```
1. LoggingMiddleware
2. BusinessConnectionExtractor      # inyecta business_connection_id
3. OwnerDetectionMiddleware         # si es la dueña → cancel_pending + observe only
4. ForbiddenKeywordsMiddleware      # cortocircuito → escalate (ANTES del Analista)
5. AuthMiddleware                   # ¿está en allowlist y no está paused?
6. → TurnOrchestrator
```

**Contrato de entrada al sistema:**

```python
class IncomingTurn(BaseModel):
    chat_id: int
    telegram_user_id: int
    message_id: int
    text: str
    business_connection_id: str
    timestamp: datetime
    is_from_owner: bool = False
```

### 3.2 TurnOrchestrator

**Responsabilidad:** punto de entrada de un turno VIP. Cancela lo anterior y lanza el Director.

```python
class TurnOrchestrator:
    def __init__(self, director: CognitiveDirector, behavior: BehaviorEngine, ...): ...

    async def handle_vip_message(self, turn: IncomingTurn) -> None:
        # 1. Cancelar cualquier delivery pendiente de este chat
        await self.behavior.cancel_pending(turn.chat_id, reason="new_message")

        # 2. Guardar mensaje en message_history
        await self.history.append(turn)

        # 3. Ejecutar pipeline cognitivo
        decision = await self.director.handle_turn(turn)

        # 4. Actuar según Decision
        if decision.action == "escalate":
            await self.admin.notify_escalation(turn, decision)
        elif decision.action == "approve":
            await self.admin.send_draft_for_approval(turn, decision)
        else:
            # En MVP no deberían llegar otras acciones
            raise ValueError(f"Unexpected action in MVP: {decision.action}")
```

### 3.3 CognitiveDirector (MVP)

**Responsabilidad:** orquestar el happy path de forma determinista.

```python
class CognitiveDirector:
    async def handle_turn(self, turn: IncomingTurn) -> Decision:
        # 1. Analyst
        comprehension = await self.analyst.analyze(turn)
        await self.trace.store(turn_id, "comprehension", comprehension)

        # 2. ContextBuilder (MVP: solo historial + persona)
        recent_history = await self.history.get_recent(turn.chat_id, limit=12)
        prompt = self.context_builder.build(
            turn=turn,
            comprehension=comprehension,
            history=recent_history,
            persona=self.persona,          # texto fijo de la dueña
        )
        await self.trace.store(turn_id, "prompt", prompt)

        # 3. Generator
        draft = await self.generator.generate(prompt)
        await self.trace.store(turn_id, "generated", draft)

        # 4. Evaluator
        evaluation = await self.evaluator.evaluate(draft, comprehension, turn)
        await self.trace.store(turn_id, "evaluation", evaluation)

        # 5. Decider
        decision = self.decider.decide(evaluation, comprehension, mode="supervised")
        decision.draft_text = draft
        await self.trace.store(turn_id, "decision", decision)

        return decision
```

**Nota MVP:** No hay Planner ni Registry. El ContextBuilder es deliberadamente simple.

### 3.4 Analyst

```python
class Analyst(Protocol):
    async def analyze(self, turn: IncomingTurn) -> Comprehension: ...

class Comprehension(BaseModel):
    intent: str
    topics: list[str]
    emotion: str
    urgency: Literal["baja", "media", "alta"]
    risk: Literal["bajo", "medio", "alto"]
    # En MVP los needs_* se ignoran (no hay retrieval)
    raw_llm_output: dict | None = None
```

### 3.5 ContextBuilder (MVP)

```python
class ContextBuilder:
    def build(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
        history: list[Message],
        persona: str,
    ) -> str:
        """
        Construye un prompt mínimo:
        - Instrucciones de persona/voz
        - Historial reciente (últimos N mensajes)
        - Mensaje actual del VIP
        - Instrucción de responder como la dueña
        """
        ...
```

### 3.6 Generator

```python
class Generator(Protocol):
    async def generate(self, prompt: str) -> str: ...
```

Solo recibe el prompt ya construido y devuelve texto. Nada más.

### 3.7 Evaluator

```python
class Evaluator(Protocol):
    async def evaluate(
        self,
        draft: str,
        comprehension: Comprehension,
        turn: IncomingTurn,
    ) -> EvaluationProfile: ...

class EvaluationProfile(BaseModel):
    naturalness: float
    precision: float
    doctrine: float
    consistency: float
    safety: float
    coverage: float
    empathy: float
    raw_llm_output: dict | None = None
```

### 3.8 Decider (MVP — solo dos acciones)

```python
class Decider:
    def decide(
        self,
        evaluation: EvaluationProfile,
        comprehension: Comprehension,
        mode: Literal["supervised"] = "supervised",
    ) -> Decision:
        # Reglas mínimas MVP
        if evaluation.safety < 0.75 or comprehension.risk == "alto":
            return Decision(
                action="escalate",
                reason="safety_or_risk_high",
                evaluation=evaluation,
            )

        # En MVP solo existe modo supervisado → siempre approve
        return Decision(
            action="approve",
            reason="ok_for_human_review",
            evaluation=evaluation,
        )

class Decision(BaseModel):
    action: Literal["approve", "escalate"]   # MVP restringido
    reason: str
    evaluation: EvaluationProfile
    draft_text: str | None = None
```

### 3.9 BehaviorEngine (MVP)

```python
class DeliveryContext(BaseModel):
    chat_id: int
    business_connection_id: str
    vip_id: int | None = None
    mode: Literal["supervised"] = "supervised"

class DeliveryResult(BaseModel):
    success: bool
    message_ids: list[int] = []
    actual_delay_seconds: float = 0.0
    typing_duration_seconds: float = 0.0
    error: str | None = None

class BehaviorEngine:
    async def deliver(
        self,
        texts: list[str],
        ctx: DeliveryContext,
        turn_id: UUID,
    ) -> DeliveryResult: ...

    async def cancel_pending(self, chat_id: int, reason: str = "new_message") -> None: ...
```

**Secuencia de `deliver` en MVP:**

1. Insertar fila en `pending_deliveries` (status=`pending`)
2. `asyncio.create_task` con:
   - `await asyncio.sleep(random.uniform(4, 14))`          # delay supervisado
   - `read_business_message(...)`
   - `send_chat_action("typing")` + sleep proporcional a `len(text)`
   - `send_message(..., business_connection_id=...)`
3. Actualizar `pending_deliveries` → `done` + guardar message_ids
4. Devolver `DeliveryResult`

**Cancelación:**
- `Task.cancel()` + marcar status=`cancelled` en DB.

### 3.10 AdminService (MVP)

**Responsabilidades:**
- Enviar borrador + contexto resumido a la dueña
- Manejar callbacks: Aprobar / Corregir
- Notificar escalaciones

```python
class AdminService:
    async def send_draft_for_approval(
        self,
        turn: IncomingTurn,
        decision: Decision,
    ) -> None:
        """
        Envía al DM de la dueña:
        - Texto del VIP
        - Borrador propuesto
        - Resumen de EvaluationProfile
        - Botones: [✅ Aprobar] [✏️ Corregir] [🚫 Escalar]
        """
        ...

    async def handle_approve(self, callback, turn_id: UUID) -> None:
        # Recuperar decision.draft_text
        # Llamar BehaviorEngine.deliver(...)
        ...

    async def handle_correct(self, callback, turn_id: UUID, corrected_text: str) -> None:
        # Entregar el texto corregido vía BehaviorEngine
        # (En MVP no escribimos en Staging todavía)
        ...

    async def notify_escalation(self, turn: IncomingTurn, decision: Decision) -> None:
        ...
```

---

## 4. Modelo de datos mínimo para MVP

Solo estas tablas:

```sql
-- Allowlist
CREATE TABLE vips (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_user_id BIGINT NOT NULL UNIQUE,
    display_name     TEXT,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    paused_until     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Historial reciente
CREATE TABLE message_history (
    id                  BIGSERIAL PRIMARY KEY,
    chat_id             BIGINT NOT NULL,
    telegram_message_id BIGINT,
    role                TEXT NOT NULL,          -- 'vip' | 'owner' | 'bot'
    text                TEXT NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL
);
CREATE INDEX ON message_history (chat_id, timestamp DESC);

-- Trazas del pipeline (auditoría mínima)
CREATE TABLE pipeline_traces (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id         UUID NOT NULL UNIQUE,
    vip_id          UUID REFERENCES vips(id),
    chat_id         BIGINT NOT NULL,
    incoming_text   TEXT,
    comprehension   JSONB,
    prompt_text     TEXT,
    generated_text  TEXT,
    evaluation      JSONB,
    decision        JSONB,
    delivery_result JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Deliveries en vuelo (Behavior Engine)
CREATE TABLE pending_deliveries (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id                 BIGINT NOT NULL,
    business_connection_id  TEXT NOT NULL,
    texts                   JSONB NOT NULL,
    turn_id                 UUID NOT NULL,
    scheduled_at            TIMESTAMPTZ NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'pending',  -- pending | delivering | done | cancelled | expired
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON pending_deliveries (status, scheduled_at);

-- Borradores pendientes de aprobación (modo supervisado)
CREATE TABLE pending_approvals (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id                 UUID NOT NULL UNIQUE,
    vip_id                  UUID REFERENCES vips(id),
    chat_id                 BIGINT NOT NULL,
    business_connection_id  TEXT NOT NULL,
    draft_text              TEXT NOT NULL,
    cognitive_summary       TEXT,                    -- resumen legible para la dueña
    evaluation              JSONB,
    status                  TEXT NOT NULL DEFAULT 'waiting',  -- waiting | approved | corrected | cancelled | expired
    owner_message_id        BIGINT,                  -- mensaje del DM con los botones
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at             TIMESTAMPTZ
);
CREATE INDEX ON pending_approvals (status, created_at);

-- Escalaciones
CREATE TABLE escalations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vip_id          UUID REFERENCES vips(id),
    chat_id         BIGINT NOT NULL,
    reason          TEXT NOT NULL,
    trigger_text    TEXT,
    status          TEXT NOT NULL DEFAULT 'open',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Configuración mínima
CREATE TABLE system_config (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ejemplo de filas iniciales
INSERT INTO system_config (key, value) VALUES
('global_mode', '"supervised"'),
('owner_telegram_id', '123456789'),
('forbidden_keywords', '["pago", "transferencia", "eres un bot", "reclamación"]'),
('eval_thresholds', '{"safety": 0.75}');
```

---

## 5. Flujos críticos del MVP (paso a paso)

### 5.1 Happy path — VIP escribe → dueña aprueba

```
1. VIP envía mensaje (business_message)
2. Middleware:
   - Extrae business_connection_id
   - No es la dueña
   - No contiene palabras prohibidas
   - Está en allowlist y no está paused
3. TurnOrchestrator:
   - cancel_pending(chat_id)
   - guarda mensaje en message_history
   - llama Director.handle_turn()
4. Director:
   - Analyst → Comprehension
   - ContextBuilder → prompt (persona + historial + mensaje)
   - Generator → draft
   - Evaluator → EvaluationProfile
   - Decider → Decision(action="approve", draft_text=...)
5. AdminService envía al DM de la dueña:
   - Mensaje del VIP
   - Borrador
   - Resumen de evaluación
   - Botones [✅ Aprobar] [✏️ Corregir]
6. Dueña pulsa ✅ Aprobar
7. AdminService → BehaviorEngine.deliver(texts=[draft], ctx=...)
8. BehaviorEngine:
   - delay 4-14 s
   - mark as read
   - typing indicator
   - send_message con business_connection_id
9. Se actualiza pipeline_traces.delivery_result
```

### 5.2 Dueña corrige

```
1-5. Igual que arriba
6. Dueña pulsa ✏️ Corregir → se le pide el texto nuevo
7. AdminService recibe el texto corregido
8. BehaviorEngine.deliver(texts=[corrected_text], ...)
9. (En MVP no se guarda en Staging)
```

### 5.3 Escalación determinística

```
1. VIP envía mensaje con palabra prohibida
2. ForbiddenKeywordsMiddleware detecta match
3. Se crea notificación de escalación a la dueña
4. NO se llama al Director ni al Analista
5. VIP no recibe ninguna respuesta automática
```

### 5.4 Cancelación por mensaje nuevo

```
1. VIP envía mensaje A → se genera borrador y se espera aprobación
2. VIP envía mensaje B antes de que la dueña apruebe
3. TurnOrchestrator recibe B:
   - cancel_pending(chat_id)  → se cancela cualquier Task de delivery del mensaje A
   - se inicia pipeline limpio para el mensaje B
4. El borrador del mensaje A queda obsoleto (no se envía)
```

### 5.5 Reinicio del proceso

```
Al arrancar main.py:
1. SELECT * FROM pending_deliveries WHERE status = 'pending'
2. Para cada uno:
   - Si scheduled_at es muy antiguo → marcar 'expired' + notificar dueña
   - Si todavía es válido → re-crear el asyncio.Task
3. (Opcional) re-notificar borradores pendientes de aprobación
```

---

## 6. Interfaces LLM (MVP)

```python
class LLMProvider(Protocol):
    name: str

    async def generate(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str: ...

    async def generate_structured(
        self,
        messages: list[dict],
        schema: type[BaseModel],
        **kwargs,
    ) -> BaseModel: ...
```

En MVP se usa solo `DeepSeekProvider` (OpenAI-compatible).  
La interfaz ya permite añadir Anthropic después sin tocar el Cognitive Core.

**Uso:**
- Analyst y Evaluator → `generate_structured`
- Generator → `generate` (texto libre)

---

## 7. Estructura de carpetas mínima para MVP

```
src/diana/
├── main.py                     # entrypoint long-polling
├── config.py                   # Pydantic Settings
│
├── telegram/
│   ├── handlers/
│   │   ├── business.py         # business_message
│   │   └── admin.py            # DM + callbacks
│   ├── middlewares/
│   │   ├── auth.py
│   │   ├── forbidden.py
│   │   └── owner.py
│   └── keyboards.py
│
├── application/
│   ├── turn_orchestrator.py
│   └── admin_service.py
│
├── cognitive/
│   ├── director.py
│   ├── analyst.py
│   ├── context_builder.py
│   ├── generator.py
│   ├── evaluator.py
│   ├── decider.py
│   └── models.py               # Comprehension, EvaluationProfile, Decision, IncomingTurn
│
├── behavior/
│   ├── engine.py
│   └── timer_manager.py        # dict[chat_id, Task]
│
├── llm/
│   ├── provider.py
│   └── deepseek.py
│
└── infrastructure/
    ├── db/
    │   ├── models.py           # SQLAlchemy
    │   ├── session.py
    │   └── repositories/
    └── tracing.py
```

---

## 8. Orden de implementación recomendado (MVP)

| Paso | Qué construir | Criterio de “hecho” |
|------|---------------|---------------------|
| 1 | Proyecto + config + DB + tablas mínimas | `alembic upgrade head` funciona |
| 2 | aiogram long-polling + handler vacío de business_message | Recibe mensajes de un VIP de prueba |
| 3 | Middleware Auth + Forbidden + Owner | Short-circuits funcionan |
| 4 | Modelos Pydantic + LLMProvider (DeepSeek) | Analyst y Generator devuelven datos |
| 5 | ContextBuilder + Director (happy path) | Se genera un borrador real |
| 6 | Evaluator + Decider | Se obtiene Decision(action="approve") |
| 7 | AdminService + keyboards de aprobación | Dueña recibe borrador y puede aprobar |
| 8 | BehaviorEngine (delay + read + typing + send) | Mensaje llega al VIP con comportamiento human-like |
| 9 | Cancelación de pending + recovery en arranque | Segundo mensaje del VIP cancela el anterior |
| 10 | pipeline_traces completo | Se puede reconstruir un turno |

---

## 9. Criterios de aceptación del MVP

| ID | Criterio | Cómo verificar |
|----|----------|----------------|
| MVP-01 | Un VIP de la allowlist recibe respuesta solo después de aprobación | Prueba manual |
| MVP-02 | El mensaje sale con business_connection_id (como la dueña) | Inspección en Telegram |
| MVP-03 | Hay delay + mark-as-read + typing antes del envío | Observación visual |
| MVP-04 | Un segundo mensaje del VIP cancela el borrador anterior | Prueba de carrera |
| MVP-05 | Palabra prohibida → escalación sin llamar al LLM | Log + notificación |
| MVP-06 | Reinicio del proceso no pierde deliveries pendientes válidos | Matar proceso y reiniciar |
| MVP-07 | Toda decisión deja traza en pipeline_traces | Query a la tabla |
| MVP-08 | El Director no contiene ninguna llamada a LLM de control de flujo | Code review + AGENTS.md checklist |

---

## 10. Qué se deja preparado para la siguiente fase

Aunque no se implemente en el MVP, la estructura ya debe permitir:

- Añadir Capability Registry sin tocar el Director (solo se cambia ContextBuilder → Planner + Registry)
- Cambiar Decider para soportar `send`, `consult_doctrine`, `regenerate`
- Añadir Staging Area en el flujo de corrección
- Introducir pgvector y los 5 tipos de conocimiento
- Activar modo autónomo solo cambiando la lógica del Decider + system_config

---

**Fin del diseño de componentes del MVP**

Este documento es la guía de implementación de la Fase 1.  
Cualquier desviación que rompa los contratos de `AGENTS.md` debe ser rechazada.

Equipo de Arquitectura — Julio 2026
