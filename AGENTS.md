
AGENTS.md — Límites de módulo y flujos vivos (v1.3)

Diana Business Bot / Sistema de Automatización de Chats VIP

Campo Valor
Nivel Operación para agentes de desarrollo (humanos o IA)
Basado en REQUERIMIENTOS.md v2.1 + SPEC-1.1.md v1.5 + SPEC-FASE2.md v2.1 + SPEC-FASE3.md v3.0 + SPEC-FASE6 + SPEC-FEEDBACK
Audiencia Chat con el usuario: dueño/a de producto. Cuerpo técnico de este doc: agentes de código y revisores.
Versión 1.3 — Fase 3 (Producto Completo) + regla de comunicación con producto
Idioma Español

---

0. Comunicación con el usuario (obligatorio)

El interlocutor del chat **no es un desarrollador**: es el **dueño o dueña de producto** (quien opera el negocio, el bot y las decisiones de control). Toda la comunicación **agente ↔ usuario** (explicaciones, avances, dudas, opciones, resúmenes, errores, riesgos y pedidos de confirmación) debe usarse con **nivel técnico medio-bajo**, lenguaje **claro y práctico**.

0.1 Principio

Hablar de **qué pasa en el producto**, **qué gana o pierde el negocio**, **qué control tiene la dueña**, y **qué hay que decidir**. No hablar como a un equipo de ingeniería.

0.2 Cómo debe sonar el chat

· Frases cortas, concretas, orientadas a la decisión o al resultado.
· Explicar con el mundo real del producto: VIP, Telegram, aprobación, corrección, sandbox, modo autónomo, recontacto, promo, “el bot manda solo o espera OK”.
· Si aparece un concepto técnico inevitable, **traducirlo en una frase** al impacto de producto (ej. no “middleware fail-closed”: “si no podemos confirmar el estado, por seguridad no mandamos el mensaje”).
· Las preguntas al usuario se formulan en lenguaje de negocio/producto, no de implementación.
· Resumir avances como “qué cambió para ti / para el VIP / para el control”, no como lista de módulos.
· Ante un error o bloqueo: qué falló en la práctica, qué se puede hacer ahora, y si hace falta una decisión de la dueña.

0.3 Qué evitar en el chat (salvo que el usuario lo pida)

· Jerga de implementación sin traducción: pipeline, middleware, DI, purity, locks, migraciones, firmas de funciones, paths de archivos como eje del mensaje.
· Menús largos de opciones técnicas o “enfoques de arquitectura” cuando basta una recomendación práctica.
· Asumir que el usuario lee código, specs o PRs.
· Respuestas que suenen a code review o a clase de ingeniería.

0.4 Qué NO cambia esta regla

· El **código**, tests, commits, nombres de archivos, comentarios de código y docs técnicos de diseño **siguen siendo técnicos** y en el idioma/convención del artefacto (por defecto inglés en código; este AGENTS.md y specs de producto en español según corresponda).
· Los **límites de módulo y flujos canónicos** de las secciones siguientes siguen siendo de cumplimiento estricto para quien implementa.
· Si el usuario **pide explícitamente** detalle técnico, se puede subir el nivel solo en esa respuesta o tramo.

0.5 Autocomprobación antes de enviar un mensaje al usuario

1. ¿Lo entendería alguien que maneja el producto pero no programa?
2. ¿Queda claro el impacto en VIP / dueña / control / riesgo?
3. ¿La pregunta (si hay) se puede responder sin saber de código?
4. Si usé un término técnico, ¿lo traduje al efecto práctico?

Si alguna respuesta es “no”, reescribir el mensaje antes de enviarlo.

0.6 Idioma del producto: español neutro (obligatorio, sin excepciones)

Todo texto de producto — UI del bot, prompts, seeds de persona, plantillas,
mensajes al VIP, textos de la dueña, specs y este documento — se escribe en
**español neutro** (variante mexicana/neutra). El **español rioplatense
(voseo) está prohibido**: querés, tenés, hacés, decime, sos, vos, contame,
andás, podés, escribime, y los imperativos voseantes (Revisá, Elegí, Tocá,
Esperá, Enviá, Mandá, Comprá, Buscá, Cargá, Hablá, Poné, Dejá, Sacá, Mirá,
Fijate, Acordate, Quedate, Pará, Seguí, Probá, Usá, Creá, Editá, Borrá,
Guardá, Volvé, Pedí, Sentí, Sabé, Chequeá, Vení, Entrá, Agregá, Anotá).

Regla de acción inmediata para cualquier agente (humano o IA):

1. Al encontrar **cualquier** texto, referencia, código hardcodeado o
   instrucción que use español rioplatense — en código, docs, prompts,
   seeds, DB o ejemplos — **corregirlo en ese mismo instante** a español
   neutro, sin esperar una tarea aparte ni una orden explícita.
