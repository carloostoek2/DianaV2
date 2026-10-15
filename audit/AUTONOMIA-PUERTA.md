# Auditoría E2/E3 — la puerta de recomendación y el ajuste de confianza

Fecha: 2026-10-09. Alcance: `C-AUT-02` (puerta de recomendación: tres condiciones,
`activate`, "activar no envía") y `C-AUT-04` (vía única de confianza), más los hallazgos
H-1, H-2 y H-6 de `audit/AUTONOMIA-BANDERAS.md`.

Método: pruebas E2 sobre Postgres REAL — copia de la base real restaurada en un contenedor
desechable (`DIANA_E2E_COPY_DUMP=/tmp/diana_audit/fresh_copy.sql`, 36.4 MB, generada
2026-10-09 23:04 UTC). El contenedor se arma con `build_app`; el único simulado es el modelo
de lenguaje externo (`llm/fake.py`) y el actuador de Telegram (registra lo que se habría
enviado, nunca sale de la máquina). Nada de `InMemory*` en lo que el contrato promete
persistir.

```bash
DIANA_E2E_COPY_DUMP=/tmp/diana_audit/fresh_copy.sql sg docker -c \
  "/home/ubuntu/repos/DianaV2/.venv/bin/python -m pytest \
   tests/audit/test_C_AUT_02.py tests/audit/test_C_AUT_04.py -q"
```

Archivos: `tests/audit/test_C_AUT_02.py` (7 pruebas) y `tests/audit/test_C_AUT_04.py`
(2 pruebas parametrizadas = 4 casos).

---

## 1. Resultado

```
e2e DB: copia de la base real (fresh_copy.sql, 36.4 MB, generada 2026-10-09 23:04 UTC)
        restaurada en el contenedor
tests/audit/test_C_AUT_02.py::test_1_falta_la_coincidencia_global PASSED
tests/audit/test_C_AUT_02.py::test_2_falta_la_confianza PASSED
tests/audit/test_C_AUT_02.py::test_3_falta_una_escalacion_de_seguridad PASSED
tests/audit/test_C_AUT_02.py::test_4_las_tres_cumplidas_activa_y_no_envia PASSED
tests/audit/test_C_AUT_02.py::test_5_h1_bandera_de_coincidencia_es_muerta PASSED
tests/audit/test_C_AUT_02.py::test_6_h6_activar_dice_activado_aunque_el_maestro_este_apagado PASSED
tests/audit/test_C_AUT_02.py::test_7_con_la_recomendacion_apagada_activate_no_escribe PASSED
tests/audit/test_C_AUT_04.py::test_5_una_sola_via_de_confianza[readiness_on] PASSED
tests/audit/test_C_AUT_04.py::test_5_una_sola_via_de_confianza[readiness_off] PASSED
tests/audit/test_C_AUT_04.py::test_6_h2_readiness_on_con_quality_off_congela_la_confianza[quality_on] PASSED
tests/audit/test_C_AUT_04.py::test_6_h2_readiness_on_con_quality_off_congela_la_confianza[quality_off] PASSED

======================== 11 passed, 1 warning in 8.50s =========================
```

Estado real de la copia al arrancar (medido con el mismo servicio del panel, no con SQL
suelto): ventana de 14 días con **94 turnos terminados**, 65 aciertos / 5 desacuerdos /
21 conservadoras → **coincidencia 92.86 %** (meta 95 %), **0 escalaciones por seguridad**,
**15 VIP activos**, **0 con `auto_send`**, 552 filas en `turn_outcome_log`, 31 en
`vip_trust_budget`. La confianza máxima real es 1.0.

---

## 2. Tabla de escenarios

