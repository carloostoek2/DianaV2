# Fase 2 — Sabotaje E3, ronda 2: historial, resoluciones del sombra y Reprender

**Contratos saboteados:** `audit/contracts/C-HIST-01.md` (a) · `audit/contracts/C-SHADOW-01.md` · `audit/contracts/C-EMB-01.md`
**Pruebas exigidas:** `tests/audit/test_C_HIST_01_captura.py` (7 casos) · `tests/audit/test_C_SHADOW_01_resoluciones.py` (7 casos) · `tests/audit/test_C_EMB_01_reprender.py` (3 casos) — 17 en total
**Copia descartable:** copia de trabajo en `/tmp/diana-sabotaje-r2`, rama `sabotaje/fase2-r2` desde `main` (`45a1a7e`) — retirada al terminar (§8). **Fecha:** 2026-10-13.
**Rol:** Saboteador independiente de quien escribió las pruebas de la ronda 2.
**Sin commit a `main`. Sin despliegue. Código de producción intacto** (todas las mutaciones se aplicaron y revirtieron en la copia; ver §8).

---

## Resumen para la dueña

Se hizo la prueba que faltaba sobre las 17 pruebas nuevas: **desconectar a propósito cada pieza** y exigir que la prueba falle. Una prueba que sigue en verde después de arrancarle la pieza que dice cuidar no sirve para nada: es decorativa.

Se aplicaron **34 sabotajes**: 21 de la lista obligatoria (dependencia en `None`, bandera apagada, la pieza lanza, resultado vacío, llamador cortado, orden cambiado) y 13 diseñados para esta ronda (los más útiles: guardar un id corrido, escribir la fila dos veces, reparar el defecto abierto, apuntar la reacción al turno equivocado, dejar el contraejemplo sin su alcance).

**32 de los 34 hacen fallar la prueba que debían.** Los 2 que no mordieron no son pruebas decorativas: son dos **afirmaciones sueltas dentro de pruebas que sí sirven** (§6). Las dos están en la prueba del sombra y las dos son afirmaciones que "suenan" más fuertes de lo que en realidad comprueban. Se devuelven al Probador con el sabotaje que sobrevivió y la corrección concreta.

| Qué se le arrancó al sistema (en lenguaje llano) | Pruebas que lo delataron |
|---|---|
| La escritura del historial: el cable, la llamada, el emparejado texto ↔ número de mensaje | 5 de las 7 pruebas de historial |
| El rastro que explica por qué en una sesión de prueba **no** se escribe | 1 |
| La bandera de la promoción y la de la sesión de prueba | 2 |
| El libro de resultados del sombra: el cable, la decisión de la dueña, la nota de lo enviado | 6 de las 7 pruebas del sombra |
| El gancho de reacción del VIP y el job de respaldo | 3 |
| La lección de "Reprender": la promoción, la huella real, su alcance y su recuperación | las 3 pruebas de Reprender |

**Lo importante para el negocio:** las 17 pruebas pasan de "funciona" a **E3**, que es el nivel que exige evidencia de fallo. Lo que afirman se puede confiar: cada mensaje que Diana manda deja su fila con el número de mensaje **exacto** que devolvió Telegram (no un número cualquiera), la decisión de la dueña queda registrada y **no la pisa** el guardado posterior, y la lección de "Reprender" tiene una huella real que la búsqueda encuentra de verdad (no el vector de ceros del incidente de agosto).

**Un dato relevante:** la prueba marcada como "fallo esperado" (el job de respaldo no puede clasificar la respuesta del VIP) **está bien atada a su defecto**: al reparar el defecto en su punto exacto, la prueba pasa a verde y su marca estricta la delata. No es una prueba que se esconde detrás de un "se permite fallar".

**Dos hallazgos colaterales, para tener presentes** (§7): la bandera de la promoción y la de Destacar/Reprender están puestas **en dos lugares cada una** (el teclado y el corazón de la pieza). Eso es bueno para la seguridad, pero significa que apagar una sola no alcanza para apagar la función — hay que revisar las dos.

**Lo que NO cambia:** nada para el VIP ni para la operación. No se tocó el sistema que corre: cada mutación vivió en una copia de trabajo y se revirtió antes de pasar a la siguiente.

---

## 1. Método

El sabotaje va siempre sobre una **copia descartable**, nunca sobre el repositorio de trabajo ni sobre lo que corre el bot. Por cada sabotaje el ejecutor hace cinco pasos y falla si alguno no se cumple:

1. **Exige el árbol sin cambios** (`git status --porcelain src` vacío) antes de mutar.
2. **Muta** con anclas exactas: si el ancla no aparece **una sola vez**, aborta (evita sabotear "parecido" y creer que se saboteó).
3. **Registra el árbol mutado** (`git diff --stat src`) antes de ejecutar.
4. **Corre las 17 pruebas completas** — no solo la que debería fallar: así también se ve qué **no** falla, y se detectan efectos cruzados.
5. **Revierte** (`git checkout -- src`) y **vuelve a exigir el árbol limpio** antes del sabotaje siguiente.

