# Spec de implementación — Feedback de calidad + fix zona gris (DianaV2) — v1.0

**Objetivo:** (1) cerrar una laguna real detectada en auditoría externa donde un VIP puede quedar congelado hasta 24h sin resolución si falla la notificación de zona gris; (2) dar a la dueña dos palancas de feedback más allá de Aprobar/Corregir — **destacar** una respuesta excepcional y **reprender** una respuesta que no debe repetirse, con severidad elegible caso por caso.

**Principio guía (heredado de AGENTS.md / SPEC-EVOLUCION-AGENTE):** cada pieza nueva debe poder activarse/desactivarse por feature flag y dejar traza auditable. Nada se libera sin poder revertirse.

**Contexto de auditoría:** este spec nace de una revisión externa de `turn_orchestrator.py` (2026-08-15) y de una sesión de diseño posterior sobre el sistema de aprendizaje. Antes de implementar, leer `AGENTS.md` completo — este documento no repite los límites de módulo ya definidos ahí, solo los referencia.

---

## Fase 0 — Fix crítico: notify failure en zona gris (path VIP) — HACER PRIMERO, AISLADO

### El bug

En `src/diana/application/turn_orchestrator.py`, método `_apply_decision_after_director`, rama `decision.action == "consult_doctrine"`:

- **Rama atención general** (channel_type == "atencion", ~línea 2122-2170) envuelve `send_doctrine_query` en un `try/except`: si falla el envío del DM al owner, hace `discard_and_close(query.id)` (descongela al VIP — confirmado en `gray_zone_service.py:195-220`) y degrada la decisión a `approve` con `reason="atencion_doctrine_notify_failed"`, transicionando a `PENDING_APPROVAL` y reenviando el borrador. Tiene test dedicado: `tests/unit/application/test_turn_orchestrator.py:2846` (`"F6: doctrine notify failure discards the query and demotes to approve."`).
- **Rama VIP normal** (~línea 2216-2243, el flujo principal del bot) **NO tiene ese `try/except`**. `GrayZoneService.create_query()` congela al VIP **primero** (hasta `default_timeout_hours=24`, ver `gray_zone_service.py:72-76`) y luego inserta la query. Si `send_doctrine_query` falla después de eso (hiccup de Telegram, owner bloqueó al bot, blip de red), la excepción se propaga sin capturar: el turno nunca transiciona a `GRAY_ZONE`, no hay DM con la pregunta, y el VIP queda **congelado hasta 24h** sin que la dueña se entere. El único paracaídas es `GrayZoneExpirationJob` (corre cada 5 min pero solo actúa cuando expira el freeze completo — ver `jobs/gray_zone_expiration.py`).
- No existe test que cubra `send_doctrine_query` lanzando excepción en el path VIP (`grep send_doctrine_query tests/` solo encuentra el caso feliz en `test_turn_orchestrator.py:2905`).

### El fix

Aplicar **exactamente el mismo patrón F6** a la rama VIP. En el bloque `else:` de `_apply_decision_after_director` (consult_doctrine, path VIP):

```python
query = await self._gray_zone.create_query(
    vip_id=turn_ctx.vip_id,
    turn_id=turn_id,
    question=turn_ctx.text,
    draft=decision.draft_text or "",
    chat_id=turn_ctx.chat_id,
    business_connection_id=turn_ctx.business_connection_id,
)
try:
    await self._admin.send_doctrine_query(
        turn_ctx, decision, turn_id, query
    )
except Exception:
    # Mismo patrón F6 de la rama atención: una notificación fallida no debe
    # dejar al VIP congelado sin que la dueña se entere.
    try:
        await self._gray_zone.discard_and_close(query.id)
    except Exception:
        log_swallowed(
            logger,
            "vip_doctrine_discard_failed",
            turn_id=str(turn_id),
            vip_id=str(turn_ctx.vip_id),
            query_id=str(query.id) if hasattr(query, "id") else None,
        )
    demoted = decision.model_copy(
        update={"action": "approve", "reason": "vip_doctrine_notify_failed"}
    )
    await self._coordinator.transition(turn_id, TurnStatus.PENDING_APPROVAL)
    await self._admin.send_draft_for_approval(turn_ctx, demoted, turn_id)
    logger.warning(
        "vip_doctrine_notify_failed",
        extra={
            "turn_id": str(turn_id),
            "vip_id": str(turn_ctx.vip_id),
            "query_id": str(query.id) if hasattr(query, "id") else None,
        },
    )
    return  # o el patrón de retorno que use el resto del método en este bloque
await self._coordinator.transition(turn_id, TurnStatus.GRAY_ZONE)
logger.info("consult_doctrine_completed", extra={...})  # sin cambios
```

