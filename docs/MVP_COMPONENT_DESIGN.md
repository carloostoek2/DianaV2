# MVP Component Design — Supervised Mode (Fase 1)
**Diana Business Bot**

| Campo | Valor |
|-------|--------|
| Nivel | Diseño de componentes para el primer valor seguro |
| Basado en | `REQUERIMIENTOS.md` v2.1 + `docs/SPEC-1.1.md` v1.5 + `AGENTS.md` v1.0 |
| Objetivo | Entregar el MVP Supervisado (Fase 1) sin romper la arquitectura híbrida |
| Versión | 1.2 |
| Fecha | Julio 2026 (diseño) · 2026-08-21 (actualización de estado) |
| Estado | **Implementado y desplegado** (2026-08-21) |
| Fuente de verdad de diseño | `docs/SPEC-1.1.md` (este doc es la guía de componentes de Fase 1) |

> **Nota de estado (2026-08-21):** Guía de componentes de Fase 1 — **implementada y desplegada**.
> El diseño de componentes que sigue describe el sistema actual en su núcleo supervisado: la Fase 1 está
> en producción y la Fase 2 (memoria, zona gris, staging, sandbox) también está implementada. Para la vista
> consolidada del sistema tal como existe hoy, referirse a `docs/ARCHITECTURE.md`. Las referencias a
> "no se implementa en Fase 1" o "listo para Fase 2" que hayan quedado en secciones posteriores se
> actualizaron al estado real o se marcaron como fuera de alcance sin prometer nada.

---

## 0. Principio rector (no negociable)

> El sistema no genera respuestas.  
> El sistema toma decisiones.  
> Las respuestas son únicamente una consecuencia de esas decisiones.

Consecuencias para el MVP:

- **Director 100 % determinista** — nunca pregunta a un LLM "qué hacer".
- **Cada componente responde una sola pregunta**.
- **Explicabilidad total** — objetos intermedios persistidos.
- **Sustituibilidad** — Capability Registry desde el día 1 (reales o STUB).
- **Anti-contaminación** — la Memoria de un VIP y el banco de ejemplos permanecen aislados; la escritura en bancos de conocimiento es siempre post-turno y controlada (Staging Area con promoción explícita).

---

## 1. Objetivo del MVP

Un VIP autorizado envía un mensaje → el sistema genera un borrador → la dueña lo ve en su DM → aprueba o corrige → el mensaje se entrega en nombre de la dueña con delay + lectura + typing.

**Criterio de éxito (AC-01 + AC-03 + AC-05 + roadmap de Fase 1 de SPEC-1.1) — cumplido:**

- El VIP recibe la respuesta como si fuera la dueña (Business Connection).
- Nada llega al VIP sin aprobación explícita.
- Hay espera, mark-as-read y typing indicator.
- Escalación por palabras prohibidas funciona sin pasar por el LLM.
- Un segundo mensaje del VIP supersede el turno anterior y cancela deliveries.
- Toda decisión deja traza reconstruible en `pipeline_traces` + estado en `turns`.

Hoy (2026-08-21) estos criterios están implementados y desplegados; el diseño de componentes de este documento describe el sistema actual. Ver `docs/ARCHITECTURE.md` para la vista consolidada.

---

## 2. Alcance exacto del MVP (Fase 1)

### Dentro de alcance

| # | Componente | Notas (alineado a SPEC-1.1 §4 / §8) |
|---|------------|-------------------------------------|
| 1 | Telegram Layer (aiogram 3.x) | long-polling + `business_message` + admin DM |
| 2 | Middleware stack | Auth (allowlist) + Forbidden words + Owner detection |
| 3 | **Turn Coordinator** | Serializa por `chat_id`, máquina de estados, supersede (REQ-VIP-06) |
| 4 | TurnOrchestrator / Application | Caso de uso: entrada VIP → Director → Admin/Behavior |
| 5 | CognitiveDirector | Pipeline determinista completo de Fase 1 |
| 6 | Analyst | LLM → `Comprehension` (con flags `needs_*`) |
| 7 | **Planner** | Determinista → lista de capacidades |
| 8 | **Capability Registry + Retrievers** | `history` y `context` REAL (parcial); resto STUB → null |
| 9 | ContextBuilder | Prompt mínimo dinámico (omite bloques null) |
| 10 | Generator | LLM → texto del borrador |
| 11 | Evaluator | LLM → `EvaluationProfile` (vector 7D) |
| 12 | Decider | Solo `approve` o `escalate` (modo supervisado global) |
| 13 | BehaviorEngine | delay + read + typing + send + cancel |
| 14 | AdminService + keyboards | Aprobar / Corregir / Escalar + menú básico |
| 15 | Persistencia Fase 1 | `vips`, `message_history`, `pipeline_traces`, `pending_deliveries`, `turns`, `escalation_events`, `system_config`, `pending_approvals` |
| 16 | Learning post-turno (mínimo) | Solo persistir traza; sin Staging |

**Nota (2026-08-21):** los 16 componentes de esta tabla están **implementados y desplegados**. El aprendizaje
post-turno hoy incluye además extracción de memoria y candidatos a Staging (ver `docs/ARCHITECTURE.md` §3),
y los retrievers que en Fase 1 eran STUB ya son reales (ver §5.7).

### Fuera del alcance del MVP (Fase 1) — estado actual

