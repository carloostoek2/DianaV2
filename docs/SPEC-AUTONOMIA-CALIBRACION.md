# SPEC-AUTONOMIA-CALIBRACION.md — Camino a la autonomía (diseño aprobado)

**Versión:** 1.0 · **Fecha:** 2026-08-22 · **Estado:** DISEÑO aprobado por producto — no implementado.
**Relacionado con:** `SPEC-EVOLUCION-AGENTE.md` v1.2 (medición sombra), `SPEC-FASE3.md` §4.8 (modo autónomo), `AGENTS.md` §3–§4 (contratos).
**Nomenclatura:** esta fase se denomina **Fila 4 — Camino a la autonomía** en `docs/ESTADO-PROYECTO.md`.

---

## 1. Propósito

Convertir la medición del modo sombra en un **ciclo de aprendizaje con decisión**:
que la dueña tenga, en una sola vista, la evidencia para decidir **si activa y cuándo
activa el envío autónomo**, y que el sistema **aprenda de cada turno real** para que
el resultado del modo sombra cambie con el tiempo.

El modo sombra actual responde "¿habría enviado o no?". Este diseño agrega la
pregunta que falta: **"¿habría acertado?"** — y cierra el círculo para que la
siguiente simulación sea mejor que la anterior.

---

## 2. Decisiones de producto (aprobadas 2026-08-22)

| Decisión | Valor |
| --- | --- |
| Desbloqueo | **Gradual, por VIP** (un VIP a la vez; nunca global de golpe) |
| Umbral de confianza para recomendar | **0.90** por (VIP, categoría) |
| Tasa de coincidencia mínima | **95 %** en ventana de **2 semanas** |
| Escalaciones por seguridad en la ventana | **0** toleradas para recomendar |
| Evaluación de resultados | **Heurísticas, sin LLM** (ver §6) |
| La decisión final | **Siempre de la dueña** (el sistema solo recomienda) |

---

## 3. Principios no negociables

1. **La dueña decide; el sistema recomienda.** La activación es un botón por VIP,
   nunca un cambio automático de comportamiento.
2. **El lazo de evaluación es heurístico y determinista** — sin LLM calificando
   resultados (evita sesgo de auto-calificación y costo). Consistente con el
   detector emocional, el clasificador de turno y el motor de ánimo.
3. **El aprendizaje es post-turno** (regla AGENTS.md §1.4): todo se escribe después
   de que el turno termina, nunca durante el pipeline.
4. **Anti-contaminación total**: las señales de esta fase nunca alimentan la memoria
   del VIP ni el banco de ejemplos.
5. **El Decisor sigue intacto**: esta fase mide y recomienda; no altera la matriz de
   decisión ni las prioridades de seguridad.
6. **Supervisión antes que autonomía**: una corrección pesa mucho más que un acierto
   (asimetría conservadora existente: +0.05 / −0.20).

---

## 4. El círculo de aprendizaje (flujo funcional)

```
Turno real (VIP escribe)
   → Pipeline completo (como hoy, supervisado)
   → Decisor real decide (approve/escalate/...)
   → Dueña actúa: aprueba igual / corrige / escala
        │
        ▼  (post-turno, siempre)
┌─────────────────────────────────────────────────────────┐
│ 1. SIMULACIÓN: el Decisor re-evalúa el turno guardado    │
│    con autonomía ON → veredicto "habría enviado/no"      │
│ 2. COMPARACIÓN (C1): veredicto vs decisión real de la    │
│    dueña → acierto / desacuerdo / conservadora           │
│ 3. CALIDAD (C2): heurística puntúa el borrador sombra y  │
│    el mensaje real enviado → delta de calidad            │
│ 4. RESULTADO (C3): la reacción del VIP (su siguiente     │
│    mensaje) pasa por el detector emocional → señal        │
│ 5. AJUSTE: señales 2–4 actualizan la confianza del VIP   │
│    y las métricas globales (coincidencia, cuellos)       │
└─────────────────────────────────────────────────────────┘
        │
        ▼
La próxima simulación usa la confianza actualizada → el resultado cambia.
```

