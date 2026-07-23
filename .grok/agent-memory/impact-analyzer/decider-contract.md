# Impact Analysis: Align Decider contract to Anexo F (`docs/contratos_restantes.md`)

**Date:** 2026-07-23  
**Change:** Align Decider runtime + Decision surface to Anexo F (F.1–F.5) under **F1 action lock**  
**Analysis only** — no implementación  
**Source of truth:** `/home/ubuntu/repos/DianaV2/docs/contratos_restantes.md` § Anexo F  
**F1 locks:** `AGENTS.md` product vision vs F1 runtime; `docs/MVP_COMPONENT_DESIGN.md` §5.11 / §13; `docs/SPEC-1.1.md` decisión abierta #1  
**Pattern reference:** prior contracts (analyst/evaluator/planner/context-builder/generator) + existing `test_decider.py` matrix locks

---

## Executive Summary

The Decider today is a pure, deterministic F1 matrix: `decide(evaluation, comprehension, *, mode="supervised") → Decision` with **no LLM**, no score collapse, and public actions restricted to **`approve | escalate`**. Rules in code:

1. `evaluation.safety < safety_threshold` (default **0.3**) → `escalate` / `safety_below_threshold`
2. `comprehension.risk == "alto"` → `escalate` / `risk_high`
3. else → `approve` / `ok_for_human_review`

Director is the sole production caller; it hardcodes `mode="supervised"` and attaches `draft_text` after decide. Composition wires `Decider()` with **defaults only** (does not load `system_config.eval_thresholds` even though the seed row and `SqlSystemConfigStore.get_eval_thresholds()` exist). TurnOrchestrator only branches on `approve` / `escalate` and fails closed on any other action.

Anexo F describes a fuller contract: input `{perfil, modo_activo, umbrales{seguridad_min, naturalidad_min}}`, output `{accion: aprobar|escalar|regenerar, razon, restriccion_de_modo_aplicada}`, and a fixed evaluation order where low naturalness yields **regenerate**, and the raw “send” path is rewritten to **approve** under supervised mode.

**Global risk: low–medium.** The runtime already implements the **F1-safe subset** of F.3 (safety escalate + supervised approve). The critical danger is **over-implementation**: expanding `Decision.action` to include `regenerate` / `send` / `consult_doctrine` would break orchestrator, models validation, TAC/acceptance assumptions, and every prior contract pool’s F1 lock. Sensitive systems: deterministic Director control flow (TAC-01), BR-09 vector integrity, F1 approval queue (no auto-send), module purity (cognitive must not import telegram/behavior).

**Scope is valid and tight** (effort ~2–3). No re-partition required. Prefer: **document regenerate (F.3 rule 2) as residual**, keep `approve|escalate` only, optionally tighten auditability (`mode_restriction_applied`) and threshold wiring without expanding the public action set.

---

## Gap verification (contract vs code)

