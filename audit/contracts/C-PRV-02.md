# C-PRV-02 — Un video se revisa fotograma a fotograma antes de salir

> Ficha sin rastrear. Nivel de evidencia hoy y prioridad: `audit/MAPA-CONTRATOS.md`.

ID:            C-PRV-02
Promesa:       Antes de mandar un video a un servicio externo para que lo describa, Diana extrae un
               fotograma por segundo y los revisa en el propio servidor: si en cualquiera aparece un
               documento de identidad o un dato fuerte (tarjeta, cuenta, clave), el video **no sale**
               —un video no se puede tapar—; si todo está limpio, se describe. Cuando el video pesa
               demasiado para un solo envío, salen únicamente los cuadros ya revisados.
Fuente:        AGENTS.md §3 flujo 4.24.
Disparador:    mensaje de negocio con video o video-nota, con `FEATURE_VIDEO_VISION_ENABLED`
               encendida. El texto que acompaña el video no participa en esta decisión.
Efecto:        El texto del turno queda como `[video: <descripción>]` cuando sale; `[video] ⚠️
               contiene información sensible (no analizada)` cuando algún fotograma trae documento o
               dato fuerte; y `[video]` plano cuando la bandera está apagada, el archivo supera el
               tope de descarga o el análisis falla. El video y los fotogramas no se guardan en la
               base ni en disco.
Banderas:      `FEATURE_VIDEO_VISION_ENABLED` (hoy `true`) → OFF: sin descarga, sin fotogramas y sin
               análisis; queda la etiqueta `[video]`.
               Topes asociados: `VIDEO_VISION_MAX_FRAMES`, `VIDEO_VISION_SEND_MAX_BYTES`,
               `VIDEO_VISION_FRAMES_SENT`. El enmascarado **no** existe para video: cualquier dato
               fuerte deja el archivo fuera del servidor.
