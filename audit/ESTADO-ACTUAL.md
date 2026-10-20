# Estado actual — 2026-10-15

| Contrato | Semáforo | Nivel | Pendiente |
|---|---|---|---|
| C-SHADOW-01 | 🟢 | E3 + E4 | reacción del VIP: defecto del job de respaldo (abierto) |
| C-EMB-01 | 🟢 | E3 + E4 | Reprender en sandbox, corrección desde Atención |
| C-CTX-01 | 🟢 | E3 | vigilante de contenido |
| C-HIST-01 (a) captura | 🟢 | E3 | ajustar V4 antes de activarlo |
| C-HIST-01 (b) alta VIP | 🟢 | E3 | confirmar de qué cuenta es la sesión |
| Banderas núcleo | 🟢 | E3 | RECONTACT apagada sin declarar |
| C-SBX-01 sandbox (métricas) | 🟡 | E2 | resuelto el aislamiento en métricas (PR #26, `4bc5754`, 2026-10-19); sin backfill; falta sabotaje |
| Resto del sistema | ⚪ | E0/E1 | rondas 1 a 5 (ver audit/MAPA-CONTRATOS.md) |

Siguiente: Prompt 12 (arreglos), 13 (documentos), 14 (rondas 1 y 2 en paralelo), luego Saboteador.
Nota 2026-10-19: V2 ya no depende del journal (`NOT t.is_sandbox`, migración 037, PR #26).
Archivos más recientes: MAPA-CONTRATOS, INVESTIGACION-D, FASE2-PRUEBAS-R2, FASE2-SABOTAJE-R2.
