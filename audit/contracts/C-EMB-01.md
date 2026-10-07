# C-EMB-01 — Todo lo que Diana "recuerda" tiene una huella semántica real y se usa para buscar

ID:            C-EMB-01
Promesa:       Ejemplos dorados, correcciones, políticas, memorias y perfiles se guardan con su embedding real (vector de 384) para que la recuperación por similitud los encuentre.
Fuente:        wiki/concepts/pipeline-cognitivo.md, memoria-vip.md, calidad-feedback.md; scripts/backfill_feedback_embeddings.py (incidente 2026-08)
Disparador:    guardar ejemplo/corrección (Destacar/Reprender, staging), crear política, extraer memoria post-turno, sintetizar perfil, arranque (warmup).
Efecto:        Filas en examples / policies / memories / profiles con embedding NO nulo y NO todo ceros; y retrievers que devuelven resultados ordenados por similitud.
Banderas:      feature_memory_enabled (memorias), feature_quality_feedback_enabled, feature_profile_synthesis_enabled.
Camino (estático, SIN ejecutar):
  - EmbeddingService se crea en composition.py:569 y se inyecta en repos/servicios (:573, :603, :623, :1092, :1107, :1302, :1377).
  - Carga diferida del modelo (cognitive/embedding.py); warmup en job de arranque (jobs/embedding_warmup.py, main.py:177).
Puntos ciegos (EVIDENCIA EN CÓDIGO):
  - infrastructure/db/repositories/examples.py:74 → `embedding=embedding or [0.0] * 384`: si no llega vector, guarda ceros SIN error. La columna es NOT NULL, así que "sin embedding" se disfraza de dato válido.
  - infrastructure/db/repositories/profiles.py:29,92,95 → `_ZERO_EMBEDDING` si no hay embedder o el texto está vacío.
  - application/policy_embedding.py:28 → `embedder is None → None` y el llamador escribe "marcador cero + WARNING"; existe un servicio de reparación (PolicyEmbeddingRepairService).
  - gray_zone_service.py:181 y staging_service.py:305 → razón "no_embedder"/"embed_failed" solo en log.
  - El propio repo tiene un script de recuperación (backfill_feedback_embeddings.py) por un bug previo: ejemplos y políticas insertados con embedding cero, "invisibles" para la búsqueda.
Prueba E2:     pendiente → insertar por el flujo real (Destacar, Reprender, política, memoria, perfil) y asertar `embedding <> vector de ceros` y que el retriever lo devuelve primero para una consulta parecida.
Sabotaje E3:   pendiente → S1 (embedder=None), S3 (embed lanza), S4 (embed devuelve ceros). Esperado: la prueba falla Y el sistema deja rastro visible.
Vigilante E4:  propuesto → diario: `SELECT count(*) FROM <tabla> WHERE embedding = <ceros>` por tabla (examples, policies, memories, profiles); > 0 ⇒ alerta. Y: modelo de embeddings `is_loaded` en /health.
Nivel:         E3 SOLO en el tramo `profiles` (E2 + sabotaje S1/S2 ejecutados el 2026-10-07).
               El resto del contrato (examples / policies / memories por sus flujos reales)
               conserva su nivel previo: NO se re-verificó.
Semáforo:      🟡 global. Tramo `profiles` cerrado y verde: camino muerto eliminado
               (find_by_similarity sin llamador, borrada), documentación corregida en 12 lugares,
               prueba E2 en verde y dos sabotajes que la hacen fallar. Sigue 🟡 porque las otras
               4 tablas no se re-midieron en esta ronda y el trámite de las 2 huellas en ceros
               queda pendiente de que la dueña lo corra.
Desplegado:    SÍ — integrado a `main` y publicado en `origin/main` (`5a4a26a`) el 2026-10-07;
               bot reiniciado a las 23:49:33 UTC, servicio activo, 0 reinicios, /health ok.
Hallazgos:     H2 cerrado: el cero en profiles era histórico (28/29-jul) e inocuo. Aplicado:
               (1) find_by_similarity borrada; (2) 12 documentos corregidos; (3) script
               scripts/regenerate_profile_embeddings.py (simulación por defecto, respaldo, --apply,
               idempotente) — NO ejecutado contra producción; (4) `_embed_content` ahora registra
               `profile_embedding_zeros` con motivo (no_embedder / embedder_returned_zeros /
               empty_text) en vez de guardar ceros en silencio.
               Pendiente aparte: ContextsRepo.find_by_similarity tiene el mismo estado de huérfana.
               Ver audit/FASE2-PERFILES.md
