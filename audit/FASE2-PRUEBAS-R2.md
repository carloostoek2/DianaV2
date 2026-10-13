# Fase 2 — Pruebas E2, ronda 2: captura de historial, resoluciones del sombra y Reprender

**Contratos:** `audit/contracts/C-HIST-01.md` (a) · `audit/contracts/C-SHADOW-01.md` · `audit/contracts/C-EMB-01.md`
**Rama:** `audit/pruebas-e2-r2` (worktree en `/tmp/diana-e2-r2`, desde `main`). **Fecha:** 2026-10-12.
**Sin commit a `main`. Sin despliegue. Código de producción intacto** (ver §8).

---

## Resumen para la dueña

Se probó con efecto real —y por primera vez— **qué queda escrito en el historial del chat cada vez que
Diana manda un mensaje**. Es lo que Diana usa después para acordarse de la conversación y para aprender
tu voz. Se probaron los tres caminos por los que un mensaje sale: cuando apruebas un borrador, cuando lo
corriges, y cuando el bot recontacta solo.

Las pruebas entran por donde entra la realidad: un mensaje del VIP por el mismo camino que usa el bot,
tus botones reales (Aprobar, Corregir, Escalar, Reprender) y una base de datos Postgres de verdad. Lo
único falso es el modelo de lenguaje externo y la salida a Telegram. **No se asertó "se llamó a tal
función": se leyeron filas reales en la base y se comparó el texto guardado con el que de verdad salió
por el canal, incluido el número de mensaje que devuelve Telegram.**

| Promesa | Estado |
|---|---|
| Aprobar un borrador deja en el historial el texto enviado **con su número de mensaje de Telegram** | ✅ probado con fila real |
| Corregir guarda **el texto corregido**, no el borrador descartado, y con su número | ✅ probado con fila real |
| El recontacto automático también deja su fila | ✅ probado con fila real |
| En una sesión de prueba (sandbox) **no** se escribe historial, y es a propósito | ✅ probado en los dos estados, con el motivo visible |
| Una promoción a un chat que **no** es VIP se entrega pero **no** deja historial, y es a propósito | ✅ probado, con el caso apagado como control (0 turnos, 0 envíos) |
| Cuando corriges, queda registrado como `corrected`; cuando escalas, como `escalated` | ✅ probado, con fila real (antes solo estaba probado "aprobaste tal cual") |
| La reacción del VIP a un mensaje entregado se guarda en el turno anterior | ✅ probado: el mensaje siguiente del VIP la deja |
| El job de respaldo clasifica la respuesta del VIP cuando el bot no la vio en vivo | ❌ **no funciona** — defecto abierto, ver §5 |
| "Reprender" deja el contraejemplo con su huella real y la búsqueda por parecido lo encuentra | ✅ probado con fila real y recuperación real |

**Los 18 avisos del vigilante V4 no son fallas.** V4 cuenta "entregas sin rastro en el historial" y hoy
devuelve 18. Se revisaron uno por uno contra la base real: **los 18 son mensajes de promoción a chats
que no son VIP** (atención), que por diseño no van al historial del VIP. En la misma ventana, los 20
turnos de VIP dejaron **los 20** su fila. **Cero fallas reales.** El detalle y la evidencia están en §3.

**Lo que sí hay que decidir:** el vigilante V4, tal como está escrito, va a avisar todos los días por
mensajes de promoción en cuanto se encienda. Hay que decidir si las promociones deben quedar en el
historial o no, y ajustar V4 en consecuencia (§3.4).

**Lo que NO cambia:** nada para el VIP. No se tocó ni una línea del sistema que atiende los chats.

---

## Paso 0 — Las dos banderas y la línea del arranque

Pedido: reportar el valor real, en el `.env` y en el registro de arranque, de
`FEATURE_VIP_HISTORY_SEED_ENABLED` y `FEATURE_HISTORY_REIMPORT_ENABLED`, y la línea
`vip_history_seed_disabled_by_flag`.

### 0.1 `.env` real (`/home/ubuntu/repos/DianaV2/.env`)

```
121: VIP_HISTORY_SEED_LIMIT=20
124: VIP_HISTORY_MEDIA_LIMIT=3
133: FEATURE_HISTORY_REIMPORT_ENABLED=false
138: FEATURE_VIP_HISTORY_SEED_ENABLED=true
```

