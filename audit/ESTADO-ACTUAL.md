# Estado actual — 2026-10-15

| Contrato | Semáforo | Nivel | Pendiente |
|---|---|---|---|
| C-SHADOW-01 | 🟢 | E3 + E4 | — |
| C-EMB-01 | 🟢 | E3 + E4 | Reprender en sandbox, corrección desde Atención |
| C-CTX-01 | 🟢 | E3 | vigilante de contenido |
| C-HIST-01 (a) captura | 🟢 | E3 | V4 ajustado a turnos VIP; falta decidir si se enciende |
| C-HIST-01 (b) alta VIP | 🟢 | E3 | confirmar de qué cuenta es la sesión |
| Banderas núcleo | 🟢 | E3 | — |
| C-SBX-01 sandbox (métricas) | 🟡 | E2 | resuelto el aislamiento en métricas (PR #26, `4bc5754`, 2026-10-19); sin backfill; falta sabotaje |
| C-PRV-01 fotos | 🔴 | E3 (caminos cubiertos) | documento + 16 dígitos viaja; OCR vacío tratado como limpio; tarjeta con puntos; sin vigilante |
| C-PRV-02 video | 🟡 | E3 (≤30 s) | muestreo flojo en videos >30 s sin prueba E2; rama de cuadros inalcanzable; video sensible no llega al DM |
| C-PII-01 texto | 🔴 | E3 | tarjeta + caducidad/CVV y separadores no cubiertos; PII restaurada en logs de error (leído, no medido); sin vigilante |
| Resto del sistema | ⚪ | E0/E1 | rondas 1, 3, 4 y 5 (ver audit/MAPA-CONTRATOS.md) |

Siguiente: **Ronda 1** (C-ESC-01 escalación, C-GRZ-01 zona gris, C-SUP-01 un turno vivo); después los arreglos técnicos del `audit/REPORTE.md` §8 y las 4 decisiones de producto del §7.
Nota 2026-10-25: cerrado el defecto del job de respaldo de la reacción del VIP (el historial entrega la marca de tiempo como texto y el job la descartaba: toda reacción se cerraba como silencio; la prueba que estaba marcada como defecto conocido ya pasa). V4 mide solo turnos VIP —los 27 huecos de 14 días eran promociones a chats sin VIP— y queda listo para encender.
Nota 2026-10-24: cerrada la Ronda 2 — 42 casos E2 en verde (`tests/audit/test_C_PRV_01|02.py`, `test_C_PII_01.py`) y sabotajes revertidos; informe en `audit/REPORTE.md`.
Nota 2026-10-19: V2 ya no depende del journal (`NOT t.is_sandbox`, migración 037, PR #26).
Archivos más recientes: REPORTE, FLAG_MATRIX, TEST C-PRV/C-PII, FASE2-SABOTAJE-R2.
