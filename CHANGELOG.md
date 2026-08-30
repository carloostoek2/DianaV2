DianaV2 Changelog

Este documento registra cómo ha ido evolucionando Diana y, sobre todo, qué problema intentamos resolver con cada cambio.

La idea no es listar cada modificación del código, sino dejar constancia de las decisiones que han ido convirtiendo a Diana en el sistema que es hoy.

---

Re-importado del historial de los VIP existentes, sin riesgo para la cuenta — 2026-08-28

Cuando corregimos la importación de historial, quedó un pendiente: los VIP que ya estaban registrados nunca recibieron su historial previo, porque el bug de "ya había mensajes guardados" bloqueaba la importación el mismo día del alta. Reimportar ese historial requiere entrar al chat personal con la cuenta de Diana, y hacerlo de golpe sería un movimiento agresivo que Telegram podría sancionar. Por eso el re-importado se programa como el backfill original: un solo VIP por hora, sin excepción.

Técnicamente, esto representa: un nuevo job de aplicación que rota sobre los VIPs activos (uno por ciclo, con intervalo configurable por defecto 1 hora), reutilizando la importación ya corregida e idempotente, y re-encolando el backfill de memoria solo cuando la importación agregó mensajes nuevos.

- Se procesa un VIP por hora (configurable con `HISTORY_REIMPORT_INTERVAL_SEC`, por defecto 3600).
- El avance se guarda en la base de datos: si el bot se reinicia, continúa por donde iba, no vuelve a empezar.
- La importación no duplica nada: solo agrega los mensajes que faltan del chat personal.
- El perfil se reprocesa (backfill de memoria) únicamente cuando entraron mensajes nuevos; si no había nada que importar, no se gasta trabajo del modelo.
- La dueña recibe un aviso por cada VIP con historial importado (con el paso "X de N") o si algo falla; los ciclos sin novedades son silenciosos.
- Se activa con `FEATURE_HISTORY_REIMPORT_ENABLED=true` (apagado por defecto, para que el arranque sea siempre el mismo hasta que se decida).

Verificación: 3414 tests pasando (3225 unitarios + 43 e2e sin base + 146 e2e con base).

---

Un escalón más de pensamiento para los borradores — 2026-08-28

Diana pensaba los borradores de texto libre con el esfuerzo de razonamiento más bajo: suficiente para respuestas simples, pero corto cuando el mensaje pedía más cuidado. Subimos un escalón para que el modelo razone un poco más antes de escribir cada borrador, con mejor calidad en tono, contexto y detalle a cambio de un poco más de tiempo y consumo por borrador.

- El esfuerzo de razonamiento de los borradores pasa de "low" a "medium" (escalón intermedio de low/medium/high).
- Se puede ajustar sin tocar el código con la variable `LLM_THINKING_EFFORT` (low, medium o high).
- Los nodos de análisis en formato JSON (Analista, Evaluador) no cambian: siguen sin razonamiento extendido, igual que antes.
- El mecanismo de respaldo sigue intacto: si el razonamiento agota el presupuesto, Diana reintenta y, si hace falta, escribe el borrador sin pensar.

Verificación: 3256 tests pasando (3213 unitarios + 43 e2e sin base + 187 e2e con base).

---

Importación de historial que ya no se salta a los VIP nuevos — 2026-08-28

Cuando un VIP nuevo se registra, Diana intenta importar su historial previo del chat de la cuenta personal para arrancar con contexto y destilar la memoria desde el primer día. Pero el sistema tenía una trampa: si el chat ya tenía cualquier mensaje guardado —aunque fueran solo los del canal de Atención de ese mismo día, o una respuesta del bot— daba por hecho que el historial ya estaba importado y avisaba "ya había mensajes guardados; no se reimportó". Resultado: los VIP que se suscriben el mismo día en que empiezan a hablar con el negocio se quedaban sin su historial previo, justo lo que alimenta la memoria.

Técnicamente, esto representa: separar "el chat tiene filas" de "el historial previo ya fue importado", haciendo la importación idempotente en lugar de condicional.

