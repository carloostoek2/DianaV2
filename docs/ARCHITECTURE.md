# Arquitectura — DianaV2

**Fecha de análisis:** 2026-08-21
**Alcance:** guía consolidada de arquitectura del sistema tal como existe hoy. Punto único de entrada técnico.

---

## 1. Visión y filosofía

Diana es una asistente conversacional de Telegram que mantiene conversaciones privadas de clientes VIP con contexto, memoria y supervisión humana. El principio rector del sistema:

> El sistema no genera respuestas. El sistema toma decisiones. Las respuestas son únicamente una consecuencia de esas decisiones.

De aquí derivan los principios no negociables (fuente: `AGENTS.md` §1):

- El **Director es 100 % determinista** y nunca pregunta a un LLM "qué hacer".
- Cada **componente cognitivo responde una sola pregunta**.
- El **Behavior Engine está fuera de la cognición** (solo actúa, nunca decide ni genera).
- El **aprendizaje es siempre post-turno** y controlado (Staging Area).
- Existe **anti-contaminación total** entre la Memoria de un VIP y el banco de ejemplos.
- Toda decisión es **reconstruible a partir de objetos persistidos** (`pipeline_traces`).
- El **Turn Coordinator garantiza la serialización por chat** (un solo turno no terminal por `chat_id`).

**Supervisión antes que autonomía.** La autonomía debe ganarse mediante evidencia, no asumirse por defecto. Las respuestas correctas aumentan lentamente la confianza; una corrección de la dueña la reduce mucho más. Las conversaciones sensibles nunca entran en autonomía, y el autoenvío permanece deshabilitado por flag (ver §4).

## 2. Capas y módulos

### 2.1 Capas y responsabilidad exclusiva

| Capa / Módulo | Pregunta que responde | Puede hacer | Nunca puede hacer |
| --- | --- | --- | --- |
| Telegram Layer (`telegram/`) | ¿Cómo entro y salgo de Telegram? | Recibir updates, enviar mensajes, middlewares de short-circuit | Decidir qué decir, invocar LLM, escribir en tablas de conocimiento |
| Turn Coordinator (`application/turn_coordinator.py`) | ¿Qué turno está vivo? | Serializar por `chat_id`, gestionar la máquina de estados del Turn, cancelar entregas obsoletas | Decidir qué decir, invocar LLM, tocar memoria persistente |
| Application Services (`application/`) | ¿Qué caso de uso es este? | Orquestar Turn, Admin, Sandbox, Recontact, Promo, Calibration | Contener lógica cognitiva, generar texto, evaluar |
| Cognitive Core (`cognitive/`) | ¿Qué decisión tomar? | Ejecutar el pipeline Director → … → Decisor | Conocer aiogram, enviar mensajes, escribir en Staging, decidir delays |
| Capability Registry + Retrievers (`cognitive/retrievers/`) | ¿Qué sabemos sobre X? | Devolver conocimiento estructurado filtrado | Mezclar tipos de conocimiento, devolver Memoria de otro VIP, decidir si se usa |
| Behavior Engine (`behavior/`) | ¿Cómo se actúa el mensaje? | Delay, read, typing, send, cancel, FakeDelivery, split, quirks | Generar texto, decidir acción, invocar Analista/Generador |
| Learning (`learning/`, `application/`) | ¿Qué aprendimos de este turno? | Extraer candidatos, escribir en Staging, destilar políticas, actualizar métricas, calibrar umbrales | Ejecutarse durante el pipeline, promover automáticamente a banco vivo |
| LLM Provider (`llm/`) | ¿Cómo hablo con el modelo? | `generate` y `generate_structured` | Contener prompts de negocio, decidir umbrales, conocer VIP |
| Infrastructure / Persistence | ¿Cómo guardo y recupero datos? | Repositorios, sesiones, migraciones | Contener lógica de negocio o cognitiva |
| Jobs (`jobs/`) | ¿Qué tareas periódicas ejecutar? | Recontacto, purga de trazas, calibración, métricas, síntesis | Interferir con el pipeline de turnos en curso |

