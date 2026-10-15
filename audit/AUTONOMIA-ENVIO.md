# C-AUT-01 — Resultado de la prueba E2

Fecha: 2026-10-09.  Autor: agente de pruebas de contrato (`contract-proof`, nivel E2/E3).
Prueba: `tests/audit/test_C_AUT_01.py`.
Contrato: `audit/contracts/C-AUT-01.md`.

## Cómo se corrió

```
DIANA_E2E_COPY_DUMP=/tmp/diana_audit/fresh_copy.sql \
  sg docker -c "/home/ubuntu/repos/DianaV2/.venv/bin/python -m pytest \
    tests/audit/test_C_AUT_01.py tests/audit/test_C_AUT_01_sabotaje.py -v -rx"
```

El encabezado de la sesión confirma la base usada:

```
e2e DB: copia de la base real (fresh_copy.sql, 36.4 MB, generada 2026-10-09 23:04 UTC) restaurada en el contenedor
```

Datos reales dentro del contenedor antes de correr (medido en la misma sesión):

```
BASE: {'vips': 16, 'turnos': 2561, 'historial': 16110, 'aprobaciones': 1056}
```

No se asume base vacía: cada prueba usa un `chat_id` / `telegram_user_id` propio
(rango 9990009xx, fuera de los reales), verifica que ese VIP no exista antes de
empezar, y borra al final solo sus filas (turnos, trazas, aprobaciones, historial
y el VIP). La limpieza quedó comprobada: la corrida conjunta con la suite de
sabotaje reutiliza los mismos ids y `_assert_vip_nuevo` vuelve a pasar.

Solo son falsos el modelo de lenguaje externo (`llm/fake.py`) y la frontera con
Telegram (la sesión del `Bot`, que registra los envíos reales con su texto y
`chat_id`). Repos, orquestador, coordinador, Decisor, BehaviorEngine y Postgres
son los de producción, armados con `build_app`.

## Tabla de escenarios

| # | Escenario | Resultado esperado | Resultado real | ¿Pasa? |
|---|---|---|---|---|
| S0a | L1 ON + `vips.auto_send` ON, `GLOBAL_MODE=supervised` | turno `delivered`, sale el borrador, 0 filas en la cola | turno `delivered`; salida real `Claro, seguimos con lo que hablamos.`; 0 aprobaciones; historial de salida con el borrador; decisión `send/autonomous_ok` | ✅ |
| S0b | L1 ON + `GLOBAL_MODE=autonomous`, `auto_send` OFF | igual que S0a (L2 por modo global) | idéntico a S0a | ✅ |
| S1a | L1 OFF, `auto_send` ON | `pending_approval`, 0 salidas, borrador en la cola | `pending_approval`; 0 envíos; 1 fila con el borrador real y el turno correcto; Decisor `approve/ok_for_human_review` | ✅ |
| S1b | L1 OFF + `GLOBAL_MODE=autonomous` | igual que S1a (el modo global no sustituye a L1) | idéntico a S1a | ✅ |
| S2 | L1 ON, L2 OFF (`auto_send` False, modo supervisado) | `pending_approval`, 0 salidas, motivo de L2 | `pending_approval`; 0 envíos; 1 aprobación con `cognitive_summary="autonomous_mode_disabled"`; el Decisor igual emitió `send/autonomous_ok` | ✅ |
| S3 | L1 ON + L2 ON + VIP congelado (`frozen_until` futuro) | no sale nada | 0 turnos (el mensaje se descarta en los middlewares), 0 envíos, 0 aprobaciones | ✅ |
| S4a | L1 ON + L2 ON + VIP pausado (`paused_until` futuro), entrando por los middlewares | no sale nada | 0 turnos; 0 envíos; el evento `auth_drop_not_allowed` queda registrado. Al quitar la pausa, el MISMO VIP entrega (`delivered` + borrador) | ✅ |
| S4b | L1 ON + L2 ON, VIP pausado **después** de pasar los middlewares (mitad del turno) | no sale nada | **sale igual**: turno `delivered` y envío real `['Claro, seguimos con lo que hablamos.']` con `paused_until` futuro | ❌ **XFAIL** (defecto H-AUT1-2) |
| S5 | Canal de Atención (`vip_id=None`) + L1 ON + `GLOBAL_MODE=autonomous` | nunca autónomo: `pending_approval` con el borrador en la cola | `channel_type=atencion`, `vip_id` NULL, `pending_approval`, 0 envíos, 1 aprobación con `vip_id` NULL; el Decisor igual emitió `send` | ✅ |
| S6 | L1 ON + L2 ON + BehaviorEngine no cableado | (contrato) turno `FAILED`; hallazgo: el borrador no cae en la cola | turno `failed` con `error="autonomous_behavior_not_wired"`, 0 envíos, **0 aprobaciones**: el mensaje del VIP queda sin respuesta y sin cola | ✅ (confirma el punto ciego 5) |

