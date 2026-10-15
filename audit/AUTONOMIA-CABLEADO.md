# Cableado real del envío autónomo — rastro y puntos de rotura

Fecha: 2026-10-09. Autor: Rastreador de cableado (skill `contract-proof`).
Alcance: seguir el camino del envío autónomo desde el disparador real hasta el efecto, marcar
dónde se rompe en silencio y decir si el camino está completo, cortado o condicionado.
No se modificó código. No se leyeron conversaciones de VIP (regla PRIORITARIA del proyecto):
de la base solo se leyeron **conteos y estados**, nunca textos.

Herramientas usadas: lectura dirigida de `src/`, `python audit/tools/wiring_scan.py`
(salida cruzada contra este rastro) y consultas de solo lectura a Postgres de producción
(`vips`, `turns`, `turn_outcome_log`, `vip_trust_budget`, `turn_category_log`, `system_config`).

Reparto de responsabilidades con la auditoría de banderas (`audit/AUTONOMIA-BANDERAS.md`): esa
ficha responde *qué valor tiene cada bandera y qué la lee*. Esta responde *qué pasa, paso a paso,
cuando el camino se ejecuta, y dónde se corta sin decir nada*.

---

## 0. Veredicto en una línea

**El camino está COMPLETO para no enviar y CONDICIONADO para enviar**: con L1 apagado el envío
autónomo es inalcanzable por construcción; con L1 encendido, el envío depende de L2 (que hoy está
vacío: 0 VIPs con `auto_send`) y atraviesa 4 puertas que pueden degradarlo. Hay **2 roturas de
medición** (no de entrega) que ya están contaminando la evidencia con la que la dueña decide, y
**5 roturas de borde** en la entrega que dejan el turno o el historial en un estado que nadie mira.

---

## 1. El camino (paso a paso, con `archivo:línea`)

### A. La puerta de modo

```
business_message                                  telegram/handlers/business.py:202-236
  → TurnOrchestrator.handle_vip_message           application/turn_orchestrator.py:1219
      · límite diario de Atención (:1227-1230) — puede DROPEAR el turno en silencio
      · bump_vip_epoch + historial del VIP (:1243-1244)
      · minteo del turno bajo lock (:1248-1269)
      · _resolve_effective_mode(vip_id, channel_type)   (:1271) → :345-369
      · delay pre-pipeline con ese modo (:1277-1318)
  → _run_after_pre_delay → … → _run_cognitive_after_delay
  → Director.handle_turn (pipeline completo)       cognitive/director.py:749-761
  → Decisor.decide(mode="supervised" hardcodeado)  cognitive/decider.py:131-228
```

- **De dónde sale `global_mode`**: `Settings.global_mode` (`config/settings.py:86`,
  `Literal["supervised","autonomous","fake_delivery"]`) ← `.env:51 GLOBAL_MODE=supervised`.
  Llega al orquestador en `composition.py:1242 delivery_mode=settings.global_mode` y se guarda
  como `self._delivery_mode` (`turn_orchestrator.py:203`, `:341-343`). Coincide con el `.env`:
  supervised.
- **`_resolve_effective_mode`** (`turn_orchestrator.py:345-369`): arranca en el modo global, lo
  puede pisar con el `delivery_mode` del perfil de persona (`:357-363`), y **solo si el resultado
  es `"autonomous"`** consulta el AMS (`:364-369`).
- **Atención (`vip_id=None`) bajo `GLOBAL_MODE=autonomous`: SÍ se degrada.** El código cumple lo
  que dice el docstring: en `AutonomousModeService.is_autonomous_enabled`
  (`application/autonomous_mode_service.py:52-68`) el L1 se evalúa primero (`:59-60`), **después
  el guard de `None` (`:61-62`) y recién después el early-return por modo global (`:63-64`)**. Con
  `vip_id=None` devuelve `False` antes de llegar a la línea 63. Y en la entrega real el segundo
  guard es `_prepare_autonomous_send → is_autonomous_enabled(incoming.vip_id)`
  (`turn_orchestrator.py:2833-2859`): Atención se degrada a `approve` con
  `reason="autonomous_mode_disabled"`.
- **Quién más llama a `_resolve_effective_mode`**: nadie más (único llamador `:1271`; lo confirman
  los tests: `tests/unit/application/test_turn_orchestrator.py:4222-4325`). Consecuencia: **ese
  modo solo decide el perfil de espera pre-pipeline, nunca la acción**. `ctx.mode` en la entrega
  sale de `_effective_delivery_mode` (`:341-343`), que devuelve el modo global puro, y en el motor
  solo cambia el delay inicial (`behavior/engine.py:208`) y el camino fake
  (`behavior/engine.py:240`). **La prueba de fuego es el Decisor, no el modo.**
