🔴 ALTO

  A1. La nota desde borrador no expira ni tiene salida — texto
   accidental se convierte en nota

  callbacks.py:332-353 guarda la sesión en un dict plano
  sessions_note (admin.py:866, setup.py:127), sin TTL ni
  /cancelar. El prompt es solo "📝 Envía el texto de la nota:"
   sin hint de cancelación.
  - Qué pasa: la dueña toca "Agregar nota" en un borrador, se
  distrae, y el siguiente texto normal que escriba al bot se
  guarda como nota del VIP. No hay forma de abortar salvo
  mandar una nota.
  - Principio (Sec. 3): toda acción que captura input necesita
   un escape explícito y un límite de vida.
  - Corrección: reemplaza sessions_note por un
  MenuSessionStore con kind "note" y vip_user_id (ya existe
  ese mecanismo y tiene TTL + /cancelar), o añade expiración y
   responde "Operación expirada" en admin.py:866 cuando el
  dict está vencido. Agrega al prompt "Usa /cancelar para
  abortar."

  A2. Los wizards multi-paso mueren ante una entrada inválida
  (el error miente)                                                                                                           En menu.py:565 la sesión se pop antes de validar. En
  _handle_sandbox_forward (menu.py:1196),
  _handle_register_forward (menu.py:1239) y sandbox_profile
  (menu.py:572), si el input es inválido se muestra el error
  pero no se reinicia la sesión:
  - sandbox_profile dice "Usa los botones para seleccionar un
  perfil." pero la sesión ya se cerró → el siguiente toque se
  pierde.
  - El error de forward dice "Asegúrate de reenviar un
  mensaje…" → el usuario reenvía, y como la sesión ya no
  existe, el mensaje cae al admin router como texto normal.
  - Principio (Sec. 5): el error debe dejar al usuario con una
   acción siguiente real, no un callejón.
  - Corrección: no hacer pop antes de validar. Pasa la sesión
  a cada _handle_* y solo la borras en éxito o /cancelar. Para
   el forward inválido, mantén la sesión viva (o re-start con
  el mismo last_chat_id/last_bot_message_id) y re-edita el
  prompt.


  A3. answerCallbackQuery llega después del trabajo pesado en
  aprobar/corregir/escalar

  callbacks.py:245-267: admin.handle_approve (envío al VIP +
  escrituras DB) se ejecuta dentro de dispatch_owner_callback,
   y el query.answer() recién ocurre en callbacks.py:478+. El
  botón queda girando durante toda la entrega.
  - Principio (Sec. 1, regla dura): responder el callback
  apenas llega, antes de cualquier trabajo.
  - Corrección: al inicio de on_callback, tras el gate de
  owner, ejecuta await query.answer() vacío (limpia el
  spinner). Para los casos de alerta (no-op stale,
  _APPROVE_NOOP_ALERTS), puedes re-responder con
  query.answer(text, show_alert=True) al final — Telegram
  permite un segundo answer en la ventana de ~30s y es el
  patrón estándar para toast tardío. El flujo de
  approved/escalated ya edita el mensaje (feedback principal),
   así que el answer vacío inicial basta.

  ---
  🟠 MEDIO

  A4A4. Descartar en staging/memoria borra datos sin
  confirmación

  staging.py:105-114 (discard → staging.discard) y
  memory_approval.py borran un candidato de forma permanente,
  sin segundo paso y sin undo. El toast "Discarded" ni
  siquiera usa show_alert.
  - Principio (Sec. 3): borrar datos almacenados = confirmar
  con 2 botones y texto específico.
  - Corrección: para staging, cambia el botón a dos pasos: 🗑
  Descartar → confirmar ✅ Sí, descartar / ❌ No, mantener
  (nuevo callback sd:<id>:confirm / sd:<id>:cancel). Para
  memoria, al menos show_alert=True en el toast de
  confirmación, o un "Deshacer" temporal que re-enfile la
  fact.

  A5. Caminos de error sin botón de salida (dead-ends)

  Varios estados pasan keyboard=None en _show, dejando a la
  dueña sin teclado y obligándola a escribir /start:
  menu.py:640, 674, 699, 734, 747, 778, 884, 954, 978, 1013,
  1028 ("Gestion de perfiles no disponible", "No hay modo de
  prueba activo", "No se encontro el chat. Inicia de nuevo…",
  "Accion no disponible", etc.).
  - Principio (Sec. 5): ningún error sin una acción siguiente.
  - Corrección: en cada uno, pasa
  menu_back_keyboard(encode_menu("root")) o el back
  correspondiente en vez de None. Un helper centralizado tipo
  _error(message, text, back) evitaría que se cuelen más None.

  A6. Expiración silenciosa de sesiones multi-paso

  MenuSessionStore._resolve (menu.py:122-129) hace pop
  silencioso al vencer el TTL de 15 min. Si la dueña escribe
  la nota/dato/nombre después de ese tiempo, sessions.pop
  devuelve None y on_menu_session_text (menu.py:565-567) hace
  return sin avisar → el texto se pierde en silencio.
  - Principio (Sec. 5 + Sec. 3): un diálogo vencido debe
  avisar, no tragarse la entrada.
  - Corrección: distinguir "sin sesión" de "sesión vencida".
  En MenuSessionStore, añade un método que reporte si existía
  una sesión expirada, y responde: "Tu operación expiró,
  vuelve a intentarlo."
  
  
  A7. Confirmaciones que nunca caducan (delete / register)

  menu_confirm_delete_keyboard y
  menu_register_confirm_keyboard (keyboards.py:1047-1080) son
  botones planos sin TTL. El delete_confirm de un mensaje
  viejo sigue ejecutando aunque el VIP cambió de estado; peor
  el register confirm (menu.py:920-943): si el
  pending_vip_name ya venció, registra igual el VIP (solo sin
  nombre), con contexto viejo.
  - Principio (Sec. 3, expiración de confirmación): un diálogo
   no debe quedar vivo indefinidamente.
  - Corrección: en on_menu_callback, para register/delete,
  verificar sessions.has_active(actor_id) (o la marca de
  tiempo) antes de ejecutar; si expiró, responde
  query.answer("Esta confirmación expiró, vuelve a
  intentarlo", show_alert=True) y redirige al menú. Implica
  mover el answer de menu.py:449 al final del dispatch para
  los casos con alerta (mismo patrón que A3).

  A8. Export de métricas manda JSON como mensaje de texto (se
  rompe >4096 chars)

  callbacks.py:317-330: query.message.answer(payload) envía el
   JSON semanal como mensaje. Un resumen semanal real casi
  seguro supera 4096 caracteres → Telegram responde 400 y el
  callback cae en "Error al exportar".
  - Corrección: usa BufferedInputFile + answer_document como
  ya hace el export de traza (callbacks.py:441-445), y
  responde el callback antes del trabajo (mismo patrón A3).

  A9. No hay forma de borrar notas/datos desde el menú
  (acciones muertas)

  note_del/fact_del existen en _dispatch_action (menu.py:692,
  739) pero ningún teclado genera esos callbacks — la ficha
  lista notas/datos pero no hay botón de borrado por item. La
  única vía es el comando legacy /vip_note_del / /vip_fact_del
   (admin.py:825-839), que la dueña ya no ve en el menú.
  - Principio: la UI de botones no debe ocultar capacidades
  existentes; el menú y los comandos dicen cosas distintas.
  - Corrección: en la ficha (menu_vip_profile_keyboard o la
  vista profile en menu.py:638-650), lista cada nota/dato con
  un botón 🗑 que dispare note_del/fact_del con su índice.
  Alternativa mínima: quitar el código muerto.

A10. Navegación inconsistente entre superficies

  - mx:b (callbacks.py:312-315) manda el menú raíz como
  mensaje nuevo en vez de edit_text, acumulando paneles
  flotantes.
  - "🔙 Volver a turnos" (keyboards.py:398) va a tp:0,
  perdiendo la página actual.
  - /turnos y /resumen legacy (admin.py:674, 856) abren
  teclados sin botón "volver al menú".
  - Corrección: unificar el back a editar el mismo mensaje, y
  que el paginador recuerde la página.

  A11. Copy: ortografía inconsistente y botón largo

  - keyboards.py:1007 "🔄 Reiniciar conversacion de prueba" →
  37 chars (recomendado ≤25) y sin acentos. También menu.py
  usa "accion", "duracion", "operacion", "invalido" sin tilde,
   mientras keyboards.py/persona_admin.py sí acentúan →
  inconsistente.
  - callbacks.py:47 typo "marar falsa alarma" (debe ser
  "marcar").

  A12. Handler /start duplicado (código muerto)

  admin.py:563-567 responde ADMIN_MENU_TEXT, pero el router de
   menu.py:426-433 se registra antes en setup.py:211 y gana el
   match → el ADMIN_MENU_TEXT legacy jamás se muestra.
  Elimínalo (o unifica y actualiza las pruebas).

  A13. Botones m:vip de mensajes viejos no redirigen

  Tocar el perfil de un VIP ya desactivado (menu.py:623-635)
  muestra "Perfil de {id}" con acciones que luego fallan una a
   una. Mejor: detectar vip is None y redirigir a la lista con
   un aviso.
   
   
   
   
● A1 y A2 quedaron implementados y verificados. Resumen:

  Qué cambió

  A1 — Nota desde borrador con TTL y /cancelar
  - callbacks.py: el callback an:<chat_id> ya no guarda en un
  dict plano permanente (sessions_note) sino que abre una
  sesión "note" en el MenuSessionStore compartido (TTL 15 min
  + /cancelar). El prompt ahora dice "Usa /cancelar para
  abortar" y la confirmación edita el mensaje-prompt (no el
  borrador).
  - setup.py: el store se comparte entre el router de menú y
  el de callbacks; se eliminó sessions_note.
  - admin.py: se quitó el parámetro note_sessions, el local
  sessions_note y el bloque muerto en on_owner_text (el texto
  de nota ahora lo captura el router de menú vía
  HasActiveMenuSession).

  A2 — Los wizards sobreviven input inválido
  - menu.py: HasActiveMenuSession ya no traga comandos
  (/list_vips durante un rename va a su handler; un forward
  con contenido / sí sigue entrando al wizard). Esto también
  evita que un comando se convierta en nota (requisito de
  seguridad de A1).
  - Los handlers _handle_sandbox_forward,
  _handle_register_forward, _handle_note_text,
  _handle_fact_text, _handle_rename_text re-arrancan la sesión
   ante errores de validación (forward no identificable, VIP
  ya activo, texto vacío, formato incorrecto), así el
  "reenvía/intenta de nuevo" del mensaje es real. En
  sandbox_profile, texto en vez de botón mantiene el wizard
  vivo.

  Copy: corregí un voseo que se coló ("Reenviá" → "Reenvía") y
   añadí hints de /cancelar a los mensajes de error.

  Verificación

  - 2488 unit + 43 e2e tier1 + 121 tier2 + 23 tier3 → todo
  verde.
  - Tests nuevos: an: inicia sesión note TTL y apunta al
  prompt; nota vacía / forward inválido mantienen el wizard
  vivo; HasActiveMenuSession excluye comandos pero acepta
  forwards.
  
  Notas

  - Ruff deja 3 hallazgos pre-existentes en HEAD (no
  introducidos por mí): E402 en admin.py y dos F401
  (format_vips_list en menu.py, build_doctrine_router en
  setup.py). Los dejé para no ensuciar este paquete.
  - La expiración silenciosa de sesiones vencidas (>15 min)
  sigue ahí — es el hallazgo A6, que estaba fuera de este
  paquete.

  ¿Siguiente paquete? Sugiero A3 + A8 (respuesta temprana de
  answerCallbackQuery en aprobar/corregir/escalar y export de
  métricas como documento), que es el que más impacta el
  feedback de botones.