```bash
# copia descartable
git worktree add -b sabotaje/fase2-r2 /tmp/diana-sabotaje-r2 main

# ejecutor (vive fuera del repositorio)
python3 /tmp/sabotaje-r2/run.py              # todos los trabajos
python3 /tmp/sabotaje-r2/run.py H1 H6        # un subconjunto

# por dentro, cada corrida es:
DIANA_E2E_COPY_DUMP=.../runtime/e2e_copy/diana_copy.sql \
  .venv/bin/python -m pytest \
    tests/audit/test_C_HIST_01_captura.py \
    tests/audit/test_C_SHADOW_01_resoluciones.py \
    tests/audit/test_C_EMB_01_reprender.py \
    -v -p no:randomly --no-header
```

El sabotaje no se simula: se corre el mismo Postgres real, el mismo `build_app` y el mismo motor de huellas que la prueba ya usaba. Lo único falso sigue siendo el modelo de lenguaje externo y la salida a Telegram.

### 1.1 Línea base (antes de tocar nada)

```
$ pytest tests/audit/test_C_HIST_01_captura.py \
         tests/audit/test_C_SHADOW_01_resoluciones.py \
         tests/audit/test_C_EMB_01_reprender.py -v -p no:randomly --no-header
16 passed, 1 xfailed, 1 warning in 22.77s
```

### 1.2 Línea base otra vez (al cerrar, con el árbol ya limpio)

```
$ pytest <mismas tres pruebas> -q -p no:randomly --no-header
16 passed, 1 xfailed, 1 warning in 22.07s
```

Verde antes y después: nada de lo aplicado y revertido dejó rastro.

### 1.3 Comprobación de que la mutación fue la que corrió

Cada corrida dejó registrado el árbol mutado (`git diff --stat src`) **antes** de ejecutar, y ningún sabotaje se aplicó sobre un árbol sucio ni dejó el árbol sucio. El ejecutor además **aborta** cuando el ancla no aparece exactamente una vez (pasó dos veces durante la preparación y se corrigió el ancla: ver §4, notas de método de S6, E5 y H11), lo que descarta sabotear "parecido" y creer que se saboteó.

Las corridas tardaron entre **17,5 y 29,2 s** (la horquilla la explican las tres pruebas que cargan el modelo real de huellas). El tiempo **no** se usa aquí como prueba de que la mutación entró: la prueba de que entró es que el ejecutor registró el árbol mutado antes de correr y que la prueba falló en el punto esperado. El único caso donde la mutación *no* entró a la primera se documenta explícitamente: H13, cuyo primer intento quedó neutralizado por una reasignación posterior de la misma variable (§4).

---

## 2. Resultado por prueba (las 17 instancias)

| # | Prueba (instancia) | Sabotajes que la hacen fallar | Nivel |
|---|---|---|---|
| 1 | `test_C_HIST_01_captura.py::test_entrega_normal_deja_fila_con_texto_y_su_id_de_telegram` | H1, H3, H4, H5, H8*, H9*, H10 | **E3** |
| 2 | `test_C_HIST_01_captura.py::test_correccion_deja_fila_con_el_texto_corregido_y_su_id` | H1, H3, H4, H5, H8*, H9*, H10 | **E3** |
| 3 | `test_C_HIST_01_captura.py::test_recontacto_deja_fila_con_texto_y_su_id_de_telegram` | H2, H4, H5, H8*, H9* | **E3** |
| 4 | `test_C_HIST_01_captura.py::test_matriz_sandbox_decide_si_la_entrega_deja_historial[sin_sandbox_escribe]` | H1, H3, H4, H5, H9*, H10 | **E3** |
| 5 | `test_C_HIST_01_captura.py::test_matriz_sandbox_decide_si_la_entrega_deja_historial[sandbox_no_escribe]` | H3, H6, H10, H12* | **E3** |
| 6 | `test_C_HIST_01_captura.py::test_promocion_a_un_chat_que_no_es_vip_no_deja_historial_por_diseno[promo_on]` | H7* | **E3** |
| 7 | `test_C_HIST_01_captura.py::test_promocion_a_un_chat_que_no_es_vip_no_deja_historial_por_diseno[promo_off]` | H11, H13* | **E3** |
| 8 | `test_C_SHADOW_01_resoluciones.py::test_corregir_guarda_owner_outcome_corrected[bandera_on]` | S1, S2, S3, S9, S11* | **E3** |
| 9 | `test_C_SHADOW_01_resoluciones.py::test_corregir_guarda_owner_outcome_corrected[bandera_off]` | S12 | **E3** |
| 10 | `test_C_SHADOW_01_resoluciones.py::test_escalar_guarda_owner_outcome_escalated[bandera_on]` | S1, S2, S3, S9, S11* | **E3** |
| 11 | `test_C_SHADOW_01_resoluciones.py::test_escalar_guarda_owner_outcome_escalated[bandera_off]` | S12 | **E3** |
| 12 | `test_C_SHADOW_01_resoluciones.py::test_reaccion_del_vip_por_el_mensaje_siguiente` | S4, S7*, S9, S11* | **E3** |
| 13 | `test_C_SHADOW_01_resoluciones.py::test_job_de_respaldo_marca_silencio_cuando_el_vip_no_contesta` | S5, S9, S11* | **E3** |
| 14 | `test_C_SHADOW_01_resoluciones.py::test_job_de_respaldo_clasifica_la_respuesta_que_no_paso_por_el_pipeline` (xfail estricto) | S6* | **E3** |
| 15 | `test_C_EMB_01_reprender.py::test_reprender_deja_contraejemplo_con_huella_real_y_se_recupera` | E1, E2, E3, E4, E6*, E7*, E8* | **E3** |
| 16 | `test_C_EMB_01_reprender.py::test_matriz_sin_la_pieza_cableada_no_hay_contraejemplo[sin_feedback]` | E5 | **E3** |
| 17 | `test_C_EMB_01_reprender.py::test_matriz_sin_la_pieza_cableada_no_hay_contraejemplo[sin_staging]` | E9 | **E3** |