| Componente | Tratamiento en Fase 1 | Estado actual (2026-08-21) |
|------------|------------------------|----------------------------|
| Retrievers de memory / policy / examples / profile / schedule | **STUB** que devuelven `null` | **REAL** — memoria pgvector, perfil, política, ejemplos y schedule implementados (+ `persona_facts`, `voice_patterns`) |
| pgvector / embeddings | No | **Implementado** — pgvector con índices HNSW + sentence-transformers local (ADR-005) |
| Staging Area / destilación / promoción | No se escribe en bancos vivos | **Implementado** — corrección guarda en `staging_candidates`; pasa a `examples` solo tras promoción explícita |
| Zona gris / `consult_doctrine` | Decider no puede devolverlo | **Implementado** — el Decisor emite `consult_doctrine`; congela al VIP y pregunta a la dueña (ver ARCHITECTURE §3) |
| `regenerate` | Deshabilitado (dueña corrige en DM) | **Implementado** — variantes/regeneración de borrador (`application/draft_variants.py`) |
| Modo autónomo / `send` directo | Solo supervisado → siempre `approve` o `escalate` | **Cableado pero deshabilitado** — `FEATURE_AUTONOMOUS_MODE=false`; doble puerta vía `autonomous_mode_service` |
| Sandbox / FakeDelivery | No | **Implementado** — conversaciones con perfiles ficticios + `FakeDelivery` |
| Recontacto / Promo no-VIP | No | **Implementado** — recontacto por silencio y promo por trigger exacto (flags `true`) |
| Hot-swap de LLM en runtime | Interfaz abstracta lista; instancia DeepSeek | **Parcial** — interfaz `LLMProvider` con DeepSeek primario y Anthropic como respaldo configurable (ADR-006); el cambio dinámico en runtime **no** está implementado (ADM-03 pendiente) |
| FreezeCheck middleware | No (Fase 2) | **Implementado** — `FreezeCheckMiddleware` activo (ver §5.1) |
| Métricas agregadas | No | **Parcial** — métricas de admin y calibración existen; la calibración automática está por flag (`FEATURE_CALIBRATION_ENABLED=false`) |

---

## 3. Arquitectura de Fase 1 (vista rápida)

```
Telegram Business Connection (aiogram 3.x)
        │
        ▼
┌───────────────────────────────────────────────────────────────────┐
│  MIDDLEWARES                                                      │
│  ErrorHandler → Dedup → RateLimit → Logging → BC → Link → Owner    │
│  → FreezeCheck → Auth (allowlist) → Forbidden (cortocircuito)     │
└───────────────────────────────┬───────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────┐
│  TURN COORDINATOR                                                 │
│  • 1 turno no terminal por chat_id                                │
│  • supersede + cancel delivery del turno anterior                 │
│  • máquina de estados del Turn                                    │
└───────────────────────────────┬───────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────┐
│  COGNITIVE CORE (puro)                                            │
│  Director → Analyst → Planner → Registry/Retrievers               │
│  → ContextBuilder → Generator → Evaluator → Decider               │
└───────────────────────────────┬───────────────────────────────────┘
                                │ Decision (approve | escalate | consult_doctrine | send*)
┌───────────────────────────────▼───────────────────────────────────┐
│  AdminService (DM dueña)  →  BehaviorEngine (solo tras approve)   │
└───────────────────────────────┬───────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────┐
│  LEARNING post-turno: Staging Area + memoria + métricas           │
│  (nunca durante el pipeline)                                      │
└───────────────────────────────────────────────────────────────────┘
```

`* send` solo con `FEATURE_AUTONOMOUS_MODE=true` (hoy deshabilitado). El orden de middlewares refleja el
registro real en `src/diana/telegram/setup.py`.

---

## 4. Máquina de estados del Turn

Cada mensaje VIP crea un `Turn` que transita así (SPEC-1.1 §3):

```
[received]
    │
    ├──(cortocircuito palabra prohibida)──► [escalated] (TERMINAL)
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
                              └──(nuevo msg del VIP)──► [superseded] (TERMINAL)
```

**Invariante crítica:** solo puede existir un Turn no terminal  
(`status` ∉ `{superseded, delivered, failed, escalated}`) por `chat_id`.

El **Turn Coordinator** lo garantiza (serialización por chat: `SELECT … FOR UPDATE` sobre `turns`, o cola FIFO en memoria por `chat_id`).

**Estados añadidos tras Fase 1 (hoy activos):** `gray_zone` (zona gris / consulta de doctrina),
`waiting_delay` (delivery en vuelo tras aprobación) y `promo_pending` (secuencia promo no-VIP).
El conjunto vigente vive en `src/diana/cognitive/models.py` (`TurnStatus`) y se describe en
`docs/ARCHITECTURE.md` §3. El diagrama de arriba sigue siendo el flujo canónico del núcleo supervisado.

---

## 5. Componentes — responsabilidades y contratos

### 5.1 Telegram Layer + Middleware

**Orden del stack (registrado en `src/diana/telegram/setup.py`; implementado):**

```
1. ErrorHandlerMiddleware
2. DedupMiddleware
3. RateLimitMiddleware
4. LoggingMiddleware
5. BusinessConnectionMiddleware     # inyecta business_connection_id
6. LinkCoordinatorMiddleware       # coordinación Lucien → Diana
7. OwnerDetectionMiddleware        # dueña → cancel_pending + observe only
8. FreezeCheckMiddleware           # congela VIPs en zona gris (F2) y canal de atención (F4)
9. AuthMiddleware                  # allowlist + not paused
10. ForbiddenKeywordsMiddleware    # cortocircuito → escalate (ANTES del Analista)
11. → Turn Coordinator / application entry
```

