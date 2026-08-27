DianaV2
Carlos Ortega
Lead Developer

Construí Diana alrededor de una idea bastante sencilla:

«Una conversación no debería sentirse como una sucesión de mensajes aislados.»

Desde el principio, mi objetivo no fue hacer otro bot de Telegram que recibiera un mensaje y devolviera una respuesta. Quería construir una infraestructura conversacional capaz de mantener contexto, recordar lo importante, adaptarse a cada VIP y, sobre todo, saber cuándo debía intervenir una persona antes de tomar una decisión.

Por eso Diana combina memoria, contexto, comportamiento, aprendizaje y supervisión humana. Cada una de esas piezas existe por una razón: conseguir que la conversación sea más consistente y personal sin convertir la autonomía en una caja negra.

La regla que he intentado mantener durante todo el desarrollo es sencilla: cada nueva capacidad tiene que poder incorporarse sin romper las garantías que ya tenemos.

---

¿Qué hace Diana?

Diana gestiona conversaciones privadas de clientes VIP y acompaña prácticamente todo el ciclo de una conversación.

Cuando llega un mensaje, no quiero que el sistema se limite a contestar. Quiero que primero entienda qué está pasando, determine qué información necesita, construya el contexto adecuado, genere un borrador, lo evalúe y finalmente decida qué acción corresponde.

Por eso hoy Diana cuenta con:

- Conversaciones contextualizadas — utilizamos historial, memoria, perfil y contexto temporal para construir cada respuesta.
- Memoria por VIP — conservamos información relevante sobre preferencias, intereses, límites, contexto personal y otros datos útiles para futuras conversaciones.
- Perfiles evolutivos — sintetizamos tendencias, rasgos estables y sensibilidades a medida que evoluciona una conversación.
- Comportamiento humanizado — la entrega incorpora lectura, escritura, pausas, ritmo y división natural de mensajes.
- Decisiones antes de responder — no quiero que el sistema genere primero y se pregunte después si debía enviar. Primero analizamos el turno y determinamos la acción.
- Supervisión humana — una conversación puede pasar por aprobación, corrección o escalación antes de llegar al VIP.
- Zona gris y reglas propuestas — si Diana no tiene una regla de negocio suficiente para decidir, no quiero que improvise. Congela la conversación y pide criterio a la dueña, pudiendo además proponer una regla como ayuda.
- Sandbox — podemos probar comportamiento con perfiles ficticios sin contaminar los datos reales.
- Métricas y trazabilidad — la dueña puede revisar qué ocurrió durante un turno y cómo está evolucionando el sistema.
- Aprendizaje mediante feedback — una respuesta correcta puede convertirse en ejemplo y una respuesta incorrecta puede transformarse en una lección reutilizable.
- Contexto temporal — podemos introducir acontecimientos que solo deben influir durante una ventana de tiempo determinada.
- Integración con otros bots — Diana puede recibir eventos de otros componentes del ecosistema, como Lucien, y pedir a la dueña que decida qué hacer.
- Visión de imágenes — desde el 26 de agosto de 2026, Diana también puede interpretar determinadas fotos entrantes, siempre pasando primero por nuestro filtro local de privacidad.

---

No quería que Diana tratara a todos los VIPs igual

Uno de los primeros problemas que quise resolver fue el de una conversación basada únicamente en el historial.

El historial dice qué se dijo. No necesariamente dice qué significa ese historial para la conversación actual.

Por eso construí Diana alrededor de varias capas de información. Para cada VIP trabajamos con el historial de conversación, la memoria procesada y un perfil evolutivo. A eso añadimos el contexto temporal y las reglas de negocio que correspondan.

El turno sigue una secuencia deliberadamente separada:

analizar → planificar → recuperar conocimiento → construir contexto → generar → evaluar → decidir.

La separación no es accidental. Para mí es importante que el componente que escribe una respuesta no sea el mismo componente que decide si esa respuesta debería enviarse.

Eso nos permite corregir, medir y supervisar cada parte del proceso de forma independiente.

---

¿Cuánto tarda Diana en pensar?

Quise que la trazabilidad no fuera simplemente un registro de errores. También quería poder ver dónde se está gastando realmente el tiempo.

Cada turno mide sus propias etapas y conserva esos tiempos en la trazabilidad.

Esta es una muestra real de un turno completo del sistema:

