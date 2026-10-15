# C-SBX-01 — El sandbox prueba sin ensuciar nada

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-SBX-01
Promesa:       En un chat de prueba, Diana hace el mismo recorrido pero sin consecuencias: no guarda
               memoria, ni ejemplos, ni medición, ni historial durable. Las decisiones de doctrina sí
               se guardan, porque de ellas salen normas aplicables a situaciones reales.
Fuente:        AGENTS.md §3 flujos 4.7 y 4.20 (criterio de persistencia del 2026-08-25); BR-06;
               docs/SPEC-FASE2.md §6.4.
Disparador:    mensaje de negocio en un chat marcado como sandbox.
Efecto:        Cero filas nuevas, por ese turno, en `memories`, `examples`, `profiles`,
               `turn_outcome_log`, `vip_trust_budget` y `message_history`; con el envío directo
               encendido, el mensaje sale de inmediato y sin pasar por la cola de la dueña. En cambio,
               la consulta de zona gris y la política viva **sí** se escriben en la base real, porque
               son doctrina y no memoria del usuario. El aviso a la dueña aclara que la lección de
               Reprender no se guardó.
Banderas:      `FEATURE_SANDBOX_ENABLED` (hoy `true`) → OFF: no hay sandbox.
               `FEATURE_SANDBOX_AUTO_SEND` (hoy `true`) → OFF: el sandbox vuelve a pedir aprobación,
               byte a byte como antes.
               Es independiente de `FEATURE_AUTONOMOUS_MODE` y del permiso por VIP: es una superficie
               de prueba de la dueña, y los VIP reales nunca se ven afectados.
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
