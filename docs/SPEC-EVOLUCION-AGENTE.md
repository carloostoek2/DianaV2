# Spec de implementación — Evolución de agente (DianaV2) — v1.2

**Objetivo:** llevar a Diana de "bot con memoria consultada" a "agente con perfil evolutivo, autonomía calibrada por confianza, y personalidad con textura (mood)".

**Principio guía en todas las fases:** cada pieza nueva debe poder activarse/desactivarse por feature flag, igual que el resto del proyecto, y debe dejar traza auditable (siguiendo el patrón de `AdminTraceService`). Nada se libera sin poder revertirse.

**Lección incorporada (revisión 2026-08-06):** los umbrales de seguridad y confianza son constantes fijas (con override manual vía `system_config`), **nunca auto-calibrados por LLM**. El incidente de calibración (safety_min calibrado a 0.95 por correcciones → escalaciones masivas) es el precedente que prohíbe recalibración automática de gates de seguridad/confianza.

---

## Decisiones de diseño aprobadas (v1.2)

| ID | Decisión | Alcance |
|---|---|---|
| **EA-01** | El trust budget es la **fuente única de la decisión conductual** por (VIP, categoría); el `AutonomousModeService` existente queda como infraestructura (master switch + umbrales de evaluación). Autoenvío = **doble puerta**: `trust_score(categoría) >= umbral` **Y** evaluación del turno >= mínimos del Decider. El trust budget se actualiza solo por eventos (correcciones/autónomos), **jamás** por la calibración LLM. | Fase 5 |
| **EA-02** | El carril rápido conserva **3 filtros baratos** (sin pipeline completo): (1) clasificador seguro de fático, (2) sin trigger del middleware forbidden, (3) chequeo de seguridad del borrador generado — si el texto resulta sensible, cae a aprobación normal. | Fase 2 |
| **EA-03** | Categoría `sensitive` = **regla dura**: siempre aprobación del owner, nunca autónoma, sin importar el trust_score. | Fase 2 |
| **EA-04** | `feedback_signals`: **proxy por categoría de turno** (correcciones en turnos fático/emocional = señales de tono/personalidad; en informativos = de contenido) + el LLM de síntesis **filtra la relevancia** (recibe la corrección completa y decide). Sin esquema extra de clasificación en v1. | Fase 1 |
| **EA-05** | **Anti-contaminación** (invariante + test): el perfil (`stable_traits`/`sensitivities`) jamás alimenta el banco de ejemplos ni el retriever de examples; solo `recent_trend` y el mood entran al contexto de generación. Test estilo scans de anti-contaminación de la F5. | Fase 1 |
| **EA-06** | UI admin: **secciones en la ficha existente del VIP** (perfil + historial de versiones + confianza por categoría), secciones colapsables. No se crean comandos nuevos (`/perfil`, `/confianza`). | Fase 1 y 5 |

---

## Fase 0 — Fundaciones de datos (prerequisito de todo lo demás)

Antes de tocar comportamiento, se necesita esquema nuevo. Sin esto, las fases 1-5 no tienen dónde vivir.

**Nuevas entidades (migraciones Alembic 024+ — el head actual es 023):**

- `vip_profile` — perfil sintetizado por VIP. Columnas: `vip_id`, `stable_traits` (jsonb), `recent_trend` (jsonb), `sensitivities` (jsonb), `version`, `last_synthesized_at`, `synthesis_trigger` (enum: volume/session_close/strong_signal/emotional_signal).
- `vip_profile_history` — snapshot de cada versión anterior (para auditar drift). Columnas: `vip_id`, `version`, `profile_snapshot` (jsonb), `diff_summary` (texto corto generado por el LLM), `created_at`.
- `vip_mood_state` — estado de mood actual por VIP. Columnas: `vip_id`, `axis_playful_serious` (float -1..1), `axis_warm_distant` (float -1..1), `axis_energy` (float -1..1), `updated_at`.
- `vip_trust_budget` — presupuesto de confianza por VIP y por categoría de turno. Columnas: `vip_id`, `turn_category`, `trust_score` (float 0..1), `correction_count`, `autonomous_count`, `last_correction_at`.
- `turn_category_log` — clasificación de cada turno entrante (fático/informativo/emocional/sensible), para alimentar trust budget y decisiones futuras.
- `emotional_signal_log` — señal emocional por turno (ver componente transversal).