| # | Escenario | Esperado | Real (medido en filas) | ¿Pasa? |
|---|---|---|---|---|
| C-AUT-02 | | | | |
| 1 | Coincidencia global < 95 % (confianza 0.95, 0 escalaciones) | `ready=False`, motivo solo por coincidencia, `activate` no escribe | `ready=False`; `rate=0.929 < 0.95`; motivo `Faltan: coincidencia global 93% < 95%.`; `activate → (False, mismo motivo)`; `vips.auto_send=false`; 0 llamadas a Telegram | ✅ |
| 2 | Confianza 0.45 (coincidencia ≥ 95 %, 0 escalaciones) | `ready=False`, motivo solo por confianza | `best_trust=0.45`; `rate ≥ 0.95` (forzada con 32 aciertos propios); motivo `Faltan: confianza 0.45 < 0.90.`; `vips.auto_send=false` | ✅ |
| 3 | 1 escalación de seguridad (confianza y coincidencia OK) | `ready=False`, motivo solo por seguridad | `global_safety_escalations=1` (el Decisor sombra real re-decide el turno sembrado con `safety=0.1` y da `safety_below_threshold`); motivo `Faltan: 1 escalación(es) de seguridad.`; `vips.auto_send=false` | ✅ |
| 4 | Las tres condiciones cumplidas | `ready=True`; `activate` escribe `auto_send=true`; no envía | `ready=True`; `activate → (True, "Activado el envío autónomo para Puerta lista.")`; `select auto_send` = **true**; 0 envíos antes y después | ✅ |
| 5 | Lo que ve la dueña en el panel | LISTO / en camino + motivo | `Puerta lista — ✅ LISTO`; `Puerta lejos — ⏳ en camino` + `Faltan: confianza 0.45 < 0.90.` | ✅ |
| 6 | H-1: bandera de coincidencia ON vs OFF | Sin efecto (bandera muerta) | Resumen idéntico en los 6 campos (`n=94`, `65/5/21`, `rate=0.9286`) y mismo conteo de seguridad; con OFF la coincidencia **se sigue calculando** (n>0, rate no nulo). Escaneo del código: el token `autonomy_coincidence` solo aparece en `src/diana/config/settings.py` y `src/diana/config/banderas_nucleo.py` | ✅ |
| 7 | H-6: L1 apagado (`FEATURE_AUTONOMOUS_MODE=false`) con `auto_send=true` | "Activado" pero nada se envía; con L1 encendido sí | `activate → (True, "Activado…")` y `auto_send=true` con L1 `false`; turno real del VIP → `pending_approval` y **0 mensajes** al chat del VIP. Contraste con L1 `true`: mismo VIP, mismo `auto_send` → `delivered` y 1 `SendMessage` al VIP con el borrador autónomo | ✅ |
| 8 | Bandera del panel apagada (`FEATURE_AUTONOMY_RECOMMENDATION_ENABLED=false`) con un VIP que sí cumpliría | `activate` se niega y no escribe | `(False, "La recomendación de autonomía está desactivada …")`; `auto_send=false`; 0 llamadas a Telegram | ✅ |
| C-AUT-04 | | | | |
| 9 | readiness ON: la dueña aprueba y luego corrige | 1 sola vía: +0.05 y −0.20, un evento cada uno | Confianza real `0.50 → 0.55` (`autonomous_count=1`) y `→ 0.35` (`correction_count=1`); ledger `send/approved_as_is` y `corrected/moderate` | ✅ |
| 10 | readiness OFF: mismo turno, mismo aprobar/corregir | Doble conteo: +0.10 y −0.40 | `0.50 → 0.60` (`autonomous_count=2`) y `→ 0.25` (`autonomous_count=3`, `correction_count=2`) | ✅ |
| 11 | H-2 con quality ON (contraste) | La confianza se mueve y el ledger se escribe | `0.55` / `0.35`; `turn_outcome_log` presente; orquestador y admin SÍ reciben el servicio de medición | ✅ |
| 12 | H-2: readiness ON + `FEATURE_AUTONOMY_QUALITY_ENABLED=false` | Congelada, sin aviso | `0.50 → 0.50 → 0.50` (`autonomous_count=0`, `correction_count=0`); **sin** fila en `turn_outcome_log`; `orchestrator._outcome_log is None` y `admin._outcome is None`; **cero** WARNING/ERROR de `diana.application`/`diana.telegram`/`diana.composition` sobre confianza/outcome/autonomía | ✅ |

Notas de escenario (por qué los datos propios y no los reales):

- Las condiciones 2 y 3 de la puerta son **globales** (no por VIP), así que cada prueba
  ajusta la ventana con turnos propios (chat e ids propios) y los borra al terminar; nunca
  se toca una fila real. La cantidad de turnos se calcula en la prueba a partir del estado
  real, no está fijada a mano.
- Los turnos sembrados son data de escenario, no dobles: el panel los relee con la misma
  consulta real (`list_finished_source_turns`) y los re-decide con el Decisor sombra real.
  El turno de H-6 y los de C-AUT-04 se producen por el camino real (`business_message` por
  el dispatcher + botón/techo de la dueña).
- Si una copia futura trae escalaciones de seguridad reales en la ventana, los casos "todo
  cumplido" (4, 6, 7, y el contraste de 2/3) **se saltan con motivo explícito** en vez de
  pasar en falso: sin borrar datos reales, la puerta no podría abrirse de verdad.

---

## 3. Detalle por contrato

### C-AUT-02 — la puerta de recomendación (E2)

- `ready` es exactamente `best_trust >= 0.90 AND global_rate is not None AND
  global_rate >= 0.95 AND global_safety_escalations == 0`: los tres casos "dos de tres"
  dan `ready=False` con el motivo apuntando SOLO a la condición que falta (se asertó
  además la ausencia de menciones a las otras dos, para que el motivo sea informativo de
  verdad).
