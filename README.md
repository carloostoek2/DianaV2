# DianaV2

Asistente conversacional de Telegram para mantener conversaciones VIP con contexto, memoria y supervisión humana.

Diana es un bot de Telegram construido alrededor de una idea sencilla:

> Una conversación no debería sentirse como una sucesión de mensajes aislados.

Diana mantiene contexto, aprende de las interacciones, adapta su comportamiento a cada VIP y utiliza supervisión humana allí donde una decisión requiere criterio.

No es simplemente un bot que responde mensajes: es una infraestructura conversacional que combina memoria, contexto, comportamiento, aprendizaje y control humano para construir una experiencia más consistente y personal.

---

## ¿Qué hace Diana?

Diana gestiona conversaciones privadas de clientes VIP y acompaña todo el ciclo de una conversación:

- **Conversaciones contextualizadas** — Utiliza historial, memoria, perfil y contexto temporal para construir cada respuesta.
- **Memoria por VIP** — Conserva información relevante sobre preferencias, intereses, límites, contexto personal y otros datos útiles para futuras conversaciones.
- **Perfiles evolutivos** — Sintetiza tendencias, rasgos estables y sensibilidades a partir de la evolución de una conversación.
- **Comportamiento humanizado** — La entrega de mensajes incorpora lectura, escritura, pausas, ritmo y división natural de mensajes.
- **Decisiones antes de responder** — Diana no genera una respuesta y luego decide qué hacer con ella. Primero analiza el turno y determina cuál debería ser la acción.
- **Supervisión humana** — Las conversaciones pueden pasar por aprobación, corrección o escalación de la dueña antes de llegar al VIP.
- **Zona gris y reglas propuestas** — Cuando a Diana le falta una regla de negocio, no adivina: congela la conversación y le pide a la dueña que defina la regla, con la opción de usar una regla sugerida por el sistema.
- **Sandbox** — Permite probar el comportamiento de Diana con perfiles ficticios sin contaminar los datos reales.
- **Métricas y trazabilidad** — La dueña puede revisar cómo se procesó un turno y observar la evolución del sistema.
- **Aprendizaje mediante feedback** — Las respuestas pueden marcarse como buenas o corregirse para construir conocimiento reutilizable.
- **Contexto temporal** — Diana puede recibir eventos que solo deben influir durante una ventana de tiempo determinada.
- **Integración con otros bots** — Diana puede recibir eventos de otros componentes del ecosistema, como Lucien, y solicitar una decisión de la dueña.

---

## Diana no trata a todos los VIPs igual

Uno de los objetivos principales del proyecto es pasar de una conversación basada únicamente en el historial a una conversación basada en contexto acumulado.

Para cada VIP, Diana trabaja con diferentes capas de información: el historial de conversación, la memoria procesada y el perfil evolutivo. El turno se analiza primero, se construye el contexto a partir de esas capas, se genera la respuesta, se evalúa y solo entonces se decide qué hacer con ella. La separación entre estas etapas es deliberada: el componente que genera el texto no es el mismo que decide si ese texto debería enviarse.

---

## ¿Cuánto tarda Diana en pensar?

Cada turno recorre el mismo proceso: Diana **analiza** el mensaje, **planifica** qué conocimiento necesita, **recupera** memoria y ejemplos, **construye el contexto**, **genera** un borrador, lo **evalúa** y, al final, **decide** qué hacer con él. Cada etapa mide su propio tiempo de ejecución y el resultado queda guardado en la trazabilidad del turno.

Esta es una muestra real de un turno completo procesado por el sistema actual:

| Etapa | Qué hace | Tiempo |
| --- | --- | --- |
| Analista | Entiende el mensaje: intención, emoción, urgencia y riesgo | ~1,39 s |
| Planificador | Decide qué conocimiento se necesita | ~0,03 ms |
| Recuperación de memoria | Busca lo que Diana recuerda de ese VIP | ~145 ms |
| Recuperación de políticas | Busca reglas de negocio aplicables | 0 ms |
| Recuperación de ejemplos | Busca respuestas de referencia | ~419 ms |
| Hechos de persona | Busca rasgos de la personalidad activa | 0 ms |
| Patrones de voz | Busca patrones de estilo del canal | 0 ms |
| Construcción de contexto | Arma el contexto final para generar la respuesta | ~0,17 ms |
| Generador | Escribe el borrador de la respuesta | ~3,20 s |
| Evaluador | Evalúa el borrador (naturalidad, seguridad, cobertura, empatía) | ~1,00 s |
| Decisor | Decide la acción: enviar, aprobar, escalar o consultar una regla | ~0,04 ms |
| **Total** | | **~6,16 s** |

