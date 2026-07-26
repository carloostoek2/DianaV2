# Plan: Persona Facts + Voice Patterns + Refinamiento de Escalación

## Context

`diana_system_prompt.md` v1.1 se estructuró en el Anexo J (persona/voz siempre-presente, banco de ejemplos de voz, hechos biográficos, reglas duras/blandas). Este plan lleva eso al código real de `DianaV2-main`, respetando lo que ya existe:

- `knowledge.examples` **ya está tomado** (ejemplos aprendidos de corrección vía Staging/pgvector, F2). El catálogo de muletillas de voz (Anexo J.2) se registra como **`knowledge.voice_patterns`**, capacidad nueva e independiente.
- `knowledge.persona_facts` es enteramente nueva (Anexo J.3).
- Confirmado: con 9 hechos + 11 patrones de voz, **no se usa embedding/pgvector** — match por `tema`/`tags` contra `comprehension.topics`/`intent`. Reutiliza el patrón de `ContextRetriever`/`HistoryRetriever` (sin dependencia de `embedding_service`), no el de `ExamplesRetriever`/`MemoryRetriever`/`PolicyRetriever`.
- Dos reglas de escalación nuevas, con mecanismos distintos porque una es stateless y otra no:
  - **Frustración directa** (`emotion == "molesta"`) → puede vivir en el `Decider`, que ya recibe `Comprehension` y no necesita I/O.
  - **Pregunta repetida 3 veces** → el `Decider` es deliberadamente puro/sin I/O (Anexo F.4); esta regla necesita leer turnos anteriores del mismo chat, así que va en el `CognitiveDirector` como un chequeo determinista *después* del Analista y *antes* del Planificador — si dispara, se salta Planificador/Retrievers/Generador/Evaluador por completo (ahorro de costo, no solo de complejidad).

## Arquitectura de cambios

```
NUEVOS archivos:
  cognitive/retrievers/persona_facts.py   → PersonaFactsRetriever (match por tema, sin embeddings)
  cognitive/retrievers/voice_patterns.py  → VoicePatternsRetriever (match por tags, devuelve máx. 1)
  cognitive/repetition_guard.py           → RepetitionGuard (puro: intents[] + intent_actual -> bool)
  config/persona_diana.yaml               → catálogo estático (9 persona_facts + 11 voice_patterns)
  alembic/versions/00X_recent_intents_idx.py → índice para lectura eficiente de intents recientes

MODIFICADOS:
  cognitive/models.py           → Comprehension: + needs_persona_facts, + needs_voice_patterns
  cognitive/analyst.py          → prompt/schema: 2 campos needs_* nuevos + pistas de uso
  cognitive/planner.py          → 2 entradas nuevas en _NEED_TO_CAPABILITY
  cognitive/registry.py         → registrar ambos retrievers + PLANNER_CAPABILITY_UNIVERSE
  cognitive/context_builder.py  → 2 entradas nuevas en _KNOWLEDGE_EMISSION_ORDER
  cognitive/decider.py          → nueva regla determinista: emotion == "molesta" -> escalate
  cognitive/director.py         → chequeo de repetición justo después del Analista (pre-Planner)
  infrastructure/db/repositories/traces.py → get_recent_intents(chat_id, limit=3)
  cognitive/ports.py            → RecentIntentsPort Protocol
  composition.py                → cargar config/persona_diana.yaml, wiring de retrievers + guard

NO se modifica:
  - Evaluator, Generator (no tocan estas capacidades directamente)
  - TurnCoordinator (la repetición se resuelve en el Director, no en el Coordinator)
  - ExamplesRetriever / knowledge.examples existente (sigue siendo el pool de correcciones aprendidas)
```

## Modelo de datos: catálogo estático (sin tabla nueva)

Los 9 hechos + 11 patrones son configuración de despliegue, no datos por-VIP ni aprendidos — no necesitan tabla ni migración de esquema, a diferencia de `memories`/`policies`/`examples` (que sí son dinámicos). Se cargan una vez al arrancar desde `config/persona_diana.yaml`, igual que la `persona`/`reglas_estilo` ya se pasan hoy como strings a `ContextBuilder.build()`.

```yaml
# config/persona_diana.yaml (estructura; contenido = Anexo J.2 / J.3 ya redactado)
persona_facts:
  - id: familia_hermana
    tema: [familia]
    hecho: "..."
  # ... 8 más

voice_patterns:
  - id: risa_jsjs
    tags: [risa, humor, casual]
    patron: "jsjs / jshshs"
    uso: "..."
  # ... 10 más
```

Si en el futuro esto crece mucho (decenas/cientos de hechos) o quieres que la dueña los edite desde Telegram sin redeploy, ese es el momento de moverlo a tabla + comando de admin — no antes; es la misma lógica de "no sobre-construir" que ya aplicamos a la decisión de no usar vectores.

## Plan de implementación (6 hitos)

### H0: Modelo + config

