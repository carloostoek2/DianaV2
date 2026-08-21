# Plan: Persona Facts + Voice Patterns + Refinamiento de Escalación

> **Estado del plan (2026-08-21): Anexo H implementado y desplegado.** El plan de persona (hechos + patrones de voz + escalación + agenda semanal) está implementado. Los 10 hitos H0–H9 están **cumplidos**: el catálogo vive en `src/diana/config/persona_diana.json` (9 `persona_facts` + 11 `voice_patterns` + `schedule`), los retrievers `persona_facts`, `voice_patterns` y `schedule` están registrados en el Capability Registry y `UNIMPLEMENTED_CAPABILITIES` está vacío (ver [ARCHITECTURE.md](ARCHITECTURE.md), sección "Capability Registry + Retrievers"). Las secciones siguientes se conservan como registro/trazabilidad del plan original; los bloques marcados como "Cumplido" reflejan el estado real del sistema.

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

Como guía de diseño, si el catálogo creciera a decenas/cientos de hechos, o si la dueña necesitara editarlos desde Telegram sin redeploy, el paso natural sería moverlo a tabla + comando de admin; hoy, con 9 hechos + 11 patrones, no se justifica. Es la misma lógica de "no sobre-construir" que ya aplicamos a la decisión de no usar vectores.

## Estado actual (para quien implemente — no re-hacer lo ya hecho)

> **Última verificación de código:** 2026-08-21 (estado real contrastado contra `src/diana/` y `docs/ARCHITECTURE.md`), sobre la verificación previa de 2026-07-28 (pool residuales H7/H9 cerrado, estado contrastado contra SUMMARYs residual-* + commits del pool + tree actual). Hardener H7+H9: 2026-07-27.

| Hito | Qué es | Estado |
|---|---|---|
| H0–H5 | persona_facts + voice_patterns + escalación (frustración/repetición) | ✅ **Implementado** — catálogo `persona_diana.json` (9 facts + 11 patterns), retrievers, wiring Planner/Registry/ContextBuilder/Analyst, `frustracion_directa` en Decider, `RepetitionGuard` + `get_recent_intents` en Director, composition + tests unitarios. |
| H6 | Plantillas deterministas (saludo puro + "¿eres una IA?") | ✅ **Implementado** (actualizado 2026-08-16). IA: pre-pipeline `TemplateGate` (`deteccion_ia`). Saludo puro VIP: post-Analyst cut → pool `plantilla_saludo` (Planner→Decider saltados). Flag `FEATURE_PHATIC_AUTO_SEND` (default false): OFF = approve supervisado; ON = send VIP sin AMS. Atención nunca autoenvía. Commits pool: `141adc5`…`21ab08b`. |
| H7 | Captura de correcciones + historial de salida | ✅ **Implementado** — `handle_correct` → `StagingService.save_correction` (timing A); owner history `role="owner"` en admin (approve/correct) y orquestador autónomo; gate sandbox `should_persist`; `feature_staging_enabled` wire en composition. Commits núcleo: `b7b61da` · `3ee7607` · `f149665` · `212213e`. **Residuales 2026-07-28:** VIP inbound history bajo sandbox (`0cb21db`/`a8212b1`); multi-segment owner history 1 fila/segmento (`16773ee`..`50178c4`); recontact owner history post-deliver (`84fcf69`/`73eaea6`); Promote UI REQ-ADM-08 (`df0f5fc`..`caa8cf4`). Promo **no** escribe history. |
| H8 | Importar `diana_training.db` → tabla `examples` | ✅ **YA EJECUTADO** — 4,348 filas importadas, 455 saltadas por `contenido_pricing_excluido`. Script en `scripts/import_v1_training.py`. **No volver a correr** sin `--limit` salvo que se trunque la tabla `examples` a propósito — no hay chequeo de idempotencia (duplicaría filas). |
| H9 | `knowledge.schedule` real (agenda semanal) | ✅ **Implementado** — `ScheduleRetriever` real (`fuente=agenda_semanal_fija`), catálogo `schedule` en `persona_diana.json`, `ClockPort` cognitivo, ContextBuilder typed render, ContextRetriever day/time CDMX, Analyst needs_schedule, `UNIMPLEMENTED_CAPABILITIES` vacío. Commits núcleo: `e6aaf47` · `08be3d4` · `d217e0e` · `0f4aa69` · `410ab74`. **Residual H9.5 (2026-07-28):** `is_first_message_of_day` alineado a día civil America/Mexico_City (`65dcc22`/`5aae5be`). |

**Resumen:** 10/10 hitos del plan Anexo H cerrados (H0–H9). Pool hardener H7+H9 (2026-07-27) + pool residuales H7/H9 (2026-07-28): tests green, self-check PASSED, review 0 open.

**Residuales H7/H9 — estado (pool 2026-07-28):** VIP sandbox history ✅ · multi-segment owner history ✅ · H9.5 CDMX ✅ · recontact owner history ✅ · Promote UI (REQ-ADM-08) ✅ · promo history ❌ (explícito out-of-scope). Índice: `.grok/agent-memory/residuals/h7-h9-pool.md`.

