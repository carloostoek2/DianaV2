# C-APR-01 — Aprobar entrega de verdad, y con forma humana

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-APR-01
Promesa:       Cuando la dueña aprueba un borrador (o corrige y confirma), el mensaje sale al VIP por
               la conexión correcta, con la forma humana configurada (espera previa, marca de leído,
               "escribiendo…", división en varios mensajes) y queda registrado como enviado.
Fuente:        AGENTS.md §3 flujo 4.1, §4.2 (Behavior Engine) y §4.12 (mensajes divididos y tics
               humanos); REQ-HUM-01..06; REQ-AUTH-04 (salida en nombre de la dueña);
               docs/contratos_restantes.md Anexo I.4 y I.5.
Disparador:    la dueña toca "Aprobar" (o confirma una corrección) sobre un borrador que está en su
               cola.
Efecto:        El mensaje sale por la conexión de negocios del chat; `turns.status='delivered'`; el
               resultado de la entrega queda en la traza; se escribe una fila en `message_history` con
               el texto saliente y su identificador; la fila de `pending_approvals` queda resuelta. Si
               el turno quedó obsoleto o la entrega falla, no se envía y el motivo queda registrado,
               con aviso a la dueña cuando corresponde.
Banderas:      `FEATURE_ADVANCED_BEHAVIOR` (hoy `true`) → OFF: sin división de mensajes ni tics
               humanos; el resto de la entrega sigue igual.
               `FEATURE_SANDBOX_AUTO_SEND` no aplica a VIP reales (solo a chats de prueba).
               La división y los tics son propiedades de la entrega, no configuraciones globales.
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
