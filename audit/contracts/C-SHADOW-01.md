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
Prueba E2:     HECHO → tests/audit/test_C_SHADOW_01.py (5 pruebas: build_app con la bandera ON y OFF; mensaje VIP; aprobar; las dos rutas de diseño). Postgres real; solo el LLM es falso.
Sabotaje E3:   HECHO (2026-10-08) → 9 sabotajes aplicados y revertidos; los 9 hacen fallar exactamente la prueba que debían. Evidencia cruda en audit/FASE2-SABOTAJE.md §3.
Vigilante E4:  DESPLEGADO (2026-10-08) → scripts/vigilantes.py + cron diario (10:17 UTC), solo lectura. V2: turnos que pasaron por el pipeline y no dejaron fila de sombra (exige traza con evaluación y descarta las sesiones de sandbox, que no persisten a propósito). V7: turno entregado con nota del borrador y sin la decisión de la dueña (la firma exacta del defecto del 10-sep). El V3 propuesto NO se activó: alertaría por diseño (escalaciones que la dueña responde escribiendo en el chat, envíos automáticos y de plantilla). Calibración, falsos positivos descartados y prueba de que la alarma suena: audit/FASE2-SABOTAJE.md §9.
Nivel:         E3 en los tramos (a) turno entregado deja su fila, (b) la decisión de la dueña sobrevive al re-guardado, (c) bandera OFF no escribe, (d) rutas de diseño sin fila. E4 en (a) y (b) por los vigilantes desplegados.
               Sin cubrir: la reacción del VIP (C3, `vip_signal`) y los tramos `corregir` / `escalar` de `owner_outcome`.
Semáforo:      🟢 E3 + E4 en los tramos medidos. Los 14 huecos son rutas de diseño (probado). El hueco del 23-ago→10-sep fue un defecto de guardado (commit 3ade3b3, corregido 10-sep 19:42): 157 entregas desde el 11-sep, 0 pérdidas. Lo que falta: cubrir la reacción del VIP (C3) y los tramos corregir/escalar.
Desplegado:    Ronda E3/E4 (2026-10-08): sabotaje sobre copia descartable (producción intacta) y
               vigilantes V2/V7 activados por cron de usuario (10:17 UTC, solo lectura).
               `.env` real: FEATURE_AUTONOMY_QUALITY_ENABLED=true (bandera VIVA, verificada hoy).
               Ver audit/FASE2-SABOTAJE.md.
Hallazgos:     H-SB-2 (cerrado, 2026-10-08): los DOS niveles de silencio del contrato quedaron
               probados con evidencia — el `except` del servicio (`outcome_record_shadow_failed`) y
               el del orquestador (`outcome_log_error`, vía log_swallowed). El riesgo no es que
               fallen callados (avisan), sino que el turno sigue adelante y la fila falta: eso es
               exactamente lo que vigila V2.
               Calibración del vigilante: las 5 alertas iniciales de V2 eran sesiones de sandbox
               (§4.20: no persisten a propósito, con `post_turn_skipped_sandbox` en el journal), no
               fallas. El ejecutor las descarta leyendo el journal; sin ese filtro el vigilante
               habría avisado cada vez que la dueña prueba el sandbox.
               H1 sigue siendo riesgo sistémico pero NO fue la causa aquí (0 errores en logs 30-sep→6-oct). Causa real del hueco: upsert que borraba owner_outcome. Ver INVESTIGACION-A.md
