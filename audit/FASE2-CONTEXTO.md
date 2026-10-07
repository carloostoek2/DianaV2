# Fase 2 — Contexto temporal interpretado: ¿se usa, y responde como debería?

**Contrato:** C-CTX-01 (REQ-MEM-06) · **Antecedente:** `audit/INVESTIGACION-B.md` (§ContextsRepo)
**Rama:** `audit/perfiles-embeddings`. **Fecha:** 2026-10-07.
**Solo lectura sobre producción. Sin commit a `main`. Sin despliegue.**

---

## Resumen para la dueña

Diana guarda, después de cada turno, una pequeña "foto" del estado de la conversación: si quedó
esperando respuesta, si es el primer mensaje del día, qué día y a qué hora es. Esa foto es el
**contexto temporal**.

**Lo que se midió:**

| Pregunta | Respuesta |
|---|---|
| ¿La función se usa en producción? | **Sí.** Hay 21 fotos guardadas, de 4 chats, y el sistema las escribe después de cada turno. La bandera está encendida y coincide en los dos lugares donde vive |
| ¿Esa foto llega al modelo? | **Sí.** En **502 de 536 turnos** (94 %) el bloque de contexto está en el texto que recibe el modelo. En los últimos cuatro días, **todos** los turnos lo llevan |
| ¿Responde como debería? | **No del todo.** La foto llega, pero con **datos viejos de un turno anterior** que contradicen la conversación que el modelo está leyendo en ese mismo momento |
| ¿Al vencer se retira? | **Sí.** Una foto vencida no se usa: el sistema vuelve a calcular el estado desde la conversación. Verificado con prueba y sabotaje |
| ¿La búsqueda por parecido sobre estas fotos se usa? | **No.** Igual que en las fichas: está escrita y probada, y no la llama nadie |

**Qué pierde el negocio hoy:** el modelo recibe, en el 84 % de los turnos, un dato de "está esperando
respuesta" que no corresponde. En los casos medidos donde la foto decía "no espera respuesta", la
conversación sí la estaba esperando. Es información que en el mejor caso no aporta y en el peor
empuja a Diana a responder como si el cliente no hubiera escrito.

**Qué NO está roto:** el mecanismo funciona (escribe, lee, vence). El problema es **qué** se guarda en
la foto, no si se guarda.

---

## 1. ¿La función se usa en producción?

**Sí, en las dos direcciones: se escribe después de cada turno y se lee antes del siguiente.**

Escritura (`ContextStoreService.record_post_turn`, llamado desde el gancho post-turno del
orquestador, `turn_orchestrator.py:455`):

| Medición en la base real (solo lectura) | Valor |
|---|---|
| Filas en `contexts` | **21** |
| Vigentes / vencidas | **21 / 0** |
| Chats distintos | **4** |
| Filas con VIP asociado | 17 de 21 |
| Fecha de escritura, mínimo → máximo | 2026-10-06 22:35 → 2026-10-07 18:18 |
| Vida útil de cada foto | **24,00 h exactas** (todas) |
| Contenido | `{"tipo": "interpretado", "hechos": {…}}` con las 4 claves esperadas |
| Huella (embedding) | **real** en todas (ninguna en ceros) |

Lectura: el bloque llega al modelo. Medido sobre `pipeline_traces.prompt_text`:

| Medición | Valor |
|---|---|
| Turnos con `prompt_text` | 536 |
| Turnos cuyo texto al modelo incluye `knowledge.context` | **502 (94 %)** |
| 2026-10-07 | **12 de 12** |
| 2026-10-06 | **19 de 19** |
| 2026-10-05 | **7 de 7** |
| 2026-10-04 | **17 de 17** |

El bloque llega bien formado, dentro de `## Knowledge: knowledge.context`, antes del bloque de
políticas:

```
## Knowledge: knowledge.context
{
  "dia_semana": "miercoles",
  "hora_actual": "12:18",
  "is_first_message_of_day": false,
  "waiting_for_reply_since": null
}
```

**Bandera:** `FEATURE_CONTEXT_ENABLED=true` en el `.env` y `true` también en `system_config`
(coinciden). El repositorio del almacén se inyecta solo con la bandera encendida
(`composition.py:911-917`).

## 2. ¿La búsqueda por parecido sobre estas fotos se usa?

**No.** `ContextsRepo.find_by_similarity` (`repositories/contexts.py:104`) tiene como único llamador
su propia prueba unitaria (`tests/unit/infrastructure/test_contexts_repo.py:112`). No hay acceso
dinámico ni `Protocol` que la declare. Lo confirma el esquema: `contexts` **no tiene índice de
vector** (`pg_indexes` → solo `contexts_pkey`), igual que `profiles`.

La que **sí** se usa es `find_active_by_chat` — la lectura por chat vigente, que es la que alimenta el
pipeline.

