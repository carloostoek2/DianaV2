
  1. Recuperación de mensajes tras caída

  v1 usa Application.run_polling() con allowed_updates=["business_connection",
  "business_message", "edited_business_message", "message", "callback_query"].
  PTB persiste el update_id y al reconectar Telegram entrega todos los updates
  pendientes.

  v2 ahora incluye edited_business_message en allowed_updates, y además tiene
  missed_message_recovery.py que ejecuta get_updates(offset=None, timeout=0)
  ANTES de arrancar el polling, drenando el buffer de Telegram servidor-side
  y alimentando cada update via dispatcher.feed_update(). Esto compensa que
  aiogram no persiste update_id en disco.

  ✅ RESUELTO — la combinación de missed_message_recovery + polling cubre el
  caso mejor que v1 incluso.

  ---
  2. Persistencia de estado runtime + recuperación en reinicio

  v1 tiene diana_runtime.json y connections.json. Persiste en disco:
  timer_schedule, pending_approval, pending_guidance, pending_escalations,
  reply_gen, chat_bc, chat_meta. En cada reinicio, recover_runtime_on_startup()
  (handlers/recovery.py:68) restaura todo: timers con tiempo restante,
  borradores desde DB, re-notifica consultas de zona gris, y manda un DM a Diana
  resumiendo la recuperación.

  v2 AHORA tiene runtime_timers (tabla SQL + migration 014), timer persistence
  en BehaviorEngine (create_active antes del delay, mark_completed en finally),
  recovery_startup extiende run_startup_recovery con _recover_timers (async
  gather concurrente), recover_zombie_turns (marca turns no-terminales como
  FAILED con error="crash_recovery"), y rematerialize_drafts (re-crea
  PendingApproval desde pipeline_traces para turns stuck en generating/
  evaluating/deciding). Report extendido con timers_recovered, zombie_turns_
  expired, drafts_rematerialized. DM de resumen incluye los 3 contadores.

  ✅ RESUELTO — timers, zombie turns, y draft re-materialization completos.

  ---
  3. Manejo de edited_business_message

  v1 escucha edited_business_message en allowed_updates y en
  handlers/business.py:274 explícitamente ignora ediciones de VIP ("Edición
  ignorada"). Si el owner edita un mensaje, lo omite con log.

  v2 AHORA escucha edited_business_message (en allowed_updates y con handler
  en business.py:54-87). A diferencia de v1, NO lo ignora: lo procesa a través
  del TurnCoordinator completo, incluyendo middleware stack (Dedup, RateLimit,
  FreezeCheck, etc.). También cubierto por missed_message_recovery.

  ✅ RESUELTO — y va más allá que v1: procesa la edición en lugar de ignorarla.

  ---
  4. Handler explícito de BusinessConnection

  v1 registra BusinessConnectionHandler(handle_business_connection) que graba
  connections.json cuando Diana activa/desactiva la conexión, guarda
  diana_user_id y configura al admin.

  v2 tiene BusinessConnectionMiddleware que extrae el business_connection_id de
  los mensajes entrantes, registrado en business_message, edited_business_message
  y message. NO hay handler para el update type BusinessConnection (lifecycle
  enable/disable), no está en allowed_updates, y no persiste estado de conexión.

  v2 AHORA tiene BusinessConnectionStore (protocolo en ports.py, implementación
  SQL en business_connections.py, InMemory double en memory.py), handler en
  telegram/handlers/business_connection.py que recibe el update type
  BusinessConnection de Telegram vía @router.business_connection(), middleware
  mínimo (ErrorHandler + Logging), y "business_connection" en allowed_updates de
  main.py. Persiste is_enabled, user_id, user_chat_id, date, can_reply con
  upsert por business_connection_id. Alembic migration 015_business_connections.

  ✅ RESUELTO — handler de ciclo de vida completo con persistencia.

  ---
  5. Promo-info para NO-VIPs (auto-respuesta con plantillas fijas sin LLM)

  v1 tiene services/promo_info.py: si un no-VIP escribe exactamente una palabra
  trigger (ej. "info"), el bot responde con 2 mensajes secuenciales de plantilla
  fija, con delay humano. Sin LLM, sin approval, sin training. Trackea quién ya
  fue informado para variar el mensaje.

  v2 tiene PromoService (application/promo_service.py) con matching exacto,
  sin LLM. Integrado en AuthMiddleware: si un no-VIP manda un mensaje y
  FEATURE_PROMO_ENABLED está activo, matchea triggers y ejecuta secuencia vía
  deliver_with_sequence(). DB-backed (promo_triggers, promo_executions).

  ✅ RESUELTO — equivalente funcional, aunque requiere configuración en DB
  en lugar de un archivo Python plano.

  ---
  6. Data Pause por VIP (pausar recolección de datos)

  v1 services/data_pause.py permite pausar/reanudar la recolección de datos por
  VIP, con auto-expiración (1 día, 3 días, 1 semana, 1 mes, indefinido). Durante
  la pausa: no se registra historial, no se generan ejemplos, el bot no
  interactúa. Limpia estado en memoria.

  v2 AHORA tiene admin UI completa: keyboard inline en el perfil VIP con
  duraciones (1 día, 3 días, 1 semana, 1 mes, indefinido), handlers de pause/
  unpause en menu.py vía callback queries, teclas de duración en keyboards.py,
  y métodos pause_vip/unpause_vip en VipStore (SQL + InMemory). La UI reutiliza
  el patrón existente de FreezeCheckMiddleware: el botón muestra el estado
  actual, las duraciones se presentan en 6 filas, y el callback actualiza
  paused_until en DB. AuthMiddleware ya gateaba usuarios pausados — ahora el
  admin puede controlarlo sin SQL manual.

  ✅ RESUELTO — interfaz de gestión completa con persistencia.

  ---
  7. Registro de escalaciones a archivo de texto

  v1 handlers/business.py:28-41: log_escalation() escribe cada escalación a
  diana_escalaciones.txt con timestamp, usuario, motivo, y últimos 6 mensajes de
  contexto.

  v2 guarda en DB (escalations table) y notifica al owner vía Telegram DM.
  Además escribe un archivo de texto legible: logger diana.escalations con
  RotatingFileHandler (5 MB, 5 backups) en /var/log/diana/escalations.log.

  ✅ RESUELTO (implementado) — archivo de texto plano para debug/auditoría
  (src/diana/application/admin_service.py:52-97).

  ---
  8. Contexto temporal / rutina semanal

  v1 services/schedule.py tiene resolve_current_activity() que determina qué
  está haciendo la dueña según día/hora (servicio social, inglés, prácticas,
  diplomado, etc.) y build_temporal_context_block() que inyecta ese bloque en el
  system prompt.

  v2 tiene ScheduleRetriever (cognitive/retrievers/schedule.py) con matching
  día/hora en America/Mexico_City, registrado en registry.py como
  knowledge.schedule. Context builder (_format_schedule_body) lo formatea como
  bloque narrativo. DIFIERE de v1: la inyección es condicional — el Planner
  decide si needs_schedule es relevante, no se inyecta en every prompt como
  v1.

  ⚠️ PARCIAL — infraestructura completa, pero invocación condicional en vez de
  garantizada.

  ---
  9. History backfill al arranque

  v1 diana.py:164-168: al iniciar, encola VIPs faltantes para backfill de
  historial (history_backfill.enqueue_missing_vips()).

  v2 AHORA hace backfill al arranque: el startup sequence (main.py:117-119)
  encola VIPs faltantes vía backfill_queue.enqueue_missing_vips() antes del
  polling, con guards de 24h y skip de VIPs sin historial ni perfil.

  ✅ RESUELTO (implementado) — backfill de historial al arranque con guards
  anti-re-encolado (src/diana/application/memory_backfill_queue.py:275).

  ---
  10. Simulación de "escribiendo..." con loop

  v1 services/delivery.py:36-55: simulate_typing() usa un loop que re-envía
  send_chat_action cada ~4s porque la acción expira a los ~5s en Telegram. Para
  mensajes largos (15s), esto mantiene el indicador visible.

  v2 behavior/engine.py:621-649 (_show_typing): re-envía send_chat_action en un
  loop cada _TYPING_REFRESH_SECONDS=4.0s mientras quede duración de typing, así
  el indicador permanece visible para mensajes largos.

  ✅ RESUELTO (implementado) — loop de refresh que mantiene el indicador
  "escribiendo..." visible (src/diana/behavior/engine.py:56, 621-649).

  ---
  11. Notificación a Diana admin al arranque con resumen de recuperación

  v1 handlers/recovery.py:132-153: al terminar la recuperación, envía un DM a
  Diana listando timers, borradores y consultas recuperados.

  v2 recovery_startup.py:_notify_recovery_summary() envía DM con:
  entregas reanudadas, borradores re-notificados, entregas expiradas. Si no
  hay nada que recuperar, envía "Nada que recuperar."

  ✅ RESUELTO — cubierto e incluso más completo que la descripción original.

  ---
  12. Observación de mensajes no autorizados con persistencia

  v1 handlers/business.py:236-248: si OBSERVE_UNAUTHORIZED=True, registra
  mensajes de chats no autorizados como "ejemplos observados" para training.

  v2 no tiene este modo. Los no-VIP son: (1) enviados a training mode si está
  activo, (2) respondidos con promo si hay match, (3) silenciosamente descartados
  con log auth_drop_not_allowed. No hay recolección pasiva para training.

  ❌ NO IMPLEMENTADO

  ---
  Estado actual

  ┌─────┬────────────────────────────────┬──────────┬──────────────────────────────────────┐
  │  #  │         Funcionalidad          │  Estado  │              Notas                   │
  ├─────┼────────────────────────────────┼──────────┼──────────────────────────────────────┤
  │  1  │ Recuperación mensajes          │    ✅    │ missed_message_recovery + polling     │
  │     │ post-caída                     │ RESUELTO │ compensa falta de offset persistente  │
  ├─────┼────────────────────────────────┼──────────┼──────────────────────────────────────┤
  │  2  │ Runtime state persistence +    │    ✅    │ timers, zombie turns, draft           │
  │     │ recovery                       │ RESUELTO │ re-materialization completos          │
  ├─────┼────────────────────────────────┼──────────┼──────────────────────────────────────┤
  │  3  │ edited_business_message        │    ✅    │ handler completo con middleware       │
  │     │                                │ RESUELTO │ stack — mejor que v1 (que lo ignoraba)│
  ├─────┼────────────────────────────────┼──────────┼──────────────────────────────────────┤
  │  4  │ BusinessConnection handler     │    ✅    │ handler lifecycle enable/disable con  │
  │     │                                │ RESUELTO │ persistencia SQL + migration          │
  ├─────┼────────────────────────────────┼──────────┼──────────────────────────────────────┤
  │  5  │ Promo-info no-VIP simple       │    ✅    │ PromoService con exact-match,         │
  │     │                                │ RESUELTO │ sin LLM, multi-message con delays     │
  ├─────┼────────────────────────────────┼──────────┼──────────────────────────────────────┤
  │  6  │ Data Pause por VIP             │    ✅    │ UI admin completa con teclado de     │
  │     │                                │ RESUELTO │ duraciones, pause/unpause en DB       │
  ├─────┼────────────────────────────────┼──────────┼──────────────────────────────────────┤
  │  7  │ Escalaciones a archivo txt     │    ✅    │ RotatingFileHandler en logger        │
  │     │                                │ RESUELTO │ diana.escalaciones (admin_service)   │
  ├─────┼────────────────────────────────┼──────────┼──────────────────────────────────────┤
  │  8  │ Contexto temporal / rutina     │    ⚠️   │ ScheduleRetriever listo; inyección   │
  │     │ semanal                        │ PARCIAL  │ condicional, no garantizada           │
  ├─────┼────────────────────────────────┼──────────┼──────────────────────────────────────┤
  │  9  │ History backfill al arranque   │    ✅    │ enqueue_missing_vips() en startup     │
  │     │                                │ RESUELTO │ (main.py:117-119, queue:275)          │
  ├─────┼────────────────────────────────┼──────────┼──────────────────────────────────────┤
  │ 10  │ Loop de "escribiendo..."       │    ✅    │ loop de refresh cada 4s mantiene      │
  │     │                                │ RESUELTO │ el indicador (engine.py:621-649)      │
  ├─────┼────────────────────────────────┼──────────┼──────────────────────────────────────┤
  │ 11  │ DM de recuperación a Diana     │    ✅    │ _notify_recovery_summary() envía      │
  │     │                                │ RESUELTO │ resumen detallado post-recovery       │
  ├─────┼────────────────────────────────┼──────────┼──────────────────────────────────────┤
  │ 12  │ Observación de no autorizados  │    ❌    │ no existe el modo de observación     │
  │     │                                │ PENDIENTE│                                        │
  └─────┴────────────────────────────────┴──────────┴──────────────────────────────────────┘

  Resumen: 10 ✅ resueltos, 1 ⚠️ parcial, 1 ❌ pendiente.

  ¿Quieres que profundice en alguna de estas? La #1 y #2 son las que más impacto
   operativo tienen. Para la #1, puedo investigar exactamente por qué aiogram no
   está recuperando los mensajes pendientes — probablemente sea configuración
  del offset de updates.

✻ Worked for 2m 13s

❯ Excelente fantástico análisis. Todo me parece correcto pero De hecho tenía    
  esta duda y ahora que lo vio lo quiero preguntar.                             
  Eso de escuchar la edición del mensaje del usuario VIP se refiere a que si un 
   usuario edita su mensaje nosotros escuchando eso digamos que se actualiza    
  ese mensaje hacia nosotros? Si es así entonces sí deberíamos de tomarlo en    
  cuenta porque si un usuario edita su mensaje cambiando algo característico y  
  el bot responde a eso que ya no existe en ese momento va a parecer muy        
  extraño, sería muy extraño. Pero eso es lo que me estoy imaginando que        
  significa que así me confirmas que si es eso entonces sí hay que tomar en     
  cuenta la edición del mensaje y tal vez haya que reiniciar el proceso cuando  
  pase eso                                                                      

● Buena pregunta. Déjame revisar exactamente qué hace v1 con los mensajes
  editados para confirmártelo.

  Read 2 files (ctrl+o to expand)

● Sí, exactamente eso es. Te confirmo con el código:

  v1 sí escucha edited_business_message. En handlers/router.py:108-112:

  if update.edited_business_message:
      await _handle_business_message(
          update.edited_business_message, context, edited=True,
      )
      return

  El mensaje editado trae el texto nuevo (el contenido ya modificado). Pero
  cuando llega a la sección de VIP autorizado, lo que hace es simplemente
  ignorarlo (handlers/business.py:274):

  if edited:
      log.info(f"Edición ignorada de {username} ({vip_id})")
      return

  O sea: v1 ya lo escucha, pero lo tira a la basura. No actualiza el historial,
  no cancela el timer en curso, no reinicia el proceso de respuesta. Si el VIP
  cambió completamente el mensaje mientras el timer está corriendo, Diana va a
  responder al texto original que ya no existe. Como dices, quedaría muy
  extraño.

  Lo correcto sería:

  1. Escuchar la edición (recibir el texto nuevo)
  2. Actualizar el historial con el contenido editado
  3. Cancelar el timer actual (si hay uno en vuelo)
  4. Incrementar reply_gen y disparar un nuevo ciclo de respuesta

  Es una funcionalidad pequeña pero importante. En DianaV2 ni siquiera se
  escucha edited_business_message — no está en allowed_updates y no hay handler.
   Habría que:

  1. Agregarlo a allowed_updates en main.py
  2. Crear un handler en telegram/handlers/business.py que reciba la edición
  3. Hacer que el TurnCoordinator cancele el turno actual y cree uno nuevo con
  el texto editado

  ¿Quieres que implemente esto en DianaV2? Es relativamente acotado — toca
  principalmente el handler de business, el orchestrator, y la configuración de
  polling.

✻ Sautéed for 17s
