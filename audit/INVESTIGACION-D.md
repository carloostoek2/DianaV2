# Investigación D — Los dos contadores del vigilante

**Qué se investigó:** de dónde salen las dos frases *"Avisos tuyos que no te llegaron: 3"* y
*"lecturas de ánimo que fallaron: 1"*, cuándo ocurrieron, si fueron fallas de Telegram o del bot,
y si hay riesgo de perder avisos importantes.

**Alcance:** solo lectura. No se cambió ni una línea de código, no se mandó ningún mensaje y no se
escribió en la base. **No se leyó ni una conversación**: en todo el análisis se usaron nombres de
evento, horas y cantidades (el contenido de los chats nunca se abrió).

**Registro revisado:** el diario de la unidad del bot, del **30/09 al 10/10** (es todo lo que
conserva).

Cada conclusión va marcada como **probado** (lo verifiqué en el código o en el registro),
**probable** (la evidencia apunta fuerte ahí, pero no la puedo cerrar) o **sin determinar**.

---

## 1. Respuesta corta

- Las dos frases son dos renglones del resumen diario del vigilante, escritos en lenguaje de
  negocio. **No corresponden a dos fallas distintas: son familias.** *"Avisos tuyos que no te
  llegaron"* agrupa todos los casos en que el bot quiso avisarte algo por Telegram y el mensaje no
  salió. *"Lecturas de ánimo que fallaron"* es una sola cosa: no se pudo guardar la medición de
  ánimo de un turno. — **probado**
- **En los 10 días que el registro conserva, ninguna de las dos ocurrió.** El ánimo se midió **135
  veces sin un solo fallo**; y no hay **ni una sola línea** de "el aviso al dueño falló". — **probado**
- Por lo tanto **el "3" y el "1" no son una medición de esos días**. Los únicos lugares donde esas
  dos frases aparecen con esos números exactos son el **informe de entrega del vigilante**
  (`audit/FASE2-VIGILANTE.md`, del 08/10), donde el mensaje se muestra como **ejemplo armado "en
  modo seco"** con datos de prueba. — que el ejemplo está ahí y así rotulado: **probado**; que sea
  exactamente lo que viste: **probable**
- El vigilante **corrió 2 veces y nunca tuvo nada que avisar**. **Nunca te mandó un mensaje.** —
  **probado**
- **Ninguno de los dos contadores cubre escalaciones ni aprobaciones.** Esos avisos no se tragan:
  fallan a la vista y los borradores se vuelven a avisar solos al reiniciar. — **probado**
- Igual hay un hueco real detrás de estos contadores (no el que muestra el ejemplo): **un fallo que
  ocurre y el bot se reinicia antes del chequeo del día queda invisible para siempre.** Se explica
  en §4.3, con el arreglo mínimo propuesto en §5.

---

## 2. Qué cuenta cada frase y por dónde sale

### 2.1 "Avisos tuyos que no te llegaron"

Es la familia de los fallos cuyo nombre interno empieza con `owner_notify_failed`. Ocurre cuando el
bot ya decidió que un turno murió y **el aviso por Telegram hacia tu chat privado no salió**. Todos
pasan por un único punto (`_safe_notify_info`, en `turn_orchestrator.py`), que se traga la falla
para no romper nada más.

| Cuándo se dispara (en palabras de negocio) | Ruta del bot | ¿Está activa hoy? |
|---|---|---|
| Un VIP congelado escribió y su saludo no se envió | carril de saludos (`_prepare_phatic_template_send`) | **sí** (`FEATURE_PHATIC_AUTO_SEND=true`) |
| Un VIP en pausa escribió y su saludo no se envió | carril de saludos | **sí** |
| El saludo quedó vacío y no se pudo avisar | carril de saludos | **sí** |
| Un turno murió porque el análisis del mensaje vino mal formado | pipeline normal | **sí** |
| Un turno murió porque la evaluación vino mal formada | pipeline normal | **sí** |
| Un turno murió porque el contexto del chat se pasó de largo | pipeline normal | **sí** |
| Un turno murió porque el borrador salió vacío | pipeline normal | **sí** |
| Un borrador quedó vacío en la ventana de prueba | sandbox (`_prepare_sandbox_send`) | **sí** (`FEATURE_SANDBOX_AUTO_SEND=true`) |
| Un VIP congelado y el envío automático no salió | envío automático | no (`FEATURE_AUTONOMOUS_MODE=false`) |
| Un envío automático falló al entregar | envío automático | no |
| Un borrador quedó vacío / el VIP estaba congelado, en automático | envío automático | no |

**Detalle fino (probado):** hay **una** ruta más que escribe exactamente el mismo nombre en el
registro (`admin_service.py`, caso "el VIP se congeló mientras el borrador esperaba tu decisión"),
pero **no suma al contador**. Es decir: esa falla se ve en el registro técnico y no en tu resumen.
Hoy esa ruta nunca se disparó, así que no cambia nada de lo anterior; queda anotado porque explica
por qué "el registro muestra algo" y "el resumen cuenta otra cosa" pueden no coincidir.

