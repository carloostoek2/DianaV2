# Impact Analysis: h6-template-gate

**Date:** 2026-07-27  
**Change:** Implement ANEXO-H H6 TemplateGate in CognitiveDirector (pre-pipeline), migrate J.4 `identidad_ia` out of ForbiddenKeywordsMiddleware into TemplateGate → `Decision.action=approve`, keep J.4 `pago_precio`/`compromiso_real` in middleware, synthetic evaluation (H4 pattern), persona JSON cleanup, H6.6 tests.  
**Analysis only** — no implementación  
**Scope source:** `.planning/quick/h6-template-gate/CLARIFY.md` (locked) + `docs/ANEXO-H.md` H6.1–H6.6  
**Scope validity:** **VALID** — single coherent pool item; do not re-partition unless hybrid IA+pago / keyword-coverage residuals explode mid-plan.

---

## Executive Summary

H6 adds a pure, deterministic **TemplateGate** (`cognitive/template_gate.py`) and hooks it at the top of `CognitiveDirector.handle_turn` **before** Analyst/Planner/Registry/Context/Generator/Evaluator/Decider. Two rules (order locked): **`deteccion_ia` first**, then **`saludo_constante`**. Matches return `Decision(action="approve", reason=plantilla_*, draft_text=template, evaluation=synthetic zeros)`. TurnOrchestrator’s existing approve branch is **not modified** — only verified compatible with `AdminService.send_draft_for_approval` (requires non-null `evaluation` and uses `draft_text` + `reason`).

The **behavioral product flip** is the migration of J.4 **`identidad_ia`**: today ForbiddenKeywordsMiddleware auto-**delivers** `IA_TEMPLATE` to the VIP then **escalates** (no owner draft queue). After H6, IA probes become supervised **approve** drafts (owner queue / `/traza`), with **zero LLM** and **no auto-deliver**. `pago_precio` and `compromiso_real` stay middleware silent-escalate. Persona cleanup removes `(ver J.2 / examples)` from `src/diana/config/persona_diana.json` `reglas_estilo`.

**Global risk: MEDIUM–HIGH** (not CRITICAL if hybrid/pago invariants and cognitive purity are planned carefully). Sensitive systems: Cognitive Core purity (must **not** import `diana.application`), one-turn invariant, Decider bypass only via pre-pipeline early exit (same spirit as H4), middleware security short-circuits for pago/compromiso, supervised approve never auto-delivers.

**Highest-leverage gotchas for planner:**
1. Cognitive import purity forbids importing `match_keywords` from `application.j4_triggers` — duplicate minimal matcher or extract neutral pure helper **outside** both forbidden directions.
2. Default Director test fixture text is `"hola Diana"` → will **false-fire** `saludo_constante` unless TemplateGate is optional/`None` in unit tests or fixtures change text.
3. J.4 IA keyword set is **much broader** than H6 annex triggers; hybrid IA+pago paths need an explicit middleware rule so pago is never lost.

---

## Consumers / Call Sites Map

### A. CognitiveDirector.handle_turn (integration surface)

| Location | Role |
|----------|------|
| `src/diana/cognitive/director.py:117–141` | Entry; currently `return await self._run_pipeline(turn)` only |
| `src/diana/cognitive/director.py:57–67` | `_early_exit_evaluation()` — **reuse for H6 synthetic eval** (CLARIFY locks this; ANEXO-H H6.4 showing `evaluation=None` is **stale / overridden**) |
| `src/diana/cognitive/director.py:155–171` | H4 early-exit post-Analyst (`pregunta_repetida`) — pattern reference, not template location |
| `src/diana/application/turn_orchestrator.py:43` | Protocol `DirectorPort.handle_turn` |
| `src/diana/application/turn_orchestrator.py:289` | Production call site after `begin_turn` + history append |
| `src/diana/composition.py:395–418` | Wires CognitiveDirector (must inject TemplateGate + rules) |
| `tests/unit/cognitive/test_director.py` | ~30+ `handle_turn` call sites; default `_turn(text="hola Diana")` |
| `tests/unit/cognitive/test_director_knowledge_augmenter.py:94` | handle_turn |
| `tests/unit/application/test_turn_orchestrator.py` | Fake directors implementing `handle_turn` |
| `tests/unit/acceptance/test_tac_mvp_f1.py` | Fake director |

