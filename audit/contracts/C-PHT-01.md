# C-PHT-01 — El saludo puro se contesta solo; con sustancia vuelve al pipeline

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-PHT-01
Promesa:       Un saludo o un "¿cómo estás?" sin nada más se responde al instante con sus propias
               frases, sin pasar por la cola de la dueña. Si el mensaje trae algo más (ventas, un
               pedido, un problema, o texto largo), vuelve al pipeline completo.
Fuente:        AGENTS.md §3 flujo 4.17 (saludo y check-in fático); docs/ANEXO-H.md (H9, saludo puro
               y clasificador fático).
Disparador:    mensaje de negocio de un VIP que el clasificador marca como saludo puro, check-in de
               bienestar o check-in del día, siempre que el texto encaje en una de las formas cortas
               admitidas.
Efecto:        El turno queda entregado sin fila en `pending_approvals` y sale un mensaje real al
               VIP, elegido de una lista corta según el caso (saludo / bienestar / día). Con la
               bandera apagada, el turno va a la cola como cualquier otro. Los chats de Atención y
               los VIP congelados o pausados no entran por este carril.
Banderas:      `FEATURE_PHATIC_AUTO_SEND` (hoy `true`) → OFF: el saludo vuelve a la cola de
               aprobación.
               `FEATURE_PHATIC_AUTONOMY` (hoy `true`) — solo mide (`would_autonomous`); no habilita el
               envío.
               **No depende de** `FEATURE_AUTONOMOUS_MODE`: es un carril propio. Hoy es el único
               envío real sin aprobación que ocurre en producción.
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
