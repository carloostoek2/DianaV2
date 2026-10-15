# Auditoría de la matriz de banderas — camino a la autonomía

Fecha: 2026-10-09. Alcance: las banderas que gobiernan el envío autónomo (doble puerta L1/L2),
la capa de medición "Fila 4" y las banderas con las que interactúa (trust budget, umbrales,
vigilante de contratos). No se modificó ningún valor.

Fuentes de verdad usadas:

- `.env` real (raíz del repo), leído con `diana.config.settings.Settings`.
- `src/diana/config/settings.py` (defaults del código).
- `src/diana/config/banderas_nucleo.py` (clasificación núcleo / fuera de catálogo).
- `src/diana/composition.py` (cableado raíz).
- `system_config` en la base de producción (solo claves de configuración y conteos; no se leyó
  ningún log de conversación).
- Salida real del proceso: `runtime/banderas_arranque.json` y journald de `diana-bot`.

El proceso corre desde el árbol de trabajo (`systemctl --user cat diana-bot`: `WorkingDirectory=/home/ubuntu/repos/DianaV2`,
sin `EnvironmentFile` ni `Environment=` de banderas), así que el `.env` del repo es la fuente
efectiva: no hay override por systemd.

---

## 1. Tabla maestra (camino a la autonomía)

Valor en `.env` = valor real; "settings" = default del código (red de seguridad de entorno fresco).
Efectivo = lo que devuelve `Settings()` con el `.env` real (verificado por ejecución).

### 1.1 Doble puerta

| Variable | `.env` | settings (default) | efectivo | Efecto si está apagada | Declarada | Riesgo |
|---|---|---|---|---|---|---|
| `FEATURE_AUTONOMOUS_MODE` | `false` (`.env:72`) | `False` (`settings.py:131`) | `False` | Nadie envía solo por el Decisor: `is_autonomous_enabled` → `False` (`autonomous_mode_service.py:59`) y el `send` se degrada a `approve` (`turn_orchestrator.py:2845`). | Fuera de catálogo como kill-switch (`banderas_nucleo.py:171-174`). Correcto, pero ver H-5. | Bajo (es su estado correcto). El riesgo real es de visibilidad, no de comportamiento. |
| `vips.auto_send` (L2, columna de DB, no bandera) | — | `False` por VIP | **0 VIPs con `true`** (consultado en producción) | Aun con L1 encendido y `GLOBAL_MODE=supervised`, ningún VIP autoenvía. | No aplica. | Medio: encender L1 no cambia nada hasta que la dueña active VIP por VIP (o ponga `GLOBAL_MODE=autonomous`, que ignora el L2). |

### 1.2 Fila 4 (medición y recomendación)

| Variable | `.env` | settings (default) | efectivo | Efecto si está apagada | Declarada | Riesgo |
|---|---|---|---|---|---|---|
| `FEATURE_AUTONOMY_READINESS_ENABLED` | `true` (`.env:100`) | `False` (`settings.py:239`) | `True` | Único efecto real: deja de desactivar los incrementos sombra de trust (`turn_orchestrator.py:864` y `admin_service.py:904`). **No** apaga el panel. Ver H-4. | Fuera de catálogo: "solo mide (shadow)" (`banderas_nucleo.py:198`). | Medio: el nombre sugiere gobernar la capa de medición y en realidad gobierna la fuente del trust. |
| `FEATURE_AUTONOMY_COINCIDENCE_ENABLED` | `true` (`.env:101`) | `False` (`settings.py:241`) | `True` | **Nada.** Ningún módulo la lee. Ver H-1. | Fuera de catálogo: "solo mide (shadow)" (`banderas_nucleo.py:199`). | **Alto: bandera muerta presentada como control activo.** |
| `FEATURE_AUTONOMY_QUALITY_ENABLED` | `true` (`.env:102`) | `False` (`settings.py:243`) | `True` | No se cablea `outcome_log` al orquestador ni al admin (`composition.py:853`, `:1283`), no se arma scorer ni clasificador (`:722`, `:729`), no arranca el job C3 (`main.py:383`) y desaparece la sección de gravedad de la ficha (`:1415`). Es la bandera que **de verdad** prende la Fila 4. | Fuera de catálogo: "solo mide" (`banderas_nucleo.py:200`). | Bajo hoy (ON). Alto si se apaga con readiness ON: ver H-2. |
| `FEATURE_AUTONOMY_RECOMMENDATION_ENABLED` | `true` (`.env:103`) | `False` (`settings.py:245`) | `True` | El panel 🧭 desaparece del menú (`menu.py:579-581`), se omite la sección Autonomía del DM de borrador (`composition.py:858-862`) y `activate()` se niega (`autonomy_readiness_service.py:313`). | Fuera de catálogo: "solo mide y recomienda; nunca envía por su cuenta" (`banderas_nucleo.py:201-203`). | Bajo. |