● A3 y A8 quedaron implementados y verificados. Resumen:

  Qué cambió

  A3 — answerCallbackQuery llega antes del trabajo pesado
  - callbacks.py: el bloque de callbacks estándar (approve/correct/
   escalate) responde query.answer() vacío apenas llega el callback,
   ANTES de dispatch_owner_callback (que hace delivery al VIP +
   escrituras DB). El botón ya no queda girando durante la entrega.
  - Se eliminaron los re-answers redundantes de approved/escalated/
   awaiting_correct/nav_ok: el edit del mensaje (✅ Enviado / ⚠️
   Escalado) es el feedback principal y el answer vacío inicial basta.
   Los casos de alerta (forbidden, no-op stale, deliver_failed,
   blocked_*) siguen re-respondiendo con query.answer(text,
   show_alert=True) en la ventana de ~30s (patrón toast tardío).

  A8 — Export de métricas como documento (sin cap de 4096)
  - callbacks.py: el export mx:e responde el callback antes del trabajo
   y envía el JSON completo con BufferedInputFile + answer_document
   (metricas_semanales.json), igual que el export de traza. Ya no manda
   texto plano.
  - admin_metrics_service.py: export_week_json devuelve el JSON completo
   sin truncar; la truncación a 4096 era un workaround del cap de
   mensajes que dejó de aplicar al exportar como documento.

  Verificación

  - 2490 unit → todo verde.
  - Tests nuevos:
   test_approve_answers_before_delivery (spinner limpiado exactamente
   una vez, antes del delivery, sin re-answer);
   test_metrics_export_ships_full_json_document (answer temprano +
   documento BufferedInputFile con JSON completo);
   test_export_full_json_over_telegram_cap (payload >4096 sin truncar).

  Notas

  - F401 pre-existente de MetricsSummary en test_admin_metrics_service.py
   (no introducido aquí); se dejó igual que los otros hallazgos de HEAD.
  - El resto del paquete (A4–A13) queda para un siguiente turno.

  ¿Siguiente paquete? Sugiero A4 + A7 (descartar en staging/memoria con
  confirmación en dos pasos, y confirmaciones de delete/register con
  expiración), que reutiliza el patrón de re-answer con show_alert
  implementado en A3.