**`needs_examples` (resuelto a nivel de código, 2026-08-21):** el campo está en el schema del Analyst (`cognitive/analyst.py`, con descripción de activación), se mapea en `planner.py` a `knowledge.examples` y lo lee `evaluator.py` — la capacidad está cableada. Queda como **pendiente de investigación (operativo)**: confirmar en los traces de producción que `needs_examples` se activa en turnos reales y que el pool de H8 (4,348 ejemplos) genera retrievals efectivos. No es una brecha de implementación. Tras H7 + Promote UI, las correcciones de dueña alimentan staging y la dueña puede listar/promover/descartar ejemplos pendientes vía `/staging` (flag `FEATURE_STAGING_ENABLED`).
## Orden global (orden ejecutado)

```
H0 → H1 → H2 → (H3 ∥ H4) → H5     [núcleo: persona_facts/voice_patterns/escalación]
H6                                 [independiente — solo toca Director + nuevo template_gate.py]
H7                                 [independiente — solo toca admin_service.py/turn_orchestrator.py]
H9                                 [independiente — solo toca schedule.py/ports.py/registry.py/analyst.py]
```
H6, H7 y H9 no dependían entre sí ni de H0–H5 (tocan archivos distintos, salvo que los tres tocan `analyst.py`/`director.py` — hubo que revisar conflictos de merge si se ejecutaban en paralelo por separado). Orden relativo entre ellos: el que se quiso ver reflejado primero en producción.

## Plan de implementación (10 hitos: H0–H9)

### H0: Modelo + config

> **Cumplido (2026-08-21):** `needs_persona_facts`/`needs_voice_patterns` añadidos a `Comprehension` (`cognitive/models.py`); el catálogo real vive en `src/diana/config/persona_diana.json` (9 `persona_facts` + 11 `voice_patterns`) y se sirve vía `PersonaCatalogProvider` en `composition.py`.

- Añadir `needs_persona_facts: bool` y `needs_voice_patterns: bool` a `Comprehension` (`cognitive/models.py`). **Nota de compatibilidad:** esto es un cambio de schema (Anexo A.7) — las filas históricas de `pipeline_traces.comprehension` no tendrán estas claves. Verificar que nada re-valida JSON histórico contra el modelo Pydantic estricto (solo se muestra como blob en `AdminTraceService`/`/traza`) antes de desplegar.
- Crear `config/persona_diana.yaml` con el contenido ya redactado en el Anexo J (J.2 y J.3), incluyendo el hecho de vivienda ya resuelto.
- Loader simple en `composition.py` (YAML → dict en memoria, sin nueva dependencia si ya usan `pyyaml`; si no, `tomllib`/JSON son alternativas igual de válidas).

### H1: Retrievers nuevos (sin embeddings)

> **Cumplido (2026-08-21):** `cognitive/retrievers/persona_facts.py` y `cognitive/retrievers/voice_patterns.py` existen, con match determinista por sets (sin embeddings) y refresco por canal vía `persona_catalog_provider`.

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

> **Cumplido (2026-08-21):** `planner.py` mapea ambas capacidades (`needs_persona_facts`/`needs_voice_patterns` → `knowledge.*`); `registry.py` las registra en `build_default_registry` y en `PLANNER_CAPABILITY_UNIVERSE`; `context_builder.py` las emite tras `knowledge.context`; `analyst.py` incluye los dos campos con su descripción de activación.

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

> **Cumplido (2026-08-21):** `decider.py` evalúa `emotion == "molesta"` → `Decision(action="escalate", reason="frustracion_directa")` antes de la regla de riesgo alto.

En `decider.py`, nueva regla en la matriz F3 — evalúa **antes** de la regla de `risk == "alto"` (misma prioridad de intención: escalar sin importar si es el primer mensaje):
```python
# 2b. Frustración directa (nueva) — no espera acumulación de turnos.
if comprehension.emotion == "molesta":
    return Decision(action="escalate", reason="frustracion_directa", ...)
```
Es un cambio de una línea porque `Decider` ya recibe `Comprehension` completa — no necesita I/O ni tocar su contrato de pureza (Anexo F.4).

### H4: Regla de repetición (Director + nuevo puerto)

> **Cumplido (2026-08-21):** `RecentIntentsPort` en `cognitive/ports.py`, `get_recent_intents` en `infrastructure/db/repositories/traces.py`, `RepetitionGuard` en `cognitive/repetition_guard.py` y el chequeo post-Analyst en `director.py` (si dispara, salta Planner/Retrievers/Generador/Evaluador).

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

> **Cumplido (2026-08-21):** `composition.py` carga el catálogo e inyecta los retrievers + `RecentIntentsPort`/`RepetitionGuard` al `CognitiveDirector`; tests unitarios en `tests/unit/` (retrievers, guard, decider, director).