**Reglas de dependencia (dirección permitida):**

```
Telegram Layer → Turn Coordinator → Application Services → Cognitive Core
                                                        ↘ Behavior Engine
Application Services → Learning (solo post-turno)  ·  → Jobs (programación)
Cognitive Core → Capability Registry → Retrievers → Persistence
Cognitive Core → LLM Provider
Behavior Engine → Telegram Layer (solo para I/O)
Learning → Persistence   ·   Jobs → Application Services
```

Prohibido: que `cognitive/` importe `telegram/` o `behavior/`; que el Behavior Engine importe Analista/Generador/Evaluador/Decisor; que Learning se llame desde el Director o el pipeline; que un Retriever importe otro de tipo distinto; by-passear el Turn Coordinator; que Jobs ejecuten lógica cognitiva directamente.

### 2.2 Árbol de módulos real (`src/diana/`)

```
src/diana/
├── main.py                    # entrypoint long-polling (aiogram 3)
├── composition.py             # raíz de composición (wiring de dependencias)
├── config/                    # Settings Pydantic (env) + persona_diana.json,
│                              #   persona_atencion.json, sandbox_profiles.json
├── telegram/                  # capa de adaptación Telegram
│   ├── handlers/              # business, admin, callbacks, menu, doctrine,
│   │                          #   staging, memory_approval, persona_admin, link
│   ├── middlewares/           # auth, owner, forbidden, freeze, dedup,
│   │                          #   rate_limit, link, business_connection, error_handler, logging
│   ├── keyboards.py · notifier.py · actuator.py · helpers.py · health.py · setup.py
├── application/               # casos de uso / orquestación
│   ├── turn_coordinator.py    # serialización por chat + máquina de estados del Turn
│   ├── turn_orchestrator.py   # orquestador del turno (pipeline + aprobación + entrega)
│   ├── admin_service.py · admin_metrics_service.py · admin_trace_service.py
│   ├── sandbox.py             # simulación con perfiles ficticios
│   ├── recontact_service.py · promo_service.py · calibration_service.py
│   ├── autonomous_mode_service.py  # doble puerta de autonomía (L1 master flag + vip.auto_send)
│   ├── memory_*.py            # memoria VIP: backfill, extracción post-turno, aprobación, cola
│   ├── profile_synthesis_*.py · strong_signal_heuristics.py  # evolución de agente
│   ├── emotional_signal_detector.py · mood_engine.py · trust_budget_service.py
│   ├── turn_classifier.py     # clasificador fático (4 categorías)
│   ├── gray_zone_service.py · staging_service.py · deterministic_escalate.py
│   ├── ephemeral_event_service.py · ephemeral_knowledge.py  # eventos temporales
│   ├── link.py                # coordinador Lucien → Diana
│   ├── draft_variants.py      # variantes/regeneración de borrador
│   └── recovery*.py · cognitive_recovery.py · missed_message_recovery.py
├── cognitive/                 # CORE PURO (sin Telegram)
│   ├── director.py            # director determinista
│   ├── analyst.py · planner.py · context_builder.py
│   ├── generator.py · evaluator.py · decider.py
│   ├── registry.py            # Capability Registry (sustituibilidad)
│   ├── models.py              # Comprehension, EvaluationProfile (7D), Decision…
│   ├── thresholds.py · runtime_thresholds.py · repetition_guard.py
│   ├── template_gate.py · policy_distiller.py · persona_catalog.py
│   └── retrievers/            # base, memory, profile, history, context, policy,
│                              #   examples, schedule, persona_facts, voice_patterns
├── behavior/                  # Behavior Engine
│   ├── engine.py              # delay → read → typing → (split) → send
│   ├── split.py · quirks.py · timer_manager.py · fake.py (FakeDelivery) · ports.py
├── learning/                  # aprendizaje post-turno (post_turn.py)
├── llm/                       # provider abstracto: deepseek.py (primario), fake.py
├── jobs/                      # recontact, calibration, metrics, trace_purge, backfill,
│                              #   profile_synthesis_job, gray_zone_expiration, agent_data_purge
├── infrastructure/
│   ├── db/                    # models.py (ORM SQLAlchemy), session.py, repositories/ (por tabla)
│   └── telethon/              # vip_history_fetcher.py (historial para backfill)
```