- Consecuencia lateral confirmada: con `GLOBAL_MODE=supervised` la función retorna en `:364-365`
  **antes** de consultar el AMS, así que un VIP con `auto_send=true` nunca cambia el perfil de
  espera (queda el supervisado, 120 s; el autónomo sería 180-480 s — `composition.py:325-329`).

### B. El despacho

```
_run_cognitive_after_director (:2098-2116)
  → _apply_decision_after_director (:2135)
      · sandbox auto-send intercepta approve/send ANTES del despacho (:2194-2211)
      · action == "approve"          → PENDING_APPROVAL + DM (:2213-2220)
      · action == "consult_doctrine" → zona gris (:2222-2497)
      · action == "escalate"         → ESCALATED + aviso (:2498-2515)
      · action == "send"             → (:2516-2532)
          ├ is_phatic_template_reason → _prepare_phatic_template_send (:2565-2726)
          └ else                      → _prepare_autonomous_send (:2802-2952)
  → vuelve a _run_after_pre_delay, FUERA del lock (:1598-1723)
  → BehaviorEngine.deliver (:1673)
  → _finalize_autonomous_delivery bajo lock (:1684-1692 → :2980-3088)
  → _maybe_post_turn_terminal en el finally (:1693-1699)
  → notify_if_needed si quedó DELIVERED (:1704-1713)
```

**Cada condición que degrada `send` → `approve`, con su `reason`:**

| Condición | Punto | Resultado | Reason |
|---|---|---|---|
| `autonomous_mode is None` (no cableado) | `:2811-2831` | `FAILED("autonomous_not_wired")` | — (no aprobación) |
| L2 no habilitado (`is_autonomous_enabled` False) | `:2833-2859` | `PENDING_APPROVAL` + DM | `autonomous_mode_disabled` |
| VIP congelado | `:2861-2885` | `FAILED("vip_frozen")` + aviso | — |
| Borrador vacío | `:2887-2909` | `FAILED("empty_draft")` + aviso | — |
| BehaviorEngine no cableado | `:2911-2928` | `FAILED("autonomous_behavior_not_wired")` | — |
| VIP se congela entre el lock y la entrega | `:1602-1635` | `FAILED("vip_frozen")` + aviso | — |
| BehaviorEngine desaparece mid-flight | `:1639-1658` | `FAILED(...)` | — |

`self._behavior` y `self._autonomous_mode` están **siempre cableados** en el contenedor
(`composition.py:1238` y `:1239`), así que esas tres ramas son defensa en profundidad, no el
camino vivo. **La única degradación viva hoy es la de L2** (`:2833-2859`).

**`except Exception` y `return` mudos en ese camino:**

- `:2823-2830`, `:2871-2878`, `:2895-2902`, `:2920-2927`: `except` alrededor del `mark_failed`
  para disparar el hook post-turno antes de re-lanzar. **Re-lanzan** (no tragan), pero el error
  termina en `business_handler_error` (`telegram/handlers/business.py:227-236`): la dueña no recibe
  nada del caso `autonomous_not_wired` / `vip_frozen` / `empty_draft` cuando el fallo es de `mark_failed`.
- `:2997-3007`: `turn_after is None or terminal` → `logger.info` y `return False`. **Return mudo**
  (sin aviso a la dueña) — es el caso "el mensaje ya salió y el turno fue superseded".
- `:3045-3064`: entrega **cancelada** → `mark_failed` + traza + log, **sin `_safe_notify_info`**.
  Es la única rama terminal de la entrega que no avisa.
- `:3040-3042`, `:3057-3063`, `:3084-3087`: solo `logger.info`.
- `owner_history.py:70-78`: la escritura de historial traga el error fila por fila
  (`owner_history_append_failed`), sin aviso.
- `_safe_notify_info` (`:1070+`) es fail-soft por diseño: si el aviso cae, el fallo original no se
  enmascara, pero **el aviso tampoco llega**.

**Si el BehaviorEngine está cableado pero el envío falla a mitad de camino:**

- **Falla devuelta** (`result.success=False`): permanente → `FAILED` + **sí avisa**
  (`:3071-3088`, `owner_notify_failed_after_autonomous_deliver_fail`); cancelada → `FAILED` y
  **no avisa** (`:3045-3064`).