Con los comentarios de intención que exige la regla de prioridad (AGENTS.md §1):

- `FEATURE_HISTORY_REIMPORT_ENABLED=false` — OFF declarado, con motivo escrito en el `.env`: *"los VIP
  ya registrados no tienen historial previo en la cuenta en uso, así que la recarga no encontraría
  mensajes que importar"*. Está declarada como bandera núcleo apagada.
- `FEATURE_VIP_HISTORY_SEED_ENABLED=true` — VIVO, con motivo escrito: *"el alta trae los mensajes que
  el VIP escribió antes de estar en la lista, consultando la sesión de la cuenta en uso"*.

### 0.2 Registro de arranque (journald, unidad `diana-bot`, PID 1812647, arriba desde 2026-10-09 23:52:01 UTC)

El proceso **vivo** confirma los dos valores del `.env`:

```
2026-10-09 23:52:05,512 INFO | vip_history_seed_enabled session_path=/home/ubuntu/repos/DianaV2/runtime/diana_session limit=20
2026-10-09 23:52:06,647 INFO | history_reimport_job_skipped_flag_off
2026-10-09 23:52:05,XXX INFO | ... event=banderas_nucleo advertencia=True apagadas_declaradas=['FEATURE_HISTORY_REIMPORT_ENABLED'] apagadas_sin_declarar=['FEATURE_RECONTACT_ENABLED'] desconocidas=[] nucleo_total=20 huella=d6cc0da1170590b3
```

- `vip_history_seed_enabled … limit=20` ⇒ en el proceso en marcha `FEATURE_VIP_HISTORY_SEED_ENABLED`
  **está encendida** y el importador está cableado con la sesión y el tope del `.env`.
- `history_reimport_job_skipped_flag_off` ⇒ `FEATURE_HISTORY_REIMPORT_ENABLED` **está apagada** y el job
  de recarga se saltea entero en cada arranque.
- El resumen de banderas núcleo confirma que el apagado de reimport **está declarado**, y delata un
  segundo apagado **sin declarar**: `FEATURE_RECONTACT_ENABLED` (fuera del alcance de esta ronda; se
  reporta porque el propio aviso lo está pidiendo).

### 0.3 La línea `vip_history_seed_disabled_by_flag`

Aparece **5 veces** en todo el journal, **todas entre el 2026-10-07 y el 2026-10-08**, y **ninguna vez
desde entonces**:

```
2026-10-07 07:12:50,009 INFO | vip_history_seed_disabled_by_flag session_path=/home/ubuntu/repos/DianaV2/runtime/diana_session telethon_configured=True reason=feature_vip_history_seed_enabled=false
2026-10-07 07:16:11,416 INFO | (idéntica)
2026-10-07 23:49:36,778 INFO | (idéntica)
2026-10-07 23:59:44,881 INFO | (idéntica)
2026-10-08 00:42:34,464 INFO | (idéntica)
```

**Lectura:** es la línea que se imprime cuando alguien prende las credenciales de Telethon pero la
bandera está apagada. Corresponde a los arranques del 7 y 8 de octubre, **antes** de encender la
bandera. Desde el 2026-10-08 05:58 el arranque imprime la línea contraria
(`vip_history_seed_enabled …`), así que hoy el apagado silencioso **no está ocurriendo**.

---

## 1. Cómo correrlas

Requiere Docker. El usuario `ubuntu` no está en el grupo `docker` en esta sesión, así que se envuelve con
`sg docker`. La copia de la base real se refrescó antes de la corrida (2026-10-12 02:59 UTC) para que la
foto no fuera vieja (regla de `audit/ENTORNO.md`).

```bash
cd /home/ubuntu/repos/DianaV2 && ./scripts/refresh_e2e_copy.sh    # lectura de la base real → copia local

cd /tmp/diana-e2-r2
DIANA_E2E_COPY_DUMP=/home/ubuntu/repos/DianaV2/runtime/e2e_copy/diana_copy.sql \
  sg docker -c "cd /tmp/diana-e2-r2 && /home/ubuntu/repos/DianaV2/.venv/bin/python -m pytest \
    tests/audit/test_C_HIST_01_captura.py \
    tests/audit/test_C_SHADOW_01_resoluciones.py \
    tests/audit/test_C_EMB_01_reprender.py -v"
```

Las pruebas de huellas cargan el modelo de embeddings **real** y van marcadas `@pytest.mark.slow`.