`*` = sabotaje propio, fuera de la lista S1–S6 (§5).

**Ninguna prueba quedó decorativa: las 17 tienen al menos un sabotaje que las hace fallar.**

### 2.1 Cobertura de la lista obligatoria

| Sabotaje | Trabajos | Mordió |
|---|---|---|
| S1 — Desconectar dependencia (`None`) | H3 | 1 de 1 |
| S2 — Apagar bandera | H6, H11, S12, E5, E9 | 5 de 5 |
| S3 — Romper la pieza (lanza) | H4, E3 | 2 de 2 |
| S4 — Vaciar el resultado | H5, S2, S3, S5, S9, E2 | 6 de 6 |
| S5 — Cortar el llamador | H1, H2, S1, S4, E1, E4 | 6 de 6 |
| S6 — Cambiar el orden | H10 | 1 de 1 |
| **Total lista** | | **21 de 21** |

---

## 3. Detalle de los sabotajes de la lista (con evidencia cruda)

### H1 — Cortar el llamador del historial (camino de la dueña) · S5

**Mutación:** en `src/diana/application/admin_service.py` se comenta la llamada a `append_owner_delivery_history` que escribe la fila cuando la dueña aprueba o corrige.

**Debía fallar:** entrega normal, corrección, matriz sandbox (sin sandbox).

```
$ pytest <las 3 pruebas> -v
tests/audit/.../test_entrega_normal_deja_fila_con_texto_y_su_id_de_telegram FAILED
tests/audit/.../test_correccion_deja_fila_con_el_texto_corregido_y_su_id FAILED
tests/audit/.../test_matriz_sandbox_decide_si_la_entrega_deja_historial[sin_sandbox_escribe] FAILED
E   AssertionError: se esperaba UNA fila de historial, hay 0: []
E   AssertionError: se esperaba UNA fila, hay 0: []
=================== 3 failed, 13 passed, 1 xfailed ===================
```

### H2 — Cortar el llamador del historial (recontacto) · S5

**Mutación:** en `src/diana/application/recontact_service.py` se comenta la llamada equivalente del recontacto automático.

```
tests/audit/.../test_recontacto_deja_fila_con_texto_y_su_id_de_telegram FAILED
E   AssertionError: el recontacto entregado no dejó su fila de historial: []
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### H3 — Dependencia en `None` (cableado del historial) · S1

**Mutación:** en `src/diana/composition.py`, `AdminService` recibe `history=None`. La pieza existe, pero nunca llega a quien la usa.

```
tests/audit/.../test_entrega_normal_deja_fila_con_texto_y_su_id_de_telegram FAILED
tests/audit/.../test_correccion_deja_fila_con_el_texto_corregido_y_su_id FAILED
tests/audit/.../test_matriz_sandbox_decide_si_la_entrega_deja_historial[sin_sandbox_escribe] FAILED
tests/audit/.../test_matriz_sandbox_decide_si_la_entrega_deja_historial[sandbox_no_escribe] FAILED
tests/audit/.../test_reprender_deja_contraejemplo_con_huella_real_y_se_recupera FAILED
=================== 5 failed, 11 passed, 1 xfailed ===================
```

**Efecto cruzado que vale la pena registrar:** este sabotaje también tumba la prueba de Reprender (§7.2), y tumba el caso de la **sesión de prueba** aunque ese caso espera **cero** filas. El motivo es correcto: con el cable cortado tampoco se emite el aviso `owner_history_skipped_sandbox`, y esa prueba exige el **rastro del motivo**, no solo la ausencia de la fila. Es exactamente la diferencia entre una prueba que comprueba "no pasó nada" y una que comprueba "no pasó nada **y sabemos por qué**".

### H4 — La pieza lanza (escritura del historial) · S3

**Mutación:** `append_owner_delivery_history` lanza `RuntimeError` dentro de su `try` por fila. El `except` lo traga y deja el evento `owner_history_append_failed`.

**Debía fallar:** las tres entregas + el caso sin sandbox (la prueba exige que ese evento **no** aparezca).

```
tests/audit/.../test_entrega_normal... FAILED
tests/audit/.../test_correccion... FAILED
tests/audit/.../test_recontacto... FAILED
tests/audit/.../test_matriz_sandbox...[sin_sandbox_escribe] FAILED
E   AssertionError: se esperaba UNA fila de historial, hay 0: []
=================== 4 failed, 12 passed, 1 xfailed ===================
```

### H5 — Resultado vacío (el emparejado no devuelve nada) · S4

**Mutación:** `build_owner_history_pairs` devuelve lista vacía: no se escribe ninguna fila y sin error visible.

```
E   AssertionError: se esperaba UNA fila de historial, hay 0: []
=================== 4 failed, 12 passed, 1 xfailed ===================
```

### H6 — Apagar la sesión de prueba (sandbox que sí persiste) · S2

**Mutación:** `SandboxService.should_persist` devuelve siempre `True`: la sesión de prueba deja de ser efímera.

```
tests/audit/.../test_matriz_sandbox_decide_si_la_entrega_deja_historial[sandbox_no_escribe] FAILED
E   AssertionError: assert True is False
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### H10 — Cambiar el orden: la fila se escribe ANTES de aprobar · S6

