# C-AUT-04 — El aprendizaje no se cuenta dos veces

ID:            C-AUT-04
Promesa:       Con el camino a la autonomía encendido (`FEATURE_AUTONOMY_READINESS_ENABLED`),
               la confianza del VIP se ajusta por UNA sola fuente — el resultado resuelto del
               turno (acierto +0.05 / desacuerdo −0.20 / conservadora 0, y la señal del VIP) —
               y los incrementos/decrementos heredados del modo sombra quedan desactivados para
               no contar el mismo turno dos veces.
Fuente:        AGENTS.md §3 flujo 4.18 (invariante) y §4.18; docs/SPEC-AUTONOMIA-CALIBRACION.md
               §7 ("TrustBudgetService gana un evento `record_outcome`") y §8 (asimetría).
Disparador:    (a) cierre post-turno de un turno clasificado; (b) la dueña resuelve
               (aprobar / corregir / escalar); (c) la reacción del VIP (C-AUT-03).
Efecto:        Con `FEATURE_AUTONOMY_READINESS_ENABLED=true` y `FEATURE_AUTONOMY_QUALITY_ENABLED=true`:
               `vip_trust_budget.trust_score` cambia SOLO por eventos `record_outcome`
               (`label` / `signal`); `record_autonomous` y `record_correction` no aplican delta
               sobre el mismo turno. `autonomous_count` / `correction_count` no suben por la vía
               sombra.
Banderas:      `FEATURE_AUTONOMY_READINESS_ENABLED` (hoy `true`) → OFF: vuelven el incremento
               sombra (`record_autonomous`) y el decremento por corrección
               (`record_correction`), con el doble conteo conocido de SPEC-EA-07.
               `FEATURE_AUTONOMY_QUALITY_ENABLED` (hoy `true`) → OFF: el `outcome_log` no se
               entrega a orquestador/admin y `record_outcome` nunca corre.
               `FEATURE_TRUST_BUDGET` (hoy `true`) → OFF: sin budget cableado, no hay ninguna
               vía de ajuste.
Camino (estático, y verificado en ejecución el 2026-10-09 salvo donde se diga):
  1. Supresión del incremento sombra: `turn_orchestrator.py:859-865` → si
     `self._autonomy_readiness` es verdadero, `_run_trust_budget` retorna antes de
     `record_autonomous` (`:888`).
  2. Supresión del decremento por corrección: `admin_service.py:896-913` → el
     `record_correction` se ejecuta solo bajo `if not self._autonomy_readiness`.
  3. Fuente única: `OutcomeLogService.record_owner_outcome`
     (`outcome_log_service.py:378-388`) emite `record_outcome(event="label", value=etiqueta)`;
     `record_outcome` (`trust_budget_service.py:356-370`): `desacuerdo` → decremento,
     `acierto` → incremento, `conservadora` → sin cambio. La etiqueta se deriva con
     `label_turn(shadow_verdict, owner_outcome)`: `conservadora` y los pares no clasificables
     NO mueven la confianza (tabla del contrato, no una falla).
  4. Señal del VIP: `record_reaction` → `record_outcome(event="signal")` (`:444-446`):
     `negative` → decremento, `positive` → incremento, `neutral`/`silence` → sin cambio.
  5. Asimetría fija: `increment=0.05`, `decrement=0.2` (`trust_budget_service.py:45-46`),
     clamp a [0,1].
  6. Cableado de la bandera: `composition.py:855` (AdminService) y `:1285` (orquestador);
     `turn_orchestrator.py:234` y `admin_service.py:208` la reciben; `composition.py:852-853`
     y `:1282-1284` entregan `outcome_log` solo con el flag de calidad.
  7. Huella observable: cada evento que sí aplica actualiza `vip_trust_budget.updated_at`
     (rama de conflicto de `increment_autonomous` / `decrement_correction`); por eso un
     `updated_at` quieto es señal de que la medición dejó de mover la confianza.
Puntos ciegos: los del original (el "kill" de la vía sombra no verifica que la vía de resultado
               esté cableada → H-AUT4-2; `record_outcome` no-opea en silencio si no hay fila de
               clasificación o el VIP es nulo; `record_owner_outcome` traga excepciones; no hay
               verificación de que el delta aplicado coincida con el evento; deuda SPEC-EA-07).
