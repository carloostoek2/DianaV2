# Investigación C — La recarga de historial está apagada a propósito (y el `.env` dice lo contrario)

Fecha: **2026-10-06** · Autor: auditoría de contratos (skill `contract-proof`, contrato **C-HIST-01**)
Alcance: **solo lectura**. No se cambió código, ni banderas, ni datos, ni el `.env`. No hay commit.
Contenido de los chats y credenciales: **no se muestran**. Solo conteos, fechas, identificadores de VIP y nombres de archivo.

---

## Resumen para la dueña (lo que importa)

La recarga de historial previo de VIPs lleva **apagada desde el 6-sep-2026**, y el comentario del `.env`
todavía dice *"VIVO desde 2026-09-02"*. La decisión de apagarla **tiene sentido**, pero la razón que
quedó escrita no es la razón real, y hay **un matiz que conviene decidir**.

Lo que prometía la recarga: leer el historial de la conversación privada de cada VIP desde tu cuenta
personal de Telegram, un VIP por hora, para que Diana tenga contexto desde el primer turno.

Lo que pasa hoy:

| Pieza | Estado real | Cómo se ve |
|---|---|---|
| **Recarga de historial de VIPs ya existentes** | **Apagada y sin correr** | La bandera está en `false`; el trabajo ni se arma. Cada arranque deja una línea `history_reimport_job_skipped_flag_off` (16 veces desde el 30-sep). El contador de avance quedó congelado el **6-sep a las 03:54 UTC**. |
| **Import de historial al dar de alta un VIP NUEVO** | **Encendido** | Usa **la misma sesión de Telegram** y **no depende de esa bandera**. Se dispara cuando agregas un VIP (comando o menú). Esto no está apagado ni documentado. |
| **Lo que ya se guarda en la base** | Vivo | 15.688 filas de historial; **todas** con su número de mensaje de Telegram. Dos roles: mensajes del VIP y mensajes de Diana. |

Y el hallazgo que más importa, marcado como **indicio a confirmar**:

> **La sesión de Telegram que usa la recarga parece seguir siendo la de la cuenta vieja.** El archivo de
> sesión guarda la lista de conversaciones que esa sesión vio: aparecen los 14 VIP activos y la cuenta
> vieja, y **no aparece la cuenta nueva**. Eso no se puede confirmar del todo sin conectar a Telegram, y
> esta auditoría no conecta. Si es así, encender la recarga hoy **no traería el historial viejo** y además
> te mandaría **un aviso de fallo cada hora**.

**Lo que gana o pierde el negocio hoy:** nada se está rompiendo. Los VIPs activos tienen contexto (historial
+ memorias + ficha). El problema es de **control**: una función apagada que el `.env` declara encendida, y
una ruta parecida (alta de VIP nuevo) que sigue encendida aunque nadie la tenga presente.

**Lo que sí conviene decidir:** (1) corregir el comentario del `.env` y registrar la decisión; (2) decidir
si la sesión de Telethon se re-autoriza con la cuenta nueva o se deja como está; (3) que una bandera núcleo
apagada avise al arrancar en vez de quedarse solo en el registro técnico.

---

## Cómo accedí a los datos (transparencia)

- **Código**: lectura directa del repositorio (`infrastructure/telethon/vip_history_fetcher.py`,
  `application/vip_history_seed.py`, `application/history_reimport.py`, `jobs/history_reimport.py`,
  `composition.py`, `main.py`, `telegram/media_tags.py`).
- **Base de datos real**: conexión **de solo lectura** (transacción marcada como *read only*), tomando la
  dirección que el propio bot usa (`.env`). Ninguna escritura. Ninguna credencial se copió a un archivo ni
  a una salida.
- **Archivo de sesión de Telegram**: copia del archivo a un directorio temporal y lectura **de solo
  lectura** de su índice interno. Se leyó **solo** la lista de identificadores y fechas de conversaciones;
  **no** se leyó ni se mostró la clave de sesión, teléfonos ni nombres de personas.
- **Registro de producción**: `journalctl` de la unidad de usuario del bot (retención: desde el 30-sep).
  Por eso lo anterior al 30-sep se responde con la base, no con registros.