Lo que esta muestra revela:

- **Casi todo el tiempo es el modelo de lenguaje** (~91 %): analizar el mensaje, escribir el borrador y evaluarlo son las tres etapas que consultan al modelo; todo lo demás es prácticamente instantáneo.
- **La recuperación de conocimiento es el resto del tiempo**: la búsqueda de memoria y de ejemplos explica casi todo lo que no es el modelo.
- **Las etapas deterministas no se notan**: planificar, construir el contexto y decidir son reglas puras, sin consultas a un modelo; el Decisor decide en menos de un milisegundo.
- **En este turno el borrador no se envió directamente** (`delivery_result: null`): quedó esperando la decisión de la dueña, como corresponde al modo supervisado.

Los tiempos varían de turno a turno (dependen del modelo, del largo de la conversación y del conocimiento recuperado), pero el reparto es estable: el cuello de botella es generar y evaluar el borrador. La dueña puede ver estos números por turno desde la trazabilidad.

---

## Supervisión antes que autonomía

Diana está diseñada para evolucionar hacia una mayor autonomía, pero la autonomía no es un interruptor de "enciéndelo y crucemos los dedos".

El sistema puede medir el tipo de conversación, las señales emocionales, la calidad de las respuestas, la confianza por VIP y por categoría de turno, las correcciones de la dueña, el comportamiento histórico y la dispersión entre dimensiones de evaluación. Esta información alimenta un sistema de confianza que determina qué tan preparada está Diana para actuar de forma autónoma.

**El principio es conservador.** Una respuesta autónoma correcta aumenta lentamente la confianza. Una corrección de la dueña la reduce mucho más.

> Las conversaciones sensibles nunca entran en autonomía.

La autonomía se habilita de forma gradual y conservadora: cada VIP debe demostrar que cumple condiciones seguras de confianza y consistencia antes de que Diana pueda actuar sola, y las conversaciones sensibles quedan siempre fuera de ese camino.

---

## La dueña sigue teniendo el control

Diana no pretende sustituir el criterio de la persona que administra el sistema. La dueña dispone de un panel administrativo dentro de Telegram para controlar las partes importantes de la experiencia.

Desde allí puede administrar VIPs, consultar y editar perfiles, revisar memoria, aprobar información sensible, aprobar o corregir respuestas, escalar conversaciones, congelar o pausar VIPs, usar el sandbox, consultar métricas e inspeccionar trazabilidad, administrar personalidad y reglas, gestionar eventos temporales, destacar o reprender respuestas y decidir cómo actuar ante eventos externos.

El menú administrativo es la superficie principal del producto. Los comandos tradicionales permanecen como atajos para operaciones específicas.

---

## Un sistema que puede aprender sin tocar producción

Una de las piezas importantes de Diana es el **Sandbox**: permite ejecutar conversaciones contra perfiles ficticios y comprobar el comportamiento del pipeline antes de modificar el comportamiento real.

Los perfiles de prueba incluyen escenarios como usuario nuevo, VIP cercano, VIP reservado, VIP emocional, VIP con historial extenso y contexto adversarial. El sandbox mantiene estos escenarios aislados de la memoria, el aprendizaje y los datos reales.

> Probar una inteligencia artificial directamente sobre clientes reales es una estrategia de desarrollo que merece, como mínimo, una ceja levantada.

---

## Feedback de calidad

Diana incorpora un mecanismo explícito para convertir el criterio humano en conocimiento reutilizable. En los borradores VIP, la dueña puede:

- **Destacar** — Marcar una respuesta como un buen ejemplo y decidir si debe aplicarse únicamente a ese VIP o convertirse en conocimiento global.
- **Reprender** — Corregir una respuesta y entregar inmediatamente la versión corregida al VIP. Después puede decidir si la lección debe aplicarse únicamente a ese VIP o a todo el sistema.

Los ejemplos destacados tienen prioridad en la recuperación de ejemplos. Esto permite construir progresivamente un banco de respuestas de referencia basado en lo que realmente funciona, en lugar de depender únicamente de instrucciones estáticas.

---

## Visión de imágenes con filtro de privacidad

Diana puede **ver las fotos que le envían los VIP**: entiende de qué trata la imagen y responde con base en eso. Pero antes de que cualquier imagen salga del servidor, un **filtro local de privacidad** decide si es seguro analizarla.

El flujo es:

