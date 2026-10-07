# Investigación A — Por qué hay huecos en el registro de resultados

Fecha: **2026-10-06** · Autor: auditoría de contratos (skill `contract-proof`, contrato C-SHADOW-01)
Alcance: **solo lectura**. No se cambió código, ni banderas, ni datos. No hay commit.

---

## Resumen para la dueña (lo que importa)

El registro que mide "qué habría hecho Diana sola vs. qué hiciste tú" tiene **500 filas** entre el
23-ago y hoy. Los huecos que se veían se explican así:

| Pregunta | Qué encontramos | Veredicto |
|---|---|---|
| **A. 14 turnos sin fila de sombra** | Ninguno es un error. Son **cuatro rutas que por diseño no pasan por ese registro**: escalaciones por palabra clave, saludos/check-ins automáticos, pruebas de sandbox y un caso de falso positivo que quedó en pausa. | **Probado** |
| **B. ¿Hubo errores tragados en los logs del 2-3 oct?** | **No.** En esos dos días el sistema escribió 37 registros correctos y **cero errores**. En toda la ventana de logs que queda (30-sep → 6-oct): 116 escrituras correctas y **cero errores**. | **Probado** |
| **C. 41 turnos con puntaje pero sin tu decisión registrada** | Fue un **defecto real y ya corregido**: el registro de tu decisión se borraba solo, un instante después de que aprobabas. Se arregló el **10-sep a las 19:42** y desde entonces no se ha perdido ninguno (157 entregas desde el 11-sep, 0 pérdidas). | **Probado** |

**Lo que gana o pierde el negocio:** entre el 23-ago y el 10-sep el sistema entregó mensajes pero
no guardó qué decidiste sobre ellos. Eso deja la curva histórica de "coincidencia" incompleta en ese
tramo. **Hoy eso no afecta ninguna decisión**: la ventana que se usa para medir si Diana puede ir
sola es de 14 días, y ese período ya quedó fuera. El defecto está corregido y no ha vuelto a ocurrir.

---

## Cómo accedí a los datos (transparencia)

- **Base de datos real**: conexión **de solo lectura** (transacción marcada como *read only*), tomando
  la dirección que el propio bot usa (`.env`). Ninguna escritura. Las credenciales no se copiaron a
  ningún archivo ni salida.
- **Logs de producción**: **sí existen** y viven en el **journal del sistema**, bajo la unidad de
  usuario `diana-bot` (no había que adivinar: el proceso del bot corre bajo `systemctl --user`, y su
  salida queda ahí). Se leen con:

  ```bash
  journalctl -t diana-bot --since "2026-10-02" --until "2026-10-04"
  ```

  **Límite importante:** el journal hoy solo conserva desde el **30-sep**. Todo lo anterior
  (incluido el 24-sep) ya rotó y **no es recuperable**. Esto condiciona el veredicto de un caso de
  la pregunta A.

---

## A. Los 14 turnos VIP sin fila de sombra

Reproduje exactamente el criterio del informe previo (turnos con VIP, estado distinto de `superseded`
/ `failed`, de los últimos 30 días, sin fila en el registro). **Son 14, igual que antes.**

Al mirar **qué decidió el sistema** en cada uno, se parten en cuatro grupos limpios. El patrón es
total, no aleatorio: **cada grupo falla al 100% o al 0%**, y eso descarta la idea de errores sueltos.

| Grupo | Turnos | Causa | Evidencia |
|---|---|---|---|
| 1. Escalación por palabra clave | **6** | La escalación se dispara **antes** de que Diana piense el mensaje: no hay "borrador" que comparar. | Los 6 tienen **cero** trazas y sí un aviso de escalación (`pago_precio`, `compromiso_real`). |
| 2. Saludo / check-in automático | **5** | Son plantillas fijas ("Holis", "¿qué tal tu día?"): no pasan por evaluación, y sin evaluación no hay nada que puntuar. | Los 5 tienen la traza **sin evaluación** (`evaluation` vacía). |
| 3. Sandbox (chat de pruebas) | **2** | Es tu superficie de prueba: por diseño **no guarda nada**. | El log dice literalmente `post_turn_skipped_sandbox` para ambos. |
| 4. Falso positivo que pidió doctrina | **1** | Marcaste "falso positivo" y el sistema regeneró un borrador que volvió a pedir doctrina; ese camino quedó **en pausa** (nunca se envió nada). | Marca de falso positivo a las 04:25:52 y traza regenerada a las 04:25:53, pero **ninguna consulta de zona gris** creada y el turno siguió escalado. |

