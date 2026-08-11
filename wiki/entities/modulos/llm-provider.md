---
title: LLM Provider
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [modulo, decision]
sources: [../../AGENTS.md, ../../docs/SPEC-1.1.md]
confidence: high
---

# LLM Provider

Abstracción de proveedores de modelo de lenguaje (ADR-006). Interfaz abstracta con **hot-swap** (REQ-ADM-03): cambiar proveedor/modelo en caliente sin tocar el resto del sistema.

- **Pregunta que responde:** ¿Cómo hablo con el modelo?
- **Puede:** `generate` y `generate_structured`.
- **Nunca puede:** contener prompts de negocio, decidir umbrales, conocer VIP.

## Proveedores

- **Primario:** DeepSeek (LLM principal del sistema).
- **Secundario:** Anthropic (Claude) — respaldo configurable.

## Reglas

- El Cognitive Core depende de la interfaz, no del proveedor concreto.
- Los prompts de negocio viven en el Constructor de Contexto ([[pipeline-cognitivo]]), no en el provider.
- Generación estructurada (Pydantic v2) para objetos como la Comprensión y el [[perfil-evaluacion-multidimensional]].

## Implementación real (2026-08)

`llm/` tiene 2 archivos: `deepseek.py` (cliente OpenAI-compatible vía httpx, solo I/O) y `fake.py` (FakeLLM scriptable para tests). **Solo DeepSeek está implementado** — Anthropic queda como respaldo de diseño no implementado. La generación estructurada (Pydantic) alimenta Comprensión y perfil de evaluación.

^[src/diana/llm/*, docs/SPEC-1.1.md §1]
