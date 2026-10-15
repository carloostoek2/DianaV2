# C-ATN-01 — Atención respeta su ciclo, su tope diario y el cierre por pago

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-ATN-01
Promesa:       Quien pide información entra a un proceso de un día: recibe la promoción automática, se
               le atiende con borradores que la dueña aprueba, hasta 20 mensajes por día; al día
               siguiente el proceso se cierra solo, y si la persona paga, el ciclo se cierra y la
               entrega pasa a manos de la dueña.
Fuente:        AGENTS.md §3 (Fase 4); docs/SPEC-FASE4.md §5, §235 y §248 (retiro de la plantilla de
               cierre, 2026-09-08); REQ-ATN-01..14; REQ-ATN-13 (anti-contaminación entre canales).
Disparador:    (a) mensaje con el disparo de información; (b) cada mensaje siguiente dentro de la
               ventana del ciclo; (c) detección de pago; (d) cambio de día en la zona horaria local.
Efecto:        Fila en `atencion_cycles` (`started_at`, `closed_at`, `close_reason`) y contador por
               chat y día en `daily_message_limits`; el mensaje que supera el tope se **descarta en
               silencio** (la plantilla de cierre se retiró el 2026-09-08: no se contesta ni se
               avisa); `turns.channel_type='atencion'`; los borradores pasan por la cola de la dueña;
               el pago dispara el aviso fijo de la dueña y cierra el ciclo. El vocabulario comercial
               de pago no escala; una reclamación sí.
Banderas:      `FEATURE_GENERAL_MODE_ENABLED` (hoy `true`) → OFF: los chats que no son VIP no entran
               al canal de atención.
               Ajustes: `ATENCION_CYCLE_WINDOW_DAYS` (ventana del ciclo) y el tope diario de 20.
               El chequeo del tope es **fail-open**: si no se puede leer el contador, se atiende
               igual (la falla queda solo en el registro técnico).
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