**Detalle de implementación:** revisar cómo termina el bloque `elif`/`else` actual (qué retorna la función después de este bloque) para que el `return`/flujo después del `except` sea consistente con el resto del método — no asumir un `return` explícito si el método usa otro mecanismo de salida (p.ej. cae al final de la función). Mirar cómo lo resuelve la rama atención inmediatamente después de su bloque `except` para copiar el mismo estilo de control de flujo.

### Test a agregar

En `tests/unit/application/test_turn_orchestrator.py`, junto al test F6 existente (línea ~2846), un test hermano para el path VIP:
- Mock de `admin.send_doctrine_query` que lanza excepción.
- Verificar: `gray_zone.discard_and_close` fue llamado con el `query.id` correcto, el turno terminó en `PENDING_APPROVAL` (no en `GRAY_ZONE`), `admin.send_draft_for_approval` fue llamado con `reason="vip_doctrine_notify_failed"`, y — el más importante — que el VIP **no** queda con `frozen_until` en el futuro (verificar vía el fake de `VipStore`/`GrayZoneService` que el freeze se limpió).

### Criterio de salida

Fix aplicado, test nuevo en verde, suite completa sigue en verde (`pytest tests/unit/application/test_turn_orchestrator.py`). Esta fase es independiente de todo lo demás en este documento — se puede mergear sola.

---

## Decisiones de diseño aprobadas — Feedback de calidad (FB-01..FB-06)

| ID | Decisión | Alcance |
|---|---|---|
| **FB-01** | Dos mecanismos con fuerza distinta para la reprimenda: **política dura** (regla siempre consultada por el Decider, vía `promote_to_policy` ya existente) o **counter-example de alto peso** (ejemplo negativo en retrieval). La dueña elige caso por caso en el momento de reprender — no hay heurística automática que decida por ella. | Reprimenda |
| **FB-02** | Los ejemplos `quality='gold'` se priorizan en el retrieval de forma **no probabilística**: si existe un match `gold` sobre el umbral de similitud, siempre se incluye, independientemente de si hay ejemplos `standard` más similares. | Retrieval |
| **FB-03** | Los counter-examples dejan de muestrearse al 10% (`counter_example_chance` actual en `ExamplesRetriever` — confirmado que hoy es código muerto porque nada escribe `is_counter_example=True`). A partir de esta spec, todo counter-example nace de una reprimenda deliberada, así que se incluye **determinísticamente** cuando hay match sobre el umbral. | Retrieval |
| **FB-04** | Alcance dual (global vs VIP específico) para ambos ejes — ejemplos y políticas — vía columna `vip_id UUID NULL` nueva en ambas tablas (`examples`, `policies`). `NULL` = global. **No reutilizar la columna `scope` existente de `Policy`**: hoy `scope` codifica el eje canal (`"all"` vs canal VIP sin filtrar — ver `cognitive/retrievers/policy.py:132-139`), y mezclar semánticas rompería el filtrado de atención. `vip_id` es un filtro adicional, independiente de `scope`. | Esquema |
| **FB-05** | "Destacar" y "Reprender" promueven **de inmediato**, sin pasar por la cola de revisión de `staging_candidates` que hoy usa `Corregir` (esa cola sigue existiendo tal cual para correcciones normales sin flag). La razón: la dueña ya tomó la decisión activamente al tocar el botón — pedirle confirmar dos veces es fricción sin valor. | UX |
| **FB-06** | Todo detrás de `FEATURE_QUALITY_FEEDBACK_ENABLED` (default `false`). Con el flag apagado, los botones ⭐/🚫 no aparecen y el comportamiento actual (Aprobar/Corregir/Escalar) queda intacto. | Global |

