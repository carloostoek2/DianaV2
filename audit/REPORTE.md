# Reporte de la Ronda 2 — Privacidad

**Fecha:** 2026-10-24 · **Para:** dueña del producto · **Alcance:** tres contratos de privacidad (fotos, video y texto) · **Método:** skill `contract-proof` (rastreo, prueba de punta a punta, sabotaje y propuesta de vigilante).

**Qué se auditó:** lo que Diana promete hacer antes de mandar una foto, un video o un texto a un servicio de IA externo, y qué pasa realmente cuando el VIP manda ese contenido.

**Qué NO se hizo:** no se leyó texto de conversaciones de VIP, no se llamó a los servicios reales de Google ni de DeepSeek, y no se tocó código ni se cambió ninguna bandera. Las pruebas y los sabotajes que se citan son los documentados en las tres fichas; se corrieron en copias de trabajo aparte y se revirtieron, sin tocar producción.

**Cómo se lee el semáforo** (regla dura: sin sabotaje documentado no hay verde):

| Señal | Qué significa |
|---|---|
| 🔴 | Lo prometido **no ocurre** en casos reales, y está medido |
| 🟡 | Ocurre en una parte, pero hay una parte conocida sin probar |
| ⚪ | No hay prueba de efecto: solo se leyó el código |
| 🟢 | Hay prueba de punta a punta **y** sabotaje que demuestra que la prueba falla si se desconecta la pieza |

Contexto: **E2** es una prueba de punta a punta contra una copia real de la base; **E3** es E2 más el sabotaje (desconectar la pieza a propósito y exigir que la prueba falle); **E4** es E3 más un vigilante en producción que avisa si el efecto deja de ocurrir.

---

## 1. Resumen en una mirada

| Contrato | Qué cubre | Semáforo | En una frase |
|---|---|---|---|
| **C-PRV-01** | Fotos | 🔴 | Un documento de identidad **sí sale** cuando la foto además muestra un número de 16 dígitos; una foto que el lector no puede leer también sale, sin revisar |
| **C-PRV-02** | Video | 🟡 | Funciona en videos de hasta 30 segundos (probado y saboteado); en videos más largos la revisión se espacia y ese caso no está probado |
| **C-PII-01** | Texto | 🔴 | Una tarjeta con su fecha de vencimiento o su código de seguridad **viaja en claro** al servicio de IA; lo mismo con puntos, espacios especiales o saltos de línea |

**Lo más importante en una frase:** la cadena está bien construida y en los casos cubiertos funciona (hay sabotajes que lo demuestran), pero en los tres contratos la promesa se rompe en situaciones normales, no exóticas. Dos de esas roturas no se pueden deshacer una vez que el dato salió.

---

## 2. Lo que hay que mirar primero (🔴)

### 2.1 C-PRV-01 — Fotos: el documento de identidad no siempre se queda

**Qué prometía.** Antes de mandar una foto a Google para que la describa, Diana la lee en el propio servidor. Si trae un documento de identidad, no sale nunca, ni siquiera tapada. Si trae tarjeta, cuenta o clave, se tapan las líneas exactas y se comprueba que ya no se lean. Si no se puede verificar, no sale.

**Qué pasa en realidad** (medido de punta a punta, con la entrada real del bot y una copia de la base):

