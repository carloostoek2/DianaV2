
## Anexo C — Contrato detallado del Planificador Cognitivo

### C.1 Responsabilidad exacta
Responde: *"¿qué conocimiento recuperar?"*. Es determinista, no LLM — una función pura de la Comprensión. No decide *cómo* usar el conocimiento (eso es el Constructor de Contexto) ni *si* el turno es riesgoso (eso ya lo dijo el Analista).

### C.2 Entrada / Salida
```
PlanificadorInput  { comprension: ComprensionObject }        # Anexo A.3
PlanificadorOutput { capacidades_solicitadas: string[] }     # subconjunto de nombres de capacidad
```
Regla de mapeo (fija, sin excepción, sin LLM de por medio):
```
needs_history  = true → "knowledge.history"
needs_context  = true → "knowledge.context"
needs_memory   = true → "knowledge.memory"
needs_policy   = true → "knowledge.policy"
needs_examples = true → "knowledge.examples"
needs_schedule = true → "knowledge.schedule"   # real desde Anexo H / H9 (ScheduleRetriever + agenda
                                                 # semanal fija); ya no es half-seat / no_implementado
```

### C.3 Invariantes
- Nunca solicita una capacidad cuyo `needs_*` correspondiente sea `false` (principio de mínimo conocimiento necesario).
- Es 100% determinista: la misma Comprensión produce siempre el mismo `PlanRecuperacion`. Si esto deja de cumplirse (p. ej. alguien mete una llamada a LLM aquí "para mejorar la selección"), es un cambio de responsabilidad que debe rechazarse en revisión — ese trabajo pertenece al Analista, ampliando su clasificación, no al Planificador.
- No falla nunca por sí mismo: al ser una función pura sobre datos ya validados (la Comprensión ya pasó por A.6), no tiene camino de error propio. Si `comprension` es `null`, eso es un bug del Director invocándolo fuera de orden, no un caso a manejar aquí.

### C.4 Ejemplo
Con la Comprensión del Anexo A.4, ejemplo 4 (`needs_memory, needs_schedule, needs_examples, needs_history, needs_context = true`, `needs_policy = false`):
```json
{ "capacidades_solicitadas": ["knowledge.memory", "knowledge.schedule", "knowledge.examples", "knowledge.history", "knowledge.context"] }
```

---

## Anexo D — Contrato detallado del Constructor de Contexto

### D.1 Responsabilidad exacta
Responde: *"¿cuál es el contexto mínimo necesario para que el Generador redacte?"*. Determinista (ensambla, no razona). No genera texto de respuesta, no evalúa nada.

### D.2 Entrada
```
ConstructorInput {
  comprension: ComprensionObject
  conocimiento_recuperado: Array<{ capacidad: string, resultado: object | null }>
  voz_configurada: { persona: string, reglas_estilo: string[] }   # config de despliegue, REQ-VIP-04
}
```

### D.3 Salida
```
ContextoConstruido { prompt_final: string, bloques_incluidos: string[] }
```
`bloques_incluidos` es exactamente el subconjunto de `conocimiento_recuperado` cuyo `resultado != null` — este campo es el que luego consume el Evaluador (Anexo B.2) para saber qué tuvo disponible el Generador.

### D.4 Reglas de ensamblado (orden fijo, sin excepción)
1. Bloque de persona/voz (siempre presente).
2. Bloque de `historial` (si `knowledge.history` resolvió algo).
3. Bloque de `contexto temporal` (si `knowledge.context` resolvió algo).
4. Bloque de `memoria` (si aplica — no en MVP, stub siempre null).
5. Bloque de `política` (si aplica — no en MVP).
6. Bloque de `ejemplos` (si aplica — no en MVP).
7. El `turno_actual` al final, siempre, como lo último que el Generador lee antes de escribir.

### D.5 Invariantes
- **Nunca** incluye un bloque con `resultado = null` como sección vacía o placeholder ("Memoria: no disponible") — la sección simplemente no existe en el prompt (§3.8 del cuerpo del SPEC, REQ-NFR-07: presupuesto de prompt). Esto es fácil de romper por accidente si la implementación itera sobre *todas* las capacidades en vez de solo las resueltas — se marca explícitamente como caso de prueba obligatorio.
- No decide qué capacidades pedir (eso ya lo hizo el Planificador) ni reordena por relevancia percibida — el orden de D.4 es fijo para que el comportamiento del Generador sea comparable entre turnos.
- No trunca contenido de forma silenciosa: si el volumen total excede el límite del proveedor LLM, debe fallar explícitamente (`Turn.status = failed`, motivo `"contexto_excede_limite"`) en vez de cortar un bloque a la mitad y generar con información incompleta sin que nadie lo sepa.