Camino:        Rastreado sobre `main` (7d2a6c4), SOLO LECTURA y sin ejecutar contra Telegram ni
               Gemini reales. **Veredicto: CONDICIONADO.** El cableado llega de punta a punta
               (disparador → descarga → revisión local → decisión → texto del turno), pero la promesa
               "un fotograma por segundo" solo se cumple en videos de hasta 30 s, y la rama "video
               grande ⇒ salen los cuadros ya revisados" no es alcanzable con la configuración real
               (puntos 3 y 4 de Puntos ciegos). Al momento del rastreo no había evidencia E2/E3:
               todas las pruebas de video eran E1 con extractor, OCR y describer simulados. La
               prueba E2 y el sabotaje E3 posteriores están en los campos de cierre de esta ficha
               (14 casos, 5 sabotajes, 2026-10-24).

               DISPARADOR REAL
               - Router de negocio: src/diana/telegram/handlers/business.py:202
                 (`@router.business_message`) → callback :203; edición :239.
               - `_build_inbound` :167; banderas efectivas :178-179 (`image_on`, `video_on =
                 service.enabled`); puerta :180 (sin downloader o con la visión apagada NO se
                 descarga ni se analiza; se usa `inbound_text` :176); llamada a visión :184-189.
               - `_vision_text_and_media` :105; rama de video :134-143; etiqueta base y caption
                 :119-124 (`media_tag` en src/diana/telegram/media_tags.py:41-51; `video_note` →
                 "video" :29; marca de álbum :48-50).

               DESCARGA Y GUARDA DE TAMAÑO
               - `_video_text` business.py:71; elige `video` o `video_note` :81; guarda de 20 MiB
                 sobre el tamaño DECLARADO :84-90 (`_MAX_VIDEO_BYTES` = 20*1024*1024, :31) ⇒ log
                 info `video_vision_skipped_too_large` :86 y etiqueta plana :90.
               - Descarga en memoria: `download_media_bytes` business.py:35-42 (`bot.get_file` :37,
                 `download_file` :41); se inyecta como `functools.partial` en composition.py:517-525.
               - `analyze` business.py:94; mime del video o `video/mp4` por defecto :93.

               REVISIÓN LOCAL
               - `VideoVisionService.analyze` src/diana/application/video_vision_service.py:93;
                 apagado :95-96; revisión fuera del hilo del bot :100
                 (`asyncio.to_thread` → `_review_frames` :134).
               - Extracción: video_vision_service.py:144 → src/diana/infrastructure/vision/
                 video_frames.py:74; copia a directorio temporal :78-80; duración por ffprobe
                 :81,186-206; UNA pasada de ffmpeg :82,96-138 (fps = 30/duración :151-162,
                 `-frames:v` :119-120); respaldo cuadro a cuadro :83-87,140-149; sin cuadros ⇒
                 `FrameExtractionError` :88-93.
               - OCR por fotograma: video_vision_service.py:166-168 → ocr.py:304-306 →
                 `extract_text_with_pytesseract` ocr.py:158-196 (spa+eng con fallback eng
                 :177-190; cualquier fallo se envuelve en `OcrUnavailableError` :191-196).
               - Política de sensibilidad: es la MISMA función de fotos, importada en
                 video_vision_service.py:32 (`scan_sensitive` de
                 src/diana/application/image_vision_service.py:132-166); NO está duplicada. Se
                 aplica en :176; identidad ⇒ sensible "identidad" :177-183; dato fuerte
                 (tarjeta/clave/cuenta, `_STRONG_GROUPS` :96) ⇒ sensible :184-190; factura/recibo
                 solo (`scan.receipt`) NO bloquea, igual que en fotos.
               - Fail-closed: sin cuadros, ffmpeg ausente o OCR no disponible ⇒ `sensitive=True`
                 con `reason="no_verificable"` :145-175. Frames limpios ⇒ devuelve la tupla
                 revisada :191.

               SALIDA AL PROVEEDOR
               - Si `len(video_bytes) > send_max_bytes`: `_describe_by_frames` :105-106,118-132;
                 elige hasta `frames_to_send` cuadros con `_spread` :194-199 y los reduce con
                 `_prepare_frame` :202-204; NUNCA manda el archivo completo.
               - Si no: describe el video completo :108-110.
               - Cognitive: src/diana/cognitive/video_vision.py:57 (`describe`) y :71
                 (`describe_frames`); fail-open (None) :89-102.
               - I/O: src/diana/llm/gemini_vision.py:90-109 (`describe_video`), :111-129
                 (`describe_images`), inline_data base64 :165-174, error HTTP se levanta :196-204,
                 plazo de video 45 s (`settings.py:85`).

               EFECTO EN EL TURNO
               - `compose_media_text` src/diana/application/media_text.py:22-39: descripción ⇒
                 `[video: …]`; sensible ⇒ `[video] ⚠️ contiene información sensible (no
                 analizada)` (:19,:31-32); sin descripción ⇒ `[video]` (:35-36); el caption se
                 agrega al final (:37-38) y nunca participa en la decisión.
               - El texto entra al turno por `VipInboundMessage` (business.py:190-200) →
                 `handle_vip_message` :222. `photo_file_id` queda None para video (:143): el video
                 no se adjunta al DM de la dueña.
               - Solo el texto entra al pipeline; no se escribe el video ni los cuadros en la base.
                 (Sí hay copia temporal en disco: punto 5 de Puntos ciegos.)

               INYECCIÓN Y BANDERAS (composition.py / setup.py)
               - Valores reales del `.env` local (sin secretos): `.env:29`
                 FEATURE_IMAGE_VISION_ENABLED=true; `.env:38` FEATURE_VIDEO_VISION_ENABLED=true;
                 `.env:42` VIDEO_VISION_MAX_FRAMES=30; `.env:47`
                 VIDEO_VISION_SEND_MAX_BYTES=20971520; `.env:48` VIDEO_VISION_FRAMES_SENT=20;
                 `GEMINI_API_KEY` presente y no vacía.
               - `settings.py:67` flag; :71 max_frames=30 (ge=1,le=120); :74 send_max_bytes=20 MiB;
                 :76 frames_sent=20 (ge=1,le=60); :82 y :85 plazos. Los valores del `.env` coinciden
                 con esos defaults.
               - composition.py:487 `OcrEngine`; :488-497 `GeminiVisionProvider` SOLO si la key no
                 está vacía; :506-508 `VideoDescriber` (None sin key); :509-516 `VideoVisionService`
                 SIEMPRE construido con `enabled=settings.feature_video_vision_enabled` y los tres
                 topes; :517-525 `media_downloader` real solo si (flag imagen O flag video) Y hay
                 proveedor; :528-536 log info de arranque `media_vision_wired` (con
                 `captioner: true/false`).
               - Al router: src/diana/telegram/setup.py:319-327. Segundo consumidor (importación de
                 historial): composition.py:1437 + vip_history_seed.py:292-294. Tercero (script
                 manual): scripts/refresh_chat_media.py:117-124.
               - Bandera OFF: `_enabled=False` (video_vision_service.py:84,95-96) ⇒ `video_on=False`
                 ⇒ no hay descarga, ni cuadros, ni análisis; queda `[video]` plano con caption
                 (business.py:178-189 → media_tags.py:54-69). Aunque el downloader siga cableado
                 por la bandera de fotos, el video no entra a esa rama (prueba E1:
                 tests/unit/telegram/test_business_vision.py:352-362).
               - Bandera ON con `GEMINI_API_KEY` vacía: describer y downloader quedan None ⇒ mismo
                 comportamiento que OFF; el único rastro es el log info de arranque
                 (composition.py:528-536). La bandera es núcleo y está catalogada en
                 src/diana/config/banderas_nucleo.py:109-112 (sin apagado declarado; si se apaga,
                 el aviso de arranque la reporta).

               CRUCE CON `audit/WIRING_SCAN.md` (regenerado; mi corrida reproduce el archivo byte a
               byte): la sección 1 no lista funciones de video huérfanas (todas tienen llamador); la
               sección 4 solo aporta `telegram/handlers/business.py:86`
               `video_vision_skipped_too_large` (info); la sección 3 NO menciona
               `media_downloader`/`video_vision` porque su patrón no ve el condicional multilínea
               (wiring_scan.py:51-56). El escáner no aporta ninguna señal sobre este contrato.