- Añadir `needs_persona_facts: bool` y `needs_voice_patterns: bool` a `Comprehension` (`cognitive/models.py`). **Nota de compatibilidad:** esto es un cambio de schema (Anexo A.7) — las filas históricas de `pipeline_traces.comprehension` no tendrán estas claves. Verificar que nada re-valida JSON histórico contra el modelo Pydantic estricto (solo se muestra como blob en `AdminTraceService`/`/traza`) antes de desplegar.
- Crear `config/persona_diana.yaml` con el contenido ya redactado en el Anexo J (J.2 y J.3), incluyendo el hecho de vivienda ya resuelto.
- Loader simple en `composition.py` (YAML → dict en memoria, sin nueva dependencia si ya usan `pyyaml`; si no, `tomllib`/JSON son alternativas igual de válidas).

### H1: Retrievers nuevos (sin embeddings)

**`cognitive/retrievers/persona_facts.py`** — mismo patrón de firma que `HistoryRetriever`/`ContextRetriever` (Anexo H.2: `fetch(turn, comprehension) -> resultado | None`):
```python
class PersonaFactsRetriever:
    def __init__(self, facts: list[dict]) -> None:
        self._facts = facts

    async def fetch(self, turn, comprehension) -> dict | None:
        topics = set(comprehension.topics) | {comprehension.intent}
        for fact in self._facts:
            temas = fact["tema"] if isinstance(fact["tema"], list) else [fact["tema"]]
            if topics & set(temas):
                return {"hecho": fact["hecho"], "tema": temas[0]}
        return None  # needs_persona_facts=true pero ningún tema matchea (Anexo J.3.2)
```

**`cognitive/retrievers/voice_patterns.py`** — misma idea, pero limita a **un solo** patrón (refuerza "máx. una expresión por mensaje" a nivel de datos, no de instrucción al LLM):
```python
class VoicePatternsRetriever:
    def __init__(self, patterns: list[dict]) -> None:
        self._patterns = patterns

    async def fetch(self, turn, comprehension) -> dict | None:
        signals = {comprehension.emotion, comprehension.intent, *comprehension.topics}
        for p in self._patterns:
            if signals & set(p["tags"]):
                return {"patron": p["patron"], "uso": p["uso"]}  # solo el primero que matchea
        return None
```
Match determinista por intersección de sets — sin embeddings, sin librería nueva, O(n) sobre 9-11 registros (irrelevante en costo).

### H2: Wiring — Planner, Registry, ContextBuilder, Analyst

- `planner.py`: agregar `("needs_persona_facts", "knowledge.persona_facts")` y `("needs_voice_patterns", "knowledge.voice_patterns")` a `_NEED_TO_CAPABILITY`.
- `registry.py`: registrar ambos retrievers en `build_default_registry` (reciben la lista cargada del YAML), sumarlos a `PLANNER_CAPABILITY_UNIVERSE` para que el fail-fast de arranque (Anexo H.1) los valide igual que a los demás.
- `context_builder.py`: agregar ambos nombres a `_KNOWLEDGE_EMISSION_ORDER`. Orden sugerido: justo después de `knowledge.context` y antes de `knowledge.memory` (son datos "sobre Diana", conceptualmente más cerca de persona que de memoria/política del VIP):
```python
_KNOWLEDGE_EMISSION_ORDER = (
    "knowledge.history", "knowledge.context",
    "knowledge.persona_facts", "knowledge.voice_patterns",   # nuevas
    "knowledge.memory", "knowledge.policy", "knowledge.examples",
    "knowledge.schedule", "knowledge.profile",
)
```
- `analyst.py`: extender el prompt/schema con los dos campos nuevos, siguiendo el mismo patrón de descripción que ya usa para `needs_memory`/`needs_policy` (Anexo A.3): *"¿este turno pregunta o toca algo biográfico/personal de Diana (familia, estudios, duelo, vivienda)?"* y *"¿este turno se beneficia de un patrón de voz característico (risa, énfasis, arranque) dado el tono/emoción?"*.

### H3: Regla de frustración directa (Decider)

En `decider.py`, nueva regla en la matriz F3 — evalúa **antes** de la regla de `risk == "alto"` (misma prioridad de intención: escalar sin importar si es el primer mensaje):
```python
# 2b. Frustración directa (nueva) — no espera acumulación de turnos.
if comprehension.emotion == "molesta":
    return Decision(action="escalate", reason="frustracion_directa", ...)
```
Es un cambio de una línea porque `Decider` ya recibe `Comprehension` completa — no necesita I/O ni tocar su contrato de pureza (Anexo F.4).

### H4: Regla de repetición (Director + nuevo puerto)

Esta es la pieza nueva de verdad porque el Decisor no puede resolverla (no tiene acceso a turnos anteriores, por diseño).

**Nuevo puerto** en `cognitive/ports.py`:
```python
class RecentIntentsPort(Protocol):
    async def get_recent_intents(self, chat_id: int, *, limit: int = 3) -> list[str]: ...
```