1. **Documento que además trae un número de 16 dígitos.** El sistema decide primero "esto es una tarjeta" y después busca palabras de identidad. Tapa solo esa línea, la comprobación pasa, y la foto del documento —con la palabra DNI o PASAPORTE a la vista— **sí viaja** a Google. Ejemplo sintético usado en la prueba, no una medición de producción: un texto con "DNI 30445566" y "4111 1111 1111 1111" se clasifica como tarjeta y no como identidad.
2. **Foto que el lector local no puede leer.** Si el lector devuelve texto vacío o basura (foto borrosa, muy chica, con poco contraste), eso se interpreta como "no hay nada sensible" y la imagen **viaja idéntica al original**. La promesa dice "si no se puede verificar, no sale"; hoy solo se considera "no verificable" cuando el lector da un error, no cuando no lee nada.
3. **Tarjeta escrita con puntos.** El patrón solo reconoce grupos separados por espacio o guion. Un número como "4111.1111.1111.1111" (ejemplo sintético) viaja limpio, con el número legible.
4. **Cualquier corrida de 16 dígitos se tapa**, aunque no sea una tarjeta. Es el lado seguro, pero ensucia: números de pedido, por ejemplo.
5. **Si falla algo no previsto** (por ejemplo, el procesamiento de la imagen), la foto no se manda, pero queda como una foto común: no se marca como sensible, no se cuenta y la dueña no se entera.
6. **Si la bandera de fotos está encendida pero falta la clave de Google**, todo el camino se apaga en silencio: no hay descripción y la foto tampoco llega al mensaje de aprobación. El único rastro es una línea informativa al arrancar. El chequeo de salud (`/health`) no mira visión.
7. **No hay vigilante de privacidad.** Nadie cuenta cuántas fotos se bloquearon, cuántas se taparon ni cuántas fallaron. Si el filtro se rompe, no se detecta.

**Qué pierde el negocio.** Un documento de identidad, una tarjeta o una foto ilegible de cualquiera de los dos sale a un servicio externo y **no se puede recuperar**. No es un error que se corrige después: es un dato que ya salió. Además, cuando la foto no se analiza por un fallo, la dueña no puede distinguir "era sensible" de "el lector está roto", así que no sabe si revisar o reparar.

**Qué decisión se necesita.** Las preguntas (a) y (b) del apartado 7.

---

### 2.2 C-PII-01 — Texto: la tarjeta con vencimiento viaja en claro

**Qué prometía.** Antes de mandar cualquier texto al servicio de IA, los correos, teléfonos, tarjetas y enlaces se cambian por marcadores; si el modelo los repite en su respuesta, se restauran los valores originales, de modo que ni el VIP ni la traza notan el cambio.

**Qué pasa en realidad** (medido de punta a punta: se capturó el cuerpo exacto que el proveedor habría recibido, con el proveedor real y solo la conexión externa simulada):

1. **Tarjeta seguida de vencimiento o código de seguridad.** El sistema exige que toda la corrida de dígitos pase la validación de tarjeta; si no pasa, no reintenta con la tarjeta sola. Resultado: "4111 1111 1111 1111 12/27", "4111 1111 1111 1111 123" y "4111111111111111 12/27" (ejemplos sintéticos de la prueba) **salen en claro**. Es justamente el formato en que un VIP o la dueña pega una tarjeta con su caducidad.
2. **Separadores no cubiertos.** Solo se aceptan espacio común y guion. Una tarjeta copiada con espacio duro, con puntos o partida por un salto de línea **sale en claro**.
3. **Los datos restaurados quedan en el registro de errores.** Por lectura del código, cuando el proveedor falla se guarda una vista previa del texto **ya restaurado** (hasta 500 caracteres) y varios servicios registran el error completo, que puede incluir el texto del modelo. El registro del sistema se conserva unos 7 días. **Esto todavía no está medido**: requiere una prueba aparte para saber cuánto texto queda realmente.
4. **La traza guarda los originales.** El prompt que sale y el borrador que vuelve quedan en la base con los datos personales tal cual (unos 30 días). Es lo que el contrato pide, pero es dato personal en reposo y hay un script que lo puede exportar.
5. **La restauración es literal.** Si el modelo escribe el marcador con otra forma ("[CORREO]", "[correo ]", "[teléfono]"), el VIP y la dueña ven el marcador en vez del dato.
6. **Apagar la bandera no resiste un cambio de modelo en caliente.** Si la dueña apaga el enmascarado y después cambia de modelo desde el menú, el enmascarado se vuelve a encender. Falla del lado seguro, pero contradice el interruptor.
7. **Sin vigilante.** El único rastro del enmascarado es una línea de depuración con contadores; no hay contador durable ni chequeo en `/health`.

