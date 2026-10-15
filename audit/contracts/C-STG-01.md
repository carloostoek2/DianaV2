# C-STG-01 — La corrección no enseña sola: espera la confirmación de la dueña

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-STG-01
Promesa:       Cuando la dueña corrige un borrador, la corrección queda como candidata y **no** se
               convierte en enseñanza hasta que ella lo confirme; al confirmar, respeta el alcance que
               eligió y el canal del que viene.
Fuente:        AGENTS.md §3 flujo 4.6 y §2.1 (Learning); docs/SPEC-FASE2.md (Staging);
               REQ-TRN-07, REQ-ADM-08, BR-13, REQ-NFR-16; REQ-ATN-13 (Atención no promueve al banco
               VIP).
Disparador:    (a) la dueña corrige un borrador desde el DM; (b) confirma, descarta o promueve
               desde la cola de revisión.
Efecto:        Fila en `staging_candidates` con `candidate_type`, `payload` y `status='pending'`;
               al promover, fila en `examples` (o `policies`) con el alcance elegido (solo ese VIP o
               global). Ninguna corrección nacida en el canal de Atención puede promover al banco VIP.
               Con la bandera apagada no hay cola de candidatas y la corrección no deja candidata.
Banderas:      `FEATURE_STAGING_ENABLED` (hoy `true`) → OFF: no hay cola de candidatas.
               `FEATURE_QUALITY_FEEDBACK_ENABLED` (true) abre el camino directo de Destacar, que por
               diseño **no** pasa por esta cola (ver C-FB-01): es la excepción declarada, no un
               atajo.
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