| Gap | Contract (Anexo F) | Current code | Status |
|-----|--------------------|--------------|--------|
| F.1 single question | “¿qué acción tomar?”; no quality judge, no draft read | Matrix over profile dims + risk only; never reads draft text | **OK** |
| F.1 no LLM | Deterministic rules | Pure Python; `test_decider_source_has_no_mean_or_llm` | **OK** |
| F.2 DecisorInput | `{perfil, modo_activo, umbrales}` | Positional `evaluation`, `comprehension`, kw `mode`; thresholds on ctor | **PARTIAL** — optional DTO; `comprehension` is F1 extension (risk), not in pure F.2 |
| F.2 umbrales | `seguridad_min` + `naturalidad_min` | Only `safety` (default 0.3); no naturalness gate | **PARTIAL** — safety OK; naturalness = residual with regenerate |
| F.2 DecisorOutput acciones | `aprobar \| escalar \| regenerar` | Runtime `approve \| escalate` only (English) | **F1 LOCK** — map Spanish→English; **do not** expose regenerate |
| F.2 `restriccion_de_modo_aplicada` | set when mode rewrote raw action | Field **absent** on `Decision` | **CONFIRMED gap (optional F1)** |
| F.3 #1 safety | `seguridad < umbral` → escalar | Implemented (`safety` + threshold) | **OK** |
| F.3 #2 naturalness | `naturalidad < umbral` → regenerar (or fall to #3 if not implemented) | Not implemented | **RESIDUAL / out of scope** — document; fall-through = approve (rule 3) is F1-correct |
| F.3 #3 else | raw “enviar” → supervised → “aprobar” | Direct `approve` without intermediate “send” | **OK behaviorally**; audit field missing |
| F.3 risk=alto | Not in pure F table | Implemented as escalate | **F1 extension (keep)** — locked by MVP design + tests |
| F.4 no draft judgment | Only EvaluationProfile | Decider never sees draft; Director attaches draft after | **OK** |
| F.4 mode filter never skippable | supervised never yields raw send | mode ignored; never returns send | **OK** for F1 |
| F.5 example | safety 0.2 < 0.5 → escalate | Custom threshold test covers pattern | **OK** (default umbral is 0.3, not 0.5) |
| Composition thresholds | umbrales from deployment config | `Decider()` always default; `get_eval_thresholds` unused | **CONFIRMED gap (medium, optional)** |
| F1 Decision.action | approve\|escalate (prior pools) | Already restricted + model tests | **OK — do not expand** |

### Naming map (docs Spanish → runtime English)

| Anexo F | Runtime F1 |
|---------|------------|
| `perfil` / seguridad / naturalidad | `EvaluationProfile` / `safety` / `naturalness` |
| `modo_activo: supervisado\|autonomo` | `mode: supervised\|autonomous` (F1 always supervised) |
| `umbrales.seguridad_min` | `thresholds["safety"]` / `_safety_threshold` |
| `umbrales.naturalidad_min` | **not used in F1** (residual) |
| `accion: aprobar\|escalar\|regenerar` | `action: approve\|escalate` only |
| `razon` | `reason` |
| `restriccion_de_modo_aplicada` | optional `mode_restriction_applied` (not present) |

### F1-safe approach (locked recommendation for planner)

**Prefer subset alignment over full Anexo F.** Explicit plan residual for regenerate.

1. **Keep** `Decision.action: Literal["approve", "escalate"]`.  
2. **Document residual:** F.3 rule 2 (naturalness → regenerate) + F2+ actions (`send`, `consult_doctrine`, `regenerate`) out of F1. Under F.3 wording, when regenerate is not implemented, rule 2 **falls through to rule 3** → approve in supervised mode. Current code already matches that fall-through (no naturalness gate).  
3. **Keep** `risk == "alto"` → escalate as documented F1 extension (MVP §5.11 / §7.4), not pure F.3 — do not remove without an explicit product decision.  
4. **Optional tighten (in-scope if effort allows):**
   - Formal `DeciderInput` DTO **or** keep kwargs + document F.2 mapping (prefer minimal surface like other F1 DTOs only when it clarifies).
   - Add optional `mode_restriction_applied: str | None` on `Decision` (e.g. `"supervised_send_to_approve"` when approve path would have been raw send) for audit / F.2 completeness — **without** introducing a public `send` action.
   - Wire `Decider(thresholds=...)` from `SqlSystemConfigStore.get_eval_thresholds()` at composition (safety key only); still inject defaults if empty.
5. **Out of scope:** regenerate loop in Director, autonomous `send`, `consult_doctrine`, mean/aggregate score, hardcoding naturalness gate that escalates or regenerates, expanding orchestrator action branches.

---

## Consumers / Call Sites Map

### Production — Decider / Decision definition

| Location | Role |
|----------|------|
| `src/diana/cognitive/decider.py:10-52` | `Decider` matrix; safety + risk → escalate else approve |
| `src/diana/cognitive/models.py:210-218` | `Decision` F1: `action: approve\|escalate`, `reason`, `evaluation`, `draft_text` |
| `src/diana/cognitive/models.py:185-207` | `EvaluationProfile` 7D English + finite validators (Decider safety gate) |

### Production — sole pipeline call site

