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

## Supervisión antes que autonomía

Diana está diseñada para evolucionar hacia una mayor autonomía, pero la autonomía no es un interruptor de "enciéndelo y crucemos los dedos".

El sistema puede medir el tipo de conversación, las señales emocionales, la calidad de las respuestas, la confianza por VIP y por categoría de turno, las correcciones de la dueña, el comportamiento histórico y la dispersión entre dimensiones de evaluación. Esta información alimenta un sistema de confianza que determina qué tan preparada está Diana para actuar de forma autónoma.

**El principio es conservador.** Una respuesta autónoma correcta aumenta lentamente la confianza. Una corrección de la dueña la reduce mucho más.

> Las conversaciones sensibles nunca entran en autonomía.

La autonomía completa permanece desactivada hasta que las condiciones del sistema y de operación sean suficientemente seguras.

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

## Memoria ≠ historial

Diana mantiene una separación deliberada entre el historial de conversación y la memoria procesada. La memoria puede organizar información en categorías como identidad, preferencias, comercial, límites, sensible y perfil.

La memoria se mantiene asociada al VIP correspondiente y cuenta con mecanismos de deduplicación, control de sensibilidad y trazabilidad. La información sensible pendiente de aprobación no entra en el contexto utilizado para responder.

---

## Evolución del agente

Además de la memoria, Diana incorpora una capa experimental de evolución del agente que actualmente funciona en **shadow mode**: observa, mide y registra, pero no modifica las decisiones que afectan a las conversaciones reales.

Esta capa estudia señales emocionales, categorías de turno, tendencias del VIP, evolución del perfil, estado de ánimo, presupuesto de confianza, correcciones y comportamiento potencialmente autónomo. El objetivo es construir la información necesaria para que futuras versiones tomen mejores decisiones sin convertir cada nueva capacidad en un experimento sobre usuarios reales.

---

## Ecosistema Diana

Diana no tiene por qué vivir aislada. Existe una integración con Lucien, otro componente del ecosistema de Telegram.

Cuando Lucien expulsa a un suscriptor del canal VIP, Diana puede recibir el evento y comprobar si esa persona también pertenece a su propia base VIP. Si existe una coincidencia, Diana no toma una acción destructiva automáticamente: la dueña recibe las opciones Expulsar, Inhabilitar o Mantener.

| Acción | Efecto |
| --- | --- |
| Expulsar | Saca al VIP de la base activa |
| Inhabilitar | Lo deja fuera de circulación sin borrarlo |
| Mantener | No cambia nada |

La integración está activa en el despliegue actual <!-- VERIFY: estado real del despliegue (Fase 6) — ver docs/ESTADO-PROYECTO.md -->.

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
> DianaV2 es un proyecto en evolución. Algunas capacidades descritas aquí existen en el código pero permanecen deliberadamente desactivadas mediante feature flags mientras se validan en condiciones reales.
>
> La documentación técnica vive en `docs/ARCHITECTURE.md` y `docs/ESTADO-PROYECTO.md`; la wiki (`wiki/`) contiene los contratos y detalles operativos.

---

**DianaV2**  
Conversaciones con contexto. Memoria con propósito. Autonomía con criterio.
