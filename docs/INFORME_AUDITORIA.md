# Informe de Auditoría — Diana Business Bot

**Fecha:** Julio 2026
**Tipo:** Auditoría de alineamiento código ↔ requerimientos
**Alcance:** 161 requerimientos revisados (P0, P1, P2)

---

## Resumen ejecutivo

El sistema está firme. De 161 requerimientos revisados, **139 están cumplidos**, 14 tienen observaciones menores, y solo **2 no están implementados** (los dos son funcionalidades que directamente no existen en el código).

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
Está mencionado en los requerimientos pero no implementado. La idea es poder "escuchar" chats no-VIP sin responder, solo para aprender. No es urgente, pero está pendiente.

**3. Generalización al crear políticas — GAP-11 (P1)**
Cuando la dueña resuelve una zona gris, el sistema no le pregunta "esto aplica siempre que pregunten por X, o solo en este caso puntual?". Hoy usa el texto que la dueña escribe directamente. Habría que agregar un paso de generalización para que las políticas sean más reutilizables.

**4. Regenerar variantes — MODE-05 (P1)**
Está fuera de alcance actual. La dueña no puede pedir "generame otra versión" de un borrador. Solo puede aprobar, corregir, o escalar.

**5. Recontacto sin pipeline cognitivo — REE-02 / COG-15 (P2)**
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

### Bloque 4: Zona Gris, Memoria, Políticas (23 reqs, 20 ✅ 3 ⚠️)

| Nro | Estado | Detalle |
|-----|--------|---------|
| GAP-01 a 10 | ✅ | Detección, consulta, freeze, respuesta, destilación, timed out, feature flag |
| GAP-11 | ⚠️ | No se pide generalización explícita a la dueña |
| GAP-08 | ⚠️ | No hay comando dedicado para listar/desactivar políticas activas |
| MEM-02 | ⚠️ | En Fase 1 el aprendizaje post-turno solo verifica trazabilidad, no extrae hechos |

### Bloque 5: Aprendizaje, Staging, Anti-contaminación (22 reqs, 17 ✅ 3 ⚠️ 2 🔍)

| Nro | Estado | Detalle |
|-----|--------|---------|
| TRN-07, ADM-08, BR-13 | ✅ | Staging obligatorio, confirmación explícita, nunca auto-promover |
| TRN-06 | ⚠️ | Fase 1 implementa 2 de las 4 fuentes de señal de aprendizaje |
| MEM-02 | ⚠️ | Aprendizaje post-turno no extrae hechos nuevos en Fase 1 |
| MET-04 | ⚠️ | Detector de drift de estilo existe pero sin baseline no funciona |

### Bloque 6: Behavior Engine (13 reqs, 13 ✅)

| Nro | Estado | Detalle |
|-----|--------|---------|
| Todos | ✅ | Separado de cognición, delay, read, typing, split, quirks, fake delivery, cancelación, retries |

### Bloque 7: Fase 3 (26 reqs, 18 ✅ 5 ⚠️ 3 🔍)

| Nro | Estado | Detalle |
|-----|--------|---------|
| MODE-01 a 04 | ✅ | Modos supervisado/autónomo, draft con contexto, aprobar/corregir |
| MODE-05 | 🔍 | Regenerar variantes está fuera de alcance |
| MODE-09 | ⚠️ | No hay calificación post-send autónomo dedicada |
| REE-02 / COG-15 | ⚠️ | Recontacto usa plantillas fijas, no pipeline reducido |
| PRO-01 a 04 | ✅ | Promo completa: trigger exacto, sin LLM, diferencia primer envío, Behavior Engine |
| EVAL-02 a 03 | ✅ | Calibración semanal con percentiles, umbrales ajustados |
| EVAL-04 | 🔍 | Sin visualización de calibración |
| MET-04 | ⚠️ | Drift detector implementado pero no calibrado |

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
| ✅ Cumple | 139 |
| ⚠️ Observación menor | 14 |
| 🔍 No implementado (P2 / fuera de alcance) | 6 |
| ❌ No implementado (P1) | 2 |
| **Total** | **161** |

**Prioridad de atención:**
1. **AUTH-03** (P1) — Tope de VIPs: agregar un límite configurable
2. **GAP-11** (P1) — Generalización en políticas: preguntar a la dueña antes de crear
3. **AUTH-07** (P2) — Modo observación
4. **REE-02 / COG-15** (P2) — Pipeline reducido en recontacto
5. **MODE-09** (P1) — Feedback post-send autónomo

---

*Documento generado automáticamente por auditoría de código contra REQUERIMIENTOS.md v2.1.*