Resumen: 9 escenarios en verde, 1 en XFAIL (S4b, defecto real documentado).

## Evidencia cruda

### Corrida principal

```
tests/audit/test_C_AUT_01.py::test_s0_doble_puerta_abierta_entrega_sin_cola[l2_vip_auto_send] PASSED
tests/audit/test_C_AUT_01.py::test_s0_doble_puerta_abierta_entrega_sin_cola[l2_global_mode] PASSED
tests/audit/test_C_AUT_01.py::test_s1_l1_apagado_nada_sale_y_cae_en_la_cola[l2_por_vip] PASSED
tests/audit/test_C_AUT_01.py::test_s1_l1_apagado_nada_sale_y_cae_en_la_cola[l2_global] PASSED
tests/audit/test_C_AUT_01.py::test_s2_l2_cerrado_el_orquestador_demota_y_cae_en_la_cola PASSED
tests/audit/test_C_AUT_01.py::test_s3_vip_congelado_no_entra_al_motor_y_no_hay_envio PASSED
tests/audit/test_C_AUT_01.py::test_s4_vip_pausado_queda_fuera_en_la_entrada_y_al_reanudar_entrega PASSED
tests/audit/test_C_AUT_01.py::test_s4b_ventana_pausa_a_mitad_del_turno_no_detiene_el_envio XFAIL
tests/audit/test_C_AUT_01.py::test_s5_atencion_con_l1_y_modo_global_nunca_es_autonomo PASSED
tests/audit/test_C_AUT_01.py::test_s6_sin_behavior_el_turno_falla_y_el_borrador_no_va_a_la_cola PASSED

XFAIL tests/audit/test_C_AUT_01.py::test_s4b_ventana_pausa_a_mitad_del_turno_no_detiene_el_envio - H-AUT1-2: el camino autónomo no rechequea paused_until (solo _is_vip_paused se usa en la ruta fática). Un VIP pausado durante el turno recibe igual el envío automático.
=================== 9 passed, 1 xfailed, 1 warning in 6.16s ====================
```

### S4b con `--runxfail`: el detalle del defecto

```
E           AssertionError: un VIP pausado recibió el envío autónomo:
  turno={'id': '73c2340c-...', 'status': 'delivered', 'vip_id': '8eee24a5-...',
         'channel_type': 'vip', 'error': None}
  envios=['Claro, seguimos con lo que hablamos.']
INFO     diana.application:turn_orchestrator.py:1665 autonomous_send_start
INFO     diana.application:turn_orchestrator.py:3039 autonomous_delivered
FAILED tests/audit/test_C_AUT_01.py::test_s4b_...
```

Es decir: con `paused_until` en el futuro, el turno se persiste `delivered` y el
mensaje sale por el BehaviorEngine. La puerta de pausa existe en la entrada
(`AuthMiddleware` → `get_record_and_allowed` → `vip_is_allowed`) y en la ruta
fática (`_is_vip_paused`, `turn_orchestrator.py:2647`), pero NO en
`_prepare_autonomous_send`. La prueba quedó como `xfail` para que el defecto se
vea en cada corrida sin dejar la suite en rojo; si alguien agrega el rechequeo,
la prueba pasa (comprobado, ver sabotaje inverso más abajo).

## Comprobación de sabotaje (¿la prueba puede fallar?)

Como no se toca código de producción, cada sabotaje se aplica con `monkeypatch`
en tiempo de ejecución sobre el contenedor real y se corre la función de prueba
real del archivo E2, exigiendo que falle. Vive en
`tests/audit/test_C_AUT_01_sabotaje.py` (se corre junto con el archivo E2; su
costo es de segundos y deja la sensibilidad de cada prueba a la vista en cada
corrida). Es el paso previo del E3 formal: aquí el sabotaje es reversible y en
memoria, no una edición.

| Sabotaje | Qué se desconectó | Resultado |
|---|---|---|
| S0 | `AutonomousModeService.is_autonomous_enabled` → siempre `False` | la prueba positiva falla (el envío no sale) ✅ |
| S1 | `Decider.decide` forzado a `send` **y** AMS siempre abierto | la prueba de L1 OFF falla (con una sola guarda quitada seguía pasando: L1 tiene dos guardas) ✅ |
| S2 | AMS siempre abierto | la prueba de L2 cerrado falla ✅ |
| S3 | `FreezeCheckMiddleware.__call__` pasa de largo **y** `TurnOrchestrator._is_vip_frozen → False` | la prueba de congelado falla ✅ |
| S4a | `vip_is_allowed` → siempre `True` | la prueba de pausa en la entrada falla ✅ |
| S5 | AMS que ignora `vip_id=None` | la prueba de Atención falla (enviaría) ✅ |
| S6 | reposición del motor real antes de preparar el envío | la prueba de motor no cableado falla ✅ |
| S4b (inverso) | `_prepare_autonomous_send` con un rechequeo de pausa | la prueba pasa: el xfail detecta la corrección ✅ |