- **No se conectó a Telegram.** Verificar a qué cuenta pertenece la sesión exige abrir la sesión con la API
  de Telegram, y esta auditoría es de solo lectura. Queda como **pendiente de confirmación**.
- **Nivel de prueba alcanzado**: **E2 parcial**. El efecto de la recarga está **probado por evidencia en la
  base real** (ver §1.3), no por reproducir el ciclo. **No** se corrió un ciclo completo ni se hizo la
  prueba de sabotaje (E3): el contrato C-HIST-01 no puede pasar a verde todavía.

---

## 1. ¿Qué traería la recarga si se encendiera con la cuenta nueva?

### 1.1 Lo que dice el código, paso a paso

1. El trabajo corre **un VIP por hora** (configurable). Eso es una protección explícita para tu cuenta: el
   comentario del código dice que así *"Telegram nunca ve más de una consulta de sesión personal por hora"*.
2. Para cada VIP, el importador abre **una sesión personal de Telegram** (el archivo `diana_session.session`)
   y busca la conversación privada con ese VIP. Para encontrarla intenta tres cosas, en orden: por número
   de usuario, por nombre de usuario, y si falla, recorre **toda** tu lista de conversaciones buscando el
   número de usuario.
3. Una vez encontrada la conversación, lee **los últimos 20 mensajes** y los copia al historial de Diana,
   marcando como "Diana" los que salieron de tu cuenta y como "VIP" los que escribió la otra persona.
4. Antes de guardar, **descarta los mensajes que ya están**: compara por el número de mensaje de Telegram.
   Por eso repetir la pasada no duplica nada: donde el bot ya capturó todo en vivo, la recarga no agrega nada.

Puntos donde la cadena se rompe **en silencio** (evidencia en código):

- `composition.py:1406-1408` — si la bandera está apagada (o falta configuración de Telethon, o la memoria
  está apagada), **el servicio de recarga ni se construye**. Sin error.
- `main.py:285-288` — si el servicio no existe, el trabajo no arranca: **una línea de registro y nada más**.
- `composition.py:228` — si falta la configuración de Telethon, el import queda apagado con un registro
  informativo, sin alerta.

### 1.2 Lo que depende de cómo opera Telegram (a confirmar contigo)

Aquí está el punto de negocio. **Telegram no traslada el historial de una cuenta a otra.** El historial de
una conversación privada vive en la cuenta que participó de esa conversación. Por eso:

- Una **cuenta recién creada** no tiene conversaciones previas con tus VIPs. Al buscar la conversación, los
  tres intentos del paso 2 fallarían y el resultado sería *"no se pudo importar"*. **No traería el historial
  viejo**: ese historial pertenece a la cuenta anterior.
- Si un VIP te escribió **después** del cambio de cuenta, la recarga sí vería esos mensajes… pero son los
  mismos que el bot **ya guardó en vivo**, así que el descarte del paso 4 los ignoraría. Resultado neto:
  **no agrega nada**.
- Y hay un costo: pedir historial de forma masiva desde una cuenta nueva es exactamente el patrón que llama
  la atención de Telegram. Eso es lo que la decisión buscaba evitar.

**Conclusión con lo que dice el código:** con la cuenta nueva, la recarga **no tiene de dónde traer el
historial viejo** y no aporta contexto nuevo. La decisión de dejarla apagada es correcta.

### 1.3 Pero la recarga SÍ funcionó cuando estuvo encendida (evidencia en la base real)

Esto no es una suposición: quedó rastro en la base.

El importador etiqueta las fotos como `[foto]`. **El camino en vivo nunca escribe esa palabra** (usa
`[imagen]`, en `telegram/media_tags.py`). Es una huella exclusiva del importador. En la base hay
**2 filas** con esa huella:

| Fila | VIP | Fecha del mensaje | Posición en la tabla |
|---|---|---|---|
| 9755 | 680698671 | 23-ago-2026 | en medio de un bloque de 16 mensajes del mismo VIP |
| 9823 | 1280444712 | 31-ago-2026 | en medio de un bloque de 14 mensajes del mismo VIP |