- **Falla lanzada**: `BehaviorEngine._deliver_core` traga todo lo que pasa dentro de su `try`
  (`behavior/engine.py:353-362`) y lo devuelve como `DeliveryResult`. Pero la inserción de la
  entrega queda **fuera** del `try`: `await self._deliveries.insert_pending(record)`
  (`behavior/engine.py:192`) y `self._timers.register(...)` (`:197`). Si eso revienta, la excepción
  sube por `turn_orchestrator.py:1673` → `business.py:227` y **el turno queda en el estado no
  terminal que dejó el Director (`DECIDING`), sin aviso, sin hook post-turno y sin fila de entrega**.
  Se auto-cura cuando llega el mensaje siguiente (`turn_coordinator.py:324-329` supersede lo no
  terminal) y por `recovery_startup`, pero el mensaje de ese turno se pierde en silencio.
- **Falla a mitad de un envío partido**: con `FEATURE_ADVANCED_BEHAVIOR=true`, el autónomo entrega
  con `allow_split=True` (`:2948`). Si el segmento 2 falla, el resultado es `success=False` con
  `message_ids` del segmento 1; el finalizador marca `FAILED` y **no escribe ninguna fila en el
  historial del propietario** (el `append_owner_delivery_history` solo corre en la rama de éxito,
  `:3023-3038`). El VIP recibió media respuesta; el modelo no ve ninguna.

**¿Escribe el historial del propietario?** Sí, solo en éxito y fuera de sandbox:
`turn_orchestrator.py:3020-3038`. Ojo con el orden: primero la traza (`:3016-3019`) y después el
historial (`:3032`). Si `set_delivery_result` falla (`traces.py:61-65`, sin try), el turno ya quedó
`DELIVERED` pero **la fila de historial se pierde y la excepción sube como error genérico**.
Es un patrón compartido con el camino supervisado (`admin_service.py:2200` vs `:2219`), no un
defecto del autónomo.

**¿Crea/extiende la ventana de reacción del VIP?** La ventana no es un objeto: es implícita. La
fila de `turn_outcome_log` se escribe post-turno (`_run_outcome_log`, `:905-952`) con `created_at`
por defecto de la base (`infrastructure/db/repositories/turn_outcome.py:172-211`), y de ese
timestamp cuelgan las dos lecturas de la ventana: el hook inmediato
(`turn_outcome.py:338-361`, `created_at >= now - ventana`) y el job de respaldo
(`:363-399`, `anchor = coalesce(turns.updated_at, turns.created_at)`). Es decir: **sí se abre
ventana, pero se abre para cualquier turno no terminal con traza, no solo para los entregados**
(ver P-1).

### C. El Decisor

`cognitive/decider.py:131-228`. Orden efectivo: **seguridad (`:145`) → zona gris (`:155`) → risk
alto (`:171`) → frustración (`:181`) → send autónomo (`:193-216`) → approve (`:219-228`)**. Coincide
con AGENTS.md §4.1 (y con la nota de alineación 2026-08-21: `risk=alto` antes que `molesta`).

- `mode` **no habilita el envío**: `mode` solo se usa en `:219-221` para elegir la etiqueta
  `supervised_send_to_approve`. La única puerta es `self._feature_autonomous_mode` (`:193`), que
  entra por constructor desde `composition.py:700`. Confirmado en el código, no solo en el docstring.
- El Director pasa `mode="supervised"` hardcodeado (`cognitive/director.py:753`) y re-envuelve la
  decisión con `draft_text=draft` (`:755-761`) — necesario porque el Decisor devuelve
  `draft_text=None` en `send` (`decider.py:203-209`).
- **Con L1 apagado el camino autónomo es inalcanzable**: `if self._feature_autonomous_mode:` es
  falso → cae siempre a `approve` en `:219-228`. Por lo tanto `_prepare_autonomous_send` no se
  ejecuta nunca desde el Decisor.
- Los únicos dos productores de `action="send"` en todo `src/` son `decider.py:204` y el corte
  fático del Director (`director.py:474` y `:515`, gobernado por `FEATURE_PHATIC_AUTO_SEND`, hoy
  `true`). El segundo es el **único envío sin aprobación que ya ocurre en producción** y es
  independiente de L1/L2 (AGENTS.md §4.17).

### D. La puerta de recomendación y activación

- **El botón solo se dibuja si `ready=True`**: `telegram/handlers/menu.py:983-997` arma las tuplas y
  `telegram/keyboards.py:1402-1431` decide: `auto_send` → botón "🔴 Apagar"; si no, y `ready` →
  "🟢 Activar xxxxx"; si no está listo, **no hay botón** (solo ⏳ en el texto). Un VIP que no está
  listo no puede ser activado por un toque: no hay callback al que pegarle.