---

## 2. Resultado real (2026-10-12)

```
$ DIANA_E2E_COPY_DUMP=…/runtime/e2e_copy/diana_copy.sql sg docker -c "… python -m pytest tests/audit/test_C_HIST_01_captura.py tests/audit/test_C_SHADOW_01_resoluciones.py tests/audit/test_C_EMB_01_reprender.py -v"
============================= test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.1.1, pluggy-1.6.0 -- /home/ubuntu/repos/DianaV2/.venv/bin/python
cachedir: .pytest_cache
e2e DB: copia de la base real (diana_copy.sql, 36.8 MB, generada 2026-10-12 02:59 UTC) restaurada en el contenedor
rootdir: /tmp/diana-e2-r2
configfile: pyproject.toml
plugins: anyio-4.15.1, asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=session, asyncio_default_test_loop_scope=session
collecting ... collected 17 items

tests/audit/test_C_HIST_01_captura.py::test_entrega_normal_deja_fila_con_texto_y_su_id_de_telegram PASSED [  5%]
tests/audit/test_C_HIST_01_captura.py::test_correccion_deja_fila_con_el_texto_corregido_y_su_id PASSED [ 11%]
tests/audit/test_C_HIST_01_captura.py::test_recontacto_deja_fila_con_texto_y_su_id_de_telegram PASSED [ 17%]
tests/audit/test_C_HIST_01_captura.py::test_matriz_sandbox_decide_si_la_entrega_deja_historial[sin_sandbox_escribe] PASSED [ 23%]
tests/audit/test_C_HIST_01_captura.py::test_matriz_sandbox_decide_si_la_entrega_deja_historial[sandbox_no_escribe] PASSED [ 29%]
tests/audit/test_C_HIST_01_captura.py::test_promocion_a_un_chat_que_no_es_vip_no_deja_historial_por_diseno[promo_on] PASSED [ 35%]
tests/audit/test_C_HIST_01_captura.py::test_promocion_a_un_chat_que_no_es_vip_no_deja_historial_por_diseno[promo_off] PASSED [ 41%]
tests/audit/test_C_SHADOW_01_resoluciones.py::test_corregir_guarda_owner_outcome_corrected[bandera_on] PASSED [ 47%]
tests/audit/test_C_SHADOW_01_resoluciones.py::test_corregir_guarda_owner_outcome_corrected[bandera_off] PASSED [ 52%]
tests/audit/test_C_SHADOW_01_resoluciones.py::test_escalar_guarda_owner_outcome_escalated[bandera_on] PASSED [ 58%]
tests/audit/test_C_SHADOW_01_resoluciones.py::test_escalar_guarda_owner_outcome_escalated[bandera_off] PASSED [ 64%]
tests/audit/test_C_SHADOW_01_resoluciones.py::test_reaccion_del_vip_por_el_mensaje_siguiente PASSED [ 70%]
tests/audit/test_C_SHADOW_01_resoluciones.py::test_job_de_respaldo_marca_silencio_cuando_el_vip_no_contesta PASSED [ 76%]
tests/audit/test_C_SHADOW_01_resoluciones.py::test_job_de_respaldo_clasifica_la_respuesta_que_no_paso_por_el_pipeline XFAIL [ 82%]
tests/audit/test_C_EMB_01_reprender.py::test_reprender_deja_contraejemplo_con_huella_real_y_se_recupera PASSED [ 88%]
tests/audit/test_C_EMB_01_reprender.py::test_matriz_sin_la_pieza_cableada_no_hay_contraejemplo[sin_feedback] PASSED [ 94%]
tests/audit/test_C_EMB_01_reprender.py::test_matriz_sin_la_pieza_cableada_no_hay_contraejemplo[sin_staging] PASSED [100%]

=============================== warnings summary ===============================
tests/audit/test_C_HIST_01_captura.py::test_entrega_normal_deja_fila_con_texto_y_su_id_de_telegram
  /tmp/diana-e2-r2/tests/e2e/conftest.py:132: DeprecationWarning: testcontainers.postgres is deprecated, use testcontainers.community.postgres instead
    from testcontainers.postgres import PostgresContainer

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================== 16 passed, 1 xfailed, 1 warning in 33.55s ===================
```