Puntos ciegos: (ordenados por riesgo; EVIDENCIA EN CÓDIGO, sin ejecución real)
               1. ALTO — La promesa "un fotograma por segundo" solo vale para videos de ≤30 s. Para
                  uno más largo el muestreo baja (fps = 30/duración): 60 s ⇒ 1 cuadro cada 2 s;
                  5 min ⇒ cada 10 s; 10 min ⇒ cada 20 s. Un dato fuerte visible entre dos muestras
                  pasa como limpio y el video SALE a Google. Evidencia: video_frames.py:151-162 y
                  :27-30; settings.py:71; .env:42. Es el hueco principal del contrato; hay prueba
                  de la cobertura, no de la detección (tests/unit/infrastructure/
                  test_video_frames.py:39-44,107-119).
               2. ALTO — La detección depende de que el OCR lea el dato. Una tarjeta borrosa,
                  pequeña, inclinada, en un idioma sin paquete (solo spa+eng) o leída a medias
                  devuelve texto vacío/parcial y `scan_sensitive` la clasifica limpia ⇒ el video
                  sale. No hay umbral de confianza ni fail-closed por "OCR poco fiable": el
                  fail-closed solo dispara si el OCR LANZA `OcrUnavailableError`
                  (video_vision_service.py:166-175). Política: image_vision_service.py:132-166;
                  OCR: ocr.py:177-196.
               3. MEDIO — La rama "video grande ⇒ salen los cuadros ya revisados" es inalcanzable
                  con la configuración real: la guarda de descarga corta en 20 MiB sobre el tamaño
                  declarado (business.py:31,84-90) y `VIDEO_VISION_SEND_MAX_BYTES` = 20971520
                  (.env:47; settings.py:74). Un archivo descargable nunca cumple
                  `len(video_bytes) > 20 MiB`, así que `analyze` siempre manda el video completo
                  (video_vision_service.py:105-110). Solo se alcanzaría si (a) Telegram no declara
                  `file_size` y el archivo superara el tope —entonces la descarga falla y queda
                  etiqueta plana— o (b) se baja el tope por debajo de 20 MiB. La promesa queda
                  condicionada y sin evidencia.
               4. MEDIO — En la rama de cuadros, un cuadro de ≤1280 px viaja como PNG pero
                  rotulado `image/jpeg`: `_prepare_frame` devuelve el original cuando
                  `downscale_image` no reduce (resize.py:33-42) y `_describe_by_frames` fija
                  `mime_type="image/jpeg"` (video_vision_service.py:124-132,202-204). Los cuadros
                  de un video 720p caen justo en ese caso. Si Gemini rechaza el par, el fallo es
                  fail-open y la descripción se pierde sin ruido (video_vision.py:89-102). Ninguna
                  prueba asierta el par bytes/mime (el spy ignora `mime_type`:
                  tests/unit/application/test_video_vision_service.py:71-76).
               5. MEDIO — La ficha promete "no se guardan … en disco (solo memoria)", pero el
                  video completo se escribe en un directorio temporal y ffmpeg escribe ahí los PNG
                  (video_frames.py:78-80,106-138). Se borra al salir del bloque, pero no se
                  sobrescribe: un kill o una caída deja el video sensible en /tmp. Es inevitable
                  con ffmpeg, pero el contrato debe decir "copia temporal borrada al terminar".
               6. MEDIO — Fail-open genérico: `_video_text` atrapa `Exception` y devuelve `[video]`
                  plano (business.py:95-101). La privacidad se mantiene (nada sale), pero el turno
                  queda idéntico a "bandera apagada" y la dueña no sabe que ese video no fue
                  revisado; no hay contador ni alerta. Una excepción de OCR distinta de
                  `OcrUnavailableError` saldría por aquí (video_vision_service.py:166-175 solo
                  atrapa esa).
               7. MEDIO — Sin key de Gemini el servicio se apaga en silencio: describer y
                  downloader quedan None ⇒ `enabled=False` (composition.py:506-525;
                  video_vision_service.py:84-96). Único rastro: log info de arranque
                  (composition.py:528-536). Mismo patrón de "apagado solo con log".
               8. MEDIO — Latencia sin tope global: si la pasada única falla, el respaldo pide
                  hasta 30 cuadros con subprocess independientes, cada uno con timeout de 30 s
                  (video_frames.py:83-87,140-149,237-251) ⇒ hasta ~15 min dentro de
                  `asyncio.to_thread`, antes de crear el turno (business.py:184-189 → :222). Sin
                  circuito ni tope total; puede retrasar o dejar colgado el turno de ese chat.
               9. BAJO — ffprobe ausente (con ffmpeg presente) degrada la cobertura: duración
                  None ⇒ rate 1.0 y `-frames:v 30` ⇒ solo se revisan los primeros 30 s de un video
                  largo (video_frames.py:158-159,200-206); el único aviso es
                  `video_frames_command_failed` (warning). ffmpeg y ffprobe ausentes del todo SÍ
                  son fail-closed (`FrameExtractionError` → `no_verificable`): :145-155,237-251.
              10. BAJO — El video sensible se marca para revisión manual pero NO se adjunta al DM
                  de la dueña: `photo_file_id` solo existe para fotos (business.py:143). La dueña
                  lee "no analizada" sin poder ver el video, y el video no se persiste.
              11. BAJO — `_spread` deja fuera el último cuadro cuando recorta (índices
                  `int(i*step)`, nunca n-1): video_vision_service.py:194-199. Solo afecta lo que se
                  envía, no lo revisado.
              12. BAJO — El escáner estático no ve este cableado: la sección 3 solo detecta
                  condicionales de una línea y no reporta `media_downloader`/`video_vision`
                  (audit/tools/wiring_scan.py:51-56). Su único rastro es el log info de la guarda
                  de tamaño (audit/WIRING_SCAN.md:138). No hay que apoyarse en él para este
                  contrato.
              13. BAJO — Deriva posible aunque hoy no haya duplicación: la política es UNA función
                  importada (video_vision_service.py:32 ← image_vision_service.py:132). Video
                  consume `has_identity` y `strong` e ignora `receipt` a propósito; falta una
                  prueba de paridad foto↔video que avise si las dos aplicaciones se separan.
              14. BAJO — Otros dos consumidores del mismo servicio: importación de historial
                  (vip_history_seed.py:283-305, atrapa cualquier excepción y deja la etiqueta
                  muda = fail-open) y script manual (refresh_chat_media.py:117-124, construye
                  `GeminiVisionProvider` sin comprobar la key). No afectan el camino en vivo.
