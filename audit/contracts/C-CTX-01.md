# C-CTX-01 — El contexto temporal interpretado llega al modelo y se retira al vencer

ID:            C-CTX-01
Promesa:       Tras cada turno terminal se persiste el contexto interpretado del chat con vigencia
               (REQ-MEM-06) y el turno siguiente lo lee; al vencer, deja de usarse.
Fuente:        docs/SPEC-FASE2.md, docs/ARCHITECTURE.md §contexto, wiki/entities/tablas/esquema-conocimiento.md
Disparador:    turno VIP terminal (escritura, `ContextStoreService.record_post_turn`) → turno siguiente
               (lectura, `ContextRetriever.fetch`).
Efecto:        Fila vigente en `contexts` con embedding real y `expires_at`; y el bloque
               `knowledge.context` del prompt del modelo con las cuatro claves H.3 correctas.
Banderas:      feature_context_enabled (lee y escribe); `warmup` del motor de huellas.
Camino (estático, SIN ejecutar):
  - Escritura: turn_orchestrator.py:455 → ContextStoreService.record_post_turn (post-turno, best-effort).
  - Lectura: composition.py:911-917 → ContextRetriever(repo=contexts_repo) → find_active_by_chat.
Puntos ciegos (EVIDENCIA):
  - La foto se escribe al CERRAR el turno (justo después de que Diana respondió) y se leía entera en
    el turno siguiente: `waiting_for_reply_since` e `is_first_message_of_day` —hechos del presente—
    viajaban un turno atrasados. Medido el 2026-10-07 sobre 70 turnos reales: 59 (84 %) en desacuerdo
    con el historial del MISMO prompt, y los 30 casos de "inyectado null" iban todos en la misma
    dirección. `is_first_message_of_day`: 15/70 (21 %).
  - `ContextsRepo.find_by_similarity` (repositories/contexts.py:104): función huérfana, sin llamador
    de producción, y la tabla no tiene índice de vector. NO eliminada (pendiente de decisión).
  - `find_active_by_chat` acepta `vip_id` y no lo usa en la consulta (repositories/contexts.py:84-101).
Prueba E2:     tests/audit/test_C_CTX_01.py (3 escenarios, Postgres real, pipeline completo con
               `build_app` + orquestador; solo se simula el LLM). Escenario 1 = regresión del defecto.
Sabotaje E3:   S1 (almacén desconectado en composition.py:911) → la prueba FALLA;
               S2 (sin filtro de vigencia en find_active_by_chat) → la prueba FALLA. Ambos revertidos.
Vigilante E4:  propuesto → contar turnos cuyo bloque dice `"waiting_for_reply_since": null` (esperado 0
               tras el arreglo). V1 de vigilantes.sql ya cubre los ceros de embedding.
Nivel:         E3 (E2 + dos sabotajes ejecutados el 2026-10-07).
Semáforo:      🟢 El mecanismo se usa en producción (21 fotos, 4 chats, vigencia 24 h) y el bloque
               llega al modelo en 502/536 turnos (94 %). Defecto de contenido medido, arreglado y
               desplegado el 2026-10-07: la derivación en vivo gana sobre la foto para las cuatro
               claves H.3.
Hallazgos:     H-CTX-1 (cerrado): contexto temporal un turno atrasado. H-CTX-2 (abierto): búsqueda por
               parecido huérfana en `contexts` — pendiente de decisión de la dueña. H-CTX-3 (menor):
               parámetro `vip_id` aceptado e ignorado en `find_active_by_chat`.
               Ver audit/FASE2-CONTEXTO.md