**16 verdes y 1 `xfail` que es un hallazgo, no un problema de la prueba** (§5). El `xfail` es
`strict=True`: si alguien arregla el defecto, la prueba pasa y el `strict` **falla a propósito** para
obligar a sacarle la marca. El defecto no se puede olvidar en silencio.

### 2.1 Inventario de dobles (qué es real y qué no)

Se revisó archivo por archivo. **No hay ni un solo `MagicMock`, `AsyncMock`, `patch` ni `monkeypatch`
en las tres pruebas.** Lo único simulado son las dos fronteras externas declaradas:

| Pieza | Real o doble | Detalle |
|---|---|---|
| Arranque del sistema | **Real** | Los 17 casos entran por `build_app` (`composition.py`) con las banderas del escenario |
| Base de datos | **Real** | Postgres (contenedor `pgvector/pgvector:pg16` con la copia de la base real restaurada) |
| Orquestador, Director, Decisor, Analista, Evaluador | **Reales** | Ninguna prueba los instancia ni los sustituye |
| Repositorios | **Reales** | Se leen las filas con SQL directo contra la misma base |
| Motor de huellas | **Real** | `EmbeddingService()` de producción; la prueba **recalcula** la huella esperada y exige desvío < 1e-6 |
| Recuperador de ejemplos | **Real** | `ExamplesRetriever` + `ExamplesRepo` reales sobre la misma base: exige que el contraejemplo **vuelva** en la búsqueda |
| Job de respaldo | **Real** | `run_outcome_reaction_cycle` de producción, con los servicios ya cableados por `build_app`, y se corre un **segundo ciclo** para exigir idempotencia |
| Modelo de lenguaje | **Doble** | `diana/llm/fake.py`, determinista |
| Salida a Telegram | **Doble** | `bot.session` falso que devuelve `message_id` reales, para poder exigir el par texto ↔ número |

Por eso las pruebas pueden decir "la fila quedó con este texto y este número" en lugar de "se llamó a
tal función".

---

## 3. Los 18 casos de V4 — clasificación con evidencia

### 3.1 Qué mide V4

`audit/vigilantes.sql:91-100` (hoy `no-activado`, no se ejecuta dentro del bot):

```sql
-- V4 | no-activado | C-HIST-01 | entregas sin rastro en el historial del chat
-- NO se activa todavía: hoy devuelve 18 y la cláusula (a) del contrato sigue en E0
-- (nunca verificada con efecto real). Antes de encenderlo hay que separar el hueco
-- por diseño (sandbox) del hueco real, en la ronda de C-HIST-01.
SELECT count(*) AS entregas_sin_historial, 0 AS alerta
FROM turns t
WHERE t.status = 'delivered'
  AND t.created_at BETWEEN now() - interval '2 days' AND now() - interval '10 minutes'
  AND NOT EXISTS (SELECT 1 FROM message_history m
                  WHERE m.chat_id = t.chat_id AND m.role = 'owner' AND m.timestamp >= t.created_at);
```

La propia nota de V4 pide exactamente lo que sigue: **separar el hueco por diseño del hueco real**.

Medición del 2026-10-12 contra la base real: **18**, igual que cuando se escribió la nota.

### 3.2 La primera separación: ¿de qué canal es cada entrega?

```sql
SELECT t.channel_type,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM message_history m
            WHERE m.chat_id=t.chat_id AND m.role='owner' AND m.timestamp >= t.created_at)) AS con_historial,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM message_history m
            WHERE m.chat_id=t.chat_id AND m.role='owner' AND m.timestamp >= t.created_at)) AS sin_historial
FROM turns t
WHERE t.status='delivered'
  AND t.created_at BETWEEN now() - interval '2 days' AND now() - interval '10 minutes'
GROUP BY 1 ORDER BY 1;
```

```
 channel_type | con_historial | sin_historial
--------------+---------------+---------------
 atencion     |             5 |            18
 vip          |            20 |             0
```

**Decisivo:** los 18 son **todos** `channel_type='atencion'` (chats que no son VIP). En la misma
ventana, **los 20 turnos de VIP dejaron los 20 su fila de historial**. El contrato (a), que promete
"cada mensaje que la dueña envía por Diana queda en el historial **del VIP**", **se cumple 20 de 20**.

### 3.3 Segunda separación: ¿por qué camino salió cada entrega?

