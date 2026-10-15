# C-ESC-01 — La escalación llega a la dueña, y el falso positivo reanuda el flujo

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-ESC-01
Promesa:       Cuando el bot decide no responder solo (por seguridad, riesgo, molestia, o porque el
               mensaje dispara una regla fija), la dueña recibe el aviso con el botón para ver la
               traza, marcar falso positivo o responder ella misma; marcar "falso positivo" no cierra
               el caso: lo devuelve al flujo normal con un borrador listo.
Fuente:        AGENTS.md §3 flujos 4.2 y 4.21, §4.1 (prioridades del Decisor); docs/SPEC-1.1.md
               (escalación); docs/ANEXO-H.md (H3 frustración, H4 pregunta repetida, H6 detección de
               IA); docs/ANEXO_T-TRAZABILIDAD.md; REQ-ESC-01..06; REQ-MET-03.
Disparador:    (a) decisión `escalate` del Decisor al cerrar el pipeline; (b) cortocircuito
               determinístico antes del Analista (palabra prohibida, pregunta repetida, detección de
               IA); (c) la dueña toca "➖ Falso positivo" o "✍️ Responder al VIP" en el DM.
Efecto:        Fila en `escalation_events` (`tipo`, `motivo`, `business_connection_id`,
               `notificado=true`) y turno en `escalated`; DM a la dueña con los tres botones. Tras el
               falso positivo: marca en `owner_marks`, el turno sale de `escalated` hacia
               `pending_approval` con borrador en `pending_approvals` (o hacia zona gris si el Decisor
               regenerado pide doctrina), y `escalation_events.motivo` conserva la causa original.
               Métrica `learning_metrics.false_positive_escalation_rate`.
Banderas:      `FEATURE_ESCALATION_FP_DRAFT_ENABLED` (hoy `true`) → OFF: marcar el falso positivo
               cierra el caso sin reanudar (comportamiento anterior a la flag).
               `FEATURE_GRAY_ZONE_ENABLED` (true) → el resume puede abrir consulta de doctrina en vez
               de cola de aprobación.
               `FEATURE_QUALITY_FEEDBACK_ENABLED` (true) — no cambia este camino.
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
