# C-PII-01 — Los datos personales del texto no viajan al proveedor y vuelven intactos

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-PII-01
Promesa:       Antes de mandar cualquier texto al proveedor del modelo, los correos, teléfonos,
               tarjetas y enlaces se cambian por marcadores; si el modelo los repite en su respuesta,
               se restauran los valores originales, de modo que ni el VIP ni la traza notan el
               cambio.
Fuente:        docs/ESTADO-PROYECTO.md §Privacidad (masking activo 2026-08-22); docs/SPEC-FASE5.md
               §12.7; docs/ACUERDO-PROVEEDOR-LLM.md.
Disparador:    toda llamada al proveedor del modelo: analista, generador, evaluador, extracción de
               memoria, backfill y síntesis de perfiles.
Efecto:        En la petición que sale del servidor, los datos aparecen como `[correo]`,
               `[telefono]`, `[tarjeta]`, `[usuario]` y `[enlace]`; en el texto entregado al VIP y en
               `pipeline_traces` los valores originales están restaurados. Las tarjetas solo se
               enmascaran cuando pasan la validación de dígito de control, para no romper números que
               no son tarjetas.
Banderas:      `FEATURE_PII_MASKING_ENABLED` (hoy `true`; es la única bandera con default `true` en
               el código) → OFF: el texto viaja tal cual. Es un interruptor de depuración, no una
               capacidad de negocio.
