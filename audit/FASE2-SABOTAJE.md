# Fase 2 — Sabotaje E3 de C-SHADOW-01 y C-EMB-01

**Contratos saboteados:** `audit/contracts/C-SHADOW-01.md` (modo sombra) · `audit/contracts/C-EMB-01.md` (huellas semánticas)
**Pruebas exigidas:** `tests/audit/test_C_SHADOW_01.py` (5) y `tests/audit/test_C_EMB_01_huellas.py` (3) — 8 en total
**Copia descartable:** worktree en `/tmp/diana-sabotaje`, rama `sabotaje/fase2` desde `main` (`817f11d`) — retirada al terminar (§7). **Fecha:** 2026-10-08.
**Sin commit a `main`. Código de producción intacto** (todas las mutaciones se aplicaron y revirtieron en la copia; ver §7).

---

## Resumen para la dueña

Se hizo la prueba que faltaba: **desconectar a propósito cada pieza** y exigir que la prueba falle. Una prueba
que sigue en verde después de arrancarle la pieza que dice cuidar no sirve para nada: es decorativa.

Se aplicaron **12 sabotajes** sobre las 8 pruebas de la ronda anterior (los 8 pedidos más 2 de cobertura y
2 variantes). **Los 12 hicieron fallar la prueba que debía fallar. Ninguna prueba quedó decorativa.**

| Qué se le arrancó al sistema (en lenguaje llano) | Pruebas que lo delataron |
|---|---|
| El registro del modo sombra: el cable, la bandera y la pieza que lo escribe | 4 de las 5 pruebas de sombra |
| El arreglo de septiembre que protege lo que decide la dueña | 1 (la prueba de regresión) |
| El motor de huellas: memoria, "Destacar" y reglas | las 3 pruebas de huellas |
| El atajo de saludo de plantilla | 1 |
| La escalación por palabra clave (pago / precio) | 1 |

**Lo importante para el negocio:** las 8 pruebas pasan de "funciona" a **E3**, que es el nivel que exige
evidencia de fallo. Se puede confiar en lo que afirman: el registro del modo sombra existe de verdad, la
decisión de la dueña no se borra, y las huellas de memoria, ejemplos y reglas son reales (no el vector de
ceros que en agosto dejó cosas invisibles sin que nadie se enterara).

**Lo que NO cambia:** nada para el VIP ni para la operación. No se tocó el sistema en producción: cada
mutación vivió en una copia de trabajo y se revirtió antes de pasar a la siguiente.

---

## 1. Método

El sabotaje va siempre sobre una **copia descartable**, nunca sobre el repo de trabajo ni sobre lo que corre
el bot. Por cada sabotaje el arnés hace cinco pasos y falla si alguno no se cumple:

1. **Limpia** la copia y exige el árbol sin cambios (`git status --porcelain src` vacío).
2. **Muta**: aplica el cambio con anclas exactas (si el ancla no aparece una sola vez, el arnés aborta: evita
   sabotear "parecido" y creer que se saboteó).
3. **Corre las 8 pruebas** completas (no solo la que debería fallar: así también se ve qué NO falla).
4. **Revierte** (`git checkout -- src`).
5. **Verifica** que la copia quedó limpia antes del sabotaje siguiente.

```bash
# copia descartable
git worktree add -b sabotaje/fase2 /tmp/diana-sabotaje main     # main = 817f11d

# arnés (vive fuera del repo)
python3 /tmp/sabotaje/sabote.py

# por dentro, cada corrida es:
sg docker -c "cd /tmp/diana-sabotaje && \
  DIANA_E2E_COPY_DUMP=/home/ubuntu/repos/DianaV2/runtime/e2e_copy/diana_copy.sql \
  /home/ubuntu/repos/DianaV2/.venv/bin/python -m pytest \
  tests/audit/test_C_SHADOW_01.py tests/audit/test_C_EMB_01_huellas.py \
  -v -p no:randomly --no-header"
```

El sabotaje no se simula: se corre el mismo Postgres real, el mismo `build_app` y el mismo motor de huellas
que la prueba ya usaba. Lo único falso sigue siendo el modelo de lenguaje externo.

### Línea base (antes de tocar nada)

```
$ pytest tests/audit/test_C_SHADOW_01.py tests/audit/test_C_EMB_01_huellas.py -v -p no:randomly --no-header
8 passed, 1 warning in 29.74s
```

### Comprobación de que la mutación fue la que corrió

Cada corrida dejó registrado el árbol mutado (`git diff --stat src`) antes de ejecutar, y ningún sabotaje se
aplicó sobre un árbol sucio. Además, los tiempos lo confirman: la corrida de las 8 pruebas tarda ~30 s porque
tres de ellas cargan el modelo real de embeddings, y cuando el motor de huellas se sabotea (S1/S3/S4) esa
carga nunca ocurre y la corrida baja a 6–13 s. Si la mutación no hubiera entrado en el proceso, esos tiempos
no cambiarían.

### Reproducibilidad

La batería completa se corrió **dos veces** (24 corridas de las 8 pruebas) y los 12 sabotajes tumbaron
exactamente las mismas pruebas en ambas. Después del último revert se hizo una corrida de cierre, que volvió
a dar verde: las mutaciones no dejaron residuo ni en el texto ni en el comportamiento.