Salida (el archivo E2 y el de sabotaje en la misma sesión, que además comprueba
que la limpieza deja la base sin residuos):

```
tests/audit/test_C_AUT_01_sabotaje.py::test_sabotaje_s1_corta_las_dos_guardas_de_l1_en_verdad PASSED
tests/audit/test_C_AUT_01_sabotaje.py::test_sabotaje_s2_corta_ams_en_verdad PASSED
tests/audit/test_C_AUT_01_sabotaje.py::test_sabotaje_s0_cierra_ams_en_verdad PASSED
tests/audit/test_C_AUT_01_sabotaje.py::test_sabotaje_s3_quita_congelado_en_verdad PASSED
tests/audit/test_C_AUT_01_sabotaje.py::test_sabotaje_s4_quita_la_pausa_en_verdad PASSED
tests/audit/test_C_AUT_01_sabotaje.py::test_sabotaje_s5_quita_el_guard_de_vip_id_en_verdad PASSED
tests/audit/test_C_AUT_01_sabotaje.py::test_sabotaje_s6_con_el_motor_cableado_la_prueba_revienta PASSED
tests/audit/test_C_AUT_01_sabotaje.py::test_sabotaje_s4b_la_correccion_hace_pasar_la_prueba PASSED
=================== 17 passed, 1 xfailed, 1 warning in 7.18s ===================
```

## Hallazgos

- **H-AUT1-2 (confirmado en ejecución, antes solo en código)**: el camino
  autónomo no consulta `paused_until`. Un VIP pausado cuyo mensaje ya pasó los
  middlewares recibe el envío automático. Evidencia: S4b.
- **L1 tiene dos guardas independientes**: el Decisor (`feature_autonomous_mode`)
  y `AutonomousModeService`. Quitar una sola no abre la puerta; hay que quitar
  las dos. Es defensa en profundidad real, no código muerto.
- **S6 confirmado**: sin BehaviorEngine el turno queda `FAILED` y el borrador NO
  cae en la cola de la dueña; el mensaje del VIP queda sin respuesta y sin cola
  (coincide con el punto ciego 5 del contrato).
- **La democión por L2 deja huella distinta a la de L1**: L1 OFF se corta en el
  Decisor (`ok_for_human_review`), L2 OFF se corta en el orquestador
  (`autonomous_mode_disabled`, visible en `pending_approvals.cognitive_summary`).
  Sirve para vigilar que la doble puerta no se colapse en una sola capa.
- **La pausa en la entrada descarta el mensaje en silencio** (`auth_drop_not_allowed`,
  0 turnos): el VIP pausado no recibe nada, ni respuesta ni entrada en la cola.
  Es el comportamiento del allowlist, no de este contrato, pero conviene saberlo.
- **Nota de método (S5)**: el canal de Atención se alcanzó por **modo
  entrenamiento** (`system_config.training_mode_enabled`), que es la vía
  determinista para que un chat no-VIP llegue al pipeline con
  `channel_type="atencion"` y `vip_id=None`. La guarda bajo prueba
  (`is_autonomous_enabled(None)`) es la misma que en el modo general; solo cambia
  la puerta de entrada (que en modo general exige un ciclo de promoción abierto).
  El valor previo de la clave se lee y se restaura al final.

## Veredicto C-AUT-01

- **E2 (flujo real con efecto persistido): CUMPLIDO** para la doble puerta:
  cara positiva (entrega real sin cola) y caras negativas L1 OFF, L2 OFF,
  congelado y Atención, con estado persistido en `turns` y `pending_approvals`
  y salidas reales del actuador.
- **E3 (E2 + sabotaje): CUMPLIDO** con sabotaje en tiempo de ejecución
  (`tests/audit/test_C_AUT_01_sabotaje.py`, 8 comprobaciones, una por escenario
  y una inversa). ⚪ El sabotaje permanente en código (que rompa la suite a
  propósito en CI) queda para el agente que haga el E3 formal.
- **Excepción**: el fail-closed de la pausa a mitad de turno (S4b) NO se cumple.
  Un VIP pausado puede recibir un envío automático si la pausa entra después de
  los middlewares. El contrato ya lo declara como punto ciego; ahora hay prueba
  que lo demuestra contra Postgres real.

> Regla de la casa respetada: no se modificó código de producción, no se
> mockeó ninguna pieza prometida y no se leyó ningún log de conversaciones.
