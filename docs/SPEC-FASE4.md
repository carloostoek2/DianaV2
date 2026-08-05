# SPEC-FASE4.md — Atención al Cliente General (canal no-VIP) — v1.0

Diana Business Bot / Sistema de Automatización de Chats VIP

| Campo | Valor |
|---|---|
| Nivel | Contrato de diseño e implementación para la Fase 4 |
| Basado en | REQUERIMIENTOS.md v2.1 + SPEC.md v1.5 + SPEC-FASE2.md v2.1 + SPEC-FASE3.md v3.0 + AGENTS.md v1.3 |
| Audiencia | Ingeniería (implementación con DeepSeek en terminal; revisión posterior) |
| Versión | 1.0 — Borrador de diseño aprobado por la dueña de producto |
| Estado | Aprobado para implementación |
| Idioma | Español |

---

## Resumen de decisiones de producto (dueña)

1. **Atención general arranca supervisada**: cada respuesta a un cliente no-VIP pasa por aprobación/corrección de la dueña (igual que los VIP), hasta validar tono y estilo. El modo automático para atención queda fuera de alcance (postergado).
2. **Identidad**: la misma Diana, versión servicio: cálida y profesional, **sin coqueteo**, sin contenido íntimo/explícito.
3. **Flujo con guion**: el primer script de bienvenida sigue enviándose en automático (promo existente). Después, el sistema **identifica la intención** del cliente y responde con el guion correspondiente: precios, diferencias entre niveles, proceso de suscripción, datos de pago.
4. **Reglas duras**: no existe contacto personal ("¿dónde te puedo ver?" → servicio inexistente). No se deriva a terceros: **Diana es la única que atiende** y controla todos los aspectos de su negocio.
5. **Límite**: **20 mensajes del cliente por día por chat**, se reinicia el día siguiente (zona horaria `America/Mexico_City`).
6. **Sin entrega de contenido automática**: el bot guía hasta el pago; la entrega de contenido la hace la dueña manualmente (el bot avisa por DM cuando detecta intención/confirmación de pago).
7. **Zona gris aplica a atención**: si algo no se sabe, se consulta a la dueña (igual que VIP). Nunca inventar, nunca derivar.

---

## 1. Propósito de esta Fase

Convertir el sistema en un **asistente permanente de atención al cliente general**: cualquier persona que escriba al negocio por Telegram Business (no-VIP) recibe atención con la identidad Diana en versión servicio, primero con el script promocional automático existente y luego con respuestas guionadas, supervisadas por la dueña, con límite diario por chat y consulta a la dueña ante incertidumbre (zona gris).

Principios rectores (heredados y extendidos):

1. Un solo pipeline cognitivo; **no se duplica el sistema**. El canal (VIP / Atención) se decide una vez, de forma determinista, en la puerta de entrada.
2. Todo el comportamiento nuevo de Fase 4 está detrás del flag `FEATURE_GENERAL_MODE_ENABLED` (default `false`). Flag apagado → comportamiento idéntico al de hoy.
3. Anti-contaminación total entre canales: memoria, ejemplos y aprendizaje de atención **nunca** tocan memoria/banco VIP, y viceversa.
4. Diana atiende todo: el bot nunca dice "te comunico con alguien más". Ante desconocimiento → zona gris (consulta a la dueña), nunca inventar.
5. El Director sigue siendo 100 % determinista; el Behavior Engine sigue fuera de la cognición.

---

## 2. Alcance de la Fase 4

### 2.1 Dentro de alcance

| ID | Área |
|---|---|
| F4-01 | Flag `FEATURE_GENERAL_MODE_ENABLED` + puerta de entrada: no-VIP entra al pipeline con canal `atencion` |
| F4-02 | Límite diario de 20 mensajes del cliente por chat (reinicio diario, `America/Mexico_City`) |
| F4-03 | Entrega supervisada para atención (aprobación/corrección de la dueña, igual que VIP) |
| F4-04 | Perfil de canal "Atención" en el catálogo de persona: identidad, estilo, políticas (guiones) |
| F4-05 | Flujo post-promo: identificación de intención y respuesta con guion (precios, diferencias, suscripción, pago) |
| F4-06 | Zona gris para atención (consulta a la dueña, freeze, timeout) |
| F4-07 | Notificación a la dueña por DM ante intención/confirmación de pago (entrega manual pendiente) |
| F4-08 | Anti-contaminación de aprendizaje entre canales; trazabilidad de turns de atención |
| F4-09 | Migración de esquema 018: `channel_type` en persona_versions + tabla de límite diario |