- `composition.py`: cargar `persona_diana.yaml`, construir `PersonaFactsRetriever`/`VoicePatternsRetriever`, inyectar `RecentIntentsPort` (el mismo repo de traces ya extendido) y `RepetitionGuard` al `CognitiveDirector`.
- Tests nuevos (siguiendo la convención `tests/unit/cognitive/test_*.py` y `tests/unit/infrastructure/test_*.py` ya existente):
  - `test_persona_facts_retriever.py` — match por tema, `None` si no matchea.
  - `test_voice_patterns_retriever.py` — devuelve como máximo un patrón.
  - `test_repetition_guard.py` — racha de 3 mismo intent → `True`; racha interrumpida → `False`.
  - `test_decider.py` (extender) — `emotion == "molesta"` → `escalate`, incluso con `safety` alto.
  - `test_director.py` (extender) — repetición dispara escalación y **no** invoca Generator/Evaluator (mock con `assert_not_called`).

## Orden de implementación (ejecutado)

```
H0 (modelo + config) → H1 (retrievers) → H2 (wiring cognitivo)
  → H3 (Decider, independiente, puede ir en paralelo con H4)
  → H4 (Director + puerto + repo)
  → H5 (composition.py + tests)
```

H3 y H4 son independientes entre sí — se pueden hacer en paralelo o en cualquier orden porque tocan archivos distintos (`decider.py` vs `director.py`/`ports.py`/`traces.py`). Este orden es el que se siguió en la implementación; todos los hitos están cumplidos.

## Verificación

1. **Schema**: arranque del sistema no falla por `PLANNER_CAPABILITY_UNIVERSE` (fail-fast de H.1) — las 2 capacidades nuevas resuelven.
2. **Persona facts**: turno con `intent="preguntar_hermanos"` recupera el hecho `familia_hermana`; un saludo simple no recupera nada (`needs_persona_facts=false`).
3. **Voice patterns**: turno con `emotion="positiva"` + tema de "algo bonito compartido" recupera como máximo 1 patrón, nunca 2.
4. **Frustración**: turno con `emotion="molesta"` → `Decision.action == "escalate"` sin importar `safety`/`naturalness`.
5. **Repetición**: 3 turnos seguidos con mismo `intent` en el mismo chat → el 3ro escala **antes** de tocar Generator/Evaluator (verificar con mocks que no se llamaron).
6. **Regresión**: `pytest tests/ -x` — los 979 tests existentes siguen pasando (nada de esto debería tocar Evaluator/Generator/TurnCoordinator).
7. **Presupuesto de prompt**: comparar tamaño de `prompt_final` antes/después en un saludo simple — debe seguir siendo ~mismo tamaño que hoy (persona_facts/voice_patterns no deberían aparecer si `needs_*` es falso).

## Definición de "listo" (H0–H9 completo)

Antes de dar por cerrado el trabajo, además de la Verificación de H0–H5 y las de H6.6/H7.4/H9.7 (cada una en su sección):

1. `pytest tests/ -x` completo pasa (979 tests previos + los nuevos de cada hito).
2. Arranque de `composition.py` no falla (fail-fast del Capability Registry con las capacidades nuevas: `persona_facts`, `voice_patterns`, `schedule` ya no en `UNIMPLEMENTED_CAPABILITIES`).
3. Un turno de prueba real por cada hito nuevo (saludo puro → Analyst + plantilla `plantilla_saludo` con approve o send según `FEATURE_PHATIC_AUTO_SEND`; "¿eres una IA?" → plantilla pre-pipeline; pregunta de actividad en horario de servicio → agenda real; pregunta de actividad en hueco → una de las 3 respuestas libres; corrección de un borrador → aparece en `staging_candidates` y en `message_history`).
4. **No tocar `scripts/import_v1_training.py` ni volver a ejecutarlo** — H8 ya está hecho (ver tabla de Estado actual arriba).

## Nota aparte (fuera de este plan, mencionada por completitud)

> **Resuelta (2026-08-16):** la plantilla fija para "¿eres una IA?" se implementó vía `TemplateGate` pre-pipeline (`deteccion_ia`), no en `ForbiddenKeywordsMiddleware` — ver H6. El texto original de la nota se conserva como registro del razonamiento.

La plantilla fija para "¿eres una IA?" (Anexo J.4) usa el mismo mecanismo de `ForbiddenKeywordsMiddleware` que ya tienes, pero ese componente hoy solo sabe **escalar en silencio** (`handle_deterministic_escalation`), no **responder con texto fijo y luego escalar**. Si quieres esa plantilla exacta, es un pequeño cambio adicional en ese middleware (una rama nueva: "keyword de tipo respuesta-fija" vs "keyword de tipo escalar-silencioso"). Lo dejo fuera de este plan porque no lo mencionaste como prioridad ahora — dime si quieres que lo diseñe aparte.

---

## H6: Plantillas deterministas — saludo puro + "¿eres una IA?"