| Location | Behavior today | Notes for F.align |
|----------|----------------|-------------------|
| `src/diana/cognitive/director.py:162-171` | `base = decider.decide(evaluation, comprehension, mode="supervised")`; rebuild `Decision` with `draft_text=draft` | Keep Decider free of draft; Director remains draft attach point |
| `src/diana/composition.py:183` | `decider=Decider()` | Optional: pass thresholds from config store |
| `src/diana/config.py:41` | `global_mode: Literal["supervised"]` | Mode source of truth for app; not currently passed into Decider ctor from settings |

### Production — consume Decision (must stay approve|escalate)

| Location | Fields used | Notes |
|----------|-------------|-------|
| `src/diana/application/turn_orchestrator.py:206-221` | `decision.action` | approve → pending_approval; escalate → notify; else fail closed |
| `src/diana/application/admin_service.py:93-115` | `draft_text`, evaluation dump | Approval / escalation notify |
| `src/diana/application/ports.py:42,75` | DTO draft/eval for notify | No action enum change expected |
| `src/diana/infrastructure/db/repositories/approvals.py` | draft_text pass-through | Low |
| `src/diana/telegram/notifier.py:31` | draft in message body | Low |
| `src/diana/cognitive/ports.py:22-40` | TRACE key `"decision"` JSONB | Extra optional field on Decision is backward-compatible if optional |
| `src/diana/application/admin_service.py:38-43` | display-only eval summary | Never fed back into Decider |

### Production — thresholds infrastructure (related, optional)

| Location | Role |
|----------|------|
| `alembic/versions/001_f1_foundation.py:190` | seed `eval_thresholds = {"safety": 0.3}` |
| `src/diana/infrastructure/db/repositories/system_config.py:32-34` | `get_eval_thresholds()` |
| `src/diana/composition.py:139,183` | config_store created; **not** used to construct Decider |

### Tests — high impact

| File | Impact |
|------|--------|
| `tests/unit/cognitive/test_decider.py` | **HIGH** — matrix, thresholds, F1 action lock, no mean/LLM |
| `tests/unit/cognitive/test_models.py` | **HIGH** if Decision shape changes (literal, optional field) |
| `tests/unit/cognitive/test_director.py` | **MED–HIGH** — reasons `ok_for_human_review` / `safety_below_threshold` / `risk_high`; TAC-01 zero Decider LLM |
| `tests/unit/application/test_turn_orchestrator.py` | **MED** — approve/escalate branches; Decider() wiring in make_director helpers |
| `tests/unit/cognitive/test_import_purity.py` | **LOW** — must stay green |

### Tests — low impact (construct Decision / Decider fixtures)

| File | Notes |
|------|-------|
| `tests/unit/application/test_admin_service.py` | Decision fixtures |
| `tests/unit/application/test_admin_owner_escalate.py` | Decision fixtures |
| `tests/unit/telegram/test_callbacks.py` | Decision fixtures |
| `tests/unit/acceptance/test_tac_mvp_f1.py` | FakeDirector Decision approve |
| `tests/unit/cognitive/test_evaluation_profile_invariants.py` | Profile only; BR-09 |
| `tests/unit/test_composition_wiring.py` | May need update if Decider thresholds DI changes |

### Call-site line map (`decide`)

| Path | Lines | Note |
|------|-------|------|
| `decider.py` | 23-52 | definition |
| `director.py` | 164 | **sole production call site** |
| `test_decider.py` | many | unit matrix |
| `composition.py` | 183 | constructor only |
| `test_director.py` / `test_turn_orchestrator.py` | Decider(...) | indirect via pipeline |

---

## Risks

### Critical

1. **Expanding F1 public `Decision.action` to Anexo F / AGENTS full set**  
   - **Risk:** Adding `regenerate` / `send` / `consult_doctrine` without Director loop, Behavior, gray_zone, or orchestrator branches → runtime `ValueError("unexpected F1 action")` or silent wrong path; undoes prior pool locks.  
   - **Mitigation:** F1-compatible matrix only. Document regenerate as residual. Keep model literal + `test_decision_rejects_non_f1_actions` + orchestrator guard.

