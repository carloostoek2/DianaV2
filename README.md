# DianaV2

Una asistente conversacional diseñada para mantener conversaciones VIP con contexto, memoria y supervisión humana.

Diana es un bot de Telegram construido alrededor de una idea sencilla:

> Una conversación no debería sentirse como una sucesión de mensajes aislados.

Diana mantiene contexto, aprende de las interacciones, adapta su comportamiento a cada VIP y utiliza supervisión humana allí donde una decisión requiere criterio.

No es simplemente un bot que responde mensajes.

Es una infraestructura conversacional que combina memoria, contexto, comportamiento, aprendizaje y control humano para construir una experiencia más consistente y personal.

---

## ¿Qué hace Diana?

Diana gestiona conversaciones privadas de clientes VIP y puede acompañar todo el ciclo de una conversación:

- **Conversaciones contextualizadas** — Utiliza historial, memoria, perfil y contexto temporal para construir cada respuesta.
- **Memoria por VIP** — Conserva información relevante sobre preferencias, intereses, límites, contexto personal y otros datos útiles para futuras conversaciones.
- **Perfiles evolutivos** — El sistema puede sintetizar tendencias, rasgos estables y sensibilidades a partir de la evolución de una conversación.
- **Comportamiento humanizado** — La entrega de mensajes incorpora lectura, escritura, pausas, ritmo y división natural de mensajes.
- **Decisiones antes de responder** — Diana no genera una respuesta y luego decide qué hacer con ella. Primero analiza el turno y determina cuál debería ser la acción.
- **Supervisión humana** — Las conversaciones pueden pasar por aprobación, corrección o escalación de la dueña antes de llegar al VIP.
- **Sandbox** — Permite probar el comportamiento de Diana con perfiles ficticios sin contaminar los datos reales.
- **Métricas y trazabilidad** — La dueña puede revisar cómo se procesó un turno y observar la evolución del sistema.
- **Aprendizaje mediante feedback** — Las respuestas pueden marcarse como buenas o corregirse para construir conocimiento reutilizable.
- **Contexto temporal** — Diana puede recibir eventos que solo deben influir durante una ventana de tiempo determinada.
- **Integración con otros bots** — Diana puede recibir eventos procedentes de otros componentes del ecosistema, como Lucien, y solicitar una decisión de la dueña.

---

## Diana no trata a todos los VIPs igual

Uno de los objetivos principales del proyecto es pasar de una conversación basada únicamente en el historial a una conversación basada en contexto acumulado.

Para cada VIP, Diana puede trabajar con diferentes capas de información:

```mermaid
flowchart TD
    A[Mensaje] --> B[Análisis del turno]
    B --> C[Historial]
    B --> D[Memoria]
    B --> E[Perfil]
    C --> F[Contexto]
    D --> F
    E --> F
    F --> G[Generación]
    G --> H[Evaluación]
    H --> I[Decisión]
    I --> J[Entrega]
```

La separación entre estas etapas es deliberada.

El componente que genera el texto no es el mismo que decide si ese texto debería enviarse.

---

## Supervisión antes que autonomía

Diana está diseñada para evolucionar hacia una mayor autonomía, pero la autonomía no es un interruptor de "enciéndelo y crucemos los dedos".

Actualmente el sistema puede medir:

- tipo de conversación
- señales emocionales
- calidad de las respuestas
- confianza por VIP
- confianza por categoría de turno
- correcciones realizadas por la dueña
- comportamiento histórico
- dispersión entre dimensiones de evaluación

Esta información alimenta un sistema de confianza que permite determinar qué tan preparada está Diana para actuar de forma autónoma.

**El principio es conservador.**

Una respuesta autónoma correcta aumenta lentamente la confianza.

Una corrección de la dueña la reduce mucho más.

Además:

> Las conversaciones sensibles nunca entran en autonomía.

La autonomía completa permanece desactivada hasta que las condiciones del sistema y de operación sean suficientemente seguras.

---

## La dueña sigue teniendo el control

Diana no pretende sustituir el criterio de la persona que administra el sistema.

La dueña dispone de un panel administrativo dentro de Telegram para controlar las partes importantes de la experiencia.

Desde allí puede:

- administrar VIPs
- consultar y editar perfiles
- revisar memoria
- aprobar información sensible
- aprobar o corregir respuestas
- escalar conversaciones
- congelar o pausar VIPs
- utilizar el sandbox
- consultar métricas
- inspeccionar trazabilidad
- administrar personalidad y reglas
- gestionar eventos temporales
- destacar respuestas de alta calidad
- reprender respuestas incorrectas
- decidir cómo actuar ante eventos externos

El menú administrativo es la superficie principal del producto. Los comandos tradicionales permanecen como atajos para operaciones específicas.

---

## Un sistema que puede aprender sin tocar producción

Una de las piezas importantes de Diana es el **Sandbox**.

Permite ejecutar conversaciones contra perfiles ficticios y comprobar el comportamiento del pipeline antes de modificar el comportamiento real.