### 2.2 "Lecturas de ánimo que fallaron"

Es **un solo** fallo: `mood_engine_error`. El bot mide el ánimo del VIP en tres ejes
(juguetón/serio, cálido/distante, energía) y guarda esa medición después de cada turno. Si algo de
ese cálculo o del guardado falla, se traga y suma 1.

Qué se pierde cuando falla: la medición de ese turno no se guarda, y el saludo automático se elige
sin la pista del ánimo (puede salir un saludo menos afinado). **Nunca se pierde un mensaje ni una
decisión.** — **probado** (la bandera `FEATURE_MOOD_ENGINE=true` y el ánimo solo influye en qué
variante de saludo se elige)

---

## 3. Qué pasó de verdad en los días revisados

**Método:** se contaron las líneas del diario por nombre de evento, hora y cantidad. Nada más.

### 3.1 Los dos contadores

| Qué busqué | Cuántas líneas hay en 10 días |
|---|---|
| "el aviso al dueño no salió" (`owner_notify`) | **0** |
| "falló la lectura de ánimo" (`mood_engine`) | **0** |
| mediciones de ánimo guardadas bien (`mood_updated`) | **135** |

### 3.2 El vigilante mismo

| Qué busqué | Resultado |
|---|---|
| corridas del chequeo diario | **2** (08/10 19:51 y 09/10 15:51) |
| resultado de esas corridas | **ok** las dos: 0 alertas, 0 fallas |
| foto de los fallos internos en esas corridas | **vacía** (`swallowed: {}`) |
| mensajes del vigilante hacia la dueña | **0** (nunca escribió) |
| lecturas de `/health` ahora mismo | `swallowed` ausente = proceso sin fallos tragados |

**Conclusión:** no hay un caso que reconstruir. No hay hora, ni error, ni turno asociado, porque el
evento **no ocurrió**. — **probado**

### 3.3 Lo que sí falló en esos días (para que quede claro que el registro está vivo)

Estos fallos reales aparecen en el diario y **ninguno alimenta los dos contadores** (son otro
mecanismo de registro, quedan visibles pero no entran a tu resumen):

| Qué pasó (en palabras de negocio) | Veces |
|---|---|
| La ficha de un VIP no se pudo resintetizar | 4 |
| El modelo de lenguaje devolvió un formato inválido | 4 |
| El arranque de conversación de un VIP nuevo no se pudo hacer | 3 |
| El modelo falló al extraer recuerdos de un turno | 3 |
| Aviso: texto recortado por ser muy largo (huella de parecido) | 3 |
| No se pudo confirmar el toque de un botón tuyo | 1 |
| No se pudo reprocesar un mensaje perdido durante un reinicio | 1 |
| La descripción de una imagen falló (se siguió sin ella) | 1 |
| El servicio de visión devolvió error | 1 |
| Un turno murió por formato inválido del análisis/evaluación | 1 |
| Un turno murió en el armado del borrador | 1 |
| Un mensaje entrante terminó en error | 1 |

El más visible para el negocio es **el arranque de conversación de un VIP nuevo, que falló 3 veces
el 08/10 entre las 05:45 y las 06:12**. Es de otra investigación (no alimenta estos contadores) y su
causa concreta queda **sin determinar**; queda anotado por si conviene mirarlo aparte.

---

## 4. ¿Falla de Telegram o del bot? ¿Se puede perder un aviso importante?

### 4.1 Ánimo: nunca es Telegram

En todo ese camino **no hay ninguna llamada a Telegram**: se lee la traza del turno, se hace la
cuenta y se guarda en la base. Si falla, es el bot o la base. — **probado**

### 4.2 Avisos que no llegaron: Telegram o el bot

Ese camino hace una sola cosa: **mandar el mensaje a tu chat privado**. Si falla, o Telegram no lo
aceptó (el bot fue bloqueado, límite de mensajes, red) o el bot no pudo armarlo. **Cuál de las dos
fue en el caso del ejemplo no se puede saber, porque no hay caso**: no hay una sola línea en el
registro. — **sin determinar** (y por construcción, lo más común sería Telegram: **probable**)

### 4.3 Riesgo de perder avisos importantes: acotado, con un hueco real detrás

**Lo que NO está en riesgo** — **probado**:

- **Los borradores a aprobar** y **las escalaciones** no pasan por este camino: si el envío falla,
  el bot **no lo traga**, lo deja anotado como turno fallido y **vuelve a avisarte** al reiniciar
  (en estos días pasó: hasta **5 re-avisos** en un mismo arranque).
- Además, si una escalación se queda sin que la resuelvas, **el chequeo diario te lo avisa a los 2
  días** ("hay intercambios sin tu decisión registrada"). Hay una red.
- El aviso de pago en Atención usa **otra** etiqueta del resumen (no estas dos), aunque sí tiene una
  consecuencia real.

**Lo que SÍ se pierde en silencio** — **probado**:

