# C-LNK-01 — El aviso de expulsión pide decisión una sola vez

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-LNK-01
Promesa:       Si el bot que administra el canal VIP expulsa a un suscriptor, Diana avisa a la dueña
               con el nombre y tres opciones (expulsar, desactivar, mantener) y aplica la que ella
               elija. El mismo aviso no se repite.
Fuente:        AGENTS.md §3 flujo 4.14; docs/SPEC-FASE6.md; REQ-LNK-01..10 (migración real 028, no
               027); docs/ESTADO-PROYECTO.md §Fase 6.
Disparador:    una línea `[LINK]` en el chat de coordinación, consumida antes de la detección de la
               dueña y sin entrar al pipeline cognitivo.
Efecto:        El mensaje se consume y **no** entra al historial ni al pipeline; fila en `link_events`
               con `event_id`, `user_id` y `state`. Si la persona no es VIP activo, se registra como
               ignorado y no hay aviso (`ignored_not_vip`). Si lo es, DM con los tres botones y, al
               decidir, `vips.is_active=false` (expulsar), un congelamiento lejano (desactivar) o
               nada (mantener), con `state=decided_*`. El identificador del evento es único: el mismo
               aviso no vuelve a notificarse. Un aviso malformado no rompe nada y queda registrado.
Banderas:      `FEATURE_LINK_ENABLED` (hoy `true`) → OFF: el middleware queda inerte, no hay router
               de botones y el comportamiento es el anterior, idéntico.
               Ajustes: `link_chat_id` (chat de coordinación) y `link_disable_frozen_until` (hasta
               cuándo se congela al desactivar).
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