Los perfiles de prueba incluyen escenarios como:

- usuario nuevo
- VIP cercano
- VIP reservado
- VIP emocional
- VIP con historial extenso
- contexto adversarial

El sandbox mantiene estos escenarios aislados de la memoria, aprendizaje y datos reales.

> Probar una inteligencia artificial directamente sobre clientes reales es una estrategia de desarrollo que merece, como mínimo, una ceja levantada.

---

## Feedback de calidad

Diana incorpora un mecanismo explícito para convertir el criterio humano en conocimiento reutilizable.

En los borradores VIP, la dueña puede:

### Destacar

Marcar una respuesta como un buen ejemplo y decidir si debe aplicarse únicamente a ese VIP o convertirse en conocimiento global.

### Reprender

Corregir una respuesta y entregar inmediatamente la versión corregida al VIP. Después puede decidir si la lección debe aplicarse únicamente a ese VIP o a todo el sistema.

Los ejemplos destacados tienen prioridad en la recuperación de ejemplos.

Esto permite construir progresivamente un banco de respuestas de referencia basado en lo que realmente funciona, en lugar de depender únicamente de instrucciones estáticas.

---

## Memoria ≠ historial

Diana mantiene una separación deliberada entre el historial de conversación y la memoria procesada.

La memoria puede organizar información en categorías como:

| Categoría | Ejemplos |
| --- | --- |
| Identidad | Datos personales relevantes |
| Preferencias | Temas, tono y gustos |
| Comercial | Intereses y compras |
| Límites | Temas que deben evitarse |
| Sensible | Información que requiere aprobación |
| Perfil | Síntesis general del VIP |

La memoria se mantiene asociada al VIP correspondiente y cuenta con mecanismos de deduplicación, control de sensibilidad y trazabilidad.

La información sensible pendiente de aprobación no entra en el contexto utilizado para responder.

---

## Evolución del agente

Además de la memoria, Diana incorpora una capa experimental de evolución del agente.

Actualmente funciona en **shadow mode**:

> Observa, mide y registra, pero no modifica las decisiones que afectan a las conversaciones reales.

Esta capa estudia:

- señales emocionales
- categorías de turno
- tendencias del VIP
- evolución del perfil
- estado de ánimo
- presupuesto de confianza
- correcciones
- comportamiento potencialmente autónomo

El objetivo es construir la información necesaria para que futuras versiones puedan tomar mejores decisiones sin convertir cada nueva capacidad en un experimento sobre usuarios reales.

---

## Ecosistema Diana

Diana no tiene por qué vivir aislada.

Existe una integración con Lucien, otro componente del ecosistema de Telegram.

Cuando Lucien expulsa a un suscriptor del canal VIP, Diana puede recibir el evento y comprobar si esa persona también pertenece a su propia base VIP.

Si existe una coincidencia, Diana no toma una acción destructiva automáticamente.

La dueña recibe:

| Acción | Efecto |
| --- | --- |
| Expulsar | Saca al VIP de la base activa |
| Inhabilitar | Lo deja fuera de circulación sin borrarlo |
| Mantener | No cambia nada |

La integración permanece desactivada hasta que se complete la validación de despliegue correspondiente.

---

## Arquitectura

Diana está organizada alrededor de varias capas con responsabilidades separadas:

```mermaid
flowchart TD
    TG[Telegram] --> TL[Telegram Layer]
    TL --> AS[Application Services<br/>orchestration]
    AS --> CC[Cognitive Core]
    CC --> AN[analysis → context]
    AN --> GE[generation → eval]
    GE --> DE[decision]
    CC --> PE[Persistence]
    CC --> LLM[LLM Provider]
    PE --> LM[Learning / Memory]
    AS --> BE[Behavior Engine<br/>read / typing / send]
```

La arquitectura mantiene una separación estricta entre:

**pensar → decidir → actuar → aprender**

Esto permite evolucionar cada parte sin convertir todo el sistema en una única caja negra.

---

## Estado actual

DianaV2 se encuentra en desarrollo activo.

Actualmente están implementadas las principales capacidades de:

| Área | Estado |
| --- | --- |
| Conversación VIP supervisada | Listo |
| Atención general | Listo |
| Memoria VIP | Listo |
| Perfiles evolutivos | Listo — shadow |
| Detección emocional | Listo — shadow |
| Mood engine | Listo — shadow |
| Trust budget | Listo — shadow |
| Sandbox | Listo |
| Staging / revisión humana | Listo |
| Métricas y trazabilidad | Listo |
| Feedback de calidad | Listo |
| Eventos temporales | Listo |
| Integración Lucien → Diana | Listo |
| Autonomía conversacional | En evolución |
| Autoenvío autónomo | No habilitado |

> El estado del código no implica que todas las funcionalidades estén activadas en producción.

Las capacidades experimentales y de alto impacto están protegidas mediante feature flags y pueden activarse progresivamente.

---

## Roadmap

La evolución de Diana se plantea en capas:

### Completado