2. Si la referencia es una **regla o instrucción que prescribe usar
   voseo/rioplatense** (ej. “respondé de forma cercana” con verbos
   voseantes), **borrar esa regla** y reemplazarla por la forma neutra.
3. Verificar también la **base de datos** cuando aplique (ej.
   `persona_versions.payload` puede conservar seeds viejos con voseo);
   actualizar las filas afectadas.
4. Los textos de producto nuevos que escriba el agente deben nacer ya en
   español neutro; no es válido dejarlos en voseo “porque es lo que se
   entiende” ni postergar la corrección.

---

1. Propósito de este documento

Este archivo define límites duros de módulo y flujos canónicos que ningún agente (humano o IA) puede violar al modificar el código. También fija cómo debe hablar el agente con el dueño de producto (sección 0).

Su objetivo es proteger las propiedades arquitectónicas críticas del sistema, respetando el carácter incremental por fases (Fase 1, 2 y 3), y que las conversaciones de trabajo sean útiles para quien decide el producto.

Principios rectores (no negociables):

1. El Director es 100 % determinista y nunca pregunta a un LLM “qué hacer”.
2. Cada componente cognitivo responde una sola pregunta.
3. El Behavior Engine está fuera de la cognición.
4. El aprendizaje es siempre post-turno y controlado (Staging Area).
5. Existe anti-contaminación total entre la Memoria de un VIP y el banco de ejemplos.
6. Toda decisión es reconstruible a partir de objetos persistidos.
7. El Turn Coordinator garantiza la serialización por chat (REQ-NFR-02).

Regla de oro: Todos los nuevos comportamientos de Fase 3+ están envueltos en feature flags (FEATURE_AUTONOMOUS_MODE, FEATURE_RECONTACT_ENABLED, FEATURE_PROMO_ENABLED, FEATURE_CALIBRATION_ENABLED, FEATURE_ADVANCED_BEHAVIOR, FEATURE_GENERAL_MODE_ENABLED, FEATURE_LINK_ENABLED, FEATURE_QUALITY_FEEDBACK_ENABLED, FEATURE_SANDBOX_AUTO_SEND, FEATURE_GRAY_ZONE_PROPOSAL_ENABLED, FEATURE_AUTONOMY_READINESS_ENABLED con sus derivados FEATURE_AUTONOMY_COINCIDENCE_ENABLED, FEATURE_AUTONOMY_QUALITY_ENABLED, FEATURE_AUTONOMY_RECOMMENDATION_ENABLED, y los flags de evolución de agente). Si un flag está desactivado, el sistema se comporta como en la fase anterior. Excepción documentada: los eventos temporales no tienen flag (siempre cableados).

---

2. Mapa de módulos y límites duros (Actualizado con Fase 3)

2.1 Capas y responsabilidad exclusiva

Capa / Módulo Pregunta que responde Puede hacer Nunca puede hacer
Telegram Layer (telegram/) ¿Cómo entro y salgo de Telegram? Recibir updates, enviar mensajes, middlewares de short-circuit Decidir qué decir, invocar LLM, escribir en tablas de conocimiento
Turn Coordinator (application/turn_coordinator.py) ¿Qué turno está vivo? Serializar por chat_id, gestionar la máquina de estados del Turn, cancelar entregas obsoletas Decidir qué decir, invocar LLM, tocar memoria persistente
Application Services (application/) ¿Qué caso de uso es este? Orquestar Orquestador, Admin, Sandbox, Recontact, Promo, Calibration Contener lógica cognitiva, generar texto, evaluar
Cognitive Core (cognitive/) ¿Qué decisión tomar? Ejecutar el pipeline Director → … → Decisor Conocer aiogram, enviar mensajes, escribir en Staging, decidir delays
Capability Registry + Retrievers (cognitive/retrievers/) ¿Qué sabemos sobre X? Devolver conocimiento estructurado filtrado Mezclar tipos de conocimiento, devolver Memoria de otro VIP, decidir si se usa o no
Behavior Engine (behavior/) ¿Cómo se actúa el mensaje? Delay, read, typing, send, cancel, FakeDelivery, split messages, human quirks Generar texto, decidir acción, invocar Analista/Generador
Learning (learning/) ¿Qué aprendimos de este turno? Extraer candidatos, escribir en Staging, destilar políticas, actualizar métricas, calibrar umbrales Ejecutarse durante el pipeline de decisión, promover automáticamente a banco vivo
LLM Provider (llm/) ¿Cómo hablo con el modelo? generate y generate_structured Contener prompts de negocio, decidir umbrales, conocer VIP
Infrastructure / Persistence ¿Cómo guardo y recupero datos? Repositorios, sesiones, migraciones Contener lógica de negocio o cognitiva
Jobs (jobs/) ¿Qué tareas periódicas ejecutar? Recontacto, purga de trazas, calibración, métricas Interferir con el pipeline de turnos en curso

2.2 Reglas de dependencia (dirección permitida)