- **`activate()` reverifica las 3 condiciones**, no confía en quien lo llama:
  `autonomy_readiness_service.py:307-328` (bandera `:313-317`, VIP existe `:318-320`, `ready`
  `:321-322`), donde `ready` = confianza ≥ `confidence_min` **y** coincidencia global ≥
  `match_rate_min` **y** 0 escalaciones por seguridad (`:80-85`). El botón se redibuja después
  (`:1019`).
- **¿`set_auto_send(True)` fuera de `activate()`?** **No existe.** El escritor es único
  (`infrastructure/db/repositories/vips.py:187-201`) y sus únicos llamadores son
  `autonomy_readiness_service.py:323` (activar) y `:332` (apagar). No hay job, script, endpoint,
  migración ni seed que lo toque: `007_vip_auto_send.py` crea la columna con `server_default=false`,
  `scripts/` no la menciona y `system_config` no la escribe.
- **¿Un VIP ya activado se autoenciende al encender L1?** **Sí.** `is_autonomous_enabled` devuelve
  `True` con solo `vip.auto_send=True` cuando `global_mode != "autonomous"` (`:63-68`). No hay
  segunda confirmación al encender L1, ni fecha de caducidad, ni re-chequeo del gate §8.
  **Riesgo vivo hoy: NULO**, porque en la base real **0 de 16 VIPs tienen `auto_send=true`**
  (consulta de solo lectura del 2026-10-09). Queda como riesgo latente: si la dueña activa VIPs
  mientras L1 está apagado (el panel se lo permite y le dice "Activado", ver H-6 de la ficha de
  banderas), esos VIPs empiezan a enviar solos **en el mismo instante** en que se encienda L1, sin
  re-evaluar si siguen cumpliendo las 3 condiciones.

### E. La reacción del VIP (C3)

**Está cableada de verdad y corre en producción.** Dos entradas:
- Hook inmediato: `turn_orchestrator.py:2110-2113` → `_run_outcome_reaction` (`:954-1002`) →
  `OutcomeLogService.record_reaction` (`outcome_log_service.py:422-452`).
- Job de respaldo: registrado en `main.py:32`, `:128` y `:380-404` (exige
  `feature_autonomy_quality_enabled` + `outcome_log` + `history`; las tres se cumplen),
  implementado en `jobs/outcome_reaction.py` (`run_outcome_reaction_cycle:60-113`,
  `OutcomeReactionJob:116-171`).
- Evidencia viva: `turn_outcome_log` tiene 552 filas y **551 con `vip_signal`**
  (positive 341 · silence 165 · neutral 30 · negative 15 · NULL 1). El círculo no está muerto.
- Anti-doble-conteo real: `record_reaction` no-opea si el valor no cambia (`:440-441`).

Matiz importante del hook inmediato: corre **antes** de aplicar la decisión del turno actual
(`:2113` vs `:2120`), así que resuelve el turno **anterior** de ese chat usando la comprensión del
mensaje **actual**. Eso es lo diseñado; el problema es qué turno anterior elige (P-1).

### F. El registro del desenlace

`_maybe_post_turn` (`:420-466`) llama a `_run_outcome_log` (`:905-952`) → `record_shadow`
(`outcome_log_service.py:293-334`). **Es post-turno de verdad**:
- Camino autónomo/fático/sandbox: se dispara desde el `finally` de `:1693-1699`, **después** de
  `_finalize_autonomous_delivery`, y solo si el finalizador tocó un estado terminal
  (`post_turn_state[0]`, marcado en `:3013-3014`, `:3048-3049`, `:3069-3070`).
- Camino supervisado/escalado: `:1595` (cuando no hay job de entrega) o vía
  `AdminService.set_post_turn_hook` (`composition.py:1311`) al aprobar/corregir/escalar.
- Filtros que lo dejan mudo: sandbox sin persistencia (`:915-916`), sin `trace_reader` (`:918-919`),
  turno `SUPERSEDED`/`FAILED` (`:927-931`), sin `vip_id` (`:932-933` — **Atención nunca deja fila**),
  sin traza (`:935-936`), y todo envuelto en `log_swallowed("outcome_log_error")` (`:949-952`).

---

## 2. Tabla de puntos de rotura (ordenada por riesgo)