**Qué pierde el negocio.** Una tarjeta real con su vencimiento puede salir al proveedor externo, que es exactamente lo que este contrato existe para impedir. Además, datos personales restaurados pueden quedar en el registro del servidor. Del otro lado, un marcador mal restaurado llega visible al VIP: se ve como un error del bot y rompe la ilusión de conversación natural.

**Qué decisión se necesita.** La pregunta (c) del apartado 7. Lo demás son arreglos técnicos claros (apartado 8).

---

## 3. Lo que funciona a medias (🟡)

### C-PRV-02 — Video: se revisa bien, pero solo hasta 30 segundos

**Qué prometía.** Antes de mandar un video a Google, Diana extrae un fotograma por segundo y los revisa en el propio servidor. Si en cualquiera aparece un documento de identidad o un dato fuerte (tarjeta, cuenta, clave), el video **no sale**, porque un video no se puede tapar. Cuando pesa demasiado para un solo envío, salen únicamente los cuadros ya revisados.

**Qué sí está probado y saboteado.** Con la entrada real del bot: un dato fuerte visible **solo en el segundo 3 de un video de 6 segundos** bloquea el video; si no se extrae ningún fotograma se falla cerrado (el video no sale); con la bandera apagada no se descarga ni se analiza; un video corrupto o de más de 20 MB no se descarga. Al desconectar la revisión o el filtro, las pruebas fallan, lo que demuestra que las piezas están realmente conectadas.

**Qué pasa en realidad fuera de ese rango:**

1. **Videos de más de 30 segundos.** El tope de 30 fotogramas se reparte por todo el video: 60 segundos se revisan uno cada 2 segundos; 5 minutos, uno cada 10 segundos; 10 minutos, uno cada 20 segundos. Un dato que aparezca entre dos muestras pasa como limpio y **el video sale**. **Este caso no tiene prueba de punta a punta**: queda como riesgo abierto.
2. **Texto ilegible.** Si el lector no puede leer un fotograma (video borroso, pequeño, inclinado o en un idioma sin paquete), ese fotograma se considera limpio. Solo se falla cerrado si el lector da un error.
3. **Sin ffprobe** (una de las dos herramientas de video), solo se revisan los primeros 30 segundos de un video largo, y el único aviso es una línea de advertencia.
4. **La rama "video grande: salen solo los cuadros" no se alcanza** con la configuración real: el tope para mandar cuadros es igual al tope de descarga. En la práctica, todo video que se puede descargar se manda completo.
5. **Los cuadros reducidos viajan como PNG rotulados JPEG.** Si el proveedor rechaza el par, la descripción se pierde en silencio (el video no se filtra, pero el negocio pierde la descripción).
6. **Copia temporal en disco.** El video y los cuadros se escriben en una carpeta temporal que se borra al terminar, pero no se sobrescribe: si el proceso muere en el medio, puede quedar el video en `/tmp`. La ficha decía "solo memoria"; hay que corregir esa frase.
7. **Videos de más de 20 MB declarados** no se descargan: no hay descripción y la dueña no sabe por qué (el texto del turno queda igual que si la visión estuviera apagada).
8. **Un video marcado como sensible no se adjunta** al mensaje de la dueña: ella lee "contiene información sensible" pero **no puede ver el video** para revisarlo.
9. **Latencia sin tope global:** si la extracción rápida falla, el respaldo puede tardar hasta unos 15 minutos antes de que el turno exista. Puede retrasar o colgar ese chat.

**Qué pierde el negocio.** En videos largos, la privacidad depende de la suerte del muestreo. En videos pesados, Diana no puede describir lo que el VIP mandó. Y cuando hay algo sensible, la dueña no puede revisarlo visualmente: solo ve el aviso.

**Qué decisión se necesita.** La pregunta (d) del apartado 7.