```
Telegram Layer → Turn Coordinator → Application Services → Cognitive Core
                                                        ↘ Behavior Engine
Application Services → Learning (solo post-turno)
Application Services → Jobs (programación)
Cognitive Core       → Capability Registry → Retrievers → Persistence
Cognitive Core       → LLM Provider
Behavior Engine      → Telegram Layer (solo para I/O)
Learning             → Persistence
Jobs                 → Application Services (Recontact, Calibration, Promo)
```

Prohibido:

· Cognitive Core importar cualquier cosa de telegram/ o behavior/
· Behavior Engine importar Analista, Generador, Evaluador o Decisor
· Learning ser llamado desde dentro del Director o del pipeline de decisión
· Cualquier Retriever importar otro Retriever de tipo distinto
· By-passear el Turn Coordinator
· Jobs ejecutar lógica cognitiva o de decisión directamente (debe delegar en Application Services)

---

3. Flujos canónicos (clasificados por Fase)

🔵 [FASE 1 — MVP Supervisado] Flujos ACTIVOS

· 4.1 Turno VIP normal (pipeline completo → approve/escalate)
· 4.2 Short-circuit de escalación determinística
· 4.3 Cancelación por mensaje nuevo

🟢 [FASE 2 — MVP+] Flujos ACTIVOS (con flags)

· 4.4 Turno VIP con recuperación de memoria (FEATURE_MEMORY_ENABLED)
· 4.5 Zona Gris (FEATURE_GRAY_ZONE_ENABLED) — ver flujo canónico abajo
· 4.6 Corrección → Staging (FEATURE_STAGING_ENABLED)
· 4.7 Sandbox (FEATURE_SANDBOX_ENABLED)
· 4.20 Sandbox test window — envío directo e instantáneo (FEATURE_SANDBOX_AUTO_SEND)

4.5 Zona Gris — regla viva → regen del mismo turno → aprobación (FEATURE_GRAY_ZONE_ENABLED)

```
Decisor emite action = "consult_doctrine"
  → GrayZoneService.create_query()
      → gray_zone_queries status = 'open'
      → VIP/Atención congelado (VIP: frozen_until; Atención: query open|awaiting_send)
      → [Opcional FEATURE_GRAY_ZONE_PROPOSAL_ENABLED] GrayZoneProposalService genera
        una PROPUESTA (regla propuesta + respuesta sugerida + alcance sugerido) usando
        contexto general restringido (policies scope=all + examples gold + catálogo de
        persona) como PRÉSTAMO TEMPORAL: solo lectura, nada se persiste en
        memorias/ejemplos/perfil ni en el contexto base del pipeline. Fail-open: si la
        generación falla o excede timeout (5–10s), se sigue con el DM sin propuesta.
      → DM a la dueña: mensaje ORIGINAL del turno (texto del VIP/Atención + borrador
        sugerido) claramente identificado como CONTEXTO; después, si hay propuesta,
        bloque "Propuesta del sistema" (regla propuesta + respuesta sugerida, rotulado
        como sugerencia, no instrucción)
      → Teclado (con propuesta): 💡 Usar regla propuesta | 📝 Escribir regla | ⚠️ Escalar
      → Teclado (sin propuesta / flag OFF): 📝 Escribir regla | ⚠️ Escalar
        (NO hay "✅ Usar borrador")
  → Dueña elige:
      a) 💡 Usar regla propuesta → la regla propuesta entra como rule_text del MISMO
         camino regla→regen→aprobación (nunca directo; el botón adopta la REGLA, no el
         mensaje) + alcance Solo este VIP / A todos
      b) 📝 Escribir regla → sesión de texto libre (flujo actual)
      c) ⚠️ Escalar → cierra sin regla
  → AdminService.resolve_doctrine_rule_and_enqueue(...):
      1. Persistencia VIVA en policies (is_active=true; scope vip|all + vip_id)
         — SIN staging_candidates en este happy path
      2. Regen del MISMO turno vía Director.handle_turn(..., knowledge_overrides)
         — force-inject de la regla en knowledge.policy (no depender solo del PolicyRetriever)
         — Decisor sigue decidiendo la acción tras el inject
      3. Si regen ok (borrador no vacío, acción ≠ consult_doctrine):
         → create_supervised_delivery_from_gray_zone(draft_override=borrador_regenerado)
         → GRAY_ZONE → PENDING_APPROVAL
         → query status = 'awaiting_send'  (NO descongela)
         Nota: acción = escalate por riesgo/frustración del mensaje ORIGINAL
         (risk_high / frustracion_directa) CON borrador válido NO es fallo:
         la regla se aplicó y el borrador regenerado va a la cola de la dueña
         (ella aprueba/corrige/escala). Solo escalate por SAFETY del borrador
         regenerado (safety_below_threshold) es fail-closed.
      4. Si regen falla / vuelve consult_doctrine / borrador vacío / escalate
         por safety del borrador regenerado:
         → desactivar la policy recién insertada; query sigue 'open'; freeze retenido;
           avisar a la dueña → el caso VUELVE a resolución de zona gris (query 'open' +
           freeze + DM de doctrina vigente: la dueña puede reintentar con otra regla,
           con la propuesta, o escalar). NUNCA se auto-aplica una regla que el regen
           no pudo aplicar, ni se descongela, ni se envía el borrador fallido.
      5. Si falla crear aprobación / ChatLockTimeout:
         → reopen a 'open' si hace falta; freeze retenido; policy puede quedar viva; error reintentable
  → Cola normal de la dueña: Aprobar / Corregir / Escalar sobre el BORRADOR regenerado
  → Si Aprobar + BehaviorEngine.deliver() exitoso:
      → close_awaiting_send(unfreeze=True) → query 'resolved' + descongelar
  → Si Escalar/descartar desde doctrina o desde la cola de aprobación:
      → liberar freeze + cerrar query; la policy viva SE CONSERVA (salvo fallo de regen que ya la desactivó)
  → SI la dueña no responde en GRAY_ZONE_TIMEOUT_HOURS (default 24h):
      → expire solo queries status='open' (NO expire awaiting_send)
      → usa query.draft original → supervisión o escalate (legado; no es el narrative regla→regen)
```