- Al registrar un VIP, la importación se intenta siempre, sin el chequeo que la saltaba.
- Solo se guardan los mensajes que no estén ya en el historial (identificados por su id de Telegram), así no se duplican los mensajes del canal de Atención ni las respuestas ya guardadas.
- La importación se puede repetir sin riesgo de duplicar nada.
- El aviso a la dueña ahora dice cuántos mensajes se importaron de verdad, o que no había historial previo que importar.

Verificación: 3398 tests pasando (3211 unitarios + 187 e2e).

---

Penalización proporcional por gravedad de corrección — 2026-08-28

No me parecía justo que todas las correcciones de la dueña pesaran igual en la confianza de Diana. Un ajuste de tono para suavizar un borrador frío no es lo mismo que un incumplimiento doctrinal o un riesgo de seguridad, y quería que el sistema distinguiera esas situaciones sin volver a delegar el juicio en un LLM: la lección del incidente de calibración es que un número que gobierna la autonomía no debe moverse por un proceso automático sin supervisión.

Técnicamente, esto representa: generalizar el decremento fijo del presupuesto de confianza a una escala de tres niveles, donde la gravedad la decide la dueña con un toque y el sistema solo sugiere, nunca juzga.

- Al corregir, la dueña ahora indica la gravedad con un toque: 🎨 Tono, 📋 Contenido o ⚠️ Doctrina/Seguridad.
- El sistema preselecciona la gravedad de forma determinista (sin LLM): si el turno tuvo una consulta de zona gris, si la evaluación marcó doctrina o seguridad por debajo del umbral, o si el borrador activó un gate de seguridad, preselecciona Doctrina/Seguridad. La dueña siempre puede cambiarla.
- El botón de gravedad no bloquea la corrección: si la dueña no responde, se aplica la preselección y la corrección se entrega igual.
- Cada nivel tiene su propio castigo: Tono −0,08, Contenido −0,20 (idéntico a hoy) y Doctrina/Seguridad −0,35. El castigo mínimo sigue pesando más que el premio, así que la asimetría conservadora se mantiene.
- La severidad queda registrada en el historial de resultados del turno y la ficha del VIP muestra el desglose de correcciones por nivel.

Verificación: 3225 tests pasando (3209 unitarios + 16 e2e de base de datos).

---

Enmascarado local de datos sensibles en imágenes — 2026-08-27

Cuando añadimos la visión, resolvimos la privacidad bloqueando: si una foto contenía un dato sensible, no salía del servidor y la revisaba la dueña. Es seguro, pero desperdicia fotos útiles que solo tienen un dato puntual, como una tarjeta sobre un ticket. Quería aplicar a las imágenes el mismo criterio que ya usamos con el texto: enmascarar lo sensible antes de externalizar, en lugar de descartar todo.

Técnicamente, esto representa: llevar la frontera de privacidad que ya existe en las llamadas al LLM —donde enmascaramos emails, teléfonos y tarjetas en el texto— hasta los píxeles de la imagen, con la misma regla: los datos sensibles nunca salen del servidor en forma legible.

- El OCR local ahora extrae las cajas reales de cada línea de texto, no solo el texto.
- Si la imagen contiene un dato fuerte (tarjeta, cuenta bancaria o clave), se pintan de negro las líneas completas que lo contienen, con un margen de seguridad para que el antialiasing no deje píxeles legibles.
- La imagen tapada se vuelve a analizar antes de salir: si todavía se lee algún dato fuerte, no sale y pasa a revisión manual de la dueña. Solo viaja cuando la verificación confirma que está limpia.
- Los documentos de identidad nunca salen del servidor, ni siquiera tapados.
- Las facturas y los recibos viajan tal cual: el importe queda visible porque es el comprobante de pago, decisión de la dueña.
- El prompt de descripción indica ignorar por completo las zonas tapadas: no mencionarlas ni intentar adivinar qué hay debajo.
- La copia enmascarada es efímera: no se guarda en disco ni en la base de datos.
- El caption del VIP ya no participa en la decisión de la imagen: es texto y lo procesa el control de seguridad de texto del pipeline, igual que cualquier mensaje.
- Todo sigue protegido por el mismo interruptor "FEATURE_IMAGE_VISION_ENABLED": apagado = comportamiento anterior completo.

Verificación: 3349 tests unitarios pasando.