| # | Punto | `archivo:línea` | Qué se rompe | ¿Falla o diseño? | Consecuencia para el encendido |
|---|---|---|---|---|---|
| **P-1** | Reacción C3 atribuida a turnos no entregados | `turn_orchestrator.py:977-989` + `infrastructure/db/repositories/turn_outcome.py:338-361` | `find_pending_signal_for_chat` elige la última fila del chat con `vip_signal IS NULL`, sin exigir que ese turno haya sido **entregado**. Evidencia viva: **173 eventos `positive` y 2 `negative` sobre turnos `superseded`** (nunca enviados) y 11 `positive` + 1 `negative` sobre `escalated`, todos con fila en `turn_category_log` (o sea, **todos movieron el trust**) | **FALLA** | **Alta.** La condición 1 del gate §8 (confianza ≥ 0.90) se alimenta de señales de turnos que el VIP nunca recibió. Hoy 2 VIPs ya están en `trust=1.0`. El botón Activar puede habilitarse con evidencia inflada antes de encender L1 |
| **P-2** | `autonomous_send_rate` cuenta la decisión, no la entrega | `application/metrics_service.py:218-219`, `:257` | `send_count` sale de `decision.action == "send"` de la traza. Al encender L1 con 0 VIPs activados, **todas** las decisiones elegibles quedan `send` en la traza pero se degradan a `approve` en `turn_orchestrator.py:2846` | **FALLA** (medición) | **Alta para la dueña.** La métrica semanal dirá que Diana envió sola cuando no envió nada. Es exactamente el dato que se va a mirar para decidir el paso siguiente |
| **P-3** | Excepción de la entrega deja el turno colgado sin aviso | `behavior/engine.py:192` (fuera del `try`), `:197`; `turn_orchestrator.py:1673`; `telegram/handlers/business.py:227-236` | Si falla `insert_pending` (o el registro del timer), la excepción sube y el turno queda en `DECIDING`: no terminal, sin fila de entrega, sin hook post-turno, sin aviso a la dueña | **FALLA** (borde, probabilidad baja) | **Media.** Nadie se entera de que un turno quedó a medias. Se auto-cura al mensaje siguiente y en el arranque, pero el mensaje de ese turno se pierde mudo |
| **P-4** | Entrega cancelada → `FAILED` sin aviso | `turn_orchestrator.py:3045-3064` | Es la única rama terminal de la entrega sin `_safe_notify_info`, a diferencia del fallo permanente (`:3074-3079`) | Diseño parcial (la cancelación casi siempre la causa un mensaje nuevo) — **a confirmar** | **Media/baja.** Si la cancelación viene de un camino que la dueña no provocó, se queda sin saber que ese turno no salió |
| **P-5** | Traza antes del historial, ambos sin red | `turn_orchestrator.py:3015-3038`; `infrastructure/db/repositories/traces.py:61-65` | El turno pasa a `DELIVERED`, después se escribe la traza y **después** el historial. Si la traza falla, el mensaje salió pero **no queda fila en el historial del propietario** y el resto del bloque (aviso por umbral, logs) se aborta | **FALLA** (borde; patrón compartido con `admin_service.py:2200` vs `:2219`) | **Media.** Desincroniza la memoria del modelo de lo que realmente se envió |
| **P-6** | Envío partido: segmentos ya enviados no se registran | `behavior/engine.py:353-362`; `turn_orchestrator.py:3066-3088` | Con `FEATURE_ADVANCED_BEHAVIOR=true` el autónomo entrega con `allow_split=True` (`:2948`). Si falla el segmento N, el resultado es global `success=False` y **no se escribe ninguna fila de historial** aunque el VIP ya recibió el segmento 1 | **FALLA** (borde) | **Media/baja.** Respuesta a medias que el modelo no ve |
| **P-7** | Mensaje entregado y turno superseded | `turn_orchestrator.py:2997-3007` | Si el turno se vuelve terminal entre el `deliver` y el finalizador, se devuelve `False` con un `logger.info`: el mensaje salió, pero **no hay fila de historial, ni aviso, ni fila de `turn_outcome_log`** | Diseño (ventana estrecha) — **a confirmar** | **Baja.** Deriva de historial acotada |
| **P-8** | L2 por VIP no resuelve el perfil de espera | `turn_orchestrator.py:356-369` | Con `GLOBAL_MODE=supervised` retorna en `:364-365` **antes** de consultar el AMS, así que un VIP con `auto_send=true` nunca obtiene el modo autónomo (delay 120 s en vez de 180-480 s). El docstring promete resolver el L2 | **FALLA** (funcional menor) | **Baja.** Cambia el ritmo de espera, no la entrega. El envío igual ocurre (la puerta real es `_prepare_autonomous_send`) |
| **P-9** | Token crudo en el DM de la dueña | `application/draft_variants.py:66-85` y `:229-242` | La tabla de traducción no tiene `autonomous_mode_disabled`; el fallback devuelve el token tal cual. Además `autonomous_ok` (`:73`) quedó muerto: el orquestador siempre lo reescribe a `autonomous_mode_disabled` antes de encolar (`:2846-2851`) | **FALLA** (cosmética, visible para producto) | **Baja pero visible:** con L1 encendido, cada borrador de un VIP no activado mostrará `autonomous_mode_disabled` en el DM |
| **P-10** | `system_config.FEATURE_AUTONOMOUS_MODE=False` es config muerta | `infrastructure/db/repositories/system_config.py:132` (`get_feature_flags` sin llamadores) | Hay una fila `FEATURE_AUTONOMOUS_MODE = False` en la base que **ningún módulo lee** (la bandera real es `Settings` ← `.env`). Junto a las otras 7 filas `FEATURE_*` que contradicen al `.env`, es documentación ejecutable falsa | **FALLA** (documental) | **Media.** Un operador podría "encender la bandera en la base" y no pasa nada |
| **P-11** | Rutas de "behavior/AMS no cableados" sin aviso | `turn_orchestrator.py:2811-2831`, `:2911-2928`, `:1639-1658` | `mark_failed` + `logger.error`, sin `_safe_notify_info` | Diseño defensivo (hoy `behavior`/`ams` están siempre cableados: `composition.py:1238-1239`) | **Nula hoy.** Solo importa si alguien rompe el contenedor |
| **P-12** | Silencios de la Fila 4 | `turn_orchestrator.py:949-952`, `:999-1002`; `outcome_log_service.py:330-334`, `:390-394`, `:448-452`; `owner_history.py:70-78` | Dos niveles de `except` + `log_swallowed` en el ledger y en el historial | Diseño conocido (H-SB-2 de C-SHADOW-01) con vigilante desplegado | **Baja.** Solo `telegram/health.py` y `jobs/contract_watchdog.py` leen los contadores; la dueña no los ve en ningún panel |
| **P-13** | `paused` no se revisa en el camino autónomo | `turn_orchestrator.py:2802-2952` (ausente) vs `:2647-2668` (sí en el fático) | El autónomo no consulta `_is_vip_paused` | **Diseño efectivo:** `get_record_and_allowed` corta al VIP pausado antes del pipeline (`middlewares/auth.py:127-133`, `repositories/vips.py:67-78`), así que el pipeline nunca ve un VIP pausado | **Nula.** Asimetría de defensa en profundidad, no de comportamiento |
| **P-14** | Rutas de diseño que NO son fallas | `turn_orchestrator.py:915-916` (sandbox no escribe ledger); `:2194-2211` + `:2728-2800` (sandbox no usa AMS); `composition.py:1282-1284` (sin la bandera de calidad el ledger no se cablea); `main.py:382-388` | — | **DISEÑO** (AGENTS.md §4.20 y S4 del sandbox) | Ninguna. Solo hay que no confundirlas con huecos al mirar el journal (`post_turn_skipped_sandbox`, `owner_history_skipped_sandbox`) |