```sql
WITH base AS (
  SELECT t.id, t.chat_id, t.channel_type,
    EXISTS (SELECT 1 FROM message_history m WHERE m.chat_id=t.chat_id AND m.role='owner' AND m.timestamp >= t.created_at) AS con_hist,
    EXISTS (SELECT 1 FROM promo_executions e WHERE e.chat_id=t.chat_id
            AND e.sent_at BETWEEN t.created_at - interval '3 minutes' AND t.created_at + interval '3 minutes') AS promo,
    (SELECT count(*) FROM pending_approvals p WHERE p.turn_id=t.id) AS aprob,
    (SELECT count(*) FROM pipeline_traces tr WHERE tr.turn_id=t.id) AS trazas
  FROM turns t
  WHERE t.status='delivered' AND t.created_at BETWEEN now() - interval '2 days' AND now() - interval '10 minutes'
)
SELECT channel_type, con_hist, promo, (aprob>0) AS tiene_aprobacion, (trazas>0) AS tiene_traza, count(*) AS n
FROM base GROUP BY 1,2,3,4,5 ORDER BY 1,2 DESC,3 DESC;
```

```
 channel_type | con_hist | promo | tiene_aprobacion | tiene_traza | n
--------------+----------+-------+------------------+-------------+----
 atencion     | t        | t     | f                | f           |  5
 atencion     | f        | t     | f                | f           | 18
 vip          | t        | f     | t                | t           | 20
```

Los 18 (y también los 5 de atención que sí aparecen con historial) tienen **ejecución de promoción**,
**ninguna aprobación** y **ninguna traza de pipeline**. Los 20 de VIP tienen aprobación y traza, y
ninguna promoción. La correlación con el log de producción lo confirma en vivo:

```
2026-10-11 21:51:05,469 INFO | telegram_update chat_id=744361600 event_type=Message
2026-10-11 21:51:05,497 INFO | promo_match chat_id=744361600 telegram_user_id=744361600 trigger_id=c676e652-…
2026-10-11 21:51:05,643 INFO | telegram_update chat_id=735638960 event_type=Message
2026-10-11 21:51:05,669 INFO | promo_match chat_id=735638960 telegram_user_id=735638960 trigger_id=c676e652-…
```

### 3.4 Veredicto sobre los 18: **ruta de diseño**, no sandbox y no fallo

- **No es sandbox.** El sandbox es otra superficie y deja su propio rastro (`owner_history_skipped_sandbox`),
  que en esta ventana no aparece ni una vez (§3.5).
- **No es fallo real.** La ruta del VIP escribe 20 de 20, y las tres pruebas E2 de §2 demuestran que
  aprobar, corregir y recontactar dejan su fila con texto y número de Telegram.
- **Es ruta de diseño, y está medido con efecto real.** La prueba
  `test_promocion_a_un_chat_que_no_es_vip_no_deja_historial_por_diseno` reproduce el caso de punta a punta:
  siembra un disparador de promoción, un chat **que no está en la lista de VIP** manda el texto exacto, y
  la prueba exige las tres cosas juntas — (1) la secuencia **sí salió** por el canal (los 3 textos, en
  orden), (2) el turno quedó **`delivered`** con `channel_type='atencion'`, y (3) el historial quedó
  **vacío**, sin rastro de fallo ni de sesión de prueba. El caso con la promoción **apagada** se corre
  aparte y exige lo contrario: **cero turnos y cero envíos** — así el hueco no se puede atribuir a que
  la promoción no corrió. La explicación de por qué ocurre está en el código: la promoción no pasa por el
  pipeline — `PromoService` entrega con
  `BehaviorEngine.deliver_with_sequence` (`src/diana/application/promo_service.py:258`), y el historial
  de la dueña lo escriben **solo tres** llamadores — `turn_orchestrator.py:3032`,
  `recontact_service.py:274` y `admin_service.py:2219`. `promo_service.py` no llama a
  `append_owner_delivery_history` en absoluto, y AGENTS.md §4.10 ya dice que la promoción **no se guarda
  en `pipeline_traces`**. El turno queda `delivered` y con `channel_type='atencion'`, pero sin historial.

**Consecuencia accionable — V4 tal como está escrito va a dar un falso positivo diario.** No filtra por
canal ni excluye la promoción, así que cuenta entregas que por diseño no deben dejar historial. Dos
ajustes posibles, y **es una decisión de producto**:

