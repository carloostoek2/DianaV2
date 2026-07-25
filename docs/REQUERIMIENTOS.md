
**Documento de requisitos** del sistema de automatización de chats VIP (Diana Business Bot y sistemas equivalentes).

| Campo | Valor |
|-------|--------|
| Nivel | Requisitos de negocio y de sistema (qué debe cumplir) |
| Audiencia | Dueña del producto, stakeholders, producto, ingeniería |
| Siguiente documento | [`SPEC.md`](SPEC.md) — contrato de diseño e implementación (cómo) |
| Operación para agentes | [`AGENTS.md`](AGENTS.md) — límites de módulo y flujos vivos |
| Versión | 2.1 — Arquitectura Cognitiva + refinamiento de aprendizaje, políticas y métricas |

---

## 1. Propósito

Definir de forma **no ambigua** las capacidades, restricciones y criterios de éxito del sistema que:

- conversa en nombre de una **persona real** (la dueña de la cuenta) en Telegram;
- se limita a contactos **VIP autorizados** (y a flujos promocionales acotados para no-VIP);
- usa un **modelo de lenguaje** como razonador especializado dentro de un pipeline cognitivo, con **control humano** del riesgo;
- se comporta de forma **creíblemente humana** frente al interlocutor;
- **aprende** de correcciones, memoria por persona y reglas de negocio reutilizables de forma controlada y no contaminante;
- toma **decisiones conversacionales** mediante procesos cognitivos especializados y explicables, donde la respuesta textual es únicamente la consecuencia de esas decisiones.

Este documento **no** prescribe tecnologías concretas (bases de datos, librerías, proveedores). Eso vive en el SPEC.

---

## 2. Problema y oportunidad

### 2.1 Problema

La dueña de la cuenta atiende conversaciones de alto valor de forma manual. Eso implica:

- tiempo limitado y respuestas lentas o interrumpidas;
- riesgo de tono inconsistente o de olvidar datos del interlocutor;
- imposibilidad de cubrir silencios largos sin perder calidez;
- miedo a automatizar: pagos, crisis, promesas comerciales o “parecer un bot” no se pueden delegar a ciegas.

### 2.2 Oportunidad

Un sistema que **decide + redacta + envía en su nombre**, con:

1. apariencia humana (tiempos, lectura, “escribiendo…”);
2. modos supervisado y autónomo;
3. escalación cuando el humano debe tomar el hilo;
4. consulta de **doctrina** cuando falta una regla de negocio (no solo “¿se ve bien el texto?”);
5. memoria y ejemplos para mejorar con el uso de forma controlada;
6. pipeline cognitivo especializado, auditable y explicable, donde el LLM es un razonador, no el director.

### 2.3 Qué no es el producto

- Un bot genérico de atención al cliente multi-empresa.
- Un CRM, pasarela de pagos o panel de facturación.
- Un userbot que imite sesión de usuario como canal principal de envío (riesgo de cuenta).
- Un sistema donde el LLM “piensa” qué hacer en cada turno (el Director es determinista).
- Un sistema que aprende automáticamente de cada corrección sin staging ni revisión.

---

## 3. Arquitectura Cognitiva (fundamento del sistema)

El sistema **no es un chatbot**.  
Es un conjunto de **procesos cognitivos especializados** que colaboran para tomar una **decisión conversacional**.  
El LLM es un razonador especializado, no la inteligencia del sistema. La inteligencia emerge de la colaboración de los componentes.

### 3.1 Principio Fundamental

**Todo componente responde una sola pregunta. Nunca más de una.**

Esto permite evolución independiente de cada módulo.

### 3.2 Flujo Cognitivo Canónico (turno VIP normal)

```
Mensaje
  ↓
Director Cognitivo
  ↓
Comprensión (Analista)
  ↓
Planificación
  ↓
Recuperación (vía Capability Registry)
  ↓
Construcción del Contexto
  ↓
Generación
  ↓
Evaluación
  ↓
Decisión
  ↓
Behavior Engine (Entrega)
  ↓
Aprendizaje (post-turno)
```

### 3.3 Roles de los componentes cognitivos

| Componente | Pregunta que responde | Naturaleza |
|------------|-----------------------|----------|
| **Director Cognitivo** | ¿Qué necesita este turno? | 100 % código determinista. Orquesta. Nunca piensa, nunca escribe, nunca consulta memoria. |
| **Analista** | ¿Qué está pasando en este turno? | LLM. Produce objeto estructurado de Comprensión. |
| **Planificador Cognitivo** | ¿Qué conocimiento recuperar? | Determinista a partir de la Comprensión. |
| **Recuperadores** | ¿Qué sabemos sobre X? | Especializados (una capacidad cada uno). Interfaz idéntica. |
| **Constructor de Contexto** | ¿Cuál es el contexto mínimo necesario? | Composición dinámica. Nunca prompt fijo. |
| **Generador** | ¿Cómo respondería la dueña? | LLM. Solo redacta. No clasifica, no decide, no busca. |
| **Evaluador** | ¿Debemos confiar en este mensaje? | Produce **perfil multidimensional** (no score único). |
| **Decisor** | ¿Qué acción tomar? | Trabaja sobre el vector de evaluación + restricciones de modo. |
| **Behavior Engine** | ¿Cómo se actúa el mensaje? | Infraestructura de actuación (delay, read, typing, posibles errores humanos, mensajes divididos). Fuera de la cognición. |
| **Aprendizaje** | ¿Qué aprendimos de este turno? | Proceso separado, siempre post-turno. |

### 3.4 Capability Registry

El Director **no conoce módulos concretos**.  
Conoce únicamente **capacidades** (`knowledge.memory`, `knowledge.policy`, `knowledge.schedule`, `knowledge.examples`, `knowledge.history`, `knowledge.context`, etc.).

Un **Capability Registry** resuelve qué componente satisface cada capacidad.  
Esto garantiza **sustituibilidad** total.

### 3.5 Objeto de Comprensión (salida del Analista)

Ejemplo mínimo obligatorio:

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

Este objeto es el **lenguaje interno** del sistema. Todo lo demás depende de él.

### 3.6 Cinco tipos de conocimiento (nunca se mezclan)