> **Cumplido (2026-08-16):** ver bloque "Estado de código" abajo — `TemplateGate` pre-pipeline (`deteccion_ia`) + pool `plantilla_saludo` post-Analyst con `FEATURE_PHATIC_AUTO_SEND`.

> **Estado de código (2026-08-16, pool saludo-cognitivo):**  
> - **"¿eres una IA?"** sigue en `TemplateGate` **pre-pipeline** (`deteccion_ia` only en producción): 0 Analyst, `action=approve`, `reason=plantilla_deteccion_ia`.  
> - **Saludo puro VIP** ya **no** es short-circuit pre-Analyst ni `saludo_constante` en el gate de producción. Flujo: Analyst → predicado inyectado (`intent==saludar` + fático confiable vía `TurnClassifier` en composition) → pool de saludo → `reason=plantilla_saludo`. Planner / Generator / Evaluator / Decider no corren en el corte.  
> - **`FEATURE_PHATIC_AUTO_SEND`** (default **false** en Settings; deploy puede poner `true`): OFF → `action=approve` (cola de la dueña); ON → `action=send` solo VIP, entrega en TurnOrchestrator por `_prepare_phatic_template_send` (**sin** AMS L1/L2, **sin** trust_budget). Atención (`vip_id is None`) demote a approve. Congelado / pausado / draft vacío → fail-closed.  
> - **No** reutilizar `FEATURE_PHATIC_AUTONOMY` (shadow del clasificador) como interruptor de envío.  
> - Tabla Decider AGENTS.md §4.1 **sin cambios** (el corte es pre-Decider).

### H6.1 Por qué NO van en `ForbiddenKeywordsMiddleware`

Ese middleware corre en la capa de Telegram, antes de que exista un `Turn`/`IncomingTurn` formal, y su único camino de salida es "escalar en silencio, sin respuesta al VIP" (`handle_deterministic_escalation`). Ni el saludo ni "¿eres una IA?" quieren eso — quieren **una respuesta real** (texto de plantilla), no un silencio de escalación. El lugar correcto es `CognitiveDirector.handle_turn` / pipeline, no el middleware.

**IA (sin cambio de capa):** primer chequeo pre-Analyst vía `TemplateGate` → borrador fijo → cola de aprobación (`approve`).

**Saludo (2026-08-16):** el producto exige que **todo saludo entre al Analista** (comprender si es puro o mixto). Solo el saludo **puro** corta a plantilla después de guardar comprehension; saludos con carga / ambigüedad siguen el pipeline completo. Con flag de auto-send OFF el borrador sigue yendo a la dueña; con flag ON el VIP recibe el pool sin pasar por AMS.

### H6.2 Nuevo componente puro: `cognitive/template_gate.py`

Mismo espíritu que `Planner`/`RepetitionGuard` — determinista, sin I/O, sin LLM:

```python
@dataclass(frozen=True)
class TemplateRule:
    id: str
    trigger_patterns: list[str]   # keywords/frases, mismo estilo que match_forbidden_keywords
    max_words: int | None         # None = sin límite; usado para "saludo puro" vs mensaje mixto
    response_pool: list[str]      # 1 o más variantes
    reason: str                   # aparece en Decision.reason, visible en /traza y /turnos

class TemplateGate:
    def __init__(self, rules: list[TemplateRule], *, rng=random) -> None:
        self._rules = rules
        self._rng = rng

    def match(self, text: str) -> TemplateRule | None:
        words = text.strip().split()
        lower = text.lower()
        for rule in self._rules:
            if rule.max_words is not None and len(words) > rule.max_words:
                continue
            if any(_kw_hit(kw, lower) for kw in rule.trigger_patterns):
                return rule
        return None

    def render(self, rule: TemplateRule) -> str:
        return self._rng.choice(rule.response_pool)
```

`_kw_hit` reutiliza la misma lógica de `match_forbidden_keywords` (regex de palabra completa o frase) — no hace falta inventar un matcher nuevo.

### H6.3 Reglas: producción vs diseño histórico

**Producción (composition, 2026-08-16):**

```python
# TemplateGate de producción: SOLO IA (pre-pipeline)
deteccion_ia = TemplateRule(
    id="deteccion_ia",
    trigger_patterns=["eres una ia", "eres un bot", "eres ia",
                       "hablo con una ia", "hablo con un bot", "eres real"],
    max_words=None,
    response_pool=["jsjsj si y sólo vivo en tu mente 😏"],
    reason="plantilla_deteccion_ia",
)
template_gate = TemplateGate(rules=[deteccion_ia])

# Pool de saludo (inyectado al Director; NO va al TemplateGate de producción)
saludo_response_pool = ["Holis 😁"]

# Predicado de corte (composition adapta un único TurnClassifier → PureGreetingCutPort)
# intent == "saludar"
#   AND looks_like_pure_greeting_text (keyword + ≤4 palabras)
#   AND category fático + is_confident
#   (NO agradecer/despedirse; NO basta el intent del Analyst)
```