| Opción | Qué implica |
|---|---|
| **A (recomendada)** — V4 filtra `AND t.channel_type = 'vip'` | El vigilante vigila lo que el contrato promete (el historial **del VIP**). Deja de avisar por promociones. Requiere decidir que la promoción **no** debe quedar en el historial, que es lo que hoy hace. |
| **B** — la promoción **sí** se guarda en el historial | Cierra el hueco por el otro lado: `promo_service.py` empieza a llamar a `append_owner_delivery_history`. Cambia el comportamiento del bot (lo que Diana "recuerda" del chat) y **es cambio de producción**, fuera del alcance de esta ronda. |

Sin ninguna de las dos, V4 queda `no-activado` para siempre: encenderlo hoy avisaría a la dueña todos
los días por un comportamiento buscado.

### 3.5 Control a 30 días: los 4 turnos de VIP que sí faltaban son sandbox

Con la ventana del vigilante estirada a 30 días aparecen, además de 126 de atención, **4 turnos de
VIP** sin historial:

```sql
-- ventana de 30 días, por canal
 atencion     |   126
 vip          |     4
```

Los 4 son **del mismo chat** (`1280444712`) y de la misma hora del 2026-10-08 (04:59 a 05:09). El
registro de arranque del bot los identifica **uno por uno, por su `turn_id`**, como saltos por sandbox:

```
2026-10-08 05:00:05 INFO | owner_history_skipped_sandbox turn_id=da00900c-d13d-4547-b6e8-2770e877f81d chat_id=1280444712
2026-10-08 05:00:19 INFO | owner_history_skipped_sandbox turn_id=6fc7ec4a-9099-4848-a484-145e38f38f11 chat_id=1280444712
2026-10-08 05:09:45 INFO | owner_history_skipped_sandbox turn_id=fadd2855-120f-4074-b69f-30db52d7dce9 chat_id=1280444712
2026-10-08 05:09:59 INFO | owner_history_skipped_sandbox turn_id=f6ea1ecd-7485-415f-924f-36d2eed16854 chat_id=1280444712
```

Los cuatro `turn_id` coinciden **exactamente** con los cuatro turnos que V4 marca. Es el hueco por
diseño que AGENTS.md §4.20 declara: en sandbox la memoria del usuario es efímera
(`should_persist=false`). **No es fallo.**

Nota sobre el proxy del vigilante: la ventana de 30 días da 4 y no 7 (que son los saltos por sandbox
que hay en el journal) porque V4 pregunta "¿hay alguna fila de la dueña posterior al turno?", y en ese
chat la dueña escribió después, el 2026-10-08 a las 04:57:26 — lo que **tapa** los huecos anteriores a
esa hora. Es decir, el proxy de V4 **cuenta de más** (promociones) y **de menos** (huecos tapados por
escritura posterior de la dueña). Va anotado para cuando se encienda.

---

## 4. Matriz de banderas medida

Cada caso se corrió con la bandera encendida **y** apagada; el caso apagado asierta explícitamente que
**no hay efecto** (no que "no se llamó a nada").

| Contrato / caso | Bandera | ON | OFF |
|---|---|---|---|
| C-HIST-01 (a) entrega normal | — (historial es contrato de Fase 1, sin bandera) | 1 fila con texto + número de Telegram | n/a |
| C-HIST-01 (a) corrección | — | 1 fila con el texto **corregido** + número | n/a |
| C-HIST-01 (a) recontacto | `FEATURE_RECONTACT_ENABLED` | 1 fila con texto + número | n/a |
| C-HIST-01 (a) sesión de prueba (sandbox) | `FEATURE_SANDBOX_ENABLED` | chat con sandbox: **0 filas**, con el motivo registrado | chat sin sandbox: **1 fila** |
| C-HIST-01 (a) promoción a un no-VIP | `FEATURE_PROMO_ENABLED` (+ `FEATURE_GENERAL_MODE_ENABLED`) | **0 filas** de historial, pero **3 envíos** y turno `delivered` en `channel_type='atencion'` | **0 turnos y 0 envíos**: la pieza no está cableada |
| C-SHADOW-01 `corrected` | `FEATURE_AUTONOMY_QUALITY_ENABLED` | fila con `owner_outcome='corrected'`, `sent_score` y `quality_delta` | **0 filas**, y `feature_autonomy_quality_enabled is False` |
| C-SHADOW-01 `escalated` | `FEATURE_AUTONOMY_QUALITY_ENABLED` | fila con `owner_outcome='escalated'`, `sent_score` y `quality_delta` **en NULL** (no inventados) | **0 filas** |
| C-SHADOW-01 reacción por el mensaje siguiente | `FEATURE_AUTONOMY_QUALITY_ENABLED` | `vip_signal` pasa de NULL a un valor del vocabulario, en la fila del turno **anterior** | n/a |
| C-SHADOW-01 reacción por el job de respaldo | `FEATURE_AUTONOMY_QUALITY_ENABLED` | `vip_signal='silence'`, idempotente en un segundo ciclo | n/a |
| C-EMB-01 Reprender | `FEATURE_QUALITY_FEEDBACK_ENABLED` × `FEATURE_STAGING_ENABLED` | contraejemplo con huella real, recuperable por parecido | sin feedback **o** sin staging: **0 contraejemplos** |