### 1.3 Relacionadas

| Variable | `.env` | settings (default) | efectivo | Efecto si está apagada | Declarada | Riesgo |
|---|---|---|---|---|---|---|
| `FEATURE_TRUST_BUDGET` | `true` (`.env:90`) | `False` (`settings.py:223`) | `True` | El servicio se construye siempre pero no se inyecta (`composition.py:848`, `:1277`, `:1401`): no hay incrementos ni decrementos por categoría. Con readiness ON, el trust quedaría congelado. | Fuera de catálogo: "solo mide" (`banderas_nucleo.py:194`). | Medio. |
| `FEATURE_SEVERITY_TRUST_DECREMENT_ENABLED` | `true` (`.env:93`) | `False` (`settings.py:235`) | `True` | `_decrement_for()` vuelve al escalar fijo 0.20 (`trust_budget_service.py:262-264`). Con readiness ON el camino A está desactivado, pero el camino B (`record_outcome`, evento `label` con severidad, `outcome_log_service.py:381-388`) sigue aplicando el decremento graduado. | Fuera de catálogo: "solo mide" (`banderas_nucleo.py:195-197`). | Bajo. |
| `FEATURE_CONTRACT_WATCHDOG_ENABLED` | `true` (`.env:147`) | `False` (`settings.py:294`) | `True` | No arranca el chequeo diario (`main.py:194`), `/health` marca el vigilante como apagado (`main.py:149`) y deja de vigilar la promesa C-SHADOW-01 (turnos sin fila de sombra). | **Núcleo** (`banderas_nucleo.py:142-145`). | Bajo. Es hoy la única red que detectaría que la Fila 4 dejó de escribir. |
| `FEATURE_EMOTIONAL_DETECTOR_ENABLED` | `true` (`.env:86`) | `False` (`settings.py:176`) | `True` | No se inyecta el detector (`composition.py:1262`); los hooks sombra se saltan sin aviso (`:1200-1204`). | Fuera de catálogo: "solo mide" (`banderas_nucleo.py:190`). | Bajo (shadow). |
| `FEATURE_MOOD_ENGINE` | `true` (`.env:89`) | `False` (`settings.py:211`) | `True` | No se inyecta el motor de mood (`composition.py:1274`, `:1642`). | Fuera de catálogo: "solo mide" (`banderas_nucleo.py:193`). | Bajo (shadow). |
| `FEATURE_PHATIC_AUTONOMY` | `true` (`.env:88`) | `False` (`settings.py:195`) | `True` | No se inyecta el clasificador (`composition.py:1271`): no hay `would_autonomous` y el trust por categoría queda inerte (advertencia explícita en `composition.py:1293`). | Fuera de catálogo: "solo mide" (`banderas_nucleo.py:192`). | Bajo (shadow). Bien cubierto: hay warning de la combinación. |
| `FEATURE_PHATIC_AUTO_SEND` | `true` (`.env:75`) | `False` (`settings.py:208`) | `True` | Los saludos/check-in puros vuelven a la cola de aprobación (`turn_orchestrator.py:2578-2599`). | **Núcleo** (`banderas_nucleo.py:162-165`). | Bajo. **Pero es envío real vivo hoy, sin AMS: ver H-7.** |
| `FEATURE_SANDBOX_AUTO_SEND` | `true` (`.env:61`) | `False` (`settings.py:123`) | `True` | El sandbox vuelve a pedir aprobación (`turn_orchestrator.py:1279`, `:1604`, `:2195`). | Fuera de catálogo: superficie de prueba (`banderas_nucleo.py:181-183`). | Bajo (solo chats con sandbox activo). |
| `FEATURE_CALIBRATION_ENABLED` | `false` (`.env:73`) | `False` (`settings.py:134`) | `False` | No corre el job (`main.py:370`); `calibrate_thresholds` sale con `status="disabled"` (`calibration_service.py:141-143`). `detect_drift` sigue siendo de solo lectura. | Fuera de catálogo: kill-switch que espera a operaciones (`banderas_nucleo.py:175-177`). | Bajo hoy. **Alto si se enciende: ver H-3.** |