**Cambios a servicios existentes:**

- `memory_extraction_service`: sigue igual, sigue produciendo hechos episódicos. No se toca su contrato de salida (la Fase 4 añade un campo aditivo opcional, compatible hacia atrás).
- Nuevo repo `vip_profile_repository` (siguiendo el patrón de los repos en `infrastructure/`).
- **Retención de datos:** `vip_profile_history`, `turn_category_log` y `emotional_signal_log` crecen sin límite; definir política de purga (mismo patrón que `TracePurgeJob`, con retención por tabla).

**Criterio de salida de la fase:** migraciones aplicadas, repos con tests unitarios (fakes, sin DB), sin ningún cambio de comportamiento visible aún para el usuario.

---

## Componente transversal — Detector de quiebre emocional

No es una fase con criterio de salida propio: es un servicio que las Fases 1, 2 y 5 consumen desde el día uno. Se especifica aquí, junto a las fundaciones, porque debe existir antes de que esas fases se conecten entre sí.

### Dónde vive

`emotional_signal_detector` — corre **por turno**, **antes del carril rápido de la Fase 2** (mismo paso que el clasificador de turno 2.1, no dentro de la cadena del Director). Reusa la salida del `analyst` (emotion, urgency, risk, intent, topics) — **heurística v1, sin llamada LLM por turno**. Un refinamiento con LLM puede venir en un pool posterior, flag-gated.

**Tabla nueva (Fase 0):** `emotional_signal_log` — columnas: `vip_id`, `turn_id`, `signal_type`, `intensity`, `should_trigger_synthesis`, `should_escalate_to_owner`, `pipeline_would_have_escalated` (bool **nullable**: NULL para turnos que no pasaron por el Decider — carril rápido; la comparación aplica solo a pipeline completo), `created_at`.

### Output

```json
{
  "signal_detected": true,
  "signal_type": "vulnerabilidad | angustia | revelacion_de_vida | ruptura_de_patron",
  "intensity": 0.0-1.0,
  "should_trigger_synthesis": true,
  "should_escalate_to_owner": true
}
```

**Nota de diseño:** el set de tipos es cerrado y **no incluye "escalada"** — la escalación es una decisión del pipeline (Decider), no una señal emocional. El mapeo heurístico en v1:

| Señal | Fuente (salida del analyst) |
|---|---|
| `vulnerabilidad` | emotion en {triste, ansiosa} + intent de apertura personal |
| `angustia` | emotion en {ansiosa, molesta, triste} + urgency alta + risk medio/alto |
| `revelacion_de_vida` | topics en {honestidad, tema_pesado, extrañar, reencuentro, conexion} u otro patrón de revelación |
| `ruptura_de_patron` | comparación con baseline: alguien distante que se abre, o cálido que se enfría |

Tipos con manejo distinto:

- **Revelación de vida** → sobre todo dispara síntesis (memoria); no necesariamente escalación.
- **Angustia/crisis** → saca el turno del carril rápido (reclasificación a emocional/sensible → aprobación del owner). Para turnos de pipeline completo, en v1 es **shadow-only** (se loguea; la escalación forzada del Decider es un flag futuro).
- **Ruptura de patrón** → señal sutil pero valiosa para el perfil; no la captura una extracción de hechos simple. **Dependencia:** requiere un baseline — en Fase 0/1 temprana usa un **baseline rodante de emociones** (últimos N turnos por chat); cuando exista el perfil (Fase 1), usa `recent_trend` como baseline.

### Puntos de integración

**1. Con Fase 1 (síntesis de memoria):** si `should_trigger_synthesis` es true, se encola `profile_synthesis_job` de inmediato, sin esperar el umbral de volumen ni el cierre de sesión. Sustituye/complementa el trigger `strong_signal` mencionado en 1.1.

**2. Con Fase 2 (autonomía fática):** actúa como segunda pasada de seguridad sobre la clasificación de turno. Si un turno se clasificó como `phatic` pero el detector marca señal con intensidad relevante, se **reclasifica** antes de que el carril rápido lo tome — evita que algo como "qué haces... es que no sé si contarte algo" se trate como saludo trivial.

