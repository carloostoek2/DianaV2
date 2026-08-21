# Plan: Sistema de Trazabilidad Interactiva (Anexo T)

> **Estado: Plan implementado (2026-08-21).** El sistema de trazabilidad interactiva está implementado y desplegado: `AdminTraceService` + migración `005_trace_timings` + comandos `/turnos` y `/traza` en el DM del Director, con keyboards y callbacks de navegación (`vt`/`td`/`tp`/`tj`/`tb`). La especificación resultante es `docs/ANEXO_T-TRAZABILIDAD.md` (Anexo T). Este documento conserva la estructura de hitos como registro del plan original; cada hito está marcado como cumplido.

## Context

La dueña necesita inspeccionar el paso a paso de cualquier turno desde su DM de Telegram: qué decidió cada nodo cognitivo, cuánto tardó, y si hubo errores. Toda la información ya se persiste en `pipeline_traces`. La exposición quedó implementada: `AdminTraceService` (`src/diana/application/admin_trace_service.py`) provee la capa de consulta read-only y la superficie del Director (comandos `/turnos`, `/traza` y botones de traza) la hace interactiva desde el DM. Es un sistema read-only, no intrusivo, que corre en paralelo a Fase 2 sin modificar el pipeline cognitivo.

## Arquitectura de cambios

> Registro del diseño. Todos los archivos listados están implementados en el código actual.

```
NUEVOS archivos:
  application/admin_trace_service.py   → AdminTraceService + DTOs TurnSummary/FullTrace
  cognitive/timing.py                  → TimingContext (context manager)

MODIFICADOS:
  infrastructure/db/models.py          → añadir timings a PipelineTrace
  infrastructure/db/repositories/traces.py → get_recent_turns(), get_full_trace(), count_recent()
  cognitive/director.py                → instrumentar cada paso con TimingContext
  telegram/keyboards.py                → añadir "Ver traza" a draft_keyboard, nuevos keyboards de traza
  telegram/handlers/admin.py           → comandos /turnos y /traza
  telegram/handlers/callbacks.py       → dispatchear callbacks de traza
  telegram/notifier.py                 → notify_draft() incluye "Ver traza" (usa draft_keyboard ya modificado)
  application/ports.py                 → TrazabilityReader protocol
  composition.py                       → wiring de AdminTraceService
  alembic/versions/005_trace_timings.py → migración: timings + índice

NO se modifica:
  - El pipeline cognitivo (Director, Generador, Evaluador, Decisor)
  - Behavior Engine
  - TurnOrchestrator (solo se expone información ya persistida)
```

## Plan de implementación (7 hitos)

Los 7 hitos (H0-H7) están implementados; cada sección conserva el detalle del plan original.

### H0: Migración + modelo — ✅ Cumplido

**Estado:** La migración `005_trace_timings` aplica la columna `timings` (JSONB, `server_default '{}'`) y el índice `pipeline_traces_created_at_idx`. El modelo `PipelineTrace` expone la columna `timings` (`src/diana/infrastructure/db/models.py:146`).

**Migración** `alembic/versions/005_trace_timings.py`:
```sql
ALTER TABLE pipeline_traces ADD COLUMN timings JSONB DEFAULT '{}'::jsonb;
CREATE INDEX CONCURRENTLY IF NOT EXISTS pipeline_traces_created_at_idx
  ON pipeline_traces (created_at DESC);
```

**Modelo** en `infrastructure/db/models.py`:
- `timings: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, server_default=text("'{}'::jsonb"))` añadido a `PipelineTrace`

### H1: TimingContext + instrumentación del Director — ✅ Cumplido

**Estado:** `TimingContext` implementado en `src/diana/cognitive/timing.py`; `_run_pipeline()` del Director envuelve los pasos con `TimingContext` y acumula las keys de timings (`src/diana/cognitive/director.py`).

**Nuevo archivo** `cognitive/timing.py`:
```python
class TimingContext:
    def __enter__(self): ...
    def __exit__(self, *args): ...
    # expone elapsed_ms después de salir
```

**Modificado** `cognitive/director.py` — `_run_pipeline()`:
- Cada paso (analyst, planner, retrievers loop, context_builder, generator, evaluator, decider) se envuelve con `TimingContext`
- Se acumulan timings dict con keys: `analyst_ms`, `planner_ms`, `memory_retriever_ms`, `policy_retriever_ms`, `examples_retriever_ms`, `context_builder_ms`, `generator_ms`, `evaluator_ms`, `decider_ms`, `total_ms`
- Si un paso no se ejecuta (stub/null) → `null` o no incluir la key
- Al final del pipeline, se almacena con `await self._store("timings", timings)`
- **Importante**: `"timings": "timings"` añadido al dict `TRACE_KEY_TO_COLUMN` en `infrastructure/db/repositories/traces.py` para que `store()` sepa mapear la key a la columna ORM

