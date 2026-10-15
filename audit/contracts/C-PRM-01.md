# C-PRM-01 — La promoción responde una sola vez por ventana

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-PRM-01
Promesa:       Cuando alguien que no es VIP escribe una palabra exacta de promoción, Diana manda la
               secuencia de mensajes sin usar el modelo. Dentro de las primeras horas no vuelve a
               responder; pasado ese plazo usa una variante; y si el envío falla, se puede reintentar
               más adelante.
Fuente:        AGENTS.md §3 flujo 4.10 y §4.4 (contrato de repetición, opción de producto A);
               REQ-PRO-01..04; docs/SPEC-FASE3.md §6.3 (contrato de reenvío).
Disparador:    mensaje de un chat que no está en la lista de VIP y cuyo texto coincide **exactamente**
               con un disparo configurado (sin parecido ni interpretación).
Efecto:        Fila en `promo_executions` (`chat_id`, `trigger_id`, `sent_at`, `sequence_sent`,
               `status`); la secuencia sale con esperas y "escribiendo…" entre mensajes; no se escribe
               en `pipeline_traces` ni en el historial del chat. Dentro de `promo.cooldown_hours` el
               resultado es `suppressed` (silencio, sin entrega), incluido un segundo toque
               simultáneo, porque el turno se reclama antes de empezar a enviar. Si el envío falla, el
               reclamo pasa a `failed` y el disparo puede volver a intentarse.
Banderas:      `FEATURE_PROMO_ENABLED` (hoy `true`) → OFF: los chats que no son VIP no reciben
               promoción (queda el descarte normal).
               Ajustes asociados: `promo.cooldown_hours` (24 por defecto), `promo.repeat_days` (30 por
               defecto) y `repeat_first_message` para la variante de reenvío.
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