| Tipo | Descripción | Ejemplo |
|------|-------------|---------|
| **Perfil** | Información relativamente permanente del VIP | Nombre, ciudad, profesión |
| **Memoria** | Hechos útiles y preferencias | “Le gustan mensajes cortos”, “Viaja mucho” |
| **Contexto** | Información temporal ya interpretada | “Ayer pidió cotización y está esperando” |
| **Políticas** | Reglas de negocio / doctrina estructuradas | Ver estructura obligatoria en §9.7 |
| **Ejemplos** | Casos exitosos del pasado (inspiración, no reglas) | Conversaciones previas de estilo similar |

### 3.7 Perfil de Evaluación (reemplaza confianza única)

El Evaluador produce un **vector de dimensiones independientes**.  
No existe score único ni promedio.

Dimensiones mínimas obligatorias:

- Naturalidad
- Precisión
- Doctrina
- Consistencia
- Seguridad
- Cobertura
- Empatía

El **Decisor** aplica reglas sobre el vector (ejemplos):

- Seguridad < umbral → Escalar
- Doctrina < umbral → Consultar doctrina (zona gris)
- Naturalidad < umbral → Regenerar
- etc.

Los umbrales operativos se calibran empíricamente a partir de datos reales (ver REQ-EVAL-*).

### 3.8 Persistencia de objetos intermedios (auditabilidad)

Todos los objetos del pipeline se persisten durante un tiempo configurable:

- Comprensión
- Plan de recuperación
- Conocimiento recuperado (qué Memorias, Políticas, Ejemplos, etc. se usaron)
- Prompt construido
- Texto generado
- Perfil de Evaluación
- Decisión final
- Resultado de entrega

Esto permite reconstruir completamente el proceso mental de cualquier respuesta (“¿Por qué respondió esto?”).

### 3.9 Variantes del pipeline

| Situación | Pipeline |
|-----------|----------|
| Turno VIP normal | Completo |
| Sandbox | Completo (solo Behavior Engine es Fake Delivery) |
| Recontacto por silencio | Reducido: Evento → Director → Recuperar memoria + políticas → Generar → Evaluar → Enviar |
| Escalación por palabra prohibida | Cortocircuito determinístico antes del Analista |

### 3.10 Principios cognitivos obligatorios

- **Mínimo conocimiento necesario**: nunca se envía información innecesaria al LLM.
- **Especialización**: cada módulo hace una sola cosa.
- **Explicabilidad**: toda decisión debe poder reconstruirse.
- **Sustituibilidad**: cualquier módulo puede cambiar sin afectar a los demás (vía Capability Registry).
- **Composición**: el contexto nunca está escrito; se construye.
- **Aprendizaje incremental y controlado**: solo se incorpora conocimiento nuevo tras staging/revisión cuando corresponde; nunca se reaprende todo automáticamente.

### 3.11 La Gran Idea

> El sistema no genera respuestas.  
> El sistema toma decisiones.  
> Las respuestas son únicamente una consecuencia de esas decisiones.

---

## 4. Alcance

### 4.1 Dentro de alcance

| ID | Área |
|----|------|
| SC-01 | Chats de negocio en Telegram vinculados a la cuenta de la dueña (Chat Automation / Business). |
| SC-02 | Respuestas automáticas a un **conjunto cerrado de VIP** autorizados. |
| SC-03 | Supervisión, corrección, notas y administración desde el **DM privado** de la dueña con el bot. |
| SC-04 | Escalación a humano, aprobación de borradores, consulta de zona gris (doctrina). |
| SC-05 | Memoria por VIP (cinco tipos de conocimiento), ejemplos de entrenamiento y políticas reutilizables. |
| SC-06 | Recontacto por silencio prolongado (plantillas fijas o pipeline reducido). |
| SC-07 | Respuesta promocional acotada a no-VIP ante un disparador exacto (sin LLM). |
| SC-08 | Observación opcional de chats no autorizados para aprendizaje cuando la dueña responde a mano. |
| SC-09 | Modo de prueba (sandbox) y pausa de datos por VIP. |
| SC-10 | Recuperación razonable del estado tras reinicio del proceso. |
| SC-11 | Pipeline cognitivo completo, auditable y explicable (Director + Analista + Recuperadores + Evaluador + Decisor). |
| SC-12 | Behavior Engine separado (actuación human-like). |
| SC-13 | Aprendizaje controlado con staging area, destilación estructurada de políticas y métricas de efectividad. |

### 4.2 Fuera de alcance (v1 de producto)

| ID | Exclusión |
|----|-----------|
| OO-01 | Cobros, reembolsos o gestión de suscripciones dentro del bot. |
| OO-02 | Multi-tenant / varias dueñas en la misma instancia como producto. |
| OO-03 | Canales distintos de Telegram Business como camino principal (WhatsApp, IG, etc.). |

---

## 5. Actores y stakeholders

| Actor | Descripción | Intereses principales |
|-------|-------------|------------------------|
| **Dueña (admin)** | Persona cuya cuenta de Telegram envía los mensajes; opera el bot por DM. | Control, tono de marca, no perder VIP, no promesas falsas, poco ruido, auditabilidad, aprendizaje que realmente mejora. |
| **VIP** | Contacto en allowlist; conversación de alto valor. | Respuestas naturales, continuidad, que “conozcan” su contexto. |
| **No-VIP** | Contacto no autorizado; puede disparar promo fija o solo ser observado. | Info comercial básica sin fricción; no espera chat personal largo del bot. |
| **Sistema LLM** | Proveedor de generación de texto (actor técnico). | Recibe contexto mínimo; no es decisor final. |
| **Operación / ingeniería** | Quien despliega y mantiene. | Observabilidad, tests, recuperación, secretos seguros, trazabilidad del pipeline, métricas de aprendizaje. |

Un solo **admin** principal por despliegue (identificado por su Telegram user id).

---

## 6. Objetivos de negocio

| ID | Objetivo | Indicador cualitativo de éxito |
|----|----------|--------------------------------|
| BO-01 | Liberar tiempo de la dueña en VIP de rutina | La mayoría de turnos rutinarios se resuelven sin que escriba ella el texto final |
| BO-02 | Mantener (o mejorar) la calidad percibida del vínculo | El VIP no percibe un bot torpe; tono alineado a la persona |
| BO-03 | Reducir riesgo operativo y comercial | Casos de pago/crisis/doctrina ambigua no se inventan solos |
| BO-04 | Aprender del uso real de forma controlada | Correcciones, notas y políticas reutilizables mejoran turnos futuros **sin contaminar** el banco de conocimiento |
| BO-05 | Proteger la cuenta de Telegram | Canal oficial de automatización de negocio; sin dependencia de hacks de sesión |
| BO-06 | Tener control y explicabilidad total | Cualquier respuesta puede reconstruirse: qué se comprendió, qué se recuperó, qué se evaluó y por qué se decidió |
| BO-07 | Medir objetivamente si el aprendizaje está funcionando | Tasa de aprobación sin corrección sube; repetición de zona gris baja; falsos positivos de escalación controlados |