Nota de coherencia valor/comentario: en el bloque de autonomía **no se encontró ninguna bandera
cuyo valor contradiga su comentario**. Los dos `false` explícitos (`.env:72` para el maestro y
`.env:73` para calibración) están bajo el comentario correcto ("Explicit kill-switches (stay off
until ops is ready)"), y el bloque de Fila 4 (`.env:95-103`) dice con precisión que nada envía solo.

---

## 2. Cableado por bandera (¿el flujo existe pero nadie lo recibe?)

- `FEATURE_AUTONOMY_COINCIDENCE_ENABLED`: **no se lee en ninguna parte**. La búsqueda
  `grep -rn "autonomy_coincidence" src/ tests/` devuelve solo su definición (`settings.py:241`) y
  su exclusión de catálogo (`banderas_nucleo.py:199`). La capacidad de "coincidencia" que la
  bandera parece gobernar en realidad corre siempre: `OutcomeLogService` se construye sin
  condición (`composition.py:717`), `source=turn_outcome_repo` no está gateado, y
  `coincidence_summary`/`list_comparativas` (`outcome_log_service.py:181-215`) no consultan
  ninguna bandera. Solo el **render** del panel está gateado, y por
  `feature_autonomy_recommendation_enabled` (`menu.py:579-581`).
- `FEATURE_AUTONOMY_READINESS_ENABLED`: dos únicos usos — `composition.py:855` (se pasa a
  `AdminService`) y `:1285` (se pasa al orquestador). El efecto declarado en AGENTS.md §4.18
  **existe y se verificó**:
  - `turn_orchestrator.py:864` → `if self._autonomy_readiness: return` antes de
    `record_autonomous`;
  - `admin_service.py:904` → `if not self._autonomy_readiness:` antes de `record_correction`.
  No hay ningún otro consumidor: la bandera **no** gobierna el panel ni la puerta de recomendación.
- `FEATURE_AUTONOMY_QUALITY_ENABLED`: es el gate real de la Fila 4 (scorer, clasificador C3,
  cableado de `outcome_log` en admin y orquestador, job de reacción y `severity_counts`).
- `FEATURE_AUTONOMY_RECOMMENDATION_ENABLED`: gate del panel y de la puerta de recomendación.
- `FEATURE_AUTONOMOUS_MODE`: leído una vez (`composition.py:647`) y repartido a `Decider`,
  `shadow_decider` (siempre ON) y `AutonomousModeService`.
- Consumidor huérfano detectado: `OutcomeLogService.list_outcome_rows_since`
  (`outcome_log_service.py:414`) no tiene llamadores en `src/` (coincide con `audit/WIRING_SCAN.md`
  §1). No es una bandera, pero es flujo de la Fila 4 sin receptor.

---

## 3. `system_config` y override en caliente

**Respuesta directa: `get_feature_flags` NO se llama en producción. Ningún override de la base
prevalece sobre las banderas: prevalece `Settings`/`.env`.**

Evidencia:

- `SqlSystemConfigStore.get_feature_flags` existe (`system_config.py:132`) pero la única aparición
  de su nombre en todo el repo es su propia definición; el comentario de `composition.py:643-644`
  lo confirma ("load_feature_flags removed per review"). La prueba
  `tests/unit/test_composition_wiring.py:212` fija esa decisión.