Camino:        COMPLETO en el cableado; CONDICIONADO en el efecto. Hay un solo punto de salida para
               el texto (el proveedor DeepSeek, que enmascara en `llm/deepseek.py:161-185`) y todos
               los llamadores de texto de producción le entregan el mismo objeto `provider`; las dos
               vías que no pasan por el enmascarado no llevan texto del usuario (visión) o no salen
               del servidor (embeddings). Pero la promesa no se cumple al pie de la letra: el patrón
               deja escapar tarjetas en casos reales (punto ciego 1) y la restauración solo reconoce
               el marcador literal (punto ciego 11). Mapa verificado leyendo el código (ronda 2):
               1. Punto de salida único: `composition.py:608-614` construye DeepSeekProvider con
                  `pii_masking=settings.feature_pii_masking_enabled` (`settings.py:58`, default True)
                  → `:619-624` lo envuelve en HotSwapLLMProvider (base + override de
                  `system_config["llm"]`). El mismo `provider` se inyecta en todos los servicios
                  (`composition.py:790, 889, 913, 1105-1110, 1155, 1213, 1455`). HotSwap delega sin
                  tocar el texto (`llm/hot_swap.py:142-152`, `:154-161`).
               2. Enmascarado: `generate` → `deepseek.py:206`; `generate_structured` → `:296`; ambos
                  llaman `_mask_messages` (`:161-185`), que aplica `mask_pii` a cada mensaje cuyo
                  `content` es `str` (`:174-180`) y fusiona los mappings. El payload sale en
                  `:348-360`. Restauración: `_unmask` sobre el contenido de la respuesta en `:218`,
                  `:249` (incluye los 3 intentos del ladder) y `:309`; `unmask_pii`
                  (`pii_masker.py:128-139`) sustituye solo tokens presentes en el mapping de esa
                  llamada, los más largos primero.
               3. Analista: `telegram/handlers/business.py:203` (@router.business_message) →
                  `:281-308` handle_business_message → `:308` orchestrator.handle_vip_message
                  (`application/turn_orchestrator.py:1258`) → `:2013` director.handle_turn
                  (`cognitive/director.py:339`) → `:441` Analyst.analyze
                  (`cognitive/analyst.py:223`) → provider. Mensaje: system + UN user con turno
                  actual + historial (`analyst.py:250-263`).
               4. Generador: `director.py:680` → `Generator.generate` (`cognitive/generator.py:119`)
                  → provider; el redraft de naturalidad es una segunda llamada en `director.py:721`.
                  El prompt (persona + knowledge + texto del VIP) se construye antes del proveedor,
                  así que lo que se enmascara es el payload final.
               5. Evaluador: `director.py:688` (y `:727` en el redraft) → `evaluator.py:127` →
                  provider (structured).
               6. Extracción de memoria post-turno: `turn_orchestrator.py:439` _maybe_post_turn →
                  `:459` → `memory_extraction_service.py:445` → provider (transcripción + hechos
                  previos, `:444-454`).
               7. Backfill: job `main.py:292-300` (solo con bandera de memoria) o botón admin →
                  `memory_backfill_service.py:682` → provider (ventana de transcripción, `:678-690`).
               8. Síntesis de perfiles: job `main.py:404-421` → `jobs/profile_synthesis_job.py:57` →
                  `profile_synthesis_service.py:238` → provider (hechos + correcciones).
               9. Recontacto: job `main.py:286-289` → `application/recontact_personalizer.py:95` →
                  provider (plantilla + contexto del VIP).
              10. Propuesta de zona gris: `turn_orchestrator.py:338` / `admin_service.py:1544` →
                  `gray_zone_proposal_service.py:132` → provider (pregunta + borrador del turno).
              11. Reglas de persona (panel de la dueña): `composition.py:889` →
                  `persona_rule_drafter.py:480` → provider (texto de la dueña + catálogo).
              12. Reanudación de falso positivo y regen doctrinal: `admin_service.py:1434` y `:2545`
                  → director → generador (punto 4). Variantes de borrador: `draft_variants.py:754`
                  → director → generador.
              13. Traza: `director.py:671` guarda `prompt_text = built.prompt_final` (texto
                  ORIGINAL: el enmascarado ocurre después, dentro del proveedor) y `:682`/`:737`
                  guardan `generated_text` (borrador ya restaurado) → `SqlTraceStore.store`
                  (`infrastructure/db/repositories/traces.py:55-60`) → `pipeline_traces.prompt_text`
                  / `generated_text` (`models.py:146-147`). La traza muestra los originales, como pide
                  el contrato (ver el costo en el punto ciego 5).
              14. Rutas que NO pasan por el enmascarado: visión (fotos, video, fotogramas, importador
                  de historial y `scripts/refresh_chat_media.py:105`). `composition.py:488-507`
                  construye GeminiVisionProvider; el payload (`llm/gemini_vision.py:149-188`) lleva
                  SOLO el prompt fijo (`cognitive/image_vision.py:30-41`, `video_vision.py:24-45`) y
                  los bytes; el caption del VIP nunca viaja (AGENTS §4.22). Embeddings:
                  `cognitive/embedding.py:94-121` (sentence-transformers local, sin red). Detector
                  emocional, clasificador fático, mood y H1 son heurísticas locales; ningún job
                  construye un proveedor (`grep` de `DeepSeekProvider(`/`generate` en `src/diana/jobs`
                  sin coincidencias). `FakeLLM` (`composition.py:605`, sin API key) no hace red. No
                  hay otro cliente HTTP saliente en `src/diana` fuera de `llm/deepseek.py` y
                  `llm/gemini_vision.py`.
              15. Bandera: default `True` en `config/settings.py:58`; `.env` real
                  `FEATURE_PII_MASKING_ENABLED=true` (línea 22) y declarada núcleo en
                  `config/banderas_nucleo.py:113-116` (un OFF se avisa al arrancar). Con OFF,
                  `deepseek.py:168-169` devuelve los mensajes intactos y mapping `{}`: el texto viaja
                  tal cual en ambos sentidos. Única excepción: el proveedor que se crea al cambiar de
                  modelo en caliente fija `pii_masking=True` (`hot_swap.py:92`, punto ciego 4).
              16. Cruce con `audit/WIRING_SCAN.md` (regenerado; el archivo no se sobrescribió): la
                  corrida de `audit/tools/wiring_scan.py` da 140 líneas idénticas (diff vacío). El
                  escáner no aporta pistas de esta ficha: el proveedor no está condicionado por
                  bandera en `composition.py` (§3 no lo lista), no existe un log de "masking
                  desactivado" (§4 no lo lista porque no hay tal log) y los `logger.exception` de los
                  servicios de §2 sí son relevantes (punto ciego 3). La ausencia de pista no es
                  evidencia en ningún sentido.