**3. Con Fase 5 (trust budget):** cuando `should_escalate_to_owner` es true pero `pipeline_would_have_escalated` resulta false (el Decider normal no lo habría marcado), es la señal más valiosa para afinar umbrales del `EvaluationProfile` — indica un punto ciego del pipeline principal. Se loguea explícitamente para revisión periódica (sección en la ficha del VIP, EA-06), no solo para acción inmediata.

### Calibración de umbrales (asimétrica, por diseño)

`should_escalate_to_owner` debe tener un umbral de intensidad notablemente más alto que `should_trigger_synthesis`. Justificación: una síntesis de más es barata y de bajo riesgo; una escalación de más satura de alertas al owner y erosiona la confianza en el sistema de avisos. Mejor pecar de generoso disparando síntesis y conservador escalando.

**Los umbrales son constantes fijas con override manual por `system_config` — nunca auto-calibrados por LLM (lección del incidente de calibración).**

**Orden de construcción:** este componente se implementa junto con Fase 0, antes de conectar Fase 1 y Fase 2, ya que ambas lo dan por existente desde su diseño.

---

## Fase 1 — Ciclo de resíntesis de memoria

### 1.1 Disparadores

Nuevo componente `profile_synthesis_trigger_service` que evalúa tras cada turno (barato, sin llamar LLM) si se debe encolar resíntesis:

```
si (mensajes_desde_ultima_sintesis >= UMBRAL_VOLUMEN)
   O (inactividad_detectada Y hubo_actividad_en_sesion)
   O (senal_fuerte_detectada)          # reutiliza heurística tipo j4_triggers
   O (detector.should_trigger_synthesis)  # señal emocional (componente transversal)
entonces encolar profile_synthesis_job(vip_id, trigger_type)
```

Esto se integra como un hook al final de `turn_orchestrator` (patrón `_maybe_post_turn`), no como un job de cron adicional — la detección de "cierre de sesión" necesita saber que *ya no hay* actividad, así que sí conviene un job periódico ligero (cada 15-30 min) que revise VIPs con última actividad hace >X minutos y sin resíntesis pendiente marcada.

### 1.2 El job de síntesis (`profile_synthesis_job`)

**Patrón de capas:** el job periódico **envuelve un servicio de aplicación** (`ProfileSynthesisService`), siguiendo el patrón `CalibrationJob → CalibrationService` — el AGENTS.md prohíbe que los jobs ejecuten lógica directamente.

Input al LLM (3 bloques, explícitos, no mezclados en un solo prompt difuso):

1. `current_profile` (json: stable_traits, recent_trend, sensitivities, version).
2. `new_episodic_facts` (lista de hechos crudos desde `last_synthesized_at`).
3. `feedback_signals` (EA-04: correcciones de turnos fático/emocional desde la última síntesis, con su texto completo — el LLM filtra cuáles son de tono/personalidad vs. contenido puntual).

**Output esperado, estructurado (JSON forzado, como ya se hace en otros puntos del pipeline):**

```json
{
  "stable_traits": { ... },
  "recent_trend": { ... },
  "sensitivities": [ {"trait": "...", "weight": 0.0-1.0, "evidence_count": n} ],
  "changes_summary": "texto corto: qué cambió y por qué",
  "confidence": 0.0-1.0
}
```

El campo `confidence` es clave: si el LLM reporta baja confianza (pocos hechos nuevos, señales contradictorias), el job **no sobrescribe** — solo actualiza `recent_trend` y deja `stable_traits`/`sensitivities` intactos. Esto evita drift por ruido.

### 1.3 Decaimiento

No necesita ser un proceso separado — se resuelve dentro del mismo prompt de síntesis, dándole al LLM la antigüedad de cada sensitivity/trait existente y pidiéndole explícitamente que baje el peso (`weight`) de lo que no se reforzó en los `new_episodic_facts`, y que lo remueva de `sensitivities` (no de `stable_traits`) si el peso cae bajo un umbral.

### 1.4 Versionado y auditoría

Cada corrida exitosa: guarda el profile anterior completo en `vip_profile_history`, incrementa `version`, guarda `changes_summary` como diff legible. **El owner audita desde la ficha del VIP** (EA-06: sección "Perfil" con historial de versiones), no con comando nuevo.

**Anti-contaminación (EA-05):** invariante con test — `stable_traits`/`sensitivities` jamás entran al banco de ejemplos ni al retriever de examples; solo `recent_trend` (y mood, Fase 3) alimentan el contexto de generación.