---

Visión de imágenes con privacidad local — 2026-08-26

Quería que Diana pudiera entender las fotos que recibe un VIP, pero no estaba dispuesto a resolverlo enviando imágenes directamente a un proveedor externo. La nueva capacidad tenía que respetar la misma filosofía de privacidad y supervisión que el resto del sistema.

Técnicamente, esto representa: llevar el principio de privacidad antes que comodidad a una nueva modalidad de entrada.

- Diana puede recibir fotos y obtener una descripción breve mediante Gemini.
- Antes de salir del servidor, un OCR local revisa la imagen en busca de información sensible.
- Tarjetas, facturas, documentos de identidad, credenciales y cuentas bancarias nunca se envían al proveedor externo.
- Si la imagen es ilegible o el OCR no está disponible, cerramos el flujo por seguridad.
- Las imágenes sensibles llegan a la revisión de la dueña junto con un borrador ciego.
- La imagen no se persiste ni alimenta memoria, perfiles o ejemplos.
- La descripción entra al pipeline como texto, por lo que el núcleo cognitivo no tuvo que modificarse.
- La funcionalidad está protegida por "FEATURE_IMAGE_VISION_ENABLED".

Verificación: 3130 tests unitarios pasando.

---

Propuestas de reglas para zonas grises — 2026-08-25

No quería que Diana tuviera que inventar una regla cuando se encontrara con un caso que nuestra doctrina todavía no cubría. Pero tampoco quería que la dueña tuviera que construir siempre esa regla desde cero.

Técnicamente, esto representa: convertir “cuando no sé, pregunto” en un flujo de resolución asistida, sin darle autonomía a la propuesta.

- El sistema puede proponer una regla, una respuesta y un alcance.
- La propuesta utiliza únicamente contexto general y de solo lectura.
- La dueña decide si adopta la regla, escribe otra o escala el caso.
- Aceptar una propuesta siempre pasa por el flujo normal de regla → regeneración → aprobación.
- Si la regla no resuelve correctamente el caso, volvemos a zona gris en lugar de enviar algo a ciegas.
- La propuesta queda asociada a la consulta abierta para poder recuperarla durante el flujo de resolución.

Verificación: 3079 tests unitarios pasando.

---

Contexto persistente y perfiles semánticos — 2026-08-21

Desde el principio he querido que Diana trabaje con contexto acumulado, no solamente con el historial inmediato. Ya teníamos memoria y perfiles, pero todavía había piezas del contexto que no estaban realmente integradas en la arquitectura vectorial.

Técnicamente, esto representa: hacer que “contexto antes que respuesta” sea una propiedad real de la infraestructura.

- El contexto temporal ahora se persiste y se recupera mediante embeddings.
- Los perfiles utilizan embeddings reales en lugar de vectores vacíos.
- Añadimos recuperación semántica de perfiles.
- Alineamos los flags de memoria y contexto con el estado de Fase 2.
- Los datos expirados se limpian automáticamente.

Verificación: 2972 tests unitarios pasando.

---

Recontacto personalizado y promoción de doctrina — 2026-08-22

Quería que Diana pudiera volver a contactar a un VIP sin sonar como si estuviera ejecutando una plantilla ciega. Al mismo tiempo, las reglas descubiertas en zona gris necesitaban un camino claro para convertirse en conocimiento operativo.

Técnicamente, esto representa: utilizar el contexto acumulado para personalizar comportamiento sin introducir una segunda ruta cognitiva difícil de controlar.

- El recontacto ahora puede personalizarse con memoria visible, tendencia del perfil y políticas activas.
- Si algo falla, volvemos automáticamente a la plantilla base.
- Las reglas resueltas desde zona gris pueden entrar a la cola de revisión para convertirse en políticas reales.

Verificación: 2861 tests unitarios pasando.

---

Control de políticas, historial de perfiles y cambio de LLM — 2026-08-22

A medida que Diana crecía, necesitábamos más control sobre lo que una regla significa, cómo evoluciona un perfil y qué modelo está ejecutando el sistema.

Técnicamente, esto representa: hacer que la evolución del sistema sea reversible y observable desde la superficie administrativa.

