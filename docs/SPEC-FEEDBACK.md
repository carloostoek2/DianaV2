# Spec de implementación — Feedback de calidad + fix zona gris (DianaV2) — v1.0

**Estado (2026-08-21):** implementado y activo en `main`. `FEATURE_QUALITY_FEEDBACK_ENABLED=true` en `.env` (`docs/ARCHITECTURE.md` §4), por lo que Destacar/Reprender están operativos en los borradores VIP y el fix de zona gris (paracaídas VIP) está aplicado. Desvíos vs este texto de diseño: migración **029** `feedback_quality` (no 027); Reprender **entrega al instante** y el combo es solo promoción; botones solo en borradores VIP; labels sin emoji; el canal `atencion` no puede promover (`AtencionPromoteBlocked` en `admin_service.py`). El flujo operativo está descrito en `docs/ARCHITECTURE.md` §3 ("Feedback Destacar / Reprender", "Paracaídas de zona gris") y §5 (migración 029). El detalle de producto está en `docs/UX.md`.

**Objetivo:** (1) cerrar una laguna real detectada en auditoría externa donde un VIP puede quedar congelado hasta 24h sin resolución si falla la notificación de zona gris; (2) dar a la dueña dos palancas de feedback más allá de Aprobar/Corregir — **destacar** una respuesta excepcional y **reprender** una respuesta que no debe repetirse, con severidad elegible caso por caso.

**Principio guía (heredado de AGENTS.md / SPEC-EVOLUCION-AGENTE):** cada pieza nueva debe poder activarse/desactivarse por feature flag y dejar traza auditable. Nada se libera sin poder revertirse.

**Contexto de auditoría:** este spec nació de una revisión externa de `turn_orchestrator.py` (2026-08-15) y de una sesión de diseño posterior sobre el sistema de aprendizaje. Antes de implementar, leer `AGENTS.md` completo — este documento no repite los límites de módulo ya definidos ahí, solo los referencia.

---

## Fix aplicado — notify failure en zona gris (path VIP)

### El bug (corregido)

En `src/diana/application/turn_orchestrator.py`, método `_apply_decision_after_director`, rama `decision.action == "consult_doctrine"`:

- **Rama atención general** (channel_type == "atencion") envuelve `send_doctrine_query` en un `try/except`: si falla el envío del DM al owner, hace `discard_and_close(query.id)` (descongela al VIP — confirmado en `gray_zone_service.py`) y degrada la decisión a `approve` con `reason="atencion_doctrine_notify_failed"`, transicionando a `PENDING_APPROVAL` y reenviando el borrador. Tenía test dedicado: `tests/unit/application/test_turn_orchestrator.py` (`"F6: doctrine notify failure discards the query and demotes to approve."`).
- **Rama VIP normal** (el flujo principal del bot) **no tenía ese `try/except`**. `GrayZoneService.create_query()` congela al VIP **primero** (hasta `default_timeout_hours=24`) y luego inserta la query. Si `send_doctrine_query` fallaba después de eso (hiccup de Telegram, owner bloqueó al bot, blip de red), la excepción se propagaba sin capturar: el turno nunca transicionaba a `GRAY_ZONE`, no había DM con la pregunta, y el VIP quedaba **congelado hasta 24h** sin que la dueña se enterara. El único paracaídas era `GrayZoneExpirationJob` (corre cada 5 min pero solo actúa cuando expira el freeze completo).

### El fix aplicado

Se aplicó **exactamente el mismo patrón F6** a la rama VIP, copiando el mismo estilo de control de flujo que usa la rama atención inmediatamente después de su bloque `except`. En el bloque `else:` de `_apply_decision_after_director` (consult_doctrine, path VIP):

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
    return