Invariantes: la dueña escribe norma de negocio, no el mensaje al VIP; la propuesta del sistema es **solo sugerencia** (nunca se aplica sola, nunca salta la regeneración ni la cola de aprobación); el contexto general de la propuesta es un préstamo temporal sin escrituras ni contaminación (memorias/ejemplos/perfil/pipeline base intactos); si el regen no logra aplicar la regla, el caso permanece en resolución de zona gris (fail-closed, reintentable); Learning no participa en el resolve; Cognitive no importa telegram/behavior; Staging sigue siendo el camino de correcciones (FEATURE_STAGING_ENABLED), no del resolve de zona gris; la propuesta no toca umbrales ni gates (incidente de calibración).

🟠 [FASE 3 — Producto Completo] Flujos ACTIVOS (con flags)

4.8 Turno VIP en modo autónomo (FEATURE_AUTONOMOUS_MODE)

```
business_message
  → TurnCoordinator (igual)
  → Director (pipeline completo)
  → Decisor (orden actualizado: seguridad → zona gris → risk alto → ...):
      - Si safety baja → escalate
      - Si needs_policy + sin política → consult_doctrine
      - Si risk=alto → escalate
      - Si modo autónomo activo Y umbrales superados → send
      - Si modo autónomo activo pero umbrales no superados → approve (fallback)
      - Si no → approve
  → Si action = "send":
      → BehaviorEngine.deliver() directamente
      → Notificación a la dueña (si alguna dimensión está cerca del umbral)
      → Learning post-turno (registra traza, Staging si corrección posterior)
  → Si action = "approve":
      → Flujo supervisado normal
  → Si action = "consult_doctrine" o "escalate":
      → Flujos de Fase 2
```

4.9 Recontacto por silencio (FEATURE_RECONTACT_ENABLED)

```
Job programado (ej. cada hora):
  → RecontactService.get_due_vips()  # VIPs inactivos > N días
  → Para cada VIP:
      → RecontactService.execute_recontact(vip_id)
          → Director (pipeline reducido):
              - NO pasa por Analista ni Planificador
              - Recupera memory y policy (si las hay)
              - Genera mensaje con plantilla base + personalización
              - Evaluador (umbrales más laxos)
              - Decisor (solo send o approve, nunca consult_doctrine/escalate)
          → Si send → BehaviorEngine.deliver()
          → Si approve → cola de aprobación de la dueña
      → Programar próximo recontacto
```

Invariante: No se programa recontacto si el VIP está congelado, en pausa o con aprobación pendiente.

4.10 Promo no-VIP (FEATURE_PROMO_ENABLED)

```
business_message de no-VIP (no está en allowlist)
  → Middleware de auth detecta no-VIP
  → PromoService.match_trigger(texto)
  → Si match:
      → PromoService.execute_promo(chat_id, trigger)
          → BehaviorEngine.deliver_with_sequence(sequence, ctx)
          → NO se guarda en pipeline_traces
  → Si no match:
      → Ignorar (no se responde)
```

Reglas: No usa LLM. La secuencia se envía con delays y typing entre mensajes.

4.11 Calibración automática de umbrales (FEATURE_CALIBRATION_ENABLED)

```
Job programado (ej. cada domingo a las 3 AM):
  → CalibrationService.calibrate_thresholds(window_days=30)
      → Recupera turnos del período con evaluación y corrección (o no)
      → Para cada dimensión, calcula percentil donde la tasa de corrección es baja
      → Actualiza system_config con nuevos umbrales
  → CalibrationService.detect_drift()
      → Compara estilo actual con histórico
      → Si drift > umbral, notifica a la dueña
  → Registra en learning_metrics
  → Notifica a la dueña con resumen
```

