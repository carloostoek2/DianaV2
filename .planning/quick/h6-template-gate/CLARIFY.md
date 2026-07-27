# SCOPE CLARIFICATION (--clarify)

- **Fecha/run:** 2026-07-27T07:39Z
- **Fuente:** `--spec docs/ANEXO-H.md` (H6) + código vivo (J.4, Director, Decision)
- **Effort:** 4 (review loop: 5 slots)
- **Pool slug:** `h6-template-gate`

## GRAY AREAS MAP (resuelto)

- **Petición interpretada como:** Nuevo gate determinista pre-pipeline en Cognitive Core: plantillas fijas para saludo corto y “¿eres una IA?”, `Decision.action=approve` → cola de dueña; cero LLM; no middleware de escalación silenciosa.
- **Ya decidido por el anexo (no re-preguntar):**
  - No va en `ForbiddenKeywordsMiddleware` (H6.1).
  - Componente puro `cognitive/template_gate.py` (H6.2).
  - Reglas concretas saludo (`max_words=4`) + deteccion_ia (texto exacto) (H6.3).
  - Integración en `CognitiveDirector.handle_turn` antes del pipeline (H6.4).
  - No tocar `TurnOrchestrator` (approve path existente) (H6.4).
  - Limpieza de `reglas_estilo` (quitar `(ver J.2 / examples)`) — path real: `src/diana/config/persona_diana.json` (no yaml).
  - Verificación H6.6 (5 casos de test).

## Decisiones bloqueadas

| Tema | Decisión del usuario |
|------|----------------------|
| **J.4 `identidad_ia` vs H6 `deteccion_ia`** | **Migrar IA a H6.** Sacar `identidad_ia` del short-circuit de middleware J.4 (incl. `handle_deterministic_template_escalate` para esa categoría). Solo `TemplateGate` en Director → `action=approve` + cola. Frase exacta: `jsjsj si y sólo vivo en tu mente 😏`. **J.4 `pago_precio` y `compromiso_real` siguen en middleware.** |
| **Prioridad de reglas** | **`deteccion_ia` primero, luego `saludo_constante`.** Mensajes mixtos cortos tipo “hola eres una ia” ganan detección de IA. |
| **`Decision.evaluation`** | **Synthetic evaluation** reutilizando patrón H4 (`_early_exit_evaluation()` / zero profile). **No** hacer `evaluation` opcional. `reason` = `plantilla_saludo` \| `plantilla_deteccion_ia` es la fuente de verdad. |
| **Path de producto** | Supervisado: template → approve → dueña ve borrador en cola / `/traza`. **No** auto-deliver al VIP. **No** escalación silenciosa en paralelo (un turno por mensaje). |
| **Artefacto de config** | Spec menciona `persona_diana.yaml`; repo usa **`persona_diana.json`** — la limpieza H6.6.5 va sobre el JSON real. |

## Fuera de scope (explícito)

- Cambiar comportamiento de J.4 `pago_precio` / `compromiso_real`.
- Auto-send en modo autónomo para plantillas (siempre approve; F.4 / anexo).
- Feature flag nueva (no pedida; gate es determinista core, no Fase 3 flageable salvo residual).
- Ampliar pool de saludo o keywords más allá del anexo (salvo ajustes mínimos de wiring).
- Reintroducir auto-deliver de template IA al VIP.
- Refactors ajenos (BehaviorEngine, Learning, Decider matrix).

## Assumptions (gris menor documentado)

- Reusar `_kw_hit` / `match_keywords` de `application` desde cognitive: preferir import de la función pura de match sin acoplar a Telegram; si hay conflicto de capas, extraer matcher a módulo neutral o duplicar la lógica mínima en template_gate (planner elige el que respete AGENTS.md).
- Status del turno en template path: no hay ANALYZING obligatorio; almacenar `decision` y devolver (como early-exit H4 post-analyst, pero pre-analyst). Si el status sink espera transición, planner decide mínima (posible residual).
- Tests J.4 `identidad_ia` existentes se **actualizan/eliminan** según migración (middleware ya no short-circuita IA).
- Constantes de keywords: hardcode en composition o factory junto a `TemplateGate` (como rules del anexo), no system_config salvo residual.

## Deferred

- Ampliar `response_pool` de saludo.
- Calibrar `max_words` por telemetría.
- Unificar matcher keyword en un solo módulo “shared pure” si el impact-analyzer lo marca frágil.

## Restricciones para agentes

- **impact-analyzer:** Mapear consumidores de J.4 `identidad_ia`, `handle_deterministic_template_escalate`, `IA_TEMPLATE`, Director `handle_turn`, composition wiring, tests forbidden/j4/director. No-touch: TurnOrchestrator approve branch (solo verificar compatibilidad).
- **gsd-planner:** PLAN debe materializar: TemplateGate + orden deteccion_ia→saludo + Director pre-pipeline + synthetic eval + **migración J.4 sin identidad_ia** + cleanup persona JSON + tests H6.6. DoD medible.
- **gsd-executor:** Implementar solo PLAN; commits atómicos; Strict TDD del proyecto; English code/comments; no re-abrir decisiones.
- **arch-enforcer:** Cognitive puro (sin telegram/behavior); Director determinista; Learning no en path; un turno; Decisor no tocado para templates (bypass pre-Decider OK como H4/H6).
- **test-guardian:** Cobertura H6.6 + regresión J.4 pago/compromiso intactos + middleware IA ya no deliver+escalate + mocks LLM assert_not_called en path plantilla.

## Decisiones bloqueadas (lista corta para prompts)

1. Migrar `identidad_ia` de J.4 middleware → TemplateGate Director (approve).
2. Orden reglas: `deteccion_ia` → `saludo_constante`.
3. `evaluation` sintético H4; no Optional.
4. Limpieza `persona_diana.json` reglas_estilo.
5. No tocar TurnOrchestrator (approve path).