● A4 y A7 quedaron implementados y verificados. Resumen:

  Qué cambió

  A4 — Descartar con confirmación (ya no borra de un toque)
  - staging: el primer toque a "🗑 Descartar" (sd:<id>) ya NO borra; solo
   arma el paso de confirmación (edit_reply_markup al keyboard
   staging_discard_confirm_keyboard). "✅ Sí, descartar" (sd:<id>:confirm)
   ejecuta staging.discard; "❌ No, mantener" (sd:<id>:cancel) restaura el
   keyboard original del candidato. Nuevos encoders/parser en keyboards.py
   (sd:<uuid>:confirm / sd:<uuid>:cancel, ≤64 bytes). dispatch_staging
   devuelve discard_confirm_prompt / discarded / discard_cancelled.
  - memoria: el toast de descarte ahora usa show_alert=True (Descartado 🗑
   como alerta), el mínimo que pedía el hallazgo. Upgrade opcional a dos
   pasos queda para un follow-up si se quiere consistencia total con staging.

  A7 — Confirmaciones delete/register con expiración
  - MenuSessionStore: nuevo mecanismo de confirmación con TTL (15 min),
   separado de _sessions para no capturar texto vía HasActiveMenuSession:
   record_confirmation / confirmation_live / consume_confirmation.
  - menu.py: al mostrar el keyboard de confirmación de delete y de register
   se registra el instante; delete_confirm y register:confirm validan con
   consume_confirmation antes de ejecutar. Si expiró, se muestra
   "Esta confirmación expiró, vuelve a intentarlo." + back al menú de VIPs,
   y _dispatch_action devuelve "confirm_expired" para que on_menu_callback
   re-responda con query.answer(text, show_alert=True) (patrón A3). Así un
   Confirm viejo ya no registra un VIP sin nombre ni desactiva un VIP con
   contexto obsoleto.

  Verificación

  - 2500 unit + 43 e2e tier1 → todo verde.
  - Tests nuevos:
   test_owner_discard_arms_confirm_prompt / discard_confirm_deletes /
   discard_cancel_keeps_candidate (staging 2 pasos);
   test_discard_toast_uses_show_alert (memoria alerta);
   test_register_confirm_expired_is_rejected / test_delete_confirm_
   expired_is_rejected;
   test_confirmation_live_until_consumed / test_confirmation_expires_by_ttl /
   test_confirmation_is_not_tied_to_active_menu_session;
   roundtrips de sd:...:confirm/cancel y del keyboard en test_staging_keyboards.

  Notas

  - Los 7 hallazgos de ruff sobre menu.py/test_menu.py/test_staging_keyboards
   son pre-existentes en HEAD (verificado con git stash) — se dejaron igual.
  - Queda A5 (dead-ends con keyboard=None), A6 (expiración silenciosa de
   sesiones), A9–A13 para siguientes turnos.

  ¿Siguiente paquete? Sugiero A5 + A6 (errores con botón de salida y aviso
  de sesión vencida) — los dos problemas de "el usuario se queda sin
  siguiente acción".