Prueba E2:     HECHO (2026-10-09) → `tests/audit/test_C_AUT_04.py` (2 pruebas parametrizadas =
               4 casos), contra Postgres real, con confianza sembrada en 0,50 y un turno real
               resuelto por la dueña (aprobar y corregir):
               · readiness ON: `0.50 → 0.55` (`autonomous_count=1`) y `→ 0.35`
                 (`correction_count=1`): UN evento por resolución y la vía sombra no aporta
                 ninguno. Huella de ledger: `send/approved_as_is` y `corrected/moderate`.
               · readiness OFF (contraprueba): `0.50 → 0.60` (`autonomous_count=2`) y `→ 0.25`
                 (contadores 3 y 2): el doble conteo documentado. Confirma que la prueba mide un
                 efecto y no una constante.
               · H-2 con calidad ON (contraste): la confianza se mueve (0,55 / 0,35) y hay fila
                 de ledger.
               · H-2 con calidad OFF: `0.50 → 0.50 → 0.50`, contadores en 0, SIN fila de
                 ledger, y **cero** WARNING/ERROR de la aplicación sobre confianza ni medición.
               · Precondiciones asertadas: el turno se clasifica fático con
                 `would_autonomous=true`, el veredicto sombra es `send` y la corrección persistió
                 (staging), sin lo cual la contraprueba OFF sería vacua.
Sabotaje E3:   HECHO (2026-10-09) → 2 sabotajes con edición mínima y reversión inmediata:
               quitar `if self._autonomy_readiness: return` del orquestador (`:864`) y quitar
               `if not self._autonomy_readiness:` del admin (`:904`) → cada uno hace caer las
               pruebas que miden la vía única (3 fallos cada uno). El primero deja además una
               observación importante: con el guard quitado, el caso H-2 (calidad OFF) también
               falla, es decir **el congelamiento de H-2 depende por completo de ese guard**.
Vigilante E4:  PROPUESTO, no desplegado → `audit/AUTONOMIA-INFORME.md` §5: V8 ("la medición
               dejó de alimentar la confianza": hubo resoluciones de la dueña y NINGUNA fila de
               confianza se movió). Es el E4 exacto que este contrato pedía, y cubre por efecto
               tanto H-2 como los fallos tragados del ledger.
Nivel:         **E3** en la invariante de fuente única (E2 real + sabotaje que muerde). Sin E4.
               Una promesa del contrato NO se cumple, con prueba: la combinación "medición
               apagada" deja la confianza ajustándose por CERO fuentes, en silencio.
Semáforo:      🟢 **E3** en la vía única de confianza · 🔴 en "siempre hay una vía de ajuste"
               (H-2: la confianza se congela sin aviso).
Hallazgos:
  - H-AUT4-2 (CONFIRMADO EN EJECUCIÓN — el hallazgo más importante de su tanda): con
    `FEATURE_AUTONOMY_READINESS_ENABLED=true` y `FEATURE_AUTONOMY_QUALITY_ENABLED=false`, la
    confianza queda congelada: las DOS vías están suprimidas y la puerta de recomendación queda
    cerrada para ese VIP sin que nadie se entere (ningún aviso, ningún error de la aplicación).
    Quien apague la medición "para dejar de medir" apaga también, sin aviso, la única vía de
    ajuste que la bandera de readiness dejó viva.
  - H-AUT4-1 (verificado en ejecución, ya no solo en código): la invariante SÍ se cumple en el
    cableado actual, y ahora está demostrada por efecto, con contraprueba y sabotaje.
  - H-AUT4-3 (deuda conocida, no nueva): con calidad ON + readiness OFF persiste el doble
    conteo del decremento por gravedad (SPEC-EA-07). Hoy la configuración real no está en esa
    combinación.
  - Calidad del texto (C2) NO discrimina: el puntaje medio del borrador es casi idéntico entre
    lo que la dueña aceptó (0,620) y lo que corrigió o escaló (0,625). Consecuencia de negocio:
    ese número no sirve como red de seguridad adicional para decidir el encendido.
