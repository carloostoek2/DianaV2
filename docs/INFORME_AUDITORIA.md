# Informe de Auditoría — Diana Business Bot

**Fecha:** Julio 2026
**Tipo:** Auditoría de alineamiento código ↔ requerimientos
**Alcance:** 161 requerimientos revisados (P0, P1, P2)
**Actualizado:** 2026-08-21 — re-verificación factual contra el código (commit `b592192`). Los items que estaban marcados como no implementados / fuera de alcance fueron reclasificados según su estado real en el código.

---

## Resumen ejecutivo

El sistema está firme. De 161 requerimientos revisados, **143 están cumplidos**, 11 tienen observaciones menores, 5 no implementados (P2 / fuera de alcance) y **2 no implementados (P1)** que directamente no existen en el código.

### Lo que funciona bien

- **Pipeline cognitivo**: El flujo completo (Director → Analista → Planificador → Retrievers → Generador → Evaluador → Decisor) está correctamente implementado. Cada componente responde una sola pregunta, el Director es determinista (nunca le pregunta al LLM "qué hago"), y todo se conecta via el Registry sin acoplamiento.

- **Evaluación multidimensional**: El Evaluador mide 7 dimensiones (naturalidad, precisión, doctrina, consistencia, seguridad, cobertura, empatía). El Decisor prioriza correctamente: seguridad primero, después zona gris, después riesgo, después autónomo, después aprobar.

- **Comportamiento human-like**: El Behavior Engine está bien separado de la cognición. Hace delay, marca como leído, muestra typing, y envía con el timing correcto. En modo autónomo los delays son más largos y aleatorizados. Soporta división de mensajes largos y "tics humanos" (pausas, tipeo con error y corrección) si se activa el flag.

- **Zona gris**: El ciclo completo funciona: consultar doctrina → congelar VIP → dueña responde → se crea política estructurada → se descongela → se reutiliza en turnos futuros. Las consultas abiertas expiran después de 24h.

- **Memoria y aprendizaje**: Los 5 tipos de conocimiento (perfil, memoria, contexto, políticas, ejemplos) están separados en tablas y retrievers distintos. La memoria de un VIP es privada (nunca se contamina con ejemplos globales). Las correcciones pasan por staging y requieren confirmación explícita.

- **Anti-contaminación**: Memoria siempre filtrada por VIP. Ejemplos son globales. Nunca se mezclan.

- **Persistencia**: Todo vive en PostgreSQL. Los secretos van por env, no en el repo. Las trazas del pipeline se guardan con TTL configurable y se puede reconstruir el proceso mental de cualquier respuesta.

- **Admin**: La dueña tiene menú completo, trazabilidad paso a paso, gestión de staging, sandbox, pausa de VIPs, notas y facts.

### Lo que hay que resolver (priorizado)

**1. Tope de VIPs — AUTH-03 (P1)**
Hoy no hay un límite configurable de cuántos VIPs puede tener el sistema. Si alguien agrega 500 VIPs, el sistema lo va a intentar procesar. Conviene poner un tope configurable desde settings.

**2. Modo observación — AUTH-07 (P2)**
El sistema no tiene un modo de observación silenciosa de chats no-VIP: solo existe un training mode que responde (no-VIP con training ON pasa al pipeline cognitivo y responde). El modo observación pide "escuchar" sin responder, solo para aprender.

**3. Generalización al crear políticas — GAP-11 (P1)**
Cuando la dueña resuelve una zona gris, el sistema no le pregunta "esto aplica siempre que pregunten por X, o solo en este caso puntual?". Hoy usa el texto que la dueña escribe directamente. Habría que agregar un paso de generalización para que las políticas sean más reutilizables.

**4. Recontacto sin pipeline cognitivo — REE-02 / COG-15 (P2)**
El recontacto por silencio usa plantillas fijas, pero los requerimientos piden un pipeline reducido (que recuerde cosas del VIP, genere un mensaje personalizado, lo evalúe, etc.). Hoy salta toda la cognición.

---

## Detalle por área

### Bloque 1: Pipeline cognitivo y Director (16 reqs, 15 ✅ 1 ⚠️)

| Nro | Estado | Detalle |
|-----|--------|---------|
| 15 reqs | ✅ | Director determinista, Registry conecta componentes, cada uno responde una sola pregunta, contexto acotado |
| COG-16 | ⚠️ | El cortocircuito de escalación vive en un middleware de Telegram, no en el Director como dice el diseño original. Funciona, pero está en la capa equivocada |

### Bloque 2: Evaluación y Decisor (6 reqs, 6 ✅)

| Nro | Estado | Detalle |
|-----|--------|---------|
| Todos | ✅ | 7 dimensiones evaluadas, Decisor prioriza correctamente, modo supervisado/autónomo es filtro externo |

### Bloque 3: Auth, VIPs y Coordinación de turno (18 reqs, 15 ✅ 1 ⚠️ 2 ❌)

| Nro | Estado | Detalle |
|-----|--------|---------|
| AUTH-01 | ✅ | No-VIP no entra al flujo cognitivo |
| AUTH-02 | ✅ | Dueña puede agregar/quitar VIPs |
| AUTH-03 | ❌ | **No hay tope configurable de VIPs** |
| AUTH-07 | ❌ | **Modo observación no existe** |
| VIP-07 | ⚠️ | La deduplicación de mensajes funciona pero tiene una ventana donde podrían colarse duplicados |