## 3. Flujos canónicos

Los flujos que siguen son los definidos en `AGENTS.md` §3, descritos como operan hoy. **Estados activos:** Fase 1 (flujos base, sin flag) y Fase 2 (con flags) activos; Fase 3 y superiores activos solo según flag (ver §4).

| Flujo | Comportamiento actual |
| --- | --- |
| **Turno VIP normal** (pipeline completo → approve/escalate) | `business_message` → middlewares (auth/forbidden/freeze) → Turn Coordinator → Director (cortocircuito determinista → Analista → Planificador → Retrievers → Constructor de Contexto → Generador → Evaluador 7D → Decisor) → approve/escalate. Aprobado por la dueña → Behavior Engine entrega con delay, lectura y typing. |
| **Escalación determinística** | Short-circuit por palabra/tema prohibido antes del Analista; `Turn.status = escalated`; notifica a la dueña. |
| **Cancelación por mensaje nuevo** | Al llegar un mensaje del mismo chat, el Turn en vuelo se marca `superseded` y se cancela su delivery pendiente. |
| **Turno con memoria** | Retrievers reales (memoria pgvector + perfil + política + ejemplos) según `needs_*`; contexto mínimo dinámico. |
| **Zona gris** | Decisor con `needs_policy` sin política → `consult_doctrine`, congela al VIP/Atención y pide a la dueña una **REGLA** (no el texto al VIP). [Opcional `FEATURE_GRAY_ZONE_PROPOSAL_ENABLED`] `GrayZoneProposalService` genera una propuesta (regla + respuesta sugerida) con contexto general restringido como préstamo temporal (solo lectura, sin contaminación); DM con mensaje original como contexto + bloque de propuesta + teclado `💡 Usar regla propuesta | 📝 Escribir regla | ⚠️ Escalar`. Persistencia **viva** en `policies` (sin `staging_candidates` en el resolve), force-inject + regen del mismo turno, borrador regenerado a cola de aprobación; freeze retenido (`open` \| `awaiting_send`) hasta envío real exitoso (o escalate/discard); si el regen no aplica la regla (consulta de nuevo / borrador vacío / safety del borrador), el caso vuelve a resolución (query `open`, reintentable); escalate por riesgo/frustración del mensaje original con borrador válido SÍ encola el borrador (la dueña decide). Staging sigue solo para correcciones. |
| **Corrección → Staging** | La corrección de la dueña guarda el par (original, final) en `staging_candidates`; solo pasa a `examples` tras promoción explícita. |
| **Sandbox** | Conversaciones contra perfiles ficticios con `FakeDelivery`; aislado de memoria, aprendizaje y datos reales. |
| **Modo autónomo** | Decisor puede emitir `send` si flag + umbrales; la entrega automática exige la doble puerta (`autonomous_mode_service`), si no se demota a `approve`. **Ruta cableada pero deshabilitada** (`FEATURE_AUTONOMOUS_MODE=false`). |
| **Recontacto por silencio** | Job periódico → `RecontactService.get_due_vips()` → pipeline reducido (sin Analista/Planificador, plantillas fijas) → send o approve. Nunca si el VIP está congelado/en pausa/con aprobación pendiente. |
| **Promo no-VIP** | `business_message` de no-VIP → `match_trigger` exacto → secuencia fija con delays vía Behavior Engine; sin LLM, sin `pipeline_traces`. |
| **Calibración de umbrales** | Job semanal → percentiles de corrección sobre `pipeline_traces` → actualiza `system_config`; drift vs baseline notifica a la dueña. |
| **Mensajes divididos y quirks** | `deliver()` divide por párrafos y reenvía typing; quirks humanos probabilísticos (~20 %, priorizando typo + corrección). |
| **Feedback Destacar / Reprender** | En borradores VIP: Destacar → ejemplo `quality=gold` (este VIP o global); Reprender → entrega la corrección ya y promueve contraejemplo. Invariante: Atención no destaca ni reprende. |
| **Vínculo Lucien → Diana** | El chat de coordinación recibe `[LINK] vip_kicked` → `LinkCoordinatorMiddleware` → dedup por `event_id` → verifica VIP activo → DM a la dueña (Expulsar / Desactivar / Mantener). Sin LLM, fuera del pipeline. |
| **Eventos temporales** | La dueña crea un evento con ventana `[start_at, end_at)` → `ephemeral_events` → `KnowledgeAugmenter` inyecta `knowledge.ephemeral` (global). Sin flag: siempre cableado. |
| **Paracaídas de zona gris** | Si el DM de consulta de doctrina falla, descongela y demota a `approve` (reason `vip_doctrine_notify_failed` / `atencion_doctrine_notify_failed`). Si el DM ok, el freeze se mantiene hasta send real (ver AGENTS §4.5 / §4.16). |
| **Saludo puro VIP** | El Analista siempre analiza; solo usa plantilla fija si `intent == saludar`, texto corto (≤4 palabras) y clasificador fático confiable. Flag ON: send directo; OFF: approve. |