```
$ pytest tests/audit/test_C_SHADOW_01.py tests/audit/test_C_EMB_01_huellas.py -v -p no:randomly --no-header
8 passed, 1 warning in 29.43s      # cierre: las 12 mutaciones ya revertidas
```

---

## 2. Tabla de resultados

### 2.1 Por sabotaje

| # | Sabotaje | Pieza desconectada (punto exacto) | Pruebas que debían fallar | Resultado real | Nivel |
|---|---|---|---|---|---|
| 1 | **S1** dependencia desconectada | `composition.py` entrega `outcome_log=None` al orquestador con la bandera ON | `bandera_on`, `test_b` | **2 failed** (las 2) | E3 |
| 2 | **S2** bandera apagada donde dice ON | las 3 compuertas (`enabled=`, `outcome=`, `outcome_log=`) fuerzan el estado apagado | `bandera_on`, `test_b` | **2 failed** (las 2) | E3 |
| 3 | **S2b** bandera encendida donde dice OFF | las 3 compuertas fuerzan el estado encendido | `bandera_off` | **1 failed** (la 1) | E3 |
| 4 | **S3** la pieza lanza | `OutcomeLogService.record_shadow` lanza `RuntimeError` dentro de su propio `try` | `bandera_on`, `test_b` | **3 failed** (+ `test_d_saludo`) | E3 |
| 5 | **S3b** la pieza lanza (variante dura) | el mismo `RuntimeError`, pero antes del `try` del servicio | `bandera_on`, `test_b` | **3 failed** (+ `test_d_saludo`) | E3 |
| 6 | **S5** llamador cortado | se borra `await self._run_outcome_log(...)` del post-turno | `bandera_on`, `test_b` | **2 failed** (las 2) | E3 |
| 7 | **M7** cobertura extra | se desactiva el atajo de saludo de plantilla (`director.py`) | `test_d_saludo` | **1 failed** (la 1) | E3 |
| 8 | **M8** cobertura extra | se desactiva la clasificación J.4 (`pago_precio`) | `test_d_escalacion` | **1 failed** (la 1) | E3 |
| 9 | **Regresión** | se revierte el arreglo del commit `3ade3b3` (upsert que pisa las columnas de la dueña) | `test_b` | **1 failed** (la 1) | E3 |
| 10 | **S1** embedder desconectado | `embedder=None` en los 3 caminos reales (zona gris, Destacar, extracción de memoria) | huella memoria, ejemplo, política | **3 failed** (las 3) | E3 |
| 11 | **S3** motor de huellas lanza | `EmbeddingService.embed` lanza `RuntimeError` | huella memoria, ejemplo, política | **3 failed** (las 3) | E3 |
| 12 | **S4** motor devuelve ceros | `EmbeddingService.embed` devuelve `[0.0] * 384` | huella memoria, ejemplo, política | **3 failed** (las 3) | E3 |

**12 de 12 sabotajes mordieron.** Ninguna de las 8 pruebas quedó en verde tras el sabotaje que debía tumbarla.

### 2.2 Por prueba (esto es lo que decide el nivel)

| Prueba | Sabotajes que la hacen fallar | Veredicto |
|---|---|---|
| `test_a_...[bandera_on]` | S1, S2, S3, S3b, S5 | **E3** |
| `test_a_...[bandera_off]` | S2b | **E3** |
| `test_b_...` (regresión de septiembre) | S1, S2, S3, S3b, S5, reversión de `3ade3b3` | **E3** |
| `test_d_escalacion_...` | M8 | **E3** |
| `test_d_saludo_...` | M7, S3, S3b | **E3** |
| `test_memoria_...` | EMB-S1, EMB-S3, EMB-S4 | **E3** |
| `test_ejemplo_...` | EMB-S1, EMB-S3, EMB-S4 | **E3** |
| `test_politica_...` | EMB-S1, EMB-S3, EMB-S4 | **E3** |

**Ninguna prueba es decorativa.** Las 8 tienen al menos un sabotaje que las tumba, y las 8 vuelven a verde al
revertirlo.

---

## 3. Evidencia — salida de cada fallo

### 3.1 S1 — dependencia desconectada (`outcome_log=None`)

```
mutado: src/diana/composition.py | 4 +--- | 1 file changed, 1 insertion(+), 3 deletions(-)
=================== 2 failed, 6 passed, 1 warning in 29.47s ====================
FAILED tests/audit/test_C_SHADOW_01.py::test_a_turno_vip_entregado_deja_fila_con_veredicto_y_nota[bandera_on]
FAILED tests/audit/test_C_SHADOW_01.py::test_b_lo_que_decide_la_duena_sobrevive_al_reguardado_del_turno

E           AssertionError: con la bandera en True se esperaban 1 fila(s): []
E           assert 0 == 1
E            +  where 0 = len([])
tests/audit/test_C_SHADOW_01.py:383: AssertionError

E           AssertionError: la fila de sombra no existía antes: []
E           assert 0 == 1
E            +  where 0 = len([])
tests/audit/test_C_SHADOW_01.py:448: AssertionError
```