4.12 Mensajes divididos y quirks humanos (FEATURE_ADVANCED_BEHAVIOR)

```
BehaviorEngine.deliver() verifica ctx.allow_split
  → Si True:
      → Divide por párrafos (líneas en blanco; o saltos simples si cada bloque es un párrafo)
      → Si un segmento sigue > split_chars: divide por puntos, comas o saltos
      → Envía cada segmento con delays intermedios y typing
  → Si allow_human_quirks=True:
      → Con probabilidad ~20%, priorizando typo+corrección (~1 de cada 8 envíos):
          - Enviar corrección tipográfica (*palabra)
          - Añadir pausa extra
          - Dividir mensaje de forma "natural" (raro; el split por párrafos ya cubre lo visible)
```

4.13 Feedback de calidad — Destacar / Reprender (FEATURE_QUALITY_FEEDBACK_ENABLED)

```
Borrador VIP (nunca Atención) + flag ON
  → Fila Destacar / Reprender en el teclado de la dueña
  → Destacar: confirma alcance (este VIP / global) → inserta example quality=gold (sin staging)
  → Reprender: entrega el texto de corrección YA; el combo posterior solo promociona el contraejemplo
  → Combo se cancela si llega un mensaje nuevo del mismo chat
  → Flag OFF: teclado clásico Aprobar/Corregir/Escalar (el retrieval gold-first sigue activo)
```

Invariante: Atención no puede destacar ni reprender (REQ-ATN-13). El retrieval gold-first + visibilidad vip_id no depende del flag.

4.14 Vínculo Lucien → Diana (FEATURE_LINK_ENABLED)

```
Chat de coordinación recibe una línea [LINK] vip_kicked
  → LinkCoordinatorMiddleware (antes de OwnerDetection) consume el payload
  → Dedup por event_id → ¿es VIP activo? → DM a la dueña: Expulsar / Desactivar / Mantener
  → Flag OFF: middleware inerte; no hay router de callbacks; comportamiento idéntico al anterior
```

Nunca usa LLM. No entra al pipeline cognitivo. Ver docs/SPEC-FASE6.md (migración real: 028, no 027).

4.15 Eventos temporales (sin flag)

```
Dueña crea/edita/pausa un evento con ventana [start_at, end_at)
  → Se guarda en ephemeral_events (migración 027)
  → KnowledgeAugmenter inyecta knowledge.ephemeral al contexto (global, no por VIP)
  → No contamina memoria VIP ni el banco de ejemplos
```

4.16 Paracaídas de zona gris (VIP y Atención)

```
consult_doctrine → freeze → [propuesta opcional] → send_doctrine_query a la dueña
  → Si la generación de propuesta falla (excepción/timeout): fail-open, se sigue
    con el DM sin propuesta (nunca se pierde la consulta ni el freeze).
  → Si el DM falla: discard_and_close (descongela) + demote a approve
    reason=vip_doctrine_notify_failed | atencion_doctrine_notify_failed
  → Si el DM ok: el VIP/chat permanece congelado a través de
    resolve (regla viva + regen) → cola de aprobación → hasta un
    envío real exitoso (o escalate/discard que libere el hold).
    Query status open | awaiting_send cuenta como freeze (Atención
    incluido). No descongelar en confirm/resolve previo al send.
```

4.17 Saludo puro VIP (FEATURE_PHATIC_AUTO_SEND)

```
business_message VIP
  → Analyst (siempre; el saludo ya no se corta antes de entender)
  → Corte a plantilla SOLO si las tres se cumplen:
      1. intent == saludar
      2. el texto es un saludo corto (hola/holis/buenas/qué tal, máximo 4 palabras)
      3. clasificador fático confiable
  → Si sí: plantilla fija "Holis 😁"
      → flag ON: send directo al VIP (sin cola de la dueña)
      → flag OFF: approve (cola de la dueña)
  → Si no (pedido, pregunta, "dale", "ok", hola+contenido): pipeline completo
```

Invariante: que el Analista marque `saludar` NO basta. Sin keyword de saludo o con más de 4 palabras, nunca se usa la plantilla.

4.18 Círculo de aprendizaje de la Fila 4 (FEATURE_AUTONOMY_QUALITY_ENABLED)

```
Turno real terminado (VIP)
  → POST-TURNO (nunca en el pipeline):
      → OutcomeLogService re-decide el turno guardado con el Decisor sombra
        (autonomía ON) → shadow_verdict (send/blocked/escalate/doctrine)
      → Heurística H1 puntúa el borrador → draft_score (sin LLM)
      → Escribe turn_outcome_log (migración 030; idempotente por turn_id)
  → Dueña resuelve (aprobar / corregir / escalar):
      → AdminService actualiza owner_outcome + sent_score + quality_delta
      → TrustBudgetService.record_outcome (evento label: acierto +0.05 /
        desacuerdo −0.20 / conservadora 0) — ÚNICA fuente de trust con Fila 4 ON
  → Reacción del VIP (C3, ventana configurable):
      → Hook inmediato al llegar el siguiente mensaje (emotion + léxico H2)
      → Job de respaldo marca silence / clasifica por texto (jobs/outcome_reaction.py)
      → record_outcome (evento signal: positive +0.05 / negative −0.20)
```