---

## 7. Supuestos y dependencias

### 7.1 Supuestos

- A-01: La dueña tiene (o puede activar) **Chat Automation / Business connection** en Telegram y un bot de BotFather conectado.
- A-02: Existe al menos un proveedor LLM con API y clave válida.
- A-03: El volumen de VIP es **bajo o acotado** (lista cerrada; decenas, no miles concurrentes como requisito v1).
- A-04: El idioma principal de la conversación y de la UI admin es **español** (configurable a futuro).
- A-05: La dueña puede revisar el DM del bot con frecuencia razonable en modo supervisado.
- A-06: Los VIP aceptan conversación asíncrona (minutos de espera son normales en el dominio).

### 7.2 Dependencias externas

- D-01: Disponibilidad de la Bot API de Telegram y del modo Business.
- D-02: Disponibilidad y latencia del proveedor LLM.
- D-03: (Opcional) API de usuario Telegram solo para **importación/backfill** de historial, no como canal principal de respuesta.

### 7.3 Restricciones de producto

- C-01: El mensaje al VIP debe salir **como la dueña** (cuenta de negocio / connection), no como un bot con otro nombre en ese chat.
- C-02: No se exige multi-dispositivo de admin ni roles de equipo en v1.
- C-03: Secretos y datos reales de conversación no deben vivir en el control de versiones.
- C-04: El Director Cognitivo es 100 % determinista; nunca pregunta a un LLM “¿qué hago?”.
- C-05: Ninguna corrección entra automáticamente al banco vivo de ejemplos; siempre pasa por staging.

---

## 8. Glosario

| Término | Definición |
|---------|------------|
| **VIP** | Usuario en la lista de autorizados; recibe automatización conversacional completa. |
| **Borrador** | Texto propuesto por el Generador aún no enviado o en revisión. |
| **Modo supervisado** | Todo envío VIP pasa por aprobación (salvo excepción por-VIP de auto-envío). |
| **Modo autónomo** | El sistema envía sin aprobación previa; puede notificar según perfil de evaluación. |
| **Escalación** | El bot **no** debe cerrar el caso: la dueña (o un humano) toma el hilo. |
| **Aprobación** | Juicio sobre si un **borrador concreto** es apto para enviar. |
| **Zona gris / guidance** | Falta una **regla de negocio reutilizable**; se consulta a la dueña y se puede materializar como política. |
| **Política** | Regla de negocio / doctrina **estructurada** (disparador + regla + alcance + vigencia). |
| **Perfil** | Información relativamente permanente del VIP. |
| **Memoria** | Hechos útiles y preferencias del VIP. |
| **Contexto** | Información temporal ya interpretada del VIP. |
| **Ejemplos** | Casos exitosos del pasado usados como inspiración (few-shot). Viven en banco separado de la Memoria. |
| **Staging Area** | Zona intermedia donde las correcciones y candidatos a ejemplo esperan confirmación explícita antes de pasar al banco vivo. |
| **Comprensión** | Objeto estructurado producido por el Analista que describe el turno. |
| **Perfil de Evaluación** | Vector multidimensional (Naturalidad, Precisión, Doctrina, Consistencia, Seguridad, Cobertura, Empatía). Reemplaza la antigua “confianza única”. |
| **Director Cognitivo** | Componente 100 % determinista que orquesta el pipeline. Nunca piensa ni escribe. |
| **Analista** | Componente LLM que produce la Comprensión. |
| **Capability Registry** | Resuelve qué componente satisface una capacidad solicitada por el Director. |
| **Behavior Engine** | Módulo de actuación human-like (delay, lectura, typing, posibles errores humanos, mensajes divididos). Fuera de la cognición. |
| **Congelación VIP** | Mientras hay consulta de zona gris abierta: cero señales ni mensajes del bot hacia ese VIP. |
| **Sandbox** | Modo de prueba con perfiles ficticios / sin contaminar aprendizaje real. Usa el mismo pipeline cognitivo. |
| **Contraejemplo** | Par (borrador_original, corrección_final) que muestra explícitamente “así no → así sí”. |
| **Few-shot** | Ejemplos de conversaciones previas usados para estilo/contenido. Solo del banco vivo. |

---

## 9. Requisitos funcionales

Prioridad: **P0** indispensable · **P1** importante · **P2** deseable.

### 9.1 Identidad, canales y autorización

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-AUTH-01 | P0 | El sistema solo automatiza conversaciones VIP de usuarios presentes en una **lista de autorizados** mantenida por la dueña. |
| REQ-AUTH-02 | P0 | La dueña puede **añadir** y **quitar** VIP sin redeploy (p. ej. reenvío de mensaje + UI). |
| REQ-AUTH-03 | P0 | Existe un tope configurable de VIP simultáneos en la lista. |
| REQ-AUTH-04 | P0 | Los mensajes salientes al chat VIP se envían en nombre de la dueña mediante la conexión de negocio de Telegram. |
| REQ-AUTH-05 | P0 | El sistema distingue mensajes escritos por la **dueña** de los del **VIP** en el mismo chat. |
| REQ-AUTH-06 | P1 | Si la dueña escribe manualmente en un chat VIP, el sistema **cede** (cancela respuestas automáticas pendientes de ese turno). |
| REQ-AUTH-07 | P1 | Opcionalmente, el sistema puede **observar** chats no autorizados sin auto-responder. |
| REQ-AUTH-08 | P0 | Solo la dueña (admin configurado) opera menús, aprobaciones y comandos de administración. |