### El grupo 4, en detalle (el único que no es "por diseño")

El caso es del **24-sep 04:16** (chat con historial de "encuentro"). La secuencia fue:

1. 04:16:45 — escalación automática por palabra clave ("encuentro"). Sin traza.
2. 04:25:52 — tú marcas **falso positivo**.
3. 04:25:53 — el sistema regenera el borrador y este pide **doctrina** (no hay regla para ese caso).
4. El camino que debía abrir una consulta de doctrina **no llegó a crearla** (no hay ninguna
   consulta guardada) y el turno quedó escalado. Como nunca se envió nada, no hay resultado que
   registrar.

**Corrección (2026-10-06, tras revisar el camino en el código):** en este caso **sí recibiste un
aviso**. Cuando un falso positivo no produce borrador, el sistema te manda un mensaje duradero
(no un aviso emergente) explicando el motivo, con un texto propio para cada una de las 14 causas
posibles. La primera versión de este informe decía que el caso "no deja rastro visible para ti":
**eso era incorrecto** — se basaba solo en la base de datos y no llegué a revisar el mensaje de
Telegram. Lo que no queda es registro en la base; el aviso al chat sí existe y está completo.

Comparación que lo confirma: otros dos falsos positivos de esos mismos días, cuyo borrador
regenerado **no** pidió doctrina, **sí** tienen su fila.

**Por qué no llego a más:** para saber *cuál* de las salvaguardas detuvo el paso (chat ocupado,
mensaje viejo, falta de conexión de negocio, etc.) haría falta el log del 24-sep, que ya no existe.
La ruta está probada; el detalle exacto del freno, no.

### Contraste con la ventana viva (30-sep → 6-oct)

Para no depender solo de casos viejos, revisé los 108 turnos de esa ventana que sí llegan al paso de
registro. **Todos los huecos están explicados**:

- 3 con traza incompleta (2 turnos fallidos + 1 plantilla de check-in) → sin fila, correcto.
- 27 turnos de **Atención** (no son VIP; el registro es solo para VIP) → sin fila, correcto.
- 2 turnos de **sandbox** → sin fila, correcto.

Y un dato que cierra el asunto: de las 3 trazas incompletas, **ninguna** escribió fila; de las 105
completas, la mayoría sí. La regla se cumple sin excepciones.

**Conclusión A: PROBADO.** Los 14 huecos no son errores tragados: son cuatro rutas que no pasan por
el registro (tres por diseño, una por un camino que quedó en pausa). La hipótesis de partida
—"no son errores tragados sino rutas de diseño"— **se confirma para 13 de 14**; el restante también
es una ruta sin envío, pero con el detalle del freno sin determinar.

---

## B. ¿Hubo errores tragados el 2 y 3 de octubre?

**Dónde viven los logs de producción:** en el **journal del sistema**, unidad de usuario `diana-bot`
(`systemctl --user`), leídos con `journalctl -t diana-bot`. No hay archivo de log en disco: el bot
escribe a la salida estándar y el journal la captura. La consola de la sesión de terminal **no**
sirve para esto: su historial solo llega al 5-oct.

**Lo que dicen los dos días buscados:**

| Evento | Significado | 2–3 oct | Toda la ventana conservada |
|---|---|---|---|
| `outcome_log_shadow` | Registro escrito correctamente | **37** | **116** |
| `outcome_log_error` | Falló el paso de registro (error tragado) | **0** | **0** |
| `outcome_record_shadow_failed` | Falló el guardado en la base | **0** | **0** |

Los dos turnos del 3-oct que aparecen sin fila (20:20 y 22:03, el mismo chat) **nunca llegaron al
paso de registro**: el log muestra `post_turn_skipped_sandbox` — es el **chat de pruebas**. No es un
error: es el aislamiento del sandbox funcionando.

También verifiqué los avisos de fallo del lado de la dueña (`outcome_owner_resolution_failed`,
`outcome_owner_escalate_failed`): **cero** en toda la ventana.

**Conclusión B: PROBADO.** En el 2-3 de octubre no hubo ningún error tragado en este registro. Los
huecos observados en esa fecha son de ruta (sandbox), no de fallo. Aviso de límite: el journal
conserva solo desde el 30-sep, así que esta afirmación está acotada a esa ventana.

---

## C. Los turnos con puntaje pero sin tu decisión registrada