**Mutación:** al crear el borrador en cola se escribe ya la fila del historial (con el borrador), antes de que la dueña decida.

```
tests/audit/.../test_entrega_normal... FAILED
tests/audit/.../test_correccion... FAILED
tests/audit/.../test_matriz_sandbox...[sin_sandbox_escribe] FAILED
tests/audit/.../test_matriz_sandbox...[sandbox_no_escribe] FAILED
E   AssertionError: apareció una fila de historial ANTES de que la dueña aprobara
E   AssertionError: se esperaba UNA fila, hay 2: [{'text': 'Claro, quedamos así.', ...
=================== 4 failed, 12 passed, 1 xfailed ===================
```

### S1 — Cortar el cableado del libro de resultados (admin) · S5

**Mutación:** en `src/diana/composition.py`, `AdminService` recibe `outcome=None`: la decisión de la dueña ya no queda registrada.

```
tests/audit/.../test_corregir_guarda_owner_outcome_corrected[bandera_on] FAILED
tests/audit/.../test_escalar_guarda_owner_outcome_escalated[bandera_on] FAILED
E   AssertionError: la corrección no quedó registrada como 'corrected': {'shadow_verdict': 'send', ...
                                                                        'owner_outcome': None, ...}
E   AssertionError: la escalación no quedó registrada: {'shadow_verdict': 'send', ...
                                                       'owner_outcome': None, ...}
=================== 2 failed, 14 passed, 1 xfailed ===================
```

### S2 — Resultado vacío: la decisión de la dueña no se guarda · S4

**Mutación:** `OutcomeLogService.record_owner_outcome` devuelve `None` antes de escribir.

```
E   AssertionError: la corrección no quedó registrada como 'corrected': {..., 'owner_outcome': None, ...}
E   AssertionError: la escalación no quedó registrada: {..., 'owner_outcome': None, ...}
=================== 2 failed, 14 passed, 1 xfailed ===================
```

### S3 — Vaciar la nota de lo enviado · S4

**Mutación:** la resolución se guarda como si fuera una aprobación simple, sin la nota del texto enviado.

```
E   AssertionError: la corrección no quedó registrada como 'corrected': {..., 'owner_outcome': 'approved_as_is', ...}
E   AssertionError: la escalación no quedó registrada: {..., 'owner_outcome': 'approved_as_is', ...}
=================== 2 failed, 14 passed, 1 xfailed ===================
```

### S4 — Cortar el gancho de la reacción del VIP · S5

**Mutación:** el orquestador deja de llamar al gancho que clasifica el mensaje siguiente del VIP.

```
tests/audit/.../test_reaccion_del_vip_por_el_mensaje_siguiente FAILED
E   AssertionError: el mensaje siguiente del VIP no dejó su reacción en el turno anterior: [...]
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### S5 — El job de respaldo nunca encuentra silencio · S4

**Mutación:** `first_vip_followup_text` devuelve siempre un texto: la rama de silencio es inalcanzable.

```
tests/audit/.../test_job_de_respaldo_marca_silencio_cuando_el_vip_no_contesta FAILED
E   AssertionError: el VIP no contestó y el job no marcó silencio: [...]
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### S9 — Vaciar el veredicto del sombra al resolver la dueña · S4

**Mutación:** en `src/diana/infrastructure/db/repositories/turn_outcome.py`, la actualización de la resolución pisa `shadow_verdict` con `None` (el defecto histórico del guardado que borra lo ajeno).

**Debía fallar:** las dos resoluciones con bandera encendida (y, de arrastre, las dos de reacción).

```
tests/audit/.../test_corregir...[bandera_on] FAILED
tests/audit/.../test_escalar...[bandera_on] FAILED
tests/audit/.../test_reaccion_del_vip_por_el_mensaje_siguiente FAILED
tests/audit/.../test_job_de_respaldo_marca_silencio_cuando_el_vip_no_contesta FAILED
E   AssertionError: la resolución de la dueña falló en silencio: ['outcome_record_owner_failed']
E   AssertionError: la escalación falló en silencio: ['outcome_record_owner_failed']
=================== 4 failed, 12 passed, 1 xfailed ===================
```

### S12 — Escribir el libro de resultados con la bandera apagada · S2

**Mutación:** el libro se enciende y se cablea sin mirar su bandera (tres puntos: `enabled=True`, el cableado al administrador y el cableado al orquestador).

**Debía fallar:** los dos casos **apagados** (que exigen cero filas).

