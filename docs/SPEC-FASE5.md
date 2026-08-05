# SPEC-FASE5.md — Perfil de VIP con Memoria (backfill + mantenimiento) — v1.0

Diana Business Bot / Sistema de Automatización de Chats VIP

| Campo | Valor |
|---|---|
| Nivel | Contrato de diseño e implementación para la Fase 5 |
| Basado en | SPEC-FASE4.md v1.0 + REQUERIMIENTOS.md v2.1 + SPEC-FASE2.md v2.1 + SPEC-FASE3.md v3.0 + AGENTS.md v1.3 |
| Audiencia | Ingeniería (implementación con DeepSeek en terminal; revisión posterior) |
| Versión | 1.0 — Borrador de diseño aprobado por la dueña de producto |
| Estado | Aprobado para implementación |
| Idioma | Español |

---

## Contexto: los dos caminos de la información

| Camino | Tabla | Contenido | Estado real |
|---|---|---|---|
| **Historial crudo** | `message_history` | Transcripción de chat: `chat_id`, `role`, `text`, `timestamp` (importada por Telethon al registrar un VIP) | ✅ Funciona — 1.015+ mensajes |
| **Memoria procesada** | `memories` | Conocimiento derivado del VIP: hechos, preferencias, datos personales (búsqueda semántica por `vip_id`) | ⚠️ **Vacía (0 filas) — no existe escritor** |

Esta Fase construye el **puente**: leer el historial crudo, convertirlo en ficha del VIP (memoria procesada) y mantenerla al día.

Estado actual de `memories` (ya existente, sin cambios de estructura mayores):

| Columna | Tipo | Uso |
|---|---|---|
| `id` | uuid | PK |
| `vip_id` | uuid FK → `vips` | Alcance por VIP (anti-contaminación BR-15) |
| `embedding` | vector(384) | Búsqueda semántica (índice HNSW existente) |
| `content` | jsonb | Contenido de la memoria (estructura libre por fila) |
| `category` | text | **Tipo de sección** (identidad / preferencias / comercial / limites / sensible / perfil) |
| `confidence` | real | Nivel de confianza de la extracción |

El retriever (`MemoryRetriever`, cognitive/retrievers/memory.py) ya consulta por similitud filtrada por `vip_id` (umbral 0.75, límite 5). Solo falta **quién escribe**.

---

## Resumen de decisiones de producto (dueña)

1. El perfil por VIP se construye **una vez (backfill)** leyendo el historial completo del chat (importado por Telethon) y que el LLM extraiga la ficha estructurada. En algunos VIPs la ficha saldrá rica, en otros casi vacía — es aceptable.
2. Después, el perfil se **mantiene solo** tras cada conversación (extracción post-turno incremental).
3. **Control de la dueña**: los datos **sensibles** (salud, familia, dinero, ubicación, trabajo) entran como candidatos que la dueña aprueba; lo trivial se agrega solo.
4. La ficha es **visible y editable** desde el panel de la dueña (espacio de datos/notas por VIP).
5. Nada de esto se comparte con el canal de atención (Fase 4): la memoria es exclusiva de VIPs.
6. La feature flag `FEATURE_MEMORY_ENABLED` (ya activada) es la llave maestra: apagada → comportamiento idéntico al actual (memoria no se escribe ni se lee).

---

## 1. Propósito de esta Fase

Dar al bot **conocimiento real de cada VIP**: quién es, qué le gusta, cómo prefiere que le hablen, qué compró, qué temas evitar. Hoy ese conocimiento está enterrado en el historial crudo y el bot no lo usa. Con esta Fase, el bot consulta la ficha del VIP en cada conversación (personalización real) y la dueña puede verla y corregirla.

Principios rectores:

1. **La memoria es por VIP y solo de ese VIP** (BR-15): toda escritura y lectura filtra por `vip_id`.
2. **Extracción post-turno, nunca durante el pipeline de decisión** (regla de AGENTS.md): el aprendizaje corre después del turno.
3. **Control humano en lo sensible**: hechos delicados → candidato → aprobación de la dueña. Lo trivial → auto.
4. **Anti-contaminación**: la memoria del VIP no se mezcla con el banco de ejemplos ni con el canal de atención.
5. **Trazabilidad**: cada fila de memoria sabe de qué turno salió y quién la aprobó.

---

## 2. Alcance de la Fase 5

### 2.1 Dentro de alcance