● A5 y A6 quedaron implementados y verificados. Resumen:

  Qué cambió

  A5 — Ningún error deja sin botón de salida
  - menu.py: los dead-ends que pasaban keyboard=None ahora muestran
   menu_back_keyboard con el destino correspondiente:
   - errores del bloque VIP (profile/notas/datos): back al detalle del VIP;
   - register "ID de usuario inválido"/"Acción no disponible": back a VIPs;
   - sandbox "El modo de prueba no esta disponible": back a root;
   - sandbox "No hay modo de prueba activo" (off/reset) y "No se encontro
     el chat": back a sandbox.
  - Los prompts de wizard que piden texto (nota/dato/nombre/reenvío) siguen
   sin teclado a propósito: su salida explícita es "Usa /cancelar para
   abortar." (no son dead-ends).

  A6 — Sesión multi-paso vencida ya no traga la entrada
  - MenuSessionStore.status(owner_id) → none | live | expired (consulta pura,
   sin pop). start() ahora estampa created_at con el clock del store (inyectado
   en tests) para que el TTL sea determinista.
  - HasActiveMenuSession ahora matchea sesiones live O vencidas: un texto que
   llega después del TTL entra al wizard en vez de caer al router general.
  - on_menu_session_text: si status() == "expired", limpia la sesión y
   responde "Tu operación expiró, vuelve a intentarlo." — el texto de la
   dueña ya no se pierde en silencio.

  Verificación

  - 2506 unit + 43 e2e tier1 → todo verde.
  - Tests nuevos:
   test_profile_unavailable_has_back_keyboard / test_register_invalid_id_
   has_back_keyboard / test_sandbox_off_no_active_has_back_keyboard (A5);
   test_session_status_none_live_expired / test_has_active_menu_session_
   matches_expired_for_warning / test_menu_session_text_expired_warns_and_
   clears (A6).

  Notas

  - Los 6 hallazgos de ruff sobre menu.py/test_menu.py siguen siendo los
   pre-existentes de HEAD (format_vips_list y los imports muertos del test).
  - Queda A9–A13 para siguientes turnos (A9 borrar notas/datos desde el menú,
   A10 navegación inconsistente, A11 copy, A12 /start duplicado, A13 m:vip
   obsoletos).

  ¿Siguiente paquete? Sugiero A10 + A12 (navegación consistente y handler
  /start duplicado) — los dos de "superficies que dicen cosas distintas".