`FreezeCheckMiddleware` (índice 6, `src/diana/telegram/freeze_middleware.py`) **está implementado y activo**:
descarta silenciosamente los mensajes de VIPs con `frozen_until` futuro y, cuando un VIP congelado con
consulta de doctrina abierta insiste, notifica a la dueña con un recordatorio debounced (TTL por defecto
20 min). Es fail-closed ante error de lookup y cachea el `vip_record` para que `AuthMiddleware` lo reutilice.
La línea de "slot de middleware listo para Fase 2" quedó obsoleta.

**Contrato de entrada:**

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

### 5.2 Turn Coordinator

**Pregunta:** ¿Cómo garantizo un solo turno vivo por chat y su ciclo de vida?

```python
class TurnCoordinator:
    async def begin_turn(self, incoming: IncomingTurn) -> Turn:
        """
        1. Adquirir lock por chat_id
        2. Marcar turnos no terminales previos como superseded
        3. cancel_pending(chat_id) en BehaviorEngine
        4. Crear Turn(status='received') y devolverlo
        """
        ...

    async def transition(self, turn_id: UUID, new_status: str, **meta) -> Turn: ...

    async def mark_failed(self, turn_id: UUID, error: str) -> Turn: ...
```

Estados vigentes (columna `turns.status`; la Fase 1 usaba el subset sin `waiting_delay`/`gray_zone`/`promo_pending`):  
`received | waiting_delay | analyzing | planning | retrieving | building_context | generating | evaluating | deciding | pending_approval | gray_zone | promo_pending | escalated | superseded | delivered | failed`

### 5.3 Application entry (TurnOrchestrator)

Orquesta el caso de uso; no contiene lógica cognitiva.

```python
class TurnOrchestrator:
    def __init__(
        self,
        coordinator: TurnCoordinator,
        director: CognitiveDirector,
        admin: AdminService,
        behavior: BehaviorEngine,
        history: MessageHistoryRepo,
        ...
    ): ...

    async def handle_vip_message(self, incoming: IncomingTurn) -> None:
        turn = await self.coordinator.begin_turn(incoming)
        await self.history.append(incoming)

        try:
            decision = await self.director.handle_turn(turn, incoming)
        except Exception as exc:
            await self.coordinator.mark_failed(turn.id, str(exc))
            raise

        if decision.action == "escalate":
            await self.coordinator.transition(turn.id, "escalated")
            await self.admin.notify_escalation(incoming, decision, turn.id)
        elif decision.action == "approve":
            await self.coordinator.transition(turn.id, "pending_approval")
            await self.admin.send_draft_for_approval(incoming, decision, turn.id)
        else:
            # Fase 1: solo approve | escalate. Hoy el orquestador además maneja
            # consult_doctrine (zona gris) y send (autónomo, solo con flag).
            raise ValueError(f"Unexpected action in Fase 1: {decision.action}")

        # Learning post-turno (hoy: traza + memoria + candidatos a Staging)
        await self.learning.run_post_turn(turn.id)
```

### 5.4 CognitiveDirector (Fase 1)

**Pregunta:** ¿Qué necesita este turno?  
**Naturaleza:** 100 % determinista en el control de flujo.

```python
class CognitiveDirector:
    async def handle_turn(self, turn: Turn, incoming: IncomingTurn) -> Decision:
        # 0. Cortocircuito de palabras prohibidas puede vivir en middleware;
        #    si llega aquí, el texto ya es "seguro" a nivel léxico.
        #    (El Director NO decide acción con LLM.)

        await self.coordinator.transition(turn.id, "analyzing")
        comprehension = await self.analyst.analyze(incoming)
        await self.trace.store(turn.id, "comprehension", comprehension)

        await self.coordinator.transition(turn.id, "planning")
        plan = self.planner.plan(comprehension)  # lista de capacidades
        await self.trace.store(turn.id, "plan", plan)

        await self.coordinator.transition(turn.id, "retrieving")
        retrieved = {}
        for capability in plan.capabilities:
            retriever = self.registry.resolve(capability)
            retrieved[capability] = await retriever.fetch(incoming, comprehension)
        await self.trace.store(turn.id, "retrieved", retrieved)

        await self.coordinator.transition(turn.id, "building_context")
        prompt = self.context_builder.build(
            turn=incoming,
            comprehension=comprehension,
            knowledge=retrieved,   # nulls se omiten del prompt
            persona=self.persona,
        )
        await self.trace.store(turn.id, "prompt", prompt)

        await self.coordinator.transition(turn.id, "generating")
        draft = await self.generator.generate(prompt)
        await self.trace.store(turn.id, "generated", draft)

        await self.coordinator.transition(turn.id, "evaluating")
        evaluation = await self.evaluator.evaluate(draft, comprehension, incoming)
        await self.trace.store(turn.id, "evaluation", evaluation)

        await self.coordinator.transition(turn.id, "deciding")
        decision = self.decider.decide(
            evaluation=evaluation,
            comprehension=comprehension,
            mode="supervised",
        )
        decision.draft_text = draft
        await self.trace.store(turn.id, "decision", decision)

        return decision
```