### Lo que dicen los números

Medí "entregado por Diana pero sin tu decisión guardada", agrupando por período:

| Período | Entregados | Sin tu decisión | Escalados | Sin tu decisión |
|---|---|---|---|---|
| 23-ago → 3-sep (**conexión vieja**) | 17 | **17 (100%)** | — | — |
| 6-sep → 10-sep (**conexión nueva**) | 39 | **34 (87%)** | 11 | **11 (100%)** |
| 12-sep → 27-sep | 110 | **0 (0%)** | 18 | 1 (6%) |
| 11-sep → hoy | 157 | **0 (0%)** | — | — |

Sobre el número del informe previo: el conteo depende de cómo se corta el día (UTC o hora de
México). En UTC da **45**; en hora de México, **42**. El "41" es la misma población con un corte de
ventana algo distinto — **es una diferencia de convención, no de fondo**. Lo relevante es que el
corte es tajante: **antes del 10-sep se pierde casi todo; después, nada.**

### Qué pasó realmente

No fue un cambio de cuenta ni una conexión de negocio distinta. Fue **un defecto en cómo se guardaba
tu decisión**: cada vez que aprobabas, el sistema escribía tu decisión y, **un instante después**, el
mismo turno volvía a pasar por el paso de registro con los datos en blanco y **borraba lo que
acababas de generar**. El resultado es exactamente lo que se ve en la base: filas con puntaje del
borrador y sin tu decisión.

Pruebas de que fue eso y no otra cosa:

1. **El arreglo existe, está fechado y coincide al minuto.** El 10-sep a las 19:42 se corrigió el
   guardado para que no borre lo ya escrito. El **primer** registro de tu decisión en toda la
   historia del sistema es del **10-sep a las 20:19:54** — minutos después del arreglo, y **ninguno**
   antes.
2. **El hueco empieza antes del cambio de cuenta.** Desde el primer día del registro (23-ago) hasta
   el 9-sep hay **cero** decisiones guardadas — 100+ filas. El cambio de cuenta fue el **6-sep**.
   Si la causa fuera la cuenta, el tramo 23-ago → 5-sep (cuenta vieja) estaría bien: está **igual de
   vacío** (17 entregas, 17 sin registrar).
3. **Las aprobaciones sí se resolvieron.** En el tramo 6-10 sep, los 34 turnos entregados tienen su
   aprobación marcada como **aprobada**. O sea: tú aprobaste, el mensaje salió, y solo se perdió el
   registro del resultado. No fue que la aprobación dejara de funcionar.
4. **Después del arreglo no ha vuelto a pasar:** 157 entregas desde el 11-sep, **0** sin registrar.

### ¿La ruta de aprobación depende de datos que cambian con la cuenta?

No. Los **dos únicos** puntos del sistema donde se guarda tu decisión están en
`admin_service.py:1951` (cuando escalas) y `admin_service.py:2174` (cuando apruebas o corriges).
Ambos usan **solo**: el identificador del turno, el VIP y el texto enviado. **Ninguno** usa la
conexión de negocio ni el número del bot. La conexión de negocio, además, cambió una sola vez antes
(8-ago) y otra el 6-sep — coherente con la migración de cuenta — pero el hueco **no** sigue ese
patrón: aparece antes y desaparece con el arreglo del 10-sep, no con el cambio de cuenta.

**Conclusión C: PROBADO.** Los turnos con puntaje y sin tu decisión son consecuencia de un defecto
de guardado, corregido el 10-sep de 2026. El cambio de cuenta y la conexión de negocio quedan
**descartados** como causa. Queda un residuo normal posterior (escalados que decides no resolver, o
casos donde respondes escribiendo directo en el chat — que por decisión de producto del 6-oct no se
comparan contra el borrador).

---

## Consecuencias y qué conviene vigilar

- **Efecto histórico:** el tramo 23-ago → 10-sep no sirve para medir coincidencia. Ya está fuera de
  la ventana de 14 días, así que **no afecta** ninguna decisión de autonomía actual.
- **Lo que sí conviene vigilar** (propuesta, no implementada aquí):
  1. Aviso diario si hay turnos VIP entregados o escalados en las últimas 24 h **sin** fila — ya
     estaba propuesto como vigilante del contrato y sigue teniendo sentido.
  2. Aviso si aparece una fila con puntaje **sin** tu decisión después de una aprobación (detectaría
     de inmediato una recaída del defecto del 10-sep).
  3. ~~Un caso como el del 24-sep (falso positivo que pide doctrina y queda en pausa) hoy no deja
     rastro visible para ti.~~ **Retirado:** verificado en el código, ese caso **sí** te avisa con
     un mensaje duradero. Lo único que no existe es un registro consultable después (métrica o
     panel); el aviso en el momento, sí.