**Diseño histórico (H6 original):** existía `TemplateRule` `saludo_constante` con keywords + `max_words=4` en el gate pre-pipeline. La clase `TemplateGate` aún soporta esa forma (tests unitarios del gate); **producción ya no la cablea** como short-circuit pre-Analyst. El candado anti-mixto es **doble**: (1) forma del texto (`looks_like_pure_greeting_text`, misma lista + techo de 4 palabras) y (2) comprehension + clasificador (`ambiguedad_saludo_mas_carga` / no confiable → pipeline completo). El Analyst solo no puede disparar la plantilla: un `intent=saludar` sobre "dale" o "Hola, tengo una pregunta…" falla el corte.

### H6.4 Integración en `CognitiveDirector` (estado actual)

```text
handle_turn:
  if template_gate.match(text):          # producción: solo deteccion_ia
    return _handle_template(...)         # approve + plantilla_deteccion_ia; 0 Analyst
  return _run_pipeline(turn)

_run_pipeline:
  Analyst → store comprehension
  if pure_greeting_cut(text, comprehension) and saludo_pool:
     draft = choice(pool)
     action = "send" if phatic_auto_send else "approve"
     Decision(action, reason="plantilla_saludo", draft_text=draft, eval zeros)
     store generated_text + decision; return   # skip Planner…Decider
  # … H4 / Planner → … → Decider
```

**IA:** `_handle_template` sigue emitiendo siempre `action=approve` (nunca send/escalate en plantilla de IA).

**Saludo + orquestador:**

| Flag / canal | Director | TurnOrchestrator |
|--------------|----------|------------------|
| `FEATURE_PHATIC_AUTO_SEND=false` | `approve` + `plantilla_saludo` | Cola de la dueña (igual que cualquier approve) |
| flag true + VIP | `send` + `plantilla_saludo` | `_prepare_phatic_template_send` → BehaviorEngine (sin AMS) |
| flag true + Atención | puede emitir send en corte* | demote `phatic_auto_send_atencion` → approve |
| frozen / paused | — | fail-closed (`vip_frozen` / `vip_paused`) |

\*La defensa dura de Atención está en el orquestador; el corte cognitivo no filtra canal.

La traza conserva `reason: plantilla_saludo` / `plantilla_deteccion_ia` visible en `/traza`. No hay segunda escalación en paralelo (invariante del Turn Coordinator).

### H6.5 Qué se salta (y por qué)

| Camino | Analyst | Planner→Decider | LLM costo | Entrega |
|--------|---------|-----------------|-----------|---------|
| IA template pre-pipeline | no | no | 0 | approve (dueña) |
| Saludo puro post-Analyst | **sí (1×)** | no | 1× Analyst | approve o send (flag) |
| Saludo mixto / no-saludar | sí | sí (pipeline) | completo | Decider normal |

Ganancia del corte de saludo: se evita Planner + Generator + Evaluator + Decider en el saludo puro, a cambio de **siempre** pagar el Analista (tradeoff de producto: clasificar puro vs mixto). La plantilla IA sigue siendo 0 LLM.

### H6.6 Verificación adicional (contrato 2026-08-16)

1. "Hola" puro → Analyst **una vez**; `reason == plantilla_saludo`; `draft_text` ∈ pool; Planner/Generator/Evaluator/Decider **no** se llaman; con flag OFF `action=approve`; con flag ON `action=send`.
2. Saludo con carga / ambigüedad / intent ≠ `saludar` (p. ej. agradecer, despedirse) → **pipeline completo**, no pool de saludo.
3. "eres una ia?" → pre-pipeline, 0 Analyst, `draft_text` exacto del pool IA, `action=approve`.
4. Flag ON + Atención → no entrega autónoma (demote a approve). Flag ON + VIP congelado/pausado → no envía.
5. `FEATURE_PHATIC_AUTONOMY` no dispara envío; import purity cognitive↛application en verde.
6. Limpieza de `config/persona_diana.yaml`: quitar el `(ver J.2 / examples)` de `reglas_estilo` (hallazgo de la sesión original H6). **Cumplido (2026-08-21):** el catálogo real vive en `src/diana/config/persona_diana.json`.

---

## H7: Corrección persistida + historial de salida (gap encontrado en esta sesión)

> **Cumplido (2026-08-21):** `handle_correct` → `StagingService.save_correction`; owner history `role="owner"` en admin (approve/correct) y orquestador autónomo. Ver tabla de Estado actual (residuales 2026-07-28 todos cerrados salvo promo history, explícito out-of-scope).

### H7.1 Diagnóstico (confirmado en código, no hipótesis)

- `AdminService._resolve_and_deliver` entrega el texto correcto (original o corregido) pero **nunca actualiza** el `Decision`/`draft_text` ya persistido en la traza — solo actualiza `delivery_result` y el `status` de la aprobación.
- `StagingService.save_correction()` existe y está testeado, pero **no tiene ningún llamador en `admin_service.py`** — la corrección de la dueña se entrega y se pierde.
- `MessageHistoryWriter.append()` solo se llama una vez en todo el código (`turn_orchestrator.py:225`), con `role="vip"` — el texto que Diana efectivamente envía (aprobado o corregido) **nunca se escribe al historial**. `HistoryRetriever` ya sabe mapear `role="owner"` → `autor="dueña"` (Anexo A.2), pero nadie le da esas filas.