**Prohibido en el Director:** importar `aiogram`, `BehaviorEngine`, decidir delays, promediar scores.

### 5.5 Analyst

**Pregunta:** ¿Qué está pasando en este turno?

```python
class Analyst(Protocol):
    async def analyze(self, turn: IncomingTurn) -> Comprehension: ...

class Comprehension(BaseModel):
    intent: str
    topics: list[str]
    emotion: str
    urgency: Literal["baja", "media", "alta"]
    risk: Literal["bajo", "medio", "alto"]
    needs_memory: bool = False
    needs_policy: bool = False
    needs_schedule: bool = False
    needs_examples: bool = False
    needs_history: bool = True
    needs_context: bool = True
    raw_llm_output: dict | None = None
```

Los flags `needs_*` **se usan**: el Planner los mapea a capacidades. En Fase 1 los STUBs devolvían `null` y
el ContextBuilder omitía esos bloques; hoy todos los retrievers son **reales** (memoria pgvector, perfil,
política, ejemplos, schedule) y el ContextBuilder incluye solo los bloques relevantes al turno.

### 5.6 Planner (determinista)

**Pregunta:** ¿Qué conocimiento recuperar?

```python
class Plan(BaseModel):
    capabilities: list[str]  # p.ej. ["knowledge.history", "knowledge.context"]

class Planner:
    def plan(self, comprehension: Comprehension) -> Plan:
        caps: list[str] = []
        if comprehension.needs_history:
            caps.append("knowledge.history")
        if comprehension.needs_context:
            caps.append("knowledge.context")
        if comprehension.needs_memory:
            caps.append("knowledge.memory")
        if comprehension.needs_policy:
            caps.append("knowledge.policy")
        if comprehension.needs_examples:
            caps.append("knowledge.examples")
        if comprehension.needs_schedule:
            caps.append("knowledge.schedule")
        # Siempre asegurar history como mínimo operativo
        if "knowledge.history" not in caps:
            caps.insert(0, "knowledge.history")
        return Plan(capabilities=caps)
```

### 5.7 Capability Registry + Retrievers

**Pregunta:** ¿Qué componente concreto satisface esta capacidad?

```python
class Retriever(Protocol):
    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> Any | None: ...

class CapabilityRegistry:
    def resolve(self, capability: str) -> Retriever: ...
```

| Capacidad | Fase 1 | Estado actual (2026-08-21) |
|-----------|--------|----------------------------|
| `knowledge.history` | **REAL** — últimos N mensajes (SQL) | **REAL** |
| `knowledge.context` | **REAL (parcial)** — estado simple derivado del historial | **REAL** |
| `knowledge.profile` | **STUB** → `null` | **REAL** — perfil persistido |
| `knowledge.memory` | **STUB** → `null` | **REAL** — memoria pgvector |
| `knowledge.policy` | **STUB** → `null` | **REAL** — políticas destiladas |
| `knowledge.examples` | **STUB** → `null` | **REAL** — banco de ejemplos |
| `knowledge.schedule` | **STUB** → `null` | **REAL** |

El Director solo conoce **nombres de capacidad**, nunca clases concretas (TAC-02 / ADR-002).  
La Fase 2 reemplazó los STUBs por retrievers reales **sin tocar el Director** (cero líneas de Cognitive Core),
confirmando la sustituibilidad del Registry.

### 5.8 ContextBuilder

**Pregunta:** ¿Cuál es el contexto mínimo necesario?

```python
class ContextBuilder:
    def build(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
        knowledge: dict[str, Any | None],
        persona: str,
    ) -> str:
        """
        Composición dinámica (REQ-NFR-07):
        - Siempre: persona/voz + reglas de estilo + mensaje actual
        - Incluye solo bloques de knowledge cuyo valor no es null
        - Hoy típico: history + context + memoria + perfil + política/ejemplos
          según `needs_*` y flags
        """
        ...
```

### 5.9 Generator

```python
class Generator(Protocol):
    async def generate(self, prompt: str) -> str: ...
```

Solo recibe el prompt ya construido y devuelve texto. No clasifica, no decide, no busca.

### 5.10 Evaluator

**Pregunta:** ¿Debemos confiar en este mensaje?

```python
class Evaluator(Protocol):
    async def evaluate(
        self,
        draft: str,
        comprehension: Comprehension,
        turn: IncomingTurn,
    ) -> EvaluationProfile: ...

class EvaluationProfile(BaseModel):
    naturalness: float   # naturalidad
    precision: float
    doctrine: float      # doctrina
    consistency: float   # consistencia
    safety: float        # seguridad
    coverage: float      # cobertura
    empathy: float       # empatia
    raw_llm_output: dict | None = None
```

**Nunca** se reduce a un score único (`mean(...)` está prohibido).  
Nombres de campo en código en inglés (AGENTS.md); semántica = vector 7D de SPEC-1.1.

### 5.11 Decider (Fase 1 — modo supervisado)

**Pregunta:** ¿Qué acción tomar?

