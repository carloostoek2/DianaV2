# Plan: Sistema de Trazabilidad Interactiva (Anexo T)

## Context

La dueña necesita inspeccionar el paso a paso de cualquier turno desde su DM de Telegram: qué decidió cada nodo cognitivo, cuánto tardó, y si hubo errores. Toda la información ya se persiste en `pipeline_traces` — solo falta exponerla. Es un sistema read-only, no intrusivo, que corre en paralelo a Fase 2 sin modificar el pipeline cognitivo.

## Arquitectura de cambios

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

### H0: Migración + modelo

**Migración** `alembic/versions/005_trace_timings.py`:
```sql
ALTER TABLE pipeline_traces ADD COLUMN timings JSONB DEFAULT '{}'::jsonb;
CREATE INDEX CONCURRENTLY IF NOT EXISTS pipeline_traces_created_at_idx
  ON pipeline_traces (created_at DESC);
```

**Modelo** en `infrastructure/db/models.py`:
- Añadir `timings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)` a `PipelineTrace`

### H1: TimingContext + instrumentación del Director

**Nuevo archivo** `cognitive/timing.py`:
```python
class TimingContext:
    def __enter__(self): ...
    def __exit__(self, *args): ...
    # expone elapsed_ms después de salir
```

**Modificar** `cognitive/director.py` — `_run_pipeline()`:
- Envolver cada paso (analyst, planner, retrievers loop, context_builder, generator, evaluator, decider) con `TimingContext`
- Acumular timings dict con keys: `analyst_ms`, `planner_ms`, `memory_retriever_ms`, `policy_retriever_ms`, `examples_retriever_ms`, `context_builder_ms`, `generator_ms`, `evaluator_ms`, `decider_ms`, `total_ms`
- Si un paso no se ejecuta (stub/null) → `null` o no incluir la key
- Al final del pipeline, almacenar con `await self._store("timings", timings)`
- **Importante**: Añadir `"timings": "timings"` al dict `TRACE_KEY_TO_COLUMN` en `infrastructure/db/repositories/traces.py` para que `store()` sepa mapear la key a la columna ORM

### H2: AdminTraceService + repositorio extendido

**Nuevo archivo** `application/admin_trace_service.py`:
- `TurnSummary` DTO: turn_id, chat_id, vip_name, message_preview (primeros 50 chars del mensaje), decision, status, created_at, correction_applied
- `FullTrace` DTO: turn_id, chat_id, vip_id, created_at, comprehension, plan, retrieved, prompt_text, generated_text, evaluation, decision, delivery_result, timings, error, status
- `AdminTraceService` con:
  - `get_recent_turns(limit=10, offset=0) -> list[TurnSummary]`
  - `get_full_trace(turn_id) -> FullTrace | None`
  - `get_turn_count() -> int` (para paginación)
  - `export_trace_json(turn_id) -> str` (opcional, H9 del spec)

**Extender** `infrastructure/db/repositories/traces.py`:
- Añadir `get_recent_turns(limit, offset)` — query que joinea `pipeline_traces` con `turns` (para status) y `vips` (para display_name), filtra por `trace_ttl_days`, ordena por `created_at DESC`
- Añadir `get_full_trace(turn_id)` — carga todas las columnas de una fila de `pipeline_traces` + `turns.status` + `turns.error`
- Añadir `count_recent()` — count con filtro TTL

**Nuevo protocolo** en `application/ports.py`:
- `TraceabilityReader` con `get_recent_turns()`, `get_full_trace()`, `count_recent()`

### H3: Comandos /turnos y /traza en el handler de admin

**Modificar** `telegram/handlers/admin.py`:
- Añadir handler para comando `/turnos`: llama a `admin_trace.get_recent_turns(limit=10)`, formatea mensaje con lista numerada, envía con teclado de paginación
- Añadir handler para comando `/traza <turn_id>`: parsea el ID (soporta UUID completo o abreviado de 8 chars), llama a `get_full_trace()`, envía mensaje resumen con teclado de pasos
- El texto del mensaje `/traza` sigue exactamente el formato del spec (sección 5.2): mensaje original, borrador generado, decisión, tiempo total, lista de pasos con duración y estado

### H4: Keyboards de trazabilidad + botón "Ver traza"

**Modificar** `telegram/keyboards.py`:

Nuevas funciones:
- `trace_list_keyboard(turns, page, total_pages)` — paginación ◀/▶ + botones "Ver traza" por cada turno (máx 10)
- `trace_detail_keyboard(turn_id)` — botones "Ver detalles" para cada paso + "Exportar JSON" + "Volver a turnos"
- `step_detail_keyboard(turn_id, step_name)` — botón "Volver a la traza"

Modificar existente:
- `draft_keyboard(turn_id)` — añadir 4to botón "🔍 Ver traza" con callback `vt:{turn_id}`

Nuevos action codes (siguiendo el patrón de 1-2 chars):
- `vt` = ver traza (desde approval o lista)
- `td` = trace detail (ver detalle de un paso específico)
- `tp` = trace page (paginación)
- `tj` = trace JSON export

### H5: Callback handlers para trazabilidad

**Modificar** `telegram/handlers/callbacks.py`:
- Extender `dispatch_owner_callback()` con nuevos casos: `vt`, `td`, `tp`, `tj`
- `vt` (ver traza): llama a `admin_trace.get_full_trace(turn_id)`, envía mensaje resumen con `trace_detail_keyboard`
- `td` (trace detail): extrae step_name del callback data, muestra entrada/salida de ese paso en mensaje aparte con `step_detail_keyboard`
- `tp` (paginación): llama a `get_recent_turns(limit=10, offset=page*10)`, edita el mensaje original con nueva página
- `tj` (JSON export): llama a `export_trace_json()`, envía como documento o mensaje de texto

### H6: Wiring en composition.py

- Instanciar `AdminTraceService` con dependencias: `SqlTraceStore` (extendido), `settings.trace_ttl_days`
- Inyectar en el admin router (pasarlo a `build_admin_router()`)
- Inyectar en el callback dispatcher

### H7: Tests

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

H3, H4, H5 pueden solaparse porque comparten la misma capa de Telegram. H0-H2 son bloqueantes.

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

1. **Migración**: `alembic upgrade head` añade la columna sin errores
2. **Tests existentes**: `pytest tests/ -x` — todos los tests F1/F2 pasan (el sistema de trazabilidad es read-only, no modifica comportamiento)
3. **Timing**: Ejecutar un turno y verificar que `pipeline_traces.timings` contiene las keys esperadas con valores > 0
4. **Comandos**: En el DM del admin, `/turnos` lista turnos recientes, `/traza <id>` muestra la traza completa con botones de detalle
5. **Navegación**: Botones de paginación funcionan, "Ver detalles" muestra entrada/salida de cada paso, "Volver" regresa al resumen
6. **Botón en aprobación**: El mensaje de borrador incluye "🔍 Ver traza" y al clickearlo muestra la traza de ese turno
7. **Auth**: Los comandos solo responden al admin configurado (middleware existente)
8. **TTL**: Turnos fuera del TTL configurado no aparecen en `/turnos`