---

## 3. Cruce con `wiring_scan.py`

`python audit/tools/wiring_scan.py .` (salida completa reproducible; resumen de lo que toca a este camino):

- **§1 funciones sin llamador**: `application/outcome_log_service.py:414 list_outcome_rows_since` —
  consumidor huérfano de la Fila 4, ya reportado como H-10. `infrastructure/db/repositories/
  system_config.py:132 get_feature_flags` — la puerta muerta de P-10. Ninguna otra toca el envío.
- **§2 errores tragados**: `turn_orchestrator.py` 41 `except Exception` + 18 `log_swallowed` (el
  archivo más ruidoso del proyecto); `admin_service.py` 58 + 20. Coincide con P-3..P-7 y P-12.
  Además confirma que **solo 2 archivos de producción leen `get_swallowed_counts`**
  (`telegram/health.py`, `jobs/contract_watchdog.py`): la dueña no tiene esa señal.
- **§3 cableado condicionado**: `outcome_log ← outcome_log si feature_autonomy_quality_enabled` —
  es el único gate de bandera en el camino del envío autónomo (todo lo demás del camino está
  cableado incondicionalmente: `behavior`, `autonomous_mode`, `traces`, `vip_store`).
- **§4 apagados silenciosos**: `application/turn_orchestrator.py:2837 autonomous_disabled_for_vip`
  (info) — **esta es la degradación viva del encendido con `GLOBAL_MODE=supervised`**, y hoy
  pasaría solo por journald; `application/recontact_service.py:228 recontact_supervised_skipped`
  (informativo: recontacto está apagado hoy).