● A10 y A12 quedaron implementados y verificados. Resumen:

  Qué cambió

  A10 — Navegación consistente entre superficies
  - callbacks.py: el back de métricas (mx:b) ahora edita el mismo panel al
   menú raíz (MENU_ROOT_TEXT + menu_root_keyboard) con fallback a mensaje
   nuevo; ya no acumula paneles flotantes.
  - keyboards.py: "🔙 Volver a turnos" ya no resetea a tp:0. La página actual
   viaja en el callback del turno (encode_trace_view(turn_id, page=N) →
   vt:<id>:N) y parse_trace_callback la extrae; trace_detail_keyboard usa
   encode_trace_page(page) para restaurar la página exacta.
  - keyboards.py: trace_list_keyboard ahora incluye una fila "🔙 Volver al
   menú" (m:root) — el /turnos legacy ya no deja a la dueña sin salida.
  - admin.py: /resumen con resumen vacío (status != ok) muestra un back al
   menú en vez de keyboard=None.

  A12 — Handler /start duplicado eliminado
  - admin.py: se eliminó el @router.message(Command("start", "menu")) que
   respondía ADMIN_MENU_TEXT — era código muerto (el router de menu.py se
   registra antes y gana el match). ADMIN_MENU_TEXT sigue exportado desde
   callbacks.py (documentación de comandos); se quitó el import sin uso.

  Verificación

  - 2512 unit + 43 e2e tier1 → todo verde.
  - Tests nuevos/actualizados:
   test_back_to_menu_row_present / test_turn_buttons_carry_current_page /
   test_back_to_turns_restores_page / test_parse_trace_view_callback_with_page
   (keyboards traza);
   test_metrics_back_edits_message_in_place / test_trace_detail_back_uses_
   parsed_page (router callbacks);
   test_basic_structure actualizado (fila Volver al menú).

  Notas

  - Queda A9 (borrar notas/datos desde el menú), A11 (copy inconsistente y
   botón largo), A13 (m:vip obsoletos) para siguientes turnos.
  - Ruff: solo el E402 pre-existente de admin.py (import a mitad de archivo,
   documentado desde HEAD); no se introdujeron hallazgos nuevos.

  ¿Siguiente paquete? Sugiero A11 + A9 (copy consistente/acentuación y el
  borrado de notas/datos desde el menú) — los dos de "la superficie dice algo
  distinto a lo que hay".