---

## Anexo técnico (para el equipo)

**Puntos de código verificados**

| Ubicación | Qué hace | Relevancia |
|---|---|---|
| `turn_orchestrator.py:432` | Única llamada a `_run_outcome_log` (dentro de `_maybe_post_turn`) | Confirma que hay **un solo** punto de entrada |
| `turn_orchestrator.py:913-936` | Sale en silencio si no hay servicio, si es sandbox, si no hay lector de trazas, si `vip_id` es nulo, si el turno es `superseded`/`failed`, o **si no hay traza** | Explica el grupo 1 (0 trazas) y los 27 turnos de Atención |
| `outcome_log_service.py:458-462` | `_redecide` devuelve vacío si faltan `evaluation` o `comprehension` | Explica el grupo 2 (plantillas) |
| `turn_orchestrator.py:421-426` | `post_turn_skipped_sandbox` | Explica el grupo 3 |
| `deterministic_escalate.py:79-151` | Crea el turno escalado sin Director ni LLM, y **sin** hook post-turno | Explica el grupo 1 (no puede haber traza) |
| `admin_service.py:1566-1709` | `_open_gray_zone_from_fp_resume`: en fallo hace `discard_and_close` y deja el turno escalado; **no dispara** hook post-turno | Explica el grupo 4 |
| `admin_service.py:1217-1290`, `escalation_labels.py:35` | `_fp_not_resumed` traduce el motivo a un aviso al dueño; 14 motivos → 14 mensajes, sin huecos (verificado: el vocabulario y los mensajes coinciden exactamente) | El dueño **sí** se entera del grupo 4 |
| `callbacks.py:790-796` | El aviso se manda como mensaje normal (`message.answer`), no como aviso emergente; el intento de editar la tarjeta está envuelto en `try/except` y no puede suprimir el mensaje | El aviso es duradero y no puede perderse en silencio |
| `admin_service.py:1951`, `:2174` | Únicos `record_owner_outcome` | Ninguno usa `business_connection_id` ni datos de la cuenta |
| `composition.py:788-791`, `:1219-1220` | El servicio se inyecta en Admin y Orquestador solo con la bandera de calidad encendida | Bandera encendida en todo el período (hay filas desde el 23-ago) |

**Commits y fechas**

- `1a4c874` (23-ago) — introduce el registro Fila 4.
- `3ade3b3` (**10-sep 19:42**) — *fix(outcome-log): preserve owner columns and first shadow on
  upsert*. El mensaje del commit describe el defecto: el paso post-aprobación volvía a llamar
  `record_shadow` y el `INSERT ON CONFLICT` **borraba** `owner_outcome`, scores y severidad.
- Primera escritura de decisión de la dueña en la base: **10-sep 20:19:54** (tras el arreglo).

**Consultas usadas** (todas de lectura; reproducibles)

- Cohorte A: `turns` con `vip_id` no nulo, `status NOT IN ('superseded','failed')`, últimos 30 días,
  `LEFT JOIN turn_outcome_log ... IS NULL` → 14 filas.
- Cruce motivo ↔ fila: agrupa por `pipeline_traces.decision->>'reason'` → plantillas 5/5 sin fila,
  sin traza 6/6 sin fila, `ok_for_human_review` 218/220 con fila.
- Cohorte C: `turn_outcome_log` con `draft_score IS NOT NULL AND owner_outcome IS NULL`, unido a
  `turns` (estado `delivered`/`escalated`) y a `pending_approvals`.
- Conexiones: `pending_approvals.business_connection_id` agrupado por fecha.

**Límites de esta investigación**

1. El journal solo conserva desde el **30-sep**; el caso del 24-sep no tiene logs → el freno exacto
   de ese turno queda **sin determinar**.
2. La cifra "41" del informe previo no se reproduce exactamente (45 en UTC, 42 en hora de México);
   se documenta la diferencia en vez de forzar el número.
3. Los grupos 1–3 se probaron con código **y** datos. El grupo 4 se probó a nivel de rama de código
   (la ruta no dispara el registro y no creó consulta), no a nivel de log.