---

## 4. Lo que no se pudo verificar (⚪)

- **Videos de más de 30 segundos:** no hay prueba de punta a punta del caso que falla (riesgo abierto del apartado 3.1).
- **Caminos de foto y video sin sabotaje individual:** factura, que el texto que acompaña no decida, el par PNG/JPEG de los cuadros y la caída del proveedor. Hay prueba de que el flujo corre, pero no de que la prueba falle si se desconecta esa pieza.
- **El registro de errores del texto (C-PII-01):** está leído en el código, no medido. Falta capturar cuánto texto real queda escrito.
- **La traza del texto:** cubierta de forma indirecta (mismo punto de restauración), sin sabotaje propio.
- **Los vigilantes propuestos en el apartado 6:** no están escritos ni corridos contra datos reales. Por la regla del método, una consulta de vigilancia que no se corrió **está sin verificar**.
- **La matriz de banderas** confirma los valores reales de configuración y del proceso vivo, pero no corrió el flujo con una foto o un video; no sube el nivel de evidencia por sí sola.

---

## 5. Lo que sí funciona (verde de verdad)

No todo está roto. Estos caminos tienen prueba de efecto **y** sabotaje documentado:

**Fotos (C-PRV-01)**
- Un documento de identidad **sin** número de 16 dígitos nunca sale, y la prueba falla si se desconecta el filtro o el lector de identidad.
- La tarjeta válida escrita con espacio o guion se tapa, y una segunda lectura comprueba que ya no se lea; si la comprobación falla, la foto no sale.
- Con la bandera apagada no se descarga nada, no se llama a Google y la foto no viaja.
- La imagen no se guarda en la base ni en disco; el turno se completa y queda el borrador en la cola.
- Una foto marcada como sensible **sí** llega a la dueña para revisión manual.

**Texto (C-PII-01)**
- Las tarjetas Visa y Amex, contiguas o agrupadas, se enmascaran antes de salir; los datos vuelven restaurados al borrador de la cola y a la traza.
- El enmascarado ocurre en el analista, el generador, el evaluador, la extracción de memoria, la síntesis de perfiles y el cambio de modelo en caliente.
- La visión (fotos y video) **no** recibe el texto del chat ni el texto que acompaña a la imagen: la prueba lo comprueba.
- Con la bandera apagada el texto viaja tal cual, que es lo que declara el interruptor.

**Video (C-PRV-02)**
- En videos de hasta 30 segundos, un dato fuerte en cualquier fotograma bloquea el video.
- Cero fotogramas, herramientas ausentes o lector caído: el video no sale (falla cerrado).
- Bandera apagada: sin descarga y sin análisis.
- Video corrupto o de más de 20 MB: no se descarga.

---

## 6. Vigilantes propuestos (propuesta, **no implementados**)

Consultas diarias de solo lectura, pensadas para sumarse al vigilante que ya corre a diario. No están escritas ni corridas contra datos reales: **quedan sin verificar** hasta que se ejecuten. Los umbrales son una propuesta inicial y hay que calibrarlos con el tráfico real.