Las 6 que siguen en verde son las correctas: la contraprueba de bandera apagada (no debe escribir nada), las
dos rutas de diseño (no llevan fila por diseño) y las tres de huellas (no dependen de esta pieza).

### 3.2 S2 — bandera apagada donde el contrato dice ON

```
mutado: src/diana/composition.py | 10 +++------- | 1 file changed, 3 insertions(+), 7 deletions(-)
=================== 2 failed, 6 passed, 1 warning in 29.65s ====================
FAILED tests/audit/test_C_SHADOW_01.py::test_a_...[bandera_on]
FAILED tests/audit/test_C_SHADOW_01.py::test_b_...

E           AssertionError: con la bandera en True se esperaban 1 fila(s): []
E           assert 0 == 1
E            +  where 0 = len([])
tests/audit/test_C_SHADOW_01.py:383: AssertionError
```

Mismo síntoma que S1 a propósito: si la bandera no fuera la que manda, el sabotaje de la bandera no se
distinguiría del corte de cable. Que ambos muerdan confirma que **la bandera es la autoridad** y que el cable
existe.

### 3.3 S2b — bandera encendida donde el contrato dice OFF (contraprueba de la matriz)

```
mutado: src/diana/composition.py | 10 +++------- | 1 file changed, 3 insertions(+), 7 deletions(-)
=================== 1 failed, 7 passed, 1 warning in 29.61s ====================
FAILED tests/audit/test_C_SHADOW_01.py::test_a_...[bandera_off]

E           AssertionError: con la bandera en False se esperaban 0 fila(s): [{'shadow_verdict': 'send',
              'shadow_reason': 'autonomous_ok', 'draft_score': None, 'owner_outcome': 'approved_as_is',
              'sent_score': None, 'quality_delta': None, 'blocked_dims': None, 'vip_signal': None,
              'correction_severity': None}]
E           assert 1 == 0
E            +  where 1 = len([{'shadow_verdict': 'send', 'shadow_reason': 'autonomous_ok', ...}])
tests/audit/test_C_SHADOW_01.py:383: AssertionError
```

Esta es la dirección que faltaba: prueba que el estado **apagado** también está medido y no es un supuesto.
Sin esta corrida, "con la bandera apagada no se escribe nada" solo sería una creencia.

### 3.4 S3 — la pieza lanza, con rastro visible (nivel del servicio)

```
mutado: src/diana/application/outcome_log_service.py | 1 + | 1 file changed, 1 insertion(+)
=================== 3 failed, 5 passed, 1 warning in 29.34s ====================
FAILED tests/audit/test_C_SHADOW_01.py::test_a_...[bandera_on]
FAILED tests/audit/test_C_SHADOW_01.py::test_b_...
FAILED tests/audit/test_C_SHADOW_01.py::test_d_saludo_de_plantilla_no_escribe_fila_por_diseno

E           AssertionError: con la bandera en True se esperaban 1 fila(s): []
E           assert 0 == 1
tests/audit/test_C_SHADOW_01.py:383: AssertionError

E           AssertionError: no hay fila, pero además hubo un fallo tragado: ['outcome_record_shadow_failed']
E           assert ['outcome_rec...hadow_failed'] == []
E             Left contains one more item: 'outcome_record_shadow_failed'

------------------------------ Captured log call -------------------------------
ERROR    diana.application:outcome_log_service.py:332 outcome_record_shadow_failed
    raise RuntimeError("SABOTAJE S3: record_shadow roto")
RuntimeError: SABOTAJE S3: record_shadow roto
```

**El rastro visible existe:** el primer nivel de silencio (el `except` propio del servicio) avisa con ERROR y
traza completa. Además la prueba lo *ve*: la aserción "hubo un fallo tragado" es la que delata el tercer fallo
(`test_d_saludo`), que en verde solo comprobaba que no hubiera fila.

### 3.5 S3b — la pieza lanza antes de su propio guard (nivel del orquestador)

```
mutado: src/diana/application/outcome_log_service.py | 1 + | 1 file changed, 1 insertion(+)
=================== 3 failed, 5 passed, 1 warning in 29.61s ====================
FAILED tests/audit/test_C_SHADOW_01.py::test_a_...[bandera_on]
FAILED tests/audit/test_C_SHADOW_01.py::test_b_...
FAILED tests/audit/test_C_SHADOW_01.py::test_d_saludo_de_plantilla_no_escribe_fila_por_diseno

E           AssertionError: no hay fila, pero además hubo un fallo tragado: ['outcome_log_error']
E           assert ['outcome_log_error'] == []
E             Left contains one more item: 'outcome_log_error'

------------------------------ Captured log call -------------------------------
ERROR    diana.application:observability.py:20 outcome_log_error
    raise RuntimeError("SABOTAJE S3b: roto fuera del guard")
RuntimeError: SABOTAJE S3b: roto fuera del guard
```

Con esto quedan **probados los dos niveles de silencio** que el contrato marcaba como punto ciego: el del
servicio (`outcome_record_shadow_failed`) y el del orquestador (`outcome_log_error`, vía `log_swallowed`). El
turno no se rompe en ninguno de los dos — y ese es exactamente el riesgo: sin la prueba, el hueco sería
invisible.