### H2: AdminTraceService + repositorio extendido — ✅ Cumplido

**Estado:** `AdminTraceService` con DTOs `TurnSummary`/`FullTrace` implementado en `src/diana/application/admin_trace_service.py`; repositorio `SqlTraceStore` extendido con `get_recent_turns`/`get_full_trace`/`count_recent` (`src/diana/infrastructure/db/repositories/traces.py`); protocolo `TraceabilityReader` en `application/ports.py`.

**Nuevo archivo** `application/admin_trace_service.py`:
- `TurnSummary` DTO: turn_id, chat_id, vip_name, message_preview (primeros 50 chars del mensaje), decision, status, created_at, correction_applied
- `FullTrace` DTO: turn_id, chat_id, vip_id, created_at, comprehension, plan, retrieved, prompt_text, generated_text, evaluation, decision, delivery_result, timings, error, status
- `AdminTraceService` con:
  - `get_recent_turns(limit=10, offset=0) -> list[TurnSummary]`
  - `get_full_trace(turn_id) -> FullTrace | None`
  - `get_turn_count() -> int` (para paginación)
  - `export_trace_json(turn_id) -> str` (H9 del spec, implementado)

**Extendido** `infrastructure/db/repositories/traces.py`:
- `get_recent_turns(limit, offset)` — query que joinea `pipeline_traces` con `turns` (para status) y `vips` (para display_name), filtra por `trace_ttl_days`, ordena por `created_at DESC`
- `get_full_trace(turn_id)` — carga todas las columnas de una fila de `pipeline_traces` + `turns.status` + `turns.error`
- `count_recent()` — count con filtro TTL

**Nuevo protocolo** en `application/ports.py`:
- `TraceabilityReader` con `get_recent_turns()`, `get_full_trace()`, `count_recent()`

### H3: Comandos /turnos y /traza en el handler de admin — ✅ Cumplido

**Estado:** Comandos `Command("turnos")` y `Command("traza")` registrados en `telegram/handlers/admin.py` (DM del Director).

**Modificado** `telegram/handlers/admin.py`:
- Handler para comando `/turnos`: llama a `admin_trace.render_turns_page(...)`, formatea mensaje con lista numerada, envía con teclado de paginación
- Handler para comando `/traza <turn_id>`: parsea el ID (soporta UUID completo o abreviado de 8 chars), llama a `get_full_trace()`, envía mensaje resumen con teclado de pasos
- El texto del mensaje `/traza` sigue el formato del spec (sección 5.2): mensaje original, borrador generado, decisión, tiempo total, lista de pasos con duración y estado

### H4: Keyboards de trazabilidad + botón "Ver traza" — ✅ Cumplido

**Estado:** `trace_list_keyboard`, `trace_detail_keyboard`, `step_detail_keyboard` y helpers de callback `encode_trace_*`/`parse_trace_callback` implementados en `telegram/keyboards.py`; `draft_keyboard` incluye el botón "Ver traza" (callback `vt` desde draft).

**Modificado** `telegram/keyboards.py`:

Nuevas funciones:
- `trace_list_keyboard(turns, page, total_pages)` — paginación ◀/▶ + botones "Ver traza" por cada turno (máx 10)
- `trace_detail_keyboard(turn_id)` — botones "Ver detalles" para cada paso + "Exportar JSON" + "Volver a turnos"
- `step_detail_keyboard(turn_id, step_name)` — botón "Volver a la traza"

Modificado existente:
- `draft_keyboard(turn_id)` — 4to botón "🔍 Ver traza" con callback `vt:{turn_id}`

Nuevos action codes (siguiendo el patrón de 1-2 chars):
- `vt` = ver traza (desde approval o lista)
- `td` = trace detail (ver detalle de un paso específico)
- `tp` = trace page (paginación)
- `tj` = trace JSON export

### H5: Callback handlers para trazabilidad — ✅ Cumplido

**Estado:** `dispatch_owner_callback()` en `telegram/handlers/callbacks.py` despacha los callbacks de traza (`vt`/`vtd`/`td`/`tdd`/`tp`/`tj`/`tb`).