**Clave del diseño:** el veredicto sombra deja de ser estático. La confianza por
VIP crece con aciertos y señales positivas del VIP, y cae fuerte con correcciones
o señales negativas. Por eso el panel muestra evolución, no una foto.

---

## 5. Componentes

### C1 — Motor de coincidencia (comparativa estrella)
Compara, por turno terminado, el veredicto de la simulación con lo que hizo la
dueña en la realidad:

| Simulación dijo | Dueña hizo | Etiqueta |
| --- | --- | --- |
| ✅ habría enviado | aprobó sin cambios | **acierto** |
| ✅ habría enviado | corrigió o escaló | **desacuerdo** |
| ❌ no habría enviado | aprobó | **conservadora** |

- Métricas: tasa de coincidencia = aciertos / (aciertos + desacuerdos); lista de
  **desacuerdos** (los casos de oro: qué corrigió la dueña que la simulación
  habría mandado mal).
- Fuente: veredicto recomputable de `pipeline_traces` (ya implementado en el modo
  sombra) + desenlace real del turno (status + candidatas de staging).

### C2 — Heurística de calidad de texto (H1)
Puntúa, sin LLM, **ambos textos** (borrador sombra y mensaje realmente enviado)
con las mismas reglas, 0–1:

- longitud adecuada · pregunta o apertura de cierre · uso del nombre del VIP ·
  léxico cálido/positivo · naturalidad coloquial · **seguridad** (si toca palabra
  prohibida o dato sensible → 0).

- Producto: **delta de calidad** = score(enviado) − score(borrador sombra).
  Cuando la dueña corrige, el delta mide el aporte de su corrección; la tendencia
  del delta (debe bajar con el tiempo) es la señal de aprendizaje.

### C3 — Señal de resultado post-envío (H2, Fila 4 ítem 2)
Cuando un mensaje se entrega, la reacción del VIP califica el resultado:

- Los siguientes mensajes del VIP (ventana corta) pasan por el **detector
  emocional existente** (heurístico) + una polaridad ligera (positiva/neutra/
  negativa) con léxico fijo.
- Positiva → refuerza confianza; negativa/molesta → resta (asimetría); silencio
  → neutro o leve negativo.
- **Sin LLM**: el cliente califica, no la IA.

### C4 — Cola durable de síntesis (Fila 4 ítem 1)
Persistir el guardián de síntesis de perfiles (hoy en memoria) para que el
aprendizaje sobreviva reinicios. Infraestructura de la capa de aprendizaje.

### C5 — Panel "🧭 Camino a la autonomía"
Vista única (sección del menú de la dueña, junto al modo sombra):

- **Preparación global**: coincidencia (vs 95 %), correcciones/semana con
  tendencia, cuellos por dimensión (p. ej. doctrina 0.70 vs 0.80).
- **Comparativas**: aciertos/desacuerdos/conservadora; lista de desacuerdos con
  borrador vs corrección; evolución semanal de la confianza por VIP.
- **Por VIP**: quién está listo (✅) y a quién le falta cuánto (⏳).
- **Recomendación**: botón de activación por VIP cuando se cumplen las 3
  condiciones de §8.

### C6 — Puerta de recomendación y activación por VIP
- Condiciones (las tres a la vez): confianza ≥ 0.90 · coincidencia global ≥ 95 %
  en 2 semanas · cero escalaciones por seguridad en la ventana.
- El botón activa `vips.auto_send` del VIP (ya existe) → la doble puerta de
  autonomía existente (L1 `FEATURE_AUTONOMOUS_MODE` + L2 `auto_send`) gobierna el
  envío real. La activación por VIP **sigue respetando el kill-switch maestro**.

---

## 6. Por qué heurísticas y no LLM en la evaluación (decisión razonada)

