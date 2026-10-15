# C-MEM-01 — Diana recuerda al VIP, y lo sensible espera la aprobación de la dueña

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-MEM-01
Promesa:       Lo que el VIP cuenta queda guardado como memoria suya y disponible en los turnos
               siguientes; los hechos sensibles no entran al contexto hasta que la dueña los aprueba;
               y un VIP nunca ve la memoria de otro.
Fuente:        AGENTS.md §3 flujo 4.4 y §2.1 (Learning); docs/SPEC-FASE5.md (4 pools);
               REQ-MEM-02..12; BR-15; EA-05; docs/ANEXO-H.md (H8, `needs_examples`).
Disparador:    (a) turno terminado (extracción posterior al turno); (b) botón "🔄 Generar perfil"
               sobre el historial; (c) nota manual de la dueña; (d) aprobación o descarte de un hecho
               sensible desde el DM.
Efecto:        Filas nuevas en `memories` con `category`, `content`, huella semántica, `source_turn_id`
               y `status`; los hechos sensibles quedan en `pending_owner` y **no** aparecen en el
               contexto hasta pasar a `approved` (los descartados tampoco); el recuperador filtra por
               estado y por VIP. La ficha del VIP se arma por secciones en `profiles`. El camino es
               best-effort: si falla, el turno sigue igual, pero el motivo debe quedar registrado.
Banderas:      `FEATURE_MEMORY_ENABLED` (hoy `true`) → OFF: no se cablea ni la extracción ni la
               recuperación de memoria.
               `FEATURE_CONTEXT_ENABLED` (true) — gobierna el bloque de contexto interpretado.
               `FEATURE_PROFILE_SYNTHESIS_ENABLED` (true) — resíntesis del perfil (ver C-PRF-01).
               `FEATURE_FORCE_PROFILE_WHEN_NOTES` (default `true` en el código) — perfil con notas.
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