---

## Fase 1 — Esquema de datos

**Migración Alembic 027** (head actual es 026 — confirmado en `alembic/versions/`):

- `examples`: agregar `quality VARCHAR NOT NULL DEFAULT 'standard'` (valores válidos: `'standard'`, `'gold'` — validar en el repo, no con `CHECK` de DB para mantener el estilo del resto del esquema) y `vip_id UUID NULL REFERENCES vips(id)` con índice (`ix_examples_vip_id`).
- `policies`: agregar `vip_id UUID NULL REFERENCES vips(id)` con índice (`ix_policies_vip_id`). **No tocar la columna `scope` existente.**
- Confirmar el nombre real de la tabla de VIPs (probablemente `vips`, verificar en `infrastructure/db/models.py` antes de escribir el FK) y el tipo exacto de PK (UUID) para que el FK sea consistente con el resto de las migraciones que referencian `vips.id`.

**Criterio de salida:** migración aplica y revierte limpio (`alembic upgrade head` / `alembic downgrade -1`), sin cambio de comportamiento visible todavía.

---

## Fase 2 — Backend: repos y servicios

### `infrastructure/db/repositories/examples.py`

- `insert(...)`: agregar parámetros `quality: str = "standard"`, `vip_id: UUID | None = None`.
- `find_by_similarity(...)`: agregar parámetro `vip_id: UUID | None = None`. Filtro adicional: `(Example.vip_id.is_(None)) | (Example.vip_id == vip_id)`. Orden: primero por `quality == 'gold'` descendente, luego por similitud (coseno) — es decir, un gold relevante nunca debería perder su lugar frente a varios standard más parecidos dentro del límite de resultados.

### `infrastructure/db/repositories/policies.py`

- `insert(...)`: agregar parámetro `vip_id: UUID | None = None`.
- `find_active_by_similarity(...)`: agregar parámetro `vip_id: UUID | None = None`, con el mismo filtro adicional `(Policy.vip_id.is_(None)) | (Policy.vip_id == vip_id)` — **en AND con el filtro de `scope` existente, no en su lugar**.
- `policy_to_dict`: incluir `vip_id` en el dict de salida.

### `cognitive/retrievers/policy.py` y `cognitive/retrievers/examples.py`

- Ambos retrievers ya reciben el `turn_ctx`/contexto del turno con `vip_id` disponible (confirmar el nombre exacto del campo en cada retriever) — pasarlo a la llamada del repo correspondiente. Para turnos de canal `atencion` (`vip_id is None` en el turno), el filtro simplemente no excluye nada adicional (comportamiento actual preservado).

### `cognitive/retrievers/examples.py` — eliminar el muestreo aleatorio

- Quitar la lógica de `counter_example_chance` (10%). Reemplazar por: siempre intentar `find_by_similarity(..., is_counter_example=True)` (o el parámetro equivalente ya existente) y, si hay match sobre el umbral, incluirlo en el contexto del Generador. Revisar tests existentes que dependan del muestreo aleatorio (mock de `random`) — probablemente haya que eliminarlos o adaptarlos, ya que el comportamiento pasa a ser determinístico.

### `application/staging_service.py`

Dos métodos nuevos, hermanos de `promote_to_example`/`promote_to_policy` (mismo manejo de errores: `ValueError` si no existe o no está `pending`):

```python
async def promote_to_counter_example(
    self,
    candidate_id: UUID,
    *,
    vip_id: UUID | None = None,
) -> object:
    """Como promote_to_example pero is_counter_example=True y vip_id opcional.
    Mantiene el bloqueo anti-contaminación de atención (REQ-ATN-13) igual
    que promote_to_example — copiar esa validación tal cual."""
```

`promote_to_policy` ya acepta todo lo necesario (`trigger`, `rule`, `scope`) — solo agregarle el parámetro `vip_id: UUID | None = None` y pasarlo al `insert()` del repo.

