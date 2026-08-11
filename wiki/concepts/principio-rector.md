---
title: Principio Rector
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [arquitectura, decision]
sources: [../../docs/REQUERIMIENTOS.md, ../../docs/SPEC-1.1.md]
confidence: high
---

# Principio Rector

**El sistema no genera respuestas. El sistema toma decisiones. Las respuestas son únicamente una consecuencia de esas decisiones.**

Es la regla inamovible sobre la que se construye todo DianaV2 (SPEC-1.1 §0). El LLM es un razonador especializado dentro de un pipeline cognitivo, nunca el director del sistema.

## Obligaciones derivadas

- [[director-cognitivo]] es 100 % determinista: nunca pregunta a un LLM "¿qué hago?".
- Especialización: cada componente responde una sola pregunta ([[pipeline-cognitivo]]).
- Explicabilidad total: los objetos intermedios se persisten para reconstruir cualquier decisión.
- Sustituibilidad: vía [[capability-registry]], ningún componente conoce a otro concreto.
- Anti-contaminación: la Memoria de un VIP nunca se convierte en few-shot general ([[anti-contaminacion]]).

## Reglas de negocio que lo protegen

- BR-08: El Director nunca pregunta a un LLM "qué hacer". Solo orquesta.
- BR-09: No existe score único de confianza; el Decisor trabaja sobre el vector ([[perfil-evaluacion-multidimensional]]).
- BR-11: El aprendizaje ocurre siempre después del turno ([[aprendizaje-post-turno]]).

^[docs/REQUERIMIENTOS.md §3.11]