Esos bloques contienen mensajes con fechas de **agosto**, pero ocupan posiciones de la tabla que
corresponden a inserciones del **2-sep** (los números de fila vecinos son de tráfico en vivo del 2-sep).
Es decir: **mensajes viejos escritos en una fecha posterior** — exactamente lo que hace la recarga.

Además, el contador de avance quedó en el VIP 7844198775 con marca de tiempo **6-sep 03:54 UTC**, y el
propio archivo de sesión registra conversaciones resueltas **hora tras hora** el 3-sep (06:20, 06:33,
07:33… 17:33), todas de VIPs distintos: es la firma del trabajo avanzando de a un VIP por hora. O sea: la
recarga **corrió del 2-sep al 6-sep** y **sí escribió en la base**.

> **Límite honesto:** el historial no guarda de dónde vino cada fila. No existe una columna de "origen" ni
> de "cuándo se insertó". Por eso, después del hecho, **no se puede medir cuánto aportó la recarga** — solo
> se puede afirmar que aportó algo, con las dos filas de arriba como prueba. Esto también significa que hoy
> **no hay forma de vigilar** que la recarga esté funcionando.

### 1.4 El indicio sobre la sesión (a confirmar contigo)

Al inspeccionar el archivo de sesión (sin leer credenciales) apareció esto:

| Qué se buscó | Resultado |
|---|---|
| Cuenta vieja (6181290784) en la lista de conversaciones de la sesión | **Presente**, registrada el 3-sep |
| Cuenta nueva (8788842027) | **Ausente** |
| Fecha de la última escritura del archivo | 22-sep-2026 00:37 UTC |
| Conversaciones en la lista | 644 (junio, julio y septiembre) |
| Los 14 VIP activos | **Todos presentes**, la mayoría registrados el 2 y 3-sep |

Las conversaciones se registraron **hora por hora** el 3-sep, que es justo la ventana en que la recarga
corría. Y la lista arrastra conversaciones de junio y julio: **es el mismo archivo desde antes del cambio
de cuenta**, no uno nuevo.

**Lo que esto sugiere** (y hay que confirmar contigo): la recarga seguiría usando la sesión de la cuenta
vieja. Si esa sesión ya no es válida, encender la bandera haría que el trabajo falle **una vez por hora** —
y, ojo, en ese caso **sí te avisaría**: el código manda un mensaje a la dueña por cada unidad fallida
(*"Re-importado de historial del VIP … falló; se reintentará en la próxima pasada"*).

**Preguntas para ti (no hace falta saber de código):**

1. La cuenta nueva, ¿se creó desde cero, o se reutilizó el número de la cuenta anterior?
2. ¿Se volvió a autorizar la sesión de Telegram para la cuenta nueva, o quedó la de antes?
3. ¿Tienes todavía acceso al historial de los chats de la cuenta anterior (por ejemplo, un respaldo
   exportado)? De eso depende si el historial viejo es recuperable por algún camino.

---

## 2. El VIP con pocos mensajes: ¿hay otras fuentes de contexto?

Primero, una corrección al comentario del `.env`: hoy **no hay "varios VIPs" con 1 a 5 mensajes**. De los
14 VIPs activos, **solo uno** cae en esa franja.

| VIP | Mensajes del VIP | Mensajes de Diana | Memorias | Ficha | Ejemplos | Trazas |
|---|---|---|---|---|---|---|
| 8362289109 | **5** (15 y 16-ago) | 88 | 8 | 1 | 0 | 0 |
| 6119775019 | 22 | 13 | 11 | 1 | 0 | 0 |
| 1023298333 | 22 | 67 | 10 | 1 | 0 | 3 |
| 8466399668 | 39 | 206 | 30 | 1 | 0 | 25 |
| … los demás (10 VIPs) | entre 41 y 364 | — | entre 11 y 55 | 1 | 0 | — |

*(Mensajes del VIP y de Diana: totales por chat en `message_history`, sin distinguir origen.)*

Respuestas concretas:

- **Rol `bot`: no existe.** El historial solo tiene dos roles: `vip` (lo que escribió la otra persona) y
  `owner` (lo que salió de tu lado, incluidos los envíos del bot). No hay una tercera fuente por ahí.