1. **Evita el sesgo de auto-calificación**: un LLM calificando su propio texto
   tiende a la benevolencia; las reglas fijas son imparciales y consistentes.
2. **Consistencia semanal**: las condiciones (95 %, ventana 2 semanas) miden
   tendencias agregadas — las heurísticas, aunque superficiales por turno, son
   estables en agregado, que es lo que la puerta necesita.
3. **Costo cero y determinismo**: sin llamadas extra al modelo, todo resultado
   es reconstruible a partir de los textos guardados.
4. **Coherencia con el sistema**: detector emocional, clasificador de turno,
   señales fuertes y motor de ánimo ya son heurísticos.
5. **El juicio de resultado lo aporta el VIP**, vía su reacción medida por el
   detector emocional — la pieza que ninguna heurística de texto puede suplir.

---

## 7. Modelo de datos propuesto

- **Nueva tabla `turn_outcome_log`** (migración **030**, pendiente de implementar):
  `id`, `turn_id` (único), `vip_id`, `shadow_verdict` (send/blocked/escalate/
  doctrine), `owner_outcome` (approved_as_is/corrected/escalated),
  `draft_score`, `sent_score`, `quality_delta`, `vip_signal` (positive/neutral/
  negative/silence | None), `created_at`.
- Escrita **post-turno** (regla de aprendizaje post-turno), nunca en el pipeline.
- Alimenta las métricas del panel y el ajuste de confianza (TrustBudgetService
  gana un evento `record_outcome`, heurístico).
- **Anti-contaminación**: esta tabla no alimenta `memories`, `examples` ni
  `vip_profile`; solo métricas de calibración.

---

## 8. Umbrales y condiciones de activación (aprobados)

| Condición | Valor |
| --- | --- |
| Confianza del VIP (categoría) | ≥ 0.90 |
| Tasa de coincidencia global | ≥ 95 % (ventana 2 semanas) |
| Escalaciones por seguridad en ventana | 0 |
| Asimetría de aprendizaje | +0.05 acierto / −0.20 corrección (existente) |

---

## 9. Fases de implementación (orden recomendado)

1. **Fase A — C1 Motor de coincidencia + comparativas en el panel** (datos ya
   existentes; sin migración inicial si se computa al vuelo).
2. **Fase B — C2 heurística de calidad + C3 señal post-envío + migración 030**
   (el círculo de aprendizaje completo).
3. **Fase C — C4 cola durable de síntesis.**
4. **Fase D — C6 puerta de recomendación + botón por VIP** (sigue apagado el
   kill-switch maestro hasta que la dueña lo decida).

Cada fase con su feature flag (`FEATURE_AUTONOMY_READINESS_ENABLED` y derivados,
default `false`), tests y doc. Al implementar cada flujo se actualizará `AGENTS.md`
§3 con la etiqueta correspondiente (regla §8 de AGENTS.md).

---

## 10. Cumplimiento AGENTS.md (verificación al implementar)

- Director determinista: la capa nueva no toca el Director ni el Decisor.
- Un componente, una pregunta: C1 compara, C2 puntúa textos, C3 lee reacción,
  C6 recomienda — sin mezclar.
- Learning post-turno: todos los escritos son post-turno.
- Anti-contaminación memoria ↔ ejemplos: `turn_outcome_log` es métrica pura.
- Feature flags: toda la capa nace detrás de flags en `false`.
- El Behavior Engine sigue siendo el único que envía; la recomendación nunca
  envía por su cuenta.

---

## 11. Pendientes a definir antes de la Fase D

- Texto y límite de la ventana de reacción del VIP (horas) para C3.
- Lexicones exactos de H1/H2 (se definen en la fase B con ejemplos reales).
- Presentación final del panel (maqueta en Telegram, 3–4 pantallas).

---

*Fin de SPEC-AUTONOMIA-CALIBRACION.md v1.0 — diseño aprobado por producto, pendiente de implementación por fases.*