**Criterio de salida de la fase:** por cada VIP con suficiente historial, existe un `vip_profile` que se actualiza solo, con al menos 2-3 ciclos de síntesis corridos en modo sombra (se genera pero no se usa aún en generación de respuesta) para validar calidad antes de conectarlo al pipeline de generación.

---

## Fase 2 — Autonomía fática (saludos, small talk)

### 2.1 Clasificador de turno

Nuevo paso ligero al inicio del pipeline cognitivo (antes o junto al `analyst`): clasifica el turno entrante en una de las categorías (`phatic`, `informational`, `emotional`, `sensitive`). Puede ser heurística + LLM barato — no necesita las 7 dimensiones completas del `EvaluationProfile`.

**Orden:** clasificador → detector de quiebre emocional (reclasifica si hay señal) → carril rápido (si sigue fático) o pipeline completo.

Esto se guarda en `turn_category_log` (fase 0) para alimentar trust budget más adelante.

### 2.2 Carril rápido

Si `turn_category == phatic` (tras la segunda pasada del detector) **y** el flag `feature_phatic_autonomy` está activo **y** `vip_trust_budget` para esa categoría/VIP supera el umbral mínimo (arranca conservador, ej. 0.9, casi nadie fuera si aún no hay historial) **y** pasan los 3 filtros de EA-02:

1. Clasificador seguro (sin ambigüedad).
2. Sin trigger del middleware forbidden.
3. Chequeo de seguridad del borrador generado — si es sensible, cae a aprobación normal.

En el carril rápido:

- Se salta el pipeline completo de evaluación de 7 dimensiones.
- Se genera la respuesta usando: turno actual + `vip_mood_state` (fase 3, si ya existe) + `recent_trend` del perfil (fase 1).
- Se envía sin pasar por aprobación del owner.
- Se registra en `turn_category_log` como autónomo, para trazabilidad.

**EA-03 (regla dura):** la categoría `sensitive` nunca entra al carril rápido ni a autonomía — siempre aprobación del owner, sin importar el trust_score.

**Importante:** el clasificador debe tener un modo "no estoy seguro" — si hay ambigüedad entre fático y algo con más carga (ej. "qué haces" seguido de algo emocional en el mismo mensaje), cae al pipeline normal. Mejor pecar de conservador aquí.

**Criterio de salida de la fase:** medir en producción (modo shadow primero: clasifica y registra qué habría hecho, sin autoenviar) qué % de turnos fáticos se clasifican bien, antes de activar autoenvío real.

---

## Fase 3 — Motor de mood

### 3.1 Estado

`vip_mood_state` (fase 0) con 3 ejes. Se actualiza, no se recalcula desde cero: `nuevo_valor = valor_actual * (1 - tasa_retorno) + señal_del_turno * peso_señal`, con un pequeño ruido acotado. Esto da el "promedio móvil con retorno a la base" que discutimos.

### 3.2 Señal del turno

Un paso barato (heurística + sentiment ligero, no necesita LLM completo) que estima, por turno, hacia dónde empuja cada eje. **Reusa la salida del `analyst` del pipeline cognitivo** (emotion: neutral/positiva/ansiosa/molesta/triste/cariñosa/urgente) — mapeo emotion → ejes. Evitar duplicar llamadas al LLM.

### 3.3 Conexión con generación

El mood **no genera texto nuevo**: se pasa como parámetro de selección/matiz a `draft_variants.py`. Concretamente:

- Cada variante generada se etiqueta con un tono dominante usando el `emotion` del analyst correspondiente (o el de la variante si se regenera) — **sin llamada LLM adicional**.
- El mood decide cuál variante se privilegia por distancia: mapeo de ejes de mood → tono preferido (juguetón/serio, cálido/distante), y se selecciona la variante cuya etiqueta queda más cerca.
- En v1 basta etiquetar la variante con el `emotion`/razón del Decider ya disponible en `_draft_versions` (campo `reason`).

**Criterio de salida de la fase:** correr en shadow (calcular mood, loguearlo, no usarlo en selección real) por un tiempo para validar que los ejes se mueven de forma razonable y no erráticamente, antes de conectarlo a la selección de variantes.

---

## Fase 4 — Iniciativa contextual

