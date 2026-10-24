# Matriz de banderas — contratos auditados

Este documento responde una sola pregunta: **para cada contrato auditado, qué bandera lo gobierna,
cuál es su valor real, qué se pierde si se apaga y quién se entera**.

Regla de esta matriz: solo entra lo verificado. Cada fila cita el archivo y la línea que la sostiene.
No se cambió ningún valor de bandera ni el `.env` para escribirla.

---

## Ronda 2 — privacidad (2026-10-24)

Contratos: **C-PRV-01** (fotos), **C-PRV-02** (video), **C-PII-01** (texto).

### Cómo se verificó

| Qué | Cómo | Resultado |
|---|---|---|
| Default real de cada bandera | Lectura de `src/diana/config/settings.py` | ver tabla |
| Valor efectivo en el entorno | `Settings()` cargado con el `.env` real; se imprimieron **solo** los seis valores de privacidad (sin claves ni cadenas de conexión) | ver tabla |
| Valor real del proceso vivo | `GET http://127.0.0.1:8080/health` → bloque `checks.flags` | las tres banderas no aparecen entre las apagadas |
| Aviso al arrancar | `runtime/banderas_arranque.json` + `src/diana/application/aviso_banderas.py` | 1 apagada declarada, 1 sin declarar (`FEATURE_RECONTACT_ENABLED`) |
| Dependencias locales | `which ffmpeg ffprobe tesseract`; import de `pytesseract` y `PIL` en el venv | presentes |
| Texto de conversaciones VIP | **no leído** (regla de privacidad) | — |

Nivel de evidencia que deja esta ronda: **E1** para los tres contratos (lectura de código + configuración
real). No se corrió una prueba de efecto con una imagen o un video reales; esta matriz **no** sube el
nivel de `audit/MAPA-CONTRATOS.md`.

### Tabla principal

| Bandera | Default en `settings.py` | Valor real en `.env` | ¿Núcleo? | Qué se pierde si está OFF | Aviso a la dueña al arrancar si OFF | ¿Declarada como apagada a propósito? |
|---|---|---|---|---|---|---|
| `FEATURE_IMAGE_VISION_ENABLED` | `False` (`settings.py:62`) | **`true`** (`.env:29`), comentario de comportamiento (`.env:24-27`) | **Sí** (`banderas_nucleo.py:105-108`) | No se descarga la foto, no corre el filtro OCR, Diana no la describe (queda `[imagen]`), **y la foto deja de aparecer en el DM de aprobación** (`photo_file_id=None`, verificado en `tests/unit/telegram/test_business_vision.py:245-252`) | **Sí** — aviso de banderas núcleo sin declarar (no está declarada) | No |
| `FEATURE_VIDEO_VISION_ENABLED` | `False` (`settings.py:67`) | **`true`** (`.env:38`), comentario de comportamiento (`.env:31-36`) | **Sí** (`banderas_nucleo.py:109-112`) | No se descarga el video, no se extraen fotogramas, no se revisa ni se describe (queda `[video]`) | **Sí** — aviso de banderas núcleo sin declarar | No |
| `FEATURE_PII_MASKING_ENABLED` | **`True`** (`settings.py:58`; única bandera con default seguro) | **`true`** (`.env:22`), comentario «Default seguro = true; apagar solo para depuración» (`.env:19-21`) | **Sí** (`banderas_nucleo.py:113-116`) | El texto del turno viaja **tal cual** al proveedor externo: correos, teléfonos, tarjetas, `@usuarios` y enlaces dejan de reemplazarse (`deepseek.py:168-169`) | **Sí** — aviso de banderas núcleo sin declarar | No |

**Corrección importante sobre la hipótesis de núcleo.** Para fotos y video, apagar la bandera **no**
manda la media «sin revisar»: apaga también la descarga y la llamada al proveedor. Es decir, con la
bandera OFF no hay fuga (no se descarga nada); lo que se pierde es la **capacidad del negocio** (Diana
no ve la foto/video y la dueña no recibe la foto en la cola). Siguen siendo núcleo por esa pérdida, no
porque la privacidad se rompa. El único de los tres que al apagarse rompe la promesa de privacidad es
`FEATURE_PII_MASKING_ENABLED`: el texto sale sin enmascarar.

### Cumplimiento de la regla de prioridad (AGENTS.md §1)

| Requisito | Estado |
|---|---|
| Valor explícito en el `.env` real | **Cumple** para las tres (`.env:22`, `.env:29`, `.env:38`) |
| Comentario de intención con la etiqueta VIVO / SHADOW / kill-switch | **Parcial**. Hay comentario de comportamiento en las tres, pero ninguna usa la etiqueta del vocabulario de la regla. PII dice «apagar solo para depuración»; foto y video describen el flujo, no la intención operativa |
| Bandera núcleo apagada declarada con motivo, fecha y condición | **No aplica hoy**: las tres están encendidas. Si se apaga alguna sin declararla, el arranque avisa y `/health` queda en `ok:false` |
| Catálogo completo | **Cumple** para las tres: están en `CATALOGO` |