● A11 y A9 quedaron implementados y verificados. Resumen:

  Qué cambió

  A11 — Copy consistente (acentuación y botón largo)
  - callbacks.py: typo "marar falsa alarma" → "marcar falsa alarma" en el texto
    de ayuda de comandos (ADMIN_MENU_TEXT).
  - keyboards.py: "🔄 Reiniciar conversacion de prueba" (37 chars) → "🔄
    Reiniciar prueba" (18 chars, bajo el límite de ~25).
  - menu.py: la copy sin tilde ahora acentúa, alineada con keyboards.py /
    persona_admin.py: "accion"→"acción", "duracion"→"duración", "operacion"→
    "operación", "invalido"→"inválido", "esta"→"está", "reenvia"→"reenvía",
    "encontro"→"encontró", "activacion"→"activación", "conversacion"→
    "conversación", "escalo"→"escaló", "Asegurate"→"Asegúrate", "opcion"→
    "opción", "metricas"→"métricas", "mas"→"más".

  A9 — Borrar notas/datos desde el menú (ficha con botones por item)
  - keyboards.py: menu_vip_profile_keyboard acepta facts/notes y añade un botón
    🗑 por item: "🗑 {key}" → fact_del:<key> y "🗑 Nota {i}" → note_del:<i>, con
    el mismo índice que muestra la ficha. Una clave que rebase los 64 bytes de
    callback_data se salta (la ficha la sigue mostrando y el comando legacy
    /vip_fact_del puede borrarla) en vez de reventar el build del teclado.
  - menu.py: el dispatch "profile" pasa result.content (facts/notes) al teclado,
    así los botones aparecen en la ficha real. Los paths transitorios (perfil en
    cola / no disponible) se mantienen sin botones de borrado.

  Verificación

  - Suite runnable en esta shell → verde (2513 unit). Los 5 fallos restantes son
    ambientales y ajenos al paquete: falta asyncpg (test_composition_wiring.py)
    y sentence-transformers (test_embedding.py).
  - Tests nuevos (6):
   test_profile_keyboard_per_item_delete_buttons / no_delete_buttons_without_data
   / skips_overlong_fact_key (teclado de la ficha);
   test_profile_action_shows_delete_buttons_per_item (dispatch profile con
   facts/notes);
   test_note_del_from_ficha_deletes_note / test_fact_del_from_ficha_deletes_fact
   (los botones de la ficha llegan al servicio con índice/clave correctos).
  - test_pause_without_duration_shows_picker actualizado ("duracion"→"duración").

  Notas

  - Los 6 hallazgos de ruff sobre menu.py/test_menu.py son los pre-existentes de
    HEAD (format_vips_list y los imports muertos del test) — no se introdujeron
    nuevos; keyboards.py y callbacks.py quedaron limpios.
  - Queda A13 (m:vip obsoletos no redirigen a la lista) como único pendiente del
    paquete A9-A13.

  ¿Siguiente paquete? A13 (detectar VIP desactivado en m:vip y redirigir a la
  lista con aviso) — cierra el paquete A9-A13.


● A13 quedó implementado y verificado. Resumen:

  Qué cambió

  A13 — Botones m:vip de mensajes viejos redirigen a la lista
  - menu.py: la tarjeta de detalle (action == str(user_id)) ahora comprueba
    vip is None or not vip.is_active. Un VIP desactivado (deactivate solo
    marca is_active=False) ya no renderiza "Perfil de {id}" con acciones que
    fallan una a una; se muestra "El VIP ya no existe o fue desactivado." con
    back a la lista (mismo patrón de las líneas de error ya existentes). Como
    la lista usa list_active(), el redirect no puede entrar en bucle.

  Verificación

  - 2520 unit en entorno completo (2512 + 6 de A11/A9 + 2 de A13); en esta
    shell 2515 runneables → verde + 5 fallos ambientales pre-existentes
    (asyncpg / sentence-transformers).
  - Tests nuevos:
   test_stale_vip_button_redirects_to_list_when_deactivated (m:vip de un VIP
   desactivado → warning + back a m:vips);
   test_active_vip_card_still_shows_actions (regresión: el activo sigue
   mostrando la tarjeta con sus acciones).

  Notas

  - Ruff: siguen solo los 6 hallazgos pre-existentes de HEAD; no se
    introdujeron nuevos.
  - Con esto queda cerrado el paquete completo A9–A13. La ficha tiene borrado
    por item (A9), el copy es consistente (A11) y los m:vip obsoletos ya
    redirigen (A13).

  ¿Siguiente paquete? A4 follow-up opcional: llevar el descarte de memoria a
  dos pasos (hoy solo muestra toast con show_alert) para consistencia total
  con staging. Queda fuera de los hallazgos pendientes.