### Bloque 4: Zona Gris, Memoria, Políticas (23 reqs, 21 ✅ 2 ⚠️)

| Nro | Estado | Detalle |
|-----|--------|---------|
| GAP-01 a 10 | ✅ | Detección, consulta, freeze, respuesta, destilación, timed out, feature flag |
| GAP-11 | ⚠️ | No se pide generalización explícita a la dueña |
| GAP-08 | ⚠️ | No hay comando dedicado para listar/desactivar políticas activas |
| MEM-02 | ✅ | La extracción post-turno está implementada y cableada al orquestador de turno (`memory_extraction_service.py` `extract_post_turn`, invocado desde `turn_orchestrator.py` `_maybe_post_turn`) |

### Bloque 5: Aprendizaje, Staging, Anti-contaminación (22 reqs, 20 ✅ 2 🔍)

| Nro | Estado | Detalle |
|-----|--------|---------|
| TRN-07, ADM-08, BR-13 | ✅ | Staging obligatorio, confirmación explícita, nunca auto-promover |
| TRN-06 | ✅ | Las fuentes de señal de aprendizaje están implementadas y cableadas (`strong_signal_heuristics.py` señal fuerte para resíntesis + `profile_synthesis_trigger_service.py`) |
| MEM-02 | ✅ | La extracción post-turno extrae hechos (`extract_post_turn` → `insert_facts`) y está cableada al orquestador |
| MET-04 | ✅ | El detector de drift tiene baseline configurable (`calibration_service.py` `drift_alert_threshold: 0.1`, `baseline_weeks: 4`) y calcula `style_drift_score` contra él |

### Bloque 6: Behavior Engine (13 reqs, 13 ✅)

| Nro | Estado | Detalle |
|-----|--------|---------|
| Todos | ✅ | Separado de cognición, delay, read, typing, split, quirks, fake delivery, cancelación, retries |

### Bloque 7: Fase 3 (26 reqs, 20 ✅ 4 ⚠️ 2 🔍)

| Nro | Estado | Detalle |
|-----|--------|---------|
| MODE-01 a 04 | ✅ | Modos supervisado/autónomo, draft con contexto, aprobar/corregir |
| MODE-05 | ✅ | Regenerar variantes está implementado (`draft_variants.py` `DraftVariantService.regenerate`, callbacks regen/prev/next, botones prev / Regenerar / next) |
| MODE-09 | ⚠️ | No hay calificación post-send autónomo dedicada |
| REE-02 / COG-15 | ⚠️ | Recontacto usa plantillas fijas, no pipeline reducido |
| PRO-01 a 04 | ✅ | Promo completa: trigger exacto, sin LLM, diferencia primer envío, Behavior Engine |
| EVAL-02 a 03 | ✅ | Calibración semanal con percentiles, umbrales ajustados |
| EVAL-04 | 🔍 | Sin visualización de calibración por dimensión (el resumen semanal muestra tasa global y drift, no tabla por dimensión) |
| MET-04 | ✅ | Drift detector con baseline de 4 semanas y umbral de alerta configurable; el drift se calcula contra el baseline |

### Bloque 8: Admin, Persistencia, NFRs (34 reqs, 33 ✅ 1 🔍)

| Nro | Estado | Detalle |
|-----|--------|---------|
| ADM-01, 04-09 | ✅ | Menú, pausa, sandbox, traza, staging, métricas |
| ADM-03 | 🔍 | No hay cambio de LLM en caliente |
| PER-01 a 08 | ✅ | Todo persistente, reconstruible, secretos seguros |
| NFR-01 a 16 | ✅ | Sin race conditions, sin fugas, retries acotados, testeable, explicable |

---

## Resumen numérico

| Estado | Cantidad |
|--------|----------|
| ✅ Cumple | 143 |
| ⚠️ Observación menor | 11 |
| 🔍 No implementado (P2 / fuera de alcance) | 5 |
| ❌ No implementado (P1) | 2 |
| **Total** | **161** |

**Prioridad de atención (pendientes reales a 2026-08-21):**
1. **AUTH-03** (P1) — No existe un tope configurable de VIPs simultáneos
2. **GAP-11** (P1) — Al resolver una zona gris no se pide confirmación de generalización a la dueña (el mismo texto se usa como `generalization` y `rule`)
3. **MODE-09** (P1) — No hay calificación post-send dedicada tras envíos autónomos
4. **ADM-03** (P1) — No hay cambio de proveedor/modelo LLM en caliente
5. **AUTH-07** (P2) — No hay modo de observación silenciosa de chats no-VIP
6. **REE-02 / COG-15** (P2) — El recontacto por silencio usa plantillas fijas, sin pipeline reducido
7. **EVAL-04** (P2) — No hay visualización de calibración por dimensión (el resumen semanal muestra tasa global y drift, no tabla por dimensión)
8. **GAP-08** (P2) — No hay comando dedicado para listar/desactivar las políticas de doctrina desde admin

---

*Documento generado automáticamente por auditoría de código contra REQUERIMIENTOS.md v2.1.*