### H7.2 Fix — dos cambios pequeños y acotados

**a) Capturar la corrección real (`admin_service.py`, `handle_correct`)**
```python
async def handle_correct(self, turn_id, corrected_text, *, actor_id=None):
    self._assert_owner(actor_id)
    if not (corrected_text or "").strip():
        raise ValueError("corrected_text must be non-empty")
    turn = await self._turns.get(turn_id)
    approval = await self._approvals.get_by_turn(turn_id)
    if turn is not None and approval is not None and self._staging is not None:
        await self._staging.save_correction(
            turn_id,
            original_draft=approval.draft_text,
            corrected_text=corrected_text.strip(),
            context={"chat_id": turn.chat_id, "turn_text": turn.trigger_text},
        )
    return await self._resolve_and_deliver(turn_id, corrected_text=corrected_text.strip())
```
`AdminService` gana una dependencia opcional `staging: StagingService | None` (igual patrón que `fp_marks`/`gray_zone` — opcional para no romper despliegues donde `feature_staging_enabled=False`).

**b) Registrar el texto entregado en el historial (`admin_service._resolve_and_deliver` y `turn_orchestrator._finalize_autonomous_delivery`)**
Justo después de `result.success` confirmado:
```python
if self._history is not None:
    await self._history.append(chat_id, role="owner", text=text, telegram_message_id=result.message_ids[0] if result.message_ids else None)
```
`role="owner"` porque en modo supervisado todo lo que sale ya fue aprobado por la dueña — es consistente con el vocabulario `vip|dueña` que ya usa `HistoryRetriever` (Anexo A.2), no hace falta un rol nuevo "bot"/"assistant".

### H7.3 Por qué esto importa más de lo que parece

No es solo higiene de datos — el ejemplo de "uy, no wey" que me mandaste es la prueba viva de que el sistema está generando errores de voz, y **ahora mismo cada corrección tuya se pierde en vez de convertirse en la señal que evita que se repita.** Sin H7, el catálogo de `knowledge.examples` nunca crece con tus correcciones reales — se queda vacío para siempre salvo que promuevas manualmente algo por otro camino que tampoco existe todavía (Anexo de auditoría, REQ-ADM-08).

### H7.4 Verificación
1. Corregir un borrador → aparece una fila `pending` en `staging_candidates` con `original_draft`/`corrected_text` correctos.
2. Tras entrega exitosa (aprobado o corregido) → nueva fila en `message_history` con `role="owner"` y el texto realmente enviado.
3. Un segundo turno del mismo chat → `HistoryRetriever` incluye la respuesta de Diana del turno anterior, no solo el mensaje del VIP.

---

## H8: Importar `diana_training.db` a `knowledge.examples`

> **Cumplido/ejecutado (2026-08-21):** 4,348 filas importadas vía `scripts/import_v1_training.py` (455 saltadas por `contenido_pricing_excluido`). **No re-ejecutar** sin `--limit` — no hay chequeo de idempotencia. Las preguntas abiertas de H8.2 se resolvieron durante la ejecución.

### H8.1 Mapeo de los 3 casos usables (4 803 de 4 916 filas — mismo filtro que v1 ya usa en `get_few_shots`)

| Origen v1 | Filas | `Example.turn_text` | `Example.draft_text` | `Example.corrected_text` | `is_counter_example` |
|---|---|---|---|---|---|
| `diana_manual` (extracción + observación) | 4 623 | Último mensaje del VIP en el contexto | `""` (no hay borrador que contrastar — es habla real) | El mensaje real de Diana | `False` |
| `good` (aprobado sin cambios) | 128 | Último mensaje del VIP | `""` (aprobado tal cual, no hay contraste útil) | `bot_response` | `False` |
| `corrected` | 52 | Último mensaje del VIP | `bot_response` (el borrador rechazado) | `correction` (la reescritura de la dueña) | `False` |
| `pending` (113) / `bad` (0) | — | **no se importan** — mismo criterio que `get_few_shots` de v1 |

Los 52 de `corrected` son el activo más valioso del lote: son exactamente el patrón `draft_text` vs `corrected_text` para el que se diseñó la tabla `examples` de v2 — no hace falta transformar nada conceptualmente, solo copiar.

El campo `topic` de v1 (ej. `saludo_cumpleaños`, `futbol`) no tiene columna equivalente en v2 — lo guardo dentro de `context` (`{"topic": ..., "v1_id": ..., "v1_rating": ...}`) para trazabilidad/auditoría futura, aunque `ExamplesRetriever` no lo use hoy para filtrar (busca solo por similitud de embedding sobre `turn_text`).

