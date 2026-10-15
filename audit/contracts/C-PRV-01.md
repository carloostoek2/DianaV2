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
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