Etapa| Qué hace| Tiempo
Analista| Entiende intención, emoción, urgencia y riesgo| ~1,39 s
Planificador| Decide qué conocimiento se necesita| ~0,03 ms
Recuperación de memoria| Busca lo que Diana recuerda de ese VIP| ~145 ms
Recuperación de políticas| Busca reglas aplicables| 0 ms
Recuperación de ejemplos| Busca respuestas de referencia| ~419 ms
Hechos de persona| Busca rasgos de personalidad activa| 0 ms
Patrones de voz| Busca patrones de estilo del canal| 0 ms
Construcción de contexto| Arma el contexto final| ~0,17 ms
Generador| Escribe el borrador| ~3,20 s
Evaluador| Evalúa naturalidad, seguridad, cobertura y empatía| ~1,00 s
Decisor| Determina la acción final| ~0,04 ms
Total| | ~6,16 s

Este tipo de medición nos dejó una conclusión bastante clara: el cuello de botella está en el modelo de lenguaje, principalmente en analizar, generar y evaluar. La recuperación de conocimiento explica prácticamente todo el resto del tiempo.

Las etapas deterministas —planificación, construcción del contexto y decisión— son prácticamente instantáneas.

Y eso es importante porque me permite optimizar donde realmente importa, en lugar de intentar acelerar componentes que ya están tardando menos de un milisegundo.

Los tiempos cambian según el modelo, la conversación y la información recuperada, pero la distribución general se mantiene bastante estable.

---

Supervisión antes que autonomía

Desde el principio tuve claro que Diana debía poder evolucionar hacia una mayor autonomía.

Lo que no quería era un botón de:

"activar autonomía y esperar que todo salga bien".

La autonomía tiene que ganarse.

Por eso construimos una capa de observación en sombra que mide cómo habría actuado Diana mientras la dueña continúa atendiendo las conversaciones reales. El sistema puede comparar la decisión potencial de Diana con la decisión que realmente tomó la dueña, registrar correcciones y construir un historial de confianza.

También medimos señales emocionales, calidad de las respuestas, categorías de conversación, confianza por VIP y por categoría, comportamiento histórico y las distintas dimensiones de evaluación.

Mi principio aquí es conservador y se traduce en números fijos, el presupuesto de confianza:

| Qué ocurre | Efecto en la confianza del VIP |
|---|---|
| Acierto: Diana habría enviado y la dueña aprobó sin cambios | +0,05 |
| Señal positiva del VIP (reacción favorable) | +0,05 |
| Desacuerdo: la dueña corrigió o escaló lo que Diana habría enviado | −0,20 |
| Señal negativa del VIP (reacción desfavorable) | −0,20 |
| Caso conservador (Diana no habría enviado) o señal neutral | 0 (no cambia) |

Cada VIP y categoría de conversación arranca con 0,20 de confianza, y el umbral para que Diana pueda actuar sola es 0,90. La asimetría es deliberada: un error resta cuatro veces más de lo que suma un acierto, es decir, un solo desacuerdo borra el equivalente a cuatro aciertos.

«Las conversaciones sensibles nunca entran en autonomía.»

No quiero que la autonomía sea simplemente una característica técnica. Quiero que sea el resultado de suficiente evidencia.

Por eso cada VIP tiene que demostrar consistencia y seguridad antes de que Diana pueda actuar sola.

Además, cada borrador se evalúa en siete dimensiones: naturalidad, precisión, doctrina, consistencia, seguridad, cobertura y empatía. Los umbrales son más exigentes cuando Diana podría enviar sola: en modo autónomo exige seguridad ≥ 0,9, doctrina ≥ 0,8 y naturalidad ≥ 0,7, mientras que en modo supervisado basta con 0,5, 0,4 y 0,5. Si la seguridad baja de 0,3, Diana nunca envía: siempre escala.

---

La dueña sigue teniendo el control

Una de las decisiones de arquitectura más importantes fue no intentar sustituir el criterio de la persona que administra el sistema.

La dueña sigue teniendo la última palabra en las partes importantes.

Desde el panel administrativo de Telegram puede administrar VIPs, consultar y editar perfiles, revisar memoria, aprobar información sensible, aprobar o corregir respuestas, escalar conversaciones, congelar o pausar VIPs, utilizar el sandbox, consultar métricas, inspeccionar trazabilidad, administrar personalidad y reglas, gestionar eventos temporales, destacar o reprender respuestas y decidir cómo actuar ante eventos externos.

