---
title: Comunicación con Producto
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [contrato, regla-negocio]
sources: [../../AGENTS.md]
confidence: high
---

# Comunicación con Producto

Regla obligatoria de AGENTS.md §0: el interlocutor del chat **no es un desarrollador** — es el **dueño o dueña de producto**. Toda comunicación agente ↔ usuario usa nivel técnico medio-bajo, lenguaje claro y práctico.

## Principios

- Hablar de **qué pasa en el producto, qué gana o pierde el negocio, qué control tiene la dueña, qué hay que decidir**.
- Frases cortas y orientadas a la decisión o al resultado.
- Conceptos técnicos inevitables → traducir a impacto de producto (ej. no "middleware fail-closed": "si no podemos confirmar el estado, por seguridad no mandamos el mensaje").
- Preguntas en lenguaje de negocio/producto, no de implementación.
- Ante error/bloqueo: qué falló en la práctica, qué se puede hacer ahora, y si hace falta una decisión de la dueña.

## Autocomprobación antes de enviar (AGENTS.md §0.5)

1. ¿Lo entendería alguien que maneja el producto pero no programa?
2. ¿Queda claro el impacto en VIP / dueña / control / riesgo?
3. ¿La pregunta se puede responder sin saber de código?
4. Si usé un término técnico, ¿lo traduje al efecto práctico?

## Idioma (AGENTS.md §0.6)

Todo texto de producto — UI, prompts, seeds, mensajes al VIP, specs — se escribe en **español neutro (variante mexicana/neutra)**. Regla de acción inmediata: cualquier texto que no sea español neutro encontrado en código, docs, prompts, seeds o DB se corrige en el mismo instante a neutro.

## Qué NO cambia esta regla

El código, tests, commits y docs técnicos siguen en la convención del artefacto (inglés en código por defecto). Los límites de módulo y flujos canónicos siguen siendo de cumplimiento estricto.

^[AGENTS.md §0]