(Menor prioridad según lo discutido — se deja especificado brevemente para cuando se llegue.)

Extiende el job de `recontact` existente: en vez de disparar solo por tiempo de inactividad, consulta `vip_profile.recent_trend` y hechos episódicos recientes marcados como "pendiente de seguimiento". **El flag es un campo aditivo opcional en el contrato de `memory_extraction_service`** (ej. `follow_up: "evento_futuro" | "problema_sin_resolver" | null`) — compatible hacia atrás, no rompe el contrato existente. El job de recontact prioriza estos sobre el simple "ha pasado tiempo".

---

## Fase 5 — Presupuesto de confianza para autonomía

### 5.1 Cálculo de `trust_score` (EA-01)

Por `(vip_id, turn_category)`: arranca en un valor bajo por defecto. Sube gradualmente con cada turno autónomo sin corrección del owner; baja de forma más agresiva (no simétrica) con cada corrección — el castigo por error debe pesar más que el premio por acierto, para que el sistema sea conservador por diseño.

```
si autonomo_sin_correccion: trust_score += incremento_pequeño
si owner_corrige: trust_score -= decremento_mayor; correction_count += 1
```

**Relación con el modo autónomo existente (EA-01):** el trust budget **reemplaza la habilitación global por VIP** del `AutonomousModeService` como fuente de la decisión conductual. El AMS queda como infraestructura (master switch `feature_autonomous_mode` + umbrales de evaluación). La decisión de autoenvío es doble puerta:

```
autoenviar = (trust_score[categoria] >= umbral) AND (evaluacion del turno >= minimos del Decider)
```

El trust budget se actualiza **solo por eventos** (correcciones / autónomos sin corrección) — la calibración LLM de umbrales **jamás** lo toca.

### 5.2 Uso del `EvaluationProfile` como señal adicional

Para turnos que sí pasan por el pipeline completo (no fáticos), antes de considerar autoenvío en fases futuras más allá de fático: mirar dispersión entre las 7 dimensiones del `EvaluationProfile`, no solo su resultado agregado. Alta dispersión (dimensiones en desacuerdo) → tratar como baja confianza aunque el score final parezca "seguro", y no autoenviar aunque el trust_score general sea alto.

### 5.3 Reportes al owner

**Sección "Confianza" en la ficha del VIP** (EA-06): trust_score por categoría, tendencia reciente, y últimas correcciones — para que el owner vea el "presupuesto" y decida si abrir más categorías a autonomía manualmente, en vez de que sea 100% automático desde el día uno.

**Criterio de salida de la fase:** el sistema puede operar semanas con autonomía fática real sin que el trust_score de ninguna categoría se degrade de forma sostenida — señal de que el presupuesto está calibrado antes de considerar abrir categorías de mayor riesgo.

---

## Orden de ejecución recomendado

```
Fase 0 (fundaciones)
   +
Detector de quiebre emocional (transversal, se construye junto a Fase 0)
   ↓
Fase 1 (memoria) ──┐
                    ├─→ Fase 3 (mood, en shadow)
Fase 2 (autonomía   │
fática, en shadow) ─┘
   ↓
Fase 5 (trust budget, activo desde que fase 2 sale de shadow)
   ↓
Fase 4 (iniciativa contextual)
```

Fase 1 y Fase 2 pueden desarrollarse en paralelo (no dependen entre sí para *construirse*), pero Fase 2 no debería salir de modo shadow hasta que Fase 1 tenga al menos `recent_trend` confiable, porque la calidad de la autonomía fática depende de tener contexto de perfil, no solo del turno aislado.

---

## Decisiones confirmadas (2026-08-06)

1. **Detector heurístico v1** — sin costo LLM por turno: mapeo de la salida del analyst (emotion/urgency/risk/intent/topics) a las señales. Un detector con LLM propio queda como pool posterior flag-gated, solo si el v1 resulta ruidoso.
2. **Escalación del detector en v1 = shadow-only** — se loguea y compara (`pipeline_would_have_escalated`), no fuerza al Decider. Forzar escalación es un flag futuro, previo a activar autoenvío de la Fase 2.
3. **Umbrales iniciales del detector**: `should_trigger_synthesis` >= 0.5, `should_escalate_to_owner` >= 0.8 — constantes fijas, override manual por `system_config`, nunca auto-calibrados.