---

## 4. Evidencia viva de la base (solo conteos, lectura)

| Dato | Valor | Relevancia |
|---|---|---|
| `vips` con `auto_send=true` | **0 de 16** | Encender L1 con `GLOBAL_MODE=supervised` **no envía nada**: L2 está vacío |
| `turn_outcome_log` | 552 filas (170 en 14 días) | La Fila 4 mide |
| `vip_signal` | 551 con señal (positive 341 · silence 165 · neutral 30 · negative 15) | C3 cableado y corriendo |
| `vip_signal` sobre turnos `superseded` | 263 filas (173 `positive`) | **Contaminación de P-1, medida en producción** |
| `vip_signal` sobre turnos `escalated` | 52 filas (11 `positive`) | Idem |
| `vip_trust_budget` | 31 filas, máximo `trust_score = 1.0` (2 VIPs) | La condición 1 del gate §8 ya está satisfecha para algunos VIPs |
| `system_config` umbrales | `autonomous_thresholds {safety_min 0.9, doctrine_min 0.8, naturalness_min 0.7}`; `eval_thresholds {safety 0.3}` | Son los mínimos reales del Decisor (`composition.py:1689-1703`) |
| `alembic_version` | `036_correction_severity` | Esquema al día |
| `system_config.FEATURE_AUTONOMOUS_MODE` | `False`, **sin lector** | P-10 |

⚪ No se inspeccionó el contenido de las filas (textos de borrador, correcciones, reacciones):
sería material de conversación. Solo se leyeron estados, etiquetas y conteos.

---

## 5. Respuesta a las preguntas concretas de la misión

1. **¿`global_mode` coincide con el `.env`?** Sí: `supervised` en los tres lugares
   (`.env:51` → `settings.py:86` → `composition.py:1242`).
2. **¿Atención se degrada con `GLOBAL_MODE=autonomous`?** Sí, y en dos capas: el guard de `None`
   corre antes del early-return del modo global (`autonomous_mode_service.py:59-64`) **y** la
   entrega vuelve a consultar el AMS (`turn_orchestrator.py:2833-2859`).
3. **¿`mode` habilita el envío?** No. Solo `feature_autonomous_mode` (`decider.py:193`), y el
   Director hardcodea `mode="supervised"` (`director.py:753`).
4. **¿El botón Activar exige `ready`?** Sí en la UI (no se dibuja si no está listo) y sí en el
   servicio (`activate()` re-evalúa las 3 condiciones).
5. **¿`set_auto_send(True)` fuera de `activate()`?** No existe ese camino. Pero **un VIP ya
   activado se autoenciende con L1 sin segunda puerta**; hoy hay 0 filas así.
6. **¿C3 está cableado o es código huérfano?** Cableado, con hook inmediato **y** job registrado en
   `main.py`; evidencia en base (551 señales).
7. **¿El registro del desenlace es post-turno?** Sí: autónomo después de la entrega
   (`:1693-1699`), supervisado después de encolar/aprobar (`:1595`, `composition.py:1311`), y
   siempre con los filtros de `_run_outcome_log` (`:913-936`).
8. **¿Con las puertas cerradas realmente NO ocurre?** **Sí, y por construcción**: con L1 apagado el
   Decisor no puede emitir `send` (`decider.py:193` en falso), así que `_prepare_autonomous_send`
   es inalcanzable desde el pipeline. **Matiz:** ya hay envíos sin aprobación hoy por el carril
   fático (`FEATURE_PHATIC_AUTO_SEND=true`, `director.py:474/515` → `turn_orchestrator.py:2517`),
   que es independiente de L1/L2. "Nada se envía solo" es falso hoy, y no por el autónomo.

---

## 6. Pruebas E2 recomendadas (para el Probador), por prioridad

Todas contra Postgres real, `build_app` + `FakeLLM`, observando el **efecto** (llamadas reales del
bot o filas), nunca "se llamó a X". Plantilla de armado: `tests/audit/test_C_SHADOW_01.py`
(`_settings()` con `Settings.model_construct`, `_app_y_vip`, `SpyBotSession` para ver el envío
saliente). `build_app` **no acepta** inyectar el actuador (`composition.py:438-447` usa
`AiogramTelegramActuator`), así que la observación va por `SpyBotSession` como en C-SHADOW-01.

