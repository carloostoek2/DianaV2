# Fase 2 — Pruebas E2 de C-SHADOW-01 y C-EMB-01

**Contratos:** `audit/contracts/C-SHADOW-01.md` (modo sombra) · `audit/contracts/C-EMB-01.md` (huellas semánticas)
**Rama:** `audit/pruebas-e2` (desde `main`). **Fecha:** 2026-10-08.
**Sin commit a `main`. Sin despliegue. Código de producción intacto** (ver §7).

---

## Resumen para la dueña

Se probaron con efecto real dos cosas que el sistema *promete* hacer y que hasta ahora solo estaban
verificadas leyendo el código: **el registro del modo sombra** (lo que Diana habría decidido sola,
contra lo que decidiste tú) y **las huellas semánticas** (los 384 números con los que Diana "busca por
parecido" lo que recuerda).

Las pruebas entran por donde entra la realidad: un mensaje de un VIP por el mismo camino que usa el bot
en producción, tus botones reales (aprobar, destacar, escribir una regla) y una base de datos Postgres
de verdad. Lo único falso es el modelo de lenguaje externo. **No se asertó "se llamó a tal función":
se leyeron filas reales en la base.**

Qué queda verificado:

| Promesa | Estado |
|---|---|
| Un turno de VIP entregado deja su fila con el veredicto de sombra y la nota del borrador | ✅ probado con fila real |
| Lo que tú decides (aprobaste tal cual) queda guardado **y no se borra** en un guardado posterior | ✅ probado, y es la regresión del defecto de septiembre |
| Con la bandera del círculo de aprendizaje apagada, no se escribe nada | ✅ probado encendiendo y apagando |
| Las rutas que no pasan por el pipeline (escalación por palabra clave y saludo de plantilla) no escriben fila, y es **a propósito** | ✅ probado, con el motivo visible |
| Un recuerdo, un ejemplo dorado y una regla se guardan con huella real (no en ceros) y la búsqueda por parecido los encuentra **primeros** | ✅ probado en las tres tablas |

**Lo importante para el negocio:** ninguna de estas 8 pruebas es decorativa. Se desconectó a propósito
cada pieza, una por una (8 sabotajes), y **las 8 pruebas fallaron como debían**. Eso es lo que
distingue "la prueba pasa" de "la prueba sirve": la evidencia está en §5.

**Lo que NO cambia:** nada para el VIP. No se tocó ni una línea del sistema que atiende los chats.

---

## 1. Cómo correrlas

Requiere Docker. El usuario no está en el grupo `docker` en esta sesión, así que se envuelve con `sg docker`:

```bash
cd /home/ubuntu/repos/DianaV2
sg docker -c ".venv/bin/python -m pytest tests/audit/test_C_SHADOW_01.py tests/audit/test_C_EMB_01_huellas.py -v -p no:randomly"
```

Carpeta de auditoría completa (incluye las pruebas de rondas anteriores):

```bash
sg docker -c ".venv/bin/python -m pytest tests/audit/ -q -p no:randomly"
```

Las pruebas de huellas cargan el modelo de embeddings real y van marcadas `@pytest.mark.slow`; se
pueden excluir con `-m "not slow"` cuando solo se quiere el resto.

---

## 2. Resultado real (2026-10-08)

```
$ sg docker -c ".venv/bin/python -m pytest tests/audit/test_C_SHADOW_01.py tests/audit/test_C_EMB_01_huellas.py -v -p no:randomly --no-header"
collected 8 items

tests/audit/test_C_SHADOW_01.py::test_a_turno_vip_entregado_deja_fila_con_veredicto_y_nota[bandera_on] PASSED [ 12%]
tests/audit/test_C_SHADOW_01.py::test_a_turno_vip_entregado_deja_fila_con_veredicto_y_nota[bandera_off] PASSED [ 25%]
tests/audit/test_C_SHADOW_01.py::test_b_lo_que_decide_la_duena_sobrevive_al_reguardado_del_turno PASSED [ 37%]
tests/audit/test_C_SHADOW_01.py::test_d_escalacion_por_palabra_clave_no_escribe_fila_por_diseno PASSED [ 50%]
tests/audit/test_C_SHADOW_01.py::test_d_saludo_de_plantilla_no_escribe_fila_por_diseno PASSED [ 62%]
tests/audit/test_C_EMB_01_huellas.py::test_memoria_del_turno_real_lleva_huella_y_se_recupera PASSED [ 75%]
tests/audit/test_C_EMB_01_huellas.py::test_ejemplo_dorado_destacado_lleva_huella_y_se_recupera PASSED [ 87%]
tests/audit/test_C_EMB_01_huellas.py::test_politica_de_zona_gris_lleva_huella_y_se_recupera PASSED [100%]
======================== 8 passed, 1 warning in 41.50s =========================
```

Carpeta de auditoría completa y línea base e2e, para descartar que se haya roto algo alrededor:

```
$ sg docker -c ".venv/bin/python -m pytest tests/audit/ -q -p no:randomly"
15 passed, 1 warning in 57.49s

$ sg docker -c ".venv/bin/python -m pytest tests/e2e -q -p no:randomly"
233 passed, 1 warning in 33.48s
```

`233 passed` es idéntico a `audit/LINEA-BASE-E2E.txt`: la línea base no se movió.

---

## 3. Qué prueba cada prueba

### `tests/audit/test_C_SHADOW_01.py` — contrato C-SHADOW-01

| Prueba | Cláusula | Qué asertó sobre filas reales |
|---|---|---|
| `test_a_...[bandera_on]` | (a) | Turno VIP entregado → **1 fila** en `turn_outcome_log` con `shadow_verdict` dentro del vocabulario (`send`/`blocked`/`escalate`/`doctrine`), `shadow_reason` no vacío y `draft_score` numérico en `(0, 1]` |
| `test_a_...[bandera_off]` | (c) | Mismo turno, bandera apagada → **0 filas**, y el turno igual se entregó (`status='delivered'`) |
| `test_b_...` | (b) | Tras aprobar: **1 fila** con `owner_outcome='approved_as_is'` y `sent_score` presente; después se dispara **dos veces** el re-guardado del mismo turno (el hook real post-turno y el `insert` crudo del repositorio) y `owner_outcome`, `sent_score` y `shadow_verdict` **siguen intactos** |
| `test_d_escalacion_...` | (d) | Escalación por palabra clave: turno `escalated`, **sin traza** en `pipeline_traces` (no entró al pipeline), **0 llamadas** al modelo, fila real en `escalation_events` con `tipo='pago_precio'`, **0 filas** en `turn_outcome_log` y **0 fallos tragados** en el log |
| `test_d_saludo_...` | (d) | Saludo de plantilla: **hay** traza con la comprensión del Analista, **no hay** evaluación, `decision.reason='plantilla_saludo'`, **0 filas** en `turn_outcome_log` y **0 fallos tragados** |

### `tests/audit/test_C_EMB_01_huellas.py` — contrato C-EMB-01

| Prueba | Camino real | Qué asertó |
|---|---|---|
| `test_memoria_...` | mensaje VIP → pipeline → aprobación de la dueña → extracción post-turno | Fila en `memories` con la huella de 384 dimensiones **idéntica** a la que produce el motor de producción para ese mismo texto (desvío máximo `< 1e-6`); el recuperador de memoria devuelve el hecho **primero** para una paráfrasis |
| `test_ejemplo_...` | mensaje VIP → botón **Destacar** → alcance "este VIP" | Fila dorada en `examples` (`quality='gold'`, no contraejemplo) con huella del motor real; el recuperador de ejemplos lo devuelve **primero** |
| `test_politica_...` | mensaje VIP sin regla → zona gris → botón **Escribir regla** + texto libre → confirmar alcance | Fila viva en `policies` (`is_active=true`) con `trigger_description` = la pregunta del VIP y huella del motor real; el recuperador de reglas la devuelve **primero** |

Las tres verifican lo mismo en el fondo: la huella **no es el vector de ceros** (el disfraz que en
agosto dejó ejemplos y políticas invisibles sin error), tiene 384 dimensiones, y **la produjo el motor
real** — no un relleno que casualmente no es cero.

---

## 4. Matriz de bandera (`feature_autonomy_quality_enabled`)

| Estado | Efecto medido |
|---|---|
| **ON** | El turno entregado deja su fila con veredicto y nota; la resolución de la dueña se guarda en esa misma fila |
| **OFF** | Ninguna escritura. El turno se entrega igual: el apagado **no rompe** el turno, solo deja de medir |

El caso OFF es el que hace fuerte al caso ON: si la prueba solo corriera encendida, "hay 1 fila" podría
ser casualidad. Al medir los dos estados con la misma prueba, la fila queda atribuida a la bandera.

Las pruebas de huellas encienden solo la bandera de su propio camino (`feature_memory_enabled`,
`feature_quality_feedback_enabled` + `feature_staging_enabled`, `feature_gray_zone_enabled`) para que un
hueco no se pueda atribuir a otra pieza.

---

## 5. Falsabilidad — evidencia para el Saboteador (E3)

Una prueba que pasa a la primera **no se da por buena**. Antes de entregarla se desconectó a propósito
cada pieza (mutación temporal sobre el código de producción, **siempre revertida**; ver §7) y se exigió
que la prueba fallara. Los 8 casos:

| # | Pieza desconectada | Prueba exigida | Resultado observado |
|---|---|---|---|
| M1 | Bandera del círculo apagada sin efecto: `enabled=True` **y** las dos compuertas de `composition` pasando el servicio siempre | `test_a...[bandera_off]` | **FALLA** — `assert 1 == 0` (apareció la fila que no debía) |
| M2 | Upsert vuelve al estado previo al commit `3ade3b3` (`ON CONFLICT` pisa con `EXCLUDED`) | `test_b_...` | **FALLA** — `owner_outcome` quedó en `None` |
| M3 | Se quita la llamada post-turno `_run_outcome_log` | `test_a...[bandera_on]` | **FALLA** — 0 filas donde se esperaba 1 |
| M4 | Huella de ejemplo forzada a ceros (`examples`, `embedding or [0.0]*384`) | `test_ejemplo_...` | **FALLA** — "la huella quedó en ceros" |
| M5 | Huella de memoria forzada a ceros (caché de `memory_extraction_service`) | `test_memoria_...` | **FALLA** — "la huella quedó en ceros" |
| M6 | Huella de política no disponible (`embed_policy_text` → `None`) | `test_politica_...` | **FALLA** — "la huella quedó en ceros" |
| M7 | Atajo de saludo desactivado (el mensaje cae al pipeline completo) | `test_d_saludo_...` | **FALLA** — apareció evaluación en la traza |
| M8 | Escalación determinística J.4 desactivada | `test_d_escalacion_...` | **FALLA** — el turno quedó `pending_approval`, no `escalated` |

Salida consolidada del arnés:

```
[M1_bandera_off_sin_efecto] → FALLA (esperado FALLA) OK muerde
[M2_upsert_pisa_columnas_duena] → FALLA (esperado FALLA) OK muerde
[M3_sin_llamada_post_turno] → FALLA (esperado FALLA) OK muerde
[M4_huella_de_ejemplo_en_ceros] → FALLA (esperado FALLA) OK muerde
[M5_huella_de_memoria_en_ceros] → FALLA (esperado FALLA) OK muerde
[M6_politica_sin_huella] → FALLA (esperado FALLA) OK muerde
[M7_saludo_sin_atajo] → FALLA (esperado FALLA) OK muerde
[M8_escalacion_deterministica_apagada] → FALLA (esperado FALLA) OK muerde
```

### 5.1 Dos mutaciones que NO mordieron (y qué enseñaron)

Queda constancia porque son la parte útil para el Saboteador: el primer intento de sabotaje **no**
alcanzó para tumbar la prueba, y eso obligó a encontrar el punto real.

- **M1 al primer intento** (pasar el servicio ignorando la bandera en `composition`) → la prueba siguió
  pasando. La bandera **no tiene un solo candado, tiene tres**: `enabled=` al construir
  `OutcomeLogService` (`composition.py:731`) y las dos compuertas `outcome_log if ... else None`
  (`composition.py:853` y `:1282`). Un sabotaje de un solo punto no alcanza; hay que anular las dos
  compuertas **y** el `enabled`. Es defensa en profundidad real, no un candado decorativo.
- **M5 al primer intento** (forzar ceros en `memory_backfill_service.py`) → la prueba siguió pasando,
  porque la extracción post-turno **no pasa por ese archivo**: usa `memory_extraction_service.py`, y
  dentro de él el embedding se sirve de una caché que se llena antes (`_dedup_semantic`), así que mutar
  el `if emb is None` es código muerto en ese camino. El punto que manda es el llenado de la caché.

Ambos quedaron resueltos y las mutaciones finales muerden. Se dejan anotados como **pistas de sabotage
para E3**, no como pendientes.

---

## 6. Límites — lo que estas pruebas NO prueban

- **La reacción del VIP (`vip_signal`, C3)** no se cubre aquí: se dispara por el mensaje siguiente del
  VIP o por el job de respaldo (`jobs/outcome_reaction.py`). Queda para una ronda propia.
- **Los tramos `corregir` y `escalar`** de `owner_outcome` no están cubiertos: se probó
  `approved_as_is`. La ficha menciona los tres valores; los otros dos quedan pendientes.
- **El tramo `profiles` de C-EMB-01** ya estaba cubierto por `tests/audit/test_C_EMB_01.py` (ronda
  anterior) y no se re-midió aquí.
- **La bandera real del `.env` de producción** no es verificable desde las pruebas: estas encienden y
  apagan la bandera en memoria. Qué valor tiene hoy en producción es otra verificación.
- Las pruebas **no** cubren los fallos tragados que sí quedarían en producción si algo se rompe en
  runtime: solo se asertó que en estos caminos felices **no** hubo ninguno.

---

## 7. Garantía de que producción quedó intacta

Las mutaciones de §5 se aplicaron y se revirtieron dentro del mismo arnés (`finally`), que además
compara el árbol con `git diff` al terminar. Estado final del repositorio:

```
$ git status --short
 M pyproject.toml
?? tests/audit/test_C_EMB_01_huellas.py
?? tests/audit/test_C_SHADOW_01.py

$ git diff
--- a/pyproject.toml
+++ b/pyproject.toml
@@ markers = [
     "db: Tests that require a real PostgreSQL database via testcontainers.",
+    "slow: Tests that load the real embedding model (deselect with '-m \"not slow\"').",
 ]
```

**`src/` sin un solo cambio.** Lo único modificado es `pyproject.toml`, y solo para **registrar el
marcador `slow`** que las pruebas de huellas ya usaban: sin registrarlo, pytest emitía un aviso por
marcador desconocido en cada corrida. No es código de producción.

---

## 8. Siguiente paso

Entregar a **E3 (Saboteador)** con las 8 mutaciones de §5 ya identificadas, incluida la advertencia de
§5.1: M1 exige sabotaje compuesto (tres compuertas) y M5 debe atacar el llenado de la caché de
`memory_extraction_service`, no el `if emb is None`.