### D.6 Errores
- Único camino de fallo propio: exceso de tamaño (D.5). No hay reintento automático — es una señal de que el Planificador está pidiendo demasiado o el historial configurado (`N` mensajes) es muy grande; se resuelve ajustando configuración, no reintentando el mismo turno.

---

## Anexo E — Contrato detallado del Generador

### E.1 Responsabilidad exacta
Responde: *"¿cómo respondería la dueña?"*. Es el único nodo que produce el texto final visible al VIP (antes de aprobación). No clasifica, no busca conocimiento, no evalúa su propio resultado (REQ-COG-07 — separación estricta entre quien escribe y quien juzga).

### E.2 Entrada / Salida
```
GeneradorInput  { prompt_final: string }        # de D.3, tal cual, sin modificación
GeneradorOutput { texto: string }                # texto plano; sin JSON, sin metadata
```

### E.3 Invariantes
- Temperatura/creatividad del modelo puede ser más alta aquí que en Analista/Evaluador (que buscan consistencia de clasificación) — es una decisión de tuning, no de contrato, pero se documenta porque es la única pieza del pipeline donde variabilidad es deseable en vez de riesgo.
- No tiene acceso a `PerfilEvaluacion` de intentos anteriores del mismo turno cuando hay `Regenerar` (ver §3.11 del cuerpo) — con `Regenerar` (implementado en `application/draft_variants.py`), el Generador recibe el mismo `prompt_final`, no una versión "corregida según lo que falló", salvo que se decida explícitamente lo contrario en una iteración posterior de este contrato.
- Nunca escribe directamente a ningún canal — su salida siempre pasa por Evaluador → Decisor → cola de aprobación antes de cualquier entrega (invariante de todo el modo supervisado, §3.11 y §3.13).

### E.4 Errores
- Salida vacía o solo espacios en blanco se trata como fallo de generación (reintento único, luego `failed`) — nunca se envía un borrador vacío a la cola de aprobación de la dueña.
- Sin validación de "calidad" aquí — esa responsabilidad es exclusivamente del Evaluador (Anexo B); el Generador solo valida que produjo *algo*.

---

## Anexo F — Contrato detallado del Decisor

### F.1 Responsabilidad exacta
Responde: *"¿qué acción tomar?"*. Determinista, no LLM. Es el único nodo que combina tres insumos independientes (perfil del Evaluador, modo activo, umbrales de configuración) para producir una acción — pero no juzga calidad ni clasifica: consume juicios ya hechos por otros.

### F.2 Entrada / Salida
```
DecisorInput {
  perfil: PerfilEvaluacion              # Anexo B.3
  modo_activo: "supervisado" | "autonomo"   # MVP: siempre "supervisado"
  umbrales: { seguridad_min: number, naturalidad_min: number }   # config de despliegue
}
DecisorOutput {
  accion: "aprobar" | "escalar" | "regenerar"
  razon: string
  restriccion_de_modo_aplicada: string | null
}
```

### F.3 Tabla de reglas (orden de evaluación fijo — la primera que aplica gana)

| # | Condición | Acción bruta | Filtro de modo (`supervisado`) | Acción final |
|---|---|---|---|---|
| 1 | `perfil.seguridad < umbrales.seguridad_min` | Escalar | Escalar no se filtra (nunca se envía inseguro) | **Escalar** |
| 2 | `perfil.naturalidad < umbrales.naturalidad_min` | Regenerar | Regenerar no se filtra | **Regenerar** (si está implementado en el despliegue; si no, cae a la regla 3) |
| 3 | ninguna de las anteriores | Enviar | `supervisado` reescribe "Enviar" → "Aprobar" (nunca hay envío directo) | **Aprobar** |

`restriccion_de_modo_aplicada` se llena solo cuando el filtro de modo cambió la acción bruta (siempre en la regla 3 bajo modo supervisado) — sirve como registro auditable de que el sistema *quiso* enviar directo y el modo se lo impidió, útil el día que se compare comportamiento entre modo supervisado y autónomo.