- El único lector genérico de campos `feature_*` es `aviso_banderas.valores_de_settings`
  (`aviso_banderas.py:69-75`), y se usa solo para el resumen de arranque.

Consecuencia práctica: `system_config` guarda filas `FEATURE_*` **obsoletas y contradictorias con
el `.env`**, que el código ignora por completo:

```
FEATURE_ADVANCED_BEHAVIOR   = False   (.env: true)
FEATURE_GENERAL_MODE_ENABLED= False   (.env: true)
FEATURE_GRAY_ZONE_ENABLED   = False   (.env: true)
FEATURE_PROMO_ENABLED       = False   (.env: true)
FEATURE_SANDBOX_ENABLED     = False   (.env: true)
FEATURE_STAGING_ENABLED     = False   (.env: true)
FEATURE_PERSONA_ADMIN_ENABLED=False   (.env: true)
FEATURE_CONTEXT_ENABLED     = True    (.env: true)
FEATURE_MEMORY_ENABLED      = True    (.env: true)
FEATURE_AUTONOMOUS_MODE     = False   (.env: false)  [coincide por casualidad]
FEATURE_RECONTACT_ENABLED   = False   (.env: false)
FEATURE_CALIBRATION_ENABLED = False   (.env: false)
```

No hay ninguna fila `FEATURE_AUTONOMY_*` en la base. Quien intente auditar el sistema leyendo la
tabla obtendrá un estado falso (por ejemplo, creería que la zona gris está apagada).

Lo que **sí** llega desde la base son los **umbrales**, no las banderas: `autonomous_thresholds`,
`supervised_thresholds` y `eval_thresholds` se leen al arrancar (`composition.py:1687-1703`) y
están sembrados por la migración `006_f3_flags_thresholds` y `001_f1_foundation`. Ver sección 5.

---

## 4. Umbrales: ¿se mezclan?

**Dentro del Decisor, no.** La separación pedida por AGENTS.md §7 se cumple:

- Gate de seguridad P1: `evaluation.safety < float(self._runtime.safety)` — clave suelta `safety`
  (`decider.py:145`).
- Envío autónomo: `safety_min` / `doctrine_min` / `naturalness_min` — claves `*_min`
  (`decider.py:193-202`, `thresholds.py:23-29`).

**Pero el contenedor compartido sí permite que un umbral pise al otro**, en dos rutas:

1. Hidratación de arranque (`composition.py:1692-1703`): lee `supervised_thresholds` y, si trae
   `safety_min`, hace `holder.replace_safety(float(...))` — es decir, **escribe el umbral
   supervisado en el slot del gate P1**. Luego, si `eval_thresholds` trae `safety`, lo vuelve a
   pisar. Hoy la base tiene `eval_thresholds = {"safety": 0.3}` y `supervised_thresholds.safety_min = 0.5`,
   así que el resultado final es 0.3 (el valor correcto). Si algún día desaparece la clave `safety`
   de `eval_thresholds`, el gate P1 queda en 0.5 sin ningún aviso.
2. Calibración (`calibration_service.py:202-206`): al aplicar, hace
   `replace_autonomous(final_auto)` y `replace_safety(float(final_sup["safety_min"]))` — vuelve a
   escribir el umbral **supervisado** en el gate **P1**. Y el `RuntimeThresholds` que recibe
   (`composition.py:1368`) es **el mismo objeto** que usan el Decider vivo y el Decisor sombra
   (`:692`, `:701`, `:710`). Encender `FEATURE_CALIBRATION_ENABLED` mueve por lo tanto el gate de
   escalación por seguridad en caliente, sin reinicio.

Hoy el riesgo está latente porque `FEATURE_CALIBRATION_ENABLED=false` y la base tiene
`eval_thresholds.safety=0.3`. Queda como advertencia para el encendido (H-3).

---

## 5. Chequeo real de banderas (`EstadoBanderas`)

