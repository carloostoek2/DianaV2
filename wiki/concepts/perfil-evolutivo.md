---
title: Perfil Evolutivo
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [memoria, aprendizaje, decision]
sources: [../../docs/SPEC-EVOLUCION-AGENTE.md]
confidence: high
---

# Perfil Evolutivo

El perfil sintetizado del VIP que evoluciona solo (Fase 1 de la evolución de agente). Va más allá de la memoria episódica ([[memoria-vip]]): compila **rasgos estables, tendencia reciente y sensibilidades** con versionado y auditoría.

- Tablas (migraciones 024+): `vip_profile` (stable_traits, recent_trend, sensitivities, version, synthesis_trigger) y `vip_profile_history` (snapshots con diff_summary).

## Estructura del output de síntesis (JSON forzado)

```json
{
  "stable_traits": { ... },
  "recent_trend": { ... },
  "sensitivities": [ {"trait": "...", "weight": 0.0-1.0, "evidence_count": n} ],
  "changes_summary": "qué cambió y por qué",
  "confidence": 0.0-1.0
}
```

El campo `confidence` es clave: con baja confianza (pocos hechos nuevos, señales contradictorias) el job **no sobrescribe** — solo actualiza `recent_trend` y deja `stable_traits`/`sensitivities` intactos (anti-drift por ruido).

## Ciclo de resíntesis

1. **Disparadores** (`profile_synthesis_trigger_service`, barato, sin LLM): umbral de volumen de mensajes, inactividad tras sesión activa, señal fuerte, o `detector.should_trigger_synthesis` (ver [[detector-emocional]]).
2. **Job** (`profile_synthesis_job` → envuelve `ProfileSynthesisService`; los jobs no ejecutan lógica): input al LLM en 3 bloques explícitos — perfil actual + hechos episódicos nuevos + `feedback_signals` (EA-04: correcciones de turnos fático/emocional con texto completo; el LLM filtra tono/personalidad vs. contenido).
3. **Decaimiento:** dentro del mismo prompt, con antigüedad de cada trait/sensitivity; baja el `weight` de lo no reforzado y lo remueve de `sensitivities` (no de `stable_traits`) bajo umbral.
4. **Versionado:** guarda el perfil anterior en `vip_profile_history`, incrementa `version`, `changes_summary` como diff legible. El owner audita desde la ficha del VIP (EA-06).

## Reglas duras

- **EA-05 (anti-contaminación):** `stable_traits`/`sensitivities` jamás entran al banco de ejemplos ni al retriever de examples; **solo `recent_trend` (y mood) alimentan el contexto de generación**. Test estilo scans de anti-contaminación.
- Los umbrales de síntesis se calibran de forma asimétrica: generoso para sintetizar, conservador para escalar.
- La Fase 2 (autonomía fática) no sale de shadow hasta que `recent_trend` sea confiable (la calidad de la autonomía depende del contexto de perfil).

## Motor de mood (Fase 3)

`vip_mood_state` con 3 ejes (juguetón-serio, cálido-distante, energía): promedio móvil con retorno a la base (`nuevo = actual*(1-tasa_retorno) + señal*peso` + ruido acotado). El mood **no genera texto**: matiza la selección de variantes en `draft_variants.py` por distancia entre ejes y tono etiquetado de cada variante. Corre en shadow hasta validar que los ejes se mueven razonablemente.

Relacionado: [[trust-budget]], [[spec-evolucion-agente]], [[memoria-vip]].

^[docs/SPEC-EVOLUCION-AGENTE.md §Fase 1, §Fase 3]
