# C-SUP-01 — Un mensaje nuevo cancela la respuesta anterior

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-SUP-01
Promesa:       Si el VIP escribe otra vez mientras hay un turno pendiente, el anterior se cancela y
               no se le envía: nunca salen dos respuestas, ni una respuesta que ya quedó vieja.
Fuente:        AGENTS.md §3 flujo 4.3 y §2.1 (Turn Coordinator); REQ-VIP-06, REQ-VIP-08,
               REQ-NFR-02; docs/contratos_restantes.md Anexo G.3 (invariante marcado como no
               negociable); docs/ANEXO-H.md (cortocircuitos que también escriben historial).
Disparador:    mensaje de negocio del mismo chat cuando ya existe un turno no terminal.
Efecto:        El turno anterior pasa a `superseded`; si estaba esperando aprobación, su fila en
               `pending_approvals` deja de estar viva; el motor de comportamiento aborta la entrega
               cuando el turno dejó de estar vigente, de modo que no sale nada al VIP; y en todo
               momento hay como máximo **una** fila de turno no terminal por chat.
Banderas:      Ninguna propia. Interactúa con `FEATURE_AUTONOMOUS_MODE` (el camino de envío autónomo
               también debe respetar la obsolescencia) y `FEATURE_SANDBOX_AUTO_SEND` (el envío
               directo del sandbox es instantáneo, pero un mensaje nuevo sigue mandando).
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