### 9.2 Pipeline Cognitivo (REQ-COG)

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-COG-01 | P0 | Todo turno VIP normal atraviesa el pipeline cognitivo completo: Director → Analista → Planificación → Recuperación → Construcción de Contexto → Generación → Evaluación → Decisión → Behavior Engine → Aprendizaje. |
| REQ-COG-02 | P0 | El **Director Cognitivo** es 100 % determinista (código). Nunca invoca un LLM para decidir “qué hacer”. Solo orquesta a partir de la Comprensión. |
| REQ-COG-03 | P0 | El Director conoce únicamente **capacidades** (`knowledge.memory`, `knowledge.policy`, etc.). Un **Capability Registry** resuelve los componentes concretos. |
| REQ-COG-04 | P0 | El **Analista** (LLM) produce un objeto de Comprensión estructurado que incluye al menos: intent, topics, emotion, urgency, risk, y flags needs_* para cada tipo de conocimiento. |
| REQ-COG-05 | P0 | Cada **Recuperador** tiene exactamente la misma interfaz (entrada: necesidad → salida: información estructurada) y responde una sola pregunta. |
| REQ-COG-06 | P0 | El **Constructor de Contexto** compone dinámicamente el prompt mínimo necesario. No existe prompt fijo. Cualquier bloque puede estar ausente. |
| REQ-COG-07 | P0 | El **Generador** (LLM) recibe un contexto completamente preparado y **solo redacta**. No clasifica, no busca conocimiento, no toma decisiones. |
| REQ-COG-08 | P0 | El **Evaluador** produce un **perfil de evaluación multidimensional** (Naturalidad, Precisión, Doctrina, Consistencia, Seguridad, Cobertura, Empatía). No existe score único ni promedio. |
| REQ-COG-09 | P0 | El **Decisor** trabaja sobre el vector de evaluación + las restricciones de modo (supervisado/autónomo) y decide una de: Enviar, Aprobar, Escalar, Consultar doctrina, Regenerar. |
| REQ-COG-10 | P0 | Los modos (supervisado/autónomo) son **restricciones externas**. El Decisor propone; los modos filtran lo permitido. |
| REQ-COG-11 | P0 | Todos los objetos intermedios del pipeline (Comprensión, Plan, conocimiento recuperado, prompt, evaluación, decisión) se **persisten** durante un tiempo configurable para auditabilidad total. |
| REQ-COG-12 | P1 | El sistema puede reconstruir de forma legible el proceso completo de cualquier respuesta (“¿Por qué respondió esto?”). |
| REQ-COG-13 | P0 | El **Behavior Engine** es un módulo separado de la cognición. Se encarga de delay, marcar como leído, typing, posibles errores humanos y mensajes divididos. |
| REQ-COG-14 | P0 | Sandbox ejecuta exactamente el mismo pipeline cognitivo (solo el Behavior Engine es Fake Delivery). |
| REQ-COG-15 | P1 | Recontacto por silencio usa un pipeline reducido: Evento → Director → Recuperar memoria + políticas → Generar → Evaluar → Enviar. |
| REQ-COG-16 | P0 | Escalación por palabras/temas prohibidos es un cortocircuito determinístico **antes** del Analista. |

### 9.3 Conversación VIP y generación de respuesta

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-VIP-01 | P0 | Ante un mensaje nuevo de un VIP autorizado, el sistema ejecuta el pipeline cognitivo completo. |
| REQ-VIP-02 | P0 | La respuesta considera historial reciente, memoria, políticas, contexto y ejemplos **únicamente** los que el Planificador solicitó. |
| REQ-VIP-03 | P0 | El Analista devuelve el objeto de Comprensión estructurado. El Generador devuelve solo texto. El Evaluador devuelve el perfil multidimensional. |
| REQ-VIP-04 | P0 | El sistema aplica un **persona/voz** definido y reglas de estilo de producto a través del Constructor de Contexto. |
| REQ-VIP-05 | P1 | El sistema puede inyectar contexto temporal (zona horaria, agenda/disponibilidad de la dueña) cuando el Planificador lo solicita. |
| REQ-VIP-06 | P0 | Mensajes VIP sucesivos **reprograman** la respuesta: no deben enviarse borradores obsoletos de un turno superado. |
| REQ-VIP-07 | P1 | Las ediciones de mensajes del VIP no deben, por defecto, disparar una nueva automatización confusa (política: ignorar o tratar de forma explícita). |
| REQ-VIP-08 | P1 | Si la generación o evaluación falla de forma reiterada, la dueña es notificada y el VIP no recibe basura ni silencio sin rastro admin. |

### 9.4 Comportamiento human-like (Behavior Engine)

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-HUM-01 | P0 | El sistema **no** responde al VIP de forma instantánea tipo bot; hay espera previa configurable. |
| REQ-HUM-02 | P0 | Antes de responder, el sistema marca el mensaje como **leído**. |
| REQ-HUM-03 | P0 | El sistema muestra **indicador de escritura** con duración razonable respecto a la longitud del texto. |
| REQ-HUM-04 | P1 | En modo autónomo, el rango de espera es mayor y aleatorizado; en supervisado puede ser más corto (la dueña ya mira). |
| REQ-HUM-05 | P1 | Secuencias de varios mensajes fijos (p. ej. promo) respetan huecos y typing entre mensajes. |
| REQ-HUM-06 | P2 | El Behavior Engine puede simular errores humanos leves o mensajes divididos cuando la política de personalidad lo permita. |

### 9.5 Modos supervisado y autónomo

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-MODE-01 | P0 | Existe un modo **supervisado global**: ningún envío VIP sin acción de la dueña (aprobar o corregir), salvo excepciones explícitas. |
| REQ-MODE-02 | P0 | Existe un modo **autónomo global**: el sistema envía sin aprobación previa (sujeto al Decisor + perfil de evaluación). |
| REQ-MODE-03 | P0 | En supervisado, la dueña recibe en su DM el borrador con contexto suficiente para decidir (incluyendo, cuando esté disponible, la traza cognitiva resumida). |
| REQ-MODE-04 | P0 | La dueña puede **aprobar** (enviar tal cual) o **corregir** (sustituir el texto y enviar la versión humana). |
| REQ-MODE-05 | P1 | La dueña puede **regenerar** variantes de un borrador y elegir entre ellas. |
| REQ-MODE-06 | P1 | La dueña puede adjuntar una **nota** sobre el VIP sin cambiar el borrador de ese turno. |
| REQ-MODE-07 | P1 | En autónomo, el Decisor puede notificar a la dueña según reglas sobre el perfil de evaluación (ej. Doctrina o Seguridad bajas). |
| REQ-MODE-08 | P1 | Puede existir **auto-envío por VIP** aunque el global sea supervisado. |
| REQ-MODE-09 | P1 | Tras envíos autónomos, la dueña puede calificar o corregir a posteriori para entrenamiento. |

