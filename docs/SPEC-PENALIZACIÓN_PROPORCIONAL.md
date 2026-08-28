---
título: SPEC-EA-07 — Penalización proporcional por gravedad de corrección
estado: propuesta (borrador para revisión de producto)
fecha: 2026-08-27
extiende: docs/SPEC-EVOLUCION-AGENTE.md §5.1 (EA-01)
relacionado: wiki/concepts/trust-budget.md, wiki/concepts/zona-gris-y-politicas.md,
             wiki/concepts/aprendizaje-post-turno.md, docs/SPEC-AUTONOMIA-CALIBRACION.md §6-§7
---

# SPEC-EA-07 — Penalización proporcional por gravedad de corrección

## 0. Problema (tal como lo plantea el owner)

El trust budget (`TrustBudgetService`, EA-01) aplica hoy un decremento **uniforme**
de `0.20` ante *cualquier* corrección del owner, sin distinguir su naturaleza:
un ajuste de tono (suavizar un borrador frío) pesa lo mismo que un
incumplimiento doctrinal. Se pide evaluar la viabilidad de un decremento
**proporcional a la gravedad** de la corrección.

Este documento: (1) audita qué señales ya existen en el sistema para clasificar
gravedad sin construir infraestructura nueva, (2) compara las opciones de
diseño con sus riesgos, y (3) propone un mecanismo concreto, compatible con
los invariantes ya establecidos en EA-01/EA-03 y con la lección del incidente
de calibración.

---

## 1. Estado actual (auditoría de código)

| Elemento | Archivo | Comportamiento |
|---|---|---|
| Decremento | `application/trust_budget_service.py` L46 | `DEFAULT_TRUST_BUDGET_DECREMENT = 0.20`, fijo, aplicado igual desde `record_correction` y desde `record_outcome(event="label", value="desacuerdo")` |
| Asimetría | `trust_budget_service.py` L127-134 | `apply_overrides` **rechaza** cualquier config donde `decrement <= increment` — la única invariante de gravedad que existe hoy es binaria (castigo > premio), no graduada |
| Origen de la corrección | `application/admin_service.py` `_correct_core` (L705-769) | El owner manda **texto libre** (`corrected_text`). No hay ningún campo estructurado de "tipo de corrección" ni "motivo" hoy. El sistema guarda `original_draft` vs `corrected_text` (vía `staging.save_correction`) pero no lo interpreta |
| Aplicación del decremento | `admin_service.py` L748-767 | `record_correction(turn_id)` — resuelve `(vip_id, category)` por `turn_id` y aplica el decremento fijo si el turno era `would_autonomous == True` |

**Conclusión de la auditoría:** hoy no existe ningún punto del pipeline que
etiquete gravedad. La única señal usada es "hubo corrección, sí/no". Pero el
sistema **ya calcula, para el mismo turno, tres señales que sí distinguen
tipo/magnitud** — simplemente no se conectan al trust budget:

### 1.1 Señal A — `EvaluationProfile` (pre-hoc, ya calculada antes del envío)

`cognitive/models.py` L222-238: el evaluador califica cada borrador en 7
dimensiones independientes, entre ellas `doctrine`, `safety`, `naturalness`,
`empathy`. Se persiste en `PipelineTrace.evaluation` (JSON), legible por
`turn_id` (ya lo hace `calibration_data.py::parse_evaluation_dims` para
`safety/doctrine/naturalness`). Es una autoevaluación del modelo **antes** de
que el owner corrija.

**Límite importante:** si el evaluador ya detectó `doctrine` o `safety` bajos,
el turno probablemente ya fue desviado por otra vía (zona gris / escalación)
antes de llegar a "corrección simple". Esta señal es más útil para
turnos donde el modelo *no* se dio cuenta del problema — que es justo el caso
más peligroso y el que menos cubre.

### 1.2 Señal B — `text_quality_heuristics` (post-hoc, determinista, mide el cambio real)

`application/text_quality_heuristics.py`: scorer determinista 0-1 sobre
longitud, cierre, uso del nombre, calidez léxica, naturalidad — con gate duro
a 0.0 si hay PII o keyword prohibida. Ya se usa para computar
`quality_delta = score(sent) − score(shadow draft)` en
`outcome_log_service.py` (`turn_outcome_log.quality_delta`), pero **solo se
loguea, no modula el trust budget**. Mide *cuánto cambió* el texto en un eje
de tono/calidez — exactamente el tipo de señal que distinguiría "ajuste
menor de tono" de "reescritura completa". No mide doctrina.

