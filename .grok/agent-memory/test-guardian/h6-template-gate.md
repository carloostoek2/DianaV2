# Test-Guardian Report: h6-template-gate

**Date:** 2026-07-27  
**Item:** h6-template-gate — deterministic TemplateGate (saludo + deteccion_ia)  
**Commits:** `7674aa6`, `ce6ab78`, `e19865f`, `d6221f7`  
**Sources:** PLAN.md, SUMMARY.md, CLARIFY.md, arch-enforcer/h6-template-gate.md  

**Verdict:** suite protege adecuadamente

## Coverage Audit

### H6.6 acceptance matrix

| # | Case | Coverage | File / test |
|---|------|----------|-------------|
| 1 | `"Hola"` → `plantilla_saludo`, draft ∈ pool, 0 Analyst/Gen/Eval | **PASS** | `test_template_gate::test_saludo_matches_*`; `test_director::test_h6_short_hola_template_approve_skips_pipeline` (spies + `llm.calls == []` + trace decision-only) |
| 2 | Long hola (5+ words) → full pipeline | **PASS** | pure gate reject + `test_h6_long_hola_does_not_template_runs_pipeline` |
| 3 | `"eres una ia?"` → exact IA draft | **PASS** | pure render + `test_h6_ia_probe_template_exact_draft` |
| 4 | Template Decision `approve` only (no send/escalate) | **PASS** | `test_h6_template_decision_never_send_or_escalate` (Hola / IA / mixed) |
| 5 | persona JSON no `(ver J.2 / examples)` | **PASS** | `test_persona_reglas_estilo_no_j2_examples_note` |

### PLAN regressions

| Case | Coverage | Evidence |
|------|----------|----------|
| Middleware pago silent escalate | **PASS** | `test_j4_pago_stops_pipeline` |
| Middleware compromiso silent escalate | **PASS** (classifier + shared MW branch) | `test_compromiso_hit` + same `if j4 is not None` path as pago; no dedicated MW test (see residual note) |
| Middleware pure IA → handler | **PASS** | `test_j4_ia_passes_to_handler` (no deliver, no escalate) |
| Mixed `"hola eres una ia"` → `plantilla_deteccion_ia` | **PASS** | pure `test_rule_order_deteccion_ia_beats_saludo_on_mixed_short`; director asserts approve for mixed |
| Hybrid IA+pago → pago | **PASS** | `test_hybrid_ia_pago_escalates_as_pago` |
| Pure IA classify → None | **PASS** | `test_pure_ia_returns_none` |
| Default `template_gate=None` no false-fire | **PASS** | `test_h6_default_gate_none_does_not_false_fire_hola_diana` |
| Composition IA-first wiring | **PASS** | `test_composition_template_gate_wired` |
| Cognitive purity | **PASS** | `test_import_purity` + template_gate stdlib-only |
| Approve orch path (no TO edits) | **PASS** | `test_turn_orchestrator.py` full suite green |
| Dead helper still unit-covered | **PASS** | `test_deterministic_escalate.py` (planned residual keep) |

### Gaps in DoD

**None.** No new tests written by this guardian pass.

### Out-of-DoD / residual (not blocking)

1. No dedicated **middleware-level** `compromiso_real` short-circuit test (pago covers the shared branch; classifier has compromiso positives).
2. Director mixed-text case asserts `action==approve` but not `reason==plantilla_deteccion_ia` (pure gate already locks order/reason).
3. Keyword coverage shrink vs former `IDENTIDAD_IA_KEYWORDS` (PLAN residual M1).
4. Dead `handle_deterministic_template_escalate` + `behavior=` (arch residual; unit tests intentionally kept).

## Mock Audit

| Archivo | Mock / patch | Clasificación | Path de negocio | Acción |
|---------|--------------|---------------|-----------------|--------|
| `test_director.py` H6.6.1 | `FakeLLM` | **PERMITIDO** | borde LLM externo | ninguna |
| `test_director.py` H6.6.1 | `AsyncMock/MagicMock(side_effect=real_method)` on analyst/planner/generator/evaluator/decider | **PERMITIDO** (spy) | verifica que pipeline **no** se invoca; no sustituye lógica del gate | ninguna |
| `test_director.py` H6.* | real `TemplateGate` injected via `make_director(..., template_gate=...)` | **N/A real** | match/render + Decision path | ninguna |
| `test_template_gate.py` | ninguno | — | pure unit | ninguna |
| `test_j4_triggers.py` | ninguno | — | pure classify | ninguna |
| `test_forbidden_mw.py` | `AsyncMock` as next `handler` | **PERMITIDO** | borde handler Telegram | ninguna |
| `test_forbidden_mw.py` IA test | real `BehaviorEngine` + `FakeTelegramActuator` | **PERMITIDO** | borde entrega; assert send_count==0 | ninguna |
| `test_composition_wiring.py` | source-text asserts (no runtime mocks) | — | wiring static | ninguna |
| `test_deterministic_escalate.py` | (legacy helper; out of critical path) | legacy | dead IA helper residual | documentado |

**Resumen mocks:** 6 permitidos en scope del ítem, **0 prohibidos**.  
**Confianza de realidad:** **alta** — pure TemplateGate real; Director con gate real + spies solo para assert_not_called; middleware con Behavior real/FakeActuator; classify sin mocks.

## Re-run Results

```bash
# Critical matrix (this guardian)
pytest -q tests/unit/cognitive/test_template_gate.py \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/application/test_j4_triggers.py \
  tests/unit/application/test_deterministic_escalate.py \
  tests/unit/telegram/test_forbidden_mw.py \
  tests/unit/test_composition_wiring.py \
  tests/unit/application/test_turn_orchestrator.py -v
# → 155 passed in 5.72s

# PLAN full safety net
pytest -q tests/unit/cognitive tests/unit/telegram \
  tests/unit/application/test_j4_triggers.py \
  tests/unit/application/test_deterministic_escalate.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/application/test_admin_service.py \
  tests/unit/test_composition_wiring.py
# → 723 passed in 12.26s
```

## Pre-existing vs Attributable

- **0 failures** in critical or safety-net suites.
- **0 regressions attributable** to h6-template-gate.
- Dead-path helper tests still green (intentional keep per PLAN).

## Handoff

**Listo para cierre / paso 6 (tests finales / commit gate).**

- No volver a executor por tests/mocks.
- No tests nuevos en este pass (DoD ya cubierto por commits del executor).
- Residuals carry-forward (not item inflation): keyword expand, shared matcher, dead helper cleanup, ANEXO-H H6.4 doc, optional MW compromiso dedicated test, optional director mixed-reason assert.

## Gate checklist

- [x] Veredicto positivo
- [x] Tests del ítem presentes (executor TDD) y verdes
- [x] Mock Audit: 0 prohibidos en scope
- [x] H6.6 + J.4 pago/compromiso + purity + composition re-run OK