| ID | Área |
|---|---|
| F5-01 | Backfill del perfil: historial (`message_history`) → LLM → ficha por secciones en `memories` |
| F5-02 | Estructura de ficha con secciones fijas (`category`) y perfil completo (`category='perfil'`) |
| F5-03 | Disparo del backfill: comando de la dueña + automático al registrar VIP nuevo (tras el seed de Telethon) |
| F5-04 | Mantenimiento post-turno: extracción incremental tras cada turno terminado |
| F5-05 | Control de la dueña: candidatos de memoria sensible (aprobación/descarte desde el DM) |
| F5-06 | Vista y edición de la ficha en el panel de VIP (existente) |
| F5-07 | Dedup: no repetir hechos ya conocidos (similitud semántica) |
| F5-08 | Manejo de historial largo (paginación por ventanas de mensajes) |
| F5-09 | Migración 022: columnas `status` y `source_turn_id` en `memories` |
| F5-10 | Anti-contaminación y trazabilidad (testeo explícito) |

### 2.2 Fuera de alcance (postergado)

| ID | Exclusión |
|---|---|
| F5-O1 | Memoria/perfil para el canal de atención (Fase 4): los no-VIP usan solo historial por chat, nunca `memories` |
| F5-O2 | Auto-promoción sin control: todo lo sensible pasa por la dueña |
| F5-O3 | Perfil multi-idioma / multi-tenant |
| F5-O4 | Regeneración completa automática del perfil (solo backfill puntual + incremental) |
| F5-O5 | Integración con Honcho u otro sistema externo de memoria |

---

## 3. La ficha del VIP: estructura

Cada VIP tiene una **ficha** compuesta por secciones. Cada sección es una fila de `memories` con su `category`, embedding del texto y contenido jsonb. Además, una fila `category='perfil'` guarda la ficha completa en un solo JSON (para vista/edición en el panel y para el backfill idempotente).

### REQ-MEM-01 — Secciones fijas (vocabulario de `category`)

| `category` | Qué contiene | Ejemplos |
|---|---|---|
| `identidad` | Datos personales estables | nombre, ciudad, familia, trabajo, estudios |
| `preferencias` | Tono y temas que le funcionan | "responde mejor al tono juguetón", "le gusta hablar de viajes", "evitar temas de salud" |
| `comercial` | Historial de compra e intereses | niveles que tiene, intereses de contenido, frecuencia |
| `limites` | Temas a evitar / límites explícitos del VIP | "no mencionar a su esposa", "no hablar de política" |
| `sensible` | Datos delicados (requieren aprobación de la dueña) | salud, finanzas, ubicación exacta, relaciones |
| `perfil` | La ficha completa en un solo JSON (vista/edición) | documento de la sección 3.1 |

### REQ-MEM-02 — Formato de la fila de sección

```json
{
  "texto": "Al VIP le gusta viajar; mencionó un viaje a CDMX en marzo.",
  "tipo": "hecho",
  "confianza": 0.9,
  "fuente": "turno | backfill",
  "turno_id": "uuid | null",
  "aprobado_por": "owner | auto | null"
}
```

- `embedding` = embedding del campo `texto`.
- `confidence` (columna real) = confianza del LLM en el hecho.
- `status` (columna nueva, ver REQ-MEM-09): `auto` | `pending_owner` | `approved`.

### REQ-MEM-03 — Perfil completo (category='perfil')

```json
{
  "vip_id": "uuid",
  "secciones": {
    "identidad": ["..."],
    "preferencias": ["..."],
    "comercial": ["..."],
    "limites": ["..."],
    "sensible": ["..."]
  },
  "generado_el": "ISO",
  "actualizado_el": "ISO",
  "fuente": "backfill | incremental",
  "version": 1
}
```

- El backfill es **idempotente**: regenerar el perfil reemplaza la fila `category='perfil'` y las secciones derivadas (mismo VIP), sin duplicar.
- El panel lee/edita esta fila; la edición manual de la dueña **gana** sobre lo automático (la fila editada no se pisa en el próximo mantenimiento; se marca `manual_edit=true`).

---

## 4. Backfill del perfil (inicial)

### REQ-MEM-04 — Fuente y proceso
1. Entrada: historial de `message_history` del `chat_id` del VIP, cronológico (reutilizar `rows_to_recent_messages`).
2. Si el historial es corto o inexistente (VIP recién registrado): se dispara primero el seed de Telethon existente (`schedule_seed_for_new_vip`) y el backfill espera a que haya mensajes (o se ejecuta bajo demanda de la dueña).
3. Construcción del transcripto: `Diana: ...` / `VIP: ...` con `timestamp` (los marcadores de multimedia "[nota de voz]" etc. ya están en el texto).
4. **Historial largo**: se pagina en ventanas (por ejemplo 200 mensajes por llamada) con un prompt de extracción acumulativa: cada ventana produce hechos; el último paso consolida/deduplica.
5. El LLM devuelve JSON estructurado (usar `generate_structured` existente) con las secciones de REQ-MEM-01.
6. Guardado: filas por sección (embedding + content) + fila `perfil`. Los hechos de `sensible` nacen con `status='pending_owner'`; el resto `auto`.
7. Resultado: notificación a la dueña ("Perfil generado para {VIP} — N hechos, M requieren tu aprobación") y log trazable.

