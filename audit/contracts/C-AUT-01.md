# C-AUT-01 — El envío autónomo entrega de verdad, y solo con las dos puertas abiertas

ID:            C-AUT-01
Promesa:       Cuando un VIP escribe y el interruptor maestro (L1) y el permiso por VIP (L2)
               están abiertos y el Decisor decide "enviar", el mensaje sale al VIP por el
               BehaviorEngine y el turno queda entregado sin pasar por la cola de aprobación;
               con cualquiera de las dos puertas cerrada, no sale nada y cae en la cola.
Fuente:        AGENTS.md §3 flujo 4.8, §4.1; docs/SPEC-FASE3.md §4.8 y §5.1–5.2;
               docs/SPEC-AUTONOMIA-CALIBRACION.md §5 C6; faltantes.md §2.
Disparador:    mensaje de negocio de un VIP (business_message) que llega al orquestador.
Efecto:        Con L1 ON + L2 ON (o `GLOBAL_MODE=autonomous`) + Decisor `send`:
               turno `DELIVERED` y una salida real del BehaviorEngine; SIN fila en
               `pending_approvals`. Con L1 OFF o L2 OFF: turno `PENDING_APPROVAL`,
               0 salidas y borrador en la cola (reason `autonomous_mode_disabled`).
Banderas:      L1 `FEATURE_AUTONOMOUS_MODE` (hoy `false` en `.env`) → OFF: el Decisor nunca
               emite `send` por umbrales y el orquestador demota a `approve`.
               L2 `vips.auto_send` por VIP, o `GLOBAL_MODE=autonomous` (hoy `supervised`).
               `FEATURE_ADVANCED_BEHAVIOR` (split/quirks en la entrega) — no cambia el gate.
Camino (estático, y verificado en ejecución el 2026-10-09 salvo donde se diga):
  1. `turn_orchestrator.py:2516` despacho `decision.action == "send"` →
     `_prepare_autonomous_send` (`:2802`); si el motivo es de plantilla fática, va por
     `_prepare_phatic_template_send` (`:2565`, otro contrato).
  2. Gate L1/L2: `_prepare_autonomous_send` → `AutonomousModeService.is_autonomous_enabled`
     (`autonomous_mode_service.py:52`): L1 `:59`; `vip_id is None → False` `:61`;
     `GLOBAL_MODE=autonomous → True` `:63`; si no, `vip.auto_send` `:65-68`.
  3. Si no está habilitado: demota `send → approve` y `PENDING_APPROVAL` + DM de borrador
     (`turn_orchestrator.py:2836-2859`).
  4. Fail-closed: `autonomous_mode` no cableado → turno `FAILED` (`:2811`); VIP congelado →
     `FAILED` (`:2861`); borrador vacío → `FAILED` (`:2887`); `behavior` ausente → `FAILED`
     (`:2911`).
  5. Entrega fuera del lock: `behavior.deliver(...)` (`:1673`), re-chequeo de congelado
     (`:1602`) → `_finalize_autonomous_delivery` (`:2980`) → `DELIVERED` (`:3015`) +
     historial de salida de la dueña.
  6. Aviso cerca de umbral (best-effort): `AutonomousModeService.notify_if_needed`
     (`:1704-1713`).
  7. Sandbox: ruta propia, sin gates AMS ni congelado/pausado (`:2194-2211` →
     `_prepare_sandbox_send` `:2728`).
Puntos ciegos: los del original (L2 no vive en el Decisor y el Decisor decide con la sola L1;
               `vip_id=None` → `False` en silencio; el camino autónomo no rechequea
               `paused_until`; `notify_if_needed` traga toda excepción; sin `behavior` el turno
               queda `FAILED` y el borrador no cae en la cola). Estado 2026-10-09: todos
               cubiertos por prueba; el de la pausa quedó CONFIRMADO como defecto (H-AUT1-2).