### 3.6 S5 — llamador cortado (función huérfana)

```
mutado: src/diana/application/turn_orchestrator.py | 2 +- | 1 file changed, 1 insertion(+), 1 deletion(-)
=================== 2 failed, 6 passed, 1 warning in 29.54s ====================
FAILED tests/audit/test_C_SHADOW_01.py::test_a_...[bandera_on]
FAILED tests/audit/test_C_SHADOW_01.py::test_b_...

E           AssertionError: con la bandera en True se esperaban 1 fila(s): []
E           assert 0 == 1
E            +  where 0 = len([])
tests/audit/test_C_SHADOW_01.py:383: AssertionError

E           AssertionError: la fila de sombra no existía antes: []
E           assert 0 == 1
tests/audit/test_C_SHADOW_01.py:448: AssertionError
```

Idéntico a S1 en la salida, y por una razón metodológica importante: **la prueba entra por el camino real**
(`build_app` + mensaje de negocio), no armando el servicio a mano. Si la prueba construyera el orquestador
ella misma, este sabotaje — y el de S1 — habrían pasado en verde.

### 3.7 M7 — atajo de saludo desactivado (cobertura extra)

```
mutado: src/diana/cognitive/director.py | 2 +- | 1 file changed, 1 insertion(+), 1 deletion(-)
=================== 1 failed, 7 passed, 1 warning in 29.66s ====================
FAILED tests/audit/test_C_SHADOW_01.py::test_d_saludo_de_plantilla_no_escribe_fila_por_diseno

E           AssertionError: el corte de saludo evaluó el borrador: la ausencia de fila ya no sería por
              diseño: {'safety': 0.95, 'empathy': 0.9, 'coverage': 0.9, 'doctrine': 0.9, 'precision': 0.9,
              'consistency': 0.9, 'naturalness': 0.9, 'raw_llm_output': {...}}
tests/audit/test_C_SHADOW_01.py:636: AssertionError
```

### 3.8 M8 — escalación determinística desactivada (cobertura extra)

```
mutado: src/diana/application/j4_triggers.py | 1 + | 1 file changed, 1 insertion(+)
=================== 1 failed, 7 passed, 1 warning in 29.57s ====================
FAILED tests/audit/test_C_SHADOW_01.py::test_d_escalacion_por_palabra_clave_no_escribe_fila_por_diseno

E           AssertionError: no escaló: {'id': '713913c0-5bf8-4204-94b2-d9ada17090d4', 'status':
              'pending_approval', 'vip_id': '4dfb38c0-54c2-47df-8e68-bc116e8e6337', 'channel_type': 'vip'}
tests/audit/test_C_SHADOW_01.py:556: AssertionError
```

M7 y M8 no estaban en la lista pedida. Se agregaron porque **sin ellos, las dos pruebas de rutas de diseño
(`test_d_*`) no eran mordidas por ningún sabotaje propio**: su evidencia E3 habría quedado apoyada solo en lo
que reportó quien escribió las pruebas, que es justamente lo que el rol del Saboteador no puede aceptar.

### 3.9 Reversión del arreglo del commit `3ade3b3` (regresión de septiembre)

```
mutado: src/diana/application/outcome_log_service.py       |  7 --
        src/diana/infrastructure/db/repositories/turn_outcome.py | 77 ++++++--------------
        2 files changed, 27 insertions(+), 57 deletions(-)
=================== 1 failed, 7 passed, 1 warning in 29.35s ====================
FAILED tests/audit/test_C_SHADOW_01.py::test_b_lo_que_decide_la_duena_sobrevive_al_reguardado_del_turno

E           AssertionError: la decisión de la dueña no quedó guardada: [{'shadow_verdict': 'send',
              'shadow_reason': 'autonomous_ok', 'draft_score': 0.4, 'owner_outcome': None,
              'sent_score': None, 'quality_delta': None, 'blocked_dims': None, 'vip_signal': None,
              'correction_severity': None}]
E           assert None == 'approved_as_is'
tests/audit/test_C_SHADOW_01.py:462: AssertionError
```

Se revirtió **solo la parte de `src/`** del commit (con `git apply -R`), dejando sus pruebas unitarias fuera
del alcance para no medir dos cosas a la vez. El defecto de septiembre vuelve a aparecer con la misma cara:
`owner_outcome` en `None` donde debería decir `approved_as_is`. La prueba de regresión cumple su función.

### 3.10 S1 — embedder desconectado en los tres caminos reales