**Decisor — orden de prioridades (contrato intocable):** seguridad baja → escalar; `needs_policy` sin política → `consult_doctrine`; `risk == "alto"` → escalar (`risk_high`); `emotion == "molesta"` → escalar (`frustracion_directa`); modo autónomo + umbrales → send; resto → approve. Con riesgo alto y emoción molesta aplicando a la vez, gana `risk_high`. La redraft por naturalidad es secuenciación del Director (pre-Decisor), no acción del Decisor.

## 4. Feature flags

Valores leídos de `.env` del repo (runtime). Los defaults del código en `src/diana/config/settings.py` son `false`; el `.env` los sobreescribe.

| Flag | Estado | Superficie que gobierna |
| --- | --- | --- |
| `FEATURE_MEMORY_ENABLED` | `true` | Wiring de memoria VIP (retrievers) |
| `FEATURE_GRAY_ZONE_ENABLED` | `true` | Zona gris / consulta de doctrina + freeze |
| `FEATURE_STAGING_ENABLED` | `true` | Staging Area y superficie `/staging` |
| `FEATURE_SANDBOX_ENABLED` | `true` | Sandbox (perfiles ficticios) |
| `FEATURE_SANDBOX_AUTO_SEND` | `true` | Sandbox test window: respuesta directa e instantánea en chats con sandbox activo (sin aprobación; bloqueos siguen notificando) |
| `FEATURE_ADVANCED_BEHAVIOR` | `true` | Mensajes divididos y quirks humanos |
| `FEATURE_PROMO_ENABLED` | `true` | Promo no-VIP (trigger exacto) |
| `FEATURE_RECONTACT_ENABLED` | `true` | Recontacto por silencio |
| `FEATURE_PERSONA_ADMIN_ENABLED` | `true` | Panel de personalidad y reglas (persona versionada) |
| `FEATURE_QUALITY_FEEDBACK_ENABLED` | `true` | Destacar / Reprender en borradores VIP |
| `FEATURE_GENERAL_MODE_ENABLED` | `true` | Atención general (canal no-VIP) |
| `FEATURE_PHATIC_AUTO_SEND` | `true` | Envío directo del saludo puro VIP |
| `FEATURE_CALIBRATION_ENABLED` | `false` | Calibración automática de umbrales |
| `FEATURE_AUTONOMOUS_MODE` | `false` | Autoenvío autónomo (kill-switch maestro) |
| `FEATURE_EMOTIONAL_DETECTOR_ENABLED` | `true` | Detector emocional (shadow) |
| `FEATURE_PROFILE_SYNTHESIS_ENABLED` | `true` | Resíntesis de perfil (shadow) |
| `FEATURE_PHATIC_AUTONOMY` | `true` | Autonomía fática (shadow) |
| `FEATURE_MOOD_ENGINE` | `true` | Motor de mood (shadow) |
| `FEATURE_TRUST_BUDGET` | `true` | Presupuesto de confianza (shadow) |
| `FEATURE_LINK_ENABLED` | `true` | Vínculo Lucien → Diana |
| `FEATURE_PII_MASKING_ENABLED` | `true` | Masking de PII en el borde LLM (default seguro; única excepción a la convención de flags en false) |