### H8.2 El punto que necesito que me confirmes antes de escribir el script

`ExamplesRetriever.fetch()` embebe `turn.text` (el mensaje **actual** del VIP) y lo compara contra `Example.embedding`, que debe haberse calculado **con el mismo modelo de embeddings** que usa `embedding_service` en producción (384 dimensiones, consistente con `sentence-transformers` en tu `pyproject.toml`). El script de migración necesita:
1. El mismo modelo/config que usa `composition.py` para instanciar `embedding_service` — dime cuál es si no es el default de `sentence-transformers` (ej. `all-MiniLM-L6-v2`).
2. **El archivo real `diana_training.db` (o al menos el schema exacto de la tabla `examples`, vía `PRAGMA table_info(examples)`)** — el reporte que me pasaste describe el "Context (last turns)" como una vista reconstruida para el documento, no me confirma si eso vive en una columna `context` propia por fila o si hay que reconstruirlo con un join. Necesito la forma exacta de la columna para no adivinar mal el `turn_text` de las 4,803 filas.

Con eso te devuelvo un script de migración (`scripts/import_v1_training.py`, offline, no toca producción) que hace: leer → filtrar (mismo criterio que `get_few_shots`) → generar embeddings → `ExamplesRepo.insert()` en lote → reporte final de cuántas filas por caso quedaron cargadas.

---

## H9: Implementar `knowledge.schedule` (agenda semanal fija)

> **Cumplido (2026-08-21):** el retriever real está implementado y registrado; esta sección se conserva como trazabilidad del plan.

### H9.1 Diagnóstico (estado original) y estado real

**Estado real (2026-08-21):** `cognitive/retrievers/schedule.py` existe con `ScheduleRetriever` real (`fuente="agenda_semanal_fija"`), registrado en `registry.py` bajo `knowledge.schedule` y validado por el fail-fast de `PLANNER_CAPABILITY_UNIVERSE`. `UNIMPLEMENTED_CAPABILITIES` está vacío (`frozenset()` — comentado "Empty after H9 (schedule is real)"). Su `fetch()` **nunca devuelve `None`**: retorna `{"tipo": "actividad", ...}` cuando el día/hora CDMX cae dentro de un bloque y `{"tipo": "respuesta_libre", ...}` en huecos o fuera de horario — la "respuesta libre" es el comportamiento diseñado para tiempo muerto, no un hueco de implementación.

**Diagnóstico original (previo a implementar, 2026-07):** `ScheduleRetriever` existía como el placeholder del Anexo H.3 (`fuente="no_implementado"`, `fetch()` → `None`) y era la única capacidad sin implementar. Todo el plumbing (`Planner._NEED_TO_CAPABILITY`, `registry.py`, `context_builder._KNOWLEDGE_EMISSION_ORDER`) ya estaba conectado; hoy esa condición ya no aplica — el retriever está implementado y registrado.

Segundo hallazgo del trace real: `"Y ahora qué haces?"` → `needs_schedule: false`. El Analista tampoco reconocía ese patrón — se resolvió ajustando su prompt además de escribir el retriever (ver H9.6).

### H9.2 Config — tabla semanal (`config/persona_diana.yaml`, mismo archivo de H0)

```yaml
schedule:
  timezone: "America/Mexico_City"
  default_responses:   # respuestas YA completas en su voz — no son "hechos", no se parafrasean
    - "Pues aquí entre cosas jsjsjs y tú?"
    - "Ya ni sé jsjsj estoy con mil cosas!"
    - "En modo zombi tratando de recuperar el alma 😁"
  bloques:
    - dias: [lunes, martes, miercoles, jueves, viernes]
      inicio: "09:00"
      fin: "12:00"
      actividad: "en el servicio social, en un instituto de adicciones"
    - dias: [lunes, martes, miercoles, jueves]
      inicio: "16:00"
      fin: "21:00"
      actividad: "en las prácticas profesionales, en una casa hogar"
    - dias: [viernes]
      inicio: "17:00"
      fin: "20:00"
      actividad: "en el diplomado de gamificación"
    - dias: [sabado]
      inicio: "08:00"
      fin: "12:00"
      actividad: "en su clase de inglés"
    - dias: [sabado]
      inicio: "14:00"
      fin: "20:00"
      actividad: "dando clases personalizadas a niños, en sus casas"
    - dias: [domingo]
      inicio: "00:00"
      fin: "23:59"
      actividad: "con su hermana, la mayor parte del día"
```
Fuera de estos bloques (L-J 12–16, V 12–17, S 12–14, y fuera de todo horario) cae en `default_responses` — una de las 3, elegida al azar, **como respuesta completa**, no como dato a parafrasear.

### H9.3 Nuevo puerto: `ClockPort` (testabilidad — mismo patrón que ya usa `recovery_startup.py`)