### `application/admin_service.py`

Dos métodos nuevos:

```python
async def handle_mark_gold(
    self,
    turn_id: UUID,
    *,
    scope: Literal["global", "vip"],
    actor_id: int,
) -> object | None:
    """Aprueba y entrega igual que handle_approve (reusar su lógica interna
    o llamarlo directamente), y además inserta un Example con quality='gold'
    usando el draft ya aprobado como corrected_text/draft_text (sin corrección
    real: draft_text == corrected_text). vip_id = turn.vip_id si scope=='vip',
    None si scope=='global'."""

async def handle_reprimand(
    self,
    turn_id: UUID,
    corrected_text: str,
    *,
    mode: Literal["policy", "counter_example"],
    scope: Literal["global", "vip"],
    actor_id: int,
) -> object | None:
    """Llama a handle_correct(turn_id, corrected_text, actor_id=actor_id) para
    resolver y entregar la corrección (comportamiento ya probado, no
    reimplementar). Después, según `mode`:
      - 'counter_example': promote_to_counter_example sobre el candidato recién
        creado por handle_correct, con vip_id según scope.
      - 'policy': promote_to_policy con trigger autogenerado a partir del texto
        del VIP en el turno (truncado/resumido) y rule = corrected_text,
        vip_id según scope. El trigger autogenerado debe quedar editable
        después vía el flujo de administración de políticas existente
        (confirmar cuál es — revisar menu 'personalidad' > 'Políticas de
        conducta' en telegram/keyboards.py) — no bloquear esta fase si esa
        edición posterior no existe todavía; documentarlo como seguido
        pendiente si es el caso."""
```

**Nota importante:** `handle_correct` ya inserta el candidato en `staging_candidates` con `status='pending'`. Para promover de inmediato (FB-05) hay que obtener el `candidate_id` que generó esa llamada — revisar la firma de retorno de `handle_correct` (el spec de arriba menciona `result.success`/`result.cancelled`; confirmar si expone el `candidate_id` o si hay que agregar ese campo al objeto de retorno para no tener que volver a consultar la tabla).

**Criterio de salida de Fase 1+2:** tests unitarios de repos (con fakes, sin DB real) y de `AdminService`/`StagingService` en verde. Sin cambios de UI todavía — se puede probar todo por test directo a los métodos nuevos.

---

## Fase 3 — Telegram: botones y flujo de captura

### `telegram/keyboards.py`

Dos códigos de callback nuevos, siguiendo el patrón `≤64 bytes` ya usado (`_ACTION_APPROVE = "a"`, etc.):

```python
_ACTION_GOLD = "gd"       # gd:<turn_id>
_ACTION_REPRIMAND = "rp"  # rp:<turn_id> — arranca sesión de texto libre, como "c"
```

Y códigos combo para las decisiones post-texto (mode × scope), ejemplo de esquema (verificar que quepan en 64 bytes — un UUID son 36 caracteres, sobra margen de sobra):

```
rpc:<turn_id>:pol:g   → reprimand confirm, policy, global
rpc:<turn_id>:pol:v   → reprimand confirm, policy, vip
rpc:<turn_id>:ex:g    → reprimand confirm, counter_example, global
rpc:<turn_id>:ex:v    → reprimand confirm, counter_example, vip
gdc:<turn_id>:g       → gold confirm, global
gdc:<turn_id>:v       → gold confirm, vip
```

`draft_keyboard(turn_id, chat_id)` (la función que arma el teclado de aprobación): agregar una fila nueva **solo si `FEATURE_QUALITY_FEEDBACK_ENABLED`** (el flag se resuelve en el caller, no dentro de `keyboards.py` — revisar cómo el resto del código gatea UI por flag, probablemente pasando un booleano a la función de construcción del teclado, como ya hace `menu_root_keyboard(show_persona=False)`):

```
[⭐ Destacar]   [🚫 Reprender]
```

Después de tocar ⭐: teclado de 2 botones `[🌍 General] [👤 Este VIP]` (`gdc:...`).
Después de escribir el texto de reprimenda: teclado de 4 botones en 2 filas (`rpc:...`), como se describió en la sesión de diseño previa.

