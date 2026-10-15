# C-AUT-03 — El círculo se cierra con la reacción del VIP (C3)

ID:            C-AUT-03
Promesa:       Después de una entrega, el siguiente mensaje del VIP (dentro de la ventana de
               reacción) o su silencio queda registrado como `vip_signal` en `turn_outcome_log`
               y ajusta la confianza del VIP; nunca se cuenta dos veces la misma señal.
Fuente:        docs/SPEC-AUTONOMIA-CALIBRACION.md §4 C3 y §7 (`vip_signal`);
               AGENTS.md §3 flujo 4.18; hueco declarado por audit/contracts/C-SHADOW-01.md
               ("Sin cubrir: la reacción del VIP (C3, `vip_signal`)").
Disparador:    (a) hook inmediato: llega un mensaje del VIP y hay una fila de resultado del
               mismo chat con `vip_signal` nulo dentro de la ventana; (b) job de respaldo
               horario: la ventana ya cerró y sigue sin señal → `silence` o clasificación por
               texto.
Efecto:        `turn_outcome_log.vip_signal` pasa de `NULL` a `positive` / `neutral` /
               `negative` / `silence`; y el evento de confianza correspondiente
               (`record_outcome(event="signal")`: `positive` +0.05, `negative` −0.20,
               `neutral`/`silence` sin cambio). Idempotente por valor de señal.
Banderas:      `FEATURE_AUTONOMY_QUALITY_ENABLED` (hoy `true`) → OFF: `outcome_log=None` en el
               orquestador (`composition.py:1282-1284`) y el job no arranca (`main.py:382-388`):
               sin hook, sin job, sin señal.
               `FEATURE_TRUST_BUDGET` (hoy `true`) → OFF: la señal se escribe en la fila pero
               no ajusta confianza.
               `OUTCOME_REACTION_WINDOW_HOURS` (hoy 6) define la ventana.
Camino (estático, SIN ejecutar; el cableado se verificó leyendo código y conteos de base):
  1. Hook inmediato: `turn_orchestrator.py:2113` → `_run_outcome_reaction` (`:954-1002`):
     busca la fila pendiente del chat (`find_pending_signal_for_chat`, `:977`) y clasifica
     (`classify_reaction`, `:984`) → `record_reaction` (`:987`).
  2. `find_pending_signal_for_chat` (`outcome_log_service.py:277-283`) → repo
     (`turn_outcome.py:338-361`): fila del chat con `vip_signal IS NULL` y `created_at >= since`,
     más reciente. **Ojo: no exige que el turno haya sido entregado** (raíz de H-AUT3-3).
  3. `classify_reaction` (`outcome_log_service.py:285-291`) → `ReactionSignalClassifier`.
  4. `record_reaction` (`:422-452`): si `current.vip_signal == vip_signal` → no-op (`:440-441`);
     si cambia, `update_signal` + evento de confianza `record_outcome(event="signal")`
     (`:444-446`).
  5. Job de respaldo: `jobs/outcome_reaction.py:64-115` (`run_outcome_reaction_cycle`):
     `list_signal_pending` → sin follow-up del VIP en la ventana → `silence` (`:98`); con
     follow-up → clasifica el texto (`:101-102`). Arrancado por `main.py:380-404` solo con el
     flag de calidad ON.
  6. Confianza: `TrustBudgetService.record_outcome` (`trust_budget_service.py:371-385`);
     `positive` → `+0.05`, `negative` → `−0.20`, `neutral`/`silence` → sin cambio.
Puntos ciegos: los del original (dos niveles de `except` que tragan; el ancla del job puede
               quedar vieja; `list_signal_pending` sin tope de antigüedad; clasificación más
               débil cuando el follow-up no pasó por ningún hook; la ventana no se reabre al
               reabrir un turno desde un falso positivo). Sigue sin prueba ninguno.
Prueba E2:     PENDIENTE. No existe `tests/audit/test_C_AUT_03.py` ni ninguna prueba de efecto de
               este contrato. Lo que hay es evidencia viva de que el cableado corre:
               `turn_outcome_log` con 552 filas y 551 con `vip_signal` (positive 341 · silence
               165 · neutral 30 · negative 15). Eso demuestra que la señal SE ESCRIBE; NO
               demuestra que se escriba sobre el turno correcto, ni la idempotencia.
Sabotaje E3:   PENDIENTE (no hay prueba que sabotear).
Vigilante E4:  PROPUESTO, no desplegado → `audit/AUTONOMIA-INFORME.md` §5: V11 (señales
               colgadas de turnos que nunca se entregaron; hoy no se activa porque da > 0 por el
               defecto conocido) y, a futuro, el cruce con el V2 ya existente.
Nivel:         E0 (código y doc) + conteos de la base real. Sin E2/E3. Sin vigilante.
Semáforo:      ⚪ **sin verificar** (hueco declarado en C-SHADOW-01), con un defecto MEDIDO en
               producción.
Hallazgos:
  - H-AUT3-3 (MEDIDO EN PRODUCCIÓN, 2026-10-09 — el hallazgo más grave del camino a la
    autonomía): la señal del VIP se escribe sobre turnos que NUNCA se entregaron. De las 341
    señales "positivas", 184 (54 %) cuelgan de turnos que no salieron al VIP: 173 en turnos
    reemplazados por un mensaje posterior (superseded) y 11 en turnos escalados. Cada una suma
    +0,05 a la confianza del VIP. La ventana elige la última fila del chat con señal nula sin
    exigir entrega (paso 2 del camino). Estimación: de los 3 pares (VIP, categoría) que hoy
    superan 0,90, uno (Hug Vbs / informativo, 0,920) caería a ~0,55 sin esa evidencia; los otros
    dos se sostienen.
  - H-AUT3-1 (código): es exactamente el hueco que C-SHADOW-01 declara "sin cubrir". El cableado
    existe y corre; no hay prueba de efecto ni vigilante.
  - H-AUT3-2 (código): dos niveles de silencio en el camino de la señal; un fallo deja la
    confianza sin ajustar sin aviso salvo journal (y el journal no lo lee la dueña).
  - Efecto de producto combinado: la única condición de la puerta que hoy podría abrirse (la
    confianza) se calcula, en parte, sobre reacciones a mensajes que el VIP no recibió. La
    condición de coincidencia (92,8 % < 95 %) es la que está frenando el encendido; sin ella, la
    puerta se habría abierto con evidencia inflada.
  - Pendiente de método: la prueba E2 de este contrato (atribución al turno correcto + no
    duplicación) es la ronda que falta para poder reportar este contrato en verde o en rojo.