### REQ-MEM-05 — Disparo
- Comando de la dueña en el DM: `/perfil <vip>` (o acción en el panel de VIP): genera/regenera el perfil de ese VIP bajo demanda.
- Automático: al **registrar un VIP nuevo** (tras el seed de historial), se agenda el backfill.
- **Decisión de producto (2026-08-05)**: TODOS los VIPs se perfilan — no hay exclusión/opt-out por VIP. El historial completo se extrae y de ahí se arma el perfil (el contenido habitual son gustos/preferencias; los datos personales tipo teléfono/dirección son raros).
- **Cuidado de la cuenta de Telegram (no oficial)**: el flujo de extracción replica el patrón de la v1 (`repos/diana/services/history_backfill.py`):
  - Cola persistente de perfiles pendientes + lock global → **un VIP a la vez** (nunca extracciones concurrentes).
  - **Timer entre VIPs**: `BACKFILL_INTERVAL_SEC` (v1 = 3600 s = 1 hora; configurable) entre el fin de un VIP y el inicio del siguiente.
  - **Conversaciones largas partidas por turnos**: si el historial supera el tamaño de ventana, se procesa por turnos (200 msgs / 12K chars) y **al terminar la serie de turnos de un VIP se espera el intervalo antes del siguiente**.
- Un job de "perfiles pendientes" (bajo demanda, NO en cada arranque de forma agresiva; puede encolar al arranque como v1 con `enqueue_missing_vips`): procesa VIPs con historial nuevo y sin perfil. Nunca corre durante el pipeline de turnos.

### REQ-MEM-06 — Costo y límites
- El backfill es una operación puntual con costo de LLM (1+ llamadas por VIP según longitud). Se ejecuta en **cola de a uno** (sin saturar).
- `VIP_HISTORY_SEED_LIMIT` existente marca el tope de mensajes importados por el seed; el backfill del perfil usa **todo** el historial disponible en `message_history` (no re-extrae de Telegram).
- El espaciado protege la cuenta (extracción Telethon) y acota el costo LLM del backfill.

---

## 5. Mantenimiento post-turno (incremental)

### REQ-MEM-07 — Extracción tras el turno
- Se ejecuta en el **post-turno** (junto al LearningService de trazabilidad existente, que no se modifica), solo para turns terminales y no-sandbox, solo si `FEATURE_MEMORY_ENABLED`.
- Entrada: mensajes del turno (VIP + borrador aprobado/enviado).
- El LLM extrae hechos nuevos candidatos (mismo esquema de REQ-MEM-02), con instrucción de **no repetir** lo ya existente en la ficha (se le pasa un resumen de la ficha actual).
- Clasificación automática de sensibilidad: si el hecho toca salud, familia, dinero, ubicación, relaciones → `pending_owner`; si es trivial/preferencia → `auto`.

### REQ-MEM-08 — Dedup
- Antes de insertar, comparar similitud semántica (pgvector) contra las filas del mismo VIP: si supera umbral (0.85) y la sección coincide, se descarta el duplicado o se fusiona (actualizar `texto` si aporta más detalle).
- Los hechos idénticos nunca se duplican; el perfil completo se re-sincroniza.

---

## 6. Control de la dueña (candidatos sensibles)

### REQ-MEM-09 — Columnas nuevas en `memories` (migración 022)
- `status` text NOT NULL default `'auto'` (`auto` | `pending_owner` | `approved` | `discarded`).
- `source_turn_id` uuid NULL (trazabilidad del turno que originó el hecho).
- Índice por `(vip_id, status)`.

### REQ-MEM-10 — Flujo de aprobación
- Los hechos `pending_owner` aparecen en el DM de la dueña (reutilizar el patrón de aprobación de staging de ejemplos existente): lista con Aprobar / Descartar por hecho.
- Aprobado → `approved` (visible para el retriever). Descartado → `discarded` (no visible). Pendiente → **no se inyecta al contexto** del bot hasta aprobación.
- La dueña también puede editar el texto del hecho antes de aprobarlo.
- Las filas `auto` son visibles de inmediato (preferencias triviales).

---

## 7. Consulta en runtime (sin cambios de interfaz)

### REQ-MEM-11
- El `MemoryRetriever` existente sigue igual: recibe el turno y la comprensión, consulta por similitud filtrada por `vip_id` (umbral 0.75, límite 5).
- Ahora devuelve datos reales. Solo se agrega: excluir filas `pending_owner`/`discarded` (no visibles hasta aprobación).
- El planner/contexto puede pedir secciones específicas si la comprensión lo sugiere (mejora opcional: filtrar por `category` cuando el tema lo amerita, ej. tema "viajes" → preferencias/identidad).