### 1.3 Señal C — vínculo con zona gris / doctrina (estructural, determinista)

`infrastructure/db/repositories/gray_zone.py::get_open_by_turn_id` — si un
turno tuvo una consulta de doctrina abierta o resuelta (`gray_zone_service`,
`handlers/doctrine.py`), eso es una marca estructural fuerte de "esto era
territorio doctrinal", independiente de cualquier heurística de texto.

**Límite:** solo cubre casos donde el sistema *ya sabía* que dudaba. Un
incumplimiento doctrinal que el modelo emitió con confianza (sin pasar por
zona gris) y que el owner detecta recién al corregir **no deja rastro
estructural** — solo se ve en el texto corregido, que hoy nadie interpreta.

### 1.4 Precedente ya existente: EA-04

`SPEC-EVOLUCION-AGENTE.md` línea 20 (EA-04): la síntesis de perfil ya
distingue "corrección de tono/personalidad" vs "corrección de contenido
puntual" — pero lo hace un **LLM de síntesis**, sobre `feedback_signals`, y
**nunca escribe al trust budget** (solo alimenta el perfil VIP). Es la prueba
de que el proyecto ya consideró este problema, y deliberadamente lo resolvió
en un carril que no toca gates de seguridad/confianza.

---

## 2. La restricción no negociable

`SPEC-EVOLUCION-AGENTE.md` línea 7 documenta el incidente que fija la
arquitectura actual:

> *"El incidente de calibración (safety_min calibrado a 0.95 por
> correcciones → escalaciones masivas) es el precedente que prohíbe
> recalibración automática de gates de seguridad/confianza."*

Y `trust_budget_service.py` L9-11 lo repite explícitamente: el score se
actualiza **solo por eventos, nunca por calibración LLM**. Cualquier
propuesta de "gravedad proporcional" que delegue el juicio de severidad a un
LLM en el momento de la corrección **reintroduce la forma exacta del
incidente**: un proceso automático moviendo un número que gobierna
autonomía, sin supervisión humana directa. No importa que la intención sea
"ser más justo" — el mecanismo de fallo es el mismo.

Esto descarta de entrada cualquier diseño donde un LLM clasifique
"tono vs. doctrina" y ese veredicto alimente directamente el decremento.

---

## 3. Opciones consideradas

| # | Mecanismo | Determinismo | Cobertura del caso "doctrina no detectada" | Fricción para el owner | Riesgo |
|---|---|---|---|---|---|
| **A** | Prefill desde `EvaluationProfile` (señal A) | Determinista | Baja (ver 1.1) | Ninguna | Bajo, pero cobertura débil donde más importa |
| **B** | Severidad = magnitud de edición (Levenshtein / delta de `text_quality_heuristics`, señal B) | Determinista | No distingue *tipo*, solo *cuánto cambió* | Ninguna | Una corrección corta puede ser gravísima ("no prometas eso" en 4 palabras) y una larga puede ser solo estilo — la magnitud del texto **no correlaciona con gravedad doctrinal** |
| **C** | Clasificador LLM en el momento de corregir | No determinista | Alta (lee el texto real) | Ninguna | **Rechazada** — es el patrón del incidente (§2) |
| **D** | Etiqueta del owner al corregir (botones, mismo patrón que `doctrine_scope_keyboard`) | Determinista (humano) | Alta — el owner es quien mejor sabe por qué corrigió | Un tap extra por corrección | Bajo: el owner ya es la autoridad final en todo el sistema (aprueba, corrige, escala); pedirle que califique su propia corrección no delega nada que no controle ya |
| **E** | Vínculo estructural con zona gris (señal C) como *hard override* a "grave" | Determinista | Solo casos ya detectados por el pipeline | Ninguna | Bajo, pero insuficiente solo |

**Ninguna opción determinista por sí sola cubre bien el caso que más le
importa al owner** (doctrina violada con confianza, sin que el pipeline lo
supiera). Ese caso solo lo puede juzgar el owner al momento de corregir. Por
eso la recomendación es un híbrido D + A + E, con D como fuente de verdad y
A/E como *prefill* para no aumentar fricción en el caso común.

---