2. **Implementing naturalness → regenerate loop “because Anexo F says so”**  
   - **Risk:** Director non-determinism surface, extra LLM cost, conflicts with SPEC open decision #1 and MVP §13 (“dueña corrige en DM”).  
   - **Mitigation:** Explicit residual; F.3 already allows fall-through to rule 3 when regenerate not implemented.

### Medium

3. **Removing `risk_high` to match pure F.3 only**  
   - **Risk:** Behavior regression vs MVP design + director/decider tests; high-risk VIP turns could reach approval queue.  
   - **Mitigation:** Keep risk gate; document as F1 extension beyond pure Anexo F table.

4. **Wiring live `system_config` thresholds without tests**  
   - **Risk:** Bad JSON / missing keys / wrong key names (`seguridad_min` vs `safety`) change escalate rate in production.  
   - **Mitigation:** English keys only (`safety`); default 0.3; unit test custom + empty dict; composition test if wired. Do **not** load `naturalness` for action change in F1.

5. **Adding required `mode_restriction_applied` without migrating fixtures**  
   - **Risk:** Many tests construct `Decision(...)` with required fields only.  
   - **Mitigation:** Field optional default `None`; set only on supervised approve path if implemented.

### Low

6. **Spanish identifiers in code**  
   - **Risk:** Drift from L1 English convention used in all prior contracts.  
   - **Mitigation:** English runtime names; Spanish only in docs/comments mapping.

7. **Collapsing EvaluationProfile to a single score**  
   - **Risk:** BR-09 / REQ-COG-08 violation.  
   - **Mitigation:** Existing source/assert tests; never introduce mean/confidence.

8. **Decider reading draft text**  
   - **Risk:** F.4 / NFR-13 separation break.  
   - **Mitigation:** Keep draft attach in Director only.

---

## Affected Tests

### Primary (must pass for this slice)

```bash
# from repo root
pytest tests/unit/cognitive/test_decider.py -q
pytest tests/unit/cognitive/test_models.py -q -k Decision
pytest tests/unit/cognitive/test_director.py -q -k "escalate or approve or tac01 or safety or risk"
pytest tests/unit/cognitive/test_import_purity.py -q
pytest tests/unit/cognitive/test_evaluation_profile_invariants.py -q
```

### Integration / wiring (if composition thresholds or Decision field change)

```bash
pytest tests/unit/application/test_turn_orchestrator.py -q -k "approve or escalate or director"
pytest tests/unit/test_composition_wiring.py -q
pytest tests/unit/application/test_admin_service.py -q
pytest tests/unit/acceptance/test_tac_mvp_f1.py -q
```

### Full cognitive + application safety net

```bash
pytest tests/unit/cognitive/ tests/unit/application/test_turn_orchestrator.py -q
# optional full unit:
pytest tests/unit -q
```

### Gold assertions to preserve / add

| Assertion | Intent |
|-----------|--------|
| `action in ("approve", "escalate")` for all matrix cells | F1 lock |
| Reject `send` / `regenerate` / `consult_doctrine` on Decision | Model gate |
| `safety < threshold` → escalate before risk check | F.3 #1 order |
| `risk == "alto"` → escalate when safety OK | F1 extension |
| equal safety threshold → approve (`>=` boundary) | threshold edge |
| mode cannot unlock `send` | F.4 mode filter |
| no `mean(` / `overall_score` / LLM in decider source | BR-09 + TAC-01 |
| Director: 3 LLM calls only (analyst/generator/evaluator) | TAC-01 |
| Orchestrator: no Behavior on approve; escalate notifies | L2 supervised |

### New tests recommended if planner includes optional work

- Documented residual: naturalness low **still approve** (no regenerate) when safety OK and risk not alto.  
- If `mode_restriction_applied` added: set on approve path; null on escalate.  
- If composition wires thresholds: `Decider` receives safety from config store / empty → default 0.3.

---

## Files Map

### Edit (likely)