- El aviso *"tu turno murió"*. Ejemplo concreto: el VIP escribe, el saludo no sale porque el VIP
  está congelado o en pausa (o el turno muere por un error de formato), y **el bot no te lo cuenta**.
  El turno queda registrado como fallido (se puede ver en la traza), pero nadie te avisa proactivamente.
- El caso más delicado sería un **envío automático fallido**: el VIP no recibe nada y nadie lo dice.
  **Hoy el modo autónomo está apagado**, así que no hay impacto; el día que se encienda, este aviso
  pasa a importar más.

**El hueco de fondo (esto sí conviene arreglarlo)** — **probado** en el código y en las pruebas:

- Los contadores viven en la **memoria del bot**. El resumen que ves es la **diferencia** contra el
  chequeo anterior.
- **Cada reinicio vuelve los contadores a cero.** En 10 días el bot se reinició **41 veces**, y el
  chequeo corre **1 vez por día**: casi siempre el contador arranca de cero entre un chequeo y el
  siguiente.
- Cuando el valor actual es **menor** que el del chequeo anterior, la diferencia da **negativa**, y
  hoy **se descarta en silencio** (hay hasta una prueba que fija ese comportamiento a propósito).
- Consecuencia: **una falla real puede ocurrir y no aparecer nunca en tu resumen**. En esta ventana
  no ocultó nada (no hubo ninguna falla de estos dos contadores), pero el mecanismo es frágil. —
  que el mecanismo puede ocultar fallas: **probado**; que haya ocultado alguna: **no en esta
  ventana** (probado), y en general **probable** que sí pueda.

---

## 5. Arreglo mínimo propuesto (no aplicado)

**A. Comparar sabiendo que hubo reinicio** — 3 líneas en `_delta_swallowed`
(`src/diana/jobs/contract_watchdog.py`).

Hoy: si el valor bajó, se descarta. Propuesto: si el valor actual es **menor** que el anterior, no
es que "bajó", es que **el bot se reinició** — y entonces todo lo que hay ahora ocurrió después del
chequeo anterior y **se reporta completo**. Requiere actualizar la prueba que hoy fija lo contrario
y agregar una prueba del caso "reinicio".

- **Qué gana:** todo lo que falló en el proceso que está vivo al momento del chequeo (hoy queda
  escondido si ese mismo evento ya había fallado antes).
- **Qué no cubre:** una falla cuyo proceso murió **antes** del chequeo. Para eso hace falta contar
  sobre algo que sobreviva al reinicio.
- **Riesgo:** bajo. Solo cambia qué se muestra en el resumen; no toca ningún flujo del producto.

**B. Que la ruta que escribe el nombre en el registro también sume al contador** — 1 línea en
`admin_service.py`. Sin esto, "el registro lo muestra" y "tu resumen no lo cuenta" pueden no
coincidir nunca más.

**C. Rotular el ejemplo del informe de entrega** — 1 línea en `audit/FASE2-VIGILANTE.md`, aclarando
que los números del ejemplo son de prueba y no una medición. Fue exactamente lo que llevó a esta
investigación.

**D. (Más grande, opcional) Contar sobre algo que sobreviva al reinicio.** El registro del sistema
ya guarda ~7-10 días y el bot **ya sabe leerlo** (lo usa para descartar las sesiones de prueba). El
chequeo diario podría contar las fallas ahí en vez de (o además de) la memoria del proceso. Es lo
único que cierra el hueco del todo. Más trabajo, y se puede hacer después de A.

**Recomendación:** aplicar **A + B + C** (chico y sin riesgo para el producto) y dejar **D** como
pendiente anotado.

---

## 6. Hallazgo aparte (no relacionado con esta investigación)

`/health` está reportando `flags.ok = false` porque **`FEATURE_RECONTACT_ENABLED` está apagada y sin
declarar**. Eso hace que el bot **te avise en cada arranque** que hay una bandera de negocio apagada
a propósito. — **probado**

Declararla es una línea (`src/diana/config/banderas_nucleo.py`) y el aviso se calla, pero la
declaración pide **motivo, fecha y condición para reactivarla**, y eso es una decisión de producto:
**¿por qué está apagado el recontacto y desde cuándo?** No lo toqué (esta tarea es solo lectura).

---

## 7. Cómo lo verifiqué

- Código: quién escribe cada contador, en qué rutas y bajo qué banderas
  (`turn_orchestrator.py`, `admin_service.py`, `contract_watchdog_service.py`,
  `jobs/contract_watchdog.py`, `observability.py`, `banderas_nucleo.py`).
- Registro del sistema: conteo por nombre de evento, hora y cantidad de las líneas del diario de la
  unidad, del 30/09 al 10/10. **No se abrió ningún contenido de conversación**; los identificadores
  de chat o de usuario no entraron a este informe.
- Latido del vigilante: `runtime/contract_watchdog.json` (2 corridas, foto de fallos internos vacía).
- `/health` en vivo: estado `ok`, sin contadores de fallos internos, con el hallazgo de §6.
- Fecha del ejemplo: el informe de entrega del vigilante es del 08/10, y su muestra coincide con
  piezas que solo existen en la batería de sabotaje (no con ninguna corrida real).
