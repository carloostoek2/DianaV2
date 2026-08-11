---
title: Pipeline Cognitivo
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [arquitectura, flujo]
sources: [../../docs/REQUERIMIENTOS.md, ../../docs/SPEC-1.1.md]
confidence: high
---

# Pipeline Cognitivo

Conjunto de procesos cognitivos especializados que colaboran para tomar una **decisión conversacional**. El sistema no es un chatbot: la inteligencia emerge de la colaboración de componentes, cada uno con una sola pregunta (REQ-NFR-13).

## Flujo canónico (turno VIP normal, REQ-COG-01)

```
Mensaje → Director → Comprensión (Analista) → Planificación → Recuperación
(vía Capability Registry) → Construcción de Contexto → Generación → Evaluación
→ Decisión → Behavior Engine (Entrega) → Aprendizaje (post-turno)
```

## Componentes y su única pregunta

| Componente | Pregunta | Naturaleza |
|---|---|---|
| [[director-cognitivo]] | ¿Qué necesita este turno? | 100 % código |
| Analista | ¿Qué está pasando? | LLM → Comprensión |
| Planificador | ¿Qué recuperar? | Determinista |
| Recuperadores | ¿Qué sabemos sobre X? | Especializados, interfaz idéntica |
| Constructor de Contexto | ¿Contexto mínimo necesario? | Composición dinámica |
| Generador | ¿Cómo respondería la dueña? | LLM, solo redacta |
| Evaluador | ¿Debemos confiar? | Perfil multidimensional |
| [[decisor]] | ¿Qué acción tomar? | Reglas sobre vector + modo |
| [[behavior-engine]] | ¿Cómo se actúa el mensaje? | Infraestructura, fuera de la cognición |
| Aprendizaje | ¿Qué aprendimos? | Siempre post-turno |

## Variantes del pipeline

- **Turno VIP normal:** completo.
- **Sandbox:** completo, solo el Behavior Engine es FakeDelivery.
- **Recontacto por silencio:** reducido (sin Analista ni Planificador; recupera memoria + políticas).
- **Escalación por palabra prohibida:** cortocircuito determinístico antes del Analista.

## Objeto de Comprensión

Salida estructurada del Analista que es el **lenguaje interno** del sistema: `intent`, `topics`, `emotion`, `urgency`, `risk` y flags `needs_*` por tipo de conocimiento. Todo lo demás depende de él.

^[docs/REQUERIMIENTOS.md §3.2-3.5, docs/SPEC-1.1.md §2]