**Nuevo método** en `infrastructure/db/repositories/traces.py`:
```python
async def get_recent_intents(self, chat_id: int, *, limit: int = 3) -> list[str]:
    """Lee comprehension->>'intent' de los últimos N turnos del chat, DESC."""
    stmt = (
        select(PipelineTrace.comprehension["intent"].astext)
        .where(PipelineTrace.chat_id == chat_id)
        .order_by(PipelineTrace.created_at.desc())
        .limit(limit)
    )
    ...
```

**Nuevo módulo puro** `cognitive/repetition_guard.py` (mismo espíritu de pureza que el Planner — recibe datos, no hace I/O):
```python
class RepetitionGuard:
    def __init__(self, threshold: int = 3) -> None:
        self._threshold = threshold

    def is_repeated(self, current_intent: str, recent_intents: list[str]) -> bool:
        # recent_intents ya viene ordenado DESC; cuenta racha desde el turno actual hacia atrás
        streak = 1
        for intent in recent_intents:
            if intent == current_intent:
                streak += 1
            else:
                break
        return streak >= self._threshold
```

**Modificación en `director.py`** (`_run_pipeline`, justo después de `await self._store(turn_id, "comprehension", comprehension)` y antes de `TurnStatus.PLANNING`):
```python
recent = await self._recent_intents.get_recent_intents(turn.chat_id, limit=self._repetition_threshold - 1)
if self._repetition_guard.is_repeated(comprehension.intent, recent):
    await self._status.transition(turn_id, TurnStatus.ESCALATED)
    await self._escalations.create(turn_id, tipo="pregunta_repetida", motivo=comprehension.intent)
    await self._notifier.notify_escalation(...)
    decision = Decision(action="escalate", reason="pregunta_repetida", evaluation=None, draft_text=None, mode_restriction_applied=None)
    await self._store(turn_id, "decision", decision)
    return decision
```
Director gana 2 dependencias nuevas en el constructor: `recent_intents: RecentIntentsPort`, `escalations`/`notifier` (probablemente ya inyectables desde donde se arma en `composition.py`, revisar si conviene pasar el mismo `EscalationStore`/`OwnerNotifierPort` que ya usa `deterministic_escalate.py`).

**Por qué antes del Planner y no en el Decider:** ahorra el costo completo de Generador+Evaluador en el tercer mensaje repetido — si esperaras al Decisor, ya habrías pagado la llamada más cara del pipeline (Generador) para descartar el resultado.

### H5: Wiring final + tests

- `composition.py`: cargar `persona_diana.yaml`, construir `PersonaFactsRetriever`/`VoicePatternsRetriever`, inyectar `RecentIntentsPort` (el mismo repo de traces ya extendido) y `RepetitionGuard` al `CognitiveDirector`.
- Tests nuevos (siguiendo la convención `tests/unit/cognitive/test_*.py` y `tests/unit/infrastructure/test_*.py` ya existente):
  - `test_persona_facts_retriever.py` — match por tema, `None` si no matchea.
  - `test_voice_patterns_retriever.py` — devuelve como máximo un patrón.
  - `test_repetition_guard.py` — racha de 3 mismo intent → `True`; racha interrumpida → `False`.
  - `test_decider.py` (extender) — `emotion == "molesta"` → `escalate`, incluso con `safety` alto.
  - `test_director.py` (extender) — repetición dispara escalación y **no** invoca Generator/Evaluator (mock con `assert_not_called`).

## Orden de implementación

```
H0 (modelo + config) → H1 (retrievers) → H2 (wiring cognitivo)
  → H3 (Decider, independiente, puede ir en paralelo con H4)
  → H4 (Director + puerto + repo)
  → H5 (composition.py + tests)
```

H3 y H4 son independientes entre sí — se pueden hacer en paralelo o en cualquier orden porque tocan archivos distintos (`decider.py` vs `director.py`/`ports.py`/`traces.py`).

## Verificación

1. **Schema**: arranque del sistema no falla por `PLANNER_CAPABILITY_UNIVERSE` (fail-fast de H.1) — las 2 capacidades nuevas resuelven.
2. **Persona facts**: turno con `intent="preguntar_hermanos"` recupera el hecho `familia_hermana`; un saludo simple no recupera nada (`needs_persona_facts=false`).
3. **Voice patterns**: turno con `emotion="positiva"` + tema de "algo bonito compartido" recupera como máximo 1 patrón, nunca 2.
4. **Frustración**: turno con `emotion="molesta"` → `Decision.action == "escalate"` sin importar `safety`/`naturalness`.
5. **Repetición**: 3 turnos seguidos con mismo `intent` en el mismo chat → el 3ro escala **antes** de tocar Generator/Evaluator (verificar con mocks que no se llamaron).
6. **Regresión**: `pytest tests/ -x` — los 979 tests existentes siguen pasando (nada de esto debería tocar Evaluator/Generator/TurnCoordinator).
7. **Presupuesto de prompt**: comparar tamaño de `prompt_final` antes/después en un saludo simple — debe seguir siendo ~mismo tamaño que hoy (persona_facts/voice_patterns no deberían aparecer si `needs_*` es falso).


