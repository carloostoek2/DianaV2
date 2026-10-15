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
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