### 9.6 Escalación a humano

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-ESC-01 | P0 | Hay temas o palabras (pagos, reclamos, “eres un bot”, crisis, etc.) que **impiden** la auto-respuesta mediante cortocircuito determinístico **antes** del Analista y avisan a la dueña. |
| REQ-ESC-02 | P0 | El Analista puede señalar risk alto o el Evaluador/Decisor pueden decidir escalar a partir del perfil de evaluación. |
| REQ-ESC-03 | P0 | En escalación, el VIP no recibe una respuesta automática del flujo normal de borrador. |
| REQ-ESC-04 | P1 | La dueña puede **triar** la escalación: válida, falso positivo, o forzar generación normal. |
| REQ-ESC-05 | P1 | Los falsos positivos se registran para reducir repeticiones indebidas. |
| REQ-ESC-06 | P1 | Queda traza auditable de escalaciones (quién, por qué, veredicto) incluyendo objetos del pipeline. |

### 9.7 Zona gris (doctrina) y políticas estructuradas

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-GAP-01 | P1 | El Analista puede indicar `needs_policy=true` o el Evaluador puede detectar Doctrina insuficiente. Esto es una observación, no la decisión. |
| REQ-GAP-02 | P1 | Si ya existe una política aplicable, el sistema **reutiliza** esa doctrina y no vuelve a preguntar a la dueña por lo mismo. |
| REQ-GAP-03 | P1 | Si no hay política, el Decisor decide “Consultar doctrina”; el VIP queda en **congelación** (sin lectura/typing/envío/recontacto del bot). |
| REQ-GAP-04 | P1 | La dueña puede: responder la doctrina, usar el borrador propuesto, u omitir el turno. |
| REQ-GAP-05 | P1 | Una respuesta de doctrina se **destila** en una política estructurada (nunca se guarda la respuesta literal como política). |
| REQ-GAP-06 | P1 | Tras resolver, el flujo vuelve al camino normal (aprobación o envío según modo). |
| REQ-GAP-07 | P1 | Las consultas abiertas expiran tras un tiempo configurable (comportamiento definido: p. ej. usar borrador). |
| REQ-GAP-08 | P2 | La dueña puede listar y desactivar políticas desde admin. |
| REQ-GAP-09 | P1 | La función de zona gris es **desactivable** por configuración sin romper el resto del producto. |
| REQ-GAP-10 | P1 | Toda política debe tener la estructura obligatoria: `disparador` (tipo de situación, no palabras exactas), `regla` (qué hacer/decir), `ejemplo_aplicado` (opcional), `alcance` (todos los VIP o segmento), `vigencia` (fecha de expiración opcional). |
| REQ-GAP-11 | P1 | Al resolver una zona gris el sistema debe pedir (o inferir y pedir confirmación) la **generalización**: “¿esto aplica siempre que pregunten por X, o solo en este caso puntual?”. Sin este paso no se crea la política. |

### 9.8 Memoria y personalización por VIP (cinco tipos)

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-MEM-01 | P1 | El sistema almacena y recupera los cinco tipos de conocimiento de forma separada: Perfil, Memoria, Contexto, Políticas, Ejemplos. |
| REQ-MEM-02 | P1 | Tras conversaciones exitosas, el proceso de Aprendizaje puede **extraer** hechos nuevos de forma automática (clasificados en el tipo correcto). |
| REQ-MEM-03 | P1 | La dueña puede añadir o borrar **notas manuales** por VIP (se almacenan como Memoria o Perfil según corresponda). |
| REQ-MEM-04 | P1 | Solo el conocimiento solicitado por el Planificador influye en el turno. |
| REQ-MEM-05 | P1 | El contenido de cualquier tipo de conocimiento se trata como **dato no confiable** (nunca como instrucciones del sistema). |
| REQ-MEM-06 | P1 | Contexto (interpretado) es distinto de Historial (raw). El recuperador de Historial devuelve mensajes; el de Contexto devuelve hechos temporales ya interpretados. |
| REQ-MEM-07 | P1 | La Memoria (hechos por VIP) y el banco de Ejemplos (few-shots) son bancos de datos **separados** con reglas de acceso separadas. La Memoria de un VIP **nunca** puede entrar al banco de few-shots reutilizables entre VIP (anti-contaminación). |

### 9.9 Aprendizaje controlado (few-shot / training)

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-TRN-01 | P1 | El sistema guarda ejemplos de contexto + respuesta (y opcionalmente corrección humana) en el tipo **Ejemplos**. |
| REQ-TRN-02 | P1 | En la generación se pueden inyectar **pocos ejemplos** del tema relevante (top-k = 3-5 por defecto), solo si el Planificador lo solicitó. |
| REQ-TRN-03 | P2 | Si la dueña responde a mano en un chat solo observado, el sistema puede capturar ese ejemplo (excluyendo temas puramente transaccionales si se configura). Se trata como candidato de menor confianza por defecto. |
| REQ-TRN-04 | P2 | Existe un medio de **importar** historiales históricos para arrancar el entrenamiento. |
| REQ-TRN-05 | P1 | El aprendizaje ocurre **siempre después** de terminar el turno. Nunca durante el pipeline de decisión. |
| REQ-TRN-06 | P1 | Existen **cuatro fuentes de señal de aprendizaje** con calidad distinta: (1) Aprobación sin cambios → señal fuerte positiva; (2) Corrección de la dueña → la más valiosa (se guarda el par borrador_original + corrección_final como contraejemplo); (3) Resolución de zona gris → se convierte en Política, no en few-shot; (4) Turnos observados donde la dueña responde a mano → señal más ruidosa, menor confianza por defecto. |
| REQ-TRN-07 | P1 | Toda corrección entra primero a un **Staging Area** (tabla de candidatos). Solo pasa al banco vivo de ejemplos tras **confirmación explícita** de la dueña (ej. botón “usar como ejemplo”). Nunca se promueve automáticamente. |
| REQ-TRN-08 | P1 | El retrieval de few-shots prioriza: (a) similitud semántica con el turno actual, (b) recencia, (c) limpieza (preferir ejemplos aprobados sin corrección sobre correcciones). Ocasionalmente se puede incluir un **contraejemplo explícito** junto al positivo. |
| REQ-TRN-09 | P1 | El banco de Ejemplos y la Memoria por VIP tienen reglas de acceso separadas. Ningún hecho de Memoria puede convertirse automáticamente en few-shot reutilizable entre VIP. |