### `telegram/handlers/callbacks.py`

- `CorrectSessionStore`: agregar un campo `mode: Literal["correct", "reprimand"] = "correct"` al tuple guardado en `_awaiting` (hoy es `(turn_id, datetime)` — pasa a `(turn_id, datetime, mode)`). `start()` acepta `mode` opcional. Esto evita crear una segunda clase de sesión paralela — reprender reusa toda la mecánica de TTL/expiración/cancel-by-turn ya probada.
- En `on_callback`: manejar `action == "gd"` (llama `admin.handle_mark_gold` con un scope temporal por defecto y muestra el teclado de confirmación de alcance — o, más simple, mostrar directo el teclado de 2 botones sin llamar a nada todavía, y resolver `handle_mark_gold` solo al tocar `gdc:...`). Preferir esta segunda opción: **no aprobar hasta que se confirme el alcance**, para no entregar el mensaje y luego no saber si el owner se arrepintió del "destacar" — aunque aprobar es idempotente y de bajo riesgo, mantiene la semántica de "una acción, un resultado" más limpia.
- Manejar `action == "rp"` igual que `"correct"` hoy pero con `sessions.start(actor_id, turn_id, mode="reprimand")`.
- Manejar los callbacks `rpc:` y `gdc:` (parsearlos con una función nueva `parse_reprimand_confirm`/`parse_gold_confirm` en `keyboards.py`, siguiendo el estilo de `parse_staging_callback`).

### `telegram/handlers/admin.py`

- `handle_admin_text`: en el bloque que resuelve `correct_sessions.resolve(actor_id)` (línea ~309-335), leer también el `mode` de la sesión. Si `mode == "reprimand"`, en vez de llamar `admin.handle_correct` directo y cerrar, guardar el texto capturado en un estado intermedio (puede ser el mismo `CorrectSessionStore` u otro pequeño store en memoria, siguiendo el patrón `DoctrineSessionStore`) y devolver el teclado de 4 opciones en vez de cerrar la sesión — la promoción real (`handle_reprimand`) se dispara recién cuando el owner toca uno de los 4 botones `rpc:...`.

**Nota de diseño para quien implemente:** esto añade un tercer "salto" de estado (texto libre → elegir combo → ejecutar) que no existe hoy en ningún flujo del bot. Vale la pena mirar cómo `DoctrineSessionStore` maneja algo parecido (captura de texto libre seguida de una acción posterior) antes de inventar un mecanismo nuevo — puede que ya resuelva el 80% del problema.

**Criterio de salida:** flujo completo probado manualmente en sandbox (`/sandbox on`, revisar `SandboxService`) más tests de integración de `callbacks.py`/`admin.py` en verde.

---

## Fase 4 — Fuera de alcance en esta versión (explícito, no implementar)

- Marcar dorado/reprimenda de forma retroactiva sobre historial ya entregado (vía `/traza`) — descartado en la sesión de diseño.
- Enganchar el reprimand al `vip_trust_budget` del Evo-Agente (bajarle confianza a la categoría del turno) — mencionado como posible extensión futura de una línea, no bloquea esta spec.
- UI para editar manualmente el `trigger`/`rule` autogenerado de una política creada por reprimenda — si el flujo de administración de políticas ya soporta editar políticas existentes, no hace falta nada nuevo; si no, queda como seguido pendiente (documentar en `faltantes.md`, no en este spec).

---

## Orden de ejecución sugerido

Fase 0 (fix, aislado, mergeable solo) → Fase 1 (migración) → Fase 2 (backend, testeable sin UI) → Fase 3 (Telegram) → validar en sandbox con el flag encendido → activar `FEATURE_QUALITY_FEEDBACK_ENABLED` en producción.

Cada fase debe dejar la suite de tests en verde antes de pasar a la siguiente — no acumular fases sin correr `pytest` completo, dado el tamaño del archivo `turn_orchestrator.py` (2576 líneas) y la cantidad de invariantes de concurrencia que ya dependen de él.
