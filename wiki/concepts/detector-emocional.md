---
title: Detector de Quiebre Emocional
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [modulo, riesgo, aprendizaje]
sources: [../../docs/SPEC-EVOLUCION-AGENTE.md]
confidence: high
---

# Detector de Quiebre Emocional

Componente transversal de la evolución de agente (v1.2). Detecta señales emocionales fuertes **por turno, sin llamada LLM** (heurística v1 sobre la salida del analyst) y alimenta síntesis de perfil, seguridad del carril rápido y calibración del pipeline.

- **Dónde vive:** `emotional_signal_detector` — corre antes del carril rápido de la Fase 2 (mismo paso que el clasificador de turno), no dentro de la cadena del Director.
- **Entrada:** salida del analyst (`emotion`, `urgency`, `risk`, `intent`, `topics`).
- **Tabla:** `emotional_signal_log` — `signal_type`, `intensity`, `should_trigger_synthesis`, `should_escalate_to_owner`, `pipeline_would_have_escalated` (bool nullable), `created_at`.

## Señales (set cerrado, sin "escalada" — eso es decisión del pipeline)

| Señal | Fuente heurística |
|---|---|
| `vulnerabilidad` | emotion ∈ {triste, ansiosa} + intent de apertura personal |
| `angustia` | emotion ∈ {ansiosa, molesta, triste} + urgency alta + risk medio/alto |
| `revelacion_de_vida` | topics ∈ {honestidad, tema_pesado, extrañar, reencuentro, conexion} |
| `ruptura_de_patron` | comparación con baseline (rodante al inicio; `recent_trend` del perfil cuando exista) |

## Umbrales (asimétricos, por diseño)

- `should_trigger_synthesis` >= **0.5** — síntesis de más es barata y de bajo riesgo.
- `should_escalate_to_owner` >= **0.8** — escalación de más satura al owner y erosiona confianza.

**Constantes fijas con override manual por `system_config` — nunca auto-calibradas por LLM** (lección del incidente de calibración, ver [[calibracion-de-umbrales]]).

## Comportamiento v1

- `angustia`/crisis → saca el turno del carril rápido (reclasifica a emocional/sensible → aprobación del owner).
- La escalación del detector es **shadow-only**: se loguea y compara (`pipeline_would_have_escalated`); no fuerza al Decider (flag futuro).
- Cuando `should_escalate_to_owner=true` pero `pipeline_would_have_escalated=false` → señal valiosa de punto ciego del pipeline; se loguea para revisión periódica en la ficha del VIP.

Relacionado: [[pipeline-cognitivo]], [[perfil-evolutivo]], [[escalacion]].

^[docs/SPEC-EVOLUCION-AGENTE.md — componente transversal]