### 9.10 Evaluación y calibración del perfil (REQ-EVAL)

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-EVAL-01 | P1 | El sistema registra, por cada turno evaluado, el perfil de evaluación completo y si el borrador fue corregido o no por la dueña. |
| REQ-EVAL-02 | P1 | Periódicamente (cada semana o cada N turnos) se calcula la calibración empírica de cada dimensión del perfil (ej. de los turnos con Doctrina > umbral, qué % realmente se aprobó sin corrección). |
| REQ-EVAL-03 | P1 | Los umbrales operativos que usa el Decisor se ajustan a partir de esa curva empírica (no se confía ciegamente en los valores absolutos que devuelve el Evaluador). |
| REQ-EVAL-04 | P2 | Existe un medio simple de visualizar la calibración actual (histograma o tabla por dimensión vs. tasa de corrección real). |

### 9.11 Recontacto por silencio

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-REE-01 | P2 | Si un VIP autorizado lleva un tiempo configurable sin escribir, el sistema puede enviar un mensaje corto de recontacto. |
| REQ-REE-02 | P2 | Los textos de recontacto pueden ser plantillas fijas o generados mediante el pipeline reducido. |
| REQ-REE-03 | P2 | No hay recontacto si el chat está congelado, con aprobación pendiente, con timer activo, en sandbox o en pausa. |
| REQ-REE-04 | P2 | La dueña es informada cuando se envía un recontacto. |

### 9.12 No-VIP y promoción

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-PRO-01 | P1 | Ante un **texto disparador exacto** de un no-VIP, el sistema puede enviar una secuencia promocional fija. |
| REQ-PRO-02 | P1 | Ese flujo **no** usa LLM ni cola de aprobación VIP ni pipeline cognitivo completo. |
| REQ-PRO-03 | P1 | Puede diferenciar primer envío vs reenvío de promos. |
| REQ-PRO-04 | P1 | El envío promo también debe sentirse human-like (Behavior Engine). |

### 9.13 Administración y operación diaria

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-ADM-01 | P0 | La dueña tiene un menú/comandos en DM para usuarios, estado y ayuda. |
| REQ-ADM-02 | P1 | Puede ver estado del sistema (modo, LLM activo, salud básica). |
| REQ-ADM-03 | P1 | Puede cambiar proveedor/modelo LLM en caliente (si hay claves). |
| REQ-ADM-04 | P1 | Puede pausar la automatización de un VIP por un periodo o indefinidamente. |
| REQ-ADM-05 | P1 | Puede activar **sandbox** para probar sin ensuciar memoria/entrenamiento reales. |
| REQ-ADM-06 | P2 | Puede consultar fallos recientes de generación y/o escalaciones. |
| REQ-ADM-07 | P1 | Puede consultar la traza cognitiva (explicabilidad) de respuestas recientes. |
| REQ-ADM-08 | P1 | Puede gestionar el Staging Area (promover o descartar candidatos a ejemplo). |
| REQ-ADM-09 | P1 | Puede ver métricas básicas de aprendizaje (tasa de aprobación sin corrección, repetición de zona gris, tasa de falsos positivos de escalación). |

### 9.14 Persistencia, continuidad y seguridad de datos

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-PER-01 | P0 | La lista VIP y el estado de conexiones de negocio sobreviven a reinicios. |
| REQ-PER-02 | P1 | Borradores pendientes de aprobación y consultas de zona gris abiertas se recuperan o se re-notifican tras reinicio. |
| REQ-PER-03 | P1 | El historial relevante por chat se conserva con un límite razonable de mensajes. |
| REQ-PER-04 | P0 | Secretos (tokens, API keys) no se embeben en el código fuente versionado. |
| REQ-PER-05 | P1 | Los datos de conversación y entrenamiento reales no se publican en el repositorio. |
| REQ-PER-06 | P0 | Los objetos intermedios del pipeline cognitivo se persisten durante un tiempo configurable. |
| REQ-PER-07 | P1 | El sistema puede reconstruir el proceso mental completo de cualquier respuesta a partir de los objetos persistidos. |
| REQ-PER-08 | P1 | El Staging Area y el banco vivo de ejemplos son entidades separadas y persistentes. |

### 9.15 Métricas de efectividad del aprendizaje (REQ-MET)

| ID | Pri | Requisito |
|----|-----|-----------|
| REQ-MET-01 | P1 | El sistema calcula y expone la **tasa de aprobación sin corrección** por semana (debe tender a subir con el tiempo). |
| REQ-MET-02 | P1 | El sistema detecta y reporta **repetición de la misma pregunta de zona gris** (si ocurre, la destilación de políticas está fallando). |
| REQ-MET-03 | P1 | El sistema calcula la **tasa de falsos positivos de escalación** y la expone al admin. |
| REQ-MET-04 | P2 | Existe un mecanismo de muestreo periódico de conversaciones para detectar **drift de estilo** (la única defensa real contra este fenómeno). |

---

## 10. Requisitos no funcionales

| ID | Pri | Categoría | Requisito |
|----|-----|-----------|-----------|
| REQ-NFR-01 | P0 | UX percibida | El VIP no debe recibir respuestas “instantáneas de bot” en el flujo principal. |
| REQ-NFR-02 | P0 | Concurrencia | Condiciones de carrera (mensaje nuevo mientras se genera/envía) no producen envíos duplicados o de turno viejo. |
| REQ-NFR-03 | P0 | Control de riesgo | En congelación por zona gris no hay fugas de I/O hacia el VIP. |
| REQ-NFR-04 | P1 | Fiabilidad | Fallos de red/API se reintentan de forma acotada; el admin puede enterarse del fallo. |
| REQ-NFR-05 | P1 | Mantenibilidad | Separación clara entre interfaz de mensajería, Behavior Engine y lógica cognitiva. |
| REQ-NFR-06 | P1 | Observabilidad | Logs operativos suficientes para diagnosticar “por qué no contestó / por qué escaló”, incluyendo traza cognitiva y métricas de aprendizaje. |
| REQ-NFR-07 | P1 | Prompt budget | El contexto al LLM se mantiene acotado (solo lo solicitado por el Planificador; top-k de ejemplos = 3-5). |
| REQ-NFR-08 | P1 | Testabilidad | Los caminos críticos (timer, aprobación, freeze, escalación, auth, pipeline cognitivo, staging) son verificables sin Telegram real. |
| REQ-NFR-09 | P1 | Seguridad de cuenta | El envío principal usa el mecanismo oficial de automatización de negocio de Telegram. |
| REQ-NFR-10 | P2 | Privacidad | Minimizar PII en logs; memoria tratada como sensible. |
| REQ-NFR-11 | P2 | Escalabilidad v1 | Correctitud con decenas de VIP y baja concurrencia es suficiente; no se exige escala masiva. |
| REQ-NFR-12 | P1 | Explicabilidad | Toda decisión del pipeline debe poder reconstruirse a partir de los objetos intermedios persistidos. |
| REQ-NFR-13 | P0 | Especialización | Ningún componente cognitivo responde más de una pregunta. |
| REQ-NFR-14 | P0 | Sustituibilidad | Cualquier recuperador o componente puede sustituirse vía Capability Registry sin afectar al Director. |
| REQ-NFR-15 | P1 | Anti-contaminación | La Memoria de un VIP nunca puede filtrarse al banco de few-shots reutilizables entre VIP. |
| REQ-NFR-16 | P1 | Aprendizaje controlado | Ninguna corrección se promueve automáticamente al banco vivo; siempre pasa por Staging Area + confirmación explícita. |