El menú administrativo se convirtió en la superficie principal del producto. Los comandos tradicionales siguen disponibles como atajos.

Esta estructura también nos permite evolucionar el sistema sin convertir cada nueva capacidad en una acción irreversible.

---

Quise poder probar inteligencia artificial sin experimentar con clientes reales

Una de las piezas que considero fundamentales es el Sandbox.

No quería que la única manera de descubrir cómo se comporta una modificación fuera ponerla delante de un VIP real.

El sandbox permite ejecutar conversaciones contra perfiles ficticios y comprobar el comportamiento del pipeline antes de modificar el comportamiento real.

Los perfiles de prueba contemplan escenarios como:

- usuario nuevo;
- VIP cercano;
- VIP reservado;
- VIP emocional;
- VIP con historial extenso;
- contexto adversarial.

Todo permanece aislado de la memoria, el aprendizaje y los datos reales.

«Probar una inteligencia artificial directamente sobre clientes reales es una estrategia de desarrollo que merece, como mínimo, una ceja levantada.»

Para mí, el sandbox no es solamente una herramienta de testing. Es una condición para poder desarrollar Diana con cierta tranquilidad.

---

Feedback de calidad

También necesitaba que el criterio humano no desapareciera después de resolver un turno.

Por eso incorporamos un mecanismo explícito de feedback.

En los borradores VIP, la dueña puede:

- Destacar una respuesta que considera un buen ejemplo y decidir si debe aplicarse a ese VIP o convertirse en conocimiento global.
- Reprender una respuesta, corregirla y enviar inmediatamente la versión corregida. Después puede decidir si esa corrección debe convertirse en una regla o lección para ese VIP o para todo el sistema.

Los ejemplos destacados tienen prioridad durante la recuperación.

Así vamos construyendo un banco de referencias basado en lo que realmente funciona, en lugar de depender únicamente de instrucciones estáticas.

---

Ahora Diana también puede ver imágenes

Esta es la capacidad más reciente que incorporamos.

A partir del 26 de agosto de 2026, Diana puede recibir una foto enviada por un VIP y entender, cuando la imagen es segura para analizar, qué aparece en ella para poder responder en función de ese contenido.

Pero aquí decidí que la visión no podía implementarse simplemente conectando la foto directamente a un modelo externo.

Primero necesitábamos resolver el problema de privacidad.

Por eso construimos un filtro local que funciona antes de que la imagen abandone nuestro servidor.

El flujo es el siguiente.

1. Primero analizamos localmente

Un lector OCR corre en nuestro propio servidor y extrae el texto y los números visibles en la imagen.

En esta etapa la imagen no se envía a ningún proveedor externo.

2. Después decidimos si la imagen puede salir

El filtro busca señales de información sensible, incluyendo:

- tarjetas de crédito o débito;
- facturas y recibos;
- documentos de identidad;
- credenciales y claves de acceso;
- cuentas bancarias.

También contemplamos los casos en los que no podemos estar seguros.

Si la imagen es ilegible o el OCR no está disponible, la tratamos como sensible.

Preferimos bloquear una imagen segura antes que enviar accidentalmente una imagen sensible.

La privacidad gana cuando hay duda.

3. Tenemos dos caminos

Si la imagen es segura, la enviamos al modelo de visión y obtenemos una descripción breve en español.

Esa descripción entra al turno como texto.

Esto fue una decisión deliberada: no quise modificar el núcleo cognitivo de Diana solamente porque ahora pueda recibir imágenes. El resto del pipeline continúa funcionando de la misma manera.

Imagen → descripción → turno de texto → comprensión → generación → evaluación → decisión.

Si la imagen resulta sensible, no la enviamos al proveedor externo.

La conversación pasa directamente a revisión de la dueña y Diana genera un borrador prudente a ciegas. La dueña recibe la foto junto con el borrador y decide qué hacer.

Así mantenemos el mismo modelo de supervisión que ya utilizábamos para los casos delicados.

4. La imagen tampoco se convierte en memoria

Otro límite que decidí mantener es que la imagen no se persiste.

No guardamos los bytes de la foto ni los incorporamos a la memoria, a los ejemplos o al perfil del VIP.

Lo que queda en el turno es texto: la descripción de una imagen segura o la marca de que una imagen no pudo analizarse por privacidad.