| Contrato | Qué se cuenta cada día | Cuándo avisa (umbral propuesto) | Quién recibe |
|---|---|---|---|
| **C-PRV-01** Fotos | Fotos que llegaron, analizadas, marcadas sensibles (por motivo), "no verificables" y fallos del camino | (1) cualquier foto sensible que **no** llegue al mensaje de aprobación — debe ser 0; (2) cualquier fallo con etiqueta plana; (3) **3 días seguidos** con 5 o más fotos analizadas y **0** sensibles y **0** no verificables; (4) bandera encendida, fotos llegando y **0** analizadas durante 2 días | Dueña, por su chat de Telegram |
| **C-PRV-02** Video | Videos que llegaron, analizados, bloqueados, no verificables, llamadas al servicio de Google y **cuántos videos pasaron de 30 s** | (1) cualquier video sensible que haya generado una llamada al proveedor — debe ser 0; (2) cualquier video de más de 30 s en el día (aviso de "cobertura reducida"); (3) 2 días con videos llegando y 0 analizados y 0 bloqueados; (4) más de 3 avisos diarios de "archivo demasiado pesado" | Dueña, por su chat de Telegram |
| **C-PII-01** Texto | Llamadas al modelo, llamadas con al menos un dato enmascarado, marcadores por tipo, y un escaneo local de los cuerpos salientes buscando tarjeta, correo o teléfono **sin** marcador (solo conteos, nunca contenido) | (1) cualquier cuerpo saliente con un patrón sin marcador — debe ser 0 (hoy **daría positivo**, por los defectos del apartado 2.2: sirve como guardia después del arreglo); (2) 7 días con 50 o más llamadas y **0** marcadores; (3) cualquier línea de error que incluya texto restaurado | Dueña para (1) y (2); el detalle técnico para (3) |

---

## 7. Decisiones que necesito de ti

Estas cuatro no las puede resolver un programador sin tu criterio, porque cambian lo que el negocio acepta perder o ganar. Mi recomendación va entre paréntesis, pero la decisión es tuya.

**(a) Documento de identidad que además trae un número de tarjeta: ¿bloquearlo siempre?**
- Opción 1 (**recomendada**): si aparece cualquier indicio de documento, la foto no sale nunca, aunque además traiga una tarjeta. Se pierde la descripción de esa foto y la revisas a mano.
- Opción 2 (lo que pasa hoy): se tapa el número y la foto del documento sale al servicio externo. Una vez que sale, no se puede deshacer.

**(b) Foto que el lector local no puede leer: ¿bloquearla siempre?**
- Opción 1 (**recomendada**): si no se pudo leer, no sale y va a revisión manual. Costo: más fotos en tu cola y el VIP espera aprobación. Beneficio: ningún documento o tarjeta borrosa se escapa.
- Opción 2 (lo que pasa hoy): se asume limpia y se manda. Costo: cualquier dato sensible en una foto borrosa sale sin revisar.
- En cualquiera de las dos, conviene que el aviso distinga "trae datos sensibles" de "no se pudo leer": hoy se ven igual y no sabes si revisar la foto o revisar el sistema.

**(c) ¿Aceptas que los datos personales originales queden guardados en la traza?**
- Opción 1 (**recomendada, con condiciones**): sí, porque la traza es tu herramienta para reconstruir qué pasó y qué escribió el VIP. Condiciones: que el dato restaurado **no** se copie al registro de errores (hoy sí se copia, por lectura del código) y que la exportación de trazas quede restringida.
- Opción 2: guardar la traza con marcadores en vez de los datos originales. Menos dato personal en reposo; al revisar una traza verías "[tarjeta]" en lugar del número. Habría que confirmar que eso te sigue alcanzando para auditar.

**(d) Videos de más de 30 segundos: ¿más muestras (más costo) o bloquear cuando no haya cobertura?**
- Opción 1: subir el tope de fotogramas. Hoy el máximo permitido es 120 (dos minutos revisados segundo a segundo). Costo: más procesamiento local y más espera antes del turno.
- Opción 2: revisar hasta 30 segundos y **bloquear** los videos más largos (no se describen, van a revisión manual o se avisa al VIP que no se pudo ver). Privacidad garantizada; se pierde la descripción de los videos largos.
- Opción 3 (intermedia): subir el tope hasta donde el costo sea aceptable y bloquear por encima de ese punto. Necesito que me digas cuánta espera toleras por turno.

---

## 8. Arreglos técnicos que no requieren tu decisión

Defectos claros; solo necesitan trabajo, no criterio de producto. El detalle con `archivo:línea` está en el anexo.

