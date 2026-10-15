# C-PRF-01 — El perfil del VIP se vuelve a sintetizar sin contaminar el banco de ejemplos

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-PRF-01
Promesa:       Cuando se acumulan señales fuertes (correcciones repetidas, cambio de estado), el
               sistema vuelve a sintetizar el perfil del VIP, guarda la versión anterior y **nunca**
               deja que el perfil entre al banco de ejemplos compartido.
Fuente:        docs/SPEC-EVOLUCION-AGENTE.md Fase 1 (resíntesis) y EA-05 (anti-contaminación),
               EA-06 (historial de versiones).
Disparador:    (a) se cumplen las condiciones de señal fuerte al cerrar un turno; (b) el job de
               síntesis drena la cola durable; (c) la dueña abre la ficha del VIP.
Efecto:        Filas versionadas en `vip_profile` y su historial en `vip_profile_history`; la cola
               `profile_synthesis_queue` avanza; una síntesis de baja confianza no sobrescribe la
               versión buena. La ficha muestra las últimas versiones con fecha y resumen del cambio.
               El perfil nunca escribe en `examples`.
Banderas:      `FEATURE_PROFILE_SYNTHESIS_ENABLED` (hoy `true`) → OFF: no se dispara ni corre la
               síntesis. Es una capacidad de medición: no cambia ninguna decisión del bot.
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
