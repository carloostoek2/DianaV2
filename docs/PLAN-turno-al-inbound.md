# Plan: Turno al inbound + espera como estado del turno

**Rama base:** `main`  
**Fecha:** 2026-08-02  
**Problema:** La espera “humana” corre **antes** de crear el turno. Si la dueña responde en esa ventana, no hay turno que cancelar y el flag de intervención se borra demasiado pronto → el bot puede seguir.  
**Referencia limpia:** v1 (`diana/`) crea la unidad de trabajo al llegar el VIP (`reply_gen` + `timer_schedule` + task) y cancela con `task.cancel()` / gen obsoleto.  
**Meta de producto:** Mismo comportamiento que v1: *si hay trabajo en el chat y llega dueña o VIP nuevo, ese trabajo muere*; la espera sigue contando desde el mensaje del VIP.

---

## 1. Principio de diseño

| Hoy (V2) | Objetivo (estilo v1 en V2) |
|---|---|
| VIP → espera (sin turno) → mint turn → LLM | VIP → **mint turn** → espera → LLM |
| Cancel dueña en espera = flag volátil | Cancel dueña = **supersede del turno vivo** |
| Abortos con `uuid4()` sintético | Siempre devolver **turn_id real** (aunque quede `superseded`) |
| Delay “humano” desacoplado de la identidad del trabajo | Delay es **fase del turno** |

La espera **no se mueve al final** (después de aprobar). Sigue al inicio, como ahora y como en v1, para que el reloj cuente desde el mensaje del VIP y no desde el OK de la dueña.

---

## 2. Flujo objetivo

```
VIP message
  → bump vip_epoch + history (igual que hoy)
  → chat_scope: begin_turn (status = waiting_delay o received)
       · supersede turnos previos del chat (cascade cancel deliveries/approvals)
       · bind turn ↔ vip_epoch
  → FUERA del lock: sleep(pre_delay)  [o timer durable — ver §4]
  → re-check: turn no terminal + epoch actual + (opcional) !owner_intervened
  → chat_scope: Director → approve | send | escalate | gray_zone
  → si send: deliver fuera de lock (skip_initial_delay=True; el delay ya se consumió)
```

**Dueña escribe en el chat (business):**

```
OwnerDetectionMiddleware
  → mark_owner_intervened (red de seguridad mid-LLM)
  → coordinate(owner) → supersede non-terminal (incluye waiting_delay)
  → cancel_pending deliveries + cancel waiting approvals
  → history role=owner
```

El turno en espera pasa a `superseded`. Al despertar del sleep, el orquestador ve terminal y **no** corre Director.

**VIP manda otro mensaje:**

```
begin_turn (replace) → supersede el anterior (reason=new_message)
  → el sleep viejo despierta, ve superseded / epoch stale → exit
```

---

## 3. Cambios por capa (orden de implementación)

### Fase A — Modelo de estado (pequeño, bloqueante)

1. **Estado de turno en espera**  
   - Opción preferida: nuevo `TurnStatus.WAITING_DELAY = "waiting_delay"` (explícito, auditable).  
   - Alternativa mínima: reutilizar `RECEIVED` solo durante la espera (menos claro en trazas/recovery).  
   - **Decisión del plan:** usar `waiting_delay`.

2. Actualizar:
   - `cognitive/models.py` (`TurnStatus`, no terminal)
   - cualquier validación de transición de status en repos/tests
   - docs de máquina de estados si existen (SPEC / AGENTS solo si el flujo canónico cambia en redacción)

3. `begin_turn` / `coordinate` VIP: crear turno en `waiting_delay` (no en `received` ya “listo para analizar”).  
   Transición a `analyzing` (o el primer status del Director) **después** de la espera.

### Fase B — Orquestador (corazón del cambio)

Archivo principal: `application/turn_orchestrator.py`

1. **Reordenar `handle_vip_message`:**
   - Mantener: fail-closed sin `business_connection_id`, bump epoch, history early.
   - **Nuevo:** bajo `chat_scope`, `begin_turn_unlocked` + bind epoch **antes** del sleep.
   - Sleep **fuera** del lock (crítico: la dueña debe poder `coordinate` sin esperar 2–8 min).
   - Tras sleep:
     - si turno terminal (`superseded` / `failed`) → log + return `turn_id` real  
     - si epoch no actual → asegurar supersede si hace falta + return  
     - si no → entrar a pipeline cognitivo (extraer de `_handle_vip_message_locked` la parte post-mint)

2. **Refactor interno sugerido:**
   - `_mint_turn_for_inbound(...)` → crea turno waiting_delay  
   - `_run_cognitive_after_delay(turn_id, incoming, ...)` → Director + routing  
   - Eliminar returns con `uuid4()` sintético en paths de cancel pre-pipeline.

3. **Autonomous send:** seguir entregando fuera del lock; `skip_initial_delay=True` porque el delay ya se aplicó al inicio (comportamiento actual de delivery post-pipeline).

4. **Dueña en espera:** dejar de depender del check `is_owner_intervened(since=before_sleep)` como camino principal.  
   - Puede quedar como **defense-in-depth** (si el flag está y el turno aún no se supersedió).  
   - El camino principal es: turno ya supersedido por `coordinate(owner)`.

### Fase C — Coordinador / middleware (simplificar, no romper)

1. `TurnCoordinator._supersede_nonterminal` ya cancela deliveries + approvals si hay turnos vivos. Con mint early, **la dueña en espera cancela de verdad**.