Invariantes: la evaluación es 100 % heurística (C1 compara, C2 puntúa, C3 lee reacción — sin LLM); todos los escritos son post-turno; `turn_outcome_log` es métrica pura (anti-contaminación: nunca alimenta `memories`/`examples`/`vip_profile`); con `FEATURE_AUTONOMY_READINESS_ENABLED` ON el trust budget es guiado por resultados (el incremento sombra `record_autonomous` y `record_correction` quedan desactivados para evitar doble conteo).

4.19 Panel "🧭 Camino a la autonomía" + activación por VIP (FEATURE_AUTONOMY_RECOMMENDATION_ENABLED)

```
Dueña abre el panel (sección del menú, junto al modo sombra)
  → AutonomyReadinessService renderiza:
      - Preparación global (coincidencia vs 95 %, cuellos por dimensión,
        escalaciones por seguridad)
      - Comparativas (aciertos/desacuerdos/conservadora + lista de desacuerdos)
      - Por VIP (✅ listo / ⏳ falta cuánto) con evolución de confianza
  → Botón "Activar" por VIP SOLO si se cumplen las 3 condiciones:
      confianza ≥ 0.90 · coincidencia global ≥ 95 % (2 semanas)
      · cero escalaciones por seguridad en la ventana
  → Activar escribe vips.auto_send (L2 de la doble puerta) — la recomendación
    NUNCA envía por su cuenta; el kill-switch maestro FEATURE_AUTONOMOUS_MODE
    sigue gobernando el envío real
```

Invariante: la activación es un botón por VIP; nunca automática. El Decisor y el Director no se tocan (la capa solo mide y recomienda).

4.20 Sandbox test window — envío directo e instantáneo (FEATURE_SANDBOX_AUTO_SEND)

```
business_message en un chat con sandbox activo + flag ON
  → Pipeline completo normal (perfil ficticio)
  → Decisor → action approve/send:
      → TurnOrchestrator (capa de aplicación, NO el Decisor) convierte en
        envío directo: _prepare_sandbox_send → BehaviorEngine.deliver()
        con ctx.instant=True (sin espera previa, sin read/typing/gaps)
      → No pasa por la cola de aprobación de la dueña
  → Escalación / consulta de doctrina: flujos de notificación configurados
    intactos (la dueña sigue recibiendo sus avisos)
  → Aislamiento sandbox intacto: should_persist=false (sin memoria, sin
    ejemplos, sin historial durable)
```

Invariantes: el flag apagado = comportamiento anterior byte a byte (el sandbox
sigue pidiendo aprobación). La regla es por chat con sandbox activo — los VIP
reales nunca se ven afectados, sin importar el valor del flag. El envío directo
del sandbox no depende de FEATURE_AUTONOMOUS_MODE ni de auto_send por VIP
(es una superficie de prueba explícita de la dueña). El motor no conoce
"sandbox": solo actúa con ctx.instant cuando la capa de aplicación lo pide.

**Criterio de persistencia en sandbox (decisión de la dueña, 2026-08-25):**
la **memoria del usuario es efímera** en sandbox (`should_persist=false` →
sin memorias, ejemplos, gold, lecciones de Reprender, mood, trust, historial
durable), pero las **decisiones de doctrina persisten** en la DB real: la
consulta de zona gris (`gray_zone_queries`), la regla viva
(`persist_live_policy` → `policies`) y lo que se decida sobre borradores
regenerados (incluso en sandbox), porque de ellas se derivan doctrinas
aplicables/faltantes en situaciones reales. El Reprender en sandbox entrega el
texto corregido pero NO guarda la lección (aislamiento); el mensaje a la dueña
lo aclara (`reprimand_lesson_not_saved_sandbox`).

4.21 Escalaciones — manejo desde el DM de la dueña (sin flag)

```
Escalación (Decisor o short-circuit determinístico) → DM a la dueña con botones:
  🔍 Ver traza        → render del resumen de traza del turno (AdminTraceService)
  ➖ Falso positivo   → AdminService.mark_false_positive (owner_marks; métricas)
  ✍️ Responder al VIP → sesión de texto libre → AdminService.handle_escalation_reply
                        → BehaviorEngine.deliver() al chat escalado
```