## 4. Diseño propuesto

### 4.1 Taxonomía de gravedad (fija, 3 niveles)

```
CorrectionSeverity = "minor" | "moderate" | "major"

minor    → ajuste de tono/estilo/calidez, el contenido de fondo era correcto
moderate → corrección de contenido puntual (dato, oferta, horario) — DEFAULT
major    → incumplimiento doctrinal, riesgo de seguridad, promesa indebida
```

`moderate` es el default y coincide **byte a byte** con el comportamiento
actual (0.20) — esto es una generalización estricta del sistema hoy, no un
cambio de comportamiento por sí solo. Nadie pierde ni gana confianza distinto
a hoy hasta que el owner empiece a usar las etiquetas `minor`/`major`.

### 4.2 Origen de la etiqueta (D, con prefill A/E)

En el flujo de corrección (`handlers/admin.py`, mismo punto donde hoy se pide
`corrected_text`), agregar un paso de un tap — **mismo patrón UI que
`doctrine_scope_keyboard`** (`ds:` — "¿Solo este VIP o a todos?"), que ya
existe y el owner ya conoce:

```
[ 🎨 Tono ]   [ 📋 Contenido ]   [ ⚠️ Doctrina/Seguridad ]
```

Preselección (no vinculante, el owner puede tocar otro botón):
- Si `gray_zone.get_open_by_turn_id(turn_id)` no es None → preseleccionar
  **Doctrina/Seguridad** (señal C).
- Si el `EvaluationProfile` del turno tiene `doctrine < umbral` o
  `safety < umbral` → preseleccionar **Doctrina/Seguridad** (señal A).
- Si `text_quality_heuristics` marcó gate duro (PII/keyword prohibida) en el
  *draft* original → preseleccionar **Doctrina/Seguridad**.
- Si ninguna de las anteriores → preseleccionar **Contenido** (comportamiento
  actual, conservador).

Si el owner no responde en la ventana de sesión (mismo TTL que
`doctrine_scope_keyboard`), se aplica el default preseleccionado — nunca
bloquea la entrega de la corrección. El botón es *metadata adicional*, no un
gate de la corrección misma.

### 4.3 Matemática del decremento

```python
DEFAULT_TRUST_BUDGET_DECREMENT_BY_SEVERITY = {
    "minor":    0.08,   # < 0.20 actual — corrige más rápido, castiga menos
    "moderate": 0.20,   # == actual, sin cambios
    "major":    0.35,   # > 0.20 actual — un incumplimiento real cuesta más
}
```

`record_correction(turn_id, *, severity="moderate")` y
`record_outcome(turn_id, event="label", value="desacuerdo", *, severity="moderate")`
reciben el nivel resuelto en `admin_service._correct_core` y aplican
`self._decrement_by_severity[severity]` en vez del escalar único.

**Invariante extendida (reemplaza la de L129 en `trust_budget_service.py`):**
la validación de asimetría en `apply_overrides` debe cumplirse para **cada
tier**, no solo para el valor agregado:

```
decrement["minor"] > increment   (el mínimo castigo sigue pesando más que el premio)
decrement["major"] >= decrement["moderate"] >= decrement["minor"]
```

Si cualquiera de las dos falla, se rechaza el `config` completo (mismo patrón
"todo o nada" que ya usa `apply_overrides` hoy, L129-134) — nunca se acepta
una configuración parcialmente inválida.

### 4.4 Cambios de esquema (mínimos, aditivos)

- `turn_outcome_log` (ya es "el ledger del círculo de aprendizaje", Fila 4):
  agregar columna `correction_severity: str | None` — nullable, no rompe
  filas existentes.
- `TurnOutcomeLogRecord` (ports.py L698-723): agregar
  `correction_severity: str | None = None`.
- **No se toca** `VipTrustBudgetStore` — sigue recibiendo un `delta: float`
  ya resuelto; la severidad se decide *antes* de llegar al store, en el
  service. Esto mantiene el store "tonto" (solo aplica deltas atómicos), que
  es como está diseñado hoy.
- Ficha del VIP (EA-06, sección "Confianza"): agregar desglose
  `minor_count / moderate_count / major_count` junto al `trend` que ya existe
  en `list_for_ficha` — visibilidad para el owner de *por qué* subió o bajó
  el score, no solo que bajó.