### Parámetros y topes

| Parámetro | Default | Valor real en `.env` | Dónde se aplica | Observación verificada |
|---|---|---|---|---|
| `VIDEO_VISION_MAX_FRAMES` | `30` (`settings.py:71`, acotado 1–120) | `30` (`.env:42`) | `FfmpegFrameExtractor(max_frames=...)` (`composition.py:510`) | Tope de fotogramas revisados **localmente**. En videos de hasta 30 s se mira 1 por segundo |
| `VIDEO_VISION_SEND_MAX_BYTES` | `20 MiB` = `20971520` (`settings.py:74`) | `20971520` (`.env:47`) | `VideoVisionService(send_max_bytes=...)` (`composition.py:514`) | **Inerte con el valor actual**: coincide exactamente con el tope de descarga de Telegram del handler (`business.py:31`, `20 * 1024 * 1024`). Un video que se puede descargar nunca supera este umbral, así que la rama «viajan solo los cuadros» no se alcanza |
| `VIDEO_VISION_FRAMES_SENT` | `20` (`settings.py:76`, acotado 1–60) | `20` (`.env:48`) | `VideoVisionService(frames_to_send=...)` (`composition.py:515`) | **Inerte hoy** por la fila anterior: solo se usa en la rama que no se alcanza |
| Tope de tamaño de **foto** | No existe tope de bytes | — | — | La foto se descarga completa y se reduce a 1280 px de lado mayor **solo para el envío** (`infrastructure/vision/resize.py:18`). `downscale_image` devuelve `None` si no puede decodificar y el llamador manda el original (`resize.py:42-47`) |
| Guard de píxeles del OCR | `4000 × 4000` px (`ocr.py:_MAX_OCR_IMAGE_PIXELS`) | — | OCR local | Protección contra bombas de descompresión; al excederse, el OCR falla y la imagen se trata como sensible |

### Override en caliente (`system_config`)

| Pregunta | Respuesta verificada |
|---|---|
| ¿`get_feature_flags` tiene llamadores reales? | **No.** Definido en `infrastructure/db/repositories/system_config.py:132` y **cero llamadores** en `src/`, `scripts/` y `tests/` |
| ¿Qué prevalece, `Settings` o la base? | **`Settings` / `.env`**. `composition.py:642-644` lo deja escrito: «Feature flags come from Settings (source of truth). DB-side overrides are not implemented» |
| ¿Se puede pisar desde la base alguna de las tres? | **No.** Ninguna de las tres se lee de `system_config`. El único uso del store relacionado con el LLM es la clave `llm` (modelo / base_url / credencial), no las banderas |
| Excepción encontrada | `HotSwapLLMProvider._default_factory` construye el proveedor con `pii_masking=True` **fijo** (`llm/hot_swap.py:92`), ignorando `feature_pii_masking_enabled`. Si la dueña cambia el modelo o la URL en caliente y además apaga el enmascarado, el cambio en caliente **vuelve a encender** el enmascarado. El kill-switch no se respeta en ese camino; no hay prueba que lo cubra |

### Fallbacks silenciosos

Los puntos ciegos del **filtro con la bandera encendida** (OCR que devuelve texto vacío y se trata como
limpio, una tarjeta que gana a un documento de identidad, separadores no cubiertos) los dejó el
Rastreador en `audit/contracts/C-PRV-01.md`, misma ronda. Esta matriz no los repite: aquí entran solo
los fallbacks que dependen de la bandera o de una pieza que la bandera deja en `None`.

Qué ve la dueña **hoy**: en todos estos casos, nada. La lista dice también qué debería ver.