1. **Lectura local** — Un lector de texto (OCR) corre en el propio servidor y extrae los textos y números visibles en la imagen. En esta etapa la imagen **no sale a ningún lado**.
2. **Revisión de sensibilidad** — Si la imagen contiene información sensible (tarjetas de crédito/débito, facturas y recibos, documentos de identidad, claves y accesos), la foto **nunca se envía a un proveedor externo**. Ante la duda (imagen ilegible, lector no disponible), también se trata como sensible: la privacidad siempre gana.
3. **Dos caminos**:
   - **Imagen segura** → se envía a un modelo de visión (Gemini) que la describe en una frase corta, y Diana responde sabiendo qué contiene. La descripción entra al turno como texto; el resto del flujo (comprensión, decisión, aprobación) no cambia.
   - **Imagen sensible** → la foto va directamente a la **revisión de la dueña**, marcada como "no analizada por privacidad", acompañada de un borrador prudente a ciegas de Diana. La dueña aprueba, corrige o descarta como siempre.
4. **La foto llega al DM de la dueña** — En cualquier aprobación originada en una foto, la imagen se adjunta junto al borrador para que la dueña juzgue con sus propios ojos.

La imagen en sí **nunca se guarda** (ni en base de datos ni en disco): solo queda texto. La descripción es parte efímera del turno y no alimenta la memoria ni los ejemplos de Diana. Toda la característica funciona detrás de un interruptor (`FEATURE_IMAGE_VISION_ENABLED`): apagada, Diana se comporta exactamente como antes.

---

## Memoria ≠ historial

Diana mantiene una separación deliberada entre el historial de conversación y la memoria procesada. La memoria puede organizar información en categorías como identidad, preferencias, comercial, límites, sensible y perfil.

La memoria se mantiene asociada al VIP correspondiente y cuenta con mecanismos de deduplicación, control de sensibilidad y trazabilidad. La información sensible pendiente de aprobación no entra en el contexto utilizado para responder.

---

## Zona gris: cuando Diana no sabe qué regla aplicar

Hay casos que ninguna regla escrita cubre todavía: Diana reconoce que le falta una regla de negocio para responder con criterio. En lugar de adivinar, lo convierte en una **zona gris**: congela la conversación y le pide a la dueña que defina la regla.

Para facilitar esa decisión, el sistema puede **proponer una regla** (una regla de negocio sugerida y una respuesta sugerida) construida a partir del conocimiento general de referencia — políticas globales, ejemplos destacados y el catálogo de persona — como una sugerencia temporal, sin tocar la memoria del VIP ni el banco de ejemplos. Si la generación falla o tarda demasiado, se sigue sin propuesta y la consulta no se pierde.

La dueña puede:

- **Usar la regla propuesta** — adoptarla como regla (nunca como mensaje directo) y seguir el flujo normal.
- **Escribir su propia regla**.
- **Escalar** — cerrar el caso sin definir regla.

Cuando la dueña define una regla, Diana **regenera el turno con esa regla** y el resultado vuelve a la cola de aprobación; la dueña sigue teniendo la última palabra antes de que llegue al VIP. La propuesta del sistema es solo una sugerencia: nunca se aplica sola, y si Diana no logra aplicar la regla correctamente, el caso permanece en resolución de zona gris en lugar de enviar algo a ciegas.

---

## Evolución del agente

Además de la memoria, Diana incorpora una capa de **evolución del agente** que funciona en **modo sombra**: observa, mide y registra cómo decidiría, sin modificar las decisiones que afectan a las conversaciones reales. Todo lo que produce es medición y recomendación, no acción automática.

Esta capa estudia señales emocionales, categorías de turno, tendencias del VIP, evolución del perfil, estado de ánimo, presupuesto de confianza, correcciones y el comportamiento potencialmente autónomo. El objetivo es construir la información necesaria para que futuras versiones tomen mejores decisiones, sin convertir cada nueva capacidad en un experimento sobre usuarios reales.

### Ver el modo sombra

La dueña puede consultar el modo sombra desde su menú:

- **Resumen** — cuántos turnos se han medido, la tendencia y las correcciones de la dueña.
- **Confianza por VIP** — qué tan cerca está cada VIP de cumplir el umbral de confianza para poder actuar sola.
- **Borradores y decisiones** — para cada turno real, Diana re-evalúa con el criterio de autonomía encendido y muestra qué habría hecho ella frente a lo que decidió la dueña, junto con el borrador real generado.

### Camino a la autonomía

Sobre esa medición, Diana **aprende**: después de cada turno real, compara lo que ella habría hecho con lo que la dueña hizo de verdad y evalúa si su decisión habría sido la correcta. Es un círculo continuo — la confianza por VIP crece con los aciertos y las señales positivas del VIP, y baja con las correcciones o las señales negativas.