> **Nota — `FEATURE_AUTONOMOUS_MODE=false`:** la ruta de autoenvío SÍ está cableada tras el flag en `src/diana/application/turn_orchestrator.py` (~304 y ~2549, demote a approve) y `src/diana/application/recontact_service.py` (~209), pero deshabilitada. Los flags de evolución de agente (`*_DETECTOR`, `*_SYNTHESIS`, `*_AUTONOMY`, `*_MOOD`, `*_TRUST_BUDGET`) están `true` en **modo medición (shadow)**: miden y registran, no cambian decisiones.

> **Nota — masking de PII (2026-08-22):** en el borde de salida del LLM (`DeepSeekProvider`) se enmascaran correos, teléfonos, tarjetas (Luhn), @usuarios y enlaces con marcadores a prueba de colisiones, y se restauran en la respuesta si el modelo los repite (transparente para el VIP y para `pipeline_traces`). Nombres propios no se enmascaran (personalización). Ver `src/diana/llm/pii_masker.py` y `docs/ACUERDO-PROVEEDOR-LLM.md`.

## 5. Modelo de datos

PostgreSQL 16+ con pgvector, ORM SQLAlchemy 2.0 async + asyncpg, migrado con **Alembic (001 → 029)**. Head actual: `029_feedback_quality`. Tablas por grupo funcional:

| Grupo | Tablas | Migraciones |
| --- | --- | --- |
| **Fase 1 — núcleo supervisado** | `vips`, `message_history`, `turns`, `pipeline_traces`, `pending_deliveries`, `pending_approvals`, `escalation_events`, `system_config` | 001–002 |
| **Fase 2 — memoria y aprendizaje** | `profiles`, `memories` (pgvector), `contexts`, `policies`, `examples`, `staging_candidates`, `gray_zone_queries` | 003–004 |
| **Fase 3 — producto completo** | `learning_metrics`, `recontact_schedules`, `promo_triggers`, `promo_executions`, `owner_marks`, `runtime_timers`, `business_connections` | 005–016 |
| **Personalidad** | `persona_versions` (catálogo versionado) | 017 |
| **Atención general (F4)** | `atencion_cycles`, `daily_message_limits`, canal `channel_type=atencion` | 018–021 |
| **Memoria VIP (F5)** | `backfill_queue`, columnas de estado/source en memoria y perfil | 022–023 |
| **Evolución de agente (shadow)** | `vip_profile`, `vip_profile_history`, `vip_mood_state`, `vip_trust_budget`, `turn_category_log`, `emotional_signal_log` | 024–026 |
| **Eventos temporales** | `ephemeral_events` | 027 |
| **Vínculo Lucien → Diana (F6)** | `link_events` (dedup por `event_id`) | 028 |
| **Feedback de calidad** | columnas `examples.quality` / `examples.vip_id` / `policies.vip_id` | 029 |

Modelos ORM autoritativos en `src/diana/infrastructure/db/models.py` (tablas del núcleo); `link_events`, `runtime_timers` y `business_connections` se definen co-localizadas en sus repositorios bajo `infrastructure/db/repositories/`. Seeds no sensibles de `system_config`: `global_mode`, `forbidden_keywords`, `eval_thresholds`, flags por defecto.

## 6. Stack y operación

| Capa | Tecnología |
| --- | --- |
| Lenguaje | Python 3.12+ (paquete instalable `src/diana`) |
| Framework Telegram | aiogram 3.x (soporte nativo Business Connection), long-polling |
| Base de datos | PostgreSQL 16+ · único almacén durable |
| Vectores | pgvector con índices HNSW |
| ORM | SQLAlchemy 2.0 (async) + asyncpg |
| Migraciones | Alembic (001 → 029) |
| Validación | Pydantic v2 |
| LLM | DeepSeek (primario) con LLMProvider abstracto para hot-swap; Anthropic como respaldo configurable |
| Embeddings | sentence-transformers (multilingüe, local) |
| Timers / behavior | `asyncio.Task` + tabla `pending_deliveries` (sin Redis) |
| Testing | pytest + pytest-asyncio; dobles FakeLLM/FakeTelegramActuator; gates de pureza de capas |

