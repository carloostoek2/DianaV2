# Arch Audit: h6-template-gate

**Date:** 2026-07-27  
**Item:** h6-template-gate — deterministic TemplateGate (saludo + deteccion_ia)  
**Commits:** `7674aa6`, `ce6ab78`, `e19865f`, `d6221f7`  
**Sources:** PLAN.md, SUMMARY.md, CLARIFY.md, AGENTS.md, live sources  

**Verdict:** PASS WITH NOTES  
**Critical violations:** 0

---

## Findings

### Critical (must fix before advance)

_None._

### Medium

1. **Dead production path retained (planned residual M2 / SUMMARY #3)**  
   - `handle_deterministic_template_escalate` remains + unit tests for `identidad_ia`.  
   - `ForbiddenKeywordsMiddleware` still accepts `behavior=` and `telegram/setup.py` still wires `behavior=behavior`.  
   - **Not a layer break** — IA branch removed from middleware; pago/compromiso never call deliver.  
   - **Fix (follow-up):** delete dead helper + drop unused `behavior` from Forbidden ctor/setup when safe.

2. **Keyword coverage shrink (planned residual M1)**  
   - Annex `deteccion_ia` triggers are narrower than former `IDENTIDAD_IA_KEYWORDS` (`sos *`, `chatgpt`, `humano`, …).  
   - Pure non-annex IA probes now hit full LLM pipeline (no middleware, no template).  
   - **Accepted by CLARIFY/PLAN** — product residual, not architecture violation.

### Observations

1. **Local `_kw_hit` duplicates `match_keywords`** — intentional purity fix (cognitive must not import `diana.application`). Shared pure matcher deferred (SUMMARY residual #2).

2. **Composition imports `IA_TEMPLATE` from application** — allowed: composition root may import all layers. Cognitive stays free of application imports (verified via `test_import_purity` FORBIDDEN_PREFIXES + AST scan of `cognitive/`).

3. **Template path skips status transitions to ANALYZING** — matches PLAN A5 / H6 pre-pipeline; only stores `decision`. Orchestrator still receives `Decision` and runs approve branch → `PENDING_APPROVAL` + `send_draft_for_approval`.

4. **Stale comment/doc residue (non-blocking):**  
   - `tests/unit/test_composition_wiring.py::test_setup_forbidden_middleware_receives_behavior` docstring still says “behavior for IA template path”.  
   - `J4Hit` docstring still mentions “when identidad_ia wins”.  
   - ANEXO-H H6.4 still shows `evaluation=None` (CLARIFY overrides with synthetic zeros).

5. **Default `template_gate=None` in unit `make_director`** — correct mitigation for fixture text `"hola Diana"`; production composition always injects gate.

---

## Architecture compliance (focus areas)

| Invariant | Result | Evidence |
|-----------|--------|----------|
| Cognitive purity (no telegram/behavior/application) | **PASS** | `template_gate.py` stdlib-only + local `_kw_hit`; `director.py` imports only cognitive; `test_import_purity` forbids `diana.application` / telegram / behavior / learning |
| Director remains deterministic | **PASS** | Template match is ordered rules + keyword hit; no LLM; `_handle_template` builds fixed `Decision` |
| Template path pre-pipeline OK | **PASS** | `handle_turn` checks gate before `_run_pipeline`; Analyst/Planner/Generator/Evaluator/Decider not called on match (spies + `llm.calls == []`) |
| Learning not on decision path | **PASS** | Template path only `_store(decision)`; no Learning import/call in cognitive; TO learning remains post-turn |
| One-turn invariant (no dual escalate+approve) | **PASS** | Template always `action="approve"` only; middleware no longer deliver+escalate for IA; hybrid IA+pago → pago escalate only (classifier never returns `identidad_ia`) |
| J.4 pago/compromiso still middleware | **PASS** | `classify_j4_text` priority pago → compromiso; Forbidden short-circuits those only |
| `identidad_ia` migrated off middleware | **PASS** | IA branch deleted from `forbidden.py`; pure IA → handler; TemplateGate supervised approve |
| No TO / Decider / BehaviorEngine / Learning functional edits | **PASS** | SUMMARY no-touch list; TO approve path still `PENDING_APPROVAL` + draft (no deliver); decider/behavior/learning/Alembic not in change set |
| Scope of PLAN respected | **PASS** | Files match PLAN file map; 4 atomic conventional commits |
| Supervised only (no auto-send) | **PASS** | Template Decision never `send`/`escalate`; Decider matrix untouched |

---

## Layer map (post-change)

```
Telegram ForbiddenMW
  → J.4 pago/compromiso / forbidden keywords → silent escalate (unchanged)
  → pure IA / short saludo → handler → TurnCoordinator → TO → Director
       → TemplateGate.match (cognitive pure)
       → Decision(approve, plantilla_*, draft, synthetic eval)
       → TO approve branch → owner queue (no Behavior.deliver)
```

Composition root builds `TemplateGate(rules=[deteccion_ia, saludo_constante])` and injects into Director — correct layer for rule factory.

---

## Compliance Checklist

- [x] Capas respetadas (cognitive pure; composition wiring; middleware residual J.4 only)
- [x] Scope del PLAN respetado (no TO/Decider/Behavior/Learning/Alembic)
- [x] Director 100% determinista en path plantilla
- [x] Learning solo post-turno (no en TemplateGate / Director template path)
- [x] Un turno por mensaje (approve only; no dual escalate)
- [x] Decisor no tocado para templates (bypass pre-pipeline como H4/H6)
- [x] Behavior Engine no genera ni decide (IA auto-deliver removed)
- [x] Anti-pattern PLAN: no `from diana.application` en cognitive/
- [x] Anti-pattern PLAN: no `evaluation=None` (synthetic zeros)
- [x] Logging: no required new logs; optional noise correctly skipped
- [x] Tests reflect contracts H6.6.1–5 + J.4 regression + purity
- [ ] Dead helper / `behavior=` cleanup (explicit residual follow-up)
- [ ] Expand deteccion_ia keywords (product residual)

---

## Handoff

**Verdict gate:** PASS WITH NOTES · **0 critical** → advance to **test-guardian**.

Next step: `test-guardian` for H6.6 coverage + J.4 pago/compromiso regression + middleware IA pass-through + mock LLM assert_not_called on template path.

Do **not** return to gsd-executor for architecture fixes.

---

## Residuals (carry to SUMMARY / backlog)

1. Expand `deteccion_ia` toward former `IDENTIDAD_IA_KEYWORDS` (out-of-scope).  
2. Shared pure keyword matcher (out-of-scope).  
3. Remove dead `handle_deterministic_template_escalate` + Forbidden `behavior=` (in-scope-followup).  
4. ANEXO-H H6.4 docs: synthetic eval vs `None` (out-of-scope).  
5. Owner UI soften zero scores for `plantilla_*` (out-of-scope).  
6. Suite fixture text hygiene (`hola Diana`) (out-of-scope; mitigated).