await self._coordinator.transition(turn_id, TurnStatus.GRAY_ZONE)
logger.info("consult_doctrine_completed", extra={...})
```

El comportamiento resultante está operativo hoy y se describe en `docs/ARCHITECTURE.md` §3 ("Paracaídas de zona gris"): si el DM de consulta de doctrina falla, el sistema descongela y demota a `approve` con `reason="vip_doctrine_notify_failed"` (path VIP) o `"atencion_doctrine_notify_failed"` (path atención).

### Test que cubre el caso

En `tests/unit/application/test_turn_orchestrator.py`, junto al test F6 existente (`"F6: doctrine notify failure discards the query and demotes to approve."`), un test hermano cubre el path VIP: mock de `admin.send_doctrine_query` que lanza excepción y verifica que `gray_zone.discard_and_close` fue llamado con el `query.id` correcto, el turno terminó en `PENDING_APPROVAL` (no en `GRAY_ZONE`), `admin.send_draft_for_approval` fue llamado con `reason="vip_doctrine_notify_failed"`, y que el VIP no queda con `frozen_until` en el futuro.

### Resultado

Fix aplicado, mergeado en `main` e independiente del resto del feedback de calidad (se mergeó solo). La suite sigue en verde.

---

## Decisiones de diseño aprobadas — Feedback de calidad (FB-01..FB-06)

Todas las decisiones siguientes están implementadas y activas.

| ID | Decisión | Alcance |
|---|---|---|
| **FB-01** | Dos mecanismos con fuerza distinta para la reprimenda: **política dura** (regla siempre consultada por el Decider, vía `promote_to_policy`) o **counter-example de alto peso** (ejemplo negativo en retrieval). La dueña elige caso por caso en el momento de reprender — no hay heurística automática que decida por ella. | Reprimenda |
| **FB-02** | Los ejemplos `quality='gold'` se priorizan en el retrieval de forma **no probabilística**: si existe un match `gold` sobre el umbral de similitud, siempre se incluye, independientemente de si hay ejemplos `standard` más similares. | Retrieval |
| **FB-03** | Los counter-examples se incluyen **determinísticamente** cuando hay match sobre el umbral: todo counter-example nace de una reprimenda deliberada y se consulta `find_by_similarity(..., counter_example=True)` de forma separada y no muestreada. | Retrieval |
| **FB-04** | Alcance dual (global vs VIP específico) para ambos ejes — ejemplos y políticas — vía columna `vip_id UUID NULL` en ambas tablas (`examples`, `policies`). `NULL` = global. **No se reutilizó la columna `scope` existente de `Policy`** (que codifica el eje canal `"all"` vs canal VIP sin filtrar): `vip_id` es un filtro adicional, independiente de `scope`. | Esquema |
| **FB-05** | "Destacar" y "Reprender" promueven **de inmediato**, sin pasar por la cola de revisión de `staging_candidates` que usa `Corregir` (esa cola sigue existiendo tal cual para correcciones normales sin flag). | UX |
| **FB-06** | Todo detrás de `FEATURE_QUALITY_FEEDBACK_ENABLED` (default `false` en `settings.py`, `true` en `.env`). Con el flag apagado, los botones no aparecen y el comportamiento actual (Aprobar/Corregir/Escalar) queda intacto. | Global |

---

## Fase 1 — Esquema de datos (implementado)

**Migración Alembic 029** `feedback_quality` (head actual — confirmado en `docs/ARCHITECTURE.md` §5):

- `examples`: se agregó `quality VARCHAR NOT NULL DEFAULT 'standard'` (valores válidos: `'standard'`, `'gold'` — validados en el repo con `validate_example_quality`, no con `CHECK` de DB, manteniendo el estilo del resto del esquema) y `vip_id UUID NULL REFERENCES vips(id)` con índice (`ix_examples_vip_id`).
- `policies`: se agregó `vip_id UUID NULL REFERENCES vips(id)` con índice (`ix_policies_vip_id`). **No se tocó la columna `scope` existente.**
- El FK referencia `vips.id` (PK UUID), consistente con el resto de las migraciones que referencian `vips.id`.

**Resultado:** migración aplicada y reversible; sin cambio de comportamiento visible en el momento de la migración.

---

## Fase 2 — Backend: repos y servicios (implementado)

### `infrastructure/db/repositories/examples.py`

- `insert(...)` acepta `quality: str = "standard"` y `vip_id: UUID | None = None`.
- `find_by_similarity(...)` acepta `vip_id: UUID | None = None`. El filtro adicional es `(Example.vip_id.is_(None)) | (Example.vip_id == vip_id)` (`vip_id_visibility_clause`); para `atencion` (`vip_id is None`) solo se ven filas globales. El orden es gold-first: `case((Example.quality == "gold", 0), else_=1)` antes de la similitud (coseno) — un gold relevante no pierde su lugar frente a varios standard más parecidos dentro del límite de resultados.

### `infrastructure/db/repositories/policies.py`

- `insert(...)` y `find_active_by_similarity(...)` aceptan `vip_id: UUID | None = None`, con el mismo filtro `(Policy.vip_id.is_(None)) | (Policy.vip_id == vip_id)` — **en AND con el filtro de `scope` existente, no en su lugar**.
- `policy_to_dict` incluye `vip_id` en el dict de salida.

### `cognitive/retrievers/policy.py` y `cognitive/retrievers/examples.py`

- Ambos retrievers reciben el contexto del turno con `vip_id` y lo pasan al repo correspondiente. Para turnos de canal `atencion` (`vip_id is None` en el turno), el filtro no excluye nada adicional (comportamiento preservado). El `PolicyRetriever` mantiene el channel-scope de `scope='all'` para atención.

### `cognitive/retrievers/examples.py` — contraejemplo determinístico

- Se eliminó el muestreo aleatorio (`counter_example_chance`). Hoy el retriever consulta `find_by_similarity(..., counter_example=False)` para los ejemplos normales y, de forma separada, `find_by_similarity(..., counter_example=True, limit=1)` para el contraejemplo; si hay match sobre el umbral, lo incluye como `[COUNTER-EXAMPLE]` en el contexto del Generador. El comportamiento es determinístico.

### `application/staging_service.py`

`promote_to_counter_example(...)` (`is_counter_example=True`, `vip_id` opcional) y `promote_to_policy(...)` (`trigger`, `rule`, `scope`, `vip_id` opcional) existen como hermanos de `promote_to_example`, con el mismo manejo de errores (`ValueError` si no existe o no está `pending`) y el bloqueo anti-contaminación de atención (REQ-ATN-13) copiado tal cual.

### `application/admin_service.py`

- `handle_mark_gold(turn_id, *, scope, actor_id, on_progress=None)` — gateado por `_require_quality_feedback()` y bloqueado para `atencion` (`AtencionPromoteBlocked`). Aprueba y entrega igual que `handle_approve` (reusando su lógica), y si la entrega no se canceló inserta un `Example` con `quality='gold'` (`insert_gold_example`) usando el draft ya aprobado (`draft_text == corrected_text`, sin corrección real). `vip_id = turn.vip_id` si `scope=='vip'`, `None` si `scope=='global'`.
- `handle_reprimand(turn_id, corrected_text, *, mode, scope, actor_id, candidate_id=None)` — gateado por `_require_quality_feedback()` y bloqueado para `atencion`. Entrega la corrección reusando `handle_correct` (`_correct_core`) y, según `mode`:
  - `'counter_example'`: `promote_to_counter_example` sobre el candidato recién creado, con `vip_id` según `scope`.
  - `'policy'`: `promote_to_policy` con trigger autogenerado a partir del texto del VIP en el turno (normalizado y truncado a 80 caracteres; fallback `"reprimenda"`), `rule = corrected_text`, `scope="all"`, `vip_id` según `scope`.

**Resultado:** tests unitarios de repos (con fakes, sin DB real) y de `AdminService`/`StagingService` en verde; la UI se agregó en la Fase 3.

---

## Fase 3 — Telegram: botones y flujo de captura (implementado)

### `telegram/keyboards.py`

Callbacks reales, siguiendo el patrón `≤64 bytes` ya usado:

```python
_ACTION_GOLD = "gd"        # gd:<turn_id>
_ACTION_REPRIMAND = "rp"   # rp:<turn_id> — arranca sesión de texto libre, como "correct"
_ACTION_GOLD_CONFIRM = "gdc"        # gdc:<turn_id>:g|v
_ACTION_REPRIMAND_CONFIRM = "rpc"   # rpc:<turn_id>:pol|ex:g|v
```

`draft_keyboard(turn_id, chat_id)` agrega una fila con los botones **Destacar** / **Reprender** (labels sin emoji) solo si `FEATURE_QUALITY_FEEDBACK_ENABLED` está activo. Después de tocar Destacar: `gold_scope_keyboard` con `[🌍 General] [👤 Este VIP]` + Volver (`gdc:<turn_id>:g|v`). Después de escribir el texto de reprimenda: teclado de confirmación de 4 opciones (`rpc:<turn_id>:pol|ex:g|v`), construido con `encode_reprimand_confirm`/`encode_gold_confirm` y parseado con `parse_reprimand_confirm`/`parse_gold_confirm` (mismo estilo que `parse_staging_callback`).

### `telegram/handlers/callbacks.py`

- `CorrectSessionStore` soporta `mode: Literal["correct", "reprimand"]` en la sesión guardada (reusa toda la mecánica de TTL/expiración/cancel-by-turn ya probada).
- `on_callback` maneja `action == "gd"` (muestra el teclado de confirmación de alcance; no aprueba hasta que se confirme `gdc:...`), `action == "rp"` igual que `"correct"` pero con `mode="reprimand"`, y los callbacks `gdc:`/`rpc:`.

### `telegram/handlers/admin.py`

- `handle_admin_text` lee el `mode` de la sesión de `CorrectSessionStore`: si es `"reprimand"`, guarda el texto capturado en un estado intermedio y devuelve el teclado de 4 opciones en vez de cerrar la sesión — la promoción real (`handle_reprimand`) se dispara recién cuando el owner toca uno de los 4 botones `rpc:...`.

**Resultado:** flujo completo probado en sandbox y tests de integración de `callbacks.py`/`admin.py` en verde; flag activado en producción.

---

## Fuera de alcance en esta versión (explícito, no implementado)

- Marcar dorado/reprimenda de forma retroactiva sobre historial ya entregado (vía `/traza`) — descartado en la sesión de diseño; fuera de alcance (no implementado).
- Enganchar el reprimand al `vip_trust_budget` del Evo-Agente (bajarle confianza a la categoría del turno) — mencionado como posible extensión futura; fuera de alcance (no implementado).
- **UI para editar manualmente el `trigger`/`rule` autogenerado de una política creada por reprimenda — pendiente (no implementado).** Las políticas de reprimenda se guardan en la tabla `policies` del DB vía `promote_to_policy` (`handle_reprimand` en `admin_service.py`), y no existe UI que las edite. El panel "Políticas de conducta" del menú Personalidad (`persona_admin.py`) edita el catálogo de persona versionado (JSON `persona_diana.json`/`persona_atencion.json`), un almacén distinto de la tabla `policies` del DB. El `trigger` autogenerado queda tal como se creó en el momento de la reprimenda; no hay flujo de edición posterior.

---

## Historial de ejecución

Se ejecutó en este orden: fix de zona gris (aislado, mergeable solo) → migración 029 → backend (testeable sin UI) → Telegram → validación en sandbox con el flag encendido → activación de `FEATURE_QUALITY_FEEDBACK_ENABLED` en producción (hoy `true` en `.env`).

Cada fase dejó la suite de tests en verde antes de pasar a la siguiente — no se acumularon fases sin correr `pytest` completo, dado el tamaño de `turn_orchestrator.py` y la cantidad de invariantes de concurrencia que dependen de él.
