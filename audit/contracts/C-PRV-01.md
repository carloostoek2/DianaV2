# C-PRV-01 — Una foto con documento o dato fuerte no sale del servidor

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-PRV-01
Promesa:       Antes de mandar una foto a un servicio externo para que la describa, Diana la lee en
               el propio servidor: si trae un documento de identidad no sale nunca (ni tapada); si
               trae tarjeta, cuenta o clave, se tapan las líneas exactas y se comprueba que ya no se
               lean; solo entonces la imagen viaja. Si no se puede verificar, no sale.
Fuente:        AGENTS.md §3 flujo 4.22; REQ-PRIV; docs/ESTADO-PROYECTO.md §Privacidad.
Disparador:    mensaje de negocio de un VIP con foto, con `FEATURE_IMAGE_VISION_ENABLED` encendida.
               El texto que acompaña la foto no participa en esta decisión.
Efecto:        El texto del turno queda como `[imagen: <descripción>]` cuando la imagen viaja limpia;
               `[imagen] ⚠️ contiene información sensible (no analizada)` cuando aparece un documento
               o cuando un dato fuerte sigue legible después de taparlo; y `[imagen]` plano cuando la
               bandera está apagada o el análisis falla. La imagen no se guarda en la base ni en
               disco (solo pasa por memoria durante el análisis). El identificador de la foto viaja
               al mensaje de aprobación para que la dueña vea la imagen.
Banderas:      `FEATURE_IMAGE_VISION_ENABLED` (hoy `true`) → OFF: sin descarga, sin análisis y sin
               foto en el DM; queda la etiqueta de media. El enmascarado vive bajo la misma bandera:
               no hay una segunda puerta para encenderlo por separado.
Camino:        COMPLETO en el cableado; CONDICIONADO en el efecto (depende de la bandera, de una
               GEMINI_API_KEY no vacía, del binario tesseract y de que el OCR devuelva texto con las
               formas que reconocen las reglas). Cadena verificada leyendo el código (ronda 2):
               1. Entrada: `telegram/handlers/business.py:202` (@router.business_message) → `:212`
                  _build_inbound → `:178` image_on = vision is not None and vision.enabled → `:180`
                  exige media_downloader → `:184` _vision_text_and_media.
               2. Foto: `business.py:125-133` → `:55` file_id de la foto más grande → `:57` descarga
                  en memoria (`business.py:35-42`, BytesIO; nada en disco) → `:58` detect_image_mime
                  (`infrastructure/vision/ocr.py:144-155`) → `:59` ImageVisionService.analyze.
               3. Filtro local: `application/image_vision_service.py:216` → `:218` puerta enabled →
                  `:222` OCR local (`ocr.py:158-196`, pytesseract perezoso) → `:230` scan_sensitive
                  (`:132-166`) → `:231` identidad ⇒ SENSIBLE y fin (no viaja, ni tapada) → `:236`
                  dato fuerte ⇒ `:238` _mask_sensitive (`:293-304`) → `:296` extract_lines
                  (`ocr.py:199-241`) → `:299` scan por línea → `:304` mask_lines
                  (`infrastructure/vision/redact.py:28-56`) → `:243` segundo OCR de verificación →
                  `:249` si sigue habiendo dato fuerte ⇒ SENSIBLE (`mask_verification_failed`) →
                  `:254` downscale (`infrastructure/vision/resize.py`) → `:255`
                  ImageDescriber.describe (`cognitive/image_vision.py:48`) → VisionProvider →
                  `llm/gemini_vision.py:70` → `:82` → `:141` → `:190` POST inline_data (llave en
                  params; los bytes no tocan disco). Rama limpia o sólo factura: `:267-276` viaja tal
                  cual (el importe queda visible).
               4. Texto del turno: `business.py:68` compose_media_text
                  (`application/media_text.py:22-39`): sensible → `⚠️ contiene información sensible
                  (no analizada)`; descripción → `[imagen: <descripción>]`; sin descripción → `[imagen]`;
                  el caption se agrega al final.
               5. Al pipeline: `business.py:190-200` VipInboundMessage (photo_file_id se devuelve
                  incluso en la rama sensible/error, `:67`) → `:222` orchestrator.handle_vip_message →
                  `application/turn_orchestrator.py:1258` → `:1283` historial (texto ya descrito) →
                  `:1996` coalesce (lee historial) → `:2009` IncomingTurn.photo_file_id → Director.
               6. DM de la dueña: `application/admin_service.py:369` photo_file_id a la aprobación →
                  `infrastructure/db/repositories/approvals.py:56` lo persiste → `admin_service.py:405`
                  al aviso → `telegram/notifier.py:59-73` send_photo best-effort.
               7. Camino paralelo con el mismo filtro: `application/vip_history_seed.py:287-289`
                  (media importada al dar de alta un VIP).
               Cableado (`composition.py`): ImageVisionService se construye SIEMPRE (`:501-505`) con
               `enabled=settings.feature_image_vision_enabled` (`:504`) y describer sólo si la llave
               Gemini no está vacía (`:488-500`); media_downloader sólo si (bandera imagen o video) Y
               hay proveedor (`:517-525`); se entrega al importador y al dispatcher en `:1436-1437` y
               `:1578-1580`, y el router lo recibe en `telegram/setup.py:319-324`. Con la bandera OFF
               (o llave vacía): `image_vision.enabled=False` (`image_vision_service.py:209`) y
               media_downloader None ⇒ sin descarga, sin OCR y sin envío; photo_file_id=None y queda la
               etiqueta plana (comportamiento previo). `.env` real: FEATURE_IMAGE_VISION_ENABLED=true con
               GEMINI_API_KEY no vacía ⇒ hoy la rama está armada.