Puntos ciegos: 1. [ALTO] Una tarjeta seguida de otro grupo de dígitos NO se enmascara. El regex
               acepta 13–19 dígitos (`pii_masker.py:32`) y la comprobación de Luhn devuelve el valor
               intacto SIN reintentar una corrida más corta (`:104-115`: el `_sub` sólo valida el
               match completo; `pattern.sub` no vuelve a probar en la misma posición). Ejemplos
               sintéticos sobre la función real, no mediciones: "4111 1111 1111 1111 12/27",
               "4111 1111 1111 1111 123" (tarjeta + CVV) y "4111111111111111 12/27" salen SIN
               enmascarar; "4111 1111 1111 1111 5" también. Es el caso natural de "tarjeta + caducidad
               / CVV" pegado por el VIP o por la dueña → la tarjeta viaja en claro al proveedor.
               2. [ALTO] Separadores no cubiertos. `pii_masker.py:32` sólo admite espacio ASCII y
               guion entre grupos (`[ -]?`): una tarjeta copiada con espacio duro (`\u00a0`), con
               salto de línea o con puntos no coincide y viaja limpia. Verificado con la función real
               (ejemplos): "4111\u00a01111\u00a01111\u00a01111" y "4111\n1111 1111 1111" quedan
               idénticas; "55.1234.5678" tampoco se enmascara. Inconsistencia: el patrón de teléfono
               usa `\s` (`:36-48`), así que un teléfono con NBSP SÍ se enmascara. Los espacios duros
               son habituales al copiar de tablas o páginas.
               3. [ALTO] La PII restaurada se escribe en el registro en los caminos de error.
               `deepseek.py:324-331` registra `content_preview=cleaned[:500]`, y `cleaned` es la
               respuesta YA restaurada → correos/teléfonos/tarjetas vuelven al journald (retención
               ~7 días). Además, varios servicios atrapan el fallo del proveedor con
               `logger.exception` (`memory_extraction_service.py:458-462`, `memory_backfill_service.py:493-499`,
               `jobs/profile_synthesis_job.py:57-63`, `gray_zone_proposal_service.py:143` y `:260`,
               `recontact_personalizer.py:99`): el `ValidationError` de pydantic incluye
               `input_value` con el texto del modelo sin enmascarar. Contraste deliberado:
               `persona_rule_drafter.py:500-505` sólo registra el tipo de error. Requiere prueba E2
               sobre el registro para confirmar cuánto texto queda.
               4. [MEDIO] La bandera OFF no apaga el enmascarado tras cambiar el modelo en caliente.
               `hot_swap.py:83-93` fija `pii_masking=True` al construir el proveedor de reemplazo,
               mientras el base usa la bandera (`composition.py:614`). En cuanto la dueña cambia el
               modelo desde el menú (`telegram/handlers/menu.py:862-864`, `:1693-1714`), el
               enmascarado queda encendido aunque `FEATURE_PII_MASKING_ENABLED=false`: la promesa
               "OFF → el texto viaja tal cual" es falsa en esa ruta (falla del lado seguro, pero
               rompe la matriz de banderas y la prueba de sabotaje).
               5. [MEDIO] PII en reposo en `pipeline_traces`. `director.py:671` guarda el prompt
               original y `:682`/`:737` el borrador restaurado; `traces.py:123-160` los devuelve y
               `scripts/export_llm_prompt.py:104-116` los exporta. Es lo que el contrato pide ("la
               traza no nota el cambio"), pero el dato personal queda en la base (TTL ~30 días,
               purga aparte) y en `comprehension`/`evaluation`, que incluyen `raw_llm_output` ya
               restaurado.
               6. [MEDIO] Degradación silenciosa. El único rastro del enmascarado es
               `deepseek.py:184` `logger.debug` con contadores; no hay contador durable, ni campo en
               `/health`, ni aviso de arranque del estado de la bandera (compárese con el log
               `media_vision_wired`, `composition.py:528-536`). Si el regex deja de coincidir (o
               alguien pone el flag en OFF y no se ve), nada lo detecta. No existe vigilante E4.
               7. [MEDIO] La regla "tarjetas solo con Luhn para no romper números que no son
               tarjetas" se cumple a medias. Bien: 16–19 dígitos que fallan Luhn no se marcan como
               tarjeta. Mal: ciertas corridas de 13 dígitos y todas las de 10–12 que encajan en el
               patrón de teléfono se enmascaran como `[telefono]` (verificado: "1234567890123" →
               `[telefono]`); es seguro para la privacidad, pero el modelo razona sobre un teléfono
               que no existe. Además el patrón de tarjeta se come el separador final: "…10005 fin"
               → "[tarjeta]fin" y el valor del mapping termina en espacio (verificado), lo que
               rompe la frontera de palabra en el prompt y se reinserta al restaurar.
               8. [MEDIO] La restauración choca con la compuerta H1 de PII. `text_quality_heuristics.py:122-127,180`
               puntúa 0.0 cualquier texto con PII, y `callbacks.py:406` + `severity_prefill.py:49-50`
               preseleccionan "major". Un borrador que cumple la regla de pago del generador
               (`generator.py:44-66`: copiar `[tarjeta]` para que se restaure el dato del negocio)
               queda con `draft_score=0.0` (`outcome_log_service.py:319`) y sube la severidad de la
               corrección. Condicionado a que el hecho vivo `metodos_pago` traiga una tarjeta que pase
               Luhn: el catálogo estático de este árbol no tiene ese tema (sólo se listaron los
               `tema`, sin leer hechos); hay que comprobarlo contra la persona viva. Ejemplo, no
               medición.
               9. [BAJO] `_mask_messages` omite sin ruido todo `content` que no sea `str`
               (`deepseek.py:174-182`). Hoy todos los llamadores de texto mandan strings (revisado),
               pero un futuro llamador multimodal por este proveedor quedaría sin enmascarar y sin
               señal; la visión usa un proveedor distinto, así que hoy no aplica.
              10. [BAJO] Colisión de marcadores entre mensajes. `mask_pii` se ejecuta por mensaje con
               su propio `used` y `mapping.update` (`deepseek.py:170-180`): dos mensajes con una
               tarjeta producen `[tarjeta]` en ambos y gana el último al restaurar. Hoy todos los
               llamadores mandan UN solo mensaje de usuario (analista `:261-263`, evaluador
               `:174-176`, generador `:104-105`, extracción `:447-454`, backfill `:684-690`,
               síntesis `:204-205`, recontacto `:84-93`), así que está dormido.
              11. [BAJO] La restauración es sólo literal. `unmask_pii` (`pii_masker.py:135-139`)
               sustituye el token exacto: el modelo que escribe `[CORREO]`, `[correo ]`,
               `[ correo]`, `[teléfono]` o un `[correo-1]` que no existe deja el marcador visible
               para el VIP y para la dueña (verificado con la función real). No hay ninguna
               comprobación del texto saliente: `grep` de los marcadores sólo encuentra la regla del
               generador y la etiqueta de la UI (`draft_variants.py:451`). Dos datos iguales sí se
               restauran bien porque reciben `[correo]` y `[correo-1]` (verificado).
              12. [BAJO] La instrucción de esquema de `generate_structured` se agrega antes de
               enmascarar (`deepseek.py:280-296`), así que un texto del usuario interpolado en un
               mensaje de sistema también se enmascara; no se encontró un llamador que meta texto
               del VIP en un mensaje de sistema.
              13. [INFO] Visión y embeddings no pasan por el enmascarado y es correcto por diseño:
               Gemini recibe prompt fijo + bytes (sin texto del usuario) y los embeddings corren en
               el servidor. Debe quedar en la prueba E2 la aserción de que el payload de visión NO
               contiene texto del chat.
              14. [INFO] `audit/WIRING_SCAN.md` no tiene una sección de PII: el proveedor no está
               condicionado con `x if settings.feature_… else None`, y no hay log de masking apagado.
               El cruce, por tanto, es negativo y no prueba nada por sí solo (regla del escáner).
              15. [INFO] La ficha afirma que `FEATURE_PII_MASKING_ENABLED` "es la única bandera con
               default `true` en el código"; no es exacto: `settings.py:128`
               (`feature_force_profile_when_notes`) y `:167` (`feature_escalation_fp_draft_enabled`)
               también arrancan en `True`. No cambia el resto del análisis, pero la frase debe
               corregirse para no confundir la matriz de banderas.
              16. [INFO] El detalle "las tarjetas solo se enmascaran si pasan Luhn" está probado en
               E1 (`tests/unit/llm/test_pii_masker.py:126-129`) sólo para una corrida de 16 dígitos;
               no cubre tarjeta+caducidad, NBSP, ni que el pipeline real use `build_app`. Las
               pruebas existentes del proveedor se construyen a mano (`test_pii_masker.py:38-53`) y
               no hay ninguna E2/E3 de esta promesa.