La funcionalidad está protegida además por "FEATURE_IMAGE_VISION_ENABLED". Si se desactiva, Diana vuelve al comportamiento anterior.

La implementación actual de visión pasó la suite completa con 3130 tests unitarios.

---

Memoria no significa historial

Otra separación que mantuve deliberadamente es la diferencia entre historial y memoria.

El historial contiene la conversación.

La memoria contiene información procesada que consideramos útil conservar.

Diana puede organizar esa información en categorías como identidad, preferencias, comercial, límites, sensible y perfil.

La memoria está asociada al VIP correspondiente y cuenta con deduplicación, control de sensibilidad y trazabilidad.

Sobre todo, la información sensible pendiente de aprobación no entra en el contexto que utilizamos para responder.

Para mí, recordar más no significa necesariamente recordar mejor. El objetivo es recordar con propósito y con límites.

---

Zona gris: cuando Diana no sabe qué regla aplicar

No quiero que Diana invente una política de negocio cuando ninguna de nuestras reglas cubre un caso.

Cuando detecta que falta una regla, el sistema convierte el caso en una zona gris.

La conversación se congela y la dueña debe decidir qué regla corresponde.

Para ayudar en ese proceso, añadimos la capacidad de generar una regla propuesta.

La propuesta puede incluir una regla de negocio sugerida, una respuesta sugerida y un alcance sugerido. Para construirla utilizamos un contexto general y de solo lectura, como políticas globales, ejemplos destacados y el catálogo de persona.

Ese contexto no se convierte automáticamente en memoria ni modifica el banco de ejemplos.

La dueña puede:

- Usar la regla propuesta.
- Escribir su propia regla.
- Escalar y cerrar el caso sin definir una regla.

Si se acepta una regla, Diana regenera el turno utilizándola y el resultado vuelve al flujo normal de aprobación.

La propuesta nunca se convierte directamente en un mensaje enviado al VIP.

Y si Diana sigue sin poder aplicar correctamente la regla, el caso vuelve a resolución de zona gris. No quiero que una regla fallida termine accidentalmente en un mensaje enviado.

---

Evolución del agente

Además de la memoria, construimos una capa específica de evolución del agente.

Esta capa funciona en modo sombra.

Diana observa cómo habría actuado, pero no interfiere en las conversaciones reales.

Mientras la dueña atiende una conversación, podemos medir en paralelo el análisis, la generación, la evaluación y la decisión potencial de Diana. Después comparamos ese comportamiento con lo que realmente ocurrió.

La capa registra, entre otras cosas:

- señales emocionales;
- categorías de turno;
- tendencias del VIP;
- evolución del perfil;
- estado de ánimo;
- presupuesto de confianza;
- correcciones;
- decisiones potencialmente autónomas.

La intención es acumular evidencia antes de permitir que una nueva capacidad se convierta en comportamiento real.

---

Cómo veo el modo sombra

La dueña puede consultar esta información directamente desde su menú.

Tenemos:

- Resumen — turnos medidos, tendencias y correcciones.
- Confianza por VIP — qué tan cerca está cada VIP del umbral (0,90) necesario para actuar de forma autónoma.
- Borradores y decisiones — para cada turno real, podemos volver a evaluarlo con el criterio de autonomía activado y comparar qué habría hecho Diana con lo que decidió realmente la dueña.

Esto nos permite observar el camino hacia la autonomía sin tener que activarla prematuramente.

---

El camino a la autonomía

La autonomía, tal como la estoy planteando en Diana, es un proceso continuo.

Después de cada turno real podemos comparar:

lo que Diana habría hecho
vs.
lo que realmente hizo la dueña.

A partir de ahí acumulamos evidencia.

Los aciertos y las señales positivas aumentan gradualmente la confianza. Las correcciones y las señales negativas la reducen.

El panel de Camino a la autonomía reúne esa información para mostrar preparación global, comparativas, aciertos, desacuerdos y decisiones conservadoras.

Los criterios para recomendar la activación son tres y se miden en una ventana de 14 días:

1. Confianza del VIP ≥ 0,90.
2. Coincidencia global ≥ 95 %, calculada como aciertos ÷ (aciertos + desacuerdos); los casos conservadores no cuentan.
3. Cero escalaciones por seguridad en la ventana.

