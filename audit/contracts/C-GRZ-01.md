# C-GRZ-01 — Sin doctrina el chat se congela, y la regla de la dueña se aplica al mismo turno

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-GRZ-01
Promesa:       Cuando el bot no tiene una norma para responder, no improvisa: congela el chat, le
               pregunta a la dueña, y cuando ella escribe la norma la aplica al mismo turno y deja el
               borrador en su cola. El chat no se descongela hasta que un mensaje salga de verdad.
Fuente:        AGENTS.md §3 flujos 4.5 y 4.16; docs/SPEC-FASE2.md §6.2 (supersede: el resolve ya no
               pasa por Staging) y §6.2 (regla clave sobre `staging_candidates`); REQ-GAP-01..11;
               BR-14; docs/SPEC-FEEDBACK.md (paracaídas del DM de doctrina).
Disparador:    (a) el Decisor emite `consult_doctrine` (hay necesidad de norma y ninguna política
               aplicable, con la zona gris encendida); (b) la dueña responde con texto libre, usa la
               regla propuesta o escala; (c) vence el plazo de la consulta.
Efecto:        Fila en `gray_zone_queries` con `status='open'` y `freeze_until`, más el chat
               congelado (`vips.frozen_until`; en Atención, por `chat_id`); DM de doctrina con el
               mensaje original y los botones. Al resolver: fila activa en `policies`
               (`trigger_description`, `rule`, `scope`, `vip_id`), regeneración del mismo turno y
               `gray_zone_queries.status='awaiting_send'`; el `status` pasa a `resolved` y el chat se
               descongela **solo** con un envío real exitoso. Si la regla no logra aplicarse, la
               política recién insertada se desactiva y la consulta sigue `open` (nada se envía). Si
               el aviso de la consulta falla, el chat se descongela y el borrador cae en la cola
               (`reason=vip_doctrine_notify_failed` / `atencion_doctrine_notify_failed`).
               Al vencer el plazo solo expiran las consultas `open`: se usa el borrador original o se
               escala.
Banderas:      `FEATURE_GRAY_ZONE_ENABLED` (hoy `true`) → OFF: no hay consulta, ni congelación, ni
               política; el comportamiento vuelve al de Fase 1.
               `FEATURE_GRAY_ZONE_PROPOSAL_ENABLED` (hoy `true`) → OFF: el DM llega sin propuesta de
               regla (dos botones en vez de tres). La generación de la propuesta es fail-open: si
               falla o tarda, la consulta y la congelación siguen.
               `FEATURE_STAGING_ENABLED` (true) — **no** participa en el resolve (camino superseded).
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