- `activate` con `ready=False` devuelve el motivo y no escribe `vips.auto_send` (leído de
  la DB); con `ready=True` lo escribe.
- Activar no envía: el actuador no recibe ni una llamada (ni antes ni después) y el turno
  real posterior de ese VIP depende del interruptor maestro, no del botón.
- La condición de seguridad se cuenta sobre las comparativas **recomputadas en sombra**
  (H-AUT2-1): el test 3 lo confirma por construcción — la escalación solo entra al conteo
  cuando la re-decisión sombra marca `safety_below_threshold`; una escalación real por
  `risk_high` no suma ahí.

### C-AUT-04 — la vía única de confianza (E2)

- Con `FEATURE_AUTONOMY_READINESS_ENABLED=true` la huella de confianza es **exactamente un
  evento por resolución** (`record_outcome`): +0.05 al aprobar y −0.20 al corregir. Los
  contadores (`autonomous_count=1`, `correction_count=1`) lo confirman; la vía sombra no
  aporta ninguno.
- Con la bandera en OFF la huella es el doble conteo documentado (`+0.10` / `−0.40`,
  `autonomous_count=2` y `correction_count=2`). Es la contraprueba de que la prueba mide
  un efecto real y no una constante.
- Precondición verificada en ambos casos: el turno se clasifica `fatico` con
  `would_autonomous=true` (sin eso, la vía sombra no existiría y la contraprueba OFF sería
  vacua), el veredicto sombra es `send` y la corrección persistió
  (`feature_staging_enabled`, requerido para que el decremento por corrección dispare).
- La confianza de partida se siembra en 0.50 y todas las cifras quedan lejos del clamp
  [0,1] (si tocara el techo o el piso, el delta no sería medible).

---

## 4. Sabotajes (E3) — cada prueba puede fallar

Cada sabotaje es una edición mínima de código de producción, la corrida, y la reversión
inmediata (`git checkout --`). El árbol de `src/` quedó limpio (verificado con
`git status --porcelain src/diana` → vacío).

| # | Sabotaje (archivo) | Esperado | Resultado real |
|---|---|---|---|
| S1 | Quitar `and global_safety_escalations == 0` de `VipReadiness.ready` (`autonomy_readiness_service.py:80-85`) | Falla el caso de seguridad | `1 failed` → **test_3_falta_una_escalacion_de_seguridad** (los otros 5 pasan: localiza la condición exacta) |
| S2 | Quitar `and global_rate >= match_rate_min` | Falla el caso de coincidencia | `1 failed` → **test_1_falta_la_coincidencia_global** |
| S3 | Quitar `self.meets_confidence and` | Falla el caso de confianza | `1 failed` → **test_2_falta_la_confianza** |
| S4 | Hacer que `activate` ignore `readiness.ready` (`:321-322`) | Debe escribir `auto_send` cuando no corresponde | `3 failed` → tests 1, 2 y 3 |
| S7 | Quitar el guard `if not self._recommendation_enabled` de `activate` (`:313-317`) | Falla el caso de bandera apagada | `1 failed` → **test_7_con_la_recomendacion_apagada_activate_no_escribe** |
| S5 | Quitar `if self._autonomy_readiness: return` del orquestador (`turn_orchestrator.py:864`) | El incremento sombra vuelve a aplicar | `3 failed` → test_5[readiness_on], test_6[quality_on] y test_6[quality_off] |
| S6 | Quitar `if not self._autonomy_readiness:` del admin (`admin_service.py:904`) | El decremento por corrección se duplica | `3 failed` → test_5[readiness_on], test_6[quality_on] y test_6[quality_off] |

Salidas crudas (extractos):

```
FAILED tests/audit/test_C_AUT_02.py::test_3_falta_una_escalacion_de_seguridad - ...
1 failed, 5 passed    # S1
FAILED tests/audit/test_C_AUT_02.py::test_1_falta_la_coincidencia_global - Assertion...
1 failed, 5 passed    # S2
FAILED tests/audit/test_C_AUT_02.py::test_2_falta_la_confianza - AssertionError...
1 failed, 5 passed    # S3
FAILED ... test_1_falta_la_coincidencia_global / test_2_falta_la_confianza /
        test_3_falta_una_escalacion_de_seguridad
3 failed, 3 passed    # S4
FAILED ... test_7_con_la_recomendacion_apagada_activate_no_escribe
1 failed, 6 passed    # S7
FAILED ... test_5_una_sola_via_de_confianza[readiness_on] /
        test_6_h2...[quality_on] / test_6_h2...[quality_off]
3 failed, 1 passed    # S5 y S6 (mismo conjunto)
```