Además, cada semana Diana recalibra sus propios umbrales de evaluación con los últimos 30 días de turnos: toma el percentil 70 % en modo supervisado y el 90 % en modo autónomo, y suaviza el cambio contra el umbral anterior para evitar saltos bruscos. También detecta deriva de estilo: si su forma de escribir se desvía más de 0,10 respecto a su histórico, se lo avisa a la dueña.

Cuando un VIP cumple los criterios establecidos, el sistema puede recomendar su activación.

Pero la activación sigue siendo una decisión humana.

Diana nunca se activa sola.

---

Ecosistema Diana

Tampoco diseñé Diana como un componente completamente aislado.

Existe una integración con Lucien, otro componente del ecosistema de Telegram.

Cuando Lucien expulsa a un suscriptor del canal VIP, Diana puede recibir ese evento y comprobar si esa persona también pertenece a su propia base VIP.

Si existe una coincidencia, Diana no ejecuta una acción destructiva automáticamente.

La dueña recibe las opciones correspondientes:

Expulsar · Inhabilitar · Mantener

y decide cómo proceder.

La misma filosofía aparece aquí que en el resto del sistema: los eventos externos pueden desencadenar una decisión, pero no necesariamente una acción irreversible.

---

Cómo ha evolucionado el proyecto

Diana no apareció completa desde el primer día.

La hemos ido construyendo por capas.

Primero establecimos la base conversacional, la memoria, los perfiles, el control administrativo y la trazabilidad.

Después fuimos incorporando sandbox, feedback de calidad, integración con Lucien, eventos temporales, recontacto, zona gris, reglas de negocio y evolución del agente.

Más adelante nos concentramos en medir la autonomía sin activarla, mejorar la privacidad y hacer que el sistema fuera operativamente más robusto.

En agosto de 2026 empezamos a cerrar piezas más profundas de infraestructura: embeddings reales para perfiles, contextos persistidos, personalización de recontacto, control de políticas, historial de versiones, cambio de modelo en caliente y medición de autonomía desde el propio panel.

También reforzamos la frontera de privacidad con el enmascaramiento de PII antes de las llamadas al LLM.

Y el último paso, por ahora, ha sido la visión de imágenes.

No la añadimos como una excepción al sistema. La incorporamos respetando la misma arquitectura que venimos siguiendo: aislar la nueva capacidad, poner límites antes de externalizar datos, mantener la supervisión y evitar contaminar la memoria con información que no necesitamos conservar.

---

Filosofía del proyecto

A medida que el sistema ha crecido, estos son los principios que he intentado mantener como guía de desarrollo:

- Contexto antes que respuesta — una respuesta útil depende de comprender la conversación, no solamente del último mensaje.
- Decisión separada de generación — generar texto y decidir si debe enviarse son problemas diferentes.
- Supervisión antes que autonomía — la autonomía debe ganarse mediante evidencia.
- Memoria con límites — recordar información no significa introducirla indiscriminadamente en cada conversación.
- Feedback como conocimiento — una corrección humana no debería desaparecer después de resolver un único turno.
- Aislamiento — los datos de un VIP no deben contaminar los de otro, y la memoria real nunca debe mezclarse con los escenarios de prueba.
- Privacidad antes que comodidad — cuando no podemos determinar si una información es segura para externalizar, no la externalizamos.
- Evolución observable — una nueva capacidad debe poder medirse antes de convertirse en comportamiento real.
- Fail-closed cuando está en juego la seguridad — ante una duda relevante, prefiero detener el flujo antes que asumir un riesgo.

---

Documentación

Este README explica cómo entiendo el producto y qué hemos construido hasta ahora.

La documentación técnica contiene el detalle de implementación:

Producto y estado

- "docs/ESTADO-PROYECTO.md" — estado actual del sistema y pendientes reales.
- "docs/PRODUCT_OWNER_ADMIN_SANDBOX.md" — reglas del producto y superficie administrativa.
- "CHANGELOG.md" — historial de cambios.

Técnica

- "docs/ARCHITECTURE.md" — arquitectura consolidada: capas, módulos y flujos del sistema.
- "docs/REQUERIMIENTOS.md" — requisitos de producto.
- "docs/SPEC-FASE3.md" — diseño de la Fase 3 (producto completo).
- "AGENTS.md" — límites de módulo y reglas operativas para el desarrollo.
- "wiki/index.md" — conocimiento detallado del sistema: conceptos, contratos, decisiones y operación.