Puntos ciegos: 1. [ALTO] Tarjeta gana a identidad en la clasificación. `image_vision_service.py:142-147`
               devuelve `strong` (tarjeta) ANTES de buscar palabras de identidad (`:151-157`). Una foto
               de documento que además muestre un número en grupos de 4 (o 16 dígitos seguidos) se
               clasifica "tarjeta": se tapa esa línea, la verificación pasa y la imagen del documento
               —con la palabra DNI/PASAPORTE visible— SÍ viaja a Gemini. Contradice "documento de
               identidad no sale nunca, ni tapada". El test unitario sólo cubre identidad contra
               factura (`tests/unit/application/test_image_vision_service.py:163`). Comprobado sobre la
               función pura con texto sintético (ejemplo, no medición): "DNI 30445566 / 4111 1111 1111
               1111" → has_identity=False, strong=True.
               2. [ALTO] OCR vacío o ilegible se trata como limpio. `ocr.py:178,190` devuelve "" y
               `image_vision_service.py:230` escanea ese vacío → sin datos → la imagen viaja. Sólo el
               OCR que LANZA excepción se considera "no verificable" (`:223`). Una foto borrosa o muy
               pequeña de un documento puede producir "" o basura y salir sin revisar. La promesa dice
               "si no se puede verificar, no sale". Comprobado sobre la función pura (ejemplo): "" y
               "ll ll1 0O0 ##" → limpio.
               3. [ALTO/MEDIO] Separadores no cubiertos. `image_vision_service.py:51-53` sólo admite
               espacio o guion entre grupos. Una tarjeta impresa "4111.1111.1111.1111" (o con "/")
               no coincide ni con el patrón agrupado ni con el contiguo → viaja limpia. Sospecha por
               lectura del patrón; requiere imagen real.
               4. [MEDIO] El filtro Luhn no se aplica a 16 dígitos. En el patrón agrupado el separador
               es opcional (`:51`), así que cualquier corrida de exactamente 16 dígitos coincide como
               "tarjeta" antes de llegar a Luhn (`:142-147`). Sólo 13/14/15/17/18/19 dígitos pasan por
               Luhn. Efecto: números de pedido de 16 dígitos se enmascaran (ruido) y el caso E2
               "tarjeta que falla Luhn" saldrá igualmente enmascarado; el comentario de `:54` y el test
               `test_long_digit_run_without_luhn_is_not_card` (17 dígitos) dan a entender otra cosa.
               5. [MEDIO] Excepciones no previstas caen en fail-open SIN la marca de sensible. Sólo
               OcrUnavailableError se convierte en sensible (`:223`, `:245`, `:297`). Cualquier otra
               excepción (p. ej. fallo de PIL al guardar en `mask_lines`, `redact.py:55`) escapa de
               analyze y la atrapa `business.py:60-67`, que devuelve la etiqueta plana
               (`image_vision_failed_fail_open`). La privacidad se mantiene (no se envió nada) pero la
               dueña no ve el aviso de sensible y el fallo no deja contador ni alerta.
               6. [MEDIO] Bandera encendida con GEMINI_API_KEY vacía apaga todo en silencio:
               `composition.py:488-505` deja describer None → `enabled=False`
               (`image_vision_service.py:209`) y `media_downloader=None` (`:517-525`), idéntico a la
               bandera OFF. Sólo hay un log informativo al arrancar (`composition.py:528-536`); ni
               `/health` ni el vigilante de contratos miran visión (sin coincidencias en
               `telegram/health.py` ni en `jobs/`).
               7. [MEDIO] Sin vigilante de privacidad (E4): nadie cuenta resultados sensibles,
               enmascarados ni `image_vision_failed_fail_open`. Un retroceso del filtro no se detecta
               en producción.
               8. [MEDIO] OCR síncrono dentro del handler async: `ocr.py:304-310` son funciones
               normales llamadas directo desde `analyze` (`:222`, `:244`, `:296`) en el bucle de
               eventos, sin timeout. Un tesseract lento o colgado frena todos los chats, y un álbum
               hace un OCR (más una segunda verificación) y una llamada a Gemini por cada foto.
               9. [BAJO] La foto en el DM es best-effort y falla callada: `notifier.py:59-73` atrapa
               Exception y registra `draft_photo_attach_failed`; la dueña ve el borrador sin foto y sin
               aviso.
               10. [BAJO] `describe` devuelve None ante fallo/timeout/vacío del proveedor
               (`cognitive/image_vision.py:56-71`) → `sensitive=False, description=None` → etiqueta
               plana (`media_text.py:33-36`). Es el fail-open declarado, pero en el texto del turno es
               indistinguible de "bandera apagada" o "imagen limpia sin describir".
               11. [BAJO] Guarda de bombas de descompresión: imágenes de más de 16 MP lanzan
               OcrUnavailableError (`ocr.py:182-183,227-228`) y se marcan sensibles sin analizarse.
               Fail-closed, pero deja fuera del caption fotos de alta resolución.
               12. [INFO] Punto ciego del escáner: `audit/WIRING_SCAN.md` §3 no lista image_vision ni
               media_downloader (su regex sólo captura `x = y if settings.feature_… else None`) y §4 no
               lista `image_vision_failed_fail_open` (sólo disabled/no_embedder/skipped/embed_failed/
               missing). La ausencia de pista no es evidencia: este cableado hubo que leerlo a mano. El
               archivo business.py tiene 5 `except Exception` y no entra en la tabla de los 15 primeros.
               13. [INFO] La foto original del VIP llega igual al DM de la dueña cuando el resultado es
               sensible o falla (`business.py:67`): es lo previsto (revisión manual), pero implica que
               el file_id viaja aunque la imagen no se haya analizado.
               14. [INFO] Los logs del camino no contienen texto de conversación: sólo tipo de error
               (`business.py:63-66`, `cognitive/image_vision.py:63-66`). `gemini_vision.py:196-204`
               registra hasta 2000 caracteres del cuerpo de error HTTP del proveedor (no la imagen ni
               el mensaje del VIP).