Reglas: la respuesta de la dueña es una acción manual (no pasa por el Decisor,
igual que Corregir — el Decisor gobierna solo los envíos automáticos). El
`business_connection_id` del chat escalado se persiste en
`escalation_events.business_connection_id` al notificar (migración 032) porque
el turno no lo guarda; sin ese dato el reply falla cerrado (nunca envía a ciegas).
La marca de falso positivo es un flag de métrica (owner_marks), NO un ejemplo:
no entra a memories/examples/policies ni enseña nada al sistema. En sandbox,
`mark_false_positive` NO persiste (aislamiento igual que el aprendizaje).

---

4. Contratos críticos que ningún agente puede romper

4.1 Decisor (orden de prioridades actualizado)

El Decisor debe evaluar las condiciones en este orden exacto:

Prioridad Condición Acción
1 perfil.seguridad < umbral_seguridad Escalar
2 comprension.needs_policy == true Y policy_retrieval_result == vacío Y FEATURE_GRAY_ZONE_ENABLED Consultar doctrina
3 comprension.risk == "alto" Escalar (risk_high)
4 comprension.emotion == "molesta" Escalar (frustracion_directa)
5 (pre-Decisor) perfil.naturalidad < umbral_naturalidad → Director re-genera 1× + re-evalúa (MVP; sin Decision.action=regenerate). El Decisor no emite regenerate. Multi-retry / action regenerate = residual.
6 Modo autónomo activo Y umbrales superados Enviar
7 Ninguna de las anteriores Aprobar

Notas sobre prioridad 5: la redraft de naturalidad es **secuenciación del Director** (pre-Decisor), no una acción del Decisor. El orden de **acciones** del Decisor sigue siendo seguridad → zona gris → escalate (risk o frustración) → send autónomo → approve; el paso 5 del Decisor es no-op (redraft ya ocurrió upstream si correspondía).

Nota de alineación (2026-08-21): la tabla coincide con `src/diana/cognitive/decider.py` — el código evalúa `risk=alto` (prioridad 3) antes que `emotion=molesta` (prioridad 4). Si ambas aplican, la acción sigue siendo Escalar y el `reason` queda `risk_high` (la severidad semántica gana sobre la señal de frustración; visible en `/traza`). `molesta` sola escala sin esperar acumulación de risk.

Justificación de la prioridad 2 sobre la 3 (BR-02 modificado): La zona gris se evalúa antes que risk=alto porque la falta de doctrina es una causa tratable que, una vez resuelta, elimina la necesidad de escalación futura. La escalación por risk=alto solo se ejecuta cuando no hay doctrina pendiente.

Justificación de la prioridad 4 (frustracion_directa): emotion molesta escala sin esperar acumulación de risk; se evalúa después de zona gris (doctrina tratable gana) y de risk=alto (si ambas aplican, gana risk_high) y antes de send autónomo.

4.2 BehaviorEngine (extensión Fase 3)

```python
async def deliver_with_sequence(texts: list[str], ctx: DeliveryContext) -> DeliveryResult
```

· Solo actúa. Nunca genera texto ni decide la acción.
· Debe respetar ctx.is_frozen.
· Si ctx.allow_split=True, debe dividir mensajes largos.
· Si ctx.allow_human_quirks=True, puede simular errores leves.

4.3 RecontactService

```python
async def execute_recontact(vip_id: UUID) -> None
```

· Nunca ejecuta el Analista ni el Planificador (es pipeline reducido).
· Solo recupera memory y policy.
· Usa plantillas fijas (no genera desde cero con LLM).
· No debe enviar mensajes si el VIP está congelado o en pausa.

4.4 PromoService

```python
async def match_trigger(text: str) -> Optional[PromoTrigger]
async def execute_promo(chat_id: int, trigger: PromoTrigger) -> None
```

· Nunca usa LLM.
· Solo dispara por texto exacto (no semántico).
· La secuencia se define en system_config o tabla promo_triggers.

4.5 CalibrationService

```python
async def calibrate_thresholds(window_days: int = 30) -> None
async def detect_drift() -> Dict[str, float]
```

· Solo usa datos de pipeline_traces y staging_candidates (turnos con corrección).
· No modifica el comportamiento del Decisor en tiempo real; solo actualiza system_config.
· Debe ejecutarse como job programado, nunca dentro del pipeline.

---

5. Reglas operativas para agentes de código (Fase 3)

5.1 Al modificar modo autónomo

1. El Decisor ya tiene la regla de send al final. Asegurarse de que el orden de prioridades se mantiene.
2. AutonomousModeService debe verificar FEATURE_AUTONOMOUS_MODE y auto_send por VIP.
3. Las notificaciones a la dueña deben ser opcionales y configurables por umbral.

5.2 Al modificar recontacto

1. El pipeline reducido no debe pasar por Analista ni Planificador.
2. Las plantillas deben ser fijas, pero pueden incluir placeholders ({nombre}, {producto}).
3. El job debe respetar los periodos de silencio configurados y evitar spam.

5.3 Al modificar promo no-VIP