1. Que un documento de identidad gane siempre sobre una tarjeta en la clasificación.
2. Que el lector vacío o poco fiable cuente como "no verificable" (falla cerrado).
3. Cubrir puntos, espacios especiales y saltos de línea en los patrones de tarjeta, tanto en fotos como en texto.
4. Aplicar la validación de tarjeta también a las corridas de 16 dígitos, para no tapar números de pedido sin necesidad.
5. Que cualquier error no previsto marque la foto como sensible y deje contador, en vez de caer como etiqueta plana.
6. Sacar el texto restaurado de los registros de error; registrar solo el tipo de error.
7. Que el cambio de modelo en caliente respete el interruptor de enmascarado.
8. Publicar en `/health` el estado real de la visión (bandera encendida con clave vacía) y del enmascarado.
9. Corregir el rótulo de los cuadros de video (PNG rotulado JPEG) y alinear los topes de envío y de descarga.
10. Poner tope de tiempo global a la extracción de fotogramas y sacar el lector de texto del hilo del bot.
11. Corregir la copia temporal de video y la frase del contrato que dice "solo memoria".
12. Adjuntar el video sensible al mensaje de la dueña (hoy solo se adjunta la foto).
13. Escribir los tres vigilantes del apartado 6 y correrlos contra datos reales antes de darlos por válidos.
14. Avisos operativos menores: `FEATURE_RECONTACT_ENABLED` está apagada sin declarar (el chequeo de salud queda en rojo permanente) y `FEATURE_FORCE_PROFILE_WHEN_NOTES` no está escrita en el `.env`.

---

## 9. Siguiente ronda recomendada

**Ronda 1, que quedó pendiente: "el VIP esperando".** Es anterior a privacidad en el mapa y sigue sin prueba de efecto. El criterio es simple: es lo que puede estar fallando hoy mientras un VIP espera respuesta.

| Orden | Contrato | Por qué |
|---|---|---|
| 1 | **C-ESC-01** Escalación y falso positivo | Es la red de seguridad: si el bot no se anima a responder, la dueña tiene que enterarse. Tiene más de diez ramas que fallan cerrado dejando solo un registro técnico, y hoy se prueba con un director falso |
| 2 | **C-GRZ-01** Zona gris y doctrina viva | Un VIP congelado no recibe nada. El flujo tiene cuatro finales distintos y ninguno tiene prueba de efecto |
| 3 | **C-SUP-01** Un solo turno vivo por chat | Es el invariante que el diseño marca como no negociable; hoy solo lo prueba un almacén en memoria |

**Deuda que deja esta ronda:** prueba de punta a punta de videos de más de 30 segundos; una prueba de paridad foto↔video para que las dos apliquen la misma política; medir qué queda en el registro de errores del texto; y corregir las frases viejas de la ficha de video (ya corregida) y de la matriz de banderas.

---

## Anexo técnico — hallazgos con `archivo:línea`

Para quien implementa. El cuerpo del reporte no depende de estos detalles.

### C-PRV-01 (fotos) — 🔴

| # | Gravedad | Qué | Dónde |
|---|---|---|---|
| 1 | ALTO | La tarjeta se clasifica antes de buscar identidad; un documento con 16 dígitos viaja | `src/diana/application/image_vision_service.py:142-147` vs `:151-157` |
| 2 | ALTO | OCR vacío o basura se trata como limpio; solo la excepción es "no verificable" | `image_vision_service.py:230`; `src/diana/infrastructure/vision/ocr.py:178,190`; excepción en `image_vision_service.py:221-227` |
| 3 | ALTO/MEDIO | Separadores no cubiertos (puntos, etc.) | `image_vision_service.py:51-53` |
| 4 | MEDIO | 16 dígitos se enmascaran antes de Luhn | `image_vision_service.py:142-147`, patrón en `:51` |
| 5 | MEDIO | Excepciones no previstas caen como etiqueta plana sin marca ni contador | `image_vision_service.py:293-304`, `infrastructure/vision/redact.py:55`, `telegram/handlers/business.py:60-67` |
| 6 | MEDIO | Bandera ON + `GEMINI_API_KEY` vacía apaga la visión en silencio; sin check en `/health` | `composition.py:488-505`, `:517-525`, `:528-536`; `image_vision_service.py:209` |
| 7 | MEDIO | Sin vigilante de privacidad | `audit/vigilantes.sql` |
| 8 | MEDIO | OCR síncrono sin timeout dentro del bucle del bot | `ocr.py:304-310`; `image_vision_service.py:222,244,296` |
| 9 | BAJO | La foto al DM es best-effort y falla callada | `telegram/notifier.py:59-73` |
| 10 | BAJO | `describe` devuelve `None` y el turno queda como etiqueta plana indistinguible | `cognitive/image_vision.py:56-71`; `application/media_text.py:33-36` |
| 11 | BAJO | Imágenes de más de 16 MP se marcan sensibles sin analizarse | `ocr.py:182-183,227-228` |
| 12 | INFO | El escáner de cableado no ve esta rama | `audit/WIRING_SCAN.md` §3–§4 |