```
tests/audit/.../test_corregir...[bandera_off] FAILED
tests/audit/.../test_escalar...[bandera_off] FAILED
E   AssertionError: con la bandera en False se esperaban 0 fila(s): [{'shadow_verdict': 'send', ...
                                                                   'owner_outcome': 'corrected', ...}]
E   AssertionError: la fila de sombra no existía antes de escalar: [{'shadow_verdict': 'send', ...}]
=================== 2 failed, 14 passed, 1 xfailed ===================
```

### E1 — Cortar el llamador de la promoción a contraejemplo · S5

**Mutación:** en `handle_reprimand`, el botón de confirmar ya no promueve la lección a contraejemplo.

```
tests/audit/.../test_reprender_deja_contraejemplo_con_huella_real_y_se_recupera FAILED
E   AssertionError: el candidato no quedó promocionado: [{'candidate_type': 'example', 'status': 'pending'}]
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### E2 — Huella en ceros (el disfraz del incidente de agosto) · S4

**Mutación:** el contraejemplo se guarda con el vector de ceros: la fila existe pero es invisible para la búsqueda por parecido.

```
E   AssertionError: examples (contraejemplo): la huella quedó en ceros
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### E3 — La pieza lanza (el motor de huellas) · S3

**Mutación:** el cálculo de la huella lanza `RuntimeError` durante la promoción.

```
E   AssertionError: el candidato no quedó promocionado: [{'candidate_type': 'example', 'status': 'pending'}]
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### E4 — Cortar el recuperador de contraejemplos · S5

**Mutación:** el recuperador de ejemplos deja de incluir los contraejemplos en lo que devuelve al pipeline.

```
E   AssertionError: el recuperador de ejemplos no devolvió nada
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### E5 — Atender el botón con la bandera apagada · S2

**Mutación (dos puntos):** se anula la exigencia de bandera en el servicio **y** la puerta de arranque del teclado en `src/diana/telegram/handlers/callbacks.py`.

**Nota de método:** el primer intento (solo el servicio) **sobrevivió**. No era una prueba decorativa: era una **guarda redundante**. La bandera está puesta en el teclado *y* en el corazón de la pieza; con una sola anulada, el botón ni arranca. Al anular las dos, la prueba falla como debe.