---

## 11. Reglas de negocio transversales

Estas reglas son **productales**; el SPEC las implementa sin contradecirlas.

| ID | Regla |
|----|--------|
| BR-01 | **Aprobación ≠ escalación ≠ zona gris ≠ nota.** Cada una responde una pregunta distinta. |
| BR-02 | La escalación por seguridad (safety baja en el perfil de evaluación) tiene prioridad absoluta sobre la zona gris. La escalación por riesgo semántico (risk=alto en la Comprensión) se evalúa después de la zona gris, ya que la ausencia de doctrina puede ser la causa raíz del riesgo y resolverla evita escalaciones futuras. En caso de que ambas señales (seguridad baja y riesgo alto) estén presentes, gana la seguridad (se escala).. |
| BR-03 | Zona gris no se usa para dudas de tono/estilo (eso es dimensión Naturalidad baja + Regenerar o Aprobar). |
| BR-04 | El bot no inventa precios, excepciones ni compromisos no respaldados por prompt, políticas o respuesta de la dueña. |
| BR-05 | Un VIP en pausa de datos no recibe automatización ni recontacto. |
| BR-06 | Sandbox no debe corromper el aprendizaje de producción. |
| BR-07 | Si la dueña retoma el chat a mano, manda su mensaje sobre cualquier borrador pendiente de ese hilo. |
| BR-08 | El Director nunca pregunta a un LLM “qué hacer”. Solo orquesta. |
| BR-09 | No existe score único de confianza. El Decisor trabaja sobre el vector de dimensiones. |
| BR-10 | Los cinco tipos de conocimiento nunca se mezclan ni se recuperan indiscriminadamente. |
| BR-11 | El aprendizaje ocurre siempre después del turno. Nunca durante la decisión. |
| BR-12 | Los modos son restricciones externas; el Decisor propone, los modos filtran. |
| BR-13 | Ninguna corrección entra al banco vivo de ejemplos sin pasar por Staging Area + confirmación explícita. |
| BR-14 | Las políticas se guardan siempre en formato estructurado y generalizado; nunca como respuesta literal de un turno. |
| BR-15 | La Memoria de un VIP es privada a ese VIP; nunca se convierte en few-shot general. |

---

## 12. Matriz de decisión (producto)

| Situación | Qué hace el sistema | Qué ve el VIP | Qué ve la dueña |
|-----------|---------------------|---------------|-----------------|
| Turno rutinario, supervisado | Pipeline completo → Decisor propone Enviar → modo fuerza Aprobar | Nada aún (hasta aprobar) | Borrador + traza cognitiva resumida |
| Turno rutinario, autónomo | Pipeline completo → Decisor propone Enviar → se envía | Respuesta con delay/typing | Nada, o aviso según reglas del perfil de evaluación |
| Palabra/tema de riesgo | Cortocircuito determinístico → Escalar | Silencio del bot | Alerta de escalación + triage |
| risk semántico alto o Doctrina baja | Pipeline → Decisor decide Escalar o Consultar doctrina | Silencio o congelación | Alerta o pregunta de guidance |
| Doctrina ya documentada | Aplica política y responde (según modo) | Respuesta alineada a doctrina | Normal (o nada) |
| Dueña escribe en el chat | Cancela automatización del turno | Mensaje de la dueña | Ella misma en el chat |
| No-VIP + trigger promo | Secuencia fija + Behavior Engine | Promo multi-mensaje | Opcional/ninguno según diseño |
| VIP en silencio N días | Pipeline reducido de recontacto | Mensaje suave | Notificación de recontacto |
| Sandbox | Pipeline completo + Fake Delivery | Nada real | Resultados de prueba |
| Corrección de borrador | Se guarda en Staging Area como candidato (par original + corrección) | — | Botón opcional “usar como ejemplo” |

---

## 13. Historias de usuario (resumen)

1. **Como** dueña, **quiero** que el bot cubra VIP de confianza en mi nombre, **para** no perder hilos cuando estoy ocupada.
2. **Como** dueña, **quiero** aprobar o corregir antes de enviar, **para** no arriesgar tono ni promesas.
3. **Como** dueña, **quiero** que pagos/crisis/“eres bot” me lleguen a mí, **para** no dejar que el modelo improvise.
4. **Como** dueña, **quiero** contestar una regla de negocio una vez y que el sistema la reutilice de forma generalizada, **para** no repetir la misma duda.
5. **Como** dueña, **quiero** notas y memoria por VIP, **para** que las respuestas se sientan personales.
6. **Como** VIP, **quiero** respuestas con ritmo humano y continuidad, **para** sentir una conversación real.
7. **Como** no-VIP, **quiero** recibir la info de promos al pedirla, **para** decidir sin chat largo.
8. **Como** dueña, **quiero** probar en sandbox, **para** iterar el prompt sin ensuciar datos reales.
9. **Como** operadora, **quiero** que un reinicio no pierda aprobaciones abiertas, **para** no dejar hilos colgados en silencio.
10. **Como** dueña o ingeniera, **quiero** poder reconstruir por qué el sistema respondió de cierta forma, **para** confiar y depurar.
11. **Como** dueña, **quiero** que mis correcciones no se conviertan automáticamente en “estilo oficial”, **para** evitar que un error puntual contamine el sistema.
12. **Como** dueña, **quiero** ver si el aprendizaje está realmente mejorando (tasa de aprobación, repetición de zona gris), **para** saber si el sistema está evolucionando o solo acumulando ruido.

---