---

## 8. Anti-contaminación y trazabilidad

### REQ-MEM-12
- Toda escritura/lectura de `memories` filtra por `vip_id` (BR-15 ya vigente en el retriever; se extiende al escritor).
- El canal `atencion` (Fase 4) **nunca** toca `memories`: usa solo `message_history` por chat.
- Los ejemplos del banco (`examples`) y la memoria (`memories`) son mundos separados (principio vigente).
- Trazabilidad: cada fila tiene `source_turn_id` + `aprobado_por`; la ficha tiene `generado_el`/`actualizado_el`.
- Tests explícitos: (a) el perfil del VIP A no aparece en consultas del VIP B; (b) los hechos `pending_owner` no se inyectan; (c) el canal de atención no lee memoria.

---

## 9. Cambios de esquema (migración 022)

| Cambio | Detalle |
|---|---|
| `memories.status` | text NOT NULL default `'auto'` |
| `memories.source_turn_id` | uuid NULL (sin FK dura, referencia blanda a `turns`) |
| Índice | `(vip_id, status)` |
| Seed | Ninguno (la memoria se llena por backfill; la tabla sigue vacía hasta entonces) |

Downgrade: drop de columnas nuevas e índice.

---

## 10. Límites de módulo (cumplimiento AGENTS.md v1.3)

- El **escritor** de memoria vive en `application/` (servicio de extracción) y `learning/` (post-turno) — nunca en `cognitive/` ni `behavior/`.
- `cognitive/` solo **lee** memoria vía retriever (sin cambios de interfaz).
- El LLM de extracción usa el mismo `LLMProvider` (generate_structured); el prompt de extracción es dato del servicio, no doctrina del bot.
- Learning se ejecuta **solo post-turno** (regla vigente); el backfill es un job/service bajo demanda que **delega** en el servicio de aplicación, nunca lógica cognitiva en jobs.
- Purity gates y serialización por chat vigentes.

---

## 11. Criterios de aceptación (checklist)

- [ ] Backfill: comando `/perfil <vip>` genera la ficha (secciones + perfil completo) desde `message_history`; idempotente (regenerar no duplica).
- [ ] Al registrar un VIP nuevo con historial, el perfil se agenda y se genera.
- [ ] Historial largo: paginación sin cortar el transcripto ni exceder el límite del modelo.
- [ ] Post-turno: tras un turno aprobado, se extraen hechos nuevos; dedup no duplica.
- [ ] Sensibles: nacen `pending_owner`, no se inyectan al contexto; aprobar/descartar/editar desde el DM funciona.
- [ ] El panel muestra la ficha completa por VIP y permite editarla; la edición manual no se pisa.
- [ ] `memories` deja de estar vacía para VIPs con historial (verificable en DB).
- [ ] Anti-contaminación: tests de aislamiento entre VIPs, entre canales, y de `pending_owner` invisible.
- [ ] Flag OFF → comportamiento idéntico al actual (suite completa verde).
- [ ] Unit + e2e (FakeLLM) verdes; purity gates verdes.

---

## 12. Decisiones abiertas / pendientes

1. **Definición de "sensible"**: lista inicial = salud, familia, dinero/pagos, ubicación, relaciones. La dueña puede ampliarla/ajustarla en la primera revisión.
2. **Umbral de dedup**: 0.85 propuesto (similitud coseno); se calibra con datos reales en revisión.
3. **Ventana de paginación del backfill**: 200 mensajes por llamada propuesto; ajustable según costo/latencia.
4. **Regeneración completa vs. incremental**: si un VIP cambia mucho, la dueña puede forzar backfill (`/perfil` de nuevo). La regeneración automática completa queda fuera de alcance.
5. **Notificación de perfil generado**: confirmar formato del DM de resumen (N hechos, M pendientes).
6. **Actualización de docs** (README, AGENTS.md) y de la tabla de flags al cierre de la Fase (tarea de cierre).
7. **Privacidad del backfill (nota de diseño, fix round F3 — hallazgo security-auditor)**: durante el backfill, el historial completo del chat del VIP se envía al proveedor LLM externo (DeepSeek) para la extracción, tal como define REQ-MEM-04 (comportamiento by-design). Controles actuales: ventana de 200 mensajes + tope de 12K caracteres por ventana y líneas truncadas a 400 caracteres (fix M2), y ninguna escritura de datos fuera de `memories`. **Pendientes para Pool 2+**: (a) flag de exclusión por VIP (opt-out del backfill), (b) evaluar redacción/masking de PII previo al envío cuando no sea necesaria para la extracción, (c) documentar retención y evaluar modelo local/on-prem para extracción sensible, (d) confirmar acuerdo de procesamiento de datos con el proveedor.