**Modificado** `telegram/handlers/callbacks.py`:
- `dispatch_owner_callback()` extendido con los casos `vt`, `vtd`, `td`, `tdd`, `tp`, `tj`, `tb`
- `vt`/`vtd` (ver traza, desde approval o lista): llama a `admin_trace.get_full_trace(turn_id)`, envía mensaje resumen con `trace_detail_keyboard`
- `td`/`tdd` (trace detail): extrae step_name del callback data, muestra entrada/salida de ese paso en mensaje aparte con `step_detail_keyboard`
- `tp` (paginación): llama a `get_recent_turns(limit=10, offset=page*10)`, edita el mensaje original con nueva página
- `tj` (JSON export): llama a `export_trace_json()`, envía como documento o mensaje de texto
- `tb` (volver al borrador): regresa a la vista de aprobación del draft

### H6: Wiring en composition.py — ✅ Cumplido

**Estado:** `AdminTraceService` instanciado e inyectado en el admin router y el callback dispatcher (`src/diana/composition.py`).

- Se instancia `AdminTraceService` con dependencias: `SqlTraceStore` (extendido), `settings.trace_ttl_days`
- Se inyecta en el admin router (pasado a `build_admin_router()`)
- Se inyecta en el callback dispatcher

### H7: Tests — ✅ Cumplido

**Estado:** Los tests del plan existen: `tests/unit/cognitive/test_timing.py`, `tests/unit/application/test_admin_trace_service.py`, `tests/unit/telegram/test_trace_keyboards.py`, `tests/unit/telegram/test_trace_callbacks.py`.

**Nuevos archivos:**
- `tests/unit/cognitive/test_timing.py` — TimingContext comportamiento básico
- `tests/unit/application/test_admin_trace_service.py` — get_recent_turns, get_full_trace con mocks
- `tests/unit/telegram/test_trace_keyboards.py` — encode/decode de nuevos callbacks
- `tests/unit/telegram/test_trace_callbacks.py` — dispatch de vt/td/tp/tj

## Orden de implementación

```
H0 (migración + modelo) → H1 (timing) → H2 (servicio + repo)
  → H4 (keyboards) → H3 (comandos) → H5 (callbacks)
  → H6 (wiring) → H7 (tests)
```

El orden se ejecutó tal cual; H3, H4, H5 se solaparon en la misma capa de Telegram, y H0-H2 fueron bloqueantes.

## Archivos clave (referencia rápida)

| Archivo | Tipo | Cambio |
|---------|------|--------|
| `alembic/versions/005_trace_timings.py` | Nuevo | Migración timings + índice |
| `src/diana/infrastructure/db/models.py` | Modificar | Añadir columna timings a PipelineTrace |
| `src/diana/infrastructure/db/repositories/traces.py` | Modificar | get_recent_turns, get_full_trace, count_recent |
| `src/diana/cognitive/timing.py` | Nuevo | TimingContext |
| `src/diana/cognitive/director.py` | Modificar | Instrumentar 8 pasos con TimingContext |
| `src/diana/application/admin_trace_service.py` | Nuevo | AdminTraceService + DTOs |
| `src/diana/application/ports.py` | Modificar | TraceabilityReader protocol |
| `src/diana/telegram/keyboards.py` | Modificar | Nuevos keyboards + "Ver traza" en draft |
| `src/diana/telegram/handlers/admin.py` | Modificar | Comandos /turnos, /traza |
| `src/diana/telegram/handlers/callbacks.py` | Modificar | Dispatch vt/td/tp/tj |
| `src/diana/composition.py` | Modificar | Wiring AdminTraceService |

## Verificación

> Checklist aplicado durante la implementación. El sistema quedó implementado y desplegado.

1. **Migración**: `alembic upgrade head` añade la columna sin errores
2. **Tests existentes**: `pytest tests/ -x` — todos los tests F1/F2 pasan (el sistema de trazabilidad es read-only, no modifica comportamiento)
3. **Timing**: un turno ejecutado registra en `pipeline_traces.timings` las keys esperadas con valores > 0
4. **Comandos**: en el DM del admin, `/turnos` lista turnos recientes, `/traza <id>` muestra la traza completa con botones de detalle
5. **Navegación**: botones de paginación funcionan, "Ver detalles" muestra entrada/salida de cada paso, "Volver" regresa al resumen
6. **Botón en aprobación**: el mensaje de borrador incluye "🔍 Ver traza" y al clickearlo muestra la traza de ese turno
7. **Auth**: los comandos solo responden al admin configurado (middleware existente)
8. **TTL**: turnos fuera del TTL configurado no aparecen en `/turnos`
