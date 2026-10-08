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
Prueba E2:     HECHO en los tramos memoria / ejemplo dorado / política → tests/audit/test_C_EMB_01_huellas.py (mensaje VIP → entrega → extracción post-turno; botón Destacar; doctrina de zona gris; Postgres real y motor de huellas real). Tramo `profiles`: tests/audit/test_C_EMB_01.py.
Sabotaje E3:   HECHO (2026-10-08) → S1 (embedder=None), S3 (el motor lanza, con rastro visible) y S4 (devuelve ceros, el disfraz del incidente de agosto): las 3 pruebas fallan en los 3 sabotajes. Evidencia cruda en audit/FASE2-SABOTAJE.md §3.10–3.12.
Vigilante E4:  DESPLEGADO (2026-10-08) → V1 de scripts/vigilantes.py, cron diario (10:17 UTC), solo lectura: huellas NUEVAS en ceros por tabla. La ventana de 2 días es lo que lo hace útil: las 2 históricas de `profiles` ya conocidas no avisan todos los días, pero un cero nuevo sí. Pendiente: `is_loaded` del motor en /health.
               H-SB-1 CERRADO (2026-10-08): `staging_service._embed` ya deja rastro en todos los caminos que
               terminan en ceros — evento `staging_embed_zeros` con motivo `no_embedder` / `empty_text` /
               `embedder_returned_zeros` (audit/FASE2-SABOTAJE.md §4). Tres pruebas unitarias nuevas.
Nivel:         E3 en `memories`, `examples` y `policies` (esta ronda) y en `profiles` (ronda anterior). E4 en la vigilancia diaria de ceros nuevos.
               Sin cubrir: el camino de "Reprender" (contraejemplo) por su propio flujo.
Semáforo:      🟢 global con vigilante diario. Las 4 tablas medidas (memories / examples / policies
               / profiles) tienen prueba E2 en verde y sabotaje que las hace fallar; el tramo
               `profiles` cerró además su camino muerto (find_by_similarity sin llamador, borrada).
               Cerrado también: H-SB-1 (los ceros silenciosos de "Destacar" ahora dejan rastro) y las 2
               huellas históricas de `profiles` (regeneradas el 2026-10-08). Hoy las 5 tablas dan 0 ceros.
Desplegado:    SÍ — integrado a `main` y publicado en `origin/main` (`5a4a26a`) el 2026-10-07;
               bot reiniciado a las 23:49:33 UTC, servicio activo, 0 reinicios, /health ok.
               Ronda E3/E4 (2026-10-08): sabotaje ejecutado sobre una copia descartable (producción
               intacta) y vigilante diario activado por cron de usuario. Ver audit/FASE2-SABOTAJE.md.
Hallazgos:     H-SB-1 (cerrado, 2026-10-08): con el embedder ausente, `staging_service._embed` devolvía
               None en silencio y el ejemplo dorado se guardaba con ceros sin ningún aviso (memoria y
               política sí avisaban). Arreglado ese mismo día, con la autorización de la dueña: la fila se
               sigue guardando (fail-open, sin cambio de comportamiento) y ahora deja el motivo
               (`staging_embed_zeros`: no_embedder / empty_text / embedder_returned_zeros — este último es
               el disfraz de agosto, el motor contesta ceros sin lanzar excepción). Tres pruebas unitarias
               nuevas, verificadas por sabotaje. Las 2 huellas históricas de `profiles` (28/29-jul) se
               regeneraron el mismo día con `regenerate_profile_embeddings.py --apply` (con respaldo):
               hoy las 5 tablas dan 0 ceros.
               H2 cerrado: el cero en profiles era histórico (28/29-jul) e inocuo. Aplicado:
               (1) find_by_similarity borrada; (2) 12 documentos corregidos; (3) script
               scripts/regenerate_profile_embeddings.py (simulación por defecto, respaldo, --apply,
               idempotente) — NO ejecutado contra producción; (4) `_embed_content` ahora registra
               `profile_embedding_zeros` con motivo (no_embedder / embedder_returned_zeros /
               empty_text) en vez de guardar ceros en silencio.
               Pendiente aparte: ContextsRepo.find_by_similarity tiene el mismo estado de huérfana.
               Ver audit/FASE2-PERFILES.md
