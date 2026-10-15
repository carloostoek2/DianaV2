# Reporte del piloto — sombra, embeddings, historial
Fecha: 2026-10-06 · Alcance: lectura estática + escaneo automático. **No se ejecutó la suite ni se probó nada contra Postgres** (sin Docker/credenciales en este entorno). Por eso ningún contrato pasa de E0.

## Semáforo
| Contrato | Estado | Por qué |
|---|---|---|
| C-EMB-01 Embeddings reales | 🔴 riesgo confirmado en código | Siguen existiendo rutas que guardan "ceros" sin error; ya hubo un incidente real (2026-08) |
| C-SHADOW-01 Sombra vs. dueña | ⚪ | Camino existe y está cableado tras bandera; fallos se tragan sin alerta |
| C-HIST-01 Historial | ⚪ | Importación se apaga con un log si falta configuración |

## Hallazgos (con evidencia)
**H1 — Los fallos se tragan y nadie ve los contadores.** 385 `except Exception` y 46 `log_swallowed` en el código. `observability.py` cuenta los fallos pero lo dice él mismo: no se exponen en /health, y ningún archivo de producción los lee. Un hook núcleo (sombra, memoria, historial) puede fallar todos los días sin que nadie lo note. Es la causa común de lo que describiste.

**H2 — "Sin embedding" se guarda como ceros, no como error.** `examples.py:74` (`embedding or [0.0]*384`), `profiles.py:29,92,95` (`_ZERO_EMBEDDING`). La columna es NOT NULL, así que el sistema disfraza la ausencia de dato. Un registro con ceros existe pero la búsqueda por similitud no lo encuentra: "recuerda" algo que nunca recupera. El repo ya tuvo este bug (`scripts/backfill_feedback_embeddings.py`).

**H3 — Apagados silenciosos por configuración.** `composition.py:228` desactiva el import de historial si falta configuración de Telethon, con solo un log info. 44 rutas más se omiten únicamente con logs `*_skipped/_disabled` (ver `audit/WIRING_SCAN.md` §4).

**H4 — Lo crítico depende de banderas que no podemos ver.** La sombra Fila 4 solo se activa con `feature_autonomy_quality_enabled`; su valor real está en `.env`, fuera del zip. Hay 18 dependencias entregadas solo si hay bandera (§3 del escaneo). Falta leer el estado real de producción.

**H5 — 15 funciones definidas que nadie llama en producción** (lista en el escaneo §1). Candidatas, p. ej. `get_feature_flags`, `list_outcome_rows_since`, `list_weeks`, `distill_from_text`. Hay que confirmar una por una si es código muerto o algo que debía conectarse.

**H6 — Auditoría previa por lectura.** La auditoría "143/161 cumple" compara código con requisitos; no demuestra ejecución. Conviene tratarla como E0.

## Preguntas para la dueña / producto
1. ¿Cuál es el valor real hoy de las banderas Fila 4 en producción?
2. (Resuelta) Respuesta directa de la dueña en el chat: no se compara; no se contempló en el diseño. No es un error.
3. ¿Podemos correr una consulta de solo lectura contra la base real para contar embeddings en ceros y filas de `turn_outcome_log`?

## Siguiente paso recomendado
1. Consulta de solo lectura en producción (3 consultas, 5 minutos) → convierte H2/H4 de riesgo en hecho.
2. Ejecutar el piloto con los agentes (Probador + Saboteador) en una máquina con Docker.
3. Decidir el arreglo de fondo para H1 (exponer los contadores de silencios y alertar), antes de seguir con más contratos.

---
# Actualización con datos de producción (informe de Claude Code, 2026-10-06)
| Contrato | Antes | Ahora | Evidencia |
|---|---|---|---|
| C-EMB-01 | 🔴 riesgo | 🔴 confirmado (parcial) | 2/3 perfiles en ceros; resto 0 ceros |
| C-SHADOW-01 | ⚪ | 🟡 | Escribe todos los días; 14/237 sin fila; hueco de resultado 6–10 sep |
| C-HIST-01a captura | ⚪ | 🟡 | 0 sin id; flujo vivo |
| C-HIST-01b recarga | ⚪ | 🔴 | bandera false; cursor congelado 6-sep; 1 VIP con 1–5 mensajes |