Prueba E2:     `tests/audit/test_C_PRV_02.py` — 14 casos, 14 passed (33–70 s). Entrada real:
               `build_app` + `dispatcher.feed_update`; ffmpeg, ffprobe, tesseract, extractor, OCR y
               `scan_sensitive` reales. Postgres real (copia `diana_copy.sql`, 2026-10-12).
               Simulados solo los bordes externos: descarga de Telegram (mp4 reales generados con
               ffmpeg) y Gemini (registra método, mime y cada payload). Casos: tarjeta visible solo
               en el segundo 3 de un video de 6 s; video grande → solo cuadros; variante sensible;
               >20 MiB; ffmpeg ausente; OCR ausente; bandera ON/OFF; video corrupto; factura; el
               caption no decide.
Sabotaje E3:   Worktree `/tmp/sabotaje-prv02` (detached `7d2a6c4`), revertido; producción intacta.
               S1 `scan_sensitive` siempre limpio → falla el caso del fotograma intermedio (4 failed).
               S5 cortar el llamador en `_review_frames` → falla el efecto (3 failed). S4 revisión
               vacía → fallan el caso intermedio y la variante sensible (4 failed). S2 bandera
               apagada → falla `bandera_on` (12 failed). S3 control negativo (extractor devuelve cero
               cuadros): la prueba SIGUE EN VERDE → confirma el fail-closed. Ningún sabotaje
               relevante sobrevivió.
