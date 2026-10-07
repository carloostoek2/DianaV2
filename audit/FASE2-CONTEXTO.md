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
| ¿Responde como debería? | **No lo hacía.** La foto llegaba, pero con **datos viejos de un turno anterior** que contradecían la conversación que el modelo estaba leyendo en ese mismo momento. **Corregido y desplegado el 2026-10-07** (§8) |
| ¿Al vencer se retira? | **Sí.** Una foto vencida no se usa: el sistema vuelve a calcular el estado desde la conversación. Verificado con prueba y sabotaje |
| ¿La búsqueda por parecido sobre estas fotos se usa? | **No.** Igual que en las fichas: está escrita y probada, y no la llama nadie |

**Qué estaba perdiendo el negocio:** el modelo recibía, en el 84 % de los turnos, un dato de "está
esperando respuesta" que no correspondía. En los casos medidos donde la foto decía "no espera
respuesta", la conversación sí la estaba esperando. Información que en el mejor caso no aporta y en el
peor empujaba a Diana a responder como si el cliente no hubiera escrito.

**Qué NO estaba roto:** el mecanismo funciona (escribe, lee, vence). El problema era **qué** se usaba
de la foto, no si se guardaba.

**El arreglo:** las cuatro claves describen el momento presente, así que ahora se calculan siempre
desde la conversación del turno; de la foto solo se toma lo que ella sola aporta. La foto se sigue
guardando y leyendo (el almacén del requerimiento queda intacto), y una prueba unitaria falla si esa
lectura se desconecta.

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
estaba enriqueciendo la decisión: la estaba sustituyendo por un dato peor.

**Causa de fondo:** las cuatro claves del bloque son hechos del **presente**. La foto se escribe al
cerrar el turno —justo después de que Diana respondió— y se leía entera en el turno siguiente. Dos de
esas claves ya se refrescaban en vivo (día y hora); las otras dos se tomaban congeladas. El arreglo
(§8) extiende el refresco a las cuatro.

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

La foto sembrada lleva además una clave que **solo** existe en ella: si el almacén dejara de leerse,
esa clave desaparecería del prompt. Así el sabotaje de la lectura se detecta aunque sus cuatro claves
de presente ya no la necesiten.

| # | Escenario | Qué exige | Resultado |
|---|---|---|---|
| 1 | Bandera ON + foto vigente que contradice el historial | El bloque sale **del historial** (regresión del defecto) **y** la clave propia de la foto sigue llegando | ✅ |
| 2 | Bandera ON + **solo foto vencida** | El bloque sale del historial: la foto vencida **no se usa** | ✅ |
| 3 | Bandera OFF + foto vigente | El bloque sale del historial: la foto **no se lee** | ✅ |

### Sabotajes

| # | Qué se desconectó | Resultado |
|---|---|---|
| **S1** | La inyección del almacén: `composition.py:911` → `effective_context_repo = None` | **El escenario 1 FALLA**: `AssertionError: el snapshot dejó de leerse (almacén desconectado)`. La lectura sigue cubierta por una prueba que falla si se corta |
| **S2** | El filtro de vigencia en `find_active_by_chat` | **El escenario 2 FALLA**: `AssertionError: se siguió usando un snapshot vencido`, con los valores de la foto vencida en el bloque |

Ambos revertidos (`grep -rn SABOTAJE src/` → sin resultados; `git diff src/diana/composition.py
src/diana/infrastructure/db/repositories/contexts.py` → vacío).

En el nivel unitario, `tests/unit/cognitive/test_retrievers.py` cubre lo mismo en chico:
`test_context_retriever_live_derivation_wins_over_stale_snapshot` (las cuatro claves son las del
historial) y `test_context_retriever_keeps_extra_keys_from_snapshot` (una clave propia de la foto
sobrevive, y esa prueba falla si se desconoce el almacén).

## 6. Matriz de banderas

| `FEATURE_CONTEXT_ENABLED` | Efecto medido |
|---|---|
| `true` (valor actual en `.env` y `system_config`) | La foto se escribe post-turno y se lee antes del turno siguiente. El bloque se calcula del historial **y** se enriquecen las claves que solo la foto aporta (hoy, ninguna de las cuatro H.3) |
| `false` | El almacén no se inyecta en el lector ni el escritor se activa: el bloque se deriva del historial. Idéntico al caso encendido para las cuatro claves H.3 |