Ejecutado con `Settings()` sobre el `.env` real y `leer_variables_feature()`:

```
encendidas ............ 18
apagadas declaradas ... 1  → FEATURE_HISTORY_REIMPORT_ENABLED
apagadas sin declarar . 1  → FEATURE_RECONTACT_ENABLED
desconocidas .......... 0
declaraciones obsoletas 0
nucleo_total .......... 20
hay_advertencia ....... True
```

- Cobertura del catálogo: `Settings` tiene **37** campos `feature_*`; el catálogo clasifica los 37
  (20 núcleo + 17 fuera). Ninguna bandera de `Settings` quedó sin clasificar, y **ninguna
  `FEATURE_*` del `.env` es desconocida para el código** (0 desconocidas).
- Confirmado en el proceso vivo: `runtime/banderas_arranque.json` trae
  `"ok": false`, `sin_declarar: ["FEATURE_RECONTACT_ENABLED"]`, huella `d6cc0da1170590b3`, y
  journald registra el mismo `WARNING event=banderas_nucleo` en los arranques del 2026-10-09
  (02:52, 03:11, 09:26).
- `FEATURE_AUTONOMOUS_MODE` está clasificada **fuera** del catálogo como kill-switch
  (`banderas_nucleo.py:171-174`). Es una clasificación defendible según el criterio escrito
  (apagada, el negocio no pierde nada: sigue habiendo cola de aprobación), pero tiene una
  consecuencia que conviene tener presente: **encenderla o apagarla no mueve el aviso de arranque
  ni el `ok` de `/health`**, es decir, la bandera que hoy más le importa a la dueña no tiene
  ninguna señal de gobierno (H-5).

---

## 6. Fallbacks silenciosos en los caminos de autonomía

Todos estos puntos degradan sin avisar a la dueña (solo log técnico). El vigilante de contratos
cubre **uno solo** de ellos (V2 de C-SHADOW-01: turnos sin fila de sombra).

| # | Punto | Efecto | Qué ve la dueña | Qué debería ver |
|---|---|---|---|---|
| S-1 | `turn_orchestrator.py:949-952` — `except Exception → log_swallowed("outcome_log_error")` | El turno sigue; no queda fila en `turn_outcome_log` | Nada | Cubierto parcialmente por el vigilante (V2). |
| S-2 | `outcome_log_service.py:330-334` — `record_shadow` traga y devuelve `None` | Segundo nivel de silencio sobre la misma fila | Nada | Ídem S-1. |
| S-3 | `turn_orchestrator.py:999-1002` — `_run_outcome_reaction` traga (`outcome_reaction_error`) | La reacción del VIP no se clasifica en el hook inmediato | Nada | El job C3 (`jobs/outcome_reaction.py`) es el respaldo; si el job también falla y no hay señal, el registro queda sin `vip_signal`. Nada avisa. |
| S-4 | `turn_orchestrator.py:900-903` — trust budget traga (`trust_budget_error`) | El trust por categoría no se mueve | Nada | Nada vigila el trust. |
| S-5 | `outcome_log_service.py:390-394` / `:448-452` — `record_owner_outcome` / `record_reaction` tragan | La decisión de la dueña no queda en el ledger | Nada | Nada vigila `owner_outcome` (el contrato lo declara "sin cubrir", `audit/contracts/C-SHADOW-01.md:26`). |
| S-6 | `outcome_log_service.py:285-291` — sin clasificador, `classify_reaction` devuelve `"neutral"` | Sesgo silencioso hacia neutro en lugar de fallo | Nada | Con `quality=true` el clasificador sí está wired; si el flag se apaga, el sesgo es invisible. |
| S-7 | `jobs/outcome_reaction.py:80-82` y `:105-108` — fallos por ciclo/ítem solo a log | Ventanas de reacción que nunca cierran | Nada | Contador de fallos sin superficie. |
| S-8 | `composition.py:1200-1204` — detector emocional off → dict `{"skipped", "reason"}` | Hook sombra inerte | Nada | Correcto para shadow, pero es otro "off silencioso" del stack. |
| S-9 | `_prepare_autonomous_send`: `autonomous_not_wired` (`:2811`), `autonomous_disabled_for_vip` (`:2836`), `vip_frozen` (`:2861`), `empty_draft` (`:2887`), `autonomous_behavior_not_wired` (`:2911`) | `autonomous_disabled_for_vip` degrada a cola de aprobación (bien); el resto marca el turno `failed` | Solo `vip_frozen` y `empty_draft` notifican (`_safe_notify_info`); `autonomous_not_wired` y `autonomous_behavior_not_wired` **no** notifican | Aviso por configuración rota: "el envío autónomo está encendido pero no está cableado". |
| S-10 | `OutcomeReactionJob` / `ContractWatchdogJob` no arrancan si su bandera está off | Silencio total | `main.py:371`, `:387`, `:195` dejan un `logger.info(..._skipped_flag_off)` | Para el maestro (`FEATURE_AUTONOMOUS_MODE`) no hay ni eso: es off por diseño. |