S5 deja además una observación útil: al quitar el guard de readiness, el caso H-2
(`quality=off`) también falla, es decir **el congelamiento de H-2 depende por completo de
ese guard** (el incremento sombra no está gobernado por la bandera de calidad).

---

## 5. Veredicto sobre los hallazgos

**H-1 — `FEATURE_AUTONOMY_COINCIDENCE_ENABLED` es una bandera muerta: CONFIRMADO.**
Evidencia doble. (a) Comportamiento: dos contenedores con la bandera en ON y OFF producen
el mismo resumen de coincidencia en los seis campos y el mismo conteo de seguridad, y con
la bandera en OFF la coincidencia **sigue calculándose** (no se "desactiva" nada).
(b) Código: el token `autonomy_coincidence` solo aparece en `config/settings.py` y
`config/banderas_nucleo.py` (definición y clasificación de catálogo); ningún módulo la lee.
No se refutó nada del hallazgo. Efecto práctico: apagarla no cambia ni la medición ni la
puerta; el único gate de render es `FEATURE_AUTONOMY_RECOMMENDATION_ENABLED`.

**H-2 — readiness ON + quality OFF congela la confianza en silencio: CONFIRMADO.**
Con `FEATURE_AUTONOMY_READINESS_ENABLED=true` y `FEATURE_AUTONOMY_QUALITY_ENABLED=false`,
un turno real aprobado y otro corregido por la dueña dejan `vip_trust_budget` **idéntico**
(`0.50`, contadores en 0), no hay fila en `turn_outcome_log`, el orquestador y el admin no
reciben el servicio de medición, y no aparece **ningún** WARNING/ERROR de la aplicación
sobre confianza/outcome/autonomía. Contraste con quality ON: `0.55` y `0.35`. La puerta de
recomendación queda cerrada para ese VIP (su confianza nunca alcanza 0.90) sin que nadie se
entere. Es el hallazgo más importante de esta tanda y no está refutado: apagar la medición
de calidad para "dejar de medir" apaga también, sin aviso, la única vía de ajuste que la
bandera de readiness dejó viva.

**H-6 — el botón Activar dice "Activado" con el maestro apagado: CONFIRMADO.**
Con L1 (`FEATURE_AUTONOMOUS_MODE`) en `false`, `activate` escribe `vips.auto_send=true` y
responde "Activado el envío autónomo para <VIP>". Un mensaje real de ese VIP queda en
`pending_approval` (cola de la dueña) y **no sale ni un mensaje** hacia el VIP. El contraste
con L1 en `true` (mismo VIP, mismo `auto_send`) da `delivered` y un `SendMessage` con el
borrador autónomo: la diferencia es exactamente el interruptor maestro. La confusión que
describe el hallazgo es real: el texto del panel ("nada cambia hasta que tú lo actives")
refuerza la creencia de que basta el botón.

No apareció ningún hallazgo nuevo más allá de H-1/H-2/H-6 y de lo ya anotado en
`C-AUT-02.md` (el conteo de seguridad sale de las comparativas recomputadas, no del
contador dedicado `count_safety_escalations_since`).

---

## 6. Lo que NO se pudo comprobar (⚪)

- ⚪ El clic real en el menú de Telegram (`menu.py:967-1022`) no se recorrió de punta a
  punta: las pruebas llaman a `AutonomyReadinessService.activate` / `render_by_vip`, que es
  exactamente lo que invoca el handler, pero no pasan por el `CallbackQuery` del menú ni
  arman el teclado `menu_autonomy_vip_keyboard`. La promesa "el botón solo se habilita con
  las tres" se verificó en el render ("✅ LISTO" vs "⏳ en camino" + motivo), no en la
  construcción del teclado.
- ⚪ `readiness_snapshot` (el bloque "Autonomía" del DM de borrador, y su degradación
  silenciosa a `has_history=False` cuando falla la DB) quedó sin prueba.
- ⚪ `FEATURE_TRUST_BUDGET=false` (sin budget cableado, ninguna vía de ajuste) no se probó.
- ⚪ La reacción del VIP (C3) y su job de respaldo (`jobs/outcome_reaction.py`) no se
  probaron: en el escenario de C-AUT-04 la señal clasificada fue neutra/silencio y así se
  asertó, precisamente para que no contaminara la medición exacta.
- ⚪ No se encendió nada en el sistema real: L1 solo se encendió dentro del contenedor de
  prueba con actuador simulado. No se leyó ningún log de conversación (regla PRIORITARIA);
  solo conteos y filas de configuración/medición.
- ⚪ El vigilante E4 propuesto en los dos contratos sigue sin existir (no hay nada que
  alerte de "la medición dejó de escribir" ni de "la combinación readiness ON + quality
  OFF"); la auditoría lo confirma como ausencia, no como defecto de esta tanda.
