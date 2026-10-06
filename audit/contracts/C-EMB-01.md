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
Nivel:         E0 + evidencia estática de riesgo real
Semáforo:      🔴 CONFIRMADO en producción: 2 de 3 perfiles con embedding en ceros (último cambio 22-sep). examples/policies/memories/contexts: 0 ceros (🟢)
Hallazgos:     H2
