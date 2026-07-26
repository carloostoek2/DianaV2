# SUMMARY — item2-deterministic-escalation

**Status:** COMPLETE  
**Date:** 2026-07-26  
**Pool:** system-prompt-struct  
**Item:** ITEM 2 — deterministic-escalation-path (H3–H5 + J.4)

## Objective

Ship deterministic hard-escalation paths so VIP turns that hit frustration, repeated intents, payment/commitment keywords, or “¿eres IA?” never reach Generator/Evaluator (and textual J.4 never enters Director).

## Tasks completed

| Task | Result | Commit |
|------|--------|--------|
| 1. H3 Decider `frustracion_directa` | Done | `2159c20` `feat(decider): escalate on emotion molesta (H3)` |
| 2a. Pure `RepetitionGuard` | Done | `281f104` `feat(cognitive): add pure RepetitionGuard for H4` |
| 2b. Port + SqlTraceStore + Director early-exit | Done | `89274fd` `feat(cognitive): H4 pregunta_repetida early-exit Decision-only` |
| 3. J.4 triggers + typed escalate + middleware | Done | `c4a5e92` `feat(application): J.4 triggers and typed deterministic escalate` |
| 4. H5 composition wiring | Done | `c3d67da` `feat(composition): wire repetition guard and j4 escalate path` |

## What landed (truths T1–T10)

- **H3:** `emotion=="molesta"` → `escalate` / `frustracion_directa` after gray zone, before risk_high.
- **H4:** `RepetitionGuard(3)` + `RecentIntentsPort` / `SqlTraceStore.get_recent_intents` + Director Decision-only early-exit `pregunta_repetida` (post-comprehension, pre-Planner). No EscalationStore/Notifier in cognitive.
- **J.4:** Pre-Director catalogs in `application/j4_triggers.py`; middleware order identidad_ia → pago_precio → compromiso_real → forbidden; IA template exact `jsjsj si y sólo vivo en tu mente 😏` via `handle_deterministic_template_escalate`.
- **H5:** Composition injects `recent_intents=traces`, `RepetitionGuard(threshold=3)`; middleware gets `behavior` for IA deliver.

## Deviations

- None material. PLAN suggested optional SQL unit for `get_recent_intents`; covered via Director + InMemoryRecentIntents (no DB fixture).
- Local `BehaviorDeliverer` protocol also defined in `deterministic_escalate.py` (duplicate of `application.ports.BehaviorDeliverer`) — residual cleanup only.

## Verifications

```text
# Item2 bundle
182 passed

# Unit regression (embedding env ignored)
1139 passed  (tests/unit --ignore=tests/unit/cognitive/test_embedding.py)
```

Primary commands:

```bash
pytest tests/unit/cognitive/test_decider.py \
  tests/unit/cognitive/test_repetition_guard.py \
  tests/unit/cognitive/test_director.py \
  tests/unit/cognitive/test_import_purity.py \
  tests/unit/application/test_j4_triggers.py \
  tests/unit/application/test_deterministic_escalate.py \
  tests/unit/telegram/test_forbidden_mw.py \
  tests/unit/test_composition_wiring.py \
  tests/unit/application/test_turn_orchestrator.py \
  tests/unit/acceptance/test_tac_mvp_f1.py -q
```

## Architecture invariants held

- Director 100% deterministic; Decision-only early exit
- Decider pure (no I/O); matrix order: safety → gray → frustracion → risk → autonomous
- Cognitive: zero EscalationStore / OwnerNotifier / application / telegram / behavior imports
- Learning still post-turn only (incomplete TRACE_KEYS on H4 exit accepted per A4)
- No FEATURE_* flags added
- No-touch: evaluator, generator, turn_coordinator, examples retriever

## Residuals

| título | clase_sugerida | por_qué | archivos |
|--------|----------------|---------|----------|
| Alembic index `(chat_id, created_at DESC)` on `pipeline_traces` | out-of-scope | Volume low; PLAN residual | `alembic/`, `pipeline_traces` |
| Owner-facing Spanish copy polish for new `tipo`/reasons | out-of-scope | Product copy | notifier payloads |
| Fuzzy J.4 / admin-editable keyword lists | out-of-scope | Explicit non-goal | j4 catalogs |
| Compromiso short-token FPs (`cita`/`encuentro`/`nos vemos`) | wontfix / accepted | Anexo J.4 fidelity; further tighten raises FN risk | `j4_triggers.py` |

### Resolved during hardener fix rounds

| Residual | Resolution | Commit |
|----------|------------|--------|
| AGENTS.md Decider table row for frustracion 2b | Documented priority 2b + justification | `bacf7fe` |
| Dedicated unit for `SqlTraceStore.get_recent_intents` | Unit tests added | `07cc653` |
| Deduplicate `BehaviorDeliverer` protocol | Import from `application.ports` only | fix R1 |
| Decision.evaluation required on H4 early exit | Fresh zeroed `EvaluationProfile` sentinel | `694dc7d` |

## Self-Check: PASSED

- [x] Todas las tareas completadas
- [x] Tests del PLAN corridos
- [x] 0 regresiones atribuibles
- [x] Convenciones del proyecto respetadas


## Hardener review fix rounds

**Effort:** 4  

### Round 1

**Review HARD_ID:** `d1064c49`  
**Issues:** 10 fixed, 0 wontfix  
**Highlights (from gsd log + commits):** soft IA deliver fail still escalates; expand pago/IA phrases + tighten compromiso; Auth before Forbidden + VIP gate on J.4; `SqlTraceStore.get_recent_intents` unit; fresh zero EvaluationProfile on H4 exit; AGENTS 2b docs.  
**Tests after R1:** 197 passed (item2+fix pack)  
**Commits:** `dbdca09`, `5a3e5ca`, `80321c1`, `07cc653`, `694dc7d`, `bacf7fe`

### Round 2

**Issues:** 5 fixed, 1 wontfix, **0 open**  
**Fixed:** pago FNs (pagué/pagó/factura/descuento/cuánto te sale/currency tokens); hybrid IA+pago motivo; IA phrases (sos humano / eres una ai); template free-form documented + empty fallback; `is_frozen` pass-through (stack already drops frozen VIP).  
**Wontfix:** compromiso short tokens `cita`/`encuentro`/`nos vemos` — Anexo product terms (accepted FP residual).  
**Commit:** `e6ad357` `fix(application): J.4 pago FNs, hybrid IA+pago motivo, IA phrases`  
**Tests after R2:** 203 passed  
**Artifact:** `.grok/agent-memory/review/system-prompt-struct-item2.md`

## Review loop (effort 4)

- **Rounds:** 2 (fix → re-review → fix residual → clean)
- **Issues closed:** R1 10 fixed; R2 5 fixed + 1 wontfix; final **0 open**
- **Review fix commits:** `dbdca09` … `e6ad357` (see table above)
- **VIP gate + Auth→Forbidden order preserved; cognitive purity unchanged**

## Next

→ Pool close / documentador (arch-enforcer + test-guardian + review 0 open already done).
