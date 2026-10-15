# C-FB-01 — Destacar enseña enseguida; Reprender corrige y después se elige el alcance

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-FB-01
Promesa:       Sobre un borrador de VIP, la dueña puede marcar "Destacar" para que ese texto cuente
               como ejemplo bueno, o "Reprender" para que su corrección salga de inmediato y después
               decidir si esa lección vale para ese VIP o para todos. En el canal de Atención ninguno
               de los dos existe.
Fuente:        AGENTS.md §3 flujo 4.13; docs/SPEC-FEEDBACK.md (migración 029); REQ-ATN-13;
               docs/ESTADO-PROYECTO.md §Feedback de calidad.
Disparador:    (a) la dueña toca "Destacar" o "Reprender" en el teclado del borrador;
               (b) elige el alcance (este VIP o global); (c) llega un mensaje nuevo del mismo chat
               (eso cancela el paso pendiente del combo).
Efecto:        Destacar inserta una fila en `examples` con `quality='gold'` y el `vip_id` elegido,
               **sin** pasar por `staging_candidates`; Reprender entrega el texto de corrección al
               chat y deja el contraejemplo (`is_counter_example`) con el alcance elegido. El
               recuperador ordena primero lo destacado. En Atención no aparece la fila de botones.
Banderas:      `FEATURE_QUALITY_FEEDBACK_ENABLED` (hoy `true`) → OFF: el teclado vuelve a
               Aprobar/Corregir/Escalar y no hay Destacar ni Reprender. El orden "primero lo
               destacado" en la recuperación **no** depende de la bandera (sigue activo).
               En sandbox el Reprender entrega el texto pero no guarda la lección (aislamiento).
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