- [x] Pipeline cognitivo
- [x] Conversación VIP supervisada
- [x] Atención general
- [x] Memoria VIP
- [x] Perfiles evolutivos
- [x] Shadow agent evolution
- [x] Sandbox
- [x] Recontacto y proactividad
- [x] Métricas y calibración
- [x] Feedback de calidad
- [x] Eventos temporales
- [x] Integración Lucien → Diana
- [x] Panel administrativo unificado

### En evolución

- [ ] Autonomía fática real
- [ ] Doble puerta de confianza para autoenvío
- [ ] Cola durable para síntesis de perfiles
- [ ] Historial completo de evolución del perfil
- [ ] Nuevas fases de iniciativa contextual

La siguiente etapa no consiste simplemente en "hacer que Diana responda sola".

Consiste en determinar cuándo debería hacerlo, cuándo no debería hacerlo y cómo demostrar que tomó la decisión correcta.

---

## Stack

- Python 3.12+
- aiogram 3
- PostgreSQL 16+
- SQLAlchemy
- Alembic
- pgvector
- Pydantic
- DeepSeek
- sentence-transformers
- pytest
- Telegram Business API

La aplicación se distribuye como paquete Python bajo `src/diana`.

---

## Desarrollo local

### Requisitos

- Python 3.12+
- PostgreSQL 16+
- Token de un bot de Telegram
- ID de la dueña
- Credenciales del proveedor LLM

### Instalación

```bash
python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"

cp .env.example .env
```

Configura las variables necesarias en `.env`:

```bash
TELEGRAM_BOT_TOKEN=...
OWNER_TELEGRAM_ID=...
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/diana
DEEPSEEK_API_KEY=...
```

### Base de datos

```bash
alembic upgrade head
```

### Ejecutar

```bash
python -m diana.main
```

Por defecto, Diana opera en modo supervisado.

---

## Tests

La suite unitaria puede ejecutarse sin una instancia real de PostgreSQL:

```bash
.venv/bin/pytest tests/unit -q
```

Las pruebas utilizan dobles de LLM y Telegram para evitar llamadas reales durante los tests.

Las capas cognitivas y de comportamiento también cuentan con pruebas de pureza para impedir que las responsabilidades se mezclen.

---

## Documentación

El README explica qué es Diana.

La documentación técnica explica cómo está construida.

### Producto y estado

- [docs/ESTADO-PROYECTO.md](docs/ESTADO-PROYECTO.md) — estado actual del sistema
- [docs/PRODUCT_OWNER_ADMIN_SANDBOX.md](docs/PRODUCT_OWNER_ADMIN_SANDBOX.md) — reglas del producto y superficie administrativa
- [CHANGELOG.md](CHANGELOG.md) — historial de cambios
- [docs/README-DEV.md](docs/README-DEV.md) — flags, arranque técnico y operación

### Arquitectura

- [docs/SPEC-1.1.md](docs/SPEC-1.1.md) — diseño técnico base
- [docs/SPEC-FASE4.md](docs/SPEC-FASE4.md) — atención general
- [docs/SPEC-FASE5.md](docs/SPEC-FASE5.md) — memoria VIP
- [docs/SPEC-FASE6.md](docs/SPEC-FASE6.md) — integración Lucien → Diana
- [docs/SPEC-FEEDBACK.md](docs/SPEC-FEEDBACK.md) — feedback de calidad
- [docs/SPEC-EVOLUCION-AGENTE.md](docs/SPEC-EVOLUCION-AGENTE.md) — evolución del agente

### Wiki

La wiki contiene el conocimiento detallado del sistema:

- [índice](wiki/index.md)
- conceptos
- módulos
- contratos
- tablas
- decisiones de producto
- reglas de seguridad
- evolución del agente
- operaciones

---

## Filosofía del proyecto

Diana está construida alrededor de algunos principios simples:

### Contexto antes que respuesta

Una respuesta útil depende de comprender la conversación, no únicamente del último mensaje.

### Decisión separada de generación

Generar texto y decidir si debe enviarse son problemas diferentes.

### Supervisión antes que autonomía

La autonomía debe ganarse mediante evidencia, no asumirse por defecto.

### Memoria con límites

Recordar información no significa introducirla indiscriminadamente en cada conversación.

### Feedback como conocimiento

Las correcciones humanas no deberían desaparecer después de resolver un único turno.

### Aislamiento

Los datos de un VIP no deben contaminar los de otro, ni la memoria real debe mezclarse con los escenarios de prueba.

### Evolución observable

Las nuevas capacidades deben poder medirse antes de convertirse en comportamiento real.

---

> [!NOTE]
> DianaV2 es un proyecto en evolución. Algunas capacidades descritas aquí existen en el código pero permanecen deliberadamente desactivadas mediante feature flags mientras se validan en condiciones reales.
>
> La documentación de `docs/` y `wiki/` contiene los contratos técnicos y operativos de mayor detalle.

---

**DianaV2**  
Conversaciones con contexto. Memoria con propósito. Autonomía con criterio.
