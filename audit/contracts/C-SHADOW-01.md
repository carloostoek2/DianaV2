# C-SHADOW-01 — El modo sombra compara el borrador de Diana con lo que decide la dueña

ID:            C-SHADOW-01
Promesa:       Por cada turno de un VIP, el sistema guarda qué habría decidido en sombra (shadow_verdict), la calidad del borrador (draft_score) y, cuando la dueña aprueba/corrige/escala, qué hizo ella (owner_outcome) con la calidad de lo enviado y la diferencia. Con eso se mide si Diana ya puede ir sola.
Fuente:        docs/SPEC-AUTONOMIA-CALIBRACION.md (Fila 4); wiki/concepts/modos-de-operacion.md
Disparador:    (a) cierre de un turno VIP; (b) la dueña aprueba / corrige / escala; (c) el VIP responde después (reacción) o hay silencio.
Efecto:        Fila en `turn_outcome_log` por turno con shadow_verdict, shadow_reason, draft_score, blocked_dims; tras la acción de la dueña: owner_outcome ∈ {approved_as_is, corrected, escalated}, sent_score, quality_delta; tras reacción: vip_signal.
Banderas:      feature_autonomy_quality_enabled → ON: se escribe todo. OFF: no se escribe nada (por diseño: `outcome_log=None` en el orquestador). Relacionadas: feature_autonomy_readiness_enabled, feature_autonomy_coincidence_enabled.
Camino (estático, SIN ejecutar):
  1. turn_orchestrator.py:432 `_run_outcome_log` → :937 `OutcomeLogService.record_shadow` → repo `turn_outcome.py` upsert por turn_id.
  2. admin_service.py:~1951 y ~2174 → `record_owner_outcome` (approved_as_is / corrected / escalated).
  3. turn_orchestrator.py:~987 `_run_outcome_reaction` y jobs/outcome_reaction.py → `record_reaction`.
  4. composition.py:1219 entrega `outcome_log` al orquestador SOLO con la bandera; :654 construye el servicio siempre pero con `enabled=` y scorer/clasificador condicionados.
Puntos ciegos:
  - turn_orchestrator.py `_run_outcome_log` envuelve todo en `except Exception → log_swallowed("outcome_log_error")`: si falla, el turno sigue y no queda fila.
  - outcome_log_service.record_shadow tiene su propio `except → logger.exception → return None`: segundo nivel de silencio.
  - Sin `trace_reader` o sin traza → `return` mudo.
  - Los contadores de `log_swallowed` no se exponen en ningún lado (ver HALLAZGO H1).
  - Las llamadas a `record_owner_outcome` en admin_service también son "best-effort".
  - La bandera real de producción vive en `.env` (no incluido en el zip): no verificable desde el código.
  - Decisión de producto (2026-10-06, dueña): cuando ella responde ESCRIBIENDO directo en el chat NO se compara contra el borrador. No es un error: no se contempló en el diseño original. Queda fuera del contrato; solo se compara por aprobar/corregir/escalar.
Prueba E2:     pendiente → tests/audit/test_C_SHADOW_01.py (P1+P2+P4: build_app con quality ON; mensaje VIP; aprobar y corregir; asertar fila completa).
Sabotaje E3:   pendiente → S1 (outcome_log=None), S3 (record_shadow lanza), S5 (quitar llamada :432). Esperado: la prueba falla en los tres.
Vigilante E4:  propuesto → diario: turnos VIP entregados/escalados de las últimas 24h SIN fila en turn_outcome_log > 0 ⇒ alerta. Y: filas con owner_outcome NULL a más de N horas de una aprobación.
Nivel:         E0 en código + evidencia viva de producción (499 filas, 23-ago → 6-oct; 223/237 turnos con fila). Sin E3.
Semáforo:      🟡 Funciona. Los 14 huecos son rutas de diseño (probado). El hueco del 23-ago→10-sep fue un defecto de guardado (commit 3ade3b3, corregido 10-sep 19:42): 157 entregas desde el 11-sep, 0 pérdidas. Falta E3 y vigilantes.
Hallazgos:     H1 sigue siendo riesgo sistémico pero NO fue la causa aquí (0 errores en logs 30-sep→6-oct). Causa real del hueco: upsert que borraba owner_outcome. Ver INVESTIGACION-A.md