Prueba E2:     HECHO (2026-10-09) → `tests/audit/test_C_AUT_01.py`, contra Postgres real (copia
               de la base real restaurada en contenedor, 36.4 MB, generada 2026-10-09 23:04 UTC;
               solo falsos el modelo de lenguaje externo y la frontera con Telegram). 10
               escenarios: 9 en verde, 1 en XFAIL.
               Verde: S0a/S0b entrega real sin cola (L2 por VIP y por modo global); S1a/S1b
               L1 OFF → cola; S2 L2 OFF → cola con motivo `autonomous_mode_disabled`;
               S3 VIP congelado → 0 turnos, 0 envíos; S4a VIP pausado en la entrada → 0 turnos,
               y al quitar la pausa el mismo VIP entrega; S5 Atención (`vip_id=None`) con L1 ON
               y modo global → cola, nunca autónomo; S6 sin motor cableado → turno `FAILED`, 0
               envíos y 0 filas de cola.
               XFAIL: S4b, VIP pausado a mitad del turno (después de los middlewares) → **sale
               igual**: turno `delivered` y envío real. Ver H-AUT1-2.
Sabotaje E3:   HECHO (2026-10-09) → `tests/audit/test_C_AUT_01_sabotaje.py`, 8 comprobaciones
               por `monkeypatch` en tiempo de ejecución sobre el contenedor real, exigiendo que
               cada prueba falle. Las 8 muerden: AMS cerrado → falla la positiva; AMS abierto →
               fallan L1 OFF, L2 OFF y Atención; congelado y pausa de entrada quitados → fallan
               sus casos; motor despuesto → falla S6; y el inverso: un rechequeo de pausa hace
               PASAR el XFAIL de S4b (la prueba detecta la corrección). Queda pendiente el
               sabotaje permanente en código (que rompa la suite a propósito en CI).
Vigilante E4:  PROPUESTO, no desplegado → `audit/AUTONOMIA-INFORME.md` §5: V9 ("un envío
               autónomo salió sin dejar su fila de medición") y V10 ("un VIP con permiso dado
               quedó en la cola: el interruptor maestro está apagado").
Nivel:         **E3** en la doble puerta y en las caras negativas probadas (E2 real + sabotaje
               que muerde). Sin E4. Una cláusula NO se cumple, con prueba en contra: el
               fail-closed de la pausa a mitad de turno (S4b).
Semáforo:      🟢 **E3** en la doble puerta · 🔴 en la cláusula de pausa (el efecto no ocurre).
Hallazgos:
  - H-AUT1-2 (CONFIRMADO EN EJECUCIÓN, antes solo en código): el camino autónomo no consulta
    `paused_until`. Un VIP pausado cuyo mensaje ya pasó los middlewares recibe el envío
    automático. Evidencia: S4b (`paused_until` futuro → turno `delivered` y mensaje real en el
    actuador). Hoy no tiene efecto porque L1 está apagado y L2 vacío; el día que la dueña active
    un VIP, una pausa a mitad de turno no lo detiene.
  - H-AUT1-1 (código, confirmado por efecto): la doble puerta se completa recién en el
    orquestador; el Decisor decide con la sola L1. S2 lo muestra: el Decisor emite
    `send/autonomous_ok` y el orquestador demota. La doble puerta funciona, pero vive en un solo
    lugar: cambiar el orden ahí la rompe sin que ninguna prueba del Decisor lo note.
  - L1 tiene DOS guardas independientes (Decisor + servicio de modo autónomo): quitar una sola
    no abre la puerta. Defensa en profundidad real, no código muerto (comprobado por sabotaje).
  - S6 confirmado: sin motor de envío, el turno queda `FAILED` y el borrador NO cae en la cola:
    el mensaje del VIP queda sin respuesta y sin cola, con solo un aviso interno.
  - La democión por L2 deja huella distinta a la de L1 (`ok_for_human_review` vs
    `autonomous_mode_disabled` en la cola): sirve para vigilar que la doble puerta no se colapse
    en una sola capa (base del vigilante V10).
  - Nota de producto: la pausa en la ENTRADA descarta el mensaje en silencio
    (`auth_drop_not_allowed`, 0 turnos): el VIP pausado no recibe nada, ni entra a la cola. Es
    el comportamiento de la lista blanca, no de este contrato, pero conviene saberlo.
  - Nota de método: la Atención se alcanzó por modo entrenamiento (`system_config.training_mode_enabled`),
    la vía determinista para que un chat no-VIP llegue al pipeline con `channel_type="atencion"`
    y `vip_id=None`. La guarda bajo prueba (`is_autonomous_enabled(None)`) es la misma en modo
    general; solo cambia la puerta de entrada.