**H6 integration point (planned):**

```text
handle_turn:
  try:
    rule = template_gate.match(turn.text)   # optional if gate is None
    if rule: return await _handle_template(turn, rule)
    return await _run_pipeline(turn)
  except: status FAILED; raise
```

### B. Decision model + Admin approve path (compatibility — no TO change)

| Location | Contract impact |
|----------|-----------------|
| `src/diana/cognitive/models.py:249–271` | `evaluation: EvaluationProfile` **required** (not Optional) |
| `src/diana/application/admin_service.py:43–50` | `_eval_summary` reads all 7 dims |
| `src/diana/application/admin_service.py:114–159` | `send_draft_for_approval` → `decision.evaluation.model_dump`, `draft_text`, `reason` |
| `src/diana/application/turn_orchestrator.py:342–349` | `action == "approve"` → `PENDING_APPROVAL` + `send_draft_for_approval`; **never** `behavior.deliver` |
| `src/diana/application/escalation_labels.py` | `tipo_from_reason` — `plantilla_*` reasons map to **semantica** default (OK for approve path; not escalate) |

**Compatibility verdict:** Synthetic zero `EvaluationProfile` + non-empty `draft_text` + `reason in {plantilla_saludo, plantilla_deteccion_ia}` works with current approve path without TurnOrchestrator edits. Owner will see `nat=0.00 …` in summary — reason string is source of truth (same as H4).

### C. J.4 identidad_ia / IA_TEMPLATE / middleware (migration surface)

| Location | Current behavior |
|----------|------------------|
| `src/diana/application/j4_triggers.py:18` | `IA_TEMPLATE = "jsjsj si y sólo vivo en tu mente 😏"` |
| `src/diana/application/j4_triggers.py:22–56` | Broad `IDENTIDAD_IA_KEYWORDS` (sos/eres, chatgpt, humano, robot, …) |
| `src/diana/application/j4_triggers.py:146–165` | `match_keywords` pure matcher |
| `src/diana/application/j4_triggers.py:168–214` | `classify_j4_text` priority: **identidad_ia → pago → compromiso** + hybrid `also_matched` |
| `src/diana/telegram/middlewares/forbidden.py:133–178` | On `identidad_ia`: `handle_deterministic_template_escalate` (deliver+escalate) or fail-closed escalate if no behavior |
| `src/diana/application/deterministic_escalate.py:89–188` | Template deliver then ESCALATED + owner notify |
| `src/diana/telegram/setup.py:100–107` | Forbidden MW wired with `behavior=behavior` for IA path |
| `src/diana/application/escalation_labels.py:16,26` | Labels for `identidad_ia` tipo (legacy escalate path) |

**H6 annex triggers (narrower than J.4):**  
`eres una ia`, `eres un bot`, `eres ia`, `hablo con una ia`, `hablo con un bot`, `eres real`  
**Missing vs live J.4:** `sos *`, `chatgpt`, `humano`, `robot`, `chatbot`, `eres una ai`, etc. → residual product coverage gap (locked by CLARIFY: do not expand beyond annex unless residual).

### D. Matcher / purity constraint

| Constraint | Evidence |
|------------|----------|
| Cognitive **must not** import `diana.application` | `tests/unit/cognitive/test_import_purity.py:10–19` (`FORBIDDEN_PREFIXES` includes `diana.application`) |
| AGENTS.md | Cognitive → Registry/LLM only; no telegram/behavior |
| CLARIFY assumption | Prefer pure match without Telegram coupling; extract neutral or **duplicate minimal** `_kw_hit` in template_gate |

**Recommended for planner (lowest risk):** implement `_kw_hit` / phrase-or-token logic **inside** `cognitive/template_gate.py` (duplicate of `match_keywords` semantics). Defer shared-module extract to residual (CLARIFY deferred).

### E. Composition / persona

| Location | Role |
|----------|------|
| `src/diana/composition.py:395–418` | Construct Director; add `template_gate=TemplateGate(rules=[deteccion_ia, saludo_constante])` (order: IA first) |
| `src/diana/config/persona_diana.json:10` | `"… (ver J.2 / examples)."` — **edit** (not yaml) |
| `src/diana/composition.py:405` | `style_rules=list(voz["reglas_estilo"])` — auto-picks cleaned JSON |