Evidencia: `tests/audit/test_C_PRV_01.py` (10 casos, 10 pasados; Postgres real, copia `diana_copy.sql` del 2026-10-12). Sabotajes (worktree revertido): S1 filtro limpio → 4 fallos; S4 enmascarado devuelve el original → 4 fallos; S5 sin filtro → 4 fallos; S2 bandera → 1 fallo. Ninguno sobrevivió.

### C-PRV-02 (video) — 🟡

| # | Gravedad | Qué | Dónde |
|---|---|---|---|
| 1 | ALTO | Cobertura temporal: 30 fotogramas repartidos (60 s → 1 cada 2 s; 5 min → 1 cada 10 s; 10 min → 1 cada 20 s) | `src/diana/infrastructure/vision/video_frames.py:151-162`; `settings.py:71`; `.env:42` |
| 2 | ALTO | La detección depende de que el lector lea; texto vacío/parcial se trata como limpio | `application/video_vision_service.py:166-175`; `ocr.py:177-196` |
| 3 | MEDIO | La rama "video grande ⇒ solo cuadros" no se alcanza (tope de envío == tope de descarga) | `telegram/handlers/business.py:31,84-90`; `settings.py:74`; `video_vision_service.py:105-110` |
| 4 | MEDIO | Cuadro ≤1280 px viaja como PNG rotulado `image/jpeg` | `video_vision_service.py:124-132,202-204`; `infrastructure/vision/resize.py:33-42` |
| 5 | MEDIO | Copia temporal del video y de los PNG en `/tmp`; se borra al salir, no se sobrescribe | `video_frames.py:78-80,106-138` |
| 6 | MEDIO | Fail-open genérico sin marca ni contador | `business.py:95-101` |
| 7 | MEDIO | Sin clave de Google, la visión de video se apaga en silencio | `composition.py:506-525`; `video_vision_service.py:84-96` |
| 8 | MEDIO | Respaldo cuadro a cuadro sin tope total (hasta ~15 min) | `video_frames.py:83-87,140-149,237-251` |
| 9 | BAJO | Sin `ffprobe`, solo los primeros 30 s del video | `video_frames.py:158-159` |
| 10 | BAJO | El video sensible no se adjunta al DM | `business.py:143` |
| 11 | BAJO | `_spread` omite el último cuadro al recortar | `video_vision_service.py:194-199` |
| 12 | BAJO | Sin prueba de paridad foto↔video | `video_vision_service.py:32` ← `image_vision_service.py:132` |

Evidencia: `tests/audit/test_C_PRV_02.py` (14 casos, 14 pasados; ffmpeg, ffprobe, tesseract, extractor, OCR y política reales). Sabotajes: S1 → 4 fallos; S5 → 3 fallos; S4 → 4 fallos; S2 → 12 fallos; S3 control negativo (cero cuadros) **siguió en verde**, lo que confirma el fallo cerrado.

### C-PII-01 (texto) — 🔴