---

## 5. Hallazgo abierto: el job de respaldo no puede clasificar la respuesta del VIP

`tests/audit/test_C_SHADOW_01_resoluciones.py:630` marca con `xfail(strict=True)` el caso "el bot estuvo
caído y el VIP igual contestó". La prueba **falla como está el sistema**, y eso es el hallazgo.

**El defecto.** `first_vip_followup_text` (`src/diana/jobs/outcome_reaction.py:52-53`) descarta toda fila
cuyo `timestamp` no sea un `datetime`:

```python
ts = row.get("timestamp")
if not isinstance(ts, datetime):
    continue
```

Pero el historial real entrega el timestamp como **texto ISO**
(`rows_to_recent_messages`, `src/diana/infrastructure/db/repositories/history.py:33`):
`"timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts)`. Y `get_recent` — el método que
el job usa — es exactamente ese (`history.py:177-188`). Resultado: **se descartan todas las filas**, la
función devuelve siempre `None`, y el job escribe `'silence'` **siempre**. La rama de clasificación
(`outcome_reaction.py:100-103`) es código muerto.

**Evidencia de producción (no solo de la prueba):**

1. El job nunca clasificó nada. Sobre el journal completo, 316 ciclos:

| Reporte del ciclo | Veces |
|---|---|
| `{'processed': 0, 'silence': 0, 'reactions': 0, 'errors': 0}` | 278 |
| `{'processed': 1, 'silence': 1, 'reactions': 0, 'errors': 0}` | 30 |
| `{'processed': 2, 'silence': 2, 'reactions': 0, 'errors': 0}` | 7 |
| `{'processed': 3, 'silence': 3, 'reactions': 0, 'errors': 0}` | 1 |

   `reactions` es **0 en los 316 ciclos**. Los 48 turnos que el job procesó los cerró **todos** como
   silencio.

2. La clasificación del job solo puede producir `positive/neutral/negative` (nunca `silence`):
   `classify_reaction` (`src/diana/application/outcome_log_service.py:285-291`). Y el gancho inmediato
   tampoco escribe `silence`. Por lo tanto **las 176 filas con `vip_signal='silence'` de la tabla
   `turn_outcome_log` las escribió el job**.

3. **80 de esas 176 (45 %) están mal**: hay un mensaje real del VIP dentro de la ventana de 6 h
   (`OUTCOME_REACTION_WINDOW_HOURS=6`) después de la entrega.

```sql
WITH silencio AS (
  SELECT t.chat_id, coalesce(t.updated_at, t.created_at) AS ancla
  FROM turn_outcome_log o JOIN turns t ON t.id = o.turn_id
  WHERE o.vip_signal = 'silence'
)
SELECT count(*) AS silencios,
       count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM message_history m
         WHERE m.chat_id = s.chat_id AND m.role='vip'
           AND m.timestamp > s.ancla AND m.timestamp <= s.ancla + interval '6 hours'
       )) AS silencios_con_respuesta_real
FROM silencio s;
```

```
 silencios | silencios_con_respuesta_real
-----------+------------------------------
       176 |                           80
```

**Impacto para el negocio.** La reacción del VIP alimenta la confianza con la que el sistema recomienda
activar el envío automático (AGENTS.md §4.18: `vip_signal='positive'` suma, `'negative'` resta). Un VIP
que contestó bien aparece como "no contestó": **el camino a la autonomía se mide con datos que están mal
en casi la mitad de los casos en que el job participa.** El gancho inmediato (el VIP escribe con el bot
arriba) funciona y no está afectado — por eso la tabla igual tiene 370 `positive`.