Riesgo agregado: si la medición de Fila 4 se degrada, el panel 🧭 sigue renderizando números que
parecen válidos (sobre filas viejas) y la puerta de recomendación simplemente nunca abre. No hay
contradicción visible para la dueña. La mitigación disponible es el vigilante de contratos
(`FEATURE_CONTRACT_WATCHDOG_ENABLED=true`), que hoy solo cubre S-1/S-2.

---

## 7. Hallazgos ordenados por gravedad

**H-1 (Alta) — `FEATURE_AUTONOMY_COINCIDENCE_ENABLED` es una bandera muerta.**
Está en `true` (`.env:101`), se documenta como activa (`faltantes.md:33`,
`docs/ESTADO-PROYECTO.md:195`, `audit/contracts/C-SHADOW-01.md:8`) y el catálogo la clasifica como
"solo mide" (`banderas_nucleo.py:199`), pero **ningún módulo la lee**. Apagarla no desactiva nada;
encenderla no enciende nada. La coincidencia real corre siempre (servicio construido sin condición,
`composition.py:717`) y solo su render depende de `FEATURE_AUTONOMY_RECOMMENDATION_ENABLED`.
Qué ve la dueña: nada. Qué debería ver: o la bandera desaparece (y se corrige la documentación),
o pasa a gobernar de verdad la parte de coincidencia del ledger.

**H-2 (Alta) — readiness ON + quality OFF congela el trust en silencio.**
Con `FEATURE_AUTONOMY_READINESS_ENABLED=true`, se desactivan `record_autonomous`
(`turn_orchestrator.py:864`) y `record_correction` (`admin_service.py:904`), dejando a
`record_outcome` como única fuente. Pero `record_outcome` solo corre si `outcome_log` está cableado,
y eso depende de `FEATURE_AUTONOMY_QUALITY_ENABLED` (`composition.py:853`, `:1283`). Si alguien
apaga quality "solo para dejar de medir", el trust deja de moverse, la confianza por VIP queda
congelada y el botón Activar nunca se habilita para VIPs nuevos. No hay ninguna advertencia para
esta combinación (compárese con el warning que sí existe para `trust_budget` + `phatic_autonomy`,
`composition.py:1293-1302`). Hoy no impacta porque ambas están en `true`.

**H-3 (Media) — Encender la calibración mueve el gate de seguridad P1 y los mínimos autónomos en caliente.**
`CalibrationService` comparte el mismo `RuntimeThresholds` que el Decisor vivo y el sombra
(`composition.py:1368` vs `:701`/`:710`) y escribe `replace_autonomous(...)` y
`replace_safety(final_sup["safety_min"])` (`calibration_service.py:203-206`). Es decir: si la dueña
enciende `FEATURE_CALIBRATION_ENABLED`, el umbral **supervisado** `safety_min` pasa a gobernar el
gate P1 de escalación por seguridad, y los mínimos de envío autónomo se recalculan solos. La
hidratación de arranque ya hace un pase equivalente (`composition.py:1692-1703`), hoy neutralizado
porque `eval_thresholds.safety = 0.3` pisa el valor. AGENTS.md §7 prohíbe compartir el umbral de
seguridad entre modos; el Decisor no lo hace, pero el contenedor sí lo permite.
Qué ve la dueña: nada (solo el log `calibration_applied`). Qué debería ver: que el umbral de
seguridad cambió y con qué valor.