2. Flag `mark_owner_intervened`:
   - **Seguir usándolo** para mid-pipeline (Director con lock o entre transitions vía `transition_sink`).
   - Revisar `clear_owner_intervention`:
     - Hoy se limpia en `coordinate(owner)` y en `begin_turn`.  
     - Tras mint early: limpio en `coordinate(owner)` sigue OK (el turno ya quedó superseded).  
     - En `begin_turn` VIP: limpiar solo **después** de haber creado el turno nuevo (o al inicio del VIP nuevo con epoch/since), para no reintroducir “flag pegado” del bug anterior.

3. `OwnerDetectionMiddleware`: sin cambio de contrato; se beneficia solo de que existan turnos supersedibles.

### Fase D — Recovery / timers (opcional en el mismo PR o follow-up)

Hoy `runtime_timers` está atado a **delivery** (`delivery_id`), no al pre-delay del orquestador.

| Opción | Cuándo |
|---|---|
| **D0 (MVP del plan)** | Sleep en memoria como ahora; si el proceso muere en la espera, el turno queda `waiting_delay` y el startup lo trata como zombie (supersede o fail + re-notify según política). |
| **D1 (follow-up)** | Extender runtime timer o tabla de “turn fire_at” para reanudar esperas tras restart (paridad con `timer_schedule` de v1). |

**Plan por defecto:** D0 en el primer cambio; documentar D1 como residual.  
En recovery startup: turnos `waiting_delay` al boot → `superseded` o `failed` con razón `process_restart` (fail-closed, predecible). No reanudar LLM a ciegas.

### Fase E — Tests (obligatorio, Strict TDD)

Orden sugerido (red → green):

1. **Dueña durante la espera:** VIP arranca delay → owner business msg → al despertar no hay Director call / no approval waiting / turno `superseded`.  
2. **VIP nuevo durante la espera:** primer turno superseded; un solo Director sobre burst/último turn.  
3. **Sin intervención:** tras delay, se crea pipeline normal (approve path).  
4. **Regresión flag stale:** VIP nuevo tras dueña no se aborta en falso.  
5. **Autónomo:** dueña en espera → no send.  
6. Ajustar tests que asumen “no turn hasta después del delay” o synthetic uuid.

Archivos de ancla:  
`tests/unit/application/test_turn_orchestrator.py`,  
`tests/unit/application/test_turn_coordinator.py`,  
`tests/unit/telegram/test_owner_mw.py`.

### Fase F — Observabilidad y producto

Logs claros:

- `turn_minted_waiting_delay`
- `turn_delay_completed` / `turn_aborted_after_delay` (reason: owner_message | new_message | restart)
- Dejar de emitir paths de “synthetic abort id”

Para la dueña (ops): en trazas se verá el turno cancelado en espera (más legible que “nunca existió”).

---

## 4. Decisiones cerradas / abiertas

| # | Tema | Decisión |
|---|---|---|
| 1 | ¿Nuevo status `waiting_delay`? | **Sí** |
| 2 | ¿Delay sigue al inicio? | **Sí** (no post-approve) |
| 3 | ¿Lock durante sleep? | **No** |
| 4 | ¿Timer durable pre-pipeline en este PR? | **No** (D0); residual D1 |
| 5 | ¿Quitar por completo flag owner? | **No**; bajar a defense-in-depth mid-LLM |
| 6 | ¿Migración DB? | Solo si el enum se valida en CHECK constraint; si es texto libre en `turns.status`, no hace falta migración de esquema |

---

## 5. Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| Más filas `superseded` (cada cancel en espera) | Esperado; útil para auditoría |
| Director / sink asume status inicial `received` | Transición explícita `waiting_delay` → primer status cognitivo |
| Zombies `waiting_delay` tras crash | Recovery fail-closed (§D0) |
| Tests frágiles por sleep real | `FixedDelayPolicy` corto (ya existe en suite) |
| Double delay (orquestador + BehaviorEngine) | Forzar `skip_initial_delay=True` en paths post-espera |

---

## 6. Criterios de hecho (DoD)

- [ ] Turno se crea **antes** de la espera humana.  
- [ ] Dueña en chat VIP durante la espera → turno `superseded`, **0** LLM, **0** envío, **0** draft nuevo.  
- [ ] VIP nuevo durante la espera → cancela el anterior; un solo pipeline vigente.  
- [ ] Sin intervención, flujo supervisado/autónomo igual que hoy en resultado.  
- [ ] No se reintroduce el “flag pegado” que abortaba VIP futuros.  
- [ ] Tests unitarios del escenario dueña-en-espera en verde.  
- [ ] Sin regresión de pureza de capas (Cognitive no conoce Telegram; cancel sigue en Coordinator/Behavior).

---

## 7. Orden de trabajo sugerido (commits)

1. `test: owner cancel during pre-delay fails today` (red) + status `waiting_delay`  
2. `feat: mint turn before human delay` (green path orquestador)  
3. `test+fix: owner/VIP supersede during delay`  
4. `chore: recovery treat waiting_delay as zombie` + limpieza de synthetic uuid / logs  
5. (opcional residual) durable pre-delay timers  

---

## 8. Fuera de alcance de este plan

- Cambiar duración de delays (2 min / 3–8 min).  
- Cambiar orden del Decisor o flags de Fase 3.  
- Reimplementar v1 monolitica; solo la mecánica de identidad-al-inbound.  
- Promo / recontact (tienen sus propios delays).

---

## 9. Siguiente paso tras aprobar el plan

Implementar en `main` (o branch `feat/turn-at-inbound` desde main) con Strict TDD, empezando por el test de dueña-en-espera y el status `waiting_delay`.