- **`message_history` con rol `owner`: sí, y es la fuente más grande.** En el caso escaso hay **88 mensajes
  de tu lado** contra 5 del VIP. Contexto hay, pero **casi todo es de Diana**, no del VIP.
- **`memories`: sí.** Entre 8 y 55 por VIP; el caso escaso tiene 8.
- **`backfill_queue`: no aporta.** Sus 19 filas están todas en estado `done`. No hay reproceso pendiente.
- **Ficha de perfil (`vip_profile`): sí**, una fila por VIP.

**Conclusión:** para ese VIP el contexto **no es escaso en volumen** (93 filas de historial + 8 memorias +
ficha), pero es **escaso en la voz del VIP**: sabemos mucho de lo que Diana dijo y poco de lo que él dijo.
Eso es lo que la recarga habría compensado — y es justo lo que ya no se puede recuperar por esta vía.

Ojo con una limitación de fondo: como el historial **no guarda el origen de cada fila**, no se puede
distinguir "mensaje capturado en vivo" de "mensaje traído por la recarga". Cualquier cuenta que se haga
hoy sobre "cuánto historial se recuperó" es una estimación, no una medición.

---

## 3. Texto para registrar la decisión (redactado, **no aplicado**)

### 3.1 Corrección del comentario en `.env` (reemplaza las líneas 103-106)

```
# Re-import de historial pre-existente de VIPs registrados antes del seed fix
# (1 VIP/hora vía Telethon; el backfill solo re-corre si el seed añadió mensajes).
# APAGADO A PROPÓSITO desde 2026-09-06 (decisión de producto, cambio de cuenta):
# al pasar a la cuenta nueva se apagó la recarga porque una cuenta recién creada
# no tiene conversaciones previas que traer y pedir historial masivo desde una
# cuenta nueva expone la cuenta ante Telegram. El comentario anterior ("VIVO
# desde 2026-09-02") quedó obsoleto.
# Condición para reactivarla: una sesión de Telethon de una cuenta que sí tenga
# los chats con los VIP (ver audit/INVESTIGACION-C.md). Ojo: el alta de un VIP
# nuevo sí importa historial con la misma sesión y NO depende de esta bandera.
FEATURE_HISTORY_REIMPORT_ENABLED=false
```

### 3.2 `faltantes.md` — agregar en §6 (Operativo / despliegue)

```
- **Recarga de historial previo de VIPs — apagada a propósito desde 2026-09-06 (decisión de producto).**
  `FEATURE_HISTORY_REIMPORT_ENABLED=false` en `.env`. Se apagó en el mismo cambio en que el bot pasó a la
  cuenta nueva de Telegram: una cuenta recién creada no tiene conversaciones previas con los VIP, así que la
  recarga no tenía qué traer, y pedir historial masivo desde una cuenta nueva expone la cuenta. **Condición
  para reactivarla:** contar con una sesión de Telethon de una cuenta que sí tenga esos chats (la recarga lee
  el historial de la cuenta dueña de la sesión, no de la base). **Ojo:** el alta de un VIP nuevo importa
  historial con la misma sesión y esa ruta **no** está cubierta por esta bandera. Fuente:
  `audit/INVESTIGACION-C.md`.
```

### 3.3 `wiki/entities/specs/estado-del-proyecto.md` — agregar en "Pendientes reales"

```
- **Recarga de historial previo de VIPs** — **apagada a propósito desde 2026-09-06** por el cambio de cuenta
  de Telegram (una cuenta nueva no tiene conversaciones previas que traer, y pedir historial masivo desde una
  cuenta nueva expone la cuenta). **Condición para reactivarla:** una sesión de Telethon de una cuenta que sí
  tenga esos chats. El alta de VIP nuevos sí importa historial y **no** depende de esta bandera.
```

Y en el encabezado del archivo: subir `updated:` y la fecha del párrafo de síntesis a **2026-10-06** (hoy
dicen 2026-08-21).

> **Nota de coherencia:** el archivo canónico de ese resumen es `docs/ESTADO-PROYECTO.md`, que la propia wiki
> cita como fuente. Si se registra la decisión, conviene escribirla también ahí para que no vuelvan a
> divergir. (`docs/ARCHITECTURE.md:142` ya lista la bandera como `false`, así que ese documento no necesita
> cambio; y `CHANGELOG.md:232` describe el comportamiento por defecto, tampoco.)