```
mutado: src/diana/composition.py | 6 +++--- | 1 file changed, 3 insertions(+), 3 deletions(-)
=================== 3 failed, 5 passed, 1 warning in 12.81s ====================
FAILED tests/audit/test_C_EMB_01_huellas.py::test_memoria_del_turno_real_lleva_huella_y_se_recupera
FAILED tests/audit/test_C_EMB_01_huellas.py::test_ejemplo_dorado_destacado_lleva_huella_y_se_recupera
FAILED tests/audit/test_C_EMB_01_huellas.py::test_politica_de_zona_gris_lleva_huella_y_se_recupera

-- memoria: la fila directamente no existe
E           AssertionError: la extracción post-turno no guardó ningún hecho: eventos vistos:
              ['coordinate_result', 'turn_begun', 'turn_minted_waiting_delay', 'turn_delay_started',
               'turn_delay_completed', 'draft_for_approval', 'vip_message_handled',
               'memory_extraction_skipped_not_terminal', 'admin_delivered', 'memory_extraction_failed']
tests/audit/test_C_EMB_01_huellas.py:393: AssertionError

-- ejemplo destacado: la fila existe pero con la huella vacía
E       AssertionError: examples: la huella quedó en ceros
E       assert [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, ...] != [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, ...]
tests/audit/test_C_EMB_01_huellas.py:308: AssertionError

-- política de zona gris: ídem
E       AssertionError: policies: la huella quedó en ceros
tests/audit/test_C_EMB_01_huellas.py:308: AssertionError
```

### 3.11 S3 — el motor de huellas lanza

```
mutado: src/diana/cognitive/embedding.py | 1 + | 1 file changed, 1 insertion(+)
=================== 3 failed, 5 passed, 1 warning in 5.95s ====================
FAILED tests/audit/test_C_EMB_01_huellas.py::test_memoria_...
FAILED tests/audit/test_C_EMB_01_huellas.py::test_ejemplo_...
FAILED tests/audit/test_C_EMB_01_huellas.py::test_politica_...

E           AssertionError: la extracción post-turno no guardó ningún hecho ... memory_extraction_failed
E       AssertionError: examples: la huella quedó en ceros
E       AssertionError: policies: la huella quedó en ceros

------------------------------ Captured log call (rastro visible) ------------------------------
ERROR    diana.application:memory_extraction_service.py:254 memory_extraction_failed
ERROR    diana.application:staging_service.py:66 staging_embed_failed
WARNING  diana.application:gray_zone_service.py:176 policy_embedding_pending
WARNING  diana.application:policy_embedding.py:36 policy_embed_attempt_failed
```

Los tres caminos dejan rastro propio cuando el motor falla: memoria y ejemplo con ERROR, política con WARNING
(`reason=embed_failed`). El tiempo de 5,82 s (contra ~30 s) confirma que el modelo real nunca llegó a cargarse.

### 3.12 S4 — el motor devuelve el vector de ceros (el disfraz de agosto)

```
mutado: src/diana/cognitive/embedding.py | 5 +---- | 1 file changed, 1 insertion(+), 4 deletions(-)
=================== 3 failed, 5 passed, 1 warning in 5.93s ====================
FAILED tests/audit/test_C_EMB_01_huellas.py::test_memoria_...
FAILED tests/audit/test_C_EMB_01_huellas.py::test_ejemplo_...
FAILED tests/audit/test_C_EMB_01_huellas.py::test_politica_...

E       AssertionError: memories: la huella quedó en ceros
E       assert [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, ...] != [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, ...]
tests/audit/test_C_EMB_01_huellas.py:308: AssertionError

E       AssertionError: examples: la huella quedó en ceros
tests/audit/test_C_EMB_01_huellas.py:308: AssertionError

E       AssertionError: policies: la huella quedó en ceros
tests/audit/test_C_EMB_01_huellas.py:308: AssertionError
```

Este es el sabotaje más importante de C-EMB-01: reproduce **exactamente** el incidente de agosto (filas
guardadas, sin error, invisibles para la búsqueda). Las tres pruebas lo detectan. Nótese el detalle fino: en
este caso la memoria **sí** inserta su fila (falla en la comprobación de la huella, no en la existencia), que
es justamente el disfraz que hay que cazar.

---

## 4. Hallazgos colaterales del sabotaje

No invalidan ninguna prueba; son cosas que solo se ven al desconectar piezas.

### H-SB-1 — Con el embedder ausente, "Destacar" escribe ceros **sin dejar rastro**

En el sabotaje S1 de C-EMB-01 (embedder en `None`), el camino de "Destacar" guardó el ejemplo dorado con la
huella en ceros y **no registró ni un solo aviso**. Los otros dos caminos sí avisan (memoria con
`memory_extraction_failed`, política con `policy_embedding_pending`), pero el de ejemplos no.

```
------------------------------ Captured log call (ejemplo, S1) ------------------------------
INFO     diana.application:admin_service.py:980 gold_example_marked
(ningún WARNING ni ERROR de huella en toda la corrida)
```

La causa está en `staging_service._embed`: cuando `self._embedder is None` devolvía `None` en silencio; solo
registraba `staging_embed_failed` si el embedder **existe y falla**. Con la pieza ausente, el repositorio
convierte ese `None` en ceros (`examples.py:74`), que es el punto ciego que el propio contrato ya tenía
anotado. **La prueba lo caza igual** (por eso es E3), pero en producción el rastro no existía.

**ARREGLADO (2026-10-08, autorizado por la dueña).** `staging_service._embed` ahora deja rastro en todos
los caminos que terminan en ceros, con el mismo vocabulario que perfiles y política: evento
`staging_embed_zeros` con `reason` = `no_embedder` / `empty_text` (a DEBUG, porque no tener texto que
huellar es legítimo) / `embedder_returned_zeros`. Este último es el disfraz de agosto: el motor contesta
ceros **sin lanzar excepción**, así que nunca caía en el camino de error y la fila parecía válida. El
comportamiento no cambió (la fila se sigue guardando, fail-open); lo que se quitó es el silencio. Tres
pruebas unitarias nuevas cubren los tres motivos, y se verificó que fallan si se revierte el arreglo
(sabotaje).