- La dueña puede definir si una regla aplica a un VIP o a todos.
- Los perfiles conservan historial de versiones.
- El modelo de IA puede cambiarse sin reiniciar el proceso.
- La configuración activa se puede consultar y modificar desde Telegram.

Verificación: 2841 tests unitarios pasando.

---

Modo sombra desde el menú de la dueña — 2026-08-22

No quería activar autonomía para descubrir después si Diana estaba preparada. Primero necesitábamos poder observar qué haría.

Técnicamente, esto representa: convertir la autonomía en algo medible antes de convertirla en comportamiento.

El modo sombra permite consultar qué habría enviado Diana, dónde habría superado los umbrales, dónde habría sido conservadora y cómo evoluciona la confianza de cada VIP, utilizando las decisiones y evaluaciones reales almacenadas durante los turnos.

La medición sigue siendo completamente observacional: el modo sombra no decide ni envía mensajes.

Para recomendar la activación de un VIP, Diana exige tres condiciones medidas en una ventana de 14 días: confianza ≥ 0,90, coincidencia global ≥ 95 % (aciertos ÷ aciertos + desacuerdos; los casos conservadores no cuentan) y cero escalaciones por seguridad. Los umbrales de evaluación se recalibran cada semana contra los últimos 30 días de turnos corregidos (percentil 70 % en supervisado, 90 % en autónomo, con suavizado para evitar saltos), y Diana avisa a la dueña si su estilo de escritura se desvía más de 0,10 de su histórico.

Verificación: 2806 tests unitarios pasando.

---

PII en la frontera del LLM — 2026-08-22

A medida que aumentábamos el uso de modelos externos, necesitábamos que la privacidad no dependiera de recordar aplicar una regla en cada módulo.

Técnicamente, esto representa: convertir la privacidad en una frontera de infraestructura.

Antes de cada llamada al LLM, Diana enmascara emails, teléfonos, tarjetas, handles y URLs. Los placeholders pueden restaurarse después, por lo que el comportamiento visible y la trazabilidad permanecen intactos.

También documentamos qué debemos exigir a los proveedores de LLM respecto a almacenamiento, entrenamiento, ubicación de datos y seguridad.

Verificación: 2796 tests unitarios pasando.

---

Sandbox, doctrina y documentación — 2026-08-21

Necesitábamos poder probar la evolución de Diana sin convertir a los VIP reales en nuestro entorno de experimentación.

Técnicamente, esto representa: separar el desarrollo del comportamiento real.

El nuevo harness externo permite ejecutar conversaciones multi-turno con perfiles ficticios, manteniendo memoria y datos aislados. También corregimos la resolución de consultas de doctrina y reorganizamos la documentación alrededor de arquitectura, estado y guías de sistema.

---

Entrega y comportamiento conversacional — 2026-08-20

Una respuesta técnicamente correcta todavía puede sentirse artificial si llega como un bloque de texto o con un ritmo extraño.

Técnicamente, esto representa: tratar la entrega como parte del comportamiento conversacional, no como una operación secundaria.

- Las respuestas se dividen naturalmente por párrafos.
- Las entregas largas muestran progreso.
- Los errores tipográficos y autocorrecciones dependen del contexto.
- Corregimos además un bloqueo de arranque relacionado con el backfill de memoria.

---

Saludo cognitivo — 2026-08-16

No tenía sentido ejecutar todo el pipeline para un simple saludo.

Técnicamente, esto representa: permitir rutas cognitivas especializadas cuando el problema es suficientemente simple, sin perder trazabilidad ni las garantías de entrega.

Los saludos claros pueden utilizar una plantilla preparada y, cuando el nivel de confianza lo permite, enviarse automáticamente manteniendo las reglas de seguridad.

---

Control de calidad, Lucien y control administrativo — 2026-08-16

Quería que el criterio de la dueña no desapareciera después de corregir una respuesta y que Diana pudiera aprender de esas correcciones.

Técnicamente, esto representa: convertir el feedback humano y los eventos externos en partes formales del sistema.

Incorporamos destacar/reprender, banco de ejemplos prioritario, eventos de Lucien, contexto temporal, feedback de entrega, manejo de mensajes editados y recuperación tras reinicios. El menú administrativo pasó a ser la superficie principal de control.

