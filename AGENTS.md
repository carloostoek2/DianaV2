

AGENTS.md — Límites de módulo y flujos vivos (v1.3)

Diana Business Bot / Sistema de Automatización de Chats VIP

Campo Valor
Nivel Operación para agentes de desarrollo (humanos o IA)
Basado en REQUERIMIENTOS.md v2.1 + SPEC.md v1.5 + SPEC-FASE2.md v2.1 + SPEC-FASE3.md v3.0
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

Regla de oro: Todos los nuevos comportamientos de Fase 3 están envueltos en feature flags (FEATURE_AUTONOMOUS_MODE, FEATURE_RECONTACT_ENABLED, FEATURE_PROMO_ENABLED, FEATURE_CALIBRATION_ENABLED, FEATURE_ADVANCED_BEHAVIOR). Si un flag está desactivado, el sistema se comporta como en Fase 2.

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
· 4.5 Zona Gris (FEATURE_GRAY_ZONE_ENABLED)
· 4.6 Corrección → Staging (FEATURE_STAGING_ENABLED)
· 4.7 Sandbox (FEATURE_SANDBOX_ENABLED)

🟠 [FASE 3 — Producto Completo] Flujos NUEVOS

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
  → Si True y len(texto) > split_chars:
      → Divide el texto por puntos, comas o saltos de línea
      → Envía cada segmento con delays intermedios y typing
  → Si allow_human_quirks=True:
      → Con probabilidad baja (ej. 5%):
          - Añadir pausa extra
          - Enviar corrección tipográfica
          - Dividir mensaje de forma "natural"
```

---

4. Contratos críticos que ningún agente puede romper

4.1 Decisor (orden de prioridades actualizado)

El Decisor debe evaluar las condiciones en este orden exacto:

Prioridad Condición Acción
1 perfil.seguridad < umbral_seguridad Escalar
2 comprension.needs_policy == true Y policy_retrieval_result == vacío Y FEATURE_GRAY_ZONE_ENABLED Consultar doctrina
2b comprension.emotion == "molesta" Escalar (frustracion_directa)
3 comprension.risk == "alto" Escalar
4 (pre-Decisor) perfil.naturalidad < umbral_naturalidad → Director re-genera 1× + re-evalúa (MVP; sin Decision.action=regenerate). El Decisor no emite regenerate. Multi-retry / action regenerate = residual.
5 Modo autónomo activo Y umbrales superados Enviar
6 Ninguna de las anteriores Aprobar

Notas sobre prioridad 4: la redraft de naturalidad es **secuenciación del Director** (pre-Decisor), no una acción del Decisor. El orden de **acciones** del Decisor sigue siendo seguridad → zona gris → frustracion → risk → send autónomo → approve; el paso 4 del Decisor es no-op (redraft ya ocurrió upstream si correspondía).

Justificación de la prioridad 2 sobre la 3 (BR-02 modificado): La zona gris se evalúa antes que risk=alto porque la falta de doctrina es una causa tratable que, una vez resuelta, elimina la necesidad de escalación futura. La escalación por risk=alto solo se ejecuta cuando no hay doctrina pendiente.

Justificación de 2b (frustracion_directa): emotion molesta escala sin esperar acumulación de risk; se evalúa después de zona gris (doctrina tratable gana) y antes de risk=alto / send autónomo.

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

5.1 Al implementar modo autónomo

1. El Decisor ya tiene la regla de send al final. Asegurarse de que el orden de prioridades se mantiene.
2. AutonomousModeService debe verificar FEATURE_AUTONOMOUS_MODE y auto_send por VIP.
3. Las notificaciones a la dueña deben ser opcionales y configurables por umbral.

5.2 Al implementar recontacto

1. El pipeline reducido no debe pasar por Analista ni Planificador.
2. Las plantillas deben ser fijas, pero pueden incluir placeholders ({nombre}, {producto}).
3. El job debe respetar los periodos de silencio configurados y evitar spam.

5.3 Al implementar promo no-VIP

1. La coincidencia debe ser exacta (case-insensitive, pero sin fuzzy matching).
2. La secuencia se envía con delays entre mensajes (BehaviorEngine ya lo soporta).
3. No se debe guardar en pipeline_traces.

5.4 Al implementar calibración

1. Usar un window_days configurable (default 30).
2. Calcular umbrales por separado para cada dimensión.
3. Aplicar suavizado (promedio con umbral anterior) para evitar oscilaciones.
4. Registrar el cambio en system_config con historial (opcional).

5.5 Al implementar Behavior avanzado

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
SPEC.md v1.5 Cómo se implementa la Fase 1 (diseño técnico)
SPEC-FASE2.md Cómo se implementa la Fase 2 (MVP+)
SPEC-FASE3.md Cómo se implementa la Fase 3 (Producto Completo)
Anexos_contratos.md Contratos detallados de todos los nodos
Anexo T Sistema de trazabilidad interactiva
AGENTS.md (este) Límites que ningún agente puede cruzar al tocar el código, clasificados por fase; más regla de comunicación con dueño de producto (sección 0)

---

Fin de AGENTS.md v1.3 (Fase 3)
Última actualización: Julio 2026
Equipo de Arquitectura — Producto completo listo para desarrollo.