### H-SB-2 — Los dos niveles de silencio de C-SHADOW-01 quedaron probados con evidencia

El contrato listaba dos puntos ciegos: el `except` del orquestador y el del servicio. S3 y S3b los ejercitan
uno por uno y ambos dejan rastro (`outcome_record_shadow_failed` y `outcome_log_error`). El riesgo real no es
que fallen en silencio, sino que **el turno sigue adelante**: si esto pasara en producción, el turno se
entrega igual y la fila falta. Eso es exactamente lo que el vigilante V2 de `audit/vigilantes.sql` detectaría.

### H-SB-3 — La bandera del círculo de aprendizaje está VIVA en el `.env` real

```
.env:102: FEATURE_AUTONOMY_QUALITY_ENABLED=true
```

El contrato decía que "la bandera real de producción vive en `.env`: no verificable desde el código". Sí es
verificable desde el archivo, y está encendida. Las pruebas la encienden y apagan **en memoria** (no leen el
`.env`), así que el E3 prueba el mecanismo, no el valor desplegado; con la bandera VIVA, el mecanismo probado
es el que corresponde a la configuración real. Las banderas relacionadas
(`FEATURE_MEMORY_ENABLED`, `FEATURE_QUALITY_FEEDBACK_ENABLED`, `FEATURE_GRAY_ZONE_ENABLED`,
`FEATURE_STAGING_ENABLED`) también están en `true`.

### H-SB-4 — Las pruebas de "hueco por diseño" también delatan fallos tragados

`test_d_saludo` y `test_d_escalacion` no solo comprueban "no hay fila": comprueban **por qué** no hay fila.
Al saboteárselas aparecieron delaciones cruzadas (S3 y S3b tumban `test_d_saludo` por la aserción
anti-silencio). Es la señal de que las pruebas de "hueco por diseño" están bien construidas: distinguen el
hueco intencional del hueco por error.

---

## 5. Límites — lo que este sabotaje NO prueba

- **El tramo de reacción del VIP (`vip_signal`, C3)** de C-SHADOW-01 sigue sin prueba: no estaba cubierto por
  la ronda del Probador ni por esta. Sigue fuera del nivel E3.
- **Los tramos `corregir` y `escalar`** de `owner_outcome`: solo se probó `approved_as_is`. Los otros dos
  valores del contrato siguen sin cobertura.
- **El camino de "Reprender"** (contraejemplo en `examples`) comparte el mismo `_embed` que "Destacar", pero
  no se midió por su propio flujo.
- **Los vigilantes E4 no están desplegados**: las consultas existen en `audit/vigilantes.sql`, pero nada las
  corre todavía. Sin ellas el nivel máximo alcanzable es E3.
- El sabotaje corre contra la **copia** de la base real restaurada en el contenedor desechable, no contra la
  base de producción. La configuración de banderas de producción se verificó leyendo el `.env`, no ejecutando.

---

## 6. Nivel resultante

| Contrato | Antes | Ahora | Vigilante E4 |
|---|---|---|---|
| **C-SHADOW-01** | 🟡 Sin E3 (evidencia viva de producción: 499 filas, 223/237 turnos con fila) | 🟢 **E3** en los tramos (a) entrega, (b) resolución de la dueña, (c) bandera OFF, (d) rutas de diseño | **Desplegado** (§9): V2 + V7, diario |
| **C-EMB-01** | 🟡 E3 solo en `profiles` | 🟢 **E3** en `memories`, `examples` y `policies` (más `profiles` de la ronda anterior) | **Desplegado** (§9): V1, diario |

Semáforo global: 🟢 **E3 + E4** en los tramos medidos. Sigue sin cubrir: la reacción del VIP (C3),
los tramos `corregir` / `escalar` de `owner_outcome` y el camino de "Reprender".

---

## 7. Garantía de que no quedó nada cambiado

Las mutaciones vivieron solo en la copia descartable, y el arnés exige árbol limpio antes de cada sabotaje.
Estado al terminar la batería completa y la corrida de cierre (verificado después de todo, no antes):

```
$ git -C /tmp/diana-sabotaje status --short        # copia descartable: archivos
(vacío)
$ git -C /tmp/diana-sabotaje diff --stat           # copia descartable: diff
(vacío)
$ git -C /tmp/diana-sabotaje log --oneline -1      # copia descartable: commits
817f11d test(audit): pruebas E2 de C-SHADOW-01 y C-EMB-01 contra Postgres real

$ git -C /home/ubuntu/repos/DianaV2 status --short src/   # repo de trabajo: código
(vacío)
$ git -C /home/ubuntu/repos/DianaV2 diff --stat           # repo de trabajo: diff
(vacío)
$ git -C /home/ubuntu/repos/DianaV2 status --short        # repo de trabajo: todo
?? audit/FASE2-SABOTAJE.md      # este informe, sin commitear (es la entrega)
```