## 3. ¿Responde como debería? — el hallazgo

**La foto se guarda al terminar el turno y se inyecta tal cual en el turno siguiente, incluidas dos
claves que son de "ahora mismo" y no de "lo que pasó".**

### Mecanismo

1. Diana responde al VIP. El turno termina.
2. El gancho post-turno interpreta el estado **en ese momento** y lo guarda. Como Diana acaba de
   responder, el último mensaje de la conversación es **suyo**.
3. En el turno siguiente, el lector toma la foto más reciente y **la inyecta**, refrescando solo
   `dia_semana` y `hora_actual`. Las otras dos claves quedan congeladas del turno anterior.

Es decir: `waiting_for_reply_since` y `is_first_message_of_day` — que describen el presente — viajan
siempre **un turno atrasadas**, mientras `dia_semana` y `hora_actual` sí se actualizan.

### Medición sobre turnos reales

Se tomaron los 80 turnos más recientes con bloque de contexto, se extrajo de cada uno el historial
que el modelo vio **y** el contexto que se le inyectó, y se recalculó en vivo lo que el historial
decía. (70 de los 80 tenían historial parseable.)

| Comparación | Resultado |
|---|---|
| `waiting_for_reply_since` inyectado ≠ el que corresponde al historial | **59 de 70 (84 %)** |
| … de esos, inyectado `null` y el historial sí esperaba respuesta | **30** |
| … de esos, inyectado con fecha y el historial no esperaba | **0** |
| `is_first_message_of_day` inyectado ≠ el que corresponde al historial | **15 de 70 (21 %)** |

La asimetría importa: **los 30 casos van todos en la misma dirección**. La foto dice "no hay respuesta
pendiente" cuando el último mensaje del chat es del cliente.

Es sistemático, no un caso suelto — ocurre todos los días medidos:

| Día | Turnos | Fallos `waiting_for_reply_since` | Fallos `is_first_message_of_day` |
|---|---|---|---|
| 2026-10-07 | 10 | 10 | 2 |
| 2026-10-06 | 16 | 14 | 3 |
| 2026-10-05 | 6 | 4 | 3 |
| 2026-10-04 | 17 | 17 | 2 |
| 2026-10-03 | 12 | 7 | 3 |
| 2026-10-02 | 9 | 7 | 2 |

**Ejemplo del efecto:** en el turno de 2026-10-07 18:18, el historial que el modelo leyó terminaba
con dos mensajes del cliente, y el bloque de contexto le decía al mismo tiempo
`"waiting_for_reply_since": null`. Dos afirmaciones opuestas en el mismo texto.

**Contraste honesto:** la alternativa (derivar en vivo desde el historial) es exactamente lo que el
sistema hacía antes de Fase 2, y es la que produce el valor correcto en estos 70 casos. La foto no
está enriqueciendo la decisión: la está sustituyendo por un dato peor.

## 4. ¿Al retirarse deja de usarse?

**Sí.** Una foto vencida no se lee nunca: la consulta filtra por vigencia
(`Context.expires_at > now`) y el lector cae a la derivación en vivo. Además, al insertar una foto
nueva se borran las vencidas de ese chat (limpieza oportunista), de modo que la tabla no crece.

Verificado con prueba real (§5, escenario 2) y con sabotaje (§5, S2): al quitar el filtro de
vigencia, la prueba falla y el sistema vuelve a usar la foto vencida.

## 5. Prueba E2 y sabotajes (E3)

`tests/audit/test_C_CTX_01.py`. Entra por el camino real: `build_app` + el orquestador armado
(`orchestrator.handle_vip_message`), contra Postgres real, con el pipeline completo. Solo se simula el
modelo de lenguaje (Analista y Evaluador con esquema fijo, Generador en texto). El almacén, el
escritor y el lector son los reales.

Cada escenario siembra un historial que dice lo **contrario** que la foto, para que la prueba
distinga de verdad "salió de la foto" de "salió del historial".

| # | Escenario | Qué exige | Resultado |
|---|---|---|---|
| 1 | Bandera ON + foto vigente | El bloque que recibe el modelo sale **de la foto** (valores que contradicen el historial) | ✅ |
| 2 | Bandera ON + **solo foto vencida** | El bloque sale del historial: la foto vencida **no se usa** | ✅ |
| 3 | Bandera OFF + foto vigente | El bloque sale del historial: la foto **no se lee** | ✅ |

### Sabotajes

| # | Qué se desconectó | Resultado |
|---|---|---|
| **S1** | La inyección del almacén: `composition.py:911` → `effective_context_repo = None` | **El escenario 1 FALLA**: `AssertionError: el bloque no salió del snapshot`, y el bloque mostró los valores del historial |
| **S2** | El filtro de vigencia en `find_active_by_chat` | **El escenario 2 FALLA**: `AssertionError: se siguió usando un snapshot vencido`, con los valores de la foto vencida en el bloque |