---

## 4. Propuesta: un aviso al arrancar cuando una bandera núcleo está apagada (solo diseño)

**El problema, con el caso de esta investigación como ejemplo.** Hoy, una bandera apagada se ve en el
registro técnico y en ningún otro lado. `FEATURE_HISTORY_REIMPORT_ENABLED=false` convivió **un mes** con un
comentario que decía lo contrario, y nadie lo notó hasta una auditoría. El registro del arranque dice
`history_reimport_job_skipped_flag_off`, en inglés, en medio de cientos de líneas. Nadie lee eso.

**Diseño propuesto (sin código):**

1. **Definir un catálogo corto de "banderas núcleo".** Son las que, si están apagadas, cambian lo que el
   negocio recibe. Candidatas: memoria, contexto, zona gris, corrección→aprendizaje, calidad
   (Destacar/Reprender), modo general/atención, promo, visión de imágenes, protección de datos personales y
   recarga de historial. **Quedan fuera** las banderas de medición (las que solo miden y no deciden nada) y
   los interruptores que se apagan a propósito por seguridad.
2. **Al arrancar, comparar el estado real contra ese catálogo** y armar la lista de las que están apagadas.
3. **Mandar UN solo mensaje a la dueña por arranque**, con la lista y una frase de qué se pierde en cada una
   (por ejemplo: *"la recarga de historial está apagada: los VIPs con poco historial no se completan"*). Ya
   existe el precedente de avisar a la dueña desde el arranque (se usa, por ejemplo, al reanudar esperas de
   VIPs tras un reinicio).
4. **Que no se repita.** Se guarda el último aviso enviado y solo se vuelve a avisar si **cambió la lista**.
   Un aviso que llega en cada reinicio se vuelve ruido y se ignora, que es el problema que se quiere evitar.
5. **Declarar las excepciones.** Toda bandera apagada **a propósito** se declara con su motivo y su fecha
   (por ejemplo, junto a la bandera en el `.env`, siguiendo la regla de prioridad ya vigente). El aviso
   menciona **solo** las que no están justificadas. Así, apagar algo con motivo no genera aviso, y apagarlo
   sin decirlo sí.
6. **No frena nada.** Es un aviso, no un bloqueo: el bot arranca igual. El mismo resumen queda en el
   registro como advertencia, para que sobreviva en el historial técnico.
7. **Criterio de aceptación** (para cuando se implemente): apagar una bandera núcleo sin declararla produce
   un mensaje a la dueña en el siguiente arranque; declararla con motivo no produce mensaje; y dos arranques
   seguidos sin cambios no repiten el aviso.

---

## 5. Qué NO se pudo verificar (y por qué)

| Pregunta | Por qué queda abierta |
|---|---|
| ¿A qué cuenta pertenece hoy la sesión de Telegram? | Exige abrir sesión contra Telegram. Fuera del alcance de solo lectura. Hay **indicio fuerte** de que sigue siendo la cuenta vieja (§1.4). |
| ¿Cuánto historial aportó realmente la recarga? | El historial no guarda de dónde vino cada fila. Solo se pudo probar que **aportó algo** (§1.3). |
| ¿La recarga traía los mensajes correctos? | No se corrió un ciclo ni se hizo prueba de sabotaje (E3). El contrato C-HIST-01 sigue **sin poder pasar a verde**. |
| ¿Qué pasó exactamente entre el 2 y el 6-sep? | El registro de producción solo conserva desde el 30-sep. La reconstrucción se hizo con la base y el archivo de sesión. |

---

## Semáforo del contrato C-HIST-01

| Parte | Estado | Motivo |
|---|---|---|
| (a) Cada mensaje que sale de Diana queda en el historial | 🟡 | 15.688 filas, **todas** con número de mensaje. Vivo en producción. Falta la prueba de punta a punta y el sabotaje. |
| (b) El historial previo del VIP se recarga | 🔴 | **No ocurre**: bandera apagada desde el 6-sep por decisión de producto, y con la sesión actual no tendría qué traer. El `.env` decía lo contrario hasta hoy. |