### 2.2 Fuera de alcance (postergado)

| ID | Exclusión |
|---|---|
| F4-O1 | Modo autónomo para atención (respuesta sin aprobación). La infraestructura lo permite; se habilita solo si la dueña lo decide tras validar el tono |
| F4-O2 | Entrega automática de contenido al cliente (la hace la dueña manualmente) |
| F4-O3 | Recontacto/promo proactiva para clientes generales (la promo de bienvenida ya existe; recontacto de no-VIPs queda fuera) |
| F4-O4 | Multi-tenant, otros canales (WhatsApp, etc.) |
| F4-O5 | CRM, tickets, historial de clientes generales más allá del historial de chat existente |
| F4-O6 | Drift de estilo / calibración para el canal atención (la muestra de drift sigue usando solo canal VIP) |

---

## 3. Concepto: perfil de canal

El sistema pasa de "una persona global" a **un perfil por tipo de chat**. El perfil se resuelve una vez por turno, en la capa de aplicación, y se inyecta como contexto al pipeline (el pipeline cognitivo no cambia).

| Aspecto | Canal VIP | Canal Atención (`atencion`) |
|---|---|---|
| Determinación | VIP permitido (auth) | no-VIP + flag general ON |
| Identidad | Diana (actual) | Diana versión servicio |
| Estilo | Cálida, cercana, coqueta permitida | Cálida-profesional, sin coqueteo, sin contenido íntimo |
| Políticas | Doctrina VIP actual | Guiones de venta/soporte + reglas duras |
| Memoria | Memoria por VIP (`memories`) | Solo historial de chat por `chat_id` (sin `memories`) |
| Entrega | Supervisada / autónoma por VIP | **Supervisada** (F4-03) |
| Límite | Sin límite diario | 20 mensajes/día/chat (F4-02) |
| Zona gris | Consulta a la dueña | Consulta a la dueña (F4-06) |
| Aprendizaje | Banco de ejemplos VIP | Marcado `channel_type=atencion`, jamás al banco VIP |

Regla de oro: **una sola rama determinista** — en la puerta (AuthMiddleware) se decide `vip_id` + `channel_type`, y el resto del turno usa el perfil correspondiente.

---

## 4. Puerta de entrada y feature flag

### REQ-ATN-01 — Flag general
- Nueva flag en `Settings`: `feature_general_mode_enabled` / env `FEATURE_GENERAL_MODE_ENABLED`, **default `false`**.
- Con la flag ON, los no-VIP pasan al pipeline con `channel_type="atencion"` (sin `vip_id`, igual que el bypass actual de training mode pero permanente y con perfil).
- El toggle manual `training_mode_enabled` (system_config) queda **deprecado** para producción: si ambos están ON, gana el canal `atencion`. El toggle se mantiene solo para pruebas manuales (no se elimina en esta fase).

### REQ-ATN-02 — Decisión en la puerta (AuthMiddleware)
- VIP permitido → `vip_id` + `channel_type="vip"` (flujo actual, sin cambios).
- no-VIP + flag ON → `channel_type="atencion"`, sin `vip_id`; continúa al pipeline (reutilizar el camino que hoy usa training mode).
- no-VIP + flag OFF → comportamiento actual (promo si aplica, luego drop).
- El orden de chequeos: sandbox → VIP → general → promo → drop.

---

## 5. Límite diario de mensajes (20/día/chat)

### REQ-ATN-03 — Contador diario
- Solo aplica a chats de canal `atencion` (no-VIP).
- Se cuentan **mensajes del cliente** (no las respuestas del bot) por `chat_id` y día local (`America/Mexico_City`).
- Alcanzado el tope (20): el bot envía **una única respuesta de cierre por día** (plantilla fija, ej. "¡Hola! Por hoy ya cubrimos todo, si necesitas algo más escríbeme mañana 😊") y los siguientes mensajes del día se ignoran (drop silencioso con log).
- El contador se reinicia al cambiar el día local. Sin reinicio por inactividad (decisión de producto).

### REQ-ATN-04 — Persistencia
- Nueva tabla `daily_message_limits` (o equivalente) con clave única `(chat_id, fecha_local)` y columna `count`.
- Upsert atómico por turno de cliente. La consulta al superar el tope debe ser barata (índice por `chat_id`).
- El conteo y el corte son deterministas; nunca dependen del LLM.

---

## 6. Entrega supervisada para atención