Correlación a investigar: el cursor de recarga y el hueco de resultados de la dueña empiezan el MISMO día (6-sep, cambio de cuenta). Hipótesis, no probada: una causa común.
Vigilantes propuestos: `audit/vigilantes.sql` (V1–V6).

---
# CIERRE DEL PILOTO (investigaciones A, B y C)
Tres hipótesis mías resultaron incorrectas al medir: (1) los huecos de la sombra NO eran errores tragados; (2) NO había causa común en el cambio de cuenta; (3) los ceros en perfiles NO eran un bug vivo. El valor del método estuvo en descartarlas con datos.

| Contrato | Semáforo final | Resumen |
|---|---|---|
| C-SHADOW-01 | 🟡 | 14 huecos = rutas de diseño. 41 pérdidas = defecto de upsert corregido 10-sep. Sin recaídas. |
| C-EMB-01 | 🟡 | 4 tablas útiles limpias. 2 ceros históricos inocuos. La wiki afirma de más. |
| C-HIST-01a | 🟡 | 15.688 filas, todas con id |
| C-HIST-01b | ⚪ por decisión | Apagada a propósito (6-sep). Falta documentarla. |
| NUEVO | ❓ | Import al alta de VIP nuevo: encendido, misma sesión Telethon, no verificado con la cuenta nueva |

Pendientes ordenados: ver mensaje de cierre. Evidencia: INVESTIGACION-A/B/C.md · vigilantes: vigilantes.sql (V1–V7).

---
# CIERRE DE LA FASE 2 (2026-10-09)
| Contrato | Semáforo | Nivel | Pendiente |
|---|---|---|---|
| C-SHADOW-01 | 🟢 | E3 + E4 | corregir/escalar, reacción del VIP (vip_signal) sin prueba |
| C-EMB-01 | 🟢 | E3 + E4 | camino "Reprender" sin prueba propia |
| C-CTX-01 (nuevo) | 🟢 | E3 | vigilante de contenido propuesto, no implementado |
| C-HIST-01 (b) puerta/alta VIP | 🟢 | E3 | — |
| C-HIST-01 (a) captura de historial | 🟡 | E0 | 18 entregas sin rastro de historial sin explicar (V4) |
| Banderas núcleo | 🟢 | E3 | RECONTACT apagada sin declarar |

Defectos reales encontrados y corregidos: contexto temporal "rancio" (84 % de turnos con dato contrario a la conversación), tarea de importación sin referencia, ceros silenciosos en "Destacar".
Pendientes abiertos: contradicción sobre FEATURE_VIP_HISTORY_SEED_ENABLED (HISTORIAL vs BANDERAS H-B2), RECONTACT, 18 entregas sin historial, "avisos tuyos que no te llegaron: 3", vigilante externo (hombre muerto), retención de journald (requiere sudo).

---
# RONDA 2 (2026-10-13) — mapa de contratos, historial, sombra, Reprender
- MAPA-CONTRATOS.md: solo 5 áreas con evidencia de efecto (E2/E3/E4); el resto del sistema está en E0/E1. El "143/161 cumple" es lectura de código.
- C-HIST-01(a) captura: E3 (17 pruebas, 34 sabotajes, 32 muerden; 2 afirmaciones sueltas devueltas al Probador). Los 18 avisos de V4 = promociones a chats no VIP, por diseño. V4 debe ajustarse antes de activarse.
- DEFECTO ABIERTO: jobs/outcome_reaction.py:52 descarta el timestamp (texto ISO vs datetime). 176 'silence' escritos por el job, 80 (45 %) mal. Alimenta la confianza de autonomía. Arreglo de 1 línea + reparación de datos pendientes de decisión.
- INVESTIGACIÓN D: "3 avisos / 1 ánimo" era un EJEMPLO en modo seco del informe del vigilante, no una medición (error de lectura corregido). Hueco real: los contadores de fallos viven en memoria y un reinicio los borra. Propuesta A+B+C.
- Contradicciones documentales: 12 (ver MAPA §4).