```python
# cognitive/ports.py
class ClockPort(Protocol):
    def now(self) -> datetime: ...
```
No reutilizo el `ClockPort` de `application/recovery_startup.py` directamente porque `cognitive/` no debe importar de `application/` (regla de capas que ya vi enforced con AST gates en varios retrievers) — es el mismo contrato, duplicado en la capa correcta.

### H9.4 `ScheduleRetriever` real

```python
import random
from zoneinfo import ZoneInfo
from diana.cognitive.ports import ClockPort

_WEEKDAY_ES = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]

class ScheduleRetriever:
    """Anexo H.3 knowledge.schedule — agenda semanal fija, sin embeddings."""

    fuente: str = "agenda_semanal_fija"

    def __init__(self, bloques: list[dict], default_responses: list[str], tz: str,
                 clock: ClockPort, rng=random) -> None:
        self._bloques = bloques
        self._defaults = default_responses
        self._tz = ZoneInfo(tz)
        self._clock = clock
        self._rng = rng

    async def fetch(self, turn, comprehension) -> dict | None:
        now_local = self._clock.now().astimezone(self._tz)
        dia = _WEEKDAY_ES[now_local.weekday()]
        hora = now_local.strftime("%H:%M")
        for b in self._bloques:
            if dia in b["dias"] and b["inicio"] <= hora < b["fin"]:
                # Caso "actividad": dato para que el Generador construya la oración.
                return {"dia": dia, "hora_actual": hora, "tipo": "actividad", "actividad": b["actividad"]}
        # Caso "tiempo muerto": respuesta YA completa, no un dato a parafrasear.
        return {"dia": dia, "hora_actual": hora, "tipo": "respuesta_libre",
                "respuesta_sugerida": self._rng.choice(self._defaults)}
```

`ContextBuilder` renderiza cada caso distinto: si `tipo == "actividad"`, se presenta como hecho ("Diana está: {actividad}") para que el Generador redacte alrededor; si `tipo == "respuesta_libre"`, se presenta como ancla de estilo ("si preguntan qué haces ahora, algo en este tono: '{respuesta_sugerida}'") — mismo principio que los `voice_patterns` (H2): ancla, no dictado literal obligatorio.

`registry.py`: quitar `"knowledge.schedule"` de `UNIMPLEMENTED_CAPABILITIES` (no la usa nadie más — confirmado, safe) y registrar la instancia real con el `clock` de producción.

### H9.5 Día/hora siempre-presente (independiente de `needs_schedule`)

Extiendo `ContextRetriever` (que ya corre seguido, cuando `needs_context=true`) para incluir `dia_semana`/`hora_actual` junto a lo que ya trae (`is_first_message_of_day`, `waiting_for_reply_since`) — barato, no necesita capacidad nueva. Esto reduce contradicciones incluso en turnos donde no se pidió `knowledge.schedule` explícitamente.

> **Estado residual 2026-07-28:** `is_first_message_of_day` compara fechas en día civil **America/Mexico_City** (misma TZ que `dia_semana` / `hora_actual`). Commits: `65dcc22` · `5aae5be`. Antes usaba `.date()` en UTC y cruzaba el límite de día de forma inconsistente.

### H9.6 Fix al Analista — `needs_schedule` no dispara con "¿qué haces ahora?"

> **Cumplido (2026-08-21):** el prompt del Analyst en `cognitive/analyst.py` ya incluye el patrón de actividad/disponibilidad actual — *"needs_schedule=true for direct questions about Diana's current activity/availability right now (qué haces, dónde andas, estás libre / "ahora qué haces"), not only future appointments"*.

En `analyst.py`, ampliar la descripción del campo: agregar explícitamente el patrón *"pregunta directa sobre la actividad/disponibilidad actual de Diana en este momento (qué haces, dónde andas, estás libre)"* como disparador de `needs_schedule=true` — hoy el prompt solo lo asocia (implícitamente) con temas de citas/agenda futura, no con "ahora mismo".

### H9.7 Verificación

> **Verificación cumplida (2026-08-21)** — los checks 1-5 se satisficieron durante la implementación de H9 (tests con `ClockPort` fake + verificación de presupuesto de prompt).

1. `"Y ahora qué haces?"` en jueves 14:30 hora CDMX → `needs_schedule=true`, `knowledge.schedule` retorna `{"tipo": "actividad", "actividad": "en las prácticas profesionales..."}`, el borrador no contradice eso.
2. Mismo mensaje en domingo → `actividad` = "con su hermana...".
3. Mismo mensaje en jueves 13:00 (hueco) → `{"tipo": "respuesta_libre", "respuesta_sugerida": "<una de las 3>"}`, y el borrador suena a esa línea sin citarla forzosamente palabra por palabra.
4. `ClockPort` fake en tests para fijar día/hora sin depender del reloj real (mismo patrón que ya usan los tests de `recovery_startup`).
5. Confirmar que un turno sin `needs_schedule` (ej. saludo simple) sigue sin traer `knowledge.schedule` — el ahorro de presupuesto de prompt no se pierde por hacerlo "siempre presente" a medias (solo día/hora vía H9.5, no el bloque completo).