### REQ-ATN-05
- La entrega del canal `atencion` es **supervisada** en esta fase: el turno produce un borrador → va a la DM de la dueña (aprobación/corrección) → solo se envía al cliente tras aprobar (flujo exacto del VIP supervisado actual).
- El modo de entrega del perfil se modela como **configuración del perfil** (no un flag global nuevo): `delivery_mode="supervised"` para atención en esta fase. El mecanismo para futuro `autonomous` ya existe (decisor + entrega autónoma) y no se toca.
- El freeze (congelación por consulta de zona gris) aplica igual que en VIP.

---

## 7. Perfil de canal "Atención" (contenido)

### REQ-ATN-06 — Catálogo de persona por canal
- `persona_versions` gana columna `channel_type` (`vip` | `atencion`), con **una versión activa por canal** (la constraint `uq_persona_versions_active` pasa a ser por `(channel_type, is_active)`).
- `PersonaCatalogProvider.get_catalog()` recibe el canal y devuelve la versión activa de ese canal; fallback al seed estático correspondiente.
- El panel de persona existente (`/persona`) permite gestionar ambos canales (selector de canal en la pantalla).

### REQ-ATN-07 — Perfil semilla `atencion` (contenido mínimo)
- **Persona**: Diana, creadora de contenido y dueña del negocio; atiende personalmente a todos. Cálida, clara, profesional. Sin coqueteo, sin contenido explícito, sin historia personal íntima (no comparte hechos del Diván con clientes generales).
- **Reglas de estilo**: respuestas cortas y directas de servicio; sin apodos de cariño; sin risa forzada; sin promesas de contenido; máximo 2-3 líneas; español natural (las reglas anti-slang/groserías globales aplican).
- **Políticas (doctrina de atención)** — mínimo semilla:
  - `precios`: precios en pesos mexicanos (reutilizar contenido del catálogo HTML de promo).
  - `diferencias_niveles`: comparativa entre niveles (qué incluye cada uno).
  - `suscripcion`: proceso paso a paso para suscribirse.
  - `datos_pago`: métodos de pago y cómo confirmar.
  - `no_contacto_personal`: no existe el contacto personal/citas ("dónde te puedo ver" → servicio inexistente; respuesta cálida y firme, sin inventar alternativas).
  - `no_contenido_hasta_pago`: el contenido se entrega después del pago; el bot guía el pago y avisa a la dueña; nunca envía contenido.
  - `unica_atencion`: Diana maneja todo; prohibido derivar a terceros o decir "eso lo ves con alguien más". Si no se sabe → zona gris.
  - `fuera_alcance`: temas fuera del negocio → respuesta cálida sin inventar, redirigir a lo que sí ofrece.
- Las policies viven en el mismo mecanismo existente (doctrina por tema). Los guiones son doctrina, no few-shots (mandatory instruction blocks).

### REQ-ATN-08 — Reglas duras de seguridad
- El perfil `atencion` **nunca** emite contenido explícito/sexual ni material del canal VIP (misma garantía que el freeze/forbidden actual, verificable en tests).
- `forbidden_keywords` y el freeze aplican a ambos canales.

---

## 8. Flujo post-promo e identificación de intención

### REQ-ATN-09 — Secuencia completa (canal atención)
1. Cliente no-VIP escribe → trigger de promo (existente) → se envía el script de bienvenida **en automático** (sin cambios).
2. El siguiente mensaje del cliente entra al pipeline con perfil `atencion`.
3. El pipeline **identifica la intención** con los mecanismos existentes (comprensión del Analista + selección de doctrina del Planner): pago, diferencias, suscripción, precios, contacto personal, fuera de alcance, o no-clasificable.
4. El Generador produce el borrador usando la policy/guion correspondiente (los guiones son doctrina; no se construye un clasificador nuevo).
5. El borrador va a la DM de la dueña (supervisado) → aprobación → Behavior Engine → envío.

### REQ-ATN-10 — Anti-repetición
- Si el cliente insiste con la misma pregunta después de la respuesta, el pipeline puede reutilizar la misma doctrina sin re-consultar (comportamiento del flujo de zona gris existente). No hay bucles de repetición de guiones en el mismo turno.

---

## 9. Zona gris para atención / Diana única atención

### REQ-ATN-11
- Cuando el pipeline no dispone de doctrina para la pregunta (sin policy aplicable), el canal `atencion` abre **consulta de zona gris** a la dueña (mecanismo existente: `consult_doctrine`, freeze del chat, DM `g:` con respuesta → regen → aprobación; timeout con `g:use_draft`).
- El borrador de zona gris **no se envía** al cliente hasta que la dueña responda o venza el timeout (idéntico al VIP).
- Prohibido en ambos canales: inventar, derivar, o responder "no sé, pregunta a otro".
- Métrica: la repetición de zona gris (existente) aplica también a atención para detectar políticas faltantes.