Prueba E2:     `tests/audit/test_C_PII_01.py` — 18 casos, 18 passed (7,5 s). `build_app` con el
               `DeepSeekProvider` real y `httpx.MockTransport` como único borde sustituido: se
               captura el cuerpo HTTP que el proveedor armaría de verdad. Postgres real (copia
               `diana_copy.sql`, 2026-10-12). Cubre flujo completo, analista, evaluador, generador,
               extracción de memoria, síntesis de perfiles (job real), tarjetas Visa/Amex/Luhn,
               restauración, bandera OFF, cambio de modelo en caliente, visión y traza.
Sabotaje E3:   Worktree `/tmp/sabotaje-pii01` (detached `7d2a6c4`), revertido; producción intacta.
               S2 bandera OFF forzada en el escenario ON → 9 failed. S4 `mask_pii` identidad →
               10 failed. S4b `unmask_pii` identidad → 2 failed (el borrador llega con marcadores;
               la aserción de traza no se alcanza, pero lee el mismo punto de restauración).
               S5 sin `_mask_messages` → 10 failed. Ningún sabotaje sobrevivió.
Vigilante E4:  Propuesto (no implementado): conteo diario de llamadas enmascaradas vs. no
               enmascaradas y muestreo de cuerpos salientes en busca de patrones de tarjeta/correo;
               alerta si aparece un dato sin marcador o si el enmascarado deja de correr.