Al momento de verificar, la copia descartable estaba en `817f11d`, el mismo commit que `main`: **no se creó
ningún commit** en ningún lado. Lo único que aparece en el repo de trabajo es este informe, sin commitear, tal como se pidió.

**`src/` sin un solo cambio en ninguna de las dos copias.** El repo de trabajo del bot no se tocó en ningún
momento: todo el sabotaje ocurrió en `/tmp/diana-sabotaje`, y el servicio `diana-bot` (que corre desde el
repo de trabajo) nunca vio código mutado. Además de los archivos, quedó verificado el comportamiento: la
corrida de cierre con todo revertido volvió a dar `8 passed` (§1).

**La copia descartable y su rama temporal se retiraron al terminar** (`git worktree remove` + `git branch -D`),
para no dejar ni siquiera una rama de más en el repo. La prueba de que no quedaba nada: los dos comandos se
ejecutaron sin `--force` sobre un árbol limpio, y `git branch -a` no muestra ninguna rama `sabotaje/*`. El
arnés (`sabote.py`) y los registros crudos de cada corrida (`out/*.txt`, `run2.log`) quedan **fuera del
repo**, en `/tmp/sabotaje/`; la copia de trabajo se recrea con el comando del Anexo cuando haga falta volver
a medir.

---

## 8. Siguiente paso

1. **Vigilancia E4 — HECHO** (§9): `scripts/vigilantes.py` corre por cron de usuario una vez por día. V1, V2
   y V7 activos; V3/V4/V5/V6 no, cada uno con su motivo escrito en `audit/vigilantes.sql`.
2. **Fichas de contrato — HECHO**: `audit/contracts/C-SHADOW-01.md` y `C-EMB-01.md` actualizadas con el nivel
   E3, el vigilante desplegado y los hallazgos.
3. **H-SB-1 — ARREGLADO** (2026-10-08, por decisión de la dueña): `staging_service._embed` ya no escribe
   ceros en silencio (§4). Tres pruebas unitarias nuevas; la suite completa (4.432 pruebas) y las pruebas E2
   de C-EMB-01 siguen en verde.
4. **Las 2 huellas históricas de `profiles` — RESUELTAS** (2026-10-08): regeneradas con
   `scripts/regenerate_profile_embeddings.py --apply` (con respaldo previo en `runtime/backup_profile_embeddings_2026-10-08T18-50-34Z.json`).
   V1 hoy da 0 en las 5 tablas.
5. **Nada más que arreglar por el sabotaje**: los 12 sabotajes hacen su trabajo y no apareció ningún defecto
   nuevo. Lo que queda son límites de cobertura (§5), no fallas.

---

## 9. Vigilancia E4 — activada el 2026-10-08

> Estado actual: el chequeo corre como **job diario dentro del bot**
> (`src/diana/jobs/contract_watchdog.py`), que es lo que le permite leer los contadores de fallos
> internos del proceso y publicar su latido en `/health`. Esta sección queda como registro de la
> ronda que lo activó. Ver `audit/FASE2-VIGILANTE.md`.

Una prueba en verde dice que el efecto ocurría **el día que se midió**. E4 es lo que avisa si mañana deja de
ocurrir. Se activó, y en el camino apareció que los vigilantes propuestos, corridos de verdad, **no servían
como estaban**.

### 9.1 Qué quedó corriendo

| Vigilante | Qué mira | Contrato |
|---|---|---|
| **V1** | huellas semánticas **nuevas** en ceros (ventana de 2 días), por tabla | C-EMB-01 |
| **V2** | turnos de VIP que pasaron por el pipeline y no dejaron su fila de sombra | C-SHADOW-01 |
| **V7** | turno entregado con nota del borrador y **sin** la decisión de la dueña (la firma del defecto del 10-sep) | C-SHADOW-01 |

Cómo corre: `scripts/vigilantes.py`, **cron de usuario, una vez por día a las 10:17 UTC**, solo lectura (cada
consulta dentro de una transacción `READ ONLY`). Avisa por Telegram **solo** si algo da más de 0. Si todo está
en orden, no manda nada y deja su latido en `runtime/vigilantes.log`.

### 9.2 Lo que salió al correrlos contra la base real (antes de encenderlos)

Los cuatro propuestos que se dejaron **apagados** no fue por prudencia genérica: es lo que devolvieron.