**No se arregló en esta ronda a propósito:** el arreglo es una línea
(`datetime.fromisoformat(ts)` cuando llega texto) en código de producción, y esta ronda tiene la
instrucción explícita de **no modificar código de producción**. La prueba queda en `xfail(strict=True)`
como alarma: el día que se arregle, la prueba pasa y el `strict` obliga a quitarle la marca.

---

## 6. Límites de esta ronda

- **Nivel E2, no E3.** Estas pruebas demuestran que el efecto ocurre; **todavía no** se les hizo el
  sabotaje que demuestra que caen si se desconecta la pieza. La ronda de sabotaje es el paso siguiente.
  (La ronda 1 sí lo tiene: `audit/FASE2-SABOTAJE.md`.)
- **Una prueba es débil por construcción**, y se declara: `test_job_de_respaldo_marca_silencio_cuando_el_vip_no_contesta`
  pasa, pero **no distingue** "el job acertó al ver silencio" de "el job dice silencio siempre". Quien
  cubre esa mitad es el `xfail` de §5 — por eso van juntas y no se puede sacar una sin la otra.
- **No se probó** la corrección desde Atención ni el Reprender en sandbox (aislamiento): siguen sin
  prueba propia, igual que quedaron en las rondas anteriores.
- **`FEATURE_RECONTACT_ENABLED` aparece apagada y sin declarar** en el aviso de banderas núcleo
  (`apagadas_sin_declarar=['FEATURE_RECONTACT_ENABLED']`). No es parte de esta ronda, pero el propio
  aviso del bot lo está reclamando.

---

## 7. Nivel alcanzado

| Contrato / cláusula | Antes | Ahora |
|---|---|---|
| C-HIST-01 (a) — captura de cada entrega | **E0** (nunca verificada con efecto real) | **E2** — 3 caminos (normal, corrección, recontacto) con fila real, texto y número de Telegram, más la matriz de sandbox y el hueco por diseño de la promoción medido con su caso apagado |
| C-SHADOW-01 (b) — resoluciones de la dueña | E2 parcial (**solo `approved_as_is`**) | **E2** — `corrected` y `escalated` con fila real, en los dos estados de la bandera |
| C-SHADOW-01 (c) — reacción del VIP | E0 | **E2 parcial** — mensaje siguiente ✅ y job de respaldo ❌ (defecto abierto, §5) |
| C-EMB-01 — camino de Reprender | E0 | **E2** — contraejemplo con huella real, recuperable por parecido, con matriz de banderas |
| Clasificación de los 18 casos de V4 | pendiente por nota del propio vigilante | **HECHO** — ruta de diseño, cero fallas reales (§3) |

---

## 8. Código de producción intacto

- Rama `audit/pruebas-e2-r2` en un **worktree** (`/tmp/diana-e2-r2`); `main` y el directorio de
  producción (`/home/ubuntu/repos/DianaV2`) siguen en `main` (commit `de46bea`), sin cambios.
- **Sin despliegue por esta ronda.** No se detuvo ni se reinició el bot desde aquí, y no se cambió ni una
  línea del código que atiende los chats. Para no dejar que se lea de más: durante la ventana de la ronda
  el servicio **sí** se reinició una vez (`diana-bot`, 2026-10-12 05:22:24 UTC, por systemd) — **no fue
  esta ronda**, que nunca tocó el servicio, y el arranque quedó con el mismo código porque el árbol de
  trabajo no cambió.
- El árbol de trabajo de producción tiene, además, un cambio automático **ajeno a esta ronda**:
  `wiki/.ua/knowledge-graph.json`, un índice regenerado por herramienta (solo cambian la fecha de
  análisis y el hash del commit). No se tocó desde aquí.
- Lo único que se ejecutó contra la base real fueron **consultas de lectura** (`SELECT`) y el
  `pg_dump` de `scripts/refresh_e2e_copy.sh`, que es de solo lectura por diseño.
- Lo único que se escribió fuera del worktree es la copia local `runtime/e2e_copy/diana_copy.sql`
  (ignorada por git, contiene datos reales, no se versiona).
- **Sin commit a `main`.**

---

Fin de `audit/FASE2-PRUEBAS-R2.md` — ronda 2 de pruebas E2 (C-HIST-01 (a), C-SHADOW-01, C-EMB-01). 2026-10-12.