**Arranque y operación:** ver `docs/README-DEV.md` (setup, configuración, flags, migraciones, run en long-polling, tests y contratos bloqueados). Supuesto operativo de proceso único: `docs/OPS_SINGLE_INSTANCE.md`. En arranque se cargan `forbidden_keywords` y umbrales calibrados, y corre la recuperación segura (expira deliveries en vuelo; nunca re-envía ni auto-aprueba en silencio).

## 7. Índice de documentación técnica

| Documento | Qué define |
| --- | --- |
| `README.md` | Qué es Diana (portada de producto) |
| `AGENTS.md` | Límites duros de módulo y flujos canónicos (contrato de implementación) |
| `docs/SPEC-1.1.md` | Diseño técnico base (principio rector, stack, ADRs, modelo de datos) |
| `docs/SPEC-FASE2.md` · `SPEC-FASE3.md` | Diseño de Fase 2 (memoria/zona gris/staging/sandbox) y Fase 3 (autonomía/recontacto/promo/calibración) |
| `docs/SPEC-FASE4.md` | Atención general (canal no-VIP) |
| `docs/SPEC-FASE5.md` | Memoria VIP / perfil de memoria (4 pools) |
| `docs/SPEC-FASE6.md` | Vínculo Lucien → Diana |
| `docs/SPEC-FEEDBACK.md` | Feedback Destacar / Reprender y bancos gold/vip |
| `docs/SPEC-EVOLUCION-AGENTE.md` | Evolución del agente (shadow mode) |
| `docs/SPEC-SYSTEM_PROMPT.md` · `ANEXO_J-SYSTEM_PROMPT.md` | Persona y system prompt |
| `docs/ESTADO-PROYECTO.md` | Estado actual del sistema y pendientes |
| `docs/INFORME_AUDITORIA.md` | Auditoría contra código (verificación de brechas) |
| `docs/README-DEV.md` | Flags, arranque técnico y operación |
| `docs/UX.md` | UX del panel de la dueña |
| `docs/ANEXO_T-TRAZABILIDAD.md` | Trazabilidad interactiva (Anexo T) |
| `docs/MVP_COMPONENT_DESIGN.md` | Guía de componentes de Fase 1 |
| `docs/REQUERIMIENTOS.md` | Qué debe cumplir el sistema (producto) |
| `docs/MINIBOT_HARNESS.md` | Harness de pruebas externo (userbot Telethon) contra el sandbox |
| `wiki/` | Conocimiento detallado: conceptos, módulos, contratos, tablas, decisiones, seguridad, operaciones (`wiki/SCHEMA.md` para el esquema) |

## 8. Decisiones de arquitectura (ADRs)

| ADR | Decisión |
| --- | --- |
| ADR-001 | Framework Telegram = aiogram 3.x (soporte Business nativo) |
| ADR-002 | Orquestación = Director custom + Capability Registry (sin frameworks de agentes externos) |
| ADR-003 | Almacenamiento = solo PostgreSQL + pgvector (simplicidad operativa) |
| ADR-004 | Behavior Engine = `asyncio.Task` + `pending_deliveries` (suficiente para el volumen) |
| ADR-005 | Embeddings locales (sentence-transformers) para Fase 2 (cero coste, intercambiable) |
| ADR-006 | LLMProvider abstracto con hot-swap (DeepSeek primario, Anthropic secundario) |

**No-metas vigentes:** sin Redis, LangChain, Celery ni Kafka; sin escalado masivo (>100 VIPs concurrentes) más allá de lo actual; multi-instancia fuera del despliegue por defecto.

---

*Análisis de arquitectura: 2026-08-21.*