Prueba E2:     `tests/audit/test_C_PRV_01.py` — 10 casos, 10 passed (17–27 s). Entrada real:
               `build_app` + `dispatcher.feed_update` con un `business_message`; pipeline cognitivo,
               filtro, OCR y enmascarado reales. Postgres real (copia `diana_copy.sql`, 2026-10-12).
               Simulados solo los bordes externos: descarga de Telegram (bytes sintéticos) y Gemini
               (servidor local que captura el payload). Casos: identidad sola, identidad + 16 dígitos,
               OCR vacío, tarjeta agrupada, tarjeta con puntos, 16 dígitos sin Luhn, factura, bandera
               OFF, proveedor caído y persistencia (sin bytes en DB ni en disco).
Sabotaje E3:   Worktree `/tmp/sabotaje-prv01` (detached `7d2a6c4`), revertido; producción intacta.
               S1 `scan_sensitive` siempre limpio → falla identidad (4 failed). S4 `_mask_sensitive`
               devuelve el original → falla tarjeta agrupada (4 failed; se detecta por el segundo OCR
               de verificación, no por comparación de bytes). S5 `analyze` sin filtro → falla
               identidad (4 failed). S2 bandera encendida en el escenario OFF → falla (1 failed;
               variante aislada falla en `downloader_calls == []`). Ningún sabotaje sobrevivió.
Vigilante E4:  Propuesto (no implementado): conteo diario de fotos sensibles, no verificables y
               fallos del camino; alerta si una foto marcada sensible no llega a la aprobación o si
               el conteo cae a cero con tráfico.
Nivel:         E3 en los caminos cubiertos (identidad sola, tarjeta agrupada, bandera OFF). Los
               hallazgos 1–3 siguen abiertos.
Semáforo:      🔴 — "un documento de identidad no sale nunca" no se cumple cuando la foto trae
               además un número de 16 dígitos, y una imagen que el OCR no puede leer (vacío) sale
               idéntica al original.
Hallazgos:     1. ALTO — documento + 16 dígitos: la tarjeta se clasifica antes de buscar identidad
                  (`image_vision_service.py:142-147`); la imagen del documento viaja tapada solo en
                  esa zona y el proveedor lee el resto del documento.
               2. ALTO — OCR vacío/basura tratado como limpio (`image_vision_service.py:230`;
                  `ocr.py:178,190`); solo el OCR que lanza es "no verificable".
               3. ALTO/MEDIO — separadores no cubiertos: el patrón solo admite espacio o guion
                  (`image_vision_service.py:51-53`); `4111.1111.1111.1111` viaja limpia.
               4. MEDIO — cualquier corrida de 16 dígitos se enmascara antes de Luhn.
               5. MEDIO — bandera ON con `GEMINI_API_KEY` vacía apaga la visión en silencio (sin
                  aviso en `/health`): no hay descripción y la foto no llega al DM.
               6. MEDIO — excepciones no previstas (p. ej. PIL) escapan a `business.py:60-67` como
                  etiqueta plana: fail-open sin marca ni contador.
               7. MEDIO — sin vigilante E4; nadie cuenta sensibles, enmascarados ni fallos.
               8. MEDIO — OCR síncrono sin timeout dentro del event loop (`ocr.py:304-310`).
