---
title: LLM Provider
created: 2026-08-11
updated: 2026-08-24
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
- **Secundario:** Anthropic (Claude) — respaldo de diseño, **no implementado**.

## Reglas

- El Cognitive Core depende de la interfaz, no del proveedor concreto.
- Los prompts de negocio viven en el Constructor de Contexto ([[pipeline-cognitivo]]), no en el provider.
- Generación estructurada (Pydantic v2) para objetos como la Comprensión y el [[perfil-evaluacion-multidimensional]].

## Implementación real (2026-08-11, actualizado 2026-08-24)

`llm/` sigue con **2** archivos: `deepseek.py` (cliente OpenAI-compatible vía httpx, solo I/O) y `fake.py` (FakeLLM scriptable para tests). **Solo DeepSeek está implementado** — no hay cliente Anthropic en el árbol.

Toggle de thinking (landed 2026-08-09, omitido en el inventario del 11): `DeepSeekProvider(thinking_enabled=...)` cableado a `settings.llm_thinking_enabled` (default `True`).

- `generate` (borradores de texto libre): con thinking on envía `"thinking": {"type": "enabled"}` y `"reasoning_effort": "low"`; timeout mínimo 120 s y `max_tokens` default 4096 (si no, 1024). Si CoT agota el presupuesto (`content` vacío + `finish_reason=length` + hubo `reasoning_content`), reintenta una vez con la misma config y, si falla igual, un tercer intento con thinking **OFF**. Callers con `max_tokens < 512` (p. ej. recontacto) fuerzan thinking off (sin effort ni ladder). Nunca usa `reasoning_content` como draft.
- `generate_structured` (Analista / Evaluador y demás JSON): **siempre** `"thinking": {"type": "disabled"}`, sin `reasoning_effort`, independiente del flag — el CoT puede agotar tokens y dejar `content` vacío.

^[src/diana/llm/*, src/diana/config/settings.py, docs/SPEC-1.1.md §1]