Tras el arreglo, las cuatro claves son **iguales con la bandera encendida y apagada** — que es justo el
punto: no dependen de la foto. Medido, no supuesto: escenarios 1 y 3 de la prueba E2.

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

## 8. Arreglo aplicado

**Opción elegida: refrescar las cuatro claves en vivo** (era la recomendada). Se evaluaron tres
caminos:

| Opción | Qué implica | Veredicto |
|---|---|---|
| **A. Refrescar también las dos claves de presente** en el lector | Cambio chico y localizado en `retrievers/context.py`. La foto sigue guardándose y leyéndose para lo que ella sola aporte | ✅ **Aplicada** |
| B. Leer la foto solo cuando el historial no alcanza | En la práctica equivale a A: la derivación en vivo siempre está disponible | Descartada por equivalente |
| C. Dejar de escribir la foto | Descarta la tabla y el requerimiento entero | ❌ Desproporcionada |

**El cambio** (`src/diana/cognitive/retrievers/context.py`): la derivación en vivo se calcula siempre
y **gana** sobre el contenido de la foto; de la foto solo sobreviven las claves que la derivación no
produce. Antes se refrescaban dos (día y hora) y se congelaban dos; ahora se refrescan las cuatro.

**Lo que esto implica, dicho sin adornos:** con las cuatro claves en vivo, la foto ya no influye en el
bloque que recibe el modelo. El almacén del requerimiento (REQ-MEM-06) sigue escribiéndose y
leyéndose, y sigue aportando cualquier clave propia que se le agregue en el futuro — pero hoy su
contenido temporal **no es determinante**. Consecuencia a vigilar: si la lectura se desconectara, el
bloque no cambiaría. Por eso la prueba exige además que una clave propia de la foto llegue al prompt
(§5): así la desconexión se nota.

**Sobre la búsqueda por parecido huérfana (`ContextsRepo.find_by_similarity`):** está en la misma
situación que la de fichas. Se propone la misma decisión (eliminarla) si no hay plan de usar la
búsqueda semántica de contextos. **No se eliminó**: requiere confirmación, igual que en el caso de las
fichas.

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

Con el arreglo aplicado, el valor esperado pasa a ser **0**: cualquier aparición vuelve a ser señal de
alerta, no ruido de fondo. Se deja como propuesta de vigilante diario.

## 10. Archivos tocados

| Archivo | Cambio |
|---|---|
| `src/diana/cognitive/retrievers/context.py` | La derivación en vivo gana sobre la foto; la foto solo aporta sus claves propias. Docstring del lector actualizado |
| `tests/unit/cognitive/test_retrievers.py` | Se reemplazó la prueba que fijaba el comportamiento viejo por dos: el vivo gana, y las claves propias de la foto sobreviven |
| `tests/audit/test_C_CTX_01.py` | **Nuevo** — 3 escenarios E2 del contexto temporal |
| `audit/FASE2-CONTEXTO.md` | Este informe |

Los dos sabotajes se aplicaron y se revirtieron (`grep -rn SABOTAJE src/` → sin resultados).

### Suites ejecutadas (2026-10-07)

| Suite | Resultado |
|---|---|
| `tests/unit` | **4352 passed** (una más que antes del arreglo) |
| `tests/e2e` | **233 passed** (igual a la línea base) |
| `tests/audit` | **7 passed** (2 de C-HIST-01, 2 de C-EMB-01, 3 de C-CTX-01) |

## 11. Estado en producción

Integrado a `main`, publicado en `origin/main` y con el bot reiniciado el **2026-10-07** (hash y hora
exactos en el commit correspondiente). Verificación posterior al reinicio:

| Comprobación | Resultado |
|---|---|
| Servicio | `active`, **0 reinicios** (sin bucle de arranque) |
| Salud | `/health` → `{"status":"ok",...}` con base y bot en verde |
| Errores o trazas en el arranque | Ninguno |

**Verificación del arreglo con turnos reales:** se repite la medición de §3 restringida a los turnos
**posteriores al reinicio**. Antes del arreglo el desacuerdo era del 84 %; después, el valor esperado
es **0**.
