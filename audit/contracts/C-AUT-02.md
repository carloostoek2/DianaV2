# C-AUT-02 — La puerta de recomendación mide y nunca envía sola

ID:            C-AUT-02
Promesa:       El panel "Camino a la autonomía" evalúa las tres condiciones de activación
               (confianza ≥ 0.90 · coincidencia global ≥ 95 % en 2 semanas · cero
               escalaciones por seguridad en la ventana) y solo habilita el botón "Activar"
               cuando las tres se cumplen; activar escribe `vips.auto_send` y NO envía nada por
               su cuenta — el interruptor maestro sigue gobernando el envío real.
Fuente:        docs/SPEC-AUTONOMIA-CALIBRACION.md §5 C5/C6 y §8; AGENTS.md §3 flujo 4.19;
               docs/SPEC-FASE3.md §4.2.
Disparador:    la dueña abre la sección "AUTONOMÍA" del menú (`autonomia`/`global`/
               `comparativas`/`vips`) o toca "Activar"/"Apagar" de un VIP.
Efecto:        `ready=True` si y solo si `best_trust ≥ autonomy_confidence_min` Y
               `global_rate ≥ autonomy_match_rate_min` Y `safety_escalations == 0`.
               `activate()` con las tres cumplidas → `vips.auto_send = true` + mensaje de
               confirmación; sin las tres → NO escribe `auto_send` y devuelve el motivo por
               condición. Nunca se llama a `behavior.deliver` desde este panel.
Banderas:      `FEATURE_AUTONOMY_RECOMMENDATION_ENABLED` (hoy `true`) → OFF: `activate()`
               devuelve "desactivada" y no escribe (`autonomy_readiness_service.py:313-317`).
               `FEATURE_AUTONOMY_QUALITY_ENABLED` (hoy `true`) → alimenta las comparativas y el
               snapshot; OFF dejaría `rate=None` → nunca listo.
               `FEATURE_AUTONOMY_COINCIDENCE_ENABLED` (hoy `true`) → BANDERA MUERTA (H-1: ningún
               módulo la lee).
               (`FEATURE_AUTONOMOUS_MODE=false` sigue siendo el kill-switch del envío real.)
Camino (estático, y verificado en ejecución el 2026-10-09 salvo donde se diga):
  1. `menu.py:967` categoría `autonomia` → `render_global` / `render_comparativas` /
     `render_by_vip`; el teclado por VIP usa `item.ready` (`menu.py:989-997`).
  2. "Activar"/"Apagar" (`menu.py:1001-1020`) → `AutonomyReadinessService.activate` /
     `deactivate`.
  3. `activate` (`autonomy_readiness_service.py:307-328`): gate de recomendación `:313`;
     `recommendation(vip_id)` `:318`; si `not readiness.ready → False + motivo` `:321-322`;
     si listo, `self._vips.set_auto_send(vip_id, True)` `:323`.
  4. `ready` se calcula en `VipReadiness.__init__` (`:80-85`): `best_trust >= confidence_min`
     AND `global_rate is not None` AND `global_rate >= match_rate_min` AND
     `global_safety_escalations == 0`.
  5. `_by_vip` (`:163-210`): `best_trust = max(trust_score)` por VIP; `global_rate` de
     `coincidence_summary`; `safety_escalations` = cuenta de comparativas con
     `shadow_reason == "safety_below_threshold"` (`:172-174`).
  6. `set_auto_send` (`vips.py:187-203`): `UPDATE vips SET auto_send`; contrato explícito de
     que el kill-switch maestro sigue gobernando. Escritor ÚNICO: solo lo llaman activar y
     apagar del panel (`:323` / `:332`); no hay job, script, endpoint, migración ni seed que lo
     toque.
  7. Cableado: `composition.py:742-751` (servicio) y `:858-862` (se entrega al AdminService
     solo con el flag de recomendación).
  8. La UI no dibuja el botón si `ready=False` (`menu.py:983-997` + `keyboards.py:1402-1431`):
     un VIP que no está listo no se puede activar por un toque.
Puntos ciegos: los del original (la condición de seguridad sale de las comparativas
               recomputadas, no del contador dedicado; `global_rate is None` bloquea sin decir
               por qué; `readiness_snapshot` degrada a `has_history=False` si falla la base;
               `except` del menú convertido en "Error del sistema" sin decir qué condición
               falló). Todos siguen abiertos.