### F.4 Invariantes
- El vocabulario de acciones brutas incluye `"enviar"` porque el mismo Decisor se reutilizará en modo autónomo (REQ-NFR-14) — pero en el MVP, con `modo_activo` fijo en `"supervisado"`, esa acción nunca sale sin pasar por el filtro de la regla 3. Ningún camino de código debe poder saltarse el filtro.
- Es 100% determinista dado el mismo `DecisorInput` — igual que el Planificador (Anexo C.3), no tiene camino de error propio salvo `perfil` inválido, que ya debió fallar antes en B.6.
- No conoce el `Borrador` en sí, solo el `PerfilEvaluacion` — no puede "leer el texto y decidir por su cuenta"; toda su información pasa por la evaluación estructurada, nunca por juicio directo sobre texto libre (mantiene la separación de responsabilidades de NFR-13).

### F.5 Ejemplo
Usando el perfil del Anexo B.4, ejemplo 2 (`seguridad: 0.2`) con `umbrales.seguridad_min = 0.5`:
```json
{ "accion": "escalar", "razon": "seguridad 0.2 < umbral 0.5", "restriccion_de_modo_aplicada": null }
```

---

## Anexo G — Contrato del Turn Coordinator

### G.1 Responsabilidad exacta
Responde: *"¿este mensaje abre un turno nuevo o afecta uno existente?"*. Es el único nodo con permiso para tocar el estado de `Turn` fuera del flujo lineal del Director — actúa como guardia de concurrencia (REQ-NFR-02, REQ-VIP-06), no como parte del razonamiento.

### G.2 Entrada / Salida
```
CoordinatorInput  { chat_id: string, autor: "vip" | "dueña", evento: MensajeNormalizado }
CoordinatorOutput { turn_id: string, accion: "crear" | "reemplazar" | "descartar_mensaje_dueña" }
```

### G.3 Reglas (evaluadas bajo el lock de `chat_id`, ver G.4)
1. `autor = dueña` + hay `Turn` no terminal → ese turno pasa a `superseded`; **no se crea turno nuevo**, el mensaje de la dueña no entra al pipeline cognitivo (`accion: descartar_mensaje_dueña`).
2. `autor = vip` + hay `Turn` no terminal → ese turno pasa a `superseded`; se crea un `Turn` nuevo con el mensaje actual (`accion: reemplazar`).
3. Sin `Turn` no terminal → se crea uno (`accion: crear`).

### G.4 Invariante de concurrencia (la más crítica de todo el sistema)
Las reglas de G.3 deben ejecutarse dentro de una **sección serializada por `chat_id`** — dos mensajes casi simultáneos del mismo VIP no pueden ambos leer "no hay turno vigente" y crear dos turnos. El mecanismo concreto (lock optimista con versión, cola FIFO particionada por `chat_id`, transacción con bloqueo de fila) es libre de implementación, pero el contrato exige que **no exista ninguna ventana** en la que dos invocaciones concurrentes para el mismo `chat_id` puedan producir dos `Turn` no terminales simultáneos. Este es el único invariante de todo el SPEC marcado como no-negociable en diseño de código: cualquier PR que lo debilite "por simplicidad" debe rechazarse.

### G.5 Errores
- Si el lock no puede adquirirse en un tiempo razonable (contención extrema, poco probable con "decenas de VIP" per REQ-NFR-11), se reintenta con backoff acotado; si sigue fallando, el mensaje se encola para reproceso, nunca se descarta silenciosamente.

---

## Anexo H — Contrato del Capability Registry y los Recuperadores

### H.1 Responsabilidad exacta del Registry
Responde: *"¿qué componente concreto satisface esta capacidad?"*. Es un mapa estático `nombre_capacidad → implementación`, resuelto una vez por despliegue (config), no por turno.

```
Registry.resolve(nombre: string) → Retriever
```
Si `nombre` no está registrado → error de configuración en tiempo de arranque del sistema, nunca en tiempo de turno (fail-fast al desplegar, no al atender un VIP).

### H.2 Responsabilidad exacta de cada Retriever
Responde (cada uno): *"¿qué sabemos sobre X?"* — interfaz idéntica para todos, implementación libre.
```
Retriever.fetch(chat_id: string, comprension: ComprensionObject) → { capacidad: string, resultado: object | null, fuente: string } | null
```

### H.3 Contratos concretos del MVP