### 4.5 Rollout (mismo patrón "shadow → activo" que el resto del proyecto)

Esto sigue exactamente el patrón que ya usa Fase 2 (fast-lane fático shadow)
y Fase 5 misma (trust budget shadow antes de autoenvío real):

1. **Shadow (2-4 semanas):** se agrega el botón de severidad y se loguea
   `correction_severity` + el decremento *que se habría aplicado* junto al
   decremento real (que sigue siendo 0.20 fijo). No se cambia ningún
   `trust_score` real todavía. Objetivo: medir la distribución real de
   `minor/moderate/major` — si el owner casi siempre marca "Contenido", la
   ganancia de este spec es marginal y no vale la complejidad.
2. **Activación manual vía `system_config`:** una vez validada la
   distribución, activar `decrement_by_severity` vía `apply_overrides` (el
   único punto de mutación manual, igual que hoy) — feature flag propio
   (p. ej. `FEATURE_SEVERITY_TRUST_DECREMENT`), apagable sin tocar código.
3. **Criterio de salida (igual formato que §5.3 del spec original):** el
   sistema puede operar semanas con severidad activa sin que la categoría
   `major` quede sub-representada de forma sospechosa (owner evitando marcarla
   por pereza) ni sobre-representada (marcándola por defecto sin pensar) —
   señal de que la etiqueta se está usando con criterio real antes de confiar
   en ella para abrir autonomía en categorías nuevas.

---

## 5. Riesgos y mitigaciones

| Riesgo | Mitigación en este diseño |
|---|---|
| El owner sub-declara `major` por prisa (corrige rápido, no piensa en la etiqueta) | Prefill determinista (§4.2) hace que los casos con señal estructural (zona gris, safety gate, doctrine bajo) ya vengan preseleccionados en `major` — el owner tiene que *bajar* la gravedad activamente, no subirla |
| El owner sobre-declara `major` para "castigar más" al sistema, distorsionando el trust score | El decremento `major` (0.35) sigue clampeado a `[0,1]`; y la fase shadow (§4.5.1) permite detectar este patrón (distribución anómala) antes de activar en vivo |
| Complejidad nueva en un módulo diseñado para ser puro y simple | El cambio es aditivo y con default `moderate=0.20` — el caso no-etiquetado es idéntico al comportamiento actual; no hay regresión posible si el flag está apagado |
| Un LLM termina clasificando gravedad "para ayudar" en una iteración futura | Este spec fija explícitamente que la etiqueta es de *origen humano* (owner) con prefill *determinista* — cualquier extensión a clasificación por LLM requeriría su propio spec y pasaría, como mínimo, por shadow + revisión, nunca escritura directa (mismo principio que ya rige todo el resto del sistema, §2) |
| Fricción del tap extra en cada corrección reduce la tasa de corrección (el owner corrige menos) | El botón no bloquea el envío de la corrección (§4.2) — la corrección se aplica igual aunque no se etiquete; el tap es estrictamente adicional |

---

## 6. Fuera de alcance (explícitamente, para esta iteración)

- **No se toca el lado del incremento** (`+0.05` por turno autónomo sin
  corrección). El owner solo pidió proporcionalidad en el castigo. Aplicar
  gravedad también al premio (p. ej. más puntos por acertar en categorías de
  mayor riesgo) es una extensión natural pero es una decisión de producto
  aparte — no viene gratis con este spec.
- **No se cambia la regla dura EA-03** (`sensitive` nunca autónoma). La
  severidad de la corrección no afecta ese gate — sigue siendo binario por
  diseño, y debe seguir siéndolo.
- **No se automatiza la clasificación vía LLM** (§2, §5) — queda fuera de
  alcance por diseño, no por limitación técnica.

---

## 7. Preguntas abiertas para el owner

1. ¿Los valores `0.08 / 0.20 / 0.35` son razonables, o prefiere fijarlos
   después de ver la distribución real en la fase shadow?
2. ¿El botón de severidad debe ser obligatorio (bloquea envío) o
   estrictamente opcional como se propone aquí? (Se recomienda opcional para
   no introducir fricción en el flujo de corrección, que hoy es rápido.)
3. ¿Vale la pena, en una fase posterior, dejar que el owner reclasifique
   una corrección ya hecha (p. ej. desde la ficha del VIP) si al ver el
   patrón repetido se da cuenta de que subestimó la gravedad?