```
tests/audit/.../test_matriz_sin_la_pieza_cableada_no_hay_contraejemplo[sin_feedback] FAILED
E   AssertionError: quedó un candidato de staging con la pieza apagada
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### E9 — La pieza de staging se cablea con su bandera apagada · S2

**Mutación:** en `src/diana/composition.py`, el servicio de candidatos se construye siempre (`if True:`), ignorando su bandera.

```
tests/audit/.../test_matriz_sin_la_pieza_cableada_no_hay_contraejemplo[sin_staging] FAILED
E   AssertionError: con la bandera apagada igual quedó un contraejemplo: [{'embedding': '[0.064...
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### H11 — Promoción que corre con su bandera apagada · S2

**Mutación (dos puntos):** se ignora la bandera en el portero del medio (`middlewares/auth.py`) **y** en el servicio de promoción (`promo_service.py`).

**Nota de método:** igual que E5, el primer intento (solo el portero) **sobrevivió** por la misma razón: la bandera está en dos lugares.

```
tests/audit/.../test_promocion_a_un_chat_que_no_es_vip_no_deja_historial_por_diseno[promo_off] FAILED
E   AssertionError: con la promoción apagada se creó un turno (1): la medición del caso encendido no vale
=================== 1 failed, 15 passed, 1 xfailed ===================
```

---

## 4. Sabotajes propios (fuera de la lista S1–S6)

Los 13 sabotajes propios buscan lo que la lista no busca: **valores plausibles pero equivocados**, **efectos de relleno**, **rastros que se pierden** y **reparar el defecto** para ver si la prueba de verdad lo persigue.

### H8 · P1 — El número de mensaje desplazado

**Qué hace:** el emparejado guarda un número corrido en uno. La fila existe, tiene número no nulo… pero no es el del envío.

**Por qué importa:** distingue "guardó un número cualquiera" de "guardó **ese** número".

```
tests/audit/.../test_entrega_normal... FAILED
tests/audit/.../test_correccion... FAILED
tests/audit/.../test_recontacto... FAILED
E   AssertionError: el id guardado no es ninguno de los que el canal devolvió: 5008 vs [5006, 5007]
E   AssertionError: el id guardado no es el del envío: {'text': 'Hola, qué lindo leerte de nuevo...',
                                                        'telegram_message_id': 5008, ...}
=================== 3 failed, 13 passed, 1 xfailed ===================
```

### H9 · P2 — La fila se escribe dos veces

**Qué hace:** la entrega deja dos filas idénticas. La prueba exige **una**.

```
E   AssertionError: se esperaba UNA fila de historial, hay 2: [{'text': 'Claro, quedamos así.', 'telegram_message_id': 5007, ...}, ...
=================== 4 failed, 12 passed, 1 xfailed ===================
```

### H7 · P3 (control positivo) — Añadir un llamador donde el contrato dice que NO hay

**Qué hace:** la promoción a un chat que no es VIP pasa a escribir historial.

**Por qué importa:** es el control del "hueco por diseño". Una prueba que solo comprueba ausencia puede pasar por accidente (porque nada se ejecutó). Aquí se demuestra que la prueba **detecta** la escritura si ocurriera.

```
tests/audit/.../test_promocion_a_un_chat_que_no_es_vip...[promo_on] FAILED
E   AssertionError: la promoción escribió historial: la clasificación de los 18 casos del vigilante V4 cambia
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### H12 · P10 — La omisión en sesión de prueba se queda sin rastro del motivo

**Qué hace:** la fila se sigue omitiendo (igual que debe), pero se borra el aviso que explica **por qué**.

**Por qué importa:** distingue "no hay fila" de "no hay fila **y sabemos que fue a propósito**". Es la diferencia entre una prueba que acepta cualquier silencio y una que exige que el silencio esté justificado.

```
tests/audit/.../test_matriz_sandbox...[sandbox_no_escribe] FAILED
E   AssertionError: la omisión en sandbox no dejó rastro del motivo: ['sandbox_activated',
    'vip_history_skipped_sandbox', 'coordinate_result', 'turn_begun', ...]
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### H13 · P11 — La puerta de atención se abre sola con la promoción apagada

**Qué hace:** con la promoción apagada nadie abrió la ventana de atención, pero la puerta se da por abierta: el mensaje entra al pipeline y crea turno.

**Por qué importa:** es "media configuración" — el caso apagado deja de ser inofensivo (`turnos == 0`) sin que nada avise.

```
tests/audit/.../test_promocion_a_un_chat_que_no_es_vip...[promo_off] FAILED
E   AssertionError: con la promoción apagada se creó un turno (1): la medición del caso encendido no vale
E   assert 1 == 0
tests/audit/test_C_HIST_01_captura.py:746: AssertionError
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### S6 · P3 — Reparar el defecto abierto (la prueba marcada como fallo esperado)

**Qué hace:** se repara el defecto en su **punto exacto** — el historial entrega la fecha como texto (`rows_to_recent_messages`, `src/diana/infrastructure/db/repositories/history.py`), no el job.

**Por qué importa:** es la única forma honesta de sabotear una prueba marcada como "se permite fallar". Si la marca es honesta, al reparar el defecto la prueba **pasa a verde inesperado** y la marca estricta la delata como fallo. Si la marca fuera una excusa, seguiría en rojo.

```
tests/audit/.../test_job_de_respaldo_clasifica_la_respuesta_que_no_paso_por_el_pipeline FAILED
[XPASS(strict)] DEFECTO ABIERTO (medido 2026-10-10): la rama de clasificación del job de respaldo
no puede dispararse. `first_vip_followup_text` descarta toda fila cuyo `timestamp` no sea `datetime`,
pero el historial real (`rows_to_recent_messages`, .../history.py:33) entrega el timestamp como texto ISO. ...
=================== 1 failed, 16 passed ===================
```

**Conclusión: la marca está bien atada al defecto.** Reparado el defecto, la prueba completa pasa.

**Nota de método honesta:** el primer intento de este sabotaje lo puse dentro del job (convirtiendo el texto a fecha al leerlo) y **no mordió**. Al mirar el porqué, la prueba muere **antes** de llegar al job: su propia comprobación previa exige `isinstance(marca, datetime)` sobre la fila sembrada, y esa comprobación falla con el texto ISO. Es decir, la prueba tiene **dos** puntos de fallo encadenados al mismo defecto, y el primero es la premisa. Reparar el punto real es lo que la destraba.

### S7 · P4 — Objetivo equivocado: la reacción se escribe en el turno nuevo

**Qué hace:** el gancho resuelve el turno que acaba de llegar en vez del turno entregado anterior.

**Por qué importa:** prueba que la prueba exige que la reacción quede en el turno **anterior**, no en cualquier turno.

```
tests/audit/.../test_reaccion_del_vip_por_el_mensaje_siguiente FAILED
E   AssertionError: el mensaje siguiente del VIP no dejó su reacción en el turno anterior: [...]
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### S11 · SONDA — Veredicto del sombra fuera del vocabulario

**Qué hace:** mismo punto que S10 (abajo) pero con un valor **inválido**.

**Por qué importa:** es la sonda que prueba que S10 sobrevivió porque la afirmación es débil, **no** porque la mutación estuviera muerta.

```
tests/audit/.../test_corregir...[bandera_on] FAILED
tests/audit/.../test_escalar...[bandera_on] FAILED
tests/audit/.../test_reaccion_del_vip_por_el_mensaje_siguiente FAILED
tests/audit/.../test_job_de_respaldo_marca_silencio_cuando_el_vip_no_contesta FAILED
E   AssertionError: con la bandera en True se esperaban 1 fila(s): []
=================== 4 failed, 12 passed, 1 xfailed ===================
```

### E6 · P7 — Alcance perdido: el contraejemplo queda sin VIP

**Qué hace:** la lección se guarda global en vez de quedar atada a este VIP.

```
E   AssertionError: Reprender no dejó el contraejemplo: [] (eventos: [...])
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### E7 · P8 — Contraejemplo disfrazado de dorado

**Qué hace:** la fila del contraejemplo se guarda además como ejemplo dorado. Una lección de "qué NO decir" quedaría promocionada como modelo a imitar.

```
E   AssertionError: un contraejemplo no puede quedar como dorado: {'embedding': '[0.06413613,-0.079899795,...
=================== 1 failed, 15 passed, 1 xfailed ===================
```

### E8 · P9 — Huella de otro texto (el borrador, no el ancla)

**Qué hace:** la huella se calcula sobre el borrador descartado en vez del texto ancla que el propio código eligió.

**Por qué importa:** distingue "la huella la produjo el motor real" de "la huella la produjo el motor real **para este texto**". Una huella válida del texto equivocado es igual de inservible para buscar.

```
E   AssertionError: la huella guardada no la produjo el motor real para el texto ancla:
                    desvío máximo 0.6853903761463165
=================== 1 failed, 15 passed, 1 xfailed ===================
```

---

## 5. Resumen de los 34 sabotajes

| Trabajo | Tipo | Qué se le arrancó | Veredicto |
|---|---|---|---|
| H1 | S5 | Llamada al historial (dueña) | MUERDE |
| H2 | S5 | Llamada al historial (recontacto) | MUERDE |
| H3 | S1 | Cableado del historial (`history=None`) | MUERDE |
| H4 | S3 | Escritura del historial lanza | MUERDE |
| H5 | S4 | Emparejado devuelve vacío | MUERDE |
| H6 | S2 | Sesión de prueba que sí persiste | MUERDE |
| H7 | P3 | Promoción que escribe historial (control positivo) | MUERDE |
| H8 | P1 | Número de mensaje desplazado | MUERDE |
| H9 | P2 | Fila escrita dos veces | MUERDE |
| H10 | S6 | Fila escrita antes de aprobar | MUERDE |
| H11 | S2 | Bandera de promoción ignorada (dos puertas) | MUERDE |
| H12 | P10 | Omisión sin rastro del motivo | MUERDE |
| H13 | P11 | Puerta de atención abierta sola | MUERDE |
| S1 | S5 | Cableado del libro de resultados | MUERDE |
| S2 | S4 | Decisión de la dueña no se guarda | MUERDE |
| S3 | S4 | Nota de lo enviado vaciada | MUERDE |
| S4 | S5 | Gancho de reacción cortado | MUERDE |
| S5 | S4 | Job sin rama de silencio | MUERDE |
| S6 | P3 | Defecto reparado (xfail) | MUERDE |
| S7 | P4 | Reacción al turno equivocado | MUERDE |
| S8 | P5 | Guarda de repetición del job quitada | **SOBREVIVE** |
| S9 | S4 | Veredicto del sombra pisado | MUERDE |
| S10 | P6 | Veredicto distinto pero válido | **SOBREVIVE** |
| S11 | SONDA | Veredicto fuera del vocabulario | MUERDE |
| S12 | S2 | Libro encendido con la bandera apagada | MUERDE |
| E1 | S5 | Promoción a contraejemplo cortada | MUERDE |
| E2 | S4 | Huella en ceros | MUERDE |
| E3 | S3 | Motor de huellas lanza | MUERDE |
| E4 | S5 | Recuperador sin contraejemplos | MUERDE |
| E5 | S2 | Bandera de Destacar/Reprender ignorada (dos puertas) | MUERDE |
| E6 | P7 | Contraejemplo sin alcance | MUERDE |
| E7 | P8 | Contraejemplo como dorado | MUERDE |
| E8 | P9 | Huella de otro texto | MUERDE |
| E9 | S2 | Candidatos cableados con su bandera apagada | MUERDE |

**32 muerden · 2 sobreviven** (los dos propios, §6).

---

## 6. Lo que NO mordió — devuelto al Probador

Los dos sabotajes que sobrevivieron **no tumban ninguna prueba completa**. Tumban **afirmaciones sueltas** dentro de pruebas que sí sirven. Se registran con precisión: no hay que reescribir la prueba, hay que ajustar una frase o reforzar una comprobación.

### 6.1 `S8 · P5` — La prueba del job de respaldo no comprueba la repetición del *evento*

**Dónde:** `tests/audit/test_C_SHADOW_01_resoluciones.py`, `test_job_de_respaldo_marca_silencio_cuando_el_vip_no_contesta`.

**Qué dice la prueba (su texto):** *"Se exige la señal guardada y que un SEGUNDO ciclo sea idempotente (no vuelve a aplicar el evento)."*

**Qué comprueba de verdad:** que la señal sigue siendo `silence` y que no hay una segunda fila. Ambas cosas se cumplen igual con la guarda de repetición puesta o quitada.

**Sabotaje que sobrevivió:** se elimina del servicio la guarda `if current.vip_signal == vip_signal: return current` (`src/diana/application/outcome_log_service.py`). El segundo ciclo vuelve a escribir la señal y **vuelve a disparar el evento del libro de confianza** — doble conteo — y la prueba sigue en verde.

```
$ pytest <las 3 pruebas> -v      # con la guarda eliminada
16 passed, 1 xfailed, 1 warning in 22.22s
```

**Consecuencia real:** el doble conteo en el libro de confianza no está protegido por ninguna prueba. Si eso importa (alimenta la confianza por VIP del panel de autonomía), falta la comprobación.

**Corrección sugerida (una de las dos):**
- **(a)** estrechar la frase: *"…y que un SEGUNDO ciclo no cambie la señal ni duplique la fila"* — quitar la mención al evento; o
- **(b)** reforzar la prueba: encender el libro de confianza en este caso y exigir **un solo** evento `signal` para ese turno tras los dos ciclos.

### 6.2 `S10 · P6` — El veredicto del sombra se comprueba por pertenencia, no por valor

**Dónde:** `tests/audit/test_C_SHADOW_01_resoluciones.py`, `test_escalar_guarda_owner_outcome_escalated`.

**Qué dice la prueba:** *"Se mide también que la fila de sombra ya existía (el veredicto del sistema se conserva)"*.

**Qué comprueba de verdad:** `fila["shadow_verdict"] in {"send", "blocked", "escalate", "doctrine"}` — que el veredicto **pertenezca a la lista**, no que sea el que el sistema calculó.

**Sabotaje que sobrevivió:** `shadow_verdict_from_decision` devuelve siempre `("blocked", "sabotaje")`. Todos los veredictos guardados quedan en `blocked` y la prueba sigue en verde.

```
$ pytest <las 3 pruebas> -v      # con el veredicto forzado a "blocked"
16 passed, 1 xfailed, 1 warning in 22.54s
```

**La mutación SÍ está viva** — la sonda S11 (mismo punto, valor inválido `"inventado"`) tumba cuatro pruebas:

```
tests/audit/.../test_corregir...[bandera_on] FAILED
tests/audit/.../test_escalar...[bandera_on] FAILED
tests/audit/.../test_reaccion_del_vip_por_el_mensaje_siguiente FAILED
tests/audit/.../test_job_de_respaldo_marca_silencio_cuando_el_vip_no_contesta FAILED
E   AssertionError: con la bandera en True se esperaban 1 fila(s): []
=================== 4 failed, 12 passed, 1 xfailed ===================
```

Es decir: la prueba protege **que el veredicto no se pierda** (S9 lo confirma: pisarlo con `None` la hace fallar), y eso es lo valioso. Lo que **no** protege es que el veredicto siga siendo el correcto.

**Corrección sugerida:** comparar contra el veredicto que produce el propio decisor sombra re-decidido por la prueba (o al menos contra el valor esperado para ese turno), en lugar de contra la lista entera.

---

## 7. Hallazgos colaterales

### 7.1 Las banderas críticas están puestas en dos lugares

Dos sabotajes fallaron al primer intento por esta razón, y los dos son **buenas noticias** para la seguridad del sistema, pero conviene saberlo:

| Bandera | Puerta 1 | Puerta 2 |
|---|---|---|
| Promoción a no-VIP (`feature_promo_enabled`) | `telegram/middlewares/auth.py` (antes de tocar el pipeline) | `application/promo_service.py` (`execute_promo` → `disabled`) |
| Destacar / Reprender (`feature_quality_feedback_enabled`) | `telegram/handlers/callbacks.py` (arranque del flujo) | `application/admin_service.py` (`_require_quality_feedback`) |

**Consecuencia práctica:** apagar una sola de las dos no alcanza para apagar la función, y una prueba que solo atraviese una de las dos puertas no demuestra que la función esté apagada de verdad. Las dos pruebas afectadas (promo y Reprender) **sí** atraviesan las dos y por eso son sólidas: fallan cuando se anulan ambas. Queda registrado para quien apague una bandera en el futuro.

### 7.2 La prueba de Reprender depende del cableado del historial

El sabotaje H3 (cortar el cableado del historial al administrador) tumba **también** `test_reprender_deja_contraejemplo_con_huella_real_y_se_recupera`. No es un error de la prueba: el flujo de Reprender usa el historial para resolver el texto que disparó la lección. Pero conviene saberlo: si algún día se corta el historial, el fallo se verá primero en el historial y después en Reprender, y no son dos problemas distintos.

### 7.3 Sobre la prueba marcada como "fallo esperado"

La marca (`xfail` estricto) del caso "el job de respaldo no puede clasificar la respuesta del VIP" está **bien atada al defecto**: reparado el defecto en su punto exacto, la prueba pasa y la marca la delata (S6). Además, la prueba tiene **dos** puntos de fallo encadenados al mismo defecto (su premisa sobre la fecha, y la clasificación en sí), lo que la hace doblemente dependiente de la reparación. Es una marca honesta, no un escondite.

---

## 8. Código de producción intacto

```bash
# la copia descartable quedó sin diferencias
$ cd /tmp/diana-sabotaje-r2 && git diff --stat
$ git status --porcelain
(sin salida)

# el repositorio de trabajo, intacto
$ cd /home/ubuntu/repos/DianaV2 && git diff --stat src/
(sin salida)
```

- **34 sabotajes** aplicados y revertidos; ningún sabotaje se aplicó sobre un árbol sucio y ninguno dejó el árbol sucio.
- La copia descartable (`/tmp/diana-sabotaje-r2`, rama `sabotaje/fase2-r2`) se retira al cerrar esta ronda.
- **Sin commit a `main`.** Sin despliegue. El bot que atiende los chats no se tocó.
- Salidas crudas de las 34 corridas: `/tmp/sabotaje-r2/out/<trabajo>.txt`.

**Última actualización:** 2026-10-13 · Ronda 2 de sabotaje E3 (historial, resoluciones del sombra y Reprender) — 34 sabotajes, 32 muerden, 2 afirmaciones devueltas al Probador.