## 14. Criterios de aceptación de producto

Un despliegue cumple los requisitos P0 (y los P1 comprometidos) cuando:

| # | Criterio | REQ principales |
|---|----------|-----------------|
| AC-01 | Un VIP autorizado recibe una respuesta en nombre de la dueña con espera, lectura y typing | REQ-AUTH-04, REQ-HUM-*, REQ-VIP-01, REQ-COG-01 |
| AC-02 | Un no autorizado no entra al flujo VIP completo | REQ-AUTH-01 |
| AC-03 | En supervisado, nada llega al VIP sin aprobar/corregir | REQ-MODE-01, REQ-MODE-03/04, REQ-COG-10 |
| AC-04 | Un segundo mensaje del VIP invalida el turno anterior | REQ-VIP-06 |
| AC-05 | Escalación por palabra/tema no auto-responde y avisa a la dueña | REQ-ESC-01..03, REQ-COG-16 |
| AC-06 | La dueña puede añadir/quitar VIP y ver estado básico | REQ-AUTH-02, REQ-ADM-01/02 |
| AC-07 | Secretos no están en el repo; reinicio conserva allowlist y conexión | REQ-PER-01, REQ-PER-04 |
| AC-08 | (P1) Zona gris congela al VIP y reutiliza política después de responder | REQ-GAP-02..06, REQ-NFR-03 |
| AC-09 | (P1) Memoria/notas afectan un turno posterior del mismo VIP | REQ-MEM-03/04 |
| AC-10 | (P1) Promo no-VIP por trigger exacto sin LLM | REQ-PRO-01/02 |
| AC-11 | El Director es determinista y usa Capability Registry | REQ-COG-02, REQ-COG-03 |
| AC-12 | No existe score único de confianza; el Decisor trabaja con vector | REQ-COG-08, REQ-COG-09, BR-09 |
| AC-13 | Todos los objetos intermedios se persisten y permiten reconstrucción | REQ-COG-11, REQ-PER-06/07, REQ-NFR-12 |
| AC-14 | Sandbox usa el mismo pipeline cognitivo | REQ-COG-14 |
| AC-15 | Behavior Engine está separado de la cognición | REQ-COG-13 |
| AC-16 | (P1) Toda corrección pasa por Staging Area; no se promueve automáticamente | REQ-TRN-07, BR-13, REQ-NFR-16 |
| AC-17 | (P1) Las políticas se crean en formato estructurado + generalización confirmada | REQ-GAP-10, REQ-GAP-11 |
| AC-18 | (P1) Memoria y few-shots están separados; no hay contaminación entre VIP | REQ-MEM-07, REQ-TRN-09, BR-15 |
| AC-19 | (P1) Existen métricas de tasa de aprobación, repetición de zona gris y falsos positivos de escalación | REQ-MET-01..03 |

---

## 15. Trazabilidad hacia el SPEC

| Bloque de requisitos | Secciones típicas en SPEC.md |
|----------------------|------------------------------|
| REQ-AUTH-* | Business connections, allowlist, admin |
| REQ-COG-* | Cognitive pipeline, Director, Analista, Capability Registry, Evaluador, Decisor |
| REQ-VIP-*, REQ-HUM-* | Timers, Behavior Engine, LLM contracts |
| REQ-MODE-* | Operating modes, approval, training feedback |
| REQ-ESC-* | Escalation (deterministic + semantic) |
| REQ-GAP-* | Gray-zone guidance, structured policies, generalization step |
| REQ-MEM-*, REQ-TRN-* | Five knowledge types, Staging Area, few-shot retrieval, anti-contamination |
| REQ-EVAL-* | Multi-dimensional evaluation profile, empirical calibration |
| REQ-REE-* | Idle re-engagement (reduced pipeline) |
| REQ-PRO-* | Non-VIP promo, multi-message delivery |
| REQ-ADM-* | Admin surface, sandbox, pause, cognitive trace, Staging management, metrics |
| REQ-MET-* | Learning effectiveness metrics |
| REQ-PER-*, REQ-NFR-* | Persistence of intermediate objects, recovery, NFR, testing, explainability, anti-contamination |

Al añadir un requisito nuevo aquí, actualizar el SPEC (y `AGENTS.md` si cambia un flujo canónico).

---

## 16. Personalización por despliegue (entradas de producto)

Antes de configurar un entorno real, el negocio debe definir:

1. Persona, voz, idioma y frases prohibidas.
2. Agenda / disponibilidad que el bot puede mencionar.
3. Criterio de quién es VIP y tamaño máximo de lista.
4. Lista de escalación (qué nunca responde el bot) + umbrales del perfil de evaluación.
5. Qué promesas comerciales puede hacer vs zona gris.
6. Textos de promo no-VIP y de recontacto.
7. Admin Telegram id.
8. Preferencia de modo inicial (supervisado recomendado al arrancar).
9. Umbrales por dimensión del perfil de evaluación (Seguridad, Doctrina, Naturalidad, etc.) y política de calibración.
10. Tiempo de retención de objetos intermedios del pipeline.
11. Política de staging (quién puede promover candidatos a ejemplo).

---

## 17. Mantenimiento de este documento

- Cambios de **comportamiento de producto** → actualizar REQUIREMENTS primero, luego SPEC.
- Cambios solo de **implementación** (librería, schema interno, refactor) → SPEC / código; no hace falta REQ nuevo si el comportamiento observable no cambia.
- No incluir aquí ejemplos de conversaciones reales ni secretos.
- Prioridades P0/P1/P2 pueden negociarse por release; un release “mínimo viable supervisado” cubre como mínimo todos los **P0**.

---

## 18. MVP recomendado (recorte de release)

**MVP supervisado (primer valor seguro)**  
REQ P0 de: AUTH, COG (pipeline básico + Director determinista + Evaluador vectorial), VIP, HUM, MODE (supervisado), ESC básica, ADM básica, PER básica (incluyendo objetos intermedios), NFR-01/02/09/13/14/16.

**MVP+ aprendizaje controlado**  
+ MEM (cinco tipos + anti-contaminación), TRN (Staging Area + fuentes de señal + retrieval), GAP (políticas estructuradas + generalización), EVAL (calibración), MET (métricas básicas), MODE autónomo opcional, ESC triage, explicabilidad P1.

**Producto completo alineado a este repo**  
+ REE, PRO, sandbox, pause, recovery rica, Behavior Engine avanzado, observabilidad completa, drift detection.
ENDOFFILE