El panel **Camino a la autonomía** reúne esa información: la preparación global, las comparativas (aciertos, desacuerdos, decisiones conservadoras) y quién está listo o a quién le falta qué. Cuando un VIP cumple los criterios de preparación, el panel lo **recomienda** y ofrece la opción de activarlo — pero la activación es siempre una decisión de la dueña. Diana nunca se activa por su cuenta.

---

## Ecosistema Diana

Diana no tiene por qué vivir aislada. Existe una integración con Lucien, otro componente del ecosistema de Telegram.

Cuando Lucien expulsa a un suscriptor del canal VIP, Diana puede recibir el evento y comprobar si esa persona también pertenece a su propia base VIP. Si existe una coincidencia, Diana no toma una acción destructiva automáticamente: la dueña recibe las opciones Expulsar, Inhabilitar o Mantener, y decide cómo proceder.

---

## Documentación

Este README explica qué es Diana. La documentación técnica explica cómo está construida.

### Producto y estado

- [docs/ESTADO-PROYECTO.md](docs/ESTADO-PROYECTO.md) — estado actual del sistema y pendientes reales
- [docs/PRODUCT_OWNER_ADMIN_SANDBOX.md](docs/PRODUCT_OWNER_ADMIN_SANDBOX.md) — reglas del producto y superficie administrativa
- [CHANGELOG.md](CHANGELOG.md) — historial de cambios

### Técnica

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — arquitectura consolidada: capas, módulos, flujos canónicos, feature flags, modelo de datos, stack y ADRs
- [docs/README-DEV.md](docs/README-DEV.md) — guía de desarrollo técnico: setup, configuración, flags, arranque long-polling, migraciones y tests
- [AGENTS.md](AGENTS.md) — contrato de implementación: límites de módulo y flujos canónicos
- [docs/REQUERIMIENTOS.md](docs/REQUERIMIENTOS.md) — requisitos de negocio y de sistema (qué debe cumplir)
- [docs/UX.md](docs/UX.md) — UX del panel de la dueña en Telegram
- [docs/INFORME_AUDITORIA.md](docs/INFORME_AUDITORIA.md) — auditoría de alineamiento código ↔ requerimientos

### Specs de diseño

- [docs/SPEC-1.1.md](docs/SPEC-1.1.md) — diseño técnico base
- [docs/SPEC-FASE2.md](docs/SPEC-FASE2.md) — memoria, zona gris, staging y sandbox
- [docs/SPEC-FASE3.md](docs/SPEC-FASE3.md) — autonomía, recontacto, promo y calibración
- [docs/SPEC-FASE4.md](docs/SPEC-FASE4.md) — atención general
- [docs/SPEC-FASE5.md](docs/SPEC-FASE5.md) — memoria VIP
- [docs/SPEC-FASE6.md](docs/SPEC-FASE6.md) — integración Lucien → Diana
- [docs/SPEC-FEEDBACK.md](docs/SPEC-FEEDBACK.md) — feedback de calidad
- [docs/SPEC-EVOLUCION-AGENTE.md](docs/SPEC-EVOLUCION-AGENTE.md) — evolución del agente

### Wiki

La wiki contiene el conocimiento detallado del sistema: conceptos, módulos, contratos, tablas, decisiones de producto, reglas de seguridad, evolución del agente y operaciones. Comienza en el [índice](wiki/index.md).

---

## Filosofía del proyecto

Diana está construida alrededor de algunos principios simples:

- **Contexto antes que respuesta** — Una respuesta útil depende de comprender la conversación, no únicamente del último mensaje.
- **Decisión separada de generación** — Generar texto y decidir si debe enviarse son problemas diferentes.
- **Supervisión antes que autonomía** — La autonomía debe ganarse mediante evidencia, no asumirse por defecto.
- **Memoria con límites** — Recordar información no significa introducirla indiscriminadamente en cada conversación.
- **Feedback como conocimiento** — Las correcciones humanas no deberían desaparecer después de resolver un único turno.
- **Aislamiento** — Los datos de un VIP no deben contaminar los de otro, ni la memoria real debe mezclarse con los escenarios de prueba.
- **Evolución observable** — Las nuevas capacidades deben poder medirse antes de convertirse en comportamiento real.

---

> [!NOTE]
> DianaV2 es un proyecto en evolución. Las capacidades de mayor impacto se protegen mediante interruptores de configuración (feature flags): así pueden validarse en condiciones reales antes de volverse comportamiento habitual, y pueden desactivarse si no demuestran ser seguras.
>
> La documentación técnica vive en `docs/ARCHITECTURE.md` y `docs/ESTADO-PROYECTO.md`; la wiki (`wiki/`) contiene los contratos y detalles operativos.

---

**DianaV2**  
Conversaciones con contexto. Memoria con propósito. Autonomía con criterio.