---

Panel de personalidad y reglas — 2026-08-04

Antes, la voz de Diana vivía en un archivo de configuración. Cualquier ajuste de tono o de estilo —hablar más corto, cambiar una muletilla, corregir un dato personal— requería editar ese archivo y reiniciar el bot. Quería que la dueña pudiera decidir cómo habla Diana directamente desde el panel, sin depender de un desarrollador y sin perder la posibilidad de volver atrás.

Técnicamente, esto representa: convertir la personalidad de Diana en un catálogo versionado que la dueña edita desde Telegram, con aplicación en caliente y restauración de versiones.

- Nueva sección del menú "🎭 Personalidad y reglas", protegida por el flag `FEATURE_PERSONA_ADMIN_ENABLED`.
- La dueña puede ver y editar cómo habla Diana: la descripción base, las reglas de tono y estilo, los datos personales, los patrones de voz, las políticas de conducta y la agenda (bloques, respuestas libres y zona horaria).
- Cada cambio se guarda como versión nueva en la base de datos y aplica al instante: el siguiente mensaje que procesa el bot ya usa la personalidad editada, sin reiniciar nada.
- El historial muestra las versiones guardadas y permite restaurar cualquiera en un toque; el catálogo de fábrica queda intacto como versión cero.
- La personalidad se administra por canal: VIP y Atención tienen versiones activas independientes.
- Solo la dueña puede editar; una edición mal formada no se guarda y muestra el motivo para corregirla.
- Con la sección apagada, el bot se comporta exactamente como antes: catálogo estático, sin consultas extra a la base.

---

Evolución del agente: modo sombra — 2026-08-07

Antes de hablar de autonomía necesitábamos observar a Diana como agente: cómo interpreta emociones, cómo clasifica turnos, cómo cambia la confianza por VIP y cómo habría decidido frente a una conversación real.

Técnicamente, esto representa: construir una capa de medición antes de construir una capa de acción.

El modo sombra registra señales emocionales, clasificación de turnos, evolución de perfiles, estado de ánimo, confianza y correcciones sin interferir en las conversaciones reales.

La confianza se mide con números fijos, el presupuesto de confianza: cada VIP y categoría de conversación arranca en 0,20, cada acierto suma +0,05 y cada corrección o señal negativa resta −0,20; los casos conservadores y las señales neutrales no cambian el valor. La asimetría es intencional: un solo error de Diana cuesta lo que ganan cuatro aciertos. Además, si las siete puntuaciones de un borrador están muy dispersas (desviación mayor a 0,25), Diana no lo considera confiable para enviar sola.

---

Base conversacional, memoria y supervisión

Las primeras capas de Diana establecieron la arquitectura sobre la que hemos ido construyendo todo lo demás:

- memoria automática;
- perfiles VIP;
- canal de atención;
- congelación y pausa de VIPs;
- sandbox;
- cola de revisión;
- métricas y trazabilidad;
- recontacto;
- recuperación ante reinicios;
- entrega humanizada;
- aislamiento de datos;
- controles de seguridad y acceso.

Técnicamente, esto representa: construir primero una infraestructura conversacional supervisable y después añadir capacidades de aprendizaje y autonomía sobre ella.

La decisión fundamental fue mantener separadas memoria, generación, evaluación, decisión y supervisión humana. Esa separación es la que nos ha permitido seguir incorporando capacidades sin convertir cada cambio en una modificación del sistema completo.

---

La dirección del proyecto

Viendo la evolución completa, las funcionalidades no son piezas independientes.

La memoria existe para que Diana tenga contexto.

Los perfiles existen para que ese contexto pueda evolucionar.

El feedback existe para que las correcciones humanas no se pierdan.

El modo sombra existe para medir si Diana está preparada para actuar sola.

La zona gris existe para que la falta de conocimiento no se convierta en una respuesta inventada.

El sandbox existe para que podamos experimentar sin utilizar clientes reales.

El filtrado de PII y la visión local existen para que añadir capacidades no implique abandonar nuestras garantías de privacidad.

Y la supervisión existe porque, por ahora, la autonomía tiene que ganarse.

Ese es el hilo que conecta todo el desarrollo de Diana.
