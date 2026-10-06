# C-HIST-01 — El historial de la dueña y de los VIP se captura y se reimporta de verdad

ID:            C-HIST-01
Promesa:       (a) Cada mensaje que la dueña envía por Diana queda en el historial del VIP (pares texto ↔ id de Telegram). (b) El historial previo del VIP se importa desde la cuenta de Telegram de la dueña, lentamente, un VIP por ciclo, para que Diana aprenda su voz y contexto.
Fuente:        wiki/entities/modulos/jobs.md; docs/SPEC-FASE5/6; application/owner_history.py, vip_history_seed.py, history_reimport.py
Disparador:    (a) entrega exitosa de un turno / corrección / recontacto; (b) job de reimport cada history_reimport_interval_sec.
Efecto:        (a) filas en historial con texto y message_id tras cada entrega; (b) historial de VIPs ampliado, cursor de reimport avanzando, cola de backfill de memoria alimentada.
Banderas:      (b) feature_history_reimport_enabled Y configuración de Telethon completa (api_id/hash/sesión) Y vip_history_seed_limit.
Camino (estático, SIN ejecutar):
  (a) orchestrator / admin_service / recontact_service → append_owner_delivery_history → build_owner_history_pairs.
  (b) main.py:285 → HistoryReimportJob → HistoryReimportService (composition.py:1406) ← requiere flag Y history_seed.enabled.
Puntos ciegos (EVIDENCIA EN CÓDIGO):
  - composition.py:228 `vip_history_seed_disabled_missing_telethon_config`: si falta configuración, el import queda apagado solo con un log info; no hay alerta.
  - composition.py:1406-1408: el servicio de reimport solo se crea si bandera Y seed habilitado; cualquiera de los dos faltantes ⇒ no existe, sin error.
  - Sandbox: el historial se omite por diseño (`owner_history_skipped_sandbox`); un chat marcado como sandbox por error dejaría de grabar sin avisar.
  - La sesión de Telethon es del mundo real: no se puede probar E2 completo sin credenciales ni cuenta; requiere fake de Telethon (solo esa frontera).
Prueba E2:     (a) pendiente: entrega real → asertar filas de historial con message_id. (b) pendiente: FakeTelethon con mensajes sembrados → un ciclo del job real → asertar historial + cursor + cola de backfill; segundo ciclo idempotente.
Sabotaje E3:   pendiente → S2 (bandera OFF), S1 (seed=None), quitar la llamada a append_owner_delivery_history.
Vigilante E4:  propuesto → (a) turnos DELIVERED sin fila de historial en 24h; (b) VIPs sin importar / cursor sin avanzar en > N intervalos con la bandera ON.
Nivel:         E0
Semáforo:      (a) captura de historial: 🟡 viva en producción (0 mensajes sin id). (b) recarga de historial: 🔴 apagada (bandera false, cursor congelado 6-sep) aunque el .env decía 'VIVO desde 2026-09-02'
Hallazgos:     H3
