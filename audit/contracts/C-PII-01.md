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
Camino:        (vacío — lo llena el Rastreador)
Puntos ciegos: (vacío)
Prueba E2:     (vacío)
Sabotaje E3:   (vacío)
Vigilante E4:  (vacío)
Nivel:         (vacío)
Semáforo:      (vacío)
Hallazgos:     (vacío)