Prueba E2:     HECHO (2026-10-09) → `tests/audit/test_C_AUT_02.py` (7 pruebas) y
               `tests/audit/test_C_AUT_04.py` (4 casos), contra Postgres real (copia fresca de
               la base real, 2026-10-09 23:04 UTC). 11 en verde.
               Probado por efecto: cada una de las tres condiciones faltando por separado (el
               motivo apunta SOLO a la que falta, y se asertó que no menciona las otras dos);
               las tres cumplidas → escribe `vips.auto_send=true` leído de la DB y 0 llamadas a
               Telegram (activar no envía); el panel ("✅ LISTO" / "⏳ en camino" + motivo);
               la bandera del panel OFF → se niega y no escribe; H-6 (activar con el maestro
               apagado: turno en cola y 0 mensajes al VIP; con el maestro encendido, mismo VIP
               y mismo permiso → entrega y 1 mensaje real).
Sabotaje E3:   HECHO (2026-10-09) → 5 sabotajes con edición mínima de código de producción y
               reversión inmediata (árbol de `src/` limpio al terminar; `git status --porcelain`
               vacío). Cada uno hizo caer exactamente la prueba de su condición: quitar
               `and global_safety_escalations == 0` → falla el caso de seguridad; quitar
               `and global_rate >= match_rate_min` → falla coincidencia; quitar
               `self.meets_confidence and` → falla confianza; `activate` ignorando
               `readiness.ready` → fallan los tres casos "falta una"; quitar el guard de la
               bandera de recomendación → falla el caso de bandera apagada.
Vigilante E4:  PROPUESTO, no desplegado → `audit/AUTONOMIA-INFORME.md` §5: V8 ("la medición
               dejó de alimentar la confianza") y V10 ("un VIP activado quedó en la cola").
               Sigue faltando el vigilante de "hay un VIP con el permiso dado que no pasó la
               puerta" (el contrato lo pedía en su versión original).
Nivel:         **E3** (E2 real + sabotaje que muerde en las tres condiciones y en el "activar
               no envía"). Sin E4.
Semáforo:      🟢 **E3**. La puerta funciona, y hoy está CERRADA (ver evidencia viva).
Hallazgos:
  - Evidencia viva del cierre (2026-10-09, copia fresca): la condición de coincidencia global
    exige 95 % y la ventana de 14 días mide 92,8 % (69 comparativas: 64 aciertos, 5
    desacuerdos). Histórico: 87,8 % (144 / 20). Tendencia semanal: 72,4 % → 88,9 % → 88,0 % →
    97,1 % → 91,7 %. La condición de seguridad sí se cumple (0 escalaciones por seguridad). La
    confianza ≥ 0,90 solo la cumplen 3 pares (VIP, categoría). Resultado: la puerta está cerrada
    y la dueña no puede activar a nadie hoy sin bajar el listón.
  - H-1 CONFIRMADO (E2): `FEATURE_AUTONOMY_COINCIDENCE_ENABLED` es una bandera muerta. Dos
    contenedores con la bandera ON y OFF dan el mismo resumen (los 6 campos) y con OFF la
    coincidencia se sigue calculando; el token solo aparece en `config/settings.py` y
    `config/banderas_nucleo.py`. Apagarla no cambia nada, y está documentada como control activo.
  - H-6 CONFIRMADO (E2): el botón dice "Activado el envío autónomo para <VIP>" aunque el
    interruptor maestro esté apagado; nada se envía. El texto del panel ("nada cambia hasta que
    tú lo actives") refuerza la confusión. Es el hallazgo con más riesgo operativo de esta
    puerta, porque el orden natural del encendido es exactamente activar VIPs y después el
    maestro.
  - H-AUT2-1 (código, sin prueba): la condición "cero escalaciones por seguridad" se cuenta
    sobre las comparativas recomputadas en sombra, no sobre el contador dedicado de resultados
    reales (`OutcomeLogService.count_safety_escalations_since` no tiene llamador en el
    readiness). El test 3 lo confirma por construcción: una escalación real por `risk_high` no
    suma ahí; solo una que la simulación marque `safety_below_threshold`.
  - Riesgo latente de secuencia: un VIP activado NO se re-evalúa al encender el maestro. Si la
    dueña activa VIPs hoy (el panel se lo permite con el maestro apagado, H-6), esos VIPs
    empiezan a enviar solos en el mismo instante en que se encienda L1, aunque ya no cumplan las
    tres condiciones. Hoy el riesgo es nulo: 0 de 16 VIPs tienen el permiso dado.