Nivel:         E3 en el enmascarado y en la restauración del borrador; la traza queda cubierta de
               forma indirecta (mismo punto de restauración).
Semáforo:      🔴 — la promesa "los correos, teléfonos, tarjetas y enlaces se cambian" falla en
               formatos reales: tarjeta seguida de caducidad/CVV y separadores de punto, espacio
               duro o salto de línea viajan en claro.
Hallazgos:     1. ALTO — tarjeta seguida de otro grupo de dígitos (`… 12/27`, `… 123`) no se
                  enmascara: el fallo de Luhn descarta el match completo sin reintentar
                  (`pii_masker.py:32`, `:104-115`).
               2. ALTO — separadores no cubiertos: el patrón solo admite `[ -]?`; espacio duro,
                  salto de línea y puntos dejan tarjeta/teléfono sin enmascarar.
               3. ALTO — PII restaurada en registros de error: `deepseek.py:324-331` loguea
                  `content_preview` desenmascarado; varios `logger.exception` pueden incluir
                  `input_value` de pydantic.
               4. MEDIO — el cambio de modelo en caliente fija `pii_masking=True`
                  (`hot_swap.py:92`): apagar el interruptor no resiste un cambio de modelo.
               5. MEDIO — PII en reposo: `pipeline_traces.prompt_text/generated_text` y
                  `raw_llm_output` guardan los originales (decisión de diseño del contrato).
               6. MEDIO — degradación silenciosa: solo `logger.debug` con contadores; sin contador
                  durable, `/health` ni vigilante.
               7. MEDIO — corridas de 13 dígitos y de 10–12 se enmascaran como `[telefono]`.
               8. BAJO — restauración solo literal: `[CORREO]` o `[correo ]` llegan visibles al VIP.