| Vigilante | Qué devolvía | Por qué no se activa así |
|---|---|---|
| **V1** | 2 ceros en `profiles` | Son las 2 filas históricas (28/29-jul) ya conocidas y sin uso. Encendido tal cual habría avisado **todos los días para siempre**. Se le puso ventana de 2 días: avisa de un cero **nuevo**, que es lo que importa. *(Después, con la autorización de la dueña, esas 2 filas se regeneraron: hoy V1 da 0 en las 5 tablas — §8.4.)* |
| **V2** | 5 turnos sin fila | Los 5 son **sesiones de sandbox** de la dueña (chat 1280444712): no persisten a propósito (§4.20 de AGENTS.md) y el journal lo dice (`post_turn_skipped_sandbox`). Sin ese filtro, cada prueba suya en el sandbox habría disparado una falsa alarma. El ejecutor los descarta leyendo el journal. |
| **V3** | 1 turno escalado sin resolución de la dueña | Alertaría **por diseño**: una escalación que la dueña responde escribiendo directo en el chat queda sin `owner_outcome` para siempre (decisión de producto del 2026-10-06), y los envíos automáticos y de plantilla tampoco tienen resolución. El caso real lo cubre V7, más preciso. |
| **V4** | 18 entregas sin rastro en el historial | Pertenece a C-HIST-01, cuya cláusula (a) sigue en **E0** (nunca verificada con efecto real). Hay que separar hueco por diseño (sandbox) de hueco real **en esa ronda**, no a ciegas. |
| **V5** | cursor de recarga con 32 días | La recarga está **apagada a propósito** desde el 2026-09-06 (la sesión de Telethon es de la cuenta anterior). Encendido, avisaría todos los días de una decisión de producto. |
| **V6** | **error de SQL** | La consulta estaba **rota**: `profiles` no tiene columna `id` (su clave es `vip_id`). Ya arreglada devuelve 12 VIP activos sin perfil — un número que dejó de ser una falla cuando la ronda anterior quitó la búsqueda por parecido de `profiles` por ser huérfana. Falta que la dueña defina si un VIP sin perfil sigue importando. |

Dos cosas que valen para el método: **una consulta de vigilancia sin correr es una consulta sin verificar**
(V6 estuvo escrita y rota desde la ronda anterior), y **un vigilante que grita por datos viejos o por rutas de
diseño se termina ignorando** — que es peor que no tener ninguno.

### 9.3 Prueba de que la alarma suena

Un vigilante que solo sabe decir "todo bien" no sirve. Se saboteó el propio vigilante, contra la base real y
en solo lectura, con cuatro casos. Los cuatro muerden:

| Caso | Sabotaje | Resultado |
|---|---|---|
| A | quitarle a V1 la ventana de 2 días (mutación real de la consulta) | **alerta** por 2 ceros reales — prueba que el aviso se dispara con datos de verdad, y que la ventana es lo único que lo mantiene callado |
| B | desactivar en el ejecutor el filtro de sandbox | **alerta** por los 5 turnos de sandbox — prueba que el filtro está haciendo trabajo |
| C | agregar una consulta rota a propósito | sale como **"no pude revisar"**, nunca como "todo bien" |
| D | hacer ilegible el journal | V2 se informa como no revisable y **V1 y V7 siguen corriendo** |

Salida real del caso A y del caso C:

```
[V1] huellas semánticas NUEVAS en ceros (el incidente de agosto): 1 alerta(s) en 5 fila(s)
V1 · huellas semánticas NUEVAS en ceros (el incidente de agosto) (C-EMB-01)
• profiles: 2 nueva(s) en cero (histórico: 2)
Qué significa: Lo que Diana guarda queda con la huella vacía: existe, pero la búsqueda
por parecido no lo encuentra (el problema de agosto).

⚠️ No pude revisar: V9 (consulta rota a propósito): UndefinedColumnError: column
"columna_que_no_existe" does not exist
```

El envío por Telegram se verificó con un mensaje de confirmación real (no con un simulacro): si el canal
estuviera mal configurado, la primera alerta de verdad se habría perdido en silencio.

### 9.4 Límite honesto de este vigilante

Avisa por Telegram cuando algo falla, y calla cuando está todo bien. Ese silencio **no distingue "todo bien"
de "el vigilante no corrió"** (por ejemplo, si la máquina está apagada). Lo que hay para cubrir ese hueco:

- cada corrida deja su línea en `runtime/vigilantes.log` (se ve la última);
- **una falla del propio vigilante sí manda mensaje** — base inalcanzable, consulta rota, journal ilegible
  (casos C y D arriba). Un vigilante muerto no se parece a un vigilante tranquilo.

Lo que falta para cerrarlo del todo es un vigilante **externo** que avise si este deja de correr (un
"hombre muerto" en otro servicio). Queda anotado como pendiente, no como hecho.

---

## Anexo — reproducir todo

```bash
# 1. copia descartable
git worktree add -b sabotaje/fase2 /tmp/diana-sabotaje main

# 2. arnés de sabotaje (vive fuera del repo, no se commitea)
python3 /tmp/sabotaje/sabote.py                    # los 12 sabotajes
python3 /tmp/sabotaje/sabote.py SH_S1_dependencia_desconectada   # uno solo

# 3. salidas crudas de cada corrida
ls /tmp/sabotaje/out/                              # <sabotaje>.txt + informe.json

# 4. vigilancia E4 (§9) — correr a mano y ver qué haría, sin mandar nada
venv/bin/python scripts/vigilantes.py --dry-run
crontab -l | grep vigilantes                       # así quedó programada
cat runtime/vigilantes.log                         # latido de la última corrida
```

Batería completa: **12 sabotajes × 2 corridas = 24 corridas de las 8 pruebas, todas revertidas, 0 residuos.**
Salida cruda de la corrida íntegra: `/tmp/sabotaje/run2.log`; fallos por sabotaje: `/tmp/sabotaje/out/*.txt`.