### F. Tests that must change / expand

| File | Why |
|------|-----|
| **NEW** `tests/unit/cognitive/test_template_gate.py` | Pure unit: match order, max_words, exact IA text, pool choice |
| **EDIT** `tests/unit/cognitive/test_director.py` | H6.6 cases + keep pipeline tests off saludo triggers; wire optional gate |
| **EDIT** `tests/unit/telegram/test_forbidden_mw.py` | `test_j4_ia_delivers_template_then_escalates` → **must invert**: IA no longer short-circuits; passes handler |
| **EDIT** `tests/unit/application/test_j4_triggers.py` | Remove or rewrite identidad_ia classify expectations if IA removed from classifier |
| **EDIT?** `tests/unit/application/test_deterministic_escalate.py` | Keep unit coverage of helper (still exists) OR mark dead-path residual if no production caller |
| **EDIT** `tests/unit/test_composition_wiring.py` | Assert TemplateGate wired on Director; `behavior=` on Forbidden may become optional residual |
| **REGRESSION** pago/compromiso forbidden tests | Must still escalate; zero Director |
| **GOLD** H6.6 five cases from annex + CLARify |

### G. Status transitions (minor)

Template path stores `decision` and returns without `ANALYZING` (pre-pipeline). H4 stores decision after Analyst. Orchestrator only requires a returned `Decision` then transitions to `PENDING_APPROVAL`. Status sink intermediate steps not required for approve path. **Residual only if** trace UI assumes ANALYZING always ran.

---

## Risks

### Critical

| ID | Risk | Mitigation |
|----|------|------------|
| **C1** | **Cognitive purity break** if `template_gate` imports `diana.application.j4_triggers.match_keywords` | Implement local matcher in `cognitive/template_gate.py`; guard with existing `test_import_purity.py` |
| **C2** | **Hybrid IA+pago security regression** if middleware simply “pass all identidad_ia” and classify still prefers IA: text like `eres un bot y cuánto cuesta?` would leave middleware without pago escalate and become TemplateGate **approve** (VIP draft) instead of payment short-circuit | Planner must choose explicit policy: **(Recommended)** remove `identidad_ia` from `classify_j4_text` so co-hit pago/compromiso still escalates; pure IA falls through to Director. Alternative: middleware branch — if IA + `also_matched` pago/compromiso → escalate pago (no deliver); if pure IA → pass |
| **C3** | **Mass Director unit test breakage** via default text `"hola Diana"` matching `saludo_constante` (`max_words=4`, trigger `hola`) | Make `template_gate: TemplateGate \| None = None` on Director (like `repetition_guard`); production composition always injects; unit tests inject only for H6 cases. Optionally change fixture text to non-greeting later |

### Medium

| ID | Risk | Mitigation |
|----|------|------------|
| **M1** | **Keyword coverage shrink** vs live J.4 (`sos un bot`, `chatgpt`, `humano`, …) → full LLM pipeline for former short-circuits | Accept per CLARIFY annex scope; document residual “expand deteccion_ia keywords to former J.4 set” |
| **M2** | **Product behavior flip:** VIP currently receives IA reply immediately; after H6 waits for owner approve | Intentional (F.4 / supervised); owner tests must assert **no** `behavior.deliver` on template path |
| **M3** | Dead code: `handle_deterministic_template_escalate` + Forbidden `behavior` inject only for IA | Keep helpers + tests unless residual cleanup; or stop passing `behavior` to Forbidden MW if unused (update composition wiring test) |
| **M4** | Spec/code drift: ANEXO-H H6.4 still shows `evaluation=None` | Implementation follows CLARIFY + live Decision model; optional docs note residual |
| **M5** | Zero evaluation dims in owner UI look like “failed eval” | Reason `plantilla_*` is truth; optional residual: prettier owner summary for synthetic |
| **M6** | Rule order bugs (`saludo` before `deteccion_ia`) | Lock rule list order in composition + unit test mixed short text e.g. `"hola eres ia"` → deteccion_ia |

### Low