| Retriever | `resultado` cuando hay dato | `resultado` cuando no hay dato |
|---|---|---|
| `HistoryRetriever` | `{ mensajes: Array<{autor, texto, timestamp}> }`, últimos N (config) | `[]` si el chat es nuevo — nunca `null` (siempre hay *algún* historial, aunque vacío) |
| `ContextRetriever` | `{ esperando_respuesta_desde: datetime \| null, es_primer_mensaje_del_dia: boolean }` | Campos en `false`/`null` explícitos, no ausencia del objeto |
| `MemoryRetriever` (stub) | — | Siempre `null` |
| `PolicyRetriever` (stub) | — | Siempre `null` |
| `ExamplesRetriever` (stub) | — | Siempre `null` |
| `ScheduleRetriever` (real — Anexo H / H9) | `{ dia, hora_actual, tipo: "actividad"\|"respuesta_libre", actividad?\|respuesta_sugerida? }` desde agenda semanal fija (`fuente=agenda_semanal_fija`); ventanas half-open `[inicio, fin)` | Sin match de bloque → `tipo=respuesta_libre` con ancla de estilo; ya **no** es capacidad half-seat (`no_implementado`). Histórico MVP: se pedía igual y el Registry devolvía stub null — obsoleto tras H9. |

### H.4 Invariantes
- Los stubs (`Memory`, `Policy`, `Examples`) **deben** implementar la interfaz completa y registrarse igual que un Retriever real — su existencia como código real (no como "capacidad ausente") es lo que garantiza que sustituirlos en MVP+ no toque a nadie más (REQ-NFR-14). No es válido que el Planificador tenga lógica especial tipo "si la capacidad es memoria, ni la pidas" — eso rompería la sustituibilidad.
- Ningún Retriever conoce a otro ni al Constructor de Contexto — se ejecutan en paralelo/aislados; el orden de ensamblado (Anexo D.4) es responsabilidad exclusiva del Constructor de Contexto, no de los Retrievers.
- Ningún Retriever escribe estado — son de solo lectura sobre las entidades de §2.

---

## Anexo I — Contrato del Behavior Engine

### I.1 Responsabilidad exacta
Responde: *"¿cómo se actúa el mensaje ya aprobado?"*. Es el único nodo con permiso para escribir al VIP. No decide contenido, no juzga nada — ejecuta.

### I.2 Entrada / Salida
```
BehaviorInput {
  chat_id: string
  texto_final: string          # el borrador aprobado, o el texto de corrección de la dueña (§3.13)
  modo: "supervisado" | "autonomo" | "fake_delivery"   # fake_delivery reservado para sandbox futuro
}
BehaviorOutput { ok: boolean, error: string | null, resultado_entrega: ResultadoEntrega }
```

### I.3 Secuencia fija (REQ-HUM-01/02/03)
1. Espera previa configurable (nunca cero — REQ-NFR-01).
2. Marca el chat como leído.
3. Indicador de "escribiendo…" con duración proporcional a `len(texto_final)` (fórmula configurable, p. ej. `min(max_seg, base + chars/velocidad)`).
4. Envía por el canal oficial de negocio (único camino de envío permitido, §5 del cuerpo).

### I.4 Invariantes
- Verifica, justo antes del paso 4, que el `Turn` asociado **no** haya pasado a `superseded` mientras esperaba (paso 1-3 toma tiempo real; un mensaje nuevo del VIP pudo llegar mientras tanto). Si ya es `superseded`, aborta sin enviar y lo registra — este es el mecanismo que cierra el ciclo de la invariante de G.4 hasta el último paso del pipeline, no solo en la creación del turno.
- No reintenta indefinidamente ante fallo de envío (REQ-NFR-04): reintento acotado (config) solo para errores de red/API transitorios; fallos definitivos se notifican a la dueña, nunca se descartan en silencio.
- `fake_delivery` está implementado y activo en el sandbox (`FEATURE_SANDBOX_ENABLED=true`, `behavior/fake.py`); el enum lo contempla (§3.12 del cuerpo) sin necesidad de cambiar la firma de este contrato.

### I.5 Errores
- Fallo de envío (canal caído, rate limit del proveedor) → `ok: false`, `error` con motivo, `Turn.status = failed` si se agotan los reintentos configurados, notificación a la dueña con contexto suficiente para que sepa que el VIP no recibió respuesta.