---

## 10. Notificación de pago

### REQ-ATN-12
- Cuando el turno de atención detecta intención/confirmación de pago (doctrina `datos_pago` activada o comprensión del cliente indicando pago realizado), se envía un DM a la dueña: "Cliente X (chat_id) está en proceso de pago / confirmó pago — entrega manual pendiente".
- Reutilizar el notifier existente; evento trazable en logs.
- La notificación es informativa: no cambia el flujo del turno (sigue supervisado).

---

## 11. Anti-contaminación y aprendizaje

### REQ-ATN-13
- Los turns del canal `atencion` se marcan con `channel_type="atencion"` (pipeline_traces y tablas de turno).
- Ejemplos/learning de atención **nunca** se promueven al banco de ejemplos VIP (el staging actual queda restringido por canal).
- El canal atención **no** usa `memories` (memoria por VIP); usa solo `message_history` por `chat_id` (ya existente) y la doctrina de atención.
- La calibración de umbrales y el drift de estilo siguen usando **solo muestras del canal VIP** (F4-O6) para no contaminar la medición con el estilo de servicio.

---

## 12. Trazabilidad y métricas

### REQ-ATN-14
- Los turns de atención son trazables igual que los VIP (`/turnos`, `/traza` incluyen `channel_type`).
- Métricas existentes que filtran por VIP quedan sin cambios; se agrega (mínimo) un conteo de turns de atención por día y de tope de límite alcanzado (log + métrica opcional).

---

## 13. Cambios de esquema (migración 018)

| Cambio | Detalle |
|---|---|
| `persona_versions.channel_type` | text NOT NULL default `'vip'`; constraint de activo por `(channel_type, is_active)` |
| `daily_message_limits` | `chat_id bigint`, `fecha_local date`, `count int`, PK/única `(chat_id, fecha_local)` |
| Seed del perfil `atencion` | Versión inicial del catálogo de atención (persona + estilo + policies) |

Downgrade: drop de la tabla de límites y de la columna `channel_type` (con re-seed del comportamiento activo VIP).

---

## 14. Límites de módulo (cumplimiento AGENTS.md v1.3)

- La decisión de canal vive en **application/ y telegram/middlewares** (AuthMiddleware) — nunca en cognitive/.
- Cognitive Core recibe el perfil como dato; no decide el canal.
- Behavior Engine no cambia de interfaz; solo recibe config del perfil.
- Learning (staging) filtra por `channel_type`; jamás promueve cruzado.
- Jobs no ejecutan lógica cognitiva (regla vigente).
- Purity gates existentes se mantienen (cognition sin aiogram, etc.).

---

## 15. Criterios de aceptación (checklist)

- [ ] Flag OFF → comportamiento idéntico al actual (suite completa verde).
- [ ] Flag ON + no-VIP → el turno corre con canal `atencion`, perfil de atención, supervisado.
- [ ] Tope 20/día: el mensaje 21 recibe la plantilla de cierre (una vez) y luego drop silencioso; el contador se reinicia al día siguiente local.
- [ ] Promo de bienvenida automática intacta; el mensaje posterior entra al pipeline.
- [ ] Intención de pago → borrador con guion de pago + DM a la dueña.
- [ ] "¿Dónde te puedo ver?" → respuesta de política `no_contacto_personal` (sin inventar).
- [ ] Pregunta sin doctrina → zona gris (freeze + DM `g:`), nunca inventa ni deriva.
- [ ] Ningún ejemplo de atención en el banco VIP (test de anti-contaminación).
- [ ] Drift de estilo solo con muestras VIP.
- [ ] Unit + e2e (FakeLLM) verdes; purity gates verdes.

---

## 16. Decisiones abiertas / pendientes

1. **Plantilla exacta del cierre de límite diario** (la dueña la confirma o ajusta en la primera revisión).
2. **Zona horaria del corte diario**: se asume `America/Mexico_City` (la del sistema); confirmar si el negocio quiere otro corte.
3. **Tono del perfil de atención**: la primera tanda de aprobaciones supervisadas servirá para afinar las reglas de estilo (iteración con la dueña).
4. **Actualización de AGENTS.md** (mapa de módulos y flujos) y de `REQUERIMIENTOS.md`/`README.md` cuando la Fase 4 quede implementada (tarea de cierre).