| ID | Risk | Mitigation |
|----|------|------------|
| **L1** | `escalation_labels` still lists `identidad_ia` | Harmless; keep for historical escalations in DB |
| **L2** | Persona JSON string-only cleanup | Single-line edit; composition already loads rules |
| **L3** | RNG in saludo pool flaky tests | Inject fixed `rng` / `random.Random(0)` in tests; assert `draft_text in response_pool` |
| **L4** | No feature flag (always-on core) | Per CLARIFY out-of-scope; document as intentional |

---

## Affected Tests

### Exact commands (primary)

```bash
# H6 pure gate + Director integration
pytest -q tests/unit/cognitive/test_template_gate.py tests/unit/cognitive/test_director.py -v

# Cognitive purity (must stay green)
pytest -q tests/unit/cognitive/test_import_purity.py -v

# J.4 / middleware migration + escalate helpers
pytest -q tests/unit/application/test_j4_triggers.py tests/unit/application/test_deterministic_escalate.py tests/unit/telegram/test_forbidden_mw.py -v

# Approve path compatibility (no TO edits; regression)
pytest -q tests/unit/application/test_turn_orchestrator.py tests/unit/application/test_admin_service.py -k "approve or draft" -v

# Composition wiring
pytest -q tests/unit/test_composition_wiring.py -v

# Acceptance TAC / middleware order
pytest -q tests/unit/acceptance/test_tac_mvp_f1.py -v

# Full cognitive + telegram unit safety net
pytest -q tests/unit/cognitive tests/unit/telegram tests/unit/application/test_j4_triggers.py tests/unit/application/test_deterministic_escalate.py tests/unit/test_composition_wiring.py -v
```

### Full unit (pre-merge)

```bash
pytest -q tests/unit -v
```

### H6.6 acceptance matrix (must map 1:1 to tests)

| # | Case | Assert |
|---|------|--------|
| 1 | `"Hola"` | `reason==plantilla_saludo`, draft ∈ pool, Analyst/Gen/Eval `assert_not_called` |
| 2 | `"Hola, tengo una pregunta sobre el contenido"` (5+ words) | no template; full pipeline |
| 3 | `"eres una ia?"` | `draft_text == "jsjsj si y sólo vivo en tu mente 😏"` exact |
| 4 | Template Decision | approve path → pending approval / draft notify (unit-level via orch/admin or director+store); **no auto-deliver** |
| 5 | persona JSON | `reglas_estilo` line lacks `(ver J.2 / examples)` |

### Extra regression (CLARIFY test-guardian)

| Case | Assert |
|------|--------|
| Middleware pago | still silent escalate, 0 Director |
| Middleware compromiso | still silent escalate |
| Middleware IA (e.g. `sos un bot?` / `eres una ia?`) | **no** short-circuit; handler awaited (Director path) |
| Mixed short `"hola eres una ia"` | reason `plantilla_deteccion_ia` not saludo |
| Cognitive purity | no `diana.application` / telegram / behavior imports |

---

## Files Map

### Edit

| Path | Change |
|------|--------|
| `src/diana/cognitive/director.py` | Inject optional TemplateGate; pre-pipeline match; `_handle_template` with synthetic eval + store decision |
| `src/diana/composition.py` | Build rules + TemplateGate; pass into Director |
| `src/diana/application/j4_triggers.py` | Remove or neuter `identidad_ia` classification path (keep `match_keywords`, pago, compromiso; decide fate of `IA_TEMPLATE` / `IDENTIDAD_IA_KEYWORDS`) |
| `src/diana/telegram/middlewares/forbidden.py` | Drop identidad_ia deliver+escalate branch; keep pago/compromiso/forbidden |
| `src/diana/config/persona_diana.json` | Remove `(ver J.2 / examples)` from reglas_estilo |
| `tests/unit/cognitive/test_director.py` | H6.6 + fixture/gate strategy |
| `tests/unit/telegram/test_forbidden_mw.py` | Invert IA short-circuit test; keep pago/forbidden |
| `tests/unit/application/test_j4_triggers.py` | Align with IA migration |
| `tests/unit/test_composition_wiring.py` | TemplateGate wired; Forbidden behavior optional residual |

### Create

| Path | Change |
|------|--------|
| `src/diana/cognitive/template_gate.py` | `TemplateRule`, `TemplateGate.match/render`, local `_kw_hit` |
| `tests/unit/cognitive/test_template_gate.py` | Pure unit coverage |