| # | Gravedad | Qué | Dónde |
|---|---|---|---|
| 1 | ALTO | Tarjeta seguida de otro grupo de dígitos no se enmascara | `src/diana/llm/pii_masker.py:32`, `:104-115` |
| 2 | ALTO | Separadores no cubiertos (`[ -]?`) | `pii_masker.py:32`; comparar con teléfono `:36-48` |
| 3 | ALTO (leído, no medido) | PII restaurada en el registro de errores | `llm/deepseek.py:324-331`; `logger.exception` en varios servicios |
| 4 | MEDIO | El cambio de modelo en caliente fija `pii_masking=True` | `llm/hot_swap.py:83-93` |
| 5 | MEDIO | PII en reposo en trazas | `cognitive/director.py:671,682,737`; `infrastructure/db/repositories/traces.py:55-60,123-160`; `scripts/export_llm_prompt.py:104-116` |
| 6 | MEDIO | Degradación silenciosa: solo `logger.debug` con contadores | `deepseek.py:184` |
| 7 | MEDIO | Corridas de 13 dígitos y de 10–12 se enmascaran como teléfono | `pii_masker.py:32-48,104-115` |
| 8 | MEDIO | La restauración choca con la compuerta de calidad (texto con PII puntúa 0,0) | `text_quality_heuristics.py:122-127,180`; `callbacks.py:406`; `severity_prefill.py:49-50` |
| 9 | BAJO | Restauración solo literal | `pii_masker.py:135-139` |
| 10 | BAJO | Colisión de marcadores entre mensajes (dormida) | `deepseek.py:170-180` |
| 11 | BAJO | `_mask_messages` omite sin ruido contenido que no sea texto | `deepseek.py:174-182` |

Evidencia: `tests/audit/test_C_PII_01.py` (18 casos, 18 pasados; proveedor real con la conexión externa simulada, capturando el cuerpo HTTP). Sabotajes: S2 → 9 fallos; S4 → 10 fallos; S4b → 2 fallos; S5 → 10 fallos. Ninguno sobrevivió.

### Inconsistencias de documentación detectadas

1. **`audit/contracts/C-PRV-02.md`, sección Camino:** la frase "No hay evidencia E2/E3" quedó corregida el 2026-10-24.
2. **`audit/FLAG_MATRIX.md`, "Qué no se verificó":** dice que los tres contratos siguen en E1; es cierto para el alcance de la matriz, pero las fichas ya tienen E2/E3. Conviene fechar la frase.
3. **`audit/FLAG_MATRIX.md`, P2:** dice que sin `ffprobe` se revisan 10 fotogramas (0 a 9 s); en el camino normal se revisan hasta 30 s; los 10 son solo el respaldo.
4. **`audit/FLAG_MATRIX.md`, F5:** una "imagen ilegible" solo falla cerrado si el lector lanza error; si devuelve vacío, la imagen sale.
5. **`audit/contracts/C-PII-01.md`, punto ciego 15:** "única bandera con default true" es inexacto (`settings.py:128` y `:167` también arrancan en `True`).

---

## Nota de método y límites

- Todo lo afirmado sale de las fichas `C-PRV-01`, `C-PRV-02`, `C-PII-01`, de `audit/FLAG_MATRIX.md`, de `audit/MAPA-CONTRATOS.md` y de la lectura directa del código citado en el anexo.
- Los textos de tarjetas y documentos entre comillas son **ejemplos sintéticos** usados en las pruebas, no datos de ningún VIP ni mediciones de producción.
- No se leyó texto de conversaciones de VIP, no se consultó la base real fuera de la copia de prueba y no se imprimieron claves ni cadenas de conexión.
- No se modificó código, ni fichas, ni banderas, ni el `.env`.
- Una prueba que pasa a la primera es sospechosa: por eso el semáforo verde exige el sabotaje documentado, y ningún vigilante se da por válido hasta que se corra contra datos reales.