Vigilante E4:  Propuesto (no implementado): conteo diario de videos analizados, bloqueados y no
               verificables, más el de llamadas al proveedor; alerta si un video marcado sensible no
               deja rastro en la cola o si un video sensible genera llamada al proveedor.
Nivel:         E3 en el rango probado: detección de dato fuerte en cualquier fotograma, rama de
               video grande (cuadros ya revisados), dependencia de la bandera y fail-closed ante cero
               cuadros. Sin sabotaje individual: factura, caption, par PNG/JPEG y fail-open del
               proveedor.
Semáforo:      🟡 — E3 en videos de hasta 30 s. La promesa "un fotograma por segundo" no se cumple
               en videos más largos (el tope de 30 fotogramas baja el muestreo) y ese caso no tiene
               prueba E2: queda como riesgo abierto.
Hallazgos:     1. ALTO — cobertura temporal: con `VIDEO_VISION_MAX_FRAMES=30`, un video de 5 min se
                  revisa cada 10 s; un dato entre muestras pasa como limpio (`video_frames.py:151-162`).
               2. ALTO — la detección depende de un OCR perfecto: texto vacío o parcial se trata
                  como limpio; el fail-closed solo dispara si el OCR lanza.
               3. MEDIO — la rama "video grande ⇒ solo cuadros" no es alcanzable con la
                  configuración real (guarda de descarga 20 MiB == `VIDEO_VISION_SEND_MAX_BYTES`);
                  funciona cuando el tope se baja, pero producción no la usa.
               4. MEDIO — en la rama de cuadros, un cuadro ≤1280 px viaja como PNG rotulado
                  `image/jpeg`; si el proveedor lo rechaza, el fail-open pierde la descripción.
               5. MEDIO — la ficha decía "solo memoria", pero el video y los PNG se escriben en un
                  directorio temporal que se borra al salir; un kill puede dejarlos en `/tmp`.
               6. MEDIO — sin `GEMINI_API_KEY`, la visión de video se apaga en silencio (solo log).
               7. BAJO — sin `ffprobe` solo se revisan los primeros 30 s (`video_frames.py:158-159`).
               8. BAJO — el video sensible no se adjunta al DM de la dueña: no puede verlo.
               9. BAJO — `_spread` omite el último cuadro al recortar.
              10. INFO — sin vigilante E4 de privacidad.