| Orden | Prueba | Qué mide | Por qué primero |
|---|---|---|---|
| 1 | **Matriz L1 × L2 (4 celdas)** con `global_mode="supervised"`: (L1 off, auto_send off) → cola; (L1 off, auto_send on) → cola; (L1 on, auto_send off) → cola **y** `reason=autonomous_mode_disabled` en la aprobación; (L1 on, auto_send on) → **envío real** (`send_message` en `SpyBotSession` + `turns.status='delivered'` + fila de historial) | Que el envío ocurre **solo** en la celda que debe | Es la promesa central del encendido. Sin esto no hay verde |
| 2 | **Atención bajo `GLOBAL_MODE=autonomous`** (mensaje de canal atencion, `vip_id=None`) | Que **no** hay `send_message` y que el turno termina en `pending_approval` | Es el invariante de seguridad que el docstring promete; hoy solo hay tests unitarios del resolver (`test_turn_orchestrator.py:4219-4325`), ninguno de la entrega |
| 3 | **Contaminación de C3 (P-1)**: entregar un turno, forzar que un mensaje posterior lo supersede **antes** de que la fila reciba señal, y verificar si `vip_signal` se escribe sobre un turno no entregado y si `vip_trust_budget` se mueve | Si la confianza sube por una reacción a un turno que el VIP nunca recibió | Es la entrada del gate §8 y ya hay 173 casos en producción. Si confirma, el gate mide mal |
| 4 | **`autonomous_send_rate` (P-2)**: con L1 on + 0 VIPs activados, correr `MetricsService.aggregate_week` y leer `week_metrics` | Que la tasa reportada a la dueña cuenta decisiones `send` que terminaron en cola | Dato de decisión del negocio; verificación barata y determinista |
| 5 | **Entrega cancelada (P-4/P-7)**: cancelar la entrega autónoma mid-flight (mensaje nuevo del VIP o `cancel_pending` de la dueña) | Estado final del turno y **si la dueña recibe algún aviso**; si el mensaje alcanzó a salir, si quedó fila de historial | Cierra la duda "¿el envío falla y nadie se entera?" |
| 6 | **Fallo duro de la entrega (P-3)**: hacer fallar `insert_pending` (o el store de entregas) y capturar el estado del turno | Que el turno queda no terminal y que solo hay `business_handler_error` | Define si hace falta un aviso o un vigilante |
| 7 | **Envío partido (P-6)**: borrador largo (`allow_split=true`) con fallo en el 2.º segmento | Que el VIP recibió el 1.º y que el historial quedó vacío | Borde realista con `FEATURE_ADVANCED_BEHAVIOR=true` |
| 8 | **Activación sin L1 (H-6 de la ficha de banderas)**: tocar Activar con L1 off y luego encender L1 | Que el VIP activado empieza a enviar sin re-evaluar el gate, y qué texto vio la dueña en el medio | Riesgo operativo de la secuencia real de encendido |
| 9 | **`localize_reason` (P-9)**: aprobación degradada por L2 | Que el DM muestra el token crudo `autonomous_mode_disabled` | Cosmético pero visible; verificación de una línea |
| 10 | **Sabotaje E3**: apagar a mano `is_autonomous_enabled` (devolver `True` siempre), quitar el guard de `None`, y hacer que la entrega corra antes del chequeo de congelación | Que cada prueba 1-2 falla exactamente por el motivo correcto | Sin sabotaje no hay verde (regla de oro del kit) |

---

## 7. Lo que no se pudo comprobar (⚪)

- ⚪ El **comportamiento en vivo al encender L1**: no se encendió nada (prohibido por la tarea).
  Todo lo de arriba es lectura de código + conteos de base.
- ⚪ El **contenido** de `turn_outcome_log`, `message_history` y los borradores: sería material de
  conversación (regla PRIORITARIA). Solo se leyeron estados, etiquetas y conteos.
- ⚪ **P-4 y P-7** (cancelación y supersede post-envío): la ventana es estrecha y no la pude
  provocar sin ejecutar el sistema; quedan como sospechas razonadas + `archivo:línea`, no como
  fallas confirmadas. Las pruebas 5 y 7 las cierran.
- ⚪ **P-3**: no pude reproducir el fallo de `insert_pending`; es una lectura del código (la
  inserción está fuera del `try` de `_deliver_core`).
- ⚪ No verifiqué si los 552 turnos con fila de `turn_outcome_log` cubren **todos** los turnos
  entregados de la ventana (sería trabajo del vigilante V2, que ya existe: ver
  `audit/FASE2-VIGILANTE.md`).
- ⚪ El historial de git del `.env` (fuera de control de versiones): no se usó como evidencia.