**H-4 (Media) — El nombre de `FEATURE_AUTONOMY_READINESS_ENABLED` engaña sobre su efecto.**
Su único efecto es gobernar la fuente del trust (H-2), no la capa de "readiness"/panel. Quien lea
el nombre y la apague creyendo que apaga el panel, en realidad activa el doble conteo de trust que
`admin_service.py:897-904` describe. No hay superficie ni log que explique el cambio.

**H-5 (Media) — La bandera más importante para la dueña no tiene señal de gobierno.**
`FEATURE_AUTONOMOUS_MODE` está fuera del catálogo (`banderas_nucleo.py:171-174`), así que su estado
no aparece en el aviso de arranque, ni en `checks.banderas` de `/health`, ni en ningún handler de
Telegram (`grep` en `src/diana/telegram/` no la menciona). Qué ve la dueña hoy: nada distingue
"autonomía apagada a propósito" de "autonomía encendida y sin ningún VIP activado". Qué debería
ver: el estado de L1 en `/health` y, en el panel 🧭, algo como "llevas X VIPs activados, pero el
envío automático general está apagado".

**H-6 (Media) — El botón Activar dice "Activado" aunque el maestro esté apagado.**
`AutonomyReadinessService.activate` escribe `vips.auto_send=true` y responde "Activado el envío
autónomo para X" (`autonomy_readiness_service.py:323-328`) sin mirar `FEATURE_AUTONOMOUS_MODE`.
Con L1 en `false`, `is_autonomous_enabled` devuelve `False` (`autonomous_mode_service.py:59`) y
**no se envía nada**: el `send` se degrada a `approve` (`turn_orchestrator.py:2845`). El texto del
panel dice "nada cambia hasta que tú lo actives", lo que refuerza la confusión (el "tú lo actives"
es el botón, y el botón no basta). Qué ve la dueña: "Activado". Qué debería ver: "Quedó activado
para este VIP, pero el envío automático general está apagado; nada se enviará solo hasta encenderlo."

**H-7 (Media/baja) — Ya hay envío real sin aprobación hoy, fuera del maestro.**
`FEATURE_PHATIC_AUTO_SEND=true` (`.env:75`) entrega saludos y check-in puros directo al VIP sin
pasar por la cola (`turn_orchestrator.py:2565-2726`, `is_phatic_template_reason` en
`template_gate.py:357-361`), y es independiente de `FEATURE_AUTONOMOUS_MODE` por diseño
(`settings.py:205-208`). `FEATURE_SANDBOX_AUTO_SEND=true` hace lo propio, pero solo en chats con
sandbox activo. Qué ve la dueña: cree que "nada se envía solo" mientras el maestro está apagado.
Qué debería ver: la aclaración de que los saludos puros ya salen solos.

**H-8 (Media/baja) — La base contradice al `.env` en 7 banderas.**
Las filas `FEATURE_*` de `system_config` listadas en la sección 3 no se leen (`get_feature_flags`
sin llamadores, `system_config.py:132`) y varias dicen lo contrario del `.env` (zona gris, staging,
promo, sandbox, advanced behavior, general mode, persona admin: `false` en la base, `true` en el
`.env`). Es documentación ejecutable falsa. Qué ve la dueña: nada. Qué debería ver: o las filas se
limpian, o se rotulan como "no operativas".

**H-9 (Baja) — `FEATURE_RECONTACT_ENABLED=false` es una bandera núcleo apagada sin declarar.**
Es el único "sin declarar" del sistema (`EstadoBanderas` y `runtime/banderas_arranque.json`). El
resultado es que `/health` reporta `ok: false` de forma permanente y el arranque emite un WARNING
en cada proceso. Efecto colateral: el `ok:false` se vuelve normal, lo que debilita la señal cuando
aparezca una bandera núcleo apagada de verdad. No es del camino a la autonomía, pero es el ruido
que hoy tapa esa señal.