| File | Why |
|------|-----|
| `src/diana/cognitive/decider.py` | Docstring / optional input shaping; keep matrix; optional mode_restriction reason metadata |
| `src/diana/cognitive/models.py` | Optional `mode_restriction_applied`; **do not** expand action Literal |
| `tests/unit/cognitive/test_decider.py` | Lock F1-safe Anexo F subset + residual naturalness behavior |
| `tests/unit/cognitive/test_models.py` | Only if Decision fields change |
| `tests/unit/cognitive/test_director.py` | Only if reason / optional field / DI changes |

### Edit (optional — composition thresholds)

| File | Why |
|------|-----|
| `src/diana/composition.py` | `Decider(thresholds=await/sync load)` — note: build is sync today; may need sync read or ctor defaults only |
| `tests/unit/test_composition_wiring.py` | Assert thresholds DI if added |

### Create (optional)

| File | Why |
|------|-----|
| `.planning/quick/decider-contract/PLAN.md` | planner output |
| `.planning/quick/decider-contract/decisions.md` | lock F1 residual regenerate + risk extension |
| `docs/` comment only | F.2 Spanish→English map if documentador phase |

### No touch

| Area | Why |
|------|-----|
| Generator / Evaluator / Analyst / Planner / ContextBuilder | Already contracted; Decider consumes their outputs |
| BehaviorEngine / telegram send path | F1 never auto-sends from Decider |
| alembic migrations | seed already has `eval_thresholds.safety`; no schema change for optional Decision field (JSONB dump) |
| Learning / Staging | post-turn only |
| Full AGENTS.md product action set | Vision stays; F1 runtime restriction stays |
| Regeneración loop / gray_zone | F2+ residual |

---

## Systems sensibles

| System | Why sensitive | Decider impact |
|--------|---------------|-----------------|
| CognitiveDirector control flow | Must stay 100% deterministic | Decider must remain pure rules |
| Decision action vocabulary | Orchestrator + admin + models | F1 approve\|escalate only |
| EvaluationProfile 7D | BR-09 | Never mean/score collapse |
| Supervised mode | No VIP send without owner | Never return `send` |
| Approval queue integrity | Non-empty draft attached by Director | Decider does not invent draft |
| Module purity | cognitive ↛ telegram/behavior | Keep; thresholds via ctor injection only |

---

## DoD for downstream

### gsd-planner

- Scope: **decider-contract** only (Anexo F under F1 lock).  
- Explicit residual ticket text: “F.3 rule 2 naturalness→regenerate deferred; F1 fall-through = approve.”  
- Explicit non-goals: expand action set; Director regenerate loop; autonomous send; consult_doctrine.  
- Decide optional vs required: `mode_restriction_applied`, composition threshold wiring.  
- Effort target ~2–3; single PR size well under 400-line risk if residual is docs+tests only.

### executor

- TDD: fail tests for residual documentation behavior + any new field before code.  
- Preserve reason strings used by director tests **or** update both atomically.  
- English identifiers only.  
- No production code outside Files Map without re-impact.

### arch-enforcer

- [ ] Director still deterministic; Decider has no LLM.  
- [ ] `Decision.action` still exactly approve\|escalate.  
- [ ] No score collapse.  
- [ ] Decider does not import telegram/behavior/application.  
- [ ] Mode cannot produce send.  
- [ ] Risk-high escalate still present unless planner explicitly removed it (should not).

### test-guardian

- Run primary pytest commands above green.  
- Confirm no forbidden mocks (Decider needs none).  
- Confirm residual naturalness test if planned.  
- Full unit optional after green primary.

---

## Ready for chain

**Handoff → gsd-planner** with tight scope:

| Item | Value |
|------|-------|
| Slug | `decider-contract` |
| Source | `docs/contratos_restantes.md` Anexo F.1–F.5 |
| F1 matrix | safety &lt; umbral → escalate; risk alto → escalate; else approve (supervised) |
| Residual | naturalness → regenerate (F.3 #2); send/autonomous; consult_doctrine |
| Optional | `mode_restriction_applied`; wire `eval_thresholds.safety` at composition |
| Primary tests | `test_decider.py`, Decision tests in `test_models.py`, director escalate/approve/TAC-01 |
| Risk | low–medium if residual respected; **critical** if action set expanded |

**Analysis complete — no implementación.**