Reglas de Fase 1 (modo supervisado global, SPEC-1.1 §4.8 + decisión abierta #3):

```python
class Decider:
    def __init__(self, thresholds: dict | None = None):
        # Fuente: system_config['eval_thresholds']; default conservador
        self.safety_threshold = (thresholds or {}).get("safety", 0.3)

    def decide(
        self,
        evaluation: EvaluationProfile,
        comprehension: Comprehension,
        mode: Literal["supervised"] = "supervised",
    ) -> Decision:
        if evaluation.safety < self.safety_threshold or comprehension.risk == "alto":
            return Decision(
                action="escalate",
                reason="safety_or_risk_high",
                evaluation=evaluation,
            )
        # Supervisado: nunca send directo
        return Decision(
            action="approve",
            reason="ok_for_human_review",
            evaluation=evaluation,
        )

class Decision(BaseModel):
    action: Literal["approve", "escalate"]  # Fase 1 restringido
    reason: str
    evaluation: EvaluationProfile
    draft_text: str | None = None
```

- En Fase 1 `regenerate` y `consult_doctrine` estaban **deshabilitados**; hoy están implementados:
  `consult_doctrine` (zona gris, con freeze) y la regeneración de variantes del borrador (MODE-05).
- Umbral inicial de seguridad: **0.3** (conservador); ajustable vía `system_config` y hoy también
  calibrable con el job de calibración (`FEATURE_CALIBRATION_ENABLED=false` en runtime).

**Evolución del contrato (hoy):** el Decisor emite `escalate | consult_doctrine | send | approve` (matriz
pura en `src/diana/cognitive/decider.py`). Orden de prioridades vigente: seguridad baja → `escalate`;
`needs_policy` sin política → `consult_doctrine`; emoción molesta → `escalate`; `risk=alto` → `escalate`;
modo autónomo + umbrales → `send` (solo con `FEATURE_AUTONOMOUS_MODE=true`); resto → `approve`
(referencia: `docs/ARCHITECTURE.md` §3). El código de Fase 1 de arriba es el subconjunto supervisado
que sigue vigente en el modo por defecto.

### 5.12 BehaviorEngine (Fase 1)

**Pregunta:** ¿Cómo se actúa el mensaje? (infraestructura pura)

```python
class DeliveryContext(BaseModel):
    chat_id: int
    business_connection_id: str
    vip_id: UUID | None = None
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
        decision: Decision | None = None,
    ) -> DeliveryResult: ...

    async def cancel_pending(self, chat_id: int, reason: str = "new_message") -> None: ...
```

**Secuencia `deliver`:**

1. Insertar fila en `pending_deliveries` (`status=pending`, con `vip_id` y `decision` si aplica).
2. `asyncio.create_task`:
   - delay configurable (ej. `random.uniform(4, 14)`)
   - `read_business_message(...)`
   - `send_chat_action("typing")` + duración proporcional a `len(text)`
   - `send_message(..., business_connection_id=...)`
3. Actualizar `pending_deliveries` → `done` (+ message_ids).
4. Devolver `DeliveryResult`.

**Cancelación:** `Task.cancel()` + `status=cancelled` en DB.

**Prohibido:** LLM, decidir acción, generar texto.

**Adiciones vigentes (Fase 2, `FEATURE_ADVANCED_BEHAVIOR=true`):** `deliver()` divide el texto por párrafos,
reenvía `send_chat_action("typing")` en loop mientras dura el typing (refresco 4 s) y aplica quirks humanos
probabilísticos (~20 %, priorizando typo + corrección).

### 5.13 AdminService (Fase 1)

```python
class AdminService:
    async def send_draft_for_approval(
        self,
        turn: IncomingTurn,
        decision: Decision,
        turn_id: UUID,
    ) -> None:
        """
        DM de la dueña:
        - Texto del VIP
        - Borrador
        - Resumen de EvaluationProfile
        - Botones: [✅ Aprobar] [✏️ Corregir] [🚫 Escalar]
        Persiste fila en pending_approvals (cola operativa).
        """
        ...

    async def handle_approve(self, callback, turn_id: UUID) -> None:
        # Si el Turn ya está superseded → no entregar
        # BehaviorEngine.deliver(draft)
        # coordinator.transition(turn_id, "delivered")
        ...

    async def handle_correct(self, callback, turn_id: UUID, corrected_text: str) -> None:
        # Entregar texto corregido vía BehaviorEngine
        # Hoy: la corrección guarda el par (original, final) en staging_candidates;
        # solo pasa a `examples` tras promoción explícita.
        # coordinator.transition(turn_id, "delivered")
        ...

    async def notify_escalation(
        self,
        turn: IncomingTurn,
        decision: Decision,
        turn_id: UUID,
    ) -> None:
        # Crea escalation_events + notifica DM
        ...
```

Superficie admin actual: `/start`, `/menu`, alta/baja de VIPs, ver estado, aprobar/corregir borradores, más
doctrina (zona gris), `/staging`, aprobación de memoria, panel de personalidad (`persona_admin`) y vínculo
Lucien → Diana. Ver `docs/ARCHITECTURE.md` §2.2 para el árbol completo.

### 5.14 Learning post-turno (mínimo)

```python
class LearningService:
    async def run_post_turn(self, turn_id: UUID) -> None:
        """Hoy: garantizar pipeline_traces completo + extracción de memoria
        post-turno + candidatos a Staging. Nunca durante el pipeline."""
        ...
```

Se invoca **después** de que el turno tomó decisión de aplicación (approve path → pending_approval /
escalate path), desde el orquestador (`_maybe_post_turn`, con guards best-effort). Nunca dentro del Director.

---

## 6. Modelo de datos Fase 1

Tablas de implementación inmediata (SPEC-1.1 §5 [FASE 1]) más `pending_approvals` y `system_config` como soporte operativo de la cola de DM y umbrales.

```sql
-- VIP allowlist
CREATE TABLE vips (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_user_id BIGINT NOT NULL UNIQUE,
    display_name     TEXT,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    paused_until     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
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

-- Turnos (máquina de estados) — CLAVE Fase 1
CREATE TABLE turns (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id             BIGINT NOT NULL,
    vip_id              UUID REFERENCES vips(id),
    status              TEXT NOT NULL,
    -- received | analyzing | planning | retrieving | building_context |
    -- generating | evaluating | deciding | pending_approval |
    -- escalated | superseded | delivered | failed
    trigger_message_id  BIGINT,
    superseded_by       UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON turns (chat_id, status);
CREATE INDEX ON turns (chat_id, created_at DESC);

-- Trazas completas del pipeline
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
CREATE INDEX ON pipeline_traces (turn_id);

-- Deliveries en vuelo
CREATE TABLE pending_deliveries (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id                 BIGINT NOT NULL,
    vip_id                  UUID REFERENCES vips(id),
    business_connection_id  TEXT NOT NULL,
    texts                   JSONB NOT NULL,
    decision                JSONB NOT NULL,
    scheduled_at            TIMESTAMPTZ NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'pending',
    -- pending | delivering | done | cancelled | expired
    turn_id                 UUID NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON pending_deliveries (status, scheduled_at);

-- Cola operativa de aprobación en DM (soporte de pending_approval)
CREATE TABLE pending_approvals (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id                 UUID NOT NULL UNIQUE,
    vip_id                  UUID REFERENCES vips(id),
    chat_id                 BIGINT NOT NULL,
    business_connection_id  TEXT NOT NULL,
    draft_text              TEXT NOT NULL,
    cognitive_summary       TEXT,
    evaluation              JSONB,
    status                  TEXT NOT NULL DEFAULT 'waiting',
    -- waiting | approved | corrected | cancelled | expired
    owner_message_id        BIGINT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at             TIMESTAMPTZ
);
CREATE INDEX ON pending_approvals (status, created_at);

-- Escalaciones (nombre canónico SPEC: escalation_events)
CREATE TABLE escalation_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id     UUID NOT NULL,
    tipo        TEXT NOT NULL,  -- cortocircuito_determinista | semantica
    motivo      TEXT,
    notificado  BOOLEAN DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Configuración (umbrales, forbidden words, owner id)
CREATE TABLE system_config (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO system_config (key, value) VALUES
('global_mode', '"supervised"'),
('owner_telegram_id', '123456789'),
('forbidden_keywords', '["pago", "transferencia", "eres un bot", "reclamación"]'),
('eval_thresholds', '{"safety": 0.3}'),
('trace_ttl_days', '30');
```

**Nota (2026-08-21):** las tablas de Fase 2/3 (`profiles`, `memories` [pgvector], `contexts`, `policies`,
`examples`, `staging_candidates`, `gray_zone_queries`, `learning_metrics`) y las de fases posteriores
(`recontact_schedules`, `promo_triggers`, `persona_versions`, `atencion_cycles`, `backfill_queue`,
`vip_profile`, `ephemeral_events`, `link_events`, etc.) **están implementadas** en el esquema actual
(migraciones Alembic 001 → 029). La arquitectura de datos vigente está en `docs/ARCHITECTURE.md` §5.
El DDL de arriba se conserva como el contrato del núcleo supervisado de Fase 1.

---

## 7. Flujos críticos (paso a paso)

Los flujos de esta sección siguen siendo el comportamiento canónico del núcleo supervisado hoy
(ver `docs/ARCHITECTURE.md` §3); se anotan las adiciones posteriores donde aplican.

### 7.1 Happy path — VIP escribe → dueña aprueba

```
1. VIP envía business_message
2. Middlewares: connection_id, no-owner, no-forbidden, allowlist OK
3. TurnCoordinator.begin_turn:
   - supersede turno previo no terminal (si hay)
   - cancel_pending(chat_id)
   - crea Turn(status=received)
4. Guarda mensaje en message_history
5. Director:
   analyzing → Analyst → Comprehension
   planning  → Planner → Plan
   retrieving→ Registry (history REAL, context parcial, resto STUB null)
   building_context → prompt (sin bloques null)
   generating → draft
   evaluating → EvaluationProfile
   deciding → Decision(action=approve)
6. Turn → pending_approval; AdminService envía borrador al DM
7. Dueña ✅ Aprobar
8. BehaviorEngine.deliver (delay → read → typing → send)
9. Turn → delivered; pipeline_traces.delivery_result actualizado
10. Learning post-turno: traza completa
```

### 7.2 Dueña corrige

```
1–6. Igual que happy path
7. Dueña ✏️ Corregir → envía texto nuevo
8. BehaviorEngine.deliver(corrected_text)
9. Turn → delivered
10. Hoy: la corrección se guarda en staging_candidates para promoción explícita
```

### 7.3 Escalación determinística (palabra prohibida)

```
1. VIP envía mensaje con keyword prohibida
2. ForbiddenKeywordsMiddleware match
3. TurnCoordinator crea Turn → escalated (o registra evento sin pipeline)
4. escalation_events (tipo=cortocircuito_determinista) + notify dueña
5. NO se llama al Director / Analyst / LLM
6. VIP no recibe respuesta automática
```

### 7.4 Escalación semántica (Decider)

```
1. Pipeline completo hasta Decider
2. safety < umbral OR risk=alto → Decision(action=escalate)
3. Turn → escalated
4. escalation_events (tipo=semantica) + notify dueña
5. Sin delivery al VIP
```

### 7.5 Cancelación / supersede por mensaje nuevo (REQ-VIP-06)

```
1. VIP mensaje A → Turn A en pending_approval (o delivery en curso)
2. VIP mensaje B
3. TurnCoordinator:
   - Turn A → superseded (superseded_by = Turn B)
   - cancel_pending(chat_id)  # Task + pending_deliveries
   - pending_approvals de A → cancelled
   - crea Turn B (received)
4. Pipeline limpio para B
5. Borrador de A no se envía
```

### 7.6 Reinicio del proceso (REQ-PER-02 / TAC-08)

```
main.py arranca:
1. pending_deliveries WHERE status='pending'
   - scheduled_at muy antiguo → expired + notificar dueña
   - aún válido → re-crear asyncio.Task
2. Re-notificar pending_approvals en waiting
3. Re-notificar escalation_events no notificados (opcional)
```

La recuperación en arranque hoy expira deliveries en vuelo sin re-enviar ni auto-aprobar en silencio
(ver `docs/ARCHITECTURE.md` §6).

---

## 8. Interfaces LLM (Fase 1)

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

- Instancia primaria: `DeepSeekProvider` (OpenAI-compatible); Anthropic como respaldo configurable (ADR-006).
- La interfaz abstracta permite el hot-swap sin tocar Cognitive Core. **Nota:** el cambio dinámico de LLM
  en runtime (vía `system_config`) **no** está implementado; la instancia se fija en construcción desde
  `settings.llm_base_url` (ADM-03 pendiente).
- **Uso:** Analyst y Evaluator → `generate_structured`; Generator → `generate`.

---

## 9. Estructura de carpetas (Fase 1 subset de SPEC-1.1 §11)

Árbol de Fase 1 (subset). El árbol real y completo del sistema actual está en `docs/ARCHITECTURE.md` §2.2.

```
src/diana/
├── main.py
├── config.py
│
├── telegram/
│   ├── handlers/
│   │   ├── business.py
│   │   ├── admin.py
│   │   └── callbacks.py
│   ├── middlewares/
│   │   ├── auth.py
│   │   ├── forbidden.py
│   │   └── owner.py          # freeze vive en telegram/freeze_middleware.py
│   └── keyboards.py
│
├── application/
│   ├── turn_coordinator.py   # NUEVO — máquina de estados + serialización
│   ├── turn_orchestrator.py
│   └── admin_service.py
│
├── cognitive/
│   ├── director.py
│   ├── analyst.py
│   ├── planner.py            # determinista
│   ├── context_builder.py
│   ├── generator.py
│   ├── evaluator.py
│   ├── decider.py
│   ├── registry.py           # Capability Registry
│   ├── models.py
│   └── retrievers/
│       ├── base.py
│       ├── history.py        # REAL
│       ├── context.py        # REAL parcial
│       ├── memory.py         # STUB
│       ├── profile.py        # STUB
│       ├── policy.py         # STUB
│       ├── examples.py       # STUB
│       └── schedule.py       # STUB
│
├── behavior/
│   ├── engine.py
│   └── timer_manager.py
│
├── learning/
│   └── post_turn.py          # solo traza en Fase 1
│
├── llm/
│   ├── provider.py
│   └── deepseek.py
│
└── infrastructure/
    ├── db/
    │   ├── models.py
    │   ├── session.py
    │   └── repositories/
    ├── logging.py
    └── tracing.py
```

Los módulos de Fase 2/3 (`application/sandbox.py`, `behavior/fake.py`, `jobs/`, `embeddings`, etc.) que en
Fase 1 "se añadirían al activar la fase" **hoy existen y están activos** (Fase 2/3 desplegadas). Ver el
árbol real en `docs/ARCHITECTURE.md` §2.2.

---

## 10. Orden de implementación recomendado

**Estado: orden ejecutado y desplegado (2026-08-21).** Se conserva como registro histórico del orden de
construcción de Fase 1; los pasos están completos.

| Paso | Qué construir | Criterio de “hecho” |
|------|---------------|---------------------|
| 1 | Proyecto + config + DB + tablas Fase 1 | `alembic upgrade head` OK |
| 2 | aiogram long-polling + handler `business_message` | Recibe mensajes de VIP de prueba |
| 3 | Middlewares Auth + Forbidden + Owner | Short-circuits funcionan |
| 4 | Turn Coordinator + tabla `turns` | 1 no-terminal por chat; supersede OK |
| 5 | LLMProvider + Analyst + Generator | Datos reales desde DeepSeek |
| 6 | Planner + Registry + Retrievers (REAL/STUB) | Registry resuelve todas las capacidades |
| 7 | ContextBuilder + Director (pipeline completo) | Borrador + traza con plan/retrieved |
| 8 | Evaluator + Decider | `approve` / `escalate` según umbrales |
| 9 | AdminService + keyboards + `pending_approvals` | Dueña aprueba/corrige en DM |
| 10 | BehaviorEngine + recovery en arranque | Delay/read/typing/send + cancel |
| 11 | Learning post-turno + `pipeline_traces` completo | Turno reconstruible de punta a punta |

---

## 11. Criterios de aceptación (MVP + TAC Fase 1)

| ID | Criterio | Cómo verificar | SPEC |
|----|----------|----------------|------|
| MVP-01 | VIP allowlist recibe respuesta solo tras aprobación | Prueba manual | TAC / AC |
| MVP-02 | Envío con `business_connection_id` | Inspección Telegram | AC-01 |
| MVP-03 | Delay + mark-as-read + typing | Observación | AC-03 |
| MVP-04 | Segundo mensaje supersede turno y cancela delivery | Prueba de carrera | TAC-07 |
| MVP-05 | Palabra prohibida → escalate sin LLM | Log + notify | TAC-06 |
| MVP-06 | Reinicio no pierde deliveries válidos | Kill + restart | TAC-08 |
| MVP-07 | Objetos intermedios en `pipeline_traces` (incl. plan/retrieved) | Query | TAC-04 |
| MVP-08 | Director sin LLM de control de flujo | Code review | TAC-01 |
| MVP-09 | EvaluationProfile es vector 7D (sin score único) | Code + traza | TAC-03 |
| MVP-10 | Registry resuelve todos los retrievers (REAL o STUB) | Unit tests | TAC-02 |
| MVP-11 | Behavior Engine fuera del Cognitive Core | Import graph | TAC-05 |
| MVP-12 | Decider Fase 1 solo `approve` \| `escalate` | Unit tests | §4.8 |
| MVP-13 | Invariante: ≤1 turno no terminal por `chat_id` | Integration test | §3 |

Estos criterios se verificaron en el merge de Fase 1; los contratos que definen siguen vigentes.

---

## 12. Transiciones que la Fase 1 preparó — estado actual

La Fase 1 dejó al Director llamando a Planner + Registry, listo para crecer sin tocarlo. Estado de cada transición hoy (2026-08-21):

| Cambio preparado | Impacto en Director | Estado hoy |
|------------------|---------------------|------------|
| STUBs → Retrievers REAL + pgvector | **Cero** líneas del Director | **Implementado** — memoria pgvector, perfil, política, ejemplos, schedule reales |
| Activar `consult_doctrine` / `regenerate` | Solo Decider + umbrales | **Implementado** — zona gris y variantes de borrador activos |
| Staging en correcciones | Solo Admin/Learning post-turno | **Implementado** — corrección → `staging_candidates` → promoción explícita |
| Modo autónomo (`send`) | Decider + `system_config` | **Cableado, deshabilitado** — `FEATURE_AUTONOMOUS_MODE=false` + doble puerta |
| Freeze middleware + gray zone | Telegram + Admin; no Cognitive Core | **Implementado** — `FreezeCheckMiddleware` + consulta de doctrina |
| Hot-swap LLM | `llm/` + config | **Parcial** — interfaz lista (DeepSeek primario, Anthropic respaldo); cambio dinámico en runtime pendiente |
| Sandbox / FakeDelivery | `behavior/fake.py` | **Implementado** — sandbox con perfiles ficticios |

---

## 13. Decisiones de implementación adoptadas (de SPEC-1.1 §9)

| # | Tema | Decisión Fase 1 |
|---|------|------------------|
| 1 | Regeneración por naturalidad baja | **No** en Fase 1 (dueña corrige en DM). Hoy implementado como variantes/regeneración del borrador (MODE-05). |
| 2 | Serialización por chat | Preferir lock DB (`turns` + `FOR UPDATE`) o `asyncio.Queue` por chat; documentar en código. |
| 3 | Umbral seguridad inicial | **0.3** en `system_config`; ajustar tras ~50 turnos reales. Hoy existe calibración automática (job, flag OFF por defecto). |
| 4 | TTL de `pipeline_traces` | 30 días (configurable). |

---

## 14. Checklist de revisión (antes de merge)

**Aplicado en el merge de Fase 1 (registro histórico).** Los límites que define siguen vigentes como contrato del núcleo supervisado.

- [ ] ¿El Director sigue siendo 100 % determinista?
- [ ] ¿Existen Planner + Registry con STUBs (no "omitidos")?
- [ ] ¿Turn Coordinator impone 1 no-terminal por chat?
- [ ] ¿EvaluationProfile es vector 7D sin score único?
- [ ] ¿Behavior Engine no genera texto ni decide acción?
- [ ] ¿Learning solo post-turno y solo traza?
- [ ] ¿No se escribe en `examples` / `memories` / Staging?
- [ ] ¿Modos y umbrales salen de config, no hardcode mágico en lógica?
- [ ] ¿Contratos alineados con `AGENTS.md` y `docs/SPEC-1.1.md`?

Si alguna respuesta es "no", el cambio **no se mergea**.

---

**Fin del diseño de componentes del MVP (Fase 1) v1.2**

Guía de diseño de la Fase 1 (núcleo supervisado) — **implementada y desplegada (2026-08-21)**.  
Fuente de verdad de diseño: `docs/SPEC-1.1.md` v1.5.  
Límites duros de módulo: `AGENTS.md`.  
Estado vigente del sistema completo: `docs/ARCHITECTURE.md`.  
Cualquier desviación que rompa esos contratos debe ser rechazada.

Equipo de Arquitectura — Julio 2026