**H-10 (Informativo) — Consumidor huérfano en la Fila 4.**
`OutcomeLogService.list_outcome_rows_since` (`outcome_log_service.py:414`) no tiene llamadores;
coincide con `audit/WIRING_SCAN.md` §1. No cambia comportamiento.

---

## 8. Lo que no se pudo comprobar

- ⚪ No se verificó el contenido de `turn_outcome_log` línea por línea (sería material de
  conversación). Solo se leyeron **conteos**: 552 filas totales, 170 en los últimos 14 días,
  204 con `owner_outcome`, 551 con `vip_signal`; `turn_category_log` 812 filas, 52 con
  `would_autonomous=true`; `vip_trust_budget` 31 filas, con valores de hasta 1.0.
- ⚪ No se inspeccionó el historial de git de `.env` para saber desde cuándo cada valor está así:
  el archivo está fuera de control de versiones y solo hay copias `.env.bak-*` en la raíz, que no
  se usaron como evidencia.
- ⚪ No se probó en vivo encender `FEATURE_AUTONOMOUS_MODE` (prohibido por la tarea: solo reportar).

---

## 9. Respuesta a las cinco preguntas de la tarea

1. **Valor real vs. declarado**: no hay contradicción valor/comentario en el camino a la autonomía.
   `FEATURE_AUTONOMOUS_MODE` está correctamente clasificada como kill-switch (no núcleo), con la
   salvedad de H-5. Las cuatro de Fila 4 están clasificadas como "solo mide"; eso es exacto para
   readiness/quality/recommendation, pero **falso en la práctica para `coincidence`** (H-1). No hay
   ninguna `FEATURE_*` del `.env` desconocida para el código (0 desconocidas).
2. **Cableado**: las cuatro de Fila 4 se recorrieron; **una (`coincidence`) no llega a ningún
   consumidor**. El acoplamiento de §4.18 (`readiness` desactiva `record_autonomous` y
   `record_correction`) **existe y está localizado** en `turn_orchestrator.py:864` y
   `admin_service.py:904`.
3. **Apagados silenciosos**: 10 puntos en la sección 6; solo S-1/S-2 están vigilados, y ninguno
   avisa a la dueña por sí mismo.
4. **Umbrales**: no se mezclan dentro del Decisor, pero el contenedor compartido sí permite que el
   `safety_min` supervisado pise el `safety` de P1 (arranque y calibración). Hoy neutralizado por
   `eval_thresholds.safety=0.3`; al encender calibración, no.
5. **Bandera apagada sin declarar**: `FEATURE_RECONTACT_ENABLED` (1). Declaradas a propósito: 1
   (`FEATURE_HISTORY_REIMPORT_ENABLED`). Desconocidas: 0.

---

## 10. Resumen para el encendido de la autonomía

El encendido del envío autónomo **no está bloqueado** por ninguna bandera mal puesta: L1 está en
`false` con el comentario correcto, las cuatro de Fila 4 y sus dependencias están todas en `true`,
la medición tiene datos (170 filas en 14 días) y L2 está vacío (0 VIPs con `auto_send`), así que
activar L1 por sí solo no enviaría nada.

Lo que puede **contaminar** el encendido:

1. H-1 (bandera muerta): la dueña y la documentación creen tener un control de coincidencia que no
   existe. Si alguien "apaga la coincidencia" para no medirla, no pasa nada; si alguien confía en
   que está apagada, tampoco.
2. H-2 (readiness sin quality): apagar quality para "dejar de medir" congela el trust y cierra la
   puerta de recomendación sin aviso.
3. H-3 (calibración): encenderla mueve el gate P1 de seguridad y los mínimos de envío autónomo en
   vivo.
4. H-6 (botón Activar): la dueña puede creer que activó el envío por VIP cuando el maestro sigue
   apagado.
5. H-5: no hay ninguna superficie que le diga el estado del maestro.