1. La coincidencia debe ser exacta (case-insensitive, pero sin fuzzy matching).
2. La secuencia se envía con delays entre mensajes (BehaviorEngine ya lo soporta).
3. No se debe guardar en pipeline_traces.

5.4 Al modificar calibración

1. Usar un window_days configurable (default 30).
2. Calcular umbrales por separado para cada dimensión.
3. Aplicar suavizado (promedio con umbral anterior) para evitar oscilaciones.
4. Registrar el cambio en system_config con historial (opcional).

5.5 Al modificar Behavior avanzado

1. allow_split y allow_human_quirks son flags del DeliveryContext, no configuraciones globales.
2. Los quirks humanos deben ser probabilísticos y no afectar el contenido del mensaje.
3. La división de mensajes debe preservar el sentido (no cortar en medio de una palabra).

5.6 Feature flags

Todos los nuevos comportamientos deben estar envueltos en if settings.FEATURE_XXX_ENABLED:.

---

6. Checklist de revisión (para PRs y agentes)

Antes de aceptar un cambio en Fase 3, verificar:

· ¿El Director sigue siendo 100 % determinista?
· ¿Cada componente cognitivo responde una sola pregunta?
· ¿El mensaje pasó por el Turn Coordinator antes de llegar al Director?
· ¿El Behavior Engine sigue fuera de la cognición?
· ¿El aprendizaje ocurre solo post-turno?
· ¿El Decisor respeta el orden de prioridades (seguridad → zona gris → risk alto → ...)?
· ¿La zona gris resuelve con regla viva + regen del mismo turno (sin staging en el happy path)?
· ¿El VIP/Atención permanece congelado hasta un envío real exitoso (o escalate/discard), no al resolver la consulta?
· ¿Los nuevos flujos (autónomo, recontacto, promo, calibración, behavior avanzado) están envueltos en feature flags?
· ¿Recontacto y promo usan BehaviorEngine, no generan texto con LLM?
· ¿La calibración solo se ejecuta en jobs programados, nunca en el pipeline?
· ¿Se mantiene la anti-contaminación Memoria ↔ Ejemplos?
· ¿Todos los objetos intermedios se siguen persistiendo?
· ¿Los modos (supervisado/autónomo) siguen siendo filtros externos?

Si alguna respuesta es “no”, el cambio no se mergea.

---

7. Qué está explícitamente prohibido (adiciones Fase 3)

Prohibición Razón
Llamar a un LLM desde RecontactService o PromoService Son flujos sin LLM por diseño
Ejecutar calibración dentro del pipeline de decisión Debe ser post-hoc, no en tiempo real
Enviar mensajes autónomos sin pasar por el Decisor El Decisor es el único que decide acción
Ignorar feature flags en nuevos comportamientos Permite rollback sin redeploy
Usar el mismo umbral para seguridad en modo autónomo y supervisado Deben ser diferentes y calibrados por separado
Programar recontacto sin verificar congelación/pausa Podría molestar al VIP en momentos inapropiados

---

8. Cómo evolucionar este documento

· Cualquier cambio de límite de módulo o de flujo canónico debe actualizar primero este AGENTS.md y después el código.
· Cuando se añada un nuevo flujo, se documenta aquí con la etiqueta [FASE 3] (o la fase que corresponda).
· Los cambios solo de implementación interna de un módulo (sin romper contratos) no requieren modificar este archivo.

---

9. Relación con los otros documentos

Documento Qué define
REQUERIMIENTOS.md Qué debe cumplir el sistema (producto)
SPEC-1.1.md v1.5 Diseño de Fase 1 (MVP supervisado)
SPEC-FASE2.md Diseño de Fase 2 (MVP+)
SPEC-FASE3.md Diseño de Fase 3 (Producto Completo)
SPEC-FASE4.md Atención general (canal no-VIP)
SPEC-FASE5.md Perfil de memoria por VIP
SPEC-FASE6.md Vínculo Lucien→Diana (migración real 028)
SPEC-FEEDBACK.md Destacar/Reprender y bancos gold/vip (migración real 029)
SPEC-AUTONOMIA-CALIBRACION.md Fila 4 — Camino a la autonomía (círculo de aprendizaje, migraciones 030–031)
ARCHITECTURE.md Arquitectura consolidada del sistema actual (entrada técnica única; mapa de módulos y flujos en §2–§3)
contratos_restantes.md · contrato_analista.md Contratos detallados de los nodos (Anexos A y C+)
ANEXO_T-TRAZABILIDAD.md Sistema de trazabilidad interactiva (Anexo T)
AGENTS.md (este) Límites que ningún agente puede cruzar al tocar el código, clasificados por fase; más regla de comunicación con dueño de producto (sección 0)

---

Fin de AGENTS.md v1.5 (Fase 3 + flujos 4.13–4.19; Fila 4 — Camino a la autonomía, migraciones 030–031)
Última actualización: Agosto 2026
Equipo de Arquitectura — Producto completo implementado (sistema actual).