Ambos revertidos (`grep -rn SABOTAJE src/` → sin resultados; `git diff src/diana/composition.py
src/diana/infrastructure/db/repositories/contexts.py` → vacío).

## 6. Matriz de banderas

| `FEATURE_CONTEXT_ENABLED` | Efecto medido |
|---|---|
| `true` (valor actual en `.env` y `system_config`) | La foto se escribe post-turno y se lee antes del turno siguiente; el bloque lleva los valores de la foto |
| `false` | El almacén no se inyecta en el lector ni el escritor se activa: el bloque se deriva del historial, idéntico al comportamiento previo a Fase 2 |

Medido, no supuesto: es el escenario 3 de la prueba E2.

## 7. Límites de esta verificación

- **No se re-ejecutó un turno contra producción.** Las mediciones de §1 y §3 son de **solo lectura**
  sobre datos ya guardados (transacción marcada como *read only*).
- **La comparación de §3 reconstruye la derivación en vivo a partir del historial que el propio
  prompt contiene.** Es exactamente el mismo insumo y la misma función pura que usa el sistema, pero
  no es una ejecución del pipeline en ese instante.
- **No se muestra contenido de conversación**: solo claves, conteos y fechas.
- **Las 4 claves del contexto son las únicas que existen.** No hay otros campos que se puedan haber
  quedado obsoletos.
- **`find_active_by_chat` acepta un parámetro `vip_id` que no usa en la consulta**
  (`repositories/contexts.py:84-101`): el llamador lo pasa esperando un filtro por VIP que no se
  aplica. Hoy no es explotable, porque el alcance por chat ya separa a los VIP; queda como hallazgo
  menor de revisión.

## 8. Arreglo propuesto (NO aplicado)

Tres caminos, de menor a mayor:

| Opción | Qué implica | Veredicto |
|---|---|---|
| **A. Refrescar también las dos claves de presente** en el lector (dejar la foto solo para lo que sí es histórico) | Cambio chico y localizado en `retrievers/context.py`. La foto seguiría guardándose y usándose para el resto | ✅ **Recomendado** |
| **B. Leer la foto solo cuando el historial no alcanza** | Conserva el diseño de "no re-derivar", pero deja de sustituir un dato bueno por uno viejo | Razonable si se quiere mantener el sentido original de REQ-MEM-06 |
| **C. Dejar de escribir la foto** | Es la más simple, pero descarta la tabla y el requerimiento entero | ❌ Desproporcionado: el gasto ya está hecho y la foto puede servir para chats sin historial |

Se recomienda **A**, y decidirlo aparte: es un cambio de comportamiento del pipeline y no se aplicó en
esta revisión.

**Sobre la búsqueda por parecido huérfana (`ContextsRepo.find_by_similarity`):** está en la misma
situación que la de fichas. Se propone la misma decisión (eliminarla) si no hay plan de usar la
búsqueda semántica de contextos. **No se eliminó**: requiere la confirmación de la dueña, igual que en
el caso de las fichas.

## 9. Vigilante propuesto (E4)

`audit/vigilantes.sql` **V1** ya cuenta ceros en `contexts`. Falta un vigilante para el problema de
§3, que es de **contenido**, no de ceros. Consulta propuesta (solo lectura):

```sql
-- Foto vigente que contradice el historial del mismo turno: la clave "espera
-- respuesta" dice null mientras el último mensaje del chat es del cliente.
-- Alerta si aparece en más del 50% de los turnos de la ventana.
SELECT count(*) AS turnos_con_contexto_rancio
FROM pipeline_traces t
WHERE t.prompt_text LIKE '%knowledge.context%'
  AND t.prompt_text LIKE '%"waiting_for_reply_since": null%'
  AND t.created_at BETWEEN now() - interval '1 day' AND now() - interval '10 minutes';
```

Se deja como **propuesta**: calibrar el umbral requiere decidir antes la opción de §8.

## 10. Archivos tocados

| Archivo | Cambio |
|---|---|
| `tests/audit/test_C_CTX_01.py` | **Nuevo** — 3 escenarios E2 del contexto temporal |
| `audit/FASE2-CONTEXTO.md` | Este informe |

**No se tocó código de producción en esta revisión.** Los dos sabotajes se aplicaron y se revirtieron.

### Suites ejecutadas (2026-10-07)

| Suite | Resultado |
|---|---|
| `tests/unit` | **4351 passed** |
| `tests/e2e` | **233 passed** (igual a la línea base) |
| `tests/audit` | **7 passed** (2 de C-HIST-01, 2 de C-EMB-01, 3 de C-CTX-01) |