### Edit (likely residual / optional this item)

| Path | Notes |
|------|-------|
| `src/diana/application/deterministic_escalate.py` | Keep for now (pago uses other helper); template helper may become unused |
| `src/diana/telegram/setup.py` | `behavior=` on Forbidden only if still needed |
| `docs/ANEXO-H.md` | Fix `evaluation=None` vs synthetic (docs residual) |
| `src/diana/application/escalation_labels.py` | Keep identidad_ia labels for historical tipos |

### No touch

| Path | Why |
|------|-----|
| `src/diana/application/turn_orchestrator.py` | Approve path already correct; verify only |
| `src/diana/cognitive/decider.py` | Templates bypass Decider |
| `src/diana/behavior/**` | No template deliver from cognitive |
| `src/diana/learning/**` | Post-turn only |
| `src/diana/application/turn_coordinator.py` | One-turn invariant; no dual escalate+approve |
| Alembic / DB schema | No persistence shape change |
| J.4 pago/compromiso keyword lists (behavior) | Explicit non-goal (except if classify refactor touches structure carefully) |

---

## Architecture invariants checklist (arch-enforcer DoD)

- [ ] Cognitive pure: no telegram/behavior/application imports from new/edited cognitive files  
- [ ] Director remains 100% deterministic (TemplateGate has no LLM)  
- [ ] Templates do not call Decider (pre-pipeline OK, same class of early-exit as H4)  
- [ ] Learning not in template path  
- [ ] One turn per message (no parallel escalate+approve)  
- [ ] Supervised template → approve only (never `send`, never Behavior from Director)  
- [ ] Middleware still short-circuits pago/compromiso/forbidden  
- [ ] IA no longer auto-delivers from middleware  

---

## Ready for chain

### Handoff → gsd-planner

**Scope (tight):**

1. Create pure `cognitive/template_gate.py` (TemplateRule + TemplateGate + local keyword hit).  
2. Rules factory: **`deteccion_ia` then `saludo_constante`** (annex patterns + exact IA response string).  
3. Wire optional TemplateGate into `CognitiveDirector.handle_turn` pre-pipeline; `_handle_template` with `_early_exit_evaluation()`, `action=approve`, store decision.  
4. Composition injects gate with both rules.  
5. Migrate J.4: remove middleware `identidad_ia` short-circuit; adjust `classify_j4_text` so **pago/compromiso still win on hybrid** (recommended).  
6. Persona JSON cleanup H6.6.5.  
7. Tests: new template_gate unit + director H6.6 + update forbidden/j4/composition; regression pago/compromiso.  
8. **Do not** edit TurnOrchestrator; **do not** Optional evaluation.

**Suggested implementation order (TDD):**  
template_gate tests → template_gate impl → director template tests (gate injected) → director impl → j4/middleware tests red → migrate j4/middleware → composition wire → persona JSON → full suite.

**DoD for executor**

- All H6.6 + hybrid/pago regression green.  
- `test_import_purity` green.  
- No production auto-deliver of IA template from middleware.  
- `"Hola"` approve plantilla; long hola → pipeline; IA exact string; persona line cleaned.

**DoD for arch-enforcer**

- Purity + Director determinism + no dual-turn + Decider untouched + flags N/A.

**DoD for test-guardian**

- LLM mocks `assert_not_called` on template path.  
- Middleware IA pass-through + pago/compromiso still block.  
- No mock of TemplateGate internals in Director tests beyond RNG if needed; real TemplateGate preferred.

**Estimated blast radius:** ~6–8 production files + ~5–7 test files; **no DB migration**. Review workload: likely **under 400 LOC** if dead-code cleanup deferred.

---

## Open residuals (explicit, non-blocking for PLAN)

1. Expand `deteccion_ia` triggers to former `IDENTIDAD_IA_KEYWORDS` (voseo/chatgpt/humano).  
2. Shared pure matcher module (cognitive ↔ application).  
3. Delete or quarantine `handle_deterministic_template_escalate` if unused.  
4. Docs ANEXO-H: synthetic evaluation vs `None`.  
5. Owner UI: hide zero synthetic scores for `plantilla_*`.  
6. Trace status: optional ANALYZING skip documentation.  
7. Fixture default `_turn` text hygiene across suite.