| # | Situación | Qué queda en `None` / qué se omite | Qué ve la dueña | Qué debería ver |
|---|---|---|---|---|
| F1 | Bandera de foto o video ON, pero `GEMINI_API_KEY` vacía | `vision_provider=None` → `image_describer`/`video_describer=None` → `self._enabled = flag and describer is not None` queda en **False** (`image_vision_service.py:209`, `video_vision_service.py:84`); `media_downloader=None` (`composition.py:517-525`) | Nada: la foto/video llega con etiqueta plana y **sin adjunto** en el DM. Solo queda `media_vision_wired` con `captioner:false` en el registro técnico | Un aviso al arrancar del tipo «la visión está encendida pero no hay con qué describir», y un check en `/health` |
| F2 | Falla la descarga o el análisis de una foto | Se devuelve etiqueta plana + `file_id`; la foto **sí** llega al DM (`business.py:60-67`) | Nada distinto a una foto sin descripción. No puede saber si fue un fallo o la bandera apagada | Un contador visible o un aviso si falla de forma repetida (hoy solo `image_vision_failed_fail_open` en el registro) |
| F3 | Falla la descarga o el análisis de un video | Etiqueta `[video]` plana (`business.py:95-101`) | Nada | Igual que F2 |
| F4 | El video declarado pesa más de 20 MiB | No se descarga; etiqueta plana (`business.py:84-90`) | Nada | «no se analizó: archivo demasiado pesado» en el texto del turno |
| F5 | OCR local roto (tesseract ausente o imagen ilegible) | Falla cerrado: `sensitive=True` y el texto del turno dice «contiene información sensible (no analizada)» (`image_vision_service.py:223-231`) | Ve la marca, pero **no** la causa: puede creer que la foto trae una tarjeta cuando en realidad el lector no funciona | Un aviso explícito de «el lector local no está disponible» y un check en `/health`; si no, todas las fotos y videos caen en revisión manual para siempre |
| F6 | `downscale_image` no puede decodificar | Devuelve `None` y **viaja el original** (`resize.py:42-47`) | Nada | Nada visible (el filtro de privacidad ya pasó), pero conviene un tope de bytes para no romper el plazo del proveedor |
| F7 | El modelo en caliente se reconstruye | `pii_masking=True` fijo (`hot_swap.py:92`) | Nada (el enmascarado sigue puesto) | Es una discrepancia de configuración: si la dueña apagó el enmascarado a propósito, debería saber que el cambio en caliente lo vuelve a encender |
| F8 | Llamadas al modelo con `FakeLLM` (sin `DEEPSEEK_API_KEY`) | No hay proveedor externo, así que C-PII-01 no aplica | Nada; el arranque solo deja `using FakeLLM` en el registro | Un aviso a la dueña: en producción eso significa que no hay borradores reales |

### Promesas del contrato que la bandera no cumple hoy

| # | Contrato | Qué promete | Qué hace el código | Consecuencia |
|---|---|---|---|---|
| P1 | C-PRV-02 | «extrae un fotograma por segundo» | Para videos de más de `VIDEO_VISION_MAX_FRAMES` segundos, la frecuencia baja a `max_frames / duración` (`video_frames.py:151-162`). Un video de 2 minutos se revisa 1 vez cada 4 s | Un dato que aparezca entre dos muestras no se ve y **el video sale**. La promesa solo se cumple en videos de hasta 30 s |
| P2 | C-PRV-02 | Revisión de punta a punta | Si `ffprobe` no informa la duración, se revisan **10 fotogramas** (segundos 0 a 9) sin importar el tope (`video_frames.py:37, 174`) | Contenido sensible después del segundo 10 en un video con metadatos raros no se revisa y el video sale |
| P3 | C-PRV-02 | «cuando pesa demasiado salen solo los cuadros» | `VIDEO_VISION_SEND_MAX_BYTES` es igual al tope de descarga (`business.py:31`) | La rama no se alcanza con los valores actuales; el parámetro no hace nada |
| P4 | Las tres | Que alguien note si el efecto deja de ocurrir | No hay vigilante de contratos para privacidad (`audit/vigilantes.sql` no consulta visión ni enmascarado) | Un fallo sostenido (OCR roto, clave inválida, proveedor caído) no avisa a la dueña |

### Apagados no declarados (comprobación global de la regla §1)

| Bandera | Estado real | Declarada | Efecto |
|---|---|---|---|
| `FEATURE_RECONTACT_ENABLED` | `false` | **No** | `/health` queda en `ok:false` permanente con `sin_declarar: ["FEATURE_RECONTACT_ENABLED"]` (verificado en el proceso vivo y en `runtime/banderas_arranque.json`); el arranque avisa una vez |
| `FEATURE_HISTORY_REIMPORT_ENABLED` | `false` | **Sí** (`banderas_nucleo.py:121-137`, desde 2026-09-06) | Silenciada correctamente |
| `FEATURE_FORCE_PROFILE_WHEN_NOTES` | Default `True` | — | **No está escrita en el `.env`** (único campo `feature_*` de `Settings` ausente). No es núcleo y no pertenece a esta ronda, pero incumple la regla §1.1 |

### Qué no se verificó

- No se ejecutó el pipeline con una foto o un video reales: los tres contratos siguen en **E1**.
- No se llamó a Gemini ni a DeepSeek.
- No se leyó texto de conversaciones de VIP; no se consultó la base.
- No se probó el enmascarado contra una muestra real de mensajes (solo lectura del código y de sus pruebas unitarias).
- El bloque `checks.flags` de `/health` no publica **cuáles** banderas están encendidas, solo las apagadas; el valor ON de las tres se confirmó por ausencia en las listas de apagadas y por `Settings()`.
- La cadena de la foto con la bandera encendida quedó rastreada por otro agente en `audit/contracts/C-PRV-01.md`; video y texto seguían sin rastrear al cerrar esta matriz.